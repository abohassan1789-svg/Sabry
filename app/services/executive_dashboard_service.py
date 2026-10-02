"""Read-only data service for the new Executive Dashboard (الداشبورد التنفيذية).

One screen, one service. The dashboard is driven by a single **date range**
(from / to); the three catalog counts (customers, suppliers, products) are always
full totals and deliberately ignore the range, exactly like the existing sales
dashboard. Everything else — the receipt-vouchers total, the monthly
sales/purchases series, the top-5 customers and suppliers, the production totals
and the loading-voucher highlights — honours the range.

Every method is strictly **read-only** (SELECT only) and fully guarded: a failing
query returns a safe empty/zero default so the dashboard can never crash the
shell. The data is assembled by :meth:`ExecutiveDashboardService.load`, which
returns one plain ``dict`` payload the UI renders directly (no Qt here, no SQL in
the UI).

Data sources (existing tables, unchanged)
-----------------------------------------
* ``customers`` / ``suppliers`` / ``products`` — catalog counts.
* ``sales_invoices`` — monthly sales, top customers, sales total (mirrors the
  existing ``CrmDashboardService`` basis: ``total_including_vat`` on
  ``issue_datetime``).
* ``purchase_invoices`` + ``purchase_invoice_lines`` — monthly purchases, top
  suppliers, purchases total (approved invoices only, ``count_price_total`` —
  the same basis as تقرير المشتريات).
* ``receipt_vouchers`` — إجمالي سندات القبض (``amount`` on ``voucher_date``).
* ``production_orders`` + ``production_order_lines`` — produced quantity, top
  produced item, and the raw-material cost (actual, falling back to expected,
  × the BOM price snapshot).
* ``loading_vouchers`` — heaviest vehicle after loading and the vehicle with the
  most vouchers. The weight columns are free-text ``varchar``, so their numeric
  value is parsed in Python (never cast in SQL).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from app.database.db import Database

logger = logging.getLogger(__name__)

UNSPECIFIED = "غير محدد"
DASH = "—"

# Arabic month names, indexed 0..11 (matches int(MM) - 1).
_AR_MONTHS = (
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
)

# Most recent months kept for the sales/purchases chart (avoids a crowded axis on
# very wide ranges; a default ~6-month range shows every month).
MAX_MONTHS = 8
TOP_LIMIT = 5

# Approved-purchases only, mirroring the purchase report.
PURCHASE_STATUS_APPROVED = "approved"

# Pull the first numeric run out of a free-text weight ("32,400 كجم" -> 32400.0).
_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


class ExecutiveDashboardService:
    """Aggregate every value the executive dashboard shows, for one date range."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    # ======================================================================
    # Public entry point — the whole dashboard payload in one call.
    # ======================================================================
    def load(self, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
        date_from = self._clean_date(date_from)
        date_to = self._clean_date(date_to)

        monthly = self._monthly_sales_purchases(date_from, date_to)
        total_sales = sum(m["sales"] for m in monthly)
        total_purchases = sum(m["purchases"] for m in monthly)

        return {
            "counts": {
                "customers": self._count("customers"),
                "suppliers": self._count("suppliers"),
                "products": self._count("products"),
            },
            "receipt_total": self._receipt_total(date_from, date_to),
            "monthly": monthly,
            "top_customers": self._top_customers(date_from, date_to),
            "top_suppliers": self._top_suppliers(date_from, date_to),
            "production": self._production_summary(date_from, date_to),
            "loading": self._loading_summary(date_from, date_to),
            "totals": {"sales": total_sales, "purchases": total_purchases},
            "range": {"date_from": date_from, "date_to": date_to},
        }

    # ======================================================================
    # Catalog counts (full totals — the range is intentionally ignored).
    # ======================================================================
    def _count(self, table: str) -> int:
        try:
            row = self.db.fetch_one(f"SELECT COUNT(*) AS c FROM {table}")
            return int(row["c"]) if row and row.get("c") is not None else 0
        except Exception:  # noqa: BLE001 - the dashboard must never crash
            logger.exception("Executive dashboard: failed to count %s", table)
            return 0

    # ======================================================================
    # إجمالي سندات القبض (receipt vouchers, by voucher_date).
    # ======================================================================
    def _receipt_total(self, date_from: str | None, date_to: str | None) -> float:
        conds, params = self._between("rv.voucher_date", date_from, date_to)
        sql = (
            "SELECT COALESCE(SUM(rv.amount), 0) AS s "
            f"FROM receipt_vouchers rv{self._where(conds)}"
        )
        return self._scalar(sql, params)

    # ======================================================================
    # Monthly sales & purchases (merged into one chronological series).
    # ======================================================================
    def _monthly_sales_purchases(
        self, date_from: str | None, date_to: str | None
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, float]] = {}

        # Sales — total_including_vat on issue_datetime (mirrors CrmDashboardService).
        s_conds, s_params = self._between_ts("si.issue_datetime", date_from, date_to)
        s_sql = (
            "SELECT to_char(date_trunc('month', si.issue_datetime), 'YYYY-MM') AS ym, "
            "COALESCE(SUM(si.total_including_vat), 0) AS total "
            f"FROM sales_invoices si{self._where(s_conds)} "
            "GROUP BY 1"
        )
        for row in self._rows(s_sql, s_params):
            ym = row.get("ym")
            if ym:
                buckets.setdefault(ym, {"sales": 0.0, "purchases": 0.0})["sales"] = float(row.get("total") or 0)

        # Purchases — approved invoices only, count_price_total on the lines.
        p_conds = ["pi.document_status = %s"]
        p_params: list[Any] = [PURCHASE_STATUS_APPROVED]
        extra_conds, extra_params = self._between("pi.issue_datetime::date", date_from, date_to)
        p_conds += extra_conds
        p_params += extra_params
        p_sql = (
            "SELECT to_char(date_trunc('month', pi.issue_datetime), 'YYYY-MM') AS ym, "
            "COALESCE(SUM(l.count_price_total), 0) AS total "
            "FROM purchase_invoices pi "
            "JOIN purchase_invoice_lines l ON l.invoice_id = pi.id "
            f"{self._where(p_conds)} GROUP BY 1"
        )
        for row in self._rows(p_sql, p_params):
            ym = row.get("ym")
            if ym:
                buckets.setdefault(ym, {"sales": 0.0, "purchases": 0.0})["purchases"] = float(row.get("total") or 0)

        ordered = sorted(buckets.items())          # chronological by 'YYYY-MM'
        ordered = ordered[-MAX_MONTHS:]            # keep the most recent months
        return [
            {"ym": ym, "label": self._month_label(ym),
             "sales": vals["sales"], "purchases": vals["purchases"]}
            for ym, vals in ordered
        ]

    # ======================================================================
    # Top 5 customers (sales) / top 5 suppliers (purchases).
    # ======================================================================
    def _top_customers(self, date_from: str | None, date_to: str | None) -> list[dict[str, Any]]:
        conds, params = self._between_ts("si.issue_datetime", date_from, date_to)
        sql = (
            f"SELECT COALESCE(c.customer_name, %s) AS name, "
            "COALESCE(SUM(si.total_including_vat), 0) AS total "
            "FROM sales_invoices si "
            "LEFT JOIN customers c ON c.customer_id = si.customer_id "
            f"{self._where(conds)} "
            "GROUP BY 1 ORDER BY total DESC, name "
            f"LIMIT {TOP_LIMIT}"
        )
        return self._named_totals(sql, [UNSPECIFIED, *params])

    def _top_suppliers(self, date_from: str | None, date_to: str | None) -> list[dict[str, Any]]:
        conds = ["pi.document_status = %s"]
        params: list[Any] = [PURCHASE_STATUS_APPROVED]
        extra_conds, extra_params = self._between("pi.issue_datetime::date", date_from, date_to)
        conds += extra_conds
        params += extra_params
        sql = (
            "SELECT COALESCE(NULLIF(TRIM(pi.supplier_name_snapshot), ''), s.supplier_name, %s) AS name, "
            "COALESCE(SUM(l.count_price_total), 0) AS total "
            "FROM purchase_invoices pi "
            "JOIN purchase_invoice_lines l ON l.invoice_id = pi.id "
            "LEFT JOIN suppliers s ON s.supplier_id = pi.supplier_id "
            f"{self._where(conds)} "
            "GROUP BY 1 ORDER BY total DESC, name "
            f"LIMIT {TOP_LIMIT}"
        )
        return self._named_totals(sql, [UNSPECIFIED, *params])

    def _named_totals(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self._rows(sql, params):
            value = float(row.get("total") or 0)
            if value <= 0:
                continue
            out.append({"name": (row.get("name") or UNSPECIFIED).strip() or UNSPECIFIED, "value": value})
        return out

    # ======================================================================
    # أوامر الإنتاج: produced quantity, top produced item, raw-material cost.
    # ======================================================================
    def _production_summary(self, date_from: str | None, date_to: str | None) -> dict[str, Any]:
        conds, params = self._between("po.order_date", date_from, date_to)
        where = self._where(conds)

        produced = self._scalar(
            f"SELECT COALESCE(SUM(po.production_quantity), 0) AS s FROM production_orders po{where}",
            params,
        )

        top_name, top_qty = DASH, 0.0
        top_row = self._rows(
            "SELECT po.product_name_snapshot AS name, "
            "COALESCE(SUM(po.production_quantity), 0) AS q "
            f"FROM production_orders po{where} "
            "GROUP BY po.product_name_snapshot ORDER BY q DESC, name LIMIT 1",
            params,
        )
        if top_row:
            top_name = (top_row[0].get("name") or UNSPECIFIED).strip() or UNSPECIFIED
            top_qty = float(top_row[0].get("q") or 0)

        # Raw-material cost: actual (falling back to expected) × the BOM price snapshot.
        cost = self._scalar(
            "SELECT COALESCE(SUM("
            "  COALESCE(NULLIF(l.actual_quantity, 0), l.expected_quantity, 0) "
            "  * COALESCE(l.bom_price_snapshot, 0)), 0) AS s "
            "FROM production_order_lines l "
            "JOIN production_orders po ON po.id = l.production_order_id"
            f"{where}",
            params,
        )

        return {
            "produced_qty": produced,
            "top_item_name": top_name,
            "top_item_qty": top_qty,
            "raw_cost": cost,
        }

    # ======================================================================
    # سندات التحميل: heaviest vehicle after loading + vehicle with most vouchers.
    #  Weight columns are free text -> parse the numeric value in Python.
    # ======================================================================
    def _loading_summary(self, date_from: str | None, date_to: str | None) -> dict[str, Any]:
        conds, params = self._between("voucher_date", date_from, date_to)
        rows = self._rows(
            "SELECT vehicle_number, weight_before_loading, weight_after_loading "
            f"FROM loading_vouchers{self._where(conds)}",
            params,
        )

        heaviest_vehicle, heaviest_value, heaviest_kind = DASH, 0.0, "after"
        counter: Counter[str] = Counter()
        for row in rows:
            vehicle = (row.get("vehicle_number") or "").strip()
            if not vehicle:
                continue
            counter[vehicle] += 1
            after = self._parse_weight(row.get("weight_after_loading"))
            before = self._parse_weight(row.get("weight_before_loading"))
            value, kind = (after, "after") if after >= before else (before, "before")
            if value > heaviest_value:
                heaviest_value, heaviest_vehicle, heaviest_kind = value, vehicle, kind

        count_vehicle, count_value = DASH, 0
        if counter:
            count_vehicle, count_value = counter.most_common(1)[0]

        return {
            "weight_vehicle": heaviest_vehicle,
            "weight_value": heaviest_value,
            "weight_kind": heaviest_kind,   # 'after' | 'before'
            "count_vehicle": count_vehicle,
            "count_value": int(count_value),
        }

    # ======================================================================
    # Low-level query helpers (all guarded — never raise to the UI).
    # ======================================================================
    def _scalar(self, sql: str, params: list[Any] | None = None) -> float:
        try:
            row = self.db.fetch_one(sql, params or [])
            return float(row["s"]) if row and row.get("s") is not None else 0.0
        except Exception:  # noqa: BLE001
            logger.exception("Executive dashboard: scalar query failed")
            return 0.0

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        try:
            return list(self.db.fetch_all(sql, params or []))
        except Exception:  # noqa: BLE001
            logger.exception("Executive dashboard: rows query failed")
            return []

    # --- WHERE / range builders --------------------------------------------
    @staticmethod
    def _where(conditions: list[str]) -> str:
        return (" WHERE " + " AND ".join(conditions)) if conditions else ""

    @staticmethod
    def _between(column: str, date_from: str | None, date_to: str | None) -> tuple[list[str], list[Any]]:
        """Inclusive range on a DATE column."""
        conds: list[str] = []
        params: list[Any] = []
        if date_from:
            conds.append(f"{column} >= %s::date")
            params.append(date_from)
        if date_to:
            conds.append(f"{column} <= %s::date")
            params.append(date_to)
        return conds, params

    @staticmethod
    def _between_ts(column: str, date_from: str | None, date_to: str | None) -> tuple[list[str], list[Any]]:
        """Inclusive range on a TIMESTAMP column (whole end day included)."""
        conds: list[str] = []
        params: list[Any] = []
        if date_from:
            conds.append(f"{column} >= %s::date")
            params.append(date_from)
        if date_to:
            conds.append(f"{column} < (%s::date + INTERVAL '1 day')")
            params.append(date_to)
        return conds, params

    # --- parsing / formatting ----------------------------------------------
    @staticmethod
    def _parse_weight(value: Any) -> float:
        if value is None:
            return 0.0
        match = _NUM_RE.search(str(value))
        if not match:
            return 0.0
        try:
            return float(match.group(0).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _month_label(ym: str) -> str:
        try:
            year, month = ym.split("-")
            name = _AR_MONTHS[int(month) - 1]
            return f"{name} {year[2:]}"
        except (ValueError, IndexError):
            return ym

    @staticmethod
    def _clean_date(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


__all__ = ["ExecutiveDashboardService"]
