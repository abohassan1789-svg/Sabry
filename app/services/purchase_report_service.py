"""Business logic for the Purchase report (تقرير المشتريات).

The UI calls only this service; this service calls only the repository. No SQL
and no Qt widgets live here — just the row mapping, the Arabic labels, the
fixed-decimal money / trimmed-quantity formatting, the dashboard KPIs and the two
pie/donut datasets, plus the input validation.

The report is strictly **read-only**: opening or refreshing it performs SELECTs
only. It lists one row per approved purchase-invoice line and derives four
dashboard cards plus two donut charts (أعلى ٥ موردين + توزيع طرق الدفع) from
those same rows in Python — a single database round-trip for the whole screen.

Money / aggregation basis
-------------------------
The purchase screen no longer captures weight, so each line has a single money
total: ``count_price_total`` (الكمية × السعر) — the invoice's headline
"إجمالي الفاتورة". It is summed for the إجمالي المشتريات card, the table's
الإجمالي column, and both donut charts (أكبر ٥ موردين + توزيع طرق الدفع), with
each label saying so.

Money and quantity are handled with :class:`decimal.Decimal` throughout (never
float), matching the ``numeric`` purchase-line columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.repositories.purchase_report_repository import (
    DEFAULT_PICKER_LIMIT,
    PurchaseReportFilters,
    PurchaseReportRepository,
)

# numeric(18,2) money, numeric(18,6) quantity.
_MONEY_QUANT = Decimal("0.01")
_ZERO = Decimal("0.00")

# Currency shown next to money values (matches the sales report / SAR app).
CURRENCY_LABEL = "ر.س"

# Payment-type codes (mirror purchase_invoices.payment_type) + their Arabic
# labels, used by the طريقة الدفع filter and the payment-distribution donut.
PAYMENT_CASH = "cash"
PAYMENT_CREDIT = "credit"
PAYMENT_LABEL_CASH = "نقدي"
PAYMENT_LABEL_CREDIT = "آجل"
PAYMENT_LABEL_UNKNOWN = "غير محدد"

# Number of suppliers shown in the "أعلى الموردين" donut.
TOP_SUPPLIERS_COUNT = 5

EMPTY_MESSAGE = "لا توجد مشتريات خلال الفترة/الفلاتر المحددة"


class PurchaseReportValidationError(Exception):
    """Raised for invalid filters. ``message`` is a ready-to-show Arabic string."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ReportColumn:
    """Lightweight column descriptor reused by the UI and later exporters."""

    key: str
    label: str


@dataclass(frozen=True)
class PurchaseReportRequest:
    date_from: str | None = None
    date_to: str | None = None
    supplier_name: str | None = None
    item_name: str | None = None
    payment_type: str | None = None


@dataclass(frozen=True)
class PurchaseReportResult:
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]           # numeric rows (Decimal) for totals/tests
    export_rows: list[dict[str, Any]]    # formatted strings keyed by column.key
    summary: dict[str, Any]              # KPIs (total + invoice/line counts + top supplier)
    top_suppliers: list[dict[str, Any]]  # donut A data (label + value + share%)
    payment_breakdown: list[dict[str, Any]]  # donut B data (نقدي / آجل shares)
    is_empty: bool


# Visible columns, in the exact required order — matching the simplified purchase
# invoice (اسم الصنف / الوحدة / الكمية / السعر / الإجمالي). The UI renders RTL, so
# the first column (التاريخ) shows on the right.
REPORT_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("issue_date", "التاريخ"),
    ReportColumn("invoice_number", "رقم الفاتورة"),
    ReportColumn("supplier_name", "اسم المورد"),
    ReportColumn("item_name", "اسم الصنف"),
    ReportColumn("unit", "الوحدة"),
    ReportColumn("item_count", "الكمية"),
    ReportColumn("unit_price", "السعر"),
    ReportColumn("count_price_total", "الإجمالي"),
)


class PurchaseReportService:
    """Build the read-only purchase report + its KPIs and two charts."""

    def __init__(self, repository: PurchaseReportRepository | None = None) -> None:
        self.repository = repository or PurchaseReportRepository()
        self.columns = list(REPORT_COLUMNS)

    # --- selectors ----------------------------------------------------------
    def company_letterhead(self) -> dict[str, Any] | None:
        """The first registered company, for the printable letterhead. Never raises."""
        try:
            return self.repository.fetch_company_letterhead()
        except Exception:  # noqa: BLE001
            return None

    # --- public API ---------------------------------------------------------
    def fetch_report(self, request: PurchaseReportRequest) -> PurchaseReportResult:
        date_from, date_to = self._validate_dates(request.date_from, request.date_to)

        filters = PurchaseReportFilters(
            date_from=date_from,
            date_to=date_to,
            supplier_name=self._clean(request.supplier_name),
            item_name=self._clean(request.item_name),
            payment_type=self._clean(request.payment_type),
        )
        raw_rows = self.repository.fetch_lines(filters)

        rows: list[dict[str, Any]] = []
        total_count_price = _ZERO
        invoice_numbers: set[str] = set()
        # supplier_id -> {"name", "total"} ranked by count_price_total
        supplier_totals: dict[Any, dict[str, Any]] = {}
        # payment label -> summed count_price_total
        payment_totals: dict[str, Decimal] = {}

        for raw in raw_rows:
            item_count = self._qty(raw.get("item_count"))
            unit_price = self._money(raw.get("unit_price"))
            count_price = self._money(raw.get("count_price_total"))

            total_count_price += count_price

            number = str(raw.get("invoice_number") or "")
            if number:
                invoice_numbers.add(number)

            sup_key = raw.get("supplier_id")
            sup_name = (raw.get("supplier_name") or "").strip() or "غير محدد"
            bucket = supplier_totals.setdefault(
                sup_key, {"name": sup_name, "total": _ZERO}
            )
            bucket["total"] += count_price
            if bucket["name"] == "غير محدد" and sup_name != "غير محدد":
                bucket["name"] = sup_name

            pay = self._payment_label(raw.get("payment_type"))
            payment_totals[pay] = payment_totals.get(pay, _ZERO) + count_price

            rows.append(
                {
                    "issue_date": self._format_date(raw.get("issue_date")),
                    "invoice_number": number,
                    "supplier_name": sup_name,
                    "item_name": (raw.get("item_name") or "").strip() or "غير محدد",
                    "unit": (raw.get("unit") or "").strip(),
                    "item_count": item_count,
                    "unit_price": unit_price,
                    "count_price_total": count_price,
                }
            )

        export_rows = [self._export_row(row) for row in rows]
        summary = self._build_summary(
            total_count_price, len(invoice_numbers), len(rows), supplier_totals,
        )
        top_suppliers = self._build_top_suppliers(supplier_totals, total_count_price)
        payment_breakdown = self._build_payment_breakdown(payment_totals, total_count_price)

        return PurchaseReportResult(
            columns=self.columns,
            rows=rows,
            export_rows=export_rows,
            summary=summary,
            top_suppliers=top_suppliers,
            payment_breakdown=payment_breakdown,
            is_empty=not rows,
        )

    # --- pickers ------------------------------------------------------------
    def search_suppliers(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        try:
            return list(self.repository.search_suppliers(keyword, limit))
        except Exception:  # noqa: BLE001 - a picker must never crash the screen
            return []

    def search_items(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        try:
            return list(self.repository.search_item_names(keyword, limit))
        except Exception:  # noqa: BLE001
            return []

    # --- KPI + chart builders ----------------------------------------------
    def _build_summary(
        self,
        total_count_price: Decimal,
        invoice_count: int,
        line_count: int,
        supplier_totals: dict[Any, dict[str, Any]],
    ) -> dict[str, Any]:
        top_supplier_name = ""
        top_supplier_value = _ZERO
        for bucket in supplier_totals.values():
            if bucket["total"] > top_supplier_value:
                top_supplier_value = bucket["total"]
                top_supplier_name = bucket["name"]

        return {
            "total_count_price": total_count_price,
            "total_count_price_label": self._money_text(total_count_price),
            "invoice_count": invoice_count,
            "invoice_count_label": f"{invoice_count:,}",
            "line_count": line_count,
            "line_count_label": f"{line_count:,}",
            "top_supplier_name": top_supplier_name or "—",
            "top_supplier_value": top_supplier_value,
            "top_supplier_value_label": self._money_text(top_supplier_value),
        }

    def _build_top_suppliers(
        self, supplier_totals: dict[Any, dict[str, Any]], total: Decimal
    ) -> list[dict[str, Any]]:
        ranked = sorted(
            supplier_totals.values(), key=lambda b: (b["total"], b["name"]), reverse=True
        )[:TOP_SUPPLIERS_COUNT]
        return [self._chart_item(b["name"], b["total"], total) for b in ranked]

    def _build_payment_breakdown(
        self, payment_totals: dict[str, Decimal], total: Decimal
    ) -> list[dict[str, Any]]:
        # Stable, meaningful order: نقدي, آجل, then anything else (غير محدد).
        order = [PAYMENT_LABEL_CASH, PAYMENT_LABEL_CREDIT]
        labels = order + [k for k in payment_totals if k not in order]
        return [
            self._chart_item(label, payment_totals[label], total)
            for label in labels
            if label in payment_totals and payment_totals[label] > _ZERO
        ]

    def _chart_item(self, label: str, value: Decimal, total: Decimal) -> dict[str, Any]:
        share = float(value / total * 100) if total > _ZERO else 0.0
        return {
            "label": label,
            "value": value,
            "value_label": self._money_text(value),
            "share": round(share, 1),
        }

    # --- money / quantity / formatting --------------------------------------
    @staticmethod
    def _money(value: Any) -> Decimal:
        if value is None:
            return _ZERO
        if isinstance(value, Decimal):
            return value.quantize(_MONEY_QUANT)
        return Decimal(str(value)).quantize(_MONEY_QUANT)

    @staticmethod
    def _qty(value: Any) -> Decimal:
        if value is None:
            return _ZERO
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _money_text(value: Decimal) -> str:
        return f"{value:,.2f}"

    @staticmethod
    def _qty_text(value: Decimal) -> str:
        """Quantity without noise: drop the fractional part when it is a whole
        number (2400, not 2400.000000), otherwise show the trimmed decimals."""
        normalised = value.normalize()
        if normalised == normalised.to_integral_value():
            return f"{int(normalised):,}"
        text = format(normalised, "f")
        whole, _, frac = text.partition(".")
        return f"{int(whole):,}.{frac}" if frac else f"{int(whole):,}"

    @classmethod
    def _payment_label(cls, value: Any) -> str:
        code = str(value or "").strip().lower()
        if code == PAYMENT_CASH:
            return PAYMENT_LABEL_CASH
        if code == PAYMENT_CREDIT:
            return PAYMENT_LABEL_CREDIT
        return PAYMENT_LABEL_UNKNOWN

    @staticmethod
    def _format_date(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    def _export_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "issue_date": row["issue_date"],
            "invoice_number": row["invoice_number"],
            "supplier_name": row["supplier_name"],
            "item_name": row["item_name"],
            "unit": row["unit"],
            "item_count": self._qty_text(row["item_count"]),
            "unit_price": self._money_text(row["unit_price"]),
            "count_price_total": self._money_text(row["count_price_total"]),
        }

    # --- validation ---------------------------------------------------------
    @staticmethod
    def _clean(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _validate_dates(
        date_from: str | None, date_to: str | None
    ) -> tuple[str | None, str | None]:
        start = (date_from or "").strip() or None
        end = (date_to or "").strip() or None
        if start and end and start > end:
            raise PurchaseReportValidationError(
                "نطاق التاريخ غير صحيح: يجب أن يكون تاريخ (من) أقل من أو يساوي تاريخ (إلى)."
            )
        return start, end


__all__ = [
    "PurchaseReportService",
    "PurchaseReportRequest",
    "PurchaseReportResult",
    "PurchaseReportValidationError",
    "ReportColumn",
    "REPORT_COLUMNS",
    "CURRENCY_LABEL",
    "EMPTY_MESSAGE",
    "TOP_SUPPLIERS_COUNT",
    "PAYMENT_CASH",
    "PAYMENT_CREDIT",
    "PAYMENT_LABEL_CASH",
    "PAYMENT_LABEL_CREDIT",
]
