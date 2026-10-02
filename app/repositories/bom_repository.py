"""Database access for the Bill of Materials module (قائمة المواد).

All SQL for the two ``bom`` tables (and the read-only product lookups the
service needs) lives here; the service and UI never touch the database directly.
Built on the shared psycopg ``Database`` helper, mirroring
``PurchaseInvoiceRepository``.

Safety contract
---------------
* The two tables are created idempotently by ``BOM_SCHEMA_SQL`` (via
  :meth:`ensure_schema`), mirrored by ``full_schema.sql`` and migration 032.
* Reads and searches go through the shared autocommit ``Database`` helper.
* Writes that must be atomic (save / update / delete) run inside a single
  short-lived psycopg transaction (``_txn``) that commits on success and rolls
  back on any error — so a failing detail row never leaves an orphan header or
  partial lines.
* Automatic BOM numbers come from the PostgreSQL sequence ``bom_number_seq`` via
  ``nextval`` (atomic — two devices creating a BOM at the same instant get
  different numbers). The UNIQUE index ``uq_boms_bom_number`` is the final guard;
  a saved manual ``BOM-<n>`` bumps the sequence past ``<n>`` so a future automatic
  number can never collide. The next number is never ``MAX(bom_number) + 1``.
"""

from __future__ import annotations

from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from app.config.database import build_database_url, runtime_connect_kwargs
from app.config.settings import get_settings
from app.database.db import Database
from app.models.bom import (
    BOM_INSERT_COLUMNS,
    BOM_NUMBER_SEQUENCE,
    BOM_SCHEMA_SQL,
    BOM_SELECT_COLUMNS,
    FIRST_BOM_SEQ,
    LINE_INSERT_COLUMNS,
    LINE_SELECT_COLUMNS,
    TBL_BOM_LINES,
    TBL_BOMS,
    format_number,
    parse_sequence_value,
)

_BOM_SELECT = ", ".join(BOM_SELECT_COLUMNS)
_LINE_SELECT = ", ".join(LINE_SELECT_COLUMNS)
# A distinct advisory-lock key so BOM numbering never contends with sales /
# purchase numbering.
_BOM_NUMBER_LOCK_KEY = 824_502_003


class BomRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        # Plain-psycopg URL for opening short-lived transactional connections.
        self._url = build_database_url(get_settings()).replace(
            "postgresql+psycopg://", "postgresql://"
        )

    # -- schema --------------------------------------------------------------
    def ensure_schema(self) -> None:
        """Create the tables + sequence + indexes + trigger if missing (safe to repeat)."""
        self.db.execute_script(BOM_SCHEMA_SQL)

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
        """Products for the أصناف lookup popup (id + code + name + unit + price)."""
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
    # BOM numbering ("BOM-<seq>", starts BOM-0001)
    # ======================================================================
    def bom_number_exists(self, bom_number: str, exclude_id: int | None = None) -> bool:
        """True if ``bom_number`` is already used (optionally ignoring one row id)."""
        if exclude_id is None:
            row = self.db.fetch_one(
                f"SELECT 1 FROM {TBL_BOMS} WHERE bom_number = %s LIMIT 1",
                [bom_number],
            )
        else:
            row = self.db.fetch_one(
                f"SELECT 1 FROM {TBL_BOMS} WHERE bom_number = %s AND id <> %s LIMIT 1",
                [bom_number, int(exclude_id)],
            )
        return row is not None

    def peek_next_number(self) -> str:
        """Advisory next automatic number for pre-filling a form (not a reservation)."""
        row = self.db.fetch_one(
            f"SELECT last_value, is_called FROM {BOM_NUMBER_SEQUENCE}"
        )
        if not row or row.get("last_value") is None:
            return format_number(FIRST_BOM_SEQ)
        last_value = int(row["last_value"])
        candidate = last_value + 1 if row.get("is_called") else last_value
        return format_number(max(candidate, FIRST_BOM_SEQ))

    def reserve_bom_number(self) -> str:
        """Atomically reserve the next unused automatic number, e.g. ``'BOM-0001'``."""
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", [_BOM_NUMBER_LOCK_KEY])
                while True:
                    cur.execute(f"SELECT nextval('{BOM_NUMBER_SEQUENCE}') AS n")
                    candidate = format_number(cur.fetchone()["n"])
                    cur.execute(
                        f"SELECT 1 FROM {TBL_BOMS} WHERE bom_number = %s LIMIT 1",
                        [candidate],
                    )
                    if cur.fetchone() is None:
                        return candidate

    @staticmethod
    def _sync_bom_number_sequence(cur: psycopg.Cursor, bom_number: object) -> None:
        """Move the automatic sequence forward for a higher manual numeric value.

        A saved ``BOM-<n>`` with ``n`` at or above the sequence's current position
        advances the sequence so the next automatic number never collides with it.
        A lower or non-standard manual number never moves the sequence backward.
        """
        value = parse_sequence_value(bom_number)
        if value is None or value < FIRST_BOM_SEQ:
            return

        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_BOM_NUMBER_LOCK_KEY])
        cur.execute(f"SELECT last_value, is_called FROM {BOM_NUMBER_SEQUENCE}")
        state = cur.fetchone()
        last_value = int(state["last_value"])
        is_called = bool(state["is_called"])
        if value > last_value or (value == last_value and not is_called):
            cur.execute(f"SELECT setval('{BOM_NUMBER_SEQUENCE}', %s, true)", [value])

    # ======================================================================
    # Load / list
    # ======================================================================
    def load_bom(self, bom_id: int) -> dict[str, Any] | None:
        header = self.db.fetch_one(
            f"SELECT {_BOM_SELECT} FROM {TBL_BOMS} WHERE id = %s", [int(bom_id)]
        )
        if header is None:
            return None
        lines = self.db.fetch_all(
            f"SELECT {_LINE_SELECT} FROM {TBL_BOM_LINES} WHERE bom_id = %s "
            "ORDER BY line_number",
            [int(bom_id)],
        )
        return {"header": header, "lines": lines}

    def load_bom_by_number(self, bom_number: str) -> dict[str, Any] | None:
        header = self.db.fetch_one(
            f"SELECT id FROM {TBL_BOMS} WHERE bom_number = %s", [bom_number]
        )
        return None if header is None else self.load_bom(int(header["id"]))

    def search_boms(
        self,
        keyword: str = "",
        limit: int = 300,
        *,
        product_id: int | None = None,
        date_from: Any = None,
        date_to: Any = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, bom_number, bom_date, product_id, product_name_snapshot, "
            f"total_material_cost FROM {TBL_BOMS}"
        )
        conds: list[str] = []
        params: list[Any] = []
        kw = (keyword or "").strip()
        if kw:
            like = f"%{kw}%"
            conds.append("(bom_number ILIKE %s OR product_name_snapshot ILIKE %s)")
            params += [like, like]
        if product_id is not None:
            conds.append("product_id = %s")
            params.append(int(product_id))
        if date_from is not None:
            conds.append("bom_date >= %s")
            params.append(date_from)
        if date_to is not None:
            conds.append("bom_date <= %s")
            params.append(date_to)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(int(limit))
        return self.db.fetch_all(sql, params)

    # ======================================================================
    # Writes (transactional)
    # ======================================================================
    def insert_bom(
        self, header: dict[str, Any], lines: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Insert a header + its lines in ONE transaction (rolls back on any error)."""
        collist = ", ".join(BOM_INSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(BOM_INSERT_COLUMNS))
        values = [header.get(col) for col in BOM_INSERT_COLUMNS]
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {TBL_BOMS} ({collist}) VALUES ({placeholders}) "
                    f"RETURNING {_BOM_SELECT}",
                    values,
                )
                stored = cur.fetchone()
                bom_id = stored["id"]
                self._sync_bom_number_sequence(cur, stored["bom_number"])
                self._insert_lines(cur, bom_id, lines)
        return self.load_bom(bom_id)

    def update_bom(
        self,
        bom_id: int,
        header_changes: dict[str, Any],
        lines: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Update a header + replace its lines atomically.

        Returns the reloaded BOM, or ``None`` if no header with ``bom_id`` exists.
        """
        set_cols = list(header_changes.keys())
        assignments = ", ".join(f"{col} = %s" for col in set_cols)
        params: list[Any] = [header_changes[col] for col in set_cols]
        params.append(int(bom_id))
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {TBL_BOMS} SET {assignments}, updated_at = now() "
                    f"WHERE id = %s RETURNING {_BOM_SELECT}",
                    params,
                )
                stored = cur.fetchone()
                if stored is None:
                    return None
                self._sync_bom_number_sequence(cur, stored["bom_number"])
                cur.execute(
                    f"DELETE FROM {TBL_BOM_LINES} WHERE bom_id = %s", [int(bom_id)]
                )
                self._insert_lines(cur, bom_id, lines)
        return self.load_bom(bom_id)

    def delete_bom(self, bom_id: int) -> bool:
        """Delete one BOM (its lines cascade). Returns True if a row was deleted."""
        with self._txn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {TBL_BOMS} WHERE id = %s RETURNING id",
                    [int(bom_id)],
                )
                return cur.fetchone() is not None

    # -- internal insert helper ---------------------------------------------
    def _insert_lines(
        self, cur: psycopg.Cursor, bom_id: int, lines: Iterable[dict[str, Any]]
    ) -> None:
        collist = ", ".join(LINE_INSERT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(LINE_INSERT_COLUMNS))
        for index, line in enumerate(lines, start=1):
            row = dict(line)
            row["bom_id"] = bom_id
            row["line_number"] = index
            cur.execute(
                f"INSERT INTO {TBL_BOM_LINES} ({collist}) VALUES ({placeholders})",
                [row.get(col) for col in LINE_INSERT_COLUMNS],
            )


__all__ = ["BomRepository"]
