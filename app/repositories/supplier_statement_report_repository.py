"""Database layer for the Supplier Statement report (كشف حساب المورد).

This is the ONLY place SQL for this report lives. It returns plain, read-only row
dicts; all Arabic descriptions, money formatting, the opening-balance row, the
running balance and the totals are computed in the service layer
(``app/services/supplier_statement_report_service.py``), and the UI never sees SQL.

Scope — count-type suppliers only
---------------------------------
Per the user's requirement, this statement is for suppliers whose نوع الحساب is
**«عدد»** (``suppliers.account_type = 'عدد'``). Every arm joins ``suppliers`` and
filters on that, so a «وزن» supplier never appears and the selector only lists
«عدد» suppliers. The invoice amount used is ``total_count_price`` («إجمالي
الفاتورة» — إجمالي سعر العدد), which is the total that matches a count account.

The statement combines two existing sources with a single ``UNION ALL`` query
(one database round-trip, all filtering done in the database — never in Python):

* ``purchase_invoices``          -> one **credit** row per invoice
  (``total_count_price``): a purchase increases what we owe the supplier, so on a
  supplier (payable) account it is a credit. ALL statuses are included (no
  ``document_status`` filter), matching the customer statement.
* ``supplier_payment_vouchers``  -> one **debit** row per voucher (``amount``):
  paying the supplier reduces what we owe, so it is a debit.

A ``UNION ALL`` (not ``UNION``) is used deliberately: an invoice and a payment
that happen to share a date/supplier/amount must never be de-duplicated. Every
movement is tagged with a stable ``source_type`` / ``source_id`` and a
``source_sequence`` (0 invoice, 1 payment) so the ordering is deterministic and
identical across preview, printing and PDF/Excel export.

Read-only contract: this module only ``SELECT``s. It never inserts, updates or
deletes any invoice, voucher or supplier row. The opening balance is read from
``suppliers.opening_balance`` and is never modified.

Filtering: ``supplier_id`` is optional (None = every «عدد» supplier); dates are
optional too (a blank bound means open-ended on that side).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.database.db import Database

# The two نوع الحساب values a supplier can carry.
ACCOUNT_TYPE_COUNT = "عدد"
ACCOUNT_TYPE_WEIGHT = "وزن"

# The purchase-invoice header total that matches each account type:
#   عدد -> total_count_price  («إجمالي الفاتورة» — إجمالي سعر العدد)
#   وزن -> total_weight_price («إجمالي الوزن»    — إجمالي سعر الوزن)
# Whitelisted because the chosen column name is interpolated into SQL below; only
# these two are ever allowed, so a caller can never inject anything else.
AMOUNT_COLUMN_BY_ACCOUNT_TYPE = {
    ACCOUNT_TYPE_COUNT: "total_count_price",
    ACCOUNT_TYPE_WEIGHT: "total_weight_price",
}
_ALLOWED_AMOUNT_COLUMNS = frozenset(AMOUNT_COLUMN_BY_ACCOUNT_TYPE.values())

_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class SupplierStatementFilters:
    """Normalised query input. ``supplier_id`` is optional (None = no restriction);
    dates are optional too (a blank bound means open-ended on that side)."""

    supplier_id: int | None = None
    date_from: str | None = None
    date_to: str | None = None


class SupplierStatementReportRepository:
    """Read-only SQL for the combined supplier statement + its lookups.

    ``account_type`` selects which suppliers the statement covers («عدد» or
    «وزن»); ``amount_column`` is the purchase-invoice total that matches it and
    defaults to the right column for that type. Both default to «عدد» so existing
    callers are unchanged.
    """

    def __init__(
        self,
        db: Database | None = None,
        *,
        account_type: str = ACCOUNT_TYPE_COUNT,
        amount_column: str | None = None,
    ) -> None:
        self.db = db or Database()
        self.account_type = account_type
        column = amount_column or AMOUNT_COLUMN_BY_ACCOUNT_TYPE.get(
            account_type, "total_count_price"
        )
        if column not in _ALLOWED_AMOUNT_COLUMNS:
            raise ValueError(f"Unsupported invoice amount column: {column!r}")
        self.amount_column = column

    # --- combined statement -------------------------------------------------
    def fetch_statement(self, filters: SupplierStatementFilters) -> list[dict[str, Any]]:
        """Return every invoice + payment movement for the «عدد» suppliers, ordered.

        Ordering is done in SQL on the real ``transaction_date`` (a DATE, not a
        formatted string), then invoices before payments on the same day (by
        ``source_sequence``), then by ``source_id`` — fully deterministic and
        identical for preview, printing and PDF/Excel export.
        """

        def _conditions(
            supplier_col: str, date_col: str, *, timestamp: bool
        ) -> tuple[str, list[Any]]:
            conditions: list[str] = []
            params: list[Any] = []
            if filters.supplier_id is not None:
                conditions.append(f"{supplier_col} = %s")
                params.append(int(filters.supplier_id))
            if filters.date_from:
                conditions.append(f"{date_col} >= %s::date")
                params.append(filters.date_from)
            if filters.date_to:
                if timestamp:
                    conditions.append(f"{date_col} < (%s::date + INTERVAL '1 day')")
                else:
                    conditions.append(f"{date_col} <= %s::date")
                params.append(filters.date_to)
            return (" AND ".join(conditions) if conditions else "TRUE"), params

        invoice_where, invoice_params = _conditions(
            "pi.supplier_id", "pi.issue_datetime", timestamp=True
        )
        voucher_where, voucher_params = _conditions(
            "spv.supplier_id", "spv.voucher_date", timestamp=False
        )

        sql = f"""
            WITH invoice_rows AS (
                SELECT
                    'purchase_invoice'::text          AS source_type,
                    pi.id                             AS source_id,
                    0                                 AS source_sequence,
                    pi.issue_datetime::date           AS transaction_date,
                    pi.supplier_id                    AS supplier_id,
                    COALESCE(s.supplier_name, pi.supplier_name_snapshot)::text AS supplier_name,
                    pi.invoice_number::text           AS document_number,
                    0::numeric                        AS debit,
                    pi.{self.amount_column}::numeric  AS credit,
                    pi.document_status::text          AS invoice_status,
                    NULL::text                        AS voucher_description
                FROM purchase_invoices pi
                JOIN suppliers s ON s.supplier_id = pi.supplier_id
                WHERE s.account_type = %s AND {invoice_where}
            ),
            voucher_rows AS (
                SELECT
                    'supplier_payment_voucher'::text  AS source_type,
                    spv.id                            AS source_id,
                    1                                 AS source_sequence,
                    spv.voucher_date                  AS transaction_date,
                    spv.supplier_id                   AS supplier_id,
                    s.supplier_name::text             AS supplier_name,
                    spv.voucher_number::text          AS document_number,
                    spv.amount::numeric               AS debit,
                    0::numeric                        AS credit,
                    NULL::text                        AS invoice_status,
                    spv.description::text             AS voucher_description
                FROM supplier_payment_vouchers spv
                JOIN suppliers s ON s.supplier_id = spv.supplier_id
                WHERE s.account_type = %s AND {voucher_where}
            ),
            combined AS (
                SELECT * FROM invoice_rows
                UNION ALL
                SELECT * FROM voucher_rows
            )
            SELECT
                source_type, source_id, source_sequence, transaction_date,
                supplier_id, supplier_name, document_number, debit, credit,
                invoice_status, voucher_description
            FROM combined
            ORDER BY transaction_date ASC,
                     source_sequence ASC,
                     source_id ASC
        """
        # Param order matches the two arms: the account-type literal precedes each
        # arm's own WHERE params (invoices first, then vouchers).
        params = (
            [self.account_type] + invoice_params
            + [self.account_type] + voucher_params
        )
        return self.db.fetch_all(sql, params)

    # --- item-level (ledger) statement -------------------------------------
    def fetch_statement_lines(self, filters: SupplierStatementFilters) -> list[dict[str, Any]]:
        """Return one row per purchase-invoice **line** (item) + one row per payment.

        Each purchase invoice is expanded into its ``purchase_invoice_lines`` (اسم
        الصنف / الكمية / السعر / القيمة), so the ledger shows item detail instead of
        a single invoice total. Payments (سندات الصرف) come through as collection
        rows. Ordering keeps a supplier's rows together, an invoice's lines together
        and, on the same day, invoice lines before payments — deterministic across
        preview, print and export. Read-only (SELECT only)."""

        def _conditions(
            supplier_col: str, date_col: str, *, timestamp: bool
        ) -> tuple[str, list[Any]]:
            conditions: list[str] = []
            params: list[Any] = []
            if filters.supplier_id is not None:
                conditions.append(f"{supplier_col} = %s")
                params.append(int(filters.supplier_id))
            if filters.date_from:
                conditions.append(f"{date_col} >= %s::date")
                params.append(filters.date_from)
            if filters.date_to:
                if timestamp:
                    conditions.append(f"{date_col} < (%s::date + INTERVAL '1 day')")
                else:
                    conditions.append(f"{date_col} <= %s::date")
                params.append(filters.date_to)
            return (" AND ".join(conditions) if conditions else "TRUE"), params

        invoice_where, invoice_params = _conditions(
            "pi.supplier_id", "pi.issue_datetime", timestamp=True
        )
        voucher_where, voucher_params = _conditions(
            "spv.supplier_id", "spv.voucher_date", timestamp=False
        )

        sql = f"""
            WITH invoice_line_rows AS (
                SELECT
                    'purchase_invoice_line'::text     AS source_type,
                    0                                 AS order_seq,
                    pi.id                             AS group_id,
                    pil.line_number                   AS line_number,
                    pi.issue_datetime::date           AS transaction_date,
                    pi.supplier_id                    AS supplier_id,
                    COALESCE(s.supplier_name, pi.supplier_name_snapshot)::text AS supplier_name,
                    pi.invoice_number::text           AS movement_number,
                    pil.item_name_snapshot::text      AS item_name,
                    pil.item_count::numeric           AS item_count,
                    pil.unit_weight::numeric          AS unit_weight,
                    pil.total_weight::numeric         AS total_weight,
                    pil.unit_price::numeric           AS unit_price,
                    pil.count_price_total::numeric    AS count_price_total,
                    pil.weight_price_total::numeric   AS weight_price_total,
                    0::numeric                        AS collections,
                    pi.document_status::text          AS invoice_status,
                    NULL::text                        AS voucher_description
                FROM purchase_invoice_lines pil
                JOIN purchase_invoices pi ON pi.id = pil.invoice_id
                JOIN suppliers s ON s.supplier_id = pi.supplier_id
                WHERE s.account_type = %s AND {invoice_where}
            ),
            voucher_rows AS (
                SELECT
                    'supplier_payment_voucher'::text  AS source_type,
                    1                                 AS order_seq,
                    spv.id                            AS group_id,
                    0                                 AS line_number,
                    spv.voucher_date                  AS transaction_date,
                    spv.supplier_id                   AS supplier_id,
                    s.supplier_name::text             AS supplier_name,
                    spv.voucher_number::text          AS movement_number,
                    NULL::text                        AS item_name,
                    NULL::numeric                     AS item_count,
                    NULL::numeric                     AS unit_weight,
                    NULL::numeric                     AS total_weight,
                    NULL::numeric                     AS unit_price,
                    NULL::numeric                     AS count_price_total,
                    NULL::numeric                     AS weight_price_total,
                    spv.amount::numeric               AS collections,
                    NULL::text                        AS invoice_status,
                    spv.description::text             AS voucher_description
                FROM supplier_payment_vouchers spv
                JOIN suppliers s ON s.supplier_id = spv.supplier_id
                WHERE s.account_type = %s AND {voucher_where}
            ),
            combined AS (
                SELECT * FROM invoice_line_rows
                UNION ALL
                SELECT * FROM voucher_rows
            )
            SELECT
                source_type, order_seq, group_id, line_number, transaction_date,
                supplier_id, supplier_name, movement_number, item_name,
                item_count, unit_weight, total_weight, unit_price,
                count_price_total, weight_price_total, collections,
                invoice_status, voucher_description
            FROM combined
            ORDER BY supplier_id ASC,
                     transaction_date ASC,
                     order_seq ASC,
                     group_id ASC,
                     line_number ASC
        """
        params = (
            [self.account_type] + invoice_params
            + [self.account_type] + voucher_params
        )
        return self.db.fetch_all(sql, params)

    # --- lookups (read-only) -----------------------------------------------
    def fetch_supplier_options(self, limit: int = 500) -> list[dict[str, Any]]:
        """Searchable supplier selector source (id + display label).

        Only suppliers of this repository's ``account_type`` are listed, so the
        wrong-type supplier can never be chosen; the stored/filter value is always
        the supplier id.
        """
        rows = self.db.fetch_all(
            "SELECT supplier_id AS id, supplier_name, mobile "
            "FROM suppliers WHERE account_type = %s "
            "ORDER BY supplier_id ASC LIMIT %s",
            [self.account_type, int(limit)],
        )
        options: list[dict[str, Any]] = []
        for row in rows:
            name = (row.get("supplier_name") or "").strip()
            mobile = (row.get("mobile") or "").strip()
            label = " - ".join(p for p in (name, mobile) if p) or str(row.get("id") or "")
            options.append({"id": row.get("id"), "label": label})
        return options

    def fetch_supplier_name(self, supplier_id: int) -> str | None:
        row = self.db.fetch_one(
            "SELECT supplier_name FROM suppliers WHERE supplier_id = %s",
            [int(supplier_id)],
        )
        if not row:
            return None
        return (row.get("supplier_name") or "").strip() or None

    def fetch_supplier_openings(self, supplier_ids: list[int]) -> dict[int, Decimal]:
        """Opening balances for several suppliers at once, ``{id: Decimal}``.

        Used by the all-suppliers view, which prepends every listed supplier's
        رصيد أول المدة. Read-only; missing/NULL balances resolve to 0.
        """
        ids = [int(s) for s in supplier_ids if s is not None]
        if not ids:
            return {}
        rows = self.db.fetch_all(
            "SELECT supplier_id, opening_balance FROM suppliers "
            "WHERE supplier_id = ANY(%s)",
            [ids],
        )
        out: dict[int, Decimal] = {}
        for row in rows:
            value = row.get("opening_balance")
            try:
                out[row.get("supplier_id")] = (
                    Decimal(str(value)) if value is not None else _ZERO
                )
            except Exception:  # noqa: BLE001
                out[row.get("supplier_id")] = _ZERO
        return out

    def fetch_supplier_opening_balance(self, supplier_id: int) -> Decimal:
        """The supplier's رصيد أول المدة, or 0 when unset/missing.

        Read-only: the opening balance shown on the statement is exactly the value
        stored on the supplier; this report never writes it back.
        """
        row = self.db.fetch_one(
            "SELECT opening_balance FROM suppliers WHERE supplier_id = %s",
            [int(supplier_id)],
        )
        if not row or row.get("opening_balance") is None:
            return _ZERO
        try:
            return Decimal(str(row.get("opening_balance")))
        except Exception:  # noqa: BLE001 - a bad stored value must not break the report
            return _ZERO
