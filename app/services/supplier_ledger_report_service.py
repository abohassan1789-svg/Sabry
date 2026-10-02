"""Item-level Supplier Ledger (كشف حساب المورد - تفصيلي) for «عدد» and «وزن».

Instead of one row per purchase invoice, every invoice is expanded into its **line
items**. The visible columns depend on the supplier's نوع الحساب:

* عدد -> التاريخ / رقم الحركة / نوع العملية / البيان / الكمية / السعر / القيمة / التحصيلات
  (القيمة = إجمالي سعر العدد للبند).
* وزن -> التاريخ / رقم الحركة / نوع العملية / البيان / الكمية / الوزن / إجمالي الوزن /
  السعر / القيمة / التحصيلات (القيمة = إجمالي سعر الوزن للبند).

Row kinds (identical for both): رصيد أول مدة (opening, under القيمة), فاتورة مشتريات
(one row per item), سداد (payment, under التحصيلات).

Closing figure (bottom, not per row):
    الرصيد المتبقي = (رصيد أول المدة + إجمالي المشتريات) − إجمالي التحصيلات

Read-only; money is :class:`Decimal`, quantities/weights kept exact (numeric(18,6)).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.repositories.supplier_statement_report_repository import (
    ACCOUNT_TYPE_COUNT,
    ACCOUNT_TYPE_WEIGHT,
    SupplierStatementFilters,
    SupplierStatementReportRepository,
)
from app.services.supplier_statement_report_service import (
    ReportColumn,
    SupplierStatementValidationError,
    SupplierStatementRequest as _Request,
)

_MONEY_QUANT = Decimal("0.01")
_ZERO = Decimal("0.00")
_TRAILING_DIGITS = re.compile(r"(\d+)\s*$")

SupplierLedgerRequest = _Request
SupplierLedgerValidationError = SupplierStatementValidationError

KIND_OPENING = "opening"
KIND_INVOICE = "invoice"
KIND_PAYMENT = "payment"

OP_OPENING = "رصيد أول مدة"
OP_INVOICE = "فاتورة مشتريات"
OP_PAYMENT = "سداد"

# Fixed columns shared by both profiles (in RTL order).
_COL_DATE = ReportColumn("transaction_date", "التاريخ")
_COL_MOVE = ReportColumn("movement_number", "رقم الحركة")
_COL_OP = ReportColumn("operation_type", "نوع العملية")
_COL_BAYAN = ReportColumn("description", "البيان")
_COL_QTY = ReportColumn("quantity", "الكمية")
_COL_UNIT_WEIGHT = ReportColumn("unit_weight", "الوزن")
_COL_TOTAL_WEIGHT = ReportColumn("total_weight", "إجمالي الوزن")
_COL_PRICE = ReportColumn("price", "السعر")
_COL_VALUE = ReportColumn("value", "القيمة")
_COL_COLLECTIONS = ReportColumn("collections", "التحصيلات")

# Formatting classes for the numeric columns.
_MONEY_KEYS = frozenset({"price", "value", "collections"})
_QTY_KEYS = frozenset({"quantity", "unit_weight", "total_weight"})


@dataclass(frozen=True)
class _LineProfile:
    """Per-account-type shape: the visible columns, which raw invoice-line field
    feeds each numeric column, and which raw field is the القيمة."""

    columns: tuple[ReportColumn, ...]
    value_field: str                          # raw line field for القيمة
    line_fields: tuple[tuple[str, str], ...]  # (column key, raw line field) for invoice rows


_COUNT_PROFILE = _LineProfile(
    columns=(_COL_DATE, _COL_MOVE, _COL_OP, _COL_BAYAN, _COL_QTY, _COL_PRICE,
             _COL_VALUE, _COL_COLLECTIONS),
    value_field="count_price_total",
    line_fields=(("quantity", "item_count"), ("price", "unit_price")),
)
_WEIGHT_PROFILE = _LineProfile(
    columns=(_COL_DATE, _COL_MOVE, _COL_OP, _COL_BAYAN, _COL_QTY, _COL_UNIT_WEIGHT,
             _COL_TOTAL_WEIGHT, _COL_PRICE, _COL_VALUE, _COL_COLLECTIONS),
    value_field="weight_price_total",
    line_fields=(("quantity", "item_count"), ("unit_weight", "unit_weight"),
                 ("total_weight", "total_weight"), ("price", "unit_price")),
)
_PROFILE_BY_ACCOUNT_TYPE = {
    ACCOUNT_TYPE_COUNT: _COUNT_PROFILE,
    ACCOUNT_TYPE_WEIGHT: _WEIGHT_PROFILE,
}

EMPTY_MESSAGE = "لا توجد حركات للمورد خلال الفترة المحددة"


@dataclass(frozen=True)
class SupplierLedgerResult:
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]
    export_rows: list[dict[str, Any]]
    summary: dict[str, Any]
    supplier_name: str | None
    is_empty: bool


class SupplierLedgerReportService:
    """Build the read-only item-level supplier ledger for one account type."""

    def __init__(
        self,
        repository: SupplierStatementReportRepository | None = None,
        *,
        account_type: str = ACCOUNT_TYPE_COUNT,
    ) -> None:
        self.repository = repository or SupplierStatementReportRepository(
            account_type=account_type
        )
        self.account_type = account_type
        self.profile = _PROFILE_BY_ACCOUNT_TYPE.get(account_type, _COUNT_PROFILE)
        self.columns = list(self.profile.columns)
        self._numeric_keys = _MONEY_KEYS | _QTY_KEYS

    # --- public API ---------------------------------------------------------
    def fetch_report(self, request: SupplierLedgerRequest) -> SupplierLedgerResult:
        supplier_id = self._optional_id(request.supplier_id, "المورد المحدد غير صالح.")
        date_from, date_to = self._validate_dates(request.date_from, request.date_to)

        filters = SupplierStatementFilters(
            supplier_id=supplier_id, date_from=date_from, date_to=date_to
        )
        raw_rows = list(self.repository.fetch_statement_lines(filters))

        supplier_name: str | None = None
        if supplier_id is not None:
            supplier_name = self.repository.fetch_supplier_name(supplier_id)

        ordered_raw = self._group_with_openings(raw_rows, supplier_id, supplier_name, date_from)

        rows: list[dict[str, Any]] = []
        total_opening = _ZERO
        total_purchases = _ZERO
        total_collections = _ZERO
        for raw in ordered_raw:
            kind = self._kind(raw.get("source_type"))
            row: dict[str, Any] = {
                "transaction_date": self._format_date(raw.get("transaction_date")),
                "movement_number": self._movement_cell(raw, kind),
                "operation_type": self._operation_type(kind),
                "description": self._description(raw, kind),
                "kind": kind,
                "supplier_name": raw.get("supplier_name") or "",
            }
            for key in self._numeric_keys:
                row[key] = None  # blank by default; each kind fills only its own

            if kind == KIND_INVOICE:
                for col_key, raw_field in self.profile.line_fields:
                    row[col_key] = self._num(raw.get(raw_field), money=col_key in _MONEY_KEYS)
                value = self._money_or_none(raw.get(self.profile.value_field))
                row["value"] = value
                total_purchases += value or _ZERO
            elif kind == KIND_OPENING:
                value = self._money_or_none(raw.get("value"))
                row["value"] = value
                total_opening += value or _ZERO
            else:  # payment
                collections = self._money_or_none(raw.get("collections"))
                row["collections"] = collections
                if collections:
                    total_collections += collections

            if supplier_name is None:
                supplier_name = raw.get("supplier_name") or None
            rows.append(row)

        total_value = total_opening + total_purchases
        remaining = total_value - total_collections
        export_rows = [self._export_row(row) for row in rows]
        summary = {
            "total_opening": total_opening,
            "total_purchases": total_purchases,
            "total_collections": total_collections,
            "total_value": total_value,
            "remaining": remaining,
            "count": len(rows),
            "total_opening_label": self._money_text(total_opening),
            "total_purchases_label": self._money_text(total_purchases),
            "total_collections_label": self._money_text(total_collections),
            "total_value_label": self._money_text(total_value),
            "remaining_label": self._money_text(remaining),
        }
        return SupplierLedgerResult(
            columns=self.columns,
            rows=rows,
            export_rows=export_rows,
            summary=summary,
            supplier_name=supplier_name,
            is_empty=not rows,
        )

    def load_supplier_options(self) -> list[dict[str, Any]]:
        try:
            return list(self.repository.fetch_supplier_options())
        except Exception:  # noqa: BLE001
            return []

    # --- grouping / opening -------------------------------------------------
    def _group_with_openings(self, raw_rows, supplier_id, supplier_name, date_from):
        if supplier_id is not None:
            supplier_ids: list[Any] = [supplier_id]
            names = {supplier_id: supplier_name or ""}
            openings = {
                supplier_id: self.repository.fetch_supplier_opening_balance(supplier_id)
            }
        else:
            names = {}
            for row in raw_rows:
                sid = row.get("supplier_id")
                if sid not in names:
                    names[sid] = row.get("supplier_name") or ""
            supplier_ids = sorted(names.keys(), key=lambda s: (s is None, s))
            openings = self.repository.fetch_supplier_openings(
                [s for s in supplier_ids if s is not None]
            )

        moves: dict[Any, list[dict[str, Any]]] = {}
        for row in raw_rows:
            moves.setdefault(row.get("supplier_id"), []).append(row)

        ordered: list[dict[str, Any]] = []
        for sid in supplier_ids:
            opening = openings.get(sid) or _ZERO
            ordered.append({
                "source_type": KIND_OPENING,
                "transaction_date": date_from,
                "supplier_id": sid,
                "supplier_name": names.get(sid) or "",
                "movement_number": None,
                "item_name": None,
                "value": self._money(opening),
                "collections": _ZERO,
                "voucher_description": None,
            })
            ordered.extend(moves.get(sid, []))
        return ordered

    # --- row logic ----------------------------------------------------------
    @staticmethod
    def _kind(source_type: Any) -> str:
        if source_type == KIND_OPENING:
            return KIND_OPENING
        if source_type == "purchase_invoice_line":
            return KIND_INVOICE
        return KIND_PAYMENT

    @staticmethod
    def _operation_type(kind: str) -> str:
        return {KIND_OPENING: OP_OPENING, KIND_INVOICE: OP_INVOICE}.get(kind, OP_PAYMENT)

    @staticmethod
    def _description(raw: dict[str, Any], kind: str) -> str:
        if kind == KIND_OPENING:
            return OP_OPENING
        if kind == KIND_INVOICE:
            return str(raw.get("item_name") or "").strip()
        return "السداد"

    def _movement_cell(self, raw: dict[str, Any], kind: str) -> str:
        if kind == KIND_OPENING:
            return "—"
        number = str(raw.get("movement_number") or "").strip()
        if kind == KIND_PAYMENT:
            return self._voucher_number(number)
        return number or "—"

    @staticmethod
    def _voucher_number(raw_number: Any) -> str:
        text = str(raw_number or "").strip()
        match = _TRAILING_DIGITS.search(text)
        return match.group(1) if match else (text or "—")

    # --- money / formatting -------------------------------------------------
    def _num(self, value: Any, *, money: bool) -> Decimal | None:
        return self._money_or_none(value) if money else self._qty_or_none(value)

    @staticmethod
    def _money(value: Any) -> Decimal:
        if value is None:
            return _ZERO
        if isinstance(value, Decimal):
            return value.quantize(_MONEY_QUANT)
        return Decimal(str(value)).quantize(_MONEY_QUANT)

    @staticmethod
    def _money_or_none(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value)).quantize(_MONEY_QUANT)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _qty_or_none(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _money_text(value: Decimal) -> str:
        return f"{value:,.2f}"

    def _money_cell(self, value: Decimal | None) -> str:
        return self._money_text(value) if value is not None else ""

    @staticmethod
    def _qty_text(value: Decimal | None) -> str:
        if value is None:
            return ""
        return format(value.normalize(), "f")  # trim trailing zeros: 50.000000 -> "50"

    @staticmethod
    def _format_date(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    def _export_row(self, row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": row["kind"]}
        for column in self.columns:
            key = column.key
            if key in _MONEY_KEYS:
                out[key] = self._money_cell(row.get(key))
            elif key in _QTY_KEYS:
                out[key] = self._qty_text(row.get(key))
            else:
                out[key] = row.get(key)
        return out

    # --- validation ---------------------------------------------------------
    @staticmethod
    def _optional_id(value: Any, invalid_message: str) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise SupplierLedgerValidationError(invalid_message) from exc

    @staticmethod
    def _validate_dates(date_from, date_to):
        start = (date_from or "").strip() or None
        end = (date_to or "").strip() or None
        if start and end and start > end:
            raise SupplierLedgerValidationError(
                "نطاق التاريخ غير صحيح: يجب أن يكون تاريخ (من) أقل من أو يساوي تاريخ (إلى)."
            )
        return start, end
