"""Database access for the Production Order module (أمر الإنتاج).

All SQL for the two ``production_order`` tables (and the read-only product /
BOM lookups the service needs) lives here; the service and UI never touch the
database directly. Built on the shared psycopg ``Database`` helper, mirroring
``BomRepository`` / ``PurchaseInvoiceRepository``.

BOM consumption
---------------
Production Orders do **not** duplicate BOM logic. All BOM reads are delegated to
:class:`BomRepository` (bound to the same ``Database`` connection, so a
search-path-bound test schema is honoured for BOM reads too):

* :meth:`find_boms_for_product` -> ``BomRepository.search_boms(product_id=...)``
* :meth:`load_bom`             -> ``BomRepository.load_bom(...)``

Safety contract
---------------
* The two tables are created idempotently by ``PRODUCTION_ORDER_SCHEMA_SQL`` (via
  :meth:`ensure_schema`), mirrored by ``full_schema.sql`` and migration 033.
* Reads and searches go through the shared autocommit ``Database`` helper.
* Writes that must be atomic (save / update / delete) run inside a single
  short-lived psycopg transaction (``_txn``) that commits on success and rolls
  back on any error — so a failing detail row never leaves an orphan header or
  partial lines.
* Automatic order numbers come from the PostgreSQL sequence
  ``production_order_number_seq`` via ``nextval`` (atomic — two devices creating
  an order at the same instant get different numbers). The UNIQUE index
  ``uq_production_orders_order_number`` is the final guard; a saved manual
  ``PRO-<n>`` bumps the sequence past ``<n>`` so a future automatic number can
  never collide. The next number is never ``MAX(order_number) + 1``.
"""

from __future__ import annotations

from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from app.config.database import build_database_url, runtime_connect_kwargs
from app.config.settings import get_settings
from app.database.db import Database
from app.models.production_order import (
    FIRST_PRO_SEQ,
    LINE_INSERT_COLUMNS,
    LINE_SELECT_COLUMNS,
    ORDER_INSERT_COLUMNS,
    ORDER_SELECT_COLUMNS,
    PRO_NUMBER_SEQUENCE,
    PRODUCTION_ORDER_SCHEMA_SQL,
    TBL_PRODUCTION_ORDER_LINES,
    TBL_PRODUCTION_ORDERS,
    format_number,
    parse_sequence_value,
)
from app.repositories.bom_repository import BomRepository

_ORDER_SELECT = ", ".join(ORDER_SELECT_COLUMNS)
_LINE_SELECT = ", ".join(LINE_SELECT_COLUMNS)
# A distinct advisory-lock key so Production Order numbering never contends with
# BOM / sales / purchase numbering.
_PRO_NUMBER_LOCK_KEY = 824_502_004


class ProductionOrderRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        # BOM reads reuse BomRepository bound to the SAME Database connection, so a
        # search-path-bound (test) schema is honoured for BOM reads too. No BOM SQL
        # is duplicated here.
        self.bom_repository = BomRepository(self.db)
        # Plain-psycopg URL for opening short-lived transactional connections.
        self._url = build_database_url(get_settings()).replace(
            "postgresql+psycopg://", "postgresql://"
        )

    # -- schema --------------------------------------------------------------
    def ensure_schema(self) -> None:
        """Create the tables + sequence + indexes + trigger if missing (safe to repeat).

        The BOM tables are a hard dependency (``bom_id`` FK), so ensure them first.
        """
        self.bom_repository.ensure_schema()
        self.db.execute_script(PRODUCTION_ORDER_SCHEMA_SQL)

    # -- transactional connection -------------------------------------------
    def _txn(self) -> psycopg.Connection:
        """Open a NON-autocommit connection (commit/rollback + close via ``with``)."""
        return psycopg.connect(self._url, row_factory=dict_row, **runtime_connect_kwargs())

    # ======================================================================
    # Master data — products (read-only lookups)
    # ======================================================================
    def get_product(self, product_id: int) -> dict[str, Any] | None:
        """Return the item master row the service needs for validation/snapshot."""
        return self.db.fetch_one(
            "SELECT id, item_code, item_name, unit, item_type, price "
            "FROM products WHERE id = %s",
            [int(product_id)],
        )

    def search_products(self, keyword: str, limit: int = 100) -> list[dict[str, Any]]:
        """Products for the finished-product lookup popup (id + code + name + unit)."""
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
    # BOM consumption (delegated to BomRepository — no BOM logic duplicated)
    # ======================================================================
    def find_boms_for_product(
        self, product_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """All BOMs whose finished product is ``product_id`` (most recent first)."""
        return self.bom_repository.search_boms(product_id=int(product_id), limit=limit)

    def load_bom(self, bom_id: int) -> dict[str, Any] | None:
        """Load a full BOM (``{"header", "lines"}``) via the BOM repository."""
        return self.bom_repository.load_bom(int(bom_id))

    # ======================================================================
    # Order numbering ("PRO-<seq>", starts PRO-001)
    # ======================================================================
    def order_number_exists(
        self, order_number: str, exclude_id: int | None = None
    ) -> bool:
        """True if ``order_number`` is already used (optionally ignoring one row id)."""
        if exclude_id is None:
            row = self.db.fetch_one(
                f"SELECT 1 FROM {TBL_PRODUCTION_ORDERS} WHERE order_number = %s LIMIT 1",
                [order_number],
            )
        else:
            row = self.db.fetch_one(
                f"SELECT 1 FROM {TBL_PRODUCTION_ORDERS} "
                "WHERE order_number = %s AND id <> %s LIMIT 1",
                [order_number, int(exclude_id)],
            )
        return row is not None

    def peek_next_number(self) -> str:
        """Advisory next automatic number for pre-filling a form (not a reservation)."""
        row = self.db.fetch_one(
            f"SELECT last_value, is_called FROM {PRO_NUMBER_SEQUENCE}"
        )
        if not row or row.get("last_value") is None:
            return format_number(FIRST_PRO_SEQ)
        last_value = int(row["last_value"])
        candidate = last_value + 1 if row.get("is_called") else last_value
        return format_number(max(candidate, FIRST_PRO_SEQ))

    def reserve_order_number(self) -> str:
        """Atomically reserve the next unused automatic number, e.g. ``'PRO-001'``."""
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", [_PRO_NUMBER_LOCK_KEY])
                while True:
                    cur.execute(f"SELECT nextval('{PRO_NUMBER_SEQUENCE}') AS n")
                    candidate = format_number(cur.fetchone()["n"])
                    cur.execute(
                        f"SELECT 1 FROM {TBL_PRODUCTION_ORDERS} "
                        "WHERE order_number = %s LIMIT 1",
                        [candidate],
                    )
                    if cur.fetchone() is None:
                        return candidate

    @staticmethod
    def _sync_order_number_sequence(cur: psycopg.Cursor, order_number: object) -> None:
        """Move the automatic sequence forward for a higher manual numeric value.

        A saved ``PRO-<n>`` with ``n`` at or above the sequence's current position
        advances the sequence so the next automatic number never collides with it.
        A lower or non-standard manual number never moves the sequence backward.
        """
        value = parse_sequence_value(order_number)
        if value is None or value < FIRST_PRO_SEQ:
            return

        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_PRO_NUMBER_LOCK_KEY])
        cur.execute(f"SELECT last_value, is_called FROM {PRO_NUMBER_SEQUENCE}")
        state = cur.fetchone()
        last_value = int(state["last_value"])
        is_called = bool(state["is_called"])
        if value > last_value or (value == last_value and not is_called):
            cur.execute(f"SELECT setval('{PRO_NUMBER_SEQUENCE}', %s, true)", [value])

    # ======================================================================
    # Load / list
    # ======================================================================
    def load_order(self, order_id: int) -> dict[str, Any] | None:
        header = self.db.fetch_one(
            f"SELECT {_ORDER_SELECT} FROM {TBL_PRODUCTION_ORDERS} WHERE id = %s",
            [int(order_id)],
        )
        if header is None:
            return None
        lines = self.db.fetch_all(
            f"SELECT {_LINE_SELECT} FROM {TBL_PRODUCTION_ORDER_LINES} "
            "WHERE production_order_id = %s ORDER BY line_number",
            [int(order_id)],
        )
        return {"header": header, "lines": lines}

    def load_order_by_number(self, order_number: str) -> dict[str, Any] | None:
        header = self.db.fetch_one(
            f"SELECT id FROM {TBL_PRODUCTION_ORDERS} WHERE order_number = %s",
            [order_number],
        )
        return None if header is None else self.load_order(int(header["id"]))

    def search_orders(
        self,
        keyword: str = "",
        limit: int = 300,
        *,
        product_id: int | None = None,
        date_from: Any = None,
        date_to: Any = None,
    ) -> list[dict[str, Any]]:
        """Lightweight header summaries for the later Search/Open UI (server-side)."""
        sql = (
            "SELECT id, order_number, order_date, product_id, product_name_snapshot, "
            f"bom_id, production_quantity FROM {TBL_PRODUCTION_ORDERS}"
        )
        conds: list[str] = []
        params: list[Any] = []
        kw = (keyword or "").strip()
        if kw:
            like = f"%{kw}%"
            conds.append("(order_number ILIKE %s OR product_name_snapshot ILIKE %s)")
            params += [like, like]
        if product_id is not None:
            conds.append("product_id = %s")
            params.append(int(product_id))
        if date_from is not None:
            conds.append("order_date >= %s")
            params.append(date_from)
        if date_to is not None:
            conds.append("order_date <= %s")
            params.append(date_to)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(int(limit))
        return self.db.fetch_all(sql, params)

    # ======================================================================
    # Writes (transactional)
    # ======================================================================
    def insert_order(
        self, header: dict[str, Any], lines: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Insert a header + its lines in ONE transaction (rolls back on any error)."""
        collist = ", ".join(ORDER_INSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(ORDER_INSERT_COLUMNS))
        values = [header.get(col) for col in ORDER_INSERT_COLUMNS]
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {TBL_PRODUCTION_ORDERS} ({collist}) "
                    f"VALUES ({placeholders}) RETURNING {_ORDER_SELECT}",
                    values,
                )
                stored = cur.fetchone()
                order_id = stored["id"]
                self._sync_order_number_sequence(cur, stored["order_number"])
                self._insert_lines(cur, order_id, lines)
        return self.load_order(order_id)

    def update_order(
        self,
        order_id: int,
        header_changes: dict[str, Any],
        lines: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Update a header + replace its lines atomically.

        Returns the reloaded order, or ``None`` if no header with ``order_id`` exists.
        """
        set_cols = list(header_changes.keys())
        assignments = ", ".join(f"{col} = %s" for col in set_cols)
        params: list[Any] = [header_changes[col] for col in set_cols]
        params.append(int(order_id))
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {TBL_PRODUCTION_ORDERS} SET {assignments}, updated_at = now() "
                    f"WHERE id = %s RETURNING {_ORDER_SELECT}",
                    params,
                )
                stored = cur.fetchone()
                if stored is None:
                    return None
                self._sync_order_number_sequence(cur, stored["order_number"])
                cur.execute(
                    f"DELETE FROM {TBL_PRODUCTION_ORDER_LINES} "
                    "WHERE production_order_id = %s",
                    [int(order_id)],
                )
                self._insert_lines(cur, order_id, lines)
        return self.load_order(order_id)

    def delete_order(self, order_id: int) -> bool:
        """Delete one order (its lines cascade). Returns True if a row was deleted."""
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {TBL_PRODUCTION_ORDERS} WHERE id = %s RETURNING id",
                    [int(order_id)],
                )
                return cur.fetchone() is not None

    # -- internal insert helper ---------------------------------------------
    def _insert_lines(
        self, cur: psycopg.Cursor, order_id: int, lines: Iterable[dict[str, Any]]
    ) -> None:
        collist = ", ".join(LINE_INSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(LINE_INSERT_COLUMNS))
        for index, line in enumerate(lines, start=1):
            row = dict(line)
            row["production_order_id"] = order_id
            row["line_number"] = index
            cur.execute(
                f"INSERT INTO {TBL_PRODUCTION_ORDER_LINES} ({collist}) "
                f"VALUES ({placeholders})",
                [row.get(col) for col in LINE_INSERT_COLUMNS],
            )


__all__ = ["ProductionOrderRepository"]
