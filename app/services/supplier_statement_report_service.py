"""Business logic for the Supplier Statement report (كشف حساب المورد).

The UI calls only this service; this service calls only the repository. No SQL
and no Qt widgets live here — just the row mapping, the exact Arabic
descriptions, the opening-balance row, the running balance, the fixed-decimal
totals and the input validation.

Account convention (supplier = payable / دائن account)
------------------------------------------------------
* ``رصيد أول المدة``   -> **credit** (دائن): the opening amount already owed.
* ``فاتورة مشتريات``   -> **credit** (دائن): a purchase increases what we owe.
* ``سند صرف``          -> **debit**  (مدين): paying the supplier reduces what we owe.

This is the mirror image of the customer statement (where an invoice is a debit
and a receipt a credit), which is correct: a customer is a receivable (asset) and
a supplier is a payable (liability). The running balance is therefore
``balance + credit - debit`` and the closing ``الرصيد`` is the amount still owed
to the supplier when positive.

The report is strictly **read-only and operational**: it combines existing
purchase invoices (credit) and supplier payment vouchers (debit) into one
statement and reads the supplier's stored opening balance. It never posts a
journal entry, never updates a supplier balance, never changes any
invoice/voucher status, and never creates a voucher. Opening or generating the
report performs SELECTs only.

Money is handled with :class:`decimal.Decimal` throughout (never float), matching
the invoice/voucher money columns (``numeric``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.repositories.supplier_statement_report_repository import (
    ACCOUNT_TYPE_COUNT,
    SupplierStatementFilters,
    SupplierStatementReportRepository,
)

_MONEY_QUANT = Decimal("0.01")
_ZERO = Decimal("0.00")

# Trailing digits of a voucher number, e.g. "Paid - Sub-7" -> "7". Used only for
# the human-facing البيان / رقم المستند; the stored number is never changed.
_TRAILING_DIGITS = re.compile(r"(\d+)\s*$")


class SupplierStatementValidationError(Exception):
    """Raised for invalid filters. ``message`` is a ready-to-show Arabic string."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ReportColumn:
    """Lightweight column descriptor reused by the Excel/PDF/print exporters."""

    key: str
    label: str


@dataclass(frozen=True)
class SupplierStatementRequest:
    supplier_id: int | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass(frozen=True)
class SupplierStatementResult:
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]          # numeric rows (Decimal debit/credit/balance)
    export_rows: list[dict[str, Any]]   # formatted strings keyed by column.key
    summary: dict[str, Any]             # Decimal totals + formatted labels
    supplier_name: str | None
    is_empty: bool


# Visible columns, in the exact required order (النموذج 10). The UI renders RTL,
# so the first column (التاريخ) shows on the right — matching the chosen mockup.
REPORT_COLUMNS: tuple[ReportColumn, ...] = (
    ReportColumn("transaction_date", "التاريخ"),
    ReportColumn("supplier_name", "اسم المورد"),
    ReportColumn("document_number", "رقم المستند"),
    ReportColumn("description", "البيان"),
    ReportColumn("debit", "مدين"),
    ReportColumn("credit", "دائن"),
    ReportColumn("balance", "الرصيد"),
)

EMPTY_MESSAGE = "لا توجد حركات للمورد خلال الفترة المحددة"

# Movement kinds carried in each row's hidden ``kind`` field, so the print
# template can colour the البيان badge without re-parsing the Arabic text.
KIND_OPENING = "opening"
KIND_INVOICE = "invoice"
KIND_PAYMENT = "payment"


class SupplierStatementReportService:
    """Build the read-only Supplier Statement from purchase invoices + payments."""

    def __init__(
        self,
        repository: SupplierStatementReportRepository | None = None,
        *,
        account_type: str = ACCOUNT_TYPE_COUNT,
    ) -> None:
        # When no repository is injected, build one bound to the requested account
        # type (which also picks the matching invoice amount column). «عدد» stays
        # the default so existing callers are unchanged.
        self.repository = repository or SupplierStatementReportRepository(
            account_type=account_type
        )
        self.account_type = account_type
        self.columns = list(REPORT_COLUMNS)

    # --- public API ---------------------------------------------------------
    def fetch_report(self, request: SupplierStatementRequest) -> SupplierStatementResult:
        supplier_id = self._optional_id(request.supplier_id, "المورد المحدد غير صالح.")
        date_from, date_to = self._validate_dates(request.date_from, request.date_to)

        filters = SupplierStatementFilters(
            supplier_id=supplier_id, date_from=date_from, date_to=date_to
        )
        raw_rows = list(self.repository.fetch_statement(filters))

        # The selected supplier's name (for the header). Left None for the
        # all-suppliers view (header shows «الكل»).
        supplier_name: str | None = None
        if supplier_id is not None:
            supplier_name = self.repository.fetch_supplier_name(supplier_id)

        # Group the movements by supplier so every supplier's رصيد أول المدة heads
        # its own block and the running balance restarts from it — for a single
        # selected supplier AND for the all-suppliers view alike (the اسم المورد
        # column keeps the blocks readable). ``ordered_raw`` is opening row, then
        # that supplier's movements by date, per supplier in id order.
        ordered_raw = self._group_with_openings(raw_rows, supplier_id, supplier_name, date_from)

        rows: list[dict[str, Any]] = []
        total_debit = _ZERO
        total_credit = _ZERO
        balance = _ZERO
        for raw in ordered_raw:
            debit = self._money(raw.get("debit"))
            credit = self._money(raw.get("credit"))
            total_debit += debit
            total_credit += credit
            # A new supplier block starts with its opening row; restart the running
            # balance there so each supplier's balance is its own, not a mix.
            if raw.get("source_type") == KIND_OPENING:
                balance = _ZERO
            balance = balance + credit - debit  # supplier (payable) natural balance
            if supplier_name is None:
                supplier_name = raw.get("supplier_name") or None
            rows.append({
                "transaction_date": self._format_date(raw.get("transaction_date")),
                "supplier_name": raw.get("supplier_name") or "",
                "document_number": self._document_cell(raw),
                "description": self._description(raw),
                "debit": debit,
                "credit": credit,
                "balance": balance,
                # hidden metadata (returned by the service, not shown as a column)
                "kind": self._kind(raw.get("source_type")),
                "source_type": raw.get("source_type"),
                "invoice_status": raw.get("invoice_status"),
            })

        export_rows = [self._export_row(row) for row in rows]
        summary = {
            "total_debit": total_debit,
            "total_credit": total_credit,
            "balance": balance,
            "count": len(rows),
            "total_debit_label": self._money_text(total_debit),
            "total_credit_label": self._money_text(total_credit),
            "balance_label": self._money_text(balance),
        }
        return SupplierStatementResult(
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
        except Exception:  # noqa: BLE001 - selector options must never break the screen
            return []

    # --- grouping / opening balance ----------------------------------------
    def _group_with_openings(
        self,
        raw_rows: list[dict[str, Any]],
        supplier_id: int | None,
        supplier_name: str | None,
        date_from: str | None,
    ) -> list[dict[str, Any]]:
        """Order the movements as per-supplier blocks, each led by its opening row.

        Single supplier -> one block (shown even with no movements). All-suppliers
        -> one block per supplier that has activity, in supplier-id order, each led
        by that supplier's رصيد أول المدة. Movements inside a block are ordered by
        date, then invoice-before-payment, then id.
        """
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
                "transaction_date": date_from,   # the period start, or None
                "supplier_id": sid,
                "supplier_name": names.get(sid) or "",
                "document_number": None,
                "debit": _ZERO,
                "credit": self._money(opening),
                "voucher_description": None,
            })
            group = moves.get(sid, [])
            group.sort(key=lambda row: (
                self._format_date(row.get("transaction_date")),
                row.get("source_sequence") or 0,
                row.get("source_id") or 0,
            ))
            ordered.extend(group)
        return ordered

    # --- row logic ----------------------------------------------------------
    def _description(self, raw: dict[str, Any]) -> str:
        """The exact Arabic البيان text for each movement type."""
        source_type = raw.get("source_type")
        if source_type == KIND_OPENING:
            return "رصيد أول المدة"
        if source_type == "purchase_invoice":
            return f"فاتورة مشتريات رقم {raw.get('document_number') or ''}"
        # supplier payment voucher
        number = self._voucher_number(raw.get("document_number"))
        statement = (raw.get("voucher_description") or "").strip()
        if statement:
            return f"سند صرف رقم {number} عن {statement}"
        return f"سند صرف رقم {number}"

    def _document_cell(self, raw: dict[str, Any]) -> str:
        """رقم المستند column: invoice number as-is, voucher number cleaned to its
        trailing digits, and a dash for the opening-balance row."""
        source_type = raw.get("source_type")
        if source_type == KIND_OPENING:
            return "—"
        if source_type == "purchase_invoice":
            return str(raw.get("document_number") or "").strip() or "—"
        return self._voucher_number(raw.get("document_number"))

    @staticmethod
    def _voucher_number(raw_number: Any) -> str:
        """Human-facing voucher number: the trailing digits of the stored value
        (e.g. ``Paid - Sub-7`` -> ``7``), or the stored value when it has none."""
        text = str(raw_number or "").strip()
        match = _TRAILING_DIGITS.search(text)
        return match.group(1) if match else (text or "—")

    @staticmethod
    def _kind(source_type: Any) -> str:
        if source_type == KIND_OPENING:
            return KIND_OPENING
        if source_type == "purchase_invoice":
            return KIND_INVOICE
        return KIND_PAYMENT

    # --- money / formatting -------------------------------------------------
    @staticmethod
    def _money(value: Any) -> Decimal:
        if value is None:
            return _ZERO
        if isinstance(value, Decimal):
            return value.quantize(_MONEY_QUANT)
        return Decimal(str(value)).quantize(_MONEY_QUANT)

    @staticmethod
    def _money_text(value: Decimal) -> str:
        return f"{value:,.2f}"

    def _money_cell(self, value: Decimal) -> str:
        """A movement shows its amount only in its own column; the opposite column
        is left blank (standard statement presentation)."""
        return self._money_text(value) if value != _ZERO else ""

    @staticmethod
    def _format_date(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    def _export_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "transaction_date": row["transaction_date"],
            "supplier_name": row["supplier_name"],
            "document_number": row["document_number"],
            "description": row["description"],
            "debit": self._money_cell(row["debit"]),
            "credit": self._money_cell(row["credit"]),
            "balance": self._money_text(row["balance"]),
        }

    # --- validation ---------------------------------------------------------
    @staticmethod
    def _optional_id(value: Any, invalid_message: str) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise SupplierStatementValidationError(invalid_message) from exc

    @staticmethod
    def _validate_dates(
        date_from: str | None, date_to: str | None
    ) -> tuple[str | None, str | None]:
        start = (date_from or "").strip() or None
        end = (date_to or "").strip() or None
        if start and end and start > end:
            raise SupplierStatementValidationError(
                "نطاق التاريخ غير صحيح: يجب أن يكون تاريخ (من) أقل من أو يساوي تاريخ (إلى)."
            )
        return start, end
