"""Business logic for the Profit Report (تقرير الأرباح).

The UI calls only this service; this service calls only the repository. No SQL
and no Qt widgets live here — just the Arabic labels, the fixed-decimal money
formatting, the KPI cards, the donut dataset and the input validation.

The report is strictly **read-only**. It lists one movement row per invoice —
sales invoices and purchase invoices merged into a single date-ordered ledger:

* نوع الحركة: «بيع» for a sales invoice, «شراء» for a purchase invoice.
* البيان: «فاتورة مبيعات رقم …» / «فاتورة مشتريات رقم …».
* عمود المبيعات: the sales invoice total (``total_including_vat``).
* عمود المشتريات: the purchase invoice total (count price + weight price).

صافي الربح = إجمالي المبيعات − إجمالي المشتريات. All money is handled with
:class:`decimal.Decimal` (never float), matching the ``numeric(18,2)`` columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.models.sales_invoice import STATUS_APPROVED
from app.repositories.profit_report_repository import ProfitReportRepository

_ZERO = Decimal("0")
_MONEY_QUANT = Decimal("0.01")

EMPTY_MESSAGE = "لا توجد فواتير مبيعات أو مشتريات خلال الفترة/الفلاتر المحددة"

# Movement-type filter values.
TYPE_ALL = "all"
TYPE_SALE = "sale"
TYPE_PURCHASE = "purchase"
_VALID_TYPES = (TYPE_ALL, TYPE_SALE, TYPE_PURCHASE)

TYPE_LABELS_AR = {TYPE_SALE: "بيع", TYPE_PURCHASE: "شراء"}


class ProfitReportValidationError(Exception):
    """Raised for invalid filters. ``message`` is a ready-to-show Arabic string."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ProfitReportRequest:
    date_from: str | None = None
    date_to: str | None = None
    movement_type: str = TYPE_ALL   # TYPE_ALL | TYPE_SALE | TYPE_PURCHASE


@dataclass(frozen=True)
class ProfitReportResult:
    rows: list[dict[str, Any]]          # numeric (Decimal) rows for totals/tests
    export_rows: list[dict[str, Any]]   # formatted strings for the table/print
    summary: dict[str, Any]             # KPI cards
    pie: list[dict[str, Any]]           # donut: {label, count, value_label, share, color}
    is_empty: bool = False


class ProfitReportService:
    """Build the read-only profit report + its KPIs and donut."""

    def __init__(self, repository: ProfitReportRepository | None = None) -> None:
        self.repository = repository or ProfitReportRepository()

    # --- selectors ----------------------------------------------------------
    def company_letterhead(self) -> dict[str, Any] | None:
        """The first registered company, for the printable letterhead. Never raises."""
        try:
            return self.repository.fetch_company_letterhead()
        except Exception:  # noqa: BLE001
            return None

    # --- public API ---------------------------------------------------------
    def fetch_report(self, request: ProfitReportRequest) -> ProfitReportResult:
        movement_type = request.movement_type if request.movement_type in _VALID_TYPES else TYPE_ALL
        date_from, date_to = self._validate_dates(request.date_from, request.date_to)

        sales_rows: list[dict[str, Any]] = []
        purchase_rows: list[dict[str, Any]] = []
        if movement_type in (TYPE_ALL, TYPE_SALE):
            sales_rows = self.repository.fetch_sales_invoices(date_from=date_from, date_to=date_to)
        if movement_type in (TYPE_ALL, TYPE_PURCHASE):
            purchase_rows = self.repository.fetch_purchase_invoices(date_from=date_from, date_to=date_to)

        movements: list[dict[str, Any]] = []
        total_sales = _ZERO
        total_purchases = _ZERO

        for row in sales_rows:
            amount = self._money(row.get("total"))
            total_sales += amount
            number = str(row.get("invoice_number") or "").strip()
            movements.append(
                {
                    "sort_key": self._sort_key(row.get("issue_datetime"), row.get("issue_date"), row.get("id")),
                    "date": row.get("issue_date"),
                    "type_code": TYPE_SALE,
                    "type_label": TYPE_LABELS_AR[TYPE_SALE],
                    "number": number,
                    "statement": f"فاتورة مبيعات رقم {number}" if number else "فاتورة مبيعات",
                    "sales_amount": amount,
                    "purchase_amount": _ZERO,
                }
            )

        for row in purchase_rows:
            amount = self._money(row.get("total"))
            total_purchases += amount
            number = str(row.get("invoice_number") or "").strip()
            movements.append(
                {
                    "sort_key": self._sort_key(row.get("issue_datetime"), row.get("issue_date"), row.get("id")),
                    "date": row.get("issue_date"),
                    "type_code": TYPE_PURCHASE,
                    "type_label": TYPE_LABELS_AR[TYPE_PURCHASE],
                    "number": number,
                    "statement": f"فاتورة مشتريات رقم {number}" if number else "فاتورة مشتريات",
                    "sales_amount": _ZERO,
                    "purchase_amount": amount,
                }
            )

        movements.sort(key=lambda item: item["sort_key"])

        export_rows = [
            {
                "date": self._format_date(m["date"]),
                "type_code": m["type_code"],
                "type_label": m["type_label"],
                "statement": m["statement"],
                "sales_amount": self._money_text(m["sales_amount"]) if m["sales_amount"] > _ZERO else "",
                "purchase_amount": self._money_text(m["purchase_amount"]) if m["purchase_amount"] > _ZERO else "",
            }
            for m in movements
        ]

        net_profit = total_sales - total_purchases
        summary = {
            "total_sales": total_sales,
            "total_sales_label": self._money_text(total_sales),
            "total_purchases": total_purchases,
            "total_purchases_label": self._money_text(total_purchases),
            "net_profit": net_profit,
            "net_profit_label": self._money_text(net_profit),
            "net_profit_sign": self._sign(net_profit),
            "margin_label": self._margin_pct(total_sales, net_profit),
            "sales_count": len(sales_rows),
            "sales_count_label": f"{len(sales_rows):,}",
            "purchase_count": len(purchase_rows),
            "purchase_count_label": f"{len(purchase_rows):,}",
            "movement_count": len(movements),
            "movement_count_label": f"{len(movements):,}",
        }

        pie = self._pie(total_sales, total_purchases)

        return ProfitReportResult(
            rows=movements,
            export_rows=export_rows,
            summary=summary,
            pie=pie,
            is_empty=not movements,
        )

    # --- donut --------------------------------------------------------------
    def _pie(self, total_sales: Decimal, total_purchases: Decimal) -> list[dict[str, Any]]:
        """Two slices — المبيعات (green) vs المشتريات (red) — with share labels."""
        grand = total_sales + total_purchases
        slices: list[dict[str, Any]] = []
        for label, value, color in (
            ("المبيعات", total_sales, "#16A34A"),
            ("المشتريات", total_purchases, "#DC2626"),
        ):
            if value <= _ZERO:
                continue
            share = float(value / grand * 100) if grand > _ZERO else 0.0
            slices.append(
                {
                    "label": label,
                    "count": int(value.to_integral_value(rounding="ROUND_HALF_UP")),
                    "value": value,
                    "value_label": self._money_text(value),
                    "share": round(share, 1),
                    "color": color,
                }
            )
        return slices

    # --- money / formatting -------------------------------------------------
    @staticmethod
    def _money(value: Any) -> Decimal:
        if value is None:
            return _ZERO
        if isinstance(value, Decimal):
            amount = value
        else:
            try:
                amount = Decimal(str(value))
            except Exception:  # noqa: BLE001
                return _ZERO
        return amount.quantize(_MONEY_QUANT)

    @classmethod
    def _money_text(cls, value: Decimal) -> str:
        """Money with 2 decimals and thousands separators: 54150 → '54,150.00'."""
        amount = value.quantize(_MONEY_QUANT)
        sign = "-" if amount < _ZERO else ""
        amount = abs(amount)
        whole, _, frac = format(amount, "f").partition(".")
        frac = (frac + "00")[:2]
        return f"{sign}{int(whole):,}.{frac}"

    @staticmethod
    def _sign(value: Decimal) -> str:
        return "pos" if value > _ZERO else "neg" if value < _ZERO else "zero"

    @classmethod
    def _margin_pct(cls, total_sales: Decimal, net_profit: Decimal) -> str:
        """Profit margin as a percentage of sales; empty when there are no sales."""
        if total_sales <= _ZERO:
            return "—"
        pct = float(net_profit / total_sales * 100)
        return f"{pct:.1f}%"

    @staticmethod
    def _sort_key(issue_datetime: Any, issue_date: Any, row_id: Any) -> tuple[str, int]:
        """Deterministic oldest-first key across the two merged sources."""
        stamp = issue_datetime if issue_datetime is not None else issue_date
        if isinstance(stamp, datetime):
            text = stamp.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(stamp, date):
            text = stamp.strftime("%Y-%m-%d 00:00:00")
        else:
            text = str(stamp or "")
        try:
            rid = int(row_id)
        except (TypeError, ValueError):
            rid = 0
        return (text, rid)

    @staticmethod
    def _format_date(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (date, datetime)):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    # --- validation ---------------------------------------------------------
    @staticmethod
    def _validate_dates(
        date_from: str | None, date_to: str | None
    ) -> tuple[str | None, str | None]:
        start = (date_from or "").strip() or None
        end = (date_to or "").strip() or None
        if start and end and start > end:
            raise ProfitReportValidationError(
                "نطاق التاريخ غير صحيح: يجب أن يكون تاريخ (من) أقل من أو يساوي تاريخ (إلى)."
            )
        return start, end


__all__ = [
    "ProfitReportService",
    "ProfitReportRequest",
    "ProfitReportResult",
    "ProfitReportValidationError",
    "EMPTY_MESSAGE",
    "TYPE_ALL",
    "TYPE_SALE",
    "TYPE_PURCHASE",
    "TYPE_LABELS_AR",
]
