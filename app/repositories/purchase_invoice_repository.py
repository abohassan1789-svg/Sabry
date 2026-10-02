"""Database access for the purchase-invoice screen.

All SQL for the three ``purchase_invoice*`` tables (and the read-only supplier
lookups it needs) lives here; the service and UI never touch the database
directly. Built on the shared psycopg ``Database`` helper, mirroring
``SaudiSalesInvoiceRepository`` but with **no VAT and no ZATCA** — the purchase
invoice has neither.

Safety contract
---------------
* This module **never** issues DDL. The three tables are created idempotently by
  ``app/database/schema/full_schema.sql``.
* Reads and searches go through the shared autocommit ``Database`` helper.
* Writes that must be atomic (save / update / approve / delete / delete-all) run
  inside a single short-lived psycopg transaction (``_txn``) that commits on
  success and rolls back on any error.
* Supplier searches query the whole table with an ``ILIKE`` filter and only then
  apply ``LIMIT`` — so a match on record #500 is found even though only the first
  100 rows are pre-loaded into the picker.
"""

from __future__ import annotations

from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.config.database import build_database_url, runtime_connect_kwargs
from app.config.settings import get_settings
from app.database.db import Database
from app.models.purchase_invoice import (
    INVOICE_INSERT_COLUMNS,
    INVOICE_SELECT_COLUMNS,
    LINE_INSERT_COLUMNS,
    LINE_SELECT_COLUMNS,
    STATUS_APPROVED,
    STATUS_DRAFT,
    TBL_AUDIT_LOGS,
    TBL_INVOICES,
    TBL_LINES,
    format_invoice_number,
    parse_sequence_value,
)

_INV_SELECT = ", ".join(INVOICE_SELECT_COLUMNS)
_LINE_SELECT = ", ".join(LINE_SELECT_COLUMNS)
# A distinct advisory-lock key so purchase numbering never contends with sales.
_INVOICE_NUMBER_LOCK_KEY = 824_502_001
_NUMBER_SEQ = "purchase_invoice_number_seq"


class StalePurchaseInvoiceError(Exception):
    """Raised when an optimistic-concurrency update finds no matching row.

    Either another user changed the invoice (row_version moved) or it is no
    longer an editable draft.
    """


class PurchaseInvoiceRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        # Plain-psycopg URL for opening short-lived transactional connections.
        self._url = build_database_url(get_settings()).replace(
            "postgresql+psycopg://", "postgresql://"
        )

    # -- transactional connection -------------------------------------------
    def _txn(self) -> psycopg.Connection:
        """Open a NON-autocommit connection (commit/rollback + close via ``with``)."""
        return psycopg.connect(self._url, row_factory=dict_row, **runtime_connect_kwargs())

    # ======================================================================
    # Master data — suppliers
    # ======================================================================
    def list_suppliers(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT supplier_id, supplier_name, mobile, account_type FROM suppliers "
            "ORDER BY supplier_name LIMIT %s",
            [int(limit)],
        )

    def search_suppliers(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        kw = (keyword or "").strip()
        if kw == "":
            return self.list_suppliers(limit)
        like = f"%{kw}%"
        return self.db.fetch_all(
            "SELECT supplier_id, supplier_name, mobile, account_type FROM suppliers "
            "WHERE COALESCE(supplier_name,'') ILIKE %s "
            "OR CAST(supplier_id AS text) LIKE %s OR COALESCE(mobile,'') ILIKE %s "
            "ORDER BY supplier_name LIMIT %s",
            [like, f"{kw}%", like, int(limit)],
        )

    def get_supplier(self, supplier_id: int) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT supplier_id, supplier_name, mobile, account_type FROM suppliers "
            "WHERE supplier_id = %s",
            [int(supplier_id)],
        )

    def search_products(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Products for the أصناف lookup popup (id + code + name + price).

        Same shape/columns as the sales screen's product search so the shared
        picker dialog renders identically. An empty keyword lists the first rows.
        """
        kw = (keyword or "").strip()
        if kw == "":
            return self.db.fetch_all(
                "SELECT id, item_code, item_name, unit, price FROM products "
                "ORDER BY item_code LIMIT %s",
                [int(limit)],
            )
        like = f"%{kw}%"
        return self.db.fetch_all(
            "SELECT id, item_code, item_name, unit, price FROM products "
            "WHERE item_name ILIKE %s OR CAST(item_code AS text) LIKE %s "
            "ORDER BY item_code LIMIT %s",
            [like, f"{kw}%", int(limit)],
        )

    # ======================================================================
    # Global invoice numbering ("Pur-<seq>", starts Pur-1001)
    # ======================================================================
    def invoice_number_exists(
        self, invoice_number: str, exclude_id: int | None = None
    ) -> bool:
        if exclude_id is None:
            row = self.db.fetch_one(
                f"SELECT 1 FROM {TBL_INVOICES} WHERE invoice_number = %s LIMIT 1",
                [invoice_number],
            )
        else:
            row = self.db.fetch_one(
                f"SELECT 1 FROM {TBL_INVOICES} "
                "WHERE invoice_number = %s AND id <> %s LIMIT 1",
                [invoice_number, int(exclude_id)],
            )
        return row is not None

    def reserve_invoice_number(self) -> str:
        """Atomically reserve the next unused automatic number, e.g. ``'Pur-1001'``."""
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s)", [_INVOICE_NUMBER_LOCK_KEY]
                )
                while True:
                    cur.execute(f"SELECT nextval('{_NUMBER_SEQ}') AS n")
                    candidate = format_invoice_number(cur.fetchone()["n"])
                    cur.execute(
                        f"SELECT 1 FROM {TBL_INVOICES} "
                        "WHERE invoice_number = %s LIMIT 1",
                        [candidate],
                    )
                    if cur.fetchone() is None:
                        return candidate

    @staticmethod
    def _sync_invoice_number_sequence(
        cur: psycopg.Cursor, invoice_number: object
    ) -> None:
        """Move the automatic sequence forward for a higher manual numeric value.

        A saved "Pur-N" (or bare "N") with N at or above the sequence's current
        position advances the sequence so the next automatic number never
        collides with it. A lower or non-standard manual number never moves the
        sequence backward.
        """
        value = parse_sequence_value(invoice_number)
        if value is None or value < 1001:
            return

        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_INVOICE_NUMBER_LOCK_KEY])
        cur.execute(f"SELECT last_value, is_called FROM {_NUMBER_SEQ}")
        state = cur.fetchone()
        last_value = int(state["last_value"])
        is_called = bool(state["is_called"])
        if value > last_value or (value == last_value and not is_called):
            cur.execute(f"SELECT setval('{_NUMBER_SEQ}', %s, true)", [value])

    # ======================================================================
    # Load / list invoices
    # ======================================================================
    def load_invoice(self, invoice_id: int) -> dict[str, Any] | None:
        header = self.db.fetch_one(
            f"SELECT {_INV_SELECT} FROM {TBL_INVOICES} WHERE id = %s", [int(invoice_id)]
        )
        if header is None:
            return None
        lines = self.db.fetch_all(
            f"SELECT {_LINE_SELECT} FROM {TBL_LINES} WHERE invoice_id = %s "
            "ORDER BY line_number",
            [int(invoice_id)],
        )
        return {"header": header, "lines": lines}

    def search_invoices(
        self,
        keyword: str = "",
        status: str | None = None,
        limit: int = 300,
        *,
        supplier_id: int | None = None,
        date_from: Any = None,
        date_to: Any = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, invoice_number, supplier_id, supplier_name_snapshot, "
            "issue_datetime, document_status, total_count_price, total_weight_price "
            f"FROM {TBL_INVOICES}"
        )
        conds: list[str] = []
        params: list[Any] = []
        kw = (keyword or "").strip()
        if kw:
            like = f"%{kw}%"
            conds.append(
                "(invoice_number ILIKE %s OR supplier_name_snapshot ILIKE %s)"
            )
            params += [like, like]
        if status in (STATUS_DRAFT, STATUS_APPROVED):
            conds.append("document_status = %s")
            params.append(status)
        if supplier_id is not None:
            conds.append("supplier_id = %s")
            params.append(int(supplier_id))
        # Inclusive date range on the calendar day (issue_datetime is a timestamp).
        if date_from is not None:
            conds.append("issue_datetime::date >= %s")
            params.append(date_from)
        if date_to is not None:
            conds.append("issue_datetime::date <= %s")
            params.append(date_to)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(int(limit))
        return self.db.fetch_all(sql, params)

    def count_drafts(self, supplier_id: int | None = None) -> int:
        if supplier_id is None:
            row = self.db.fetch_one(
                f"SELECT COUNT(*) AS n FROM {TBL_INVOICES} "
                f"WHERE document_status = '{STATUS_DRAFT}'"
            )
        else:
            row = self.db.fetch_one(
                f"SELECT COUNT(*) AS n FROM {TBL_INVOICES} "
                f"WHERE document_status = '{STATUS_DRAFT}' AND supplier_id = %s",
                [int(supplier_id)],
            )
        return int(row["n"]) if row else 0

    # ======================================================================
    # Writes (transactional)
    # ======================================================================
    def insert_invoice(
        self,
        header: dict[str, Any],
        lines: list[dict[str, Any]],
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a draft header + its lines (+ optional audit), one transaction."""
        collist = ", ".join(INVOICE_INSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(INVOICE_INSERT_COLUMNS))
        values = [header.get(col) for col in INVOICE_INSERT_COLUMNS]
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {TBL_INVOICES} ({collist}) VALUES ({placeholders}) "
                    f"RETURNING {_INV_SELECT}",
                    values,
                )
                stored = cur.fetchone()
                invoice_id = stored["id"]
                self._sync_invoice_number_sequence(cur, stored["invoice_number"])
                self._insert_lines(cur, invoice_id, lines)
                if audit is not None:
                    self._insert_audit(cur, invoice_id, audit)
        return self.load_invoice(invoice_id)

    def update_invoice(
        self,
        invoice_id: int,
        expected_row_version: int,
        header_changes: dict[str, Any],
        lines: list[dict[str, Any]],
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a draft's header + replace its lines atomically.

        Guarded by ``row_version`` (optimistic concurrency) and
        ``document_status = 'draft'``. Raises :class:`StalePurchaseInvoiceError`
        if no row matches (concurrent change or no longer a draft).
        """
        set_cols = list(header_changes.keys())
        assignments = ", ".join(f"{col} = %s" for col in set_cols)
        params: list[Any] = [header_changes[col] for col in set_cols]
        params += [int(invoice_id), int(expected_row_version)]
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {TBL_INVOICES} SET {assignments}, "
                    "row_version = row_version + 1, updated_at = now() "
                    f"WHERE id = %s AND row_version = %s AND document_status = '{STATUS_DRAFT}' "
                    f"RETURNING {_INV_SELECT}",
                    params,
                )
                stored = cur.fetchone()
                if stored is None:
                    raise StalePurchaseInvoiceError(
                        "الفاتورة تم تعديلها من مستخدم آخر أو لم تعد مسودة."
                    )
                self._sync_invoice_number_sequence(cur, stored["invoice_number"])
                cur.execute(
                    f"DELETE FROM {TBL_LINES} WHERE invoice_id = %s", [int(invoice_id)]
                )
                self._insert_lines(cur, invoice_id, lines)
                if audit is not None:
                    self._insert_audit(cur, invoice_id, audit)
        return self.load_invoice(invoice_id)

    def approve_invoice(
        self,
        invoice_id: int,
        expected_row_version: int,
        *,
        approved_by: int | None = None,
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Flip a draft to ``approved`` (local approval only).

        Guarded by ``row_version`` and ``document_status = 'draft'``, exactly like
        :meth:`update_invoice`, so a concurrent change or an already-approved
        invoice raises :class:`StalePurchaseInvoiceError`.
        """
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {TBL_INVOICES} SET document_status = '{STATUS_APPROVED}', "
                    "approved_at = now(), approved_by = %s, "
                    "row_version = row_version + 1, updated_at = now() "
                    f"WHERE id = %s AND row_version = %s AND document_status = '{STATUS_DRAFT}' "
                    f"RETURNING {_INV_SELECT}",
                    [approved_by, int(invoice_id), int(expected_row_version)],
                )
                stored = cur.fetchone()
                if stored is None:
                    raise StalePurchaseInvoiceError(
                        "الفاتورة تم تعديلها من مستخدم آخر أو لم تعد مسودة."
                    )
                if audit is not None:
                    self._insert_audit(cur, invoice_id, audit)
        return self.load_invoice(invoice_id)

    def delete_draft(
        self, invoice_id: int, performed_by: int | None = None
    ) -> bool:
        """Delete one invoice — draft **or approved**. Returns True if a row was
        deleted. Audit rows survive (FK is ON DELETE SET NULL) and a
        ``delete_draft`` entry is recorded with the invoice's real prior status.
        """
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {TBL_INVOICES} i "
                    f"WHERE i.id = %s "
                    "RETURNING i.id, i.invoice_number, i.supplier_id, i.document_status",
                    [int(invoice_id)],
                )
                row = cur.fetchone()
                if row is None:
                    return False
                self._insert_audit(
                    cur,
                    None,
                    {
                        "action": "delete_draft",
                        "old_status": row["document_status"],
                        "new_status": None,
                        "performed_by": performed_by,
                        "invoice_number_snapshot": row["invoice_number"],
                        "supplier_id_snapshot": row["supplier_id"],
                        "details": {"invoice_id": row["id"]},
                    },
                )
                return True

    def delete_all_eligible_drafts(
        self, supplier_id: int | None = None, performed_by: int | None = None
    ) -> dict[str, int]:
        """Delete every invoice in one transaction — drafts **and approved**.

        Returns ``{"deleted": n, "protected": 0}``. Nothing protects a purchase
        invoice from deletion any more, so *protected* is always zero.
        """
        supplier_clause = ""
        supplier_params: list[Any] = []
        if supplier_id is not None:
            supplier_clause = " WHERE i.supplier_id = %s"
            supplier_params = [int(supplier_id)]

        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {TBL_INVOICES} i"
                    f"{supplier_clause} "
                    "RETURNING i.id, i.invoice_number, i.supplier_id, i.document_status",
                    supplier_params,
                )
                deleted_rows = cur.fetchall()
                for row in deleted_rows:
                    self._insert_audit(
                        cur,
                        None,
                        {
                            "action": "delete_all_drafts",
                            "old_status": row["document_status"],
                            "new_status": None,
                            "performed_by": performed_by,
                            "invoice_number_snapshot": row["invoice_number"],
                            "supplier_id_snapshot": row["supplier_id"],
                            "details": {"invoice_id": row["id"]},
                        },
                    )
        deleted = len(deleted_rows)
        return {"deleted": deleted, "protected": 0}

    # -- internal insert helpers --------------------------------------------
    def _insert_lines(
        self, cur: psycopg.Cursor, invoice_id: int, lines: Iterable[dict[str, Any]]
    ) -> None:
        collist = ", ".join(LINE_INSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(LINE_INSERT_COLUMNS))
        for index, line in enumerate(lines, start=1):
            row = dict(line)
            row["invoice_id"] = invoice_id
            row["line_number"] = index
            cur.execute(
                f"INSERT INTO {TBL_LINES} ({collist}) VALUES ({placeholders})",
                [row.get(col) for col in LINE_INSERT_COLUMNS],
            )

    def _insert_audit(
        self, cur: psycopg.Cursor, invoice_id: int | None, audit: dict[str, Any]
    ) -> None:
        details = audit.get("details")
        cur.execute(
            f"INSERT INTO {TBL_AUDIT_LOGS} "
            "(invoice_id, invoice_number_snapshot, supplier_id_snapshot, action, "
            " old_status, new_status, performed_by, details) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                invoice_id,
                audit.get("invoice_number_snapshot"),
                audit.get("supplier_id_snapshot"),
                audit["action"],
                audit.get("old_status"),
                audit.get("new_status"),
                audit.get("performed_by"),
                Json(details) if details is not None else None,
            ],
        )


__all__ = ["PurchaseInvoiceRepository", "StalePurchaseInvoiceError"]
