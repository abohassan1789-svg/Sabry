"""Integration tests for :class:`BomRepository` against a real PostgreSQL.

These exercise the guarantees only a real database can provide:

* the BOM-number SEQUENCE (first number ``BOM-0001``, atomic increments, the DB
  DEFAULT, and a manual number pushing the sequence forward),
* the STORED generated ``line_total`` column (``quantity * price``),
* FK integrity + ``ON DELETE CASCADE`` (lines) / ``ON DELETE RESTRICT`` (products),
* the ``UNIQUE`` BOM number and ``UNIQUE (bom_id, component_product_id)`` guards,
* atomic rollback: a failing detail row leaves no orphan header and no partial lines.

Isolation: every test runs inside a throwaway schema (``bom_test_<n>``) created in
setup and ``DROP SCHEMA ... CASCADE``-d in teardown. The BOM tables, their stub
parents (``products`` via the real DDL, a minimal ``app_users``) and the sequence
are all created *inside* that schema via ``search_path``; the repository's own
transactional writes are bound to the same schema, so nothing in ``public`` (real
app data) is created, altered, or dropped. If no database is reachable the whole
module is skipped.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config.database import build_database_url, runtime_connect_kwargs
from app.config.settings import get_settings
from app.database.db import Database
from app.models.product import PRODUCTS_SCHEMA_SQL
from app.repositories.bom_repository import BomRepository

_SCHEMA_SEQ = iter(range(1, 1_000_000))


def _try_connect() -> Database | None:
    try:
        db = Database()
        db.execute("SELECT 1")
        return db
    except Exception:
        return None


_probe = _try_connect()
pytestmark = pytest.mark.skipif(
    _probe is None,
    reason="No PostgreSQL reachable (set DB_* env / .env to run BOM DB tests).",
)

# Minimal stand-in for app_users so the created_by/updated_by FKs resolve *inside*
# the throwaway schema (nothing in public is referenced or touched).
_STUB_APP_USERS_SQL = """
CREATE TABLE IF NOT EXISTS app_users (
    id integer PRIMARY KEY,
    username varchar(100)
);
INSERT INTO app_users (id, username) VALUES (1, 'tester') ON CONFLICT DO NOTHING;
"""


def _plain_url() -> str:
    return build_database_url(get_settings()).replace(
        "postgresql+psycopg://", "postgresql://"
    )


def _bound_db(schema: str) -> Database:
    """A fresh Database whose connection has search_path set to ``schema, public``."""
    db = Database()
    db.execute(f'SET search_path TO "{schema}", public')
    return db


@pytest.fixture()
def schema():
    name = f"bom_test_{next(_SCHEMA_SEQ)}_{os.getpid()}"
    admin = Database()
    admin.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        admin.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


@pytest.fixture()
def repo(schema):
    """A BomRepository whose reads AND transactional writes are bound to ``schema``."""
    db = _bound_db(schema)
    db.execute_script(_STUB_APP_USERS_SQL)
    db.execute_script(PRODUCTS_SCHEMA_SQL)
    r = BomRepository(db)
    r.ensure_schema()

    # Bind the repository's short-lived write transactions to the same schema, so
    # its psycopg _txn() connection never touches public. (Production _txn opens a
    # plain connection with the default search_path; here we override per test.)
    plain = _plain_url()

    def _txn():
        conn = psycopg.connect(plain, row_factory=dict_row, **runtime_connect_kwargs())
        conn.execute(f'SET search_path TO "{schema}", public')
        return conn

    r._txn = _txn
    return r


# --- helpers ----------------------------------------------------------------

def _add_product(repo: BomRepository, name: str, price: str) -> dict:
    return repo.db.fetch_one(
        "INSERT INTO products (item_name, quantity, price) VALUES (%s, 0, %s) "
        "RETURNING id, item_code",
        [name, Decimal(price)],
    )


def _header(repo, product_id, *, name="منتج تام", total="0", bom_number=None):
    return {
        "bom_number": bom_number or repo.reserve_bom_number(),
        "bom_date": date(2026, 8, 17),
        "product_id": product_id,
        "product_name_snapshot": name,
        "total_material_cost": Decimal(total),
        "created_by": 1,
        "updated_by": 1,
    }


def _line(component_id, qty, price, *, code=None, name="خشب", unit="متر"):
    return {
        "component_product_id": component_id,
        "item_code_snapshot": code,
        "item_name_snapshot": name,
        "unit_snapshot": unit,
        "quantity": Decimal(qty),
        "price": Decimal(price),
    }


@pytest.fixture()
def seed(repo):
    """A finished product + two component products; returns their ids."""
    finished = _add_product(repo, "منتج تام", "0")
    comp1 = _add_product(repo, "خشب", "10.00")
    comp2 = _add_product(repo, "مسامير", "4.00")
    return {"finished": finished, "comp1": comp1, "comp2": comp2}


# --- schema / DDL -----------------------------------------------------------

def test_ensure_schema_is_idempotent(repo, seed):
    repo.ensure_schema()  # second run must not raise
    result = repo.insert_bom(
        _header(repo, seed["finished"]["id"], total="20.00"),
        [_line(seed["comp1"]["id"], "2", "10.00", code=seed["comp1"]["item_code"])],
    )
    assert result["header"]["bom_number"] == "BOM-0001"


# --- numbering --------------------------------------------------------------

def test_reserve_bom_number_is_sequential(repo):
    assert repo.reserve_bom_number() == "BOM-0001"
    assert repo.reserve_bom_number() == "BOM-0002"
    assert repo.reserve_bom_number() == "BOM-0003"


def test_db_default_assigns_bom_0001(repo, seed):
    # Insert omitting bom_number so the column DEFAULT ('BOM-' || ...) applies.
    row = repo.db.fetch_one(
        "INSERT INTO boms (bom_date, product_id, product_name_snapshot, "
        "total_material_cost) VALUES (CURRENT_DATE, %s, %s, 0) RETURNING bom_number",
        [seed["finished"]["id"], "منتج تام"],
    )
    assert row["bom_number"] == "BOM-0001"


def test_manual_high_number_pushes_sequence(repo, seed):
    repo.insert_bom(
        _header(repo, seed["finished"]["id"], bom_number="BOM-0050", total="0"),
        [_line(seed["comp1"]["id"], "1", "10.00")],
    )
    # The next automatic reservation must jump past the manual BOM-0050.
    assert repo.reserve_bom_number() == "BOM-0051"


# --- insert + generated line_total ------------------------------------------

def test_insert_header_and_lines_with_generated_line_total(repo, seed):
    result = repo.insert_bom(
        _header(repo, seed["finished"]["id"], total="48.25"),
        [
            _line(seed["comp1"]["id"], "2.5", "10.00", code=seed["comp1"]["item_code"]),
            _line(seed["comp2"]["id"], "3", "4.00", code=seed["comp2"]["item_code"]),
        ],
    )
    header = result["header"]
    assert header["id"] is not None
    assert header["total_material_cost"] == Decimal("48.25")
    lines = result["lines"]
    assert len(lines) == 2
    # line_total is the STORED generated column quantity * price.
    assert lines[0]["line_total"] == Decimal("25.00000")
    assert lines[1]["line_total"] == Decimal("12.00000")
    assert [ln["line_number"] for ln in lines] == [1, 2]


def test_load_bom_by_number(repo, seed):
    created = repo.insert_bom(
        _header(repo, seed["finished"]["id"]),
        [_line(seed["comp1"]["id"], "1", "10.00")],
    )
    number = created["header"]["bom_number"]
    loaded = repo.load_bom_by_number(number)
    assert loaded is not None
    assert loaded["header"]["id"] == created["header"]["id"]


# --- unique constraints -----------------------------------------------------

def test_unique_bom_number_rejected(repo, seed):
    repo.insert_bom(
        _header(repo, seed["finished"]["id"], bom_number="BOM-9001"),
        [_line(seed["comp1"]["id"], "1", "10.00")],
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.insert_bom(
            _header(repo, seed["finished"]["id"], bom_number="BOM-9001"),
            [_line(seed["comp2"]["id"], "1", "4.00")],
        )


def test_duplicate_component_rejected_at_db(repo, seed):
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.insert_bom(
            _header(repo, seed["finished"]["id"]),
            [
                _line(seed["comp1"]["id"], "1", "10.00"),
                _line(seed["comp1"]["id"], "2", "10.00"),  # same component
            ],
        )
    # Atomic rollback: no orphan header was left behind.
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM boms")["c"] == 0


# --- FK integrity + cascade / restrict --------------------------------------

def test_cascade_delete_removes_lines(repo, seed):
    created = repo.insert_bom(
        _header(repo, seed["finished"]["id"]),
        [
            _line(seed["comp1"]["id"], "1", "10.00"),
            _line(seed["comp2"]["id"], "2", "4.00"),
        ],
    )
    bom_id = created["header"]["id"]
    assert repo.db.fetch_one(
        "SELECT COUNT(*) c FROM bom_lines WHERE bom_id=%s", [bom_id]
    )["c"] == 2
    assert repo.delete_bom(bom_id) is True
    # Lines cascade away with the header.
    assert repo.db.fetch_one(
        "SELECT COUNT(*) c FROM bom_lines WHERE bom_id=%s", [bom_id]
    )["c"] == 0


def test_referenced_component_product_cannot_be_deleted(repo, seed):
    repo.insert_bom(
        _header(repo, seed["finished"]["id"]),
        [_line(seed["comp1"]["id"], "1", "10.00")],
    )
    # RESTRICT: a product used by a BOM line cannot be deleted (SQLSTATE 23001,
    # restrict_violation — distinct from a plain foreign_key_violation).
    with pytest.raises(psycopg.errors.RestrictViolation):
        repo.db.execute("DELETE FROM products WHERE id=%s", [seed["comp1"]["id"]])


def test_unknown_component_fk_rejected_and_rolled_back(repo, seed):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repo.insert_bom(
            _header(repo, seed["finished"]["id"]),
            [_line(999999, "1", "10.00")],  # component_product_id does not exist
        )
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM boms")["c"] == 0


# --- CHECK constraint + atomic rollback -------------------------------------

def test_invalid_quantity_rolls_back_whole_bom(repo, seed):
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.insert_bom(
            _header(repo, seed["finished"]["id"]),
            [
                _line(seed["comp1"]["id"], "2", "10.00"),  # valid line
                _line(seed["comp2"]["id"], "0", "4.00"),   # quantity > 0 CHECK fails
            ],
        )
    # No orphan header, no partial first line.
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM boms")["c"] == 0
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM bom_lines")["c"] == 0


# --- update replaces lines atomically ---------------------------------------

def test_update_replaces_lines_and_total(repo, seed):
    created = repo.insert_bom(
        _header(repo, seed["finished"]["id"], total="20.00"),
        [_line(seed["comp1"]["id"], "2", "10.00")],
    )
    bom_id = created["header"]["id"]
    updated = repo.update_bom(
        bom_id,
        {"total_material_cost": Decimal("28.00")},
        [
            _line(seed["comp1"]["id"], "2", "10.00"),
            _line(seed["comp2"]["id"], "2", "4.00"),
        ],
    )
    assert updated["header"]["total_material_cost"] == Decimal("28.00")
    assert len(updated["lines"]) == 2


def test_update_missing_bom_returns_none(repo):
    assert repo.update_bom(123456, {"total_material_cost": Decimal("1.00")}, []) is None
