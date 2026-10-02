"""Database access for the Loading Voucher module (سند تحميل).

All SQL for the ``loading_vouchers`` table (and the read-only customer / product
lookups the service needs) lives here; the service and UI never touch the
database directly. Built on the shared psycopg ``Database`` helper, mirroring
``ProductionOrderRepository`` / ``ReceiptVoucherRepository``.

Safety contract
---------------
* The table is created idempotently by ``LOADING_VOUCHERS_SCHEMA_SQL`` (via
  :meth:`ensure_schema`), mirrored by ``full_schema.sql`` and migration 034.
* Reads and searches go through the shared autocommit ``Database`` helper.
* Writes that must be atomic (save / update / delete) run inside a single
  short-lived psycopg transaction (``_txn``) that commits on success and rolls
  back on any error.
* Automatic voucher numbers come from the PostgreSQL sequence
  ``loading_voucher_number_seq`` via ``nextval`` (atomic — two devices creating a
  voucher at the same instant get different numbers). The UNIQUE index
  ``uq_loading_vouchers_voucher_number`` is the final guard; a saved manual
  ``LV-<n>`` bumps the sequence past ``<n>`` so a future automatic number can never
  collide. The next number is never ``MAX(voucher_number) + 1``.

This is a single-item flat document — there is no detail-line table.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config.database import build_database_url, runtime_connect_kwargs
from app.config.settings import get_settings
from app.database.db import Database
from app.models.loading_voucher import (
    FIRST_LV_SEQ,
    LOADING_VOUCHERS_SCHEMA_SQL,
    LV_NUMBER_SEQUENCE,
    TBL_LOADING_VOUCHERS,
    VOUCHER_INSERT_COLUMNS,
    VOUCHER_SELECT_COLUMNS,
    format_number,
    parse_sequence_value,
)

_VOUCHER_SELECT = ", ".join(VOUCHER_SELECT_COLUMNS)
# A distinct advisory-lock key so Loading Voucher numbering never contends with
# BOM / sales / purchase / production-order numbering.
_LV_NUMBER_LOCK_KEY = 824_503_001


class LoadingVoucherRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        # Plain-psycopg URL for opening short-lived transactional connections.
        self._url = build_database_url(get_settings()).replace(
            "postgresql+psycopg://", "postgresql://"
        )

    # -- schema --------------------------------------------------------------
    def ensure_schema(self) -> None:
        """Create the table + sequence + function + indexes + trigger if missing.

        Safe to run repeatedly. ``customers`` / ``products`` / ``app_users`` are hard
        FK dependencies and are expected to exist already (created by the core /
        products / security schema bootstrap).
        """
        self.db.execute_script(LOADING_VOUCHERS_SCHEMA_SQL)

    # -- transactional connection -------------------------------------------
    def _txn(self) -> psycopg.Connection:
        """Open a NON-autocommit connection (commit/rollback + close via ``with``)."""
        return psycopg.connect(self._url, row_factory=dict_row, **runtime_connect_kwargs())

    # ======================================================================
    # Master data — customers (read-only lookups; FK by customer_id)
    # ======================================================================
    def get_customer(self, customer_id: int) -> dict[str, Any] | None:
        """Return the customer master row the service needs for validation/snapshot."""
        return self.db.fetch_one(
            "SELECT customer_id, customer_name, phone_number "
            "FROM customers WHERE customer_id = %s",
            [int(customer_id)],
        )

    def search_customers(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Customers for the lookup popup (server-side ILIKE + LIMIT, never load-all)."""
        kw = (keyword or "").strip()
        if kw == "":
            return self.db.fetch_all(
                "SELECT customer_id, customer_name, phone_number FROM customers "
                "ORDER BY customer_id LIMIT %s",
                [int(limit)],
            )
        like = f"%{kw}%"
        return self.db.fetch_all(
            "SELECT customer_id, customer_name, phone_number FROM customers "
            "WHERE COALESCE(customer_name, '') ILIKE %s "
            "OR CAST(customer_id AS text) LIKE %s "
            "OR COALESCE(CAST(phone_number AS text), '') ILIKE %s "
            "ORDER BY customer_id LIMIT %s",
            [like, f"{kw}%", like, int(limit)],
        )

    # ======================================================================
    # Master data — products (read-only lookups; FK by id)
    # ======================================================================
    def get_product(self, product_id: int) -> dict[str, Any] | None:
        """Return the item master row the service needs for validation/snapshot."""
        return self.db.fetch_one(
            "SELECT id, item_code, item_name, unit, item_type, price "
            "FROM products WHERE id = %s",
            [int(product_id)],
        )

    def search_products(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Products for the item lookup popup (id + code + name + unit)."""
        kw = (keyword or "").strip()
        if kw == "":
            return self.db.fetch_all(
                "SELECT id, item_code, item_name, unit, item_type, price FROM products "
                "ORDER BY item_code LIMIT %s",
                [int(limit)],
            )
        like = f"%{kw}%"
        return self.db.fetch_all(
            "SELECT id, item_code, item_name, unit, item_type, price FROM products "
            "WHERE item_name ILIKE %s OR CAST(item_code AS text) LIKE %s "
            "ORDER BY item_code LIMIT %s",
            [like, f"{kw}%", int(limit)],
        )

    # ======================================================================
    # Company letterhead (read-only; the single/first registered company)
    # ======================================================================
    def fetch_company_letterhead(self) -> dict[str, Any] | None:
        """Return the first company's letterhead fields for the printout.

        Reads the earliest ``companies`` row (``ORDER BY id LIMIT 1``) — the app
        registers one company in the first record. Returns the Arabic/English
        names, phone, address and the embedded logo (raw bytes + mime) so the
        print layer can build the ``data:`` URI, or ``None`` when no company is
        registered. Defensive: any read error (e.g. a not-yet-provisioned phone
        column on a stale database) yields ``None`` so printing never breaks.
        """
        try:
            return self.db.fetch_one(
                "SELECT id, name_ar, name_en, phone, address_ar, address_en, "
                "logo, logo_mime FROM companies ORDER BY id LIMIT 1"
            )
        except Exception:  # noqa: BLE001 - letterhead is optional; never block print
            return None

    # ======================================================================
    # Voucher numbering ("LV-<seq>", starts LV-001)
    # ======================================================================
    def voucher_number_exists(
        self, voucher_number: str, exclude_id: int | None = None
    ) -> bool:
        """True if ``voucher_number`` is already used (optionally ignoring one row id)."""
        if exclude_id is None:
            row = self.db.fetch_one(
                f"SELECT 1 FROM {TBL_LOADING_VOUCHERS} WHERE voucher_number = %s LIMIT 1",
                [voucher_number],
            )
        else:
            row = self.db.fetch_one(
                f"SELECT 1 FROM {TBL_LOADING_VOUCHERS} "
                "WHERE voucher_number = %s AND id <> %s LIMIT 1",
                [voucher_number, int(exclude_id)],
            )
        return row is not None

    def peek_next_number(self) -> str:
        """Advisory next automatic number for pre-filling a form (not a reservation)."""
        row = self.db.fetch_one(
            f"SELECT last_value, is_called FROM {LV_NUMBER_SEQUENCE}"
        )
        if not row or row.get("last_value") is None:
            return format_number(FIRST_LV_SEQ)
        last_value = int(row["last_value"])
        candidate = last_value + 1 if row.get("is_called") else last_value
        return format_number(max(candidate, FIRST_LV_SEQ))

    def reserve_voucher_number(self) -> str:
        """Atomically reserve the next unused automatic number, e.g. ``'LV-001'``."""
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", [_LV_NUMBER_LOCK_KEY])
                while True:
                    cur.execute(f"SELECT nextval('{LV_NUMBER_SEQUENCE}') AS n")
                    candidate = format_number(cur.fetchone()["n"])
                    cur.execute(
                        f"SELECT 1 FROM {TBL_LOADING_VOUCHERS} "
                        "WHERE voucher_number = %s LIMIT 1",
                        [candidate],
                    )
                    if cur.fetchone() is None:
                        return candidate

    @staticmethod
    def _sync_voucher_number_sequence(
        cur: psycopg.Cursor, voucher_number: object
    ) -> None:
        """Move the automatic sequence forward for a higher manual numeric value.

        A saved ``LV-<n>`` with ``n`` at or above the sequence's current position
        advances the sequence so the next automatic number never collides with it.
        A lower or non-standard manual number never moves the sequence backward.
        """
        value = parse_sequence_value(voucher_number)
        if value is None or value < FIRST_LV_SEQ:
            return

        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_LV_NUMBER_LOCK_KEY])
        cur.execute(f"SELECT last_value, is_called FROM {LV_NUMBER_SEQUENCE}")
        state = cur.fetchone()
        last_value = int(state["last_value"])
        is_called = bool(state["is_called"])
        if value > last_value or (value == last_value and not is_called):
            cur.execute(f"SELECT setval('{LV_NUMBER_SEQUENCE}', %s, true)", [value])

    # ======================================================================
    # Load / list
    # ======================================================================
    def load_voucher(self, voucher_id: int) -> dict[str, Any] | None:
        return self.db.fetch_one(
            f"SELECT {_VOUCHER_SELECT} FROM {TBL_LOADING_VOUCHERS} WHERE id = %s",
            [int(voucher_id)],
        )

    def load_voucher_by_number(self, voucher_number: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            f"SELECT {_VOUCHER_SELECT} FROM {TBL_LOADING_VOUCHERS} "
            "WHERE voucher_number = %s",
            [voucher_number],
        )

    def search_vouchers(
        self,
        keyword: str = "",
        limit: int = 300,
        *,
        customer_id: int | None = None,
        date_from: Any = None,
        date_to: Any = None,
    ) -> list[dict[str, Any]]:
        """Lightweight summaries for the later Search/Open UI (server-side)."""
        sql = (
            "SELECT id, voucher_number, voucher_date, voucher_time, customer_id, "
            "customer_name_snapshot, driver_name, vehicle_number, product_id, "
            f"item_name_snapshot, quantity_tons FROM {TBL_LOADING_VOUCHERS}"
        )
        conds: list[str] = []
        params: list[Any] = []
        kw = (keyword or "").strip()
        if kw:
            like = f"%{kw}%"
            conds.append(
                "(voucher_number ILIKE %s OR customer_name_snapshot ILIKE %s "
                "OR item_name_snapshot ILIKE %s OR driver_name ILIKE %s "
                "OR vehicle_number ILIKE %s)"
            )
            params += [like, like, like, like, like]
        if customer_id is not None:
            conds.append("customer_id = %s")
            params.append(int(customer_id))
        if date_from is not None:
            conds.append("voucher_date >= %s")
            params.append(date_from)
        if date_to is not None:
            conds.append("voucher_date <= %s")
            params.append(date_to)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(int(limit))
        return self.db.fetch_all(sql, params)

    # ======================================================================
    # Writes (transactional)
    # ======================================================================
    def insert_voucher(self, header: dict[str, Any]) -> dict[str, Any]:
        """Insert one voucher row. A blank ``voucher_number`` / date / time lets the
        DB column DEFAULT assign it (LV-<seq> / CURRENT_DATE / localtime)."""
        cols = [c for c in VOUCHER_INSERT_COLUMNS if c in header]
        collist = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        values = [header.get(col) for col in cols]
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {TBL_LOADING_VOUCHERS} ({collist}) "
                    f"VALUES ({placeholders}) RETURNING {_VOUCHER_SELECT}",
                    values,
                )
                stored = cur.fetchone()
                self._sync_voucher_number_sequence(cur, stored["voucher_number"])
        return stored

    def update_voucher(
        self, voucher_id: int, header_changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a voucher's writable columns atomically.

        Returns the reloaded voucher, or ``None`` if no row with ``voucher_id`` exists.
        An empty ``header_changes`` returns the current row unchanged.
        """
        if not header_changes:
            return self.load_voucher(int(voucher_id))
        set_cols = list(header_changes.keys())
        assignments = ", ".join(f"{col} = %s" for col in set_cols)
        params: list[Any] = [header_changes[col] for col in set_cols]
        params.append(int(voucher_id))
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {TBL_LOADING_VOUCHERS} SET {assignments}, updated_at = now() "
                    f"WHERE id = %s RETURNING {_VOUCHER_SELECT}",
                    params,
                )
                stored = cur.fetchone()
                if stored is None:
                    return None
                self._sync_voucher_number_sequence(cur, stored["voucher_number"])
        return stored

    def delete_voucher(self, voucher_id: int) -> bool:
        """Hard-delete one voucher. Returns True if a row was deleted."""
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {TBL_LOADING_VOUCHERS} WHERE id = %s RETURNING id",
                    [int(voucher_id)],
                )
                return cur.fetchone() is not None


__all__ = ["LoadingVoucherRepository"]
