"""Business logic for the Raw-Material Warehouse balance (مخزن مواد الخام).

The UI calls only this service; this service calls only the repository. No SQL
and no Qt widgets live here — just the row mapping, the Arabic labels, the
``opening + purchases − issued`` arithmetic, the trimmed-quantity formatting, the
four dashboard KPIs, the per-row stock status (منخفض / متوسط / جيد) and the input
validation.

The report is strictly **read-only**: opening or refreshing it performs SELECTs
only. It lists one row per raw-material product — filtered to ``item_type =
'مادة خام'`` — and derives four KPI cards (عدد الأصناف · إجمالي المشتريات ·
إجمالي المصروف · صافي الرصيد) from those same rows in Python, a single database
round-trip for the whole screen.

Quantities are handled with :class:`decimal.Decimal` throughout (never float),
matching the ``numeric`` product / line columns. The three sources carry
different scales (opening_balance 18,2 — a money-scaled column reused as the
opening quantity; purchases item_count 18,6; issued actual_quantity 18,3);
Decimal adds them exactly and the display trims trailing zeros.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.repositories.raw_material_balance_repository import (
    DEFAULT_PICKER_LIMIT,
    RawMaterialBalanceFilters,
    RawMaterialBalanceRepository,
)

_ZERO = Decimal("0")

EMPTY_MESSAGE = "لا توجد أصناف مواد خام مطابقة للفلاتر المحددة"

# Stock-level status labels (derived from the current balance).
STATUS_LOW = "منخفض"
STATUS_MID = "متوسط"
STATUS_OK = "جيد"
STATUS_NONE = "بدون رصيد"

# Balance thresholds for the status column / KPI colouring. A balance at or below
# LOW is critical; at or below MID is watch-level; above is healthy. These are a
# simple visual aid (no reorder-point data exists in the schema yet).
LOW_THRESHOLD = Decimal("20")
MID_THRESHOLD = Decimal("100")


class RawMaterialBalanceValidationError(Exception):
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
class RawMaterialBalanceRequest:
    item_name: str | None = None


@dataclass(frozen=True)
class RawMaterialBalanceResult:
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]           # numeric rows (Decimal) for totals/tests
    export_rows: list[dict[str, Any]]    # formatted strings keyed by column.key
    summary: dict[str, Any]              # KPIs (count + purchases + issued + net)
    is_empty: bool


# Visible columns, in RTL order (first column shows on the right).
REPORT_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("item_code", "رقم الصنف"),
    ReportColumn("item_name", "اسم الصنف"),
    ReportColumn("unit", "الوحدة"),
    ReportColumn("opening_balance", "رصيد أول المدة"),
    ReportColumn("purchased", "المشتريات"),
    ReportColumn("issued", "المصروف الفعلي"),
    ReportColumn("balance", "الرصيد الحالي"),
    ReportColumn("status", "الحالة"),
)


class RawMaterialBalanceService:
    """Build the read-only raw-material warehouse balance + its KPIs."""

    def __init__(self, repository: RawMaterialBalanceRepository | None = None) -> None:
        self.repository = repository or RawMaterialBalanceRepository()
        self.columns = list(REPORT_COLUMNS)

    # --- public API ---------------------------------------------------------
    def fetch_report(self, request: RawMaterialBalanceRequest) -> RawMaterialBalanceResult:
        filters = RawMaterialBalanceFilters(
            item_name=self._clean(request.item_name),
        )
        raw_rows = self.repository.fetch_balances(filters)

        rows: list[dict[str, Any]] = []
        total_opening = _ZERO
        total_purchased = _ZERO
        total_issued = _ZERO
        total_balance = _ZERO

        for raw in raw_rows:
            opening = self._qty(raw.get("opening_balance"))
            purchased = self._qty(raw.get("purchased"))
            issued = self._qty(raw.get("issued"))
            balance = opening + purchased - issued

            total_opening += opening
            total_purchased += purchased
            total_issued += issued
            total_balance += balance

            rows.append(
                {
                    "product_id": raw.get("product_id"),
                    "item_code": raw.get("item_code"),
                    "item_name": (raw.get("item_name") or "").strip() or "غير مسمى",
                    "unit": (raw.get("unit") or "").strip(),
                    "opening_balance": opening,
                    "purchased": purchased,
                    "issued": issued,
                    "balance": balance,
                    "status": self._status(balance),
                }
            )

        export_rows = [self._export_row(row) for row in rows]
        summary = self._build_summary(
            len(rows), total_opening, total_purchased, total_issued, total_balance
        )
        return RawMaterialBalanceResult(
            columns=self.columns,
            rows=rows,
            export_rows=export_rows,
            summary=summary,
            is_empty=not rows,
        )

    # --- item picker --------------------------------------------------------
    def search_items(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        try:
            return list(self.repository.search_raw_materials(keyword, limit))
        except Exception:  # noqa: BLE001 - a picker must never crash the screen
            return []

    # --- KPI builder --------------------------------------------------------
    def _build_summary(
        self,
        item_count: int,
        total_opening: Decimal,
        total_purchased: Decimal,
        total_issued: Decimal,
        total_balance: Decimal,
    ) -> dict[str, Any]:
        return {
            "item_count": item_count,
            "item_count_label": f"{item_count:,}",
            "total_opening": total_opening,
            "total_opening_label": self._qty_text(total_opening),
            "total_purchased": total_purchased,
            "total_purchased_label": self._qty_text(total_purchased),
            "total_issued": total_issued,
            "total_issued_label": self._qty_text(total_issued),
            "total_balance": total_balance,
            "total_balance_label": self._qty_text(total_balance),
        }

    # --- status -------------------------------------------------------------
    @classmethod
    def _status(cls, balance: Decimal) -> str:
        if balance <= _ZERO:
            return STATUS_NONE
        if balance <= LOW_THRESHOLD:
            return STATUS_LOW
        if balance <= MID_THRESHOLD:
            return STATUS_MID
        return STATUS_OK

    # --- quantity / formatting ----------------------------------------------
    @staticmethod
    def _qty(value: Any) -> Decimal:
        if value is None:
            return _ZERO
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _qty_text(value: Decimal) -> str:
        """Quantity without noise: drop the fractional part when it is whole
        (500, not 500.000), otherwise show the trimmed decimals. Negative
        balances (over-issued) keep their sign."""
        normalised = value.normalize()
        if normalised == normalised.to_integral_value():
            return f"{int(normalised):,}"
        sign = "-" if normalised < 0 else ""
        text = format(abs(normalised), "f")
        whole, _, frac = text.partition(".")
        return f"{sign}{int(whole):,}.{frac}" if frac else f"{sign}{int(whole):,}"

    def _export_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "item_code": "" if row["item_code"] is None else str(row["item_code"]),
            "item_name": row["item_name"],
            "unit": row["unit"],
            "opening_balance": self._qty_text(row["opening_balance"]),
            "purchased": self._qty_text(row["purchased"]),
            "issued": self._qty_text(row["issued"]),
            "balance": self._qty_text(row["balance"]),
            "status": row["status"],
        }

    # --- normalisation ------------------------------------------------------
    @staticmethod
    def _clean(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None


__all__ = [
    "RawMaterialBalanceService",
    "RawMaterialBalanceRequest",
    "RawMaterialBalanceResult",
    "RawMaterialBalanceValidationError",
    "ReportColumn",
    "REPORT_COLUMNS",
    "EMPTY_MESSAGE",
    "STATUS_LOW",
    "STATUS_MID",
    "STATUS_OK",
    "STATUS_NONE",
    "LOW_THRESHOLD",
    "MID_THRESHOLD",
]
