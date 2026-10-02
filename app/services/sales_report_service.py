"""Business logic for the Sales report (تقرير المبيعات).

The UI calls only this service; this service calls only the repository. No SQL
and no Qt widgets live here — just the row mapping, the Arabic labels, the
fixed-decimal money/quantity formatting, the dashboard KPIs and the input
validation.

The report is strictly **read-only**: opening or refreshing it performs SELECTs
only. It lists one row per approved-invoice line and derives three dashboard
cards plus the "top 5 customers" chart from those same rows in Python — a single
database round-trip for the whole screen, exactly like the customer-statement
report.

Money and quantity are handled with :class:`decimal.Decimal` throughout (never
float), matching the ``numeric`` invoice-line columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.repositories.sales_report_repository import (
    DEFAULT_PICKER_LIMIT,
    SalesReportFilters,
    SalesReportRepository,
)

# numeric(18,2) money, numeric(18,6) quantity.
_MONEY_QUANT = Decimal("0.01")
_ZERO = Decimal("0.00")

# Currency shown next to money values. The sales-invoice model is SAR-only
# (app.models.sales_invoice.CURRENCY_CODE == "SAR"), so the report is in ر.س.
CURRENCY_LABEL = "ر.س"

# Unit-code → Arabic label. Sales invoice lines default to 'PCE'; anything not
# mapped falls back to the raw stored code so nothing is ever hidden.
UNIT_LABELS_AR: dict[str, str] = {
    "PCE": "قطعة",
    "KGM": "كجم",
    "GRM": "جرام",
    "LTR": "لتر",
    "MTR": "متر",
    "BX": "صندوق",
    "CT": "كرتونة",
    "BG": "شكارة",
    "PK": "عبوة",
}

# Number of customers shown in the "أكبر العملاء" chart.
TOP_CUSTOMERS_COUNT = 5

EMPTY_MESSAGE = "لا توجد مبيعات خلال الفترة/الفلاتر المحددة"


class SalesReportValidationError(Exception):
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
class SalesReportRequest:
    customer_id: int | None = None
    product_id: int | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass(frozen=True)
class SalesReportResult:
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]          # numeric rows (Decimal) for totals/tests
    export_rows: list[dict[str, Any]]   # formatted strings keyed by column.key
    summary: dict[str, Any]             # KPIs: total / top customer / top item
    top_customers: list[dict[str, Any]] # chart data (label + value + share%)
    is_empty: bool


# Visible columns, in the exact required order. The UI renders RTL, so the first
# column (التاريخ) shows on the right.
REPORT_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("issue_date", "التاريخ"),
    ReportColumn("customer_name", "اسم العميل"),
    ReportColumn("invoice_number", "رقم الفاتورة"),
    ReportColumn("product_name", "اسم الصنف"),
    ReportColumn("unit", "الوحدة"),
    ReportColumn("quantity", "الكمية"),
    ReportColumn("unit_price", "السعر"),
    ReportColumn("line_total", "الإجمالي"),
    ReportColumn("vat_amount", "الضريبة"),
    ReportColumn("line_total_including_vat", "الإجمالي شامل الضريبة"),
)


class SalesReportService:
    """Build the read-only sales report + its KPIs from approved-invoice lines."""

    def __init__(self, repository: SalesReportRepository | None = None) -> None:
        self.repository = repository or SalesReportRepository()
        self.columns = list(REPORT_COLUMNS)

    # --- public API ---------------------------------------------------------
    def fetch_report(self, request: SalesReportRequest) -> SalesReportResult:
        customer_id = self._optional_id(request.customer_id, "العميل المحدد غير صالح.")
        product_id = self._optional_id(request.product_id, "الصنف المحدد غير صالح.")
        date_from, date_to = self._validate_dates(request.date_from, request.date_to)

        filters = SalesReportFilters(
            customer_id=customer_id,
            product_id=product_id,
            date_from=date_from,
            date_to=date_to,
        )
        raw_rows = self.repository.fetch_lines(filters)

        rows: list[dict[str, Any]] = []
        total_sales = _ZERO
        total_vat = _ZERO
        total_including_vat = _ZERO
        invoice_numbers: set[str] = set()
        # customer_id -> {"name", "total"}   /   product name -> {"quantity"}
        customer_totals: dict[Any, dict[str, Any]] = {}
        item_quantities: dict[str, Decimal] = {}

        for raw in raw_rows:
            line_total = self._money(raw.get("line_total"))
            vat_amount = self._money(raw.get("vat_amount"))
            line_incl = self._money(raw.get("line_total_including_vat"))
            quantity = self._qty(raw.get("quantity"))
            unit_price = self._money(raw.get("unit_price"))
            total_sales += line_total
            total_vat += vat_amount
            total_including_vat += line_incl

            number = str(raw.get("invoice_number") or "")
            if number:
                invoice_numbers.add(number)

            cust_key = raw.get("customer_id")
            cust_name = (raw.get("customer_name") or "").strip() or "غير محدد"
            bucket = customer_totals.setdefault(
                cust_key, {"name": cust_name, "total": _ZERO}
            )
            bucket["total"] += line_total
            # keep the first non-empty name we saw for this customer id
            if bucket["name"] == "غير محدد" and cust_name != "غير محدد":
                bucket["name"] = cust_name

            item_name = (raw.get("product_name") or "").strip() or "غير محدد"
            item_quantities[item_name] = item_quantities.get(item_name, _ZERO) + quantity

            rows.append(
                {
                    "issue_date": self._format_date(raw.get("issue_date")),
                    "customer_name": cust_name,
                    "invoice_number": str(raw.get("invoice_number") or ""),
                    "product_name": item_name,
                    "unit": self._unit_label(raw.get("unit_code")),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                    "vat_amount": vat_amount,
                    "line_total_including_vat": line_incl,
                }
            )

        export_rows = [self._export_row(row) for row in rows]
        summary = self._build_summary(
            total_sales, total_vat, total_including_vat,
            len(invoice_numbers), customer_totals, item_quantities,
        )
        top_customers = self._build_top_customers(customer_totals, total_sales)

        return SalesReportResult(
            columns=self.columns,
            rows=rows,
            export_rows=export_rows,
            summary=summary,
            top_customers=top_customers,
            is_empty=not rows,
        )

    # --- selectors ----------------------------------------------------------
    def company_letterhead(self) -> dict[str, Any] | None:
        """The first registered company, for the printable letterhead. Never raises."""
        try:
            return self.repository.fetch_company_letterhead()
        except Exception:  # noqa: BLE001
            return None

    def search_customers(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        try:
            return list(self.repository.search_customers(keyword, limit))
        except Exception:  # noqa: BLE001 - a picker must never crash the screen
            return []

    def search_products(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        try:
            return list(self.repository.search_products(keyword, limit))
        except Exception:  # noqa: BLE001
            return []

    def customer_name(self, customer_id: Any) -> str | None:
        cid = self._optional_id(customer_id, "العميل المحدد غير صالح.")
        if cid is None:
            return None
        try:
            return self.repository.get_customer_name(cid)
        except Exception:  # noqa: BLE001
            return None

    def product_name(self, product_id: Any) -> str | None:
        pid = self._optional_id(product_id, "الصنف المحدد غير صالح.")
        if pid is None:
            return None
        try:
            return self.repository.get_product_name(pid)
        except Exception:  # noqa: BLE001
            return None

    # --- KPI builders -------------------------------------------------------
    def _build_summary(
        self,
        total_sales: Decimal,
        total_vat: Decimal,
        total_including_vat: Decimal,
        invoice_count: int,
        customer_totals: dict[Any, dict[str, Any]],
        item_quantities: dict[str, Decimal],
    ) -> dict[str, Any]:
        top_customer_name = ""
        top_customer_value = _ZERO
        for bucket in customer_totals.values():
            if bucket["total"] > top_customer_value:
                top_customer_value = bucket["total"]
                top_customer_name = bucket["name"]

        top_item_name = ""
        top_item_qty = _ZERO
        for name, qty in item_quantities.items():
            if qty > top_item_qty:
                top_item_qty = qty
                top_item_name = name

        return {
            "total_sales": total_sales,
            "total_sales_label": self._money_text(total_sales),
            "total_vat": total_vat,
            "total_vat_label": self._money_text(total_vat),
            "total_including_vat": total_including_vat,
            "total_including_vat_label": self._money_text(total_including_vat),
            "invoice_count": invoice_count,
            "invoice_count_label": f"{invoice_count:,}",
            "top_customer_name": top_customer_name or "—",
            "top_customer_value": top_customer_value,
            "top_customer_value_label": self._money_text(top_customer_value),
            "top_item_name": top_item_name or "—",
            "top_item_quantity": top_item_qty,
            "top_item_quantity_label": self._qty_text(top_item_qty),
        }

    def _build_top_customers(
        self, customer_totals: dict[Any, dict[str, Any]], total_sales: Decimal
    ) -> list[dict[str, Any]]:
        ranked = sorted(
            customer_totals.values(), key=lambda b: (b["total"], b["name"]), reverse=True
        )[:TOP_CUSTOMERS_COUNT]
        result: list[dict[str, Any]] = []
        for bucket in ranked:
            value = bucket["total"]
            share = float(value / total_sales * 100) if total_sales > _ZERO else 0.0
            result.append(
                {
                    "label": bucket["name"],
                    "value": value,
                    "value_label": self._money_text(value),
                    "share": round(share, 1),
                }
            )
        return result

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
        number (320, not 320.000000), otherwise show the trimmed decimals."""
        normalised = value.normalize()
        # normalize() can yield exponent form (e.g. 3E+2) for round numbers.
        if normalised == normalised.to_integral_value():
            return f"{int(normalised):,}"
        text = format(normalised, "f")
        whole, _, frac = text.partition(".")
        return f"{int(whole):,}.{frac}" if frac else f"{int(whole):,}"

    @classmethod
    def _unit_label(cls, unit_code: Any) -> str:
        code = str(unit_code or "").strip()
        if code == "":
            return ""
        return UNIT_LABELS_AR.get(code.upper(), code)

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
            "customer_name": row["customer_name"],
            "invoice_number": row["invoice_number"],
            "product_name": row["product_name"],
            "unit": row["unit"],
            "quantity": self._qty_text(row["quantity"]),
            "unit_price": self._money_text(row["unit_price"]),
            "line_total": self._money_text(row["line_total"]),
            "vat_amount": self._money_text(row["vat_amount"]),
            "line_total_including_vat": self._money_text(row["line_total_including_vat"]),
        }

    # --- validation ---------------------------------------------------------
    @staticmethod
    def _optional_id(value: Any, invalid_message: str) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise SalesReportValidationError(invalid_message) from exc

    @staticmethod
    def _validate_dates(
        date_from: str | None, date_to: str | None
    ) -> tuple[str | None, str | None]:
        start = (date_from or "").strip() or None
        end = (date_to or "").strip() or None
        if start and end and start > end:
            raise SalesReportValidationError(
                "نطاق التاريخ غير صحيح: يجب أن يكون تاريخ (من) أقل من أو يساوي تاريخ (إلى)."
            )
        return start, end


__all__ = [
    "SalesReportService",
    "SalesReportRequest",
    "SalesReportResult",
    "SalesReportValidationError",
    "ReportColumn",
    "REPORT_COLUMNS",
    "CURRENCY_LABEL",
    "EMPTY_MESSAGE",
    "TOP_CUSTOMERS_COUNT",
]
