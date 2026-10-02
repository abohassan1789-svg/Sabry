"""Business logic for the Production Orders Report (تقرير أوامر الإنتاج).

The UI calls only this service; this service calls only the repository. No SQL
and no Qt widgets live here — just the Arabic labels, the fixed-decimal quantity
formatting, the dashboard KPIs, the chart datasets and the input validation.

The report is strictly **read-only**: opening or refreshing it performs SELECTs
only. It lists one summary row per production order (header fields + line
aggregates), keeps each order's material lines for the expandable detail, and
derives the KPI cards and charts from those same rows in Python — two database
round-trips for the whole screen (order summaries + their lines).

All quantities are handled with :class:`decimal.Decimal` (never float), matching
the ``numeric(18,3)`` / ``numeric(19,3)`` columns. No cost total is computed or
exposed — this mirrors the Production Order module, which stores a price snapshot
but deliberately exposes quantities and deviation only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.repositories.production_order_report_repository import (
    DEFAULT_PICKER_LIMIT,
    ROLE_FINISHED,
    ROLE_RAW,
    ProductionOrderReportRepository,
)

_ZERO = Decimal("0")
_QTY_QUANT = Decimal("0.001")

EMPTY_MESSAGE = "لا توجد أوامر إنتاج خلال الفترة/الفلاتر المحددة"

# Number of slices shown in each donut before the rest roll into «أخرى».
TOP_PRODUCTS_COUNT = 6
TOP_MATERIALS_COUNT = 6


class ProductionReportValidationError(Exception):
    """Raised for invalid filters. ``message`` is a ready-to-show Arabic string."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ReportColumn:
    key: str
    label: str


@dataclass(frozen=True)
class ProductionReportRequest:
    date_from: str | None = None
    date_to: str | None = None
    item_id: int | None = None
    item_role: str = ROLE_FINISHED   # ROLE_FINISHED | ROLE_RAW


@dataclass(frozen=True)
class ProductionReportResult:
    columns: list[ReportColumn]
    line_columns: list[ReportColumn]
    orders: list[dict[str, Any]]            # numeric (Decimal) rows for totals/tests
    export_orders: list[dict[str, Any]]     # formatted strings keyed by column.key (+ id, deviation_sign)
    lines_by_order: dict[int, list[dict[str, Any]]]  # order_id -> formatted line dicts
    summary: dict[str, Any]                 # KPI cards
    production_by_product: list[dict[str, Any]]  # donut: {label, count, value_label, share}
    material_share: list[dict[str, Any]]         # donut: {label, count, value_label, share}
    totals: dict[str, Any]                  # expected/actual/deviation totals (+ labels)
    is_empty: bool = False


# Order (header) table columns — one row per production order, expandable to lines.
REPORT_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("order_number", "رقم الأمر"),
    ReportColumn("order_date", "التاريخ"),
    ReportColumn("product_name", "المنتج التام"),
    ReportColumn("production_quantity", "الكمية المخططة"),
    ReportColumn("material_count", "عدد المواد"),
    ReportColumn("total_expected", "إجمالي المتوقع"),
    ReportColumn("total_actual", "إجمالي الفعلي"),
    ReportColumn("total_deviation", "الانحراف"),
)

# Line (material) columns — shown when an order row is expanded.
LINE_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("item_code", "الكود"),
    ReportColumn("item_name", "المادة الخام"),
    ReportColumn("unit", "الوحدة"),
    ReportColumn("expected_quantity", "المتوقع"),
    ReportColumn("actual_quantity", "الفعلي"),
    ReportColumn("deviation", "الانحراف"),
)


class ProductionOrderReportService:
    """Build the read-only production-orders report + its KPIs and charts."""

    def __init__(
        self, repository: ProductionOrderReportRepository | None = None
    ) -> None:
        self.repository = repository or ProductionOrderReportRepository()
        self.columns = list(REPORT_COLUMNS)
        self.line_columns = list(LINE_COLUMNS)

    # --- selectors ----------------------------------------------------------
    def search_products(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        try:
            return list(self.repository.search_products(keyword, limit))
        except Exception:  # noqa: BLE001 - a picker must never crash the screen
            return []

    def company_letterhead(self) -> dict[str, Any] | None:
        """The first registered company, for the printable letterhead. Never raises."""
        try:
            return self.repository.fetch_company_letterhead()
        except Exception:  # noqa: BLE001
            return None

    # --- public API ---------------------------------------------------------
    def fetch_report(self, request: ProductionReportRequest) -> ProductionReportResult:
        item_id = self._optional_id(request.item_id, "الصنف المحدد غير صالح.")
        item_role = request.item_role if request.item_role in (ROLE_FINISHED, ROLE_RAW) else ROLE_FINISHED
        date_from, date_to = self._validate_dates(request.date_from, request.date_to)

        summaries = self.repository.fetch_order_summaries(
            date_from=date_from,
            date_to=date_to,
            item_id=item_id,
            item_role=item_role,
        )
        order_ids = [int(row["id"]) for row in summaries]
        raw_lines = self.repository.fetch_lines_for_orders(order_ids)

        # --- order (header) rows -------------------------------------------
        orders: list[dict[str, Any]] = []
        export_orders: list[dict[str, Any]] = []
        total_planned = _ZERO
        total_expected = _ZERO
        total_actual = _ZERO
        total_deviation = _ZERO
        finished_ids: set[Any] = set()
        # product name -> planned quantity (for the production donut)
        product_planned: dict[str, Decimal] = {}

        for row in summaries:
            planned = self._qty(row.get("production_quantity"))
            expected = self._qty(row.get("total_expected"))
            actual = self._qty(row.get("total_actual"))
            deviation = self._qty(row.get("total_deviation"))
            total_planned += planned
            total_expected += expected
            total_actual += actual
            total_deviation += deviation
            finished_ids.add(row.get("product_id"))

            product_name = (row.get("product_name_snapshot") or "").strip() or "غير محدد"
            product_planned[product_name] = product_planned.get(product_name, _ZERO) + planned

            orders.append(
                {
                    "id": int(row["id"]),
                    "order_number": row.get("order_number") or "",
                    "order_date": row.get("order_date"),
                    "product_name": product_name,
                    "production_quantity": planned,
                    "material_count": int(row.get("material_count") or 0),
                    "total_expected": expected,
                    "total_actual": actual,
                    "total_deviation": deviation,
                }
            )
            export_orders.append(
                {
                    "id": int(row["id"]),
                    "order_number": row.get("order_number") or "",
                    "order_date": self._format_date(row.get("order_date")),
                    "product_name": product_name,
                    "production_quantity": self._qty_text(planned),
                    "material_count": f"{int(row.get('material_count') or 0):,}",
                    "total_expected": self._qty_text(expected),
                    "total_actual": self._qty_text(actual),
                    "total_deviation": self._signed_qty_text(deviation),
                    "deviation_sign": self._sign(deviation),
                }
            )

        # --- material lines (grouped per order) ----------------------------
        lines_by_order: dict[int, list[dict[str, Any]]] = {}
        # material name -> total actual quantity (for the material donut)
        material_actual: dict[str, Decimal] = {}
        material_ids: set[Any] = set()
        for line in raw_lines:
            order_id = int(line["production_order_id"])
            expected = self._qty(line.get("expected_quantity"))
            actual = self._qty(line.get("actual_quantity"))
            deviation = self._qty(line.get("deviation"))
            name = (line.get("item_name_snapshot") or "").strip() or "غير محدد"
            material_actual[name] = material_actual.get(name, _ZERO) + actual
            material_ids.add(line.get("component_product_id"))
            lines_by_order.setdefault(order_id, []).append(
                {
                    "item_code": self._code_text(line.get("item_code_snapshot")),
                    "item_name": name,
                    "unit": (line.get("unit_snapshot") or "").strip(),
                    "expected_quantity": self._qty_text(expected),
                    "actual_quantity": self._qty_text(actual),
                    "deviation": self._signed_qty_text(deviation),
                    "deviation_sign": self._sign(deviation),
                }
            )

        summary = {
            "total_orders": len(orders),
            "total_orders_label": f"{len(orders):,}",
            "total_planned": total_planned,
            "total_planned_label": self._qty_text(total_planned),
            "finished_products_count": len(finished_ids),
            "finished_products_label": f"{len(finished_ids):,}",
            "raw_materials_count": len(material_ids),
            "raw_materials_label": f"{len(material_ids):,}",
            "total_expected": total_expected,
            "total_expected_label": self._qty_text(total_expected),
            "total_actual": total_actual,
            "total_actual_label": self._qty_text(total_actual),
            "total_deviation": total_deviation,
            "total_deviation_label": self._signed_qty_text(total_deviation),
            "deviation_sign": self._sign(total_deviation),
            "deviation_pct_label": self._deviation_pct(total_expected, total_deviation),
        }

        return ProductionReportResult(
            columns=self.columns,
            line_columns=self.line_columns,
            orders=orders,
            export_orders=export_orders,
            lines_by_order=lines_by_order,
            summary=summary,
            production_by_product=self._top_slices(product_planned, TOP_PRODUCTS_COUNT),
            material_share=self._top_slices(material_actual, TOP_MATERIALS_COUNT),
            totals={
                "expected": total_expected,
                "actual": total_actual,
                "deviation": total_deviation,
                "expected_label": self._qty_text(total_expected),
                "actual_label": self._qty_text(total_actual),
                "deviation_label": self._signed_qty_text(total_deviation),
            },
            is_empty=not orders,
        )

    # --- chart helper -------------------------------------------------------
    def _top_slices(
        self, totals: dict[str, Decimal], top_n: int
    ) -> list[dict[str, Any]]:
        """Rank a name→quantity map into donut slices (top N + «أخرى» rollup).

        ``count`` is an int (the shared donut widget casts to int); ``value_label``
        keeps the precise quantity and ``share`` the percentage for the legend.
        """
        positive = {name: qty for name, qty in totals.items() if qty > _ZERO}
        grand = sum(positive.values(), _ZERO)
        if grand <= _ZERO:
            return []
        ranked = sorted(positive.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
        head = ranked[: max(1, top_n - 1)] if len(ranked) > top_n else ranked
        tail = ranked[len(head):]
        slices: list[dict[str, Any]] = []
        for name, qty in head:
            slices.append(self._slice(name, qty, grand))
        if tail:
            other = sum((qty for _n, qty in tail), _ZERO)
            slices.append(self._slice("أخرى", other, grand))
        return slices

    def _slice(self, name: str, qty: Decimal, grand: Decimal) -> dict[str, Any]:
        share = float(qty / grand * 100) if grand > _ZERO else 0.0
        return {
            "label": name,
            "count": int(qty.to_integral_value(rounding="ROUND_HALF_UP")),
            "value": qty,
            "value_label": self._qty_text(qty),
            "share": round(share, 1),
        }

    # --- money / quantity / formatting --------------------------------------
    @staticmethod
    def _qty(value: Any) -> Decimal:
        if value is None:
            return _ZERO
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:  # noqa: BLE001
            return _ZERO

    @staticmethod
    def _qty_text(value: Decimal) -> str:
        """Quantity without noise: 320 not 320.000, but keep real decimals."""
        normalised = value.normalize()
        if normalised == normalised.to_integral_value():
            return f"{int(normalised):,}"
        text = format(normalised, "f")
        whole, _, frac = text.partition(".")
        sign = "-" if whole.startswith("-") else ""
        whole = whole.lstrip("-")
        return f"{sign}{int(whole):,}.{frac}" if frac else f"{sign}{int(whole):,}"

    @classmethod
    def _signed_qty_text(cls, value: Decimal) -> str:
        """Deviation with an explicit leading + for positive values."""
        if value > _ZERO:
            return "+" + cls._qty_text(value)
        return cls._qty_text(value)  # negative keeps '-', zero shows '0'

    @staticmethod
    def _sign(value: Decimal) -> str:
        return "pos" if value > _ZERO else "neg" if value < _ZERO else "zero"

    @classmethod
    def _deviation_pct(cls, expected: Decimal, deviation: Decimal) -> str:
        if expected <= _ZERO:
            return ""
        pct = float(deviation / expected * 100)
        arrow = "↑" if pct > 0 else "↓" if pct < 0 else ""
        return f"{arrow} {abs(pct):.2f}%".strip()

    @staticmethod
    def _code_text(value: Any) -> str:
        if value in (None, ""):
            return ""
        text = str(value).strip()
        try:
            return str(int(text))
        except (TypeError, ValueError):
            return text

    @staticmethod
    def _format_date(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    # --- validation ---------------------------------------------------------
    @staticmethod
    def _optional_id(value: Any, invalid_message: str) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ProductionReportValidationError(invalid_message) from exc

    @staticmethod
    def _validate_dates(
        date_from: str | None, date_to: str | None
    ) -> tuple[str | None, str | None]:
        start = (date_from or "").strip() or None
        end = (date_to or "").strip() or None
        if start and end and start > end:
            raise ProductionReportValidationError(
                "نطاق التاريخ غير صحيح: يجب أن يكون تاريخ (من) أقل من أو يساوي تاريخ (إلى)."
            )
        return start, end


__all__ = [
    "ProductionOrderReportService",
    "ProductionReportRequest",
    "ProductionReportResult",
    "ProductionReportValidationError",
    "ReportColumn",
    "REPORT_COLUMNS",
    "LINE_COLUMNS",
    "EMPTY_MESSAGE",
    "ROLE_FINISHED",
    "ROLE_RAW",
]
