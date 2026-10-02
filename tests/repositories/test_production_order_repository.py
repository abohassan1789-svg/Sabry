"""Integration tests for :class:`ProductionOrderRepository` against a real PostgreSQL.

These exercise the guarantees only a real database can provide:

* the order-number SEQUENCE (first number ``PRO-001``, atomic increments, the DB
  DEFAULT, 3-digit padding growth ``PRO-999`` -> ``PRO-1000``, and a manual number
  pushing the sequence forward while a lower one never moves it backward),
* the STORED generated ``deviation`` column (``actual_quantity - expected_quantity``),
* FK integrity + ``ON DELETE CASCADE`` (lines) / ``ON DELETE RESTRICT`` (products, BOM),
* the ``UNIQUE`` order number and ``UNIQUE (production_order_id, component_product_id)``,
* atomic rollback: a failing detail row leaves no orphan header and no partial lines,
* update replaces lines atomically,
* snapshot stability: editing the product master after save never changes a stored order.

BOM data is created through :class:`BomRepository` (reused, not duplicated), bound
to the same throwaway schema.

Isolation: every test runs inside a throwaway schema (``po_test_<n>``) created in
setup and ``DROP SCHEMA ... CASCADE``-d in teardown. The order/BOM tables, their
stub parents (``products`` via the real DDL, a minimal ``app_users``) and the
sequences are all created *inside* that schema via ``search_path``; the
repository's own transactional writes are bound to the same schema, so nothing in
``public`` (real app data — including the real BOM) is created, altered, or
dropped. If no database is reachable the whole module is skipped.
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
from app.repositories.production_order_repository import ProductionOrderRepository

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
    reason="No PostgreSQL reachable (set DB_* env / .env to run PO DB tests).",
)

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
    db = Database()
    db.execute(f'SET search_path TO "{schema}", public')
    return db


@pytest.fixture()
def schema():
    name = f"po_test_{next(_SCHEMA_SEQ)}_{os.getpid()}"
    admin = Database()
    admin.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        admin.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


@pytest.fixture()
def repo(schema):
    """A ProductionOrderRepository whose reads AND writes are bound to ``schema``."""
    db = _bound_db(schema)
    db.execute_script(_STUB_APP_USERS_SQL)
    db.execute_script(PRODUCTS_SCHEMA_SQL)
    r = ProductionOrderRepository(db)
    r.ensure_schema()  # ensures BOM schema (FK dependency) + PO schema on bound db

    plain = _plain_url()

    def _txn():
        conn = psycopg.connect(plain, row_factory=dict_row, **runtime_connect_kwargs())
        conn.execute(f'SET search_path TO "{schema}", public')
        return conn

    # Bind BOTH the PO write txns and the reused BOM write txns to the same schema.
    r._txn = _txn
    r.bom_repository._txn = _txn
    return r


# --- helpers ----------------------------------------------------------------

def _add_product(repo: ProductionOrderRepository, name: str, price: str) -> dict:
    return repo.db.fetch_one(
        "INSERT INTO products (item_name, quantity, price) VALUES (%s, 0, %s) "
        "RETURNING id, item_code",
        [name, Decimal(price)],
    )


def _bom_line(component, qty, price):
    return {
        "component_product_id": component["id"],
        "item_code_snapshot": component["item_code"],
        "item_name_snapshot": "مكوّن",
        "unit_snapshot": "وحدة",
        "quantity": Decimal(qty),
        "price": Decimal(price),
    }


def _add_bom(repo, product_id, lines, *, name="خرسانة") -> int:
    """Create a BOM (header + lines) via the reused BomRepository; return its id."""
    header = {
        "bom_number": repo.bom_repository.reserve_bom_number(),
        "bom_date": date(2026, 8, 17),
        "product_id": product_id,
        "product_name_snapshot": name,
        "total_material_cost": Decimal("0"),
        "created_by": 1,
        "updated_by": 1,
    }
    created = repo.bom_repository.insert_bom(header, lines)
    return int(created["header"]["id"])


def _po_header(repo, product_id, bom_id, *, qty="10", order_number=None, name="خرسانة"):
    return {
        "order_number": order_number or repo.reserve_order_number(),
        "order_date": date(2026, 8, 17),
        "product_id": product_id,
        "product_name_snapshot": name,
        "bom_id": bom_id,
        "production_quantity": Decimal(qty),
        "created_by": 1,
        "updated_by": 1,
    }


def _po_line(component, per_unit, expected, actual, price, *, name="أسمنت", unit="شيكارة"):
    return {
        "component_product_id": component["id"],
        "item_code_snapshot": component["item_code"],
        "item_name_snapshot": name,
        "unit_snapshot": unit,
        "bom_quantity_per_unit": Decimal(per_unit),
        "expected_quantity": Decimal(expected),
        "actual_quantity": Decimal(actual),
        "bom_price_snapshot": Decimal(price),
    }


@pytest.fixture()
def seed(repo):
    """A finished product, two components, and a BOM (أسمنت ×5, رمل ×2)."""
    finished = _add_product(repo, "خرسانة", "0")
    comp1 = _add_product(repo, "أسمنت", "10.00")
    comp2 = _add_product(repo, "رمل", "4.00")
    bom_id = _add_bom(repo, finished["id"], [
        _bom_line(comp1, "5", "10.00"),
        _bom_line(comp2, "2", "4.00"),
    ])
    return {"finished": finished, "comp1": comp1, "comp2": comp2, "bom_id": bom_id}


# --- schema / DDL -----------------------------------------------------------

def test_ensure_schema_is_idempotent(repo, seed):
    repo.ensure_schema()  # second run must not raise
    result = repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    assert result["header"]["order_number"] == "PRO-001"


# --- numbering --------------------------------------------------------------

def test_reserve_order_number_is_sequential(repo):
    assert repo.reserve_order_number() == "PRO-001"
    assert repo.reserve_order_number() == "PRO-002"
    assert repo.reserve_order_number() == "PRO-003"


def test_db_default_assigns_pro_001(repo, seed):
    # Insert omitting order_number so the column DEFAULT ('PRO-' || ...) applies.
    row = repo.db.fetch_one(
        "INSERT INTO production_orders (order_date, product_id, product_name_snapshot, "
        "bom_id, production_quantity) VALUES (CURRENT_DATE, %s, %s, %s, 1) "
        "RETURNING order_number",
        [seed["finished"]["id"], "خرسانة", seed["bom_id"]],
    )
    assert row["order_number"] == "PRO-001"


def test_padding_grows_past_999(repo, seed):
    # Move the sequence so the next DEFAULT values are PRO-999 then PRO-1000.
    repo.db.execute("SELECT setval('production_order_number_seq', 998, true)")

    def _default_number():
        return repo.db.fetch_one(
            "INSERT INTO production_orders (order_date, product_id, "
            "product_name_snapshot, bom_id, production_quantity) "
            "VALUES (CURRENT_DATE, %s, %s, %s, 1) RETURNING order_number",
            [seed["finished"]["id"], "خرسانة", seed["bom_id"]],
        )["order_number"]

    assert _default_number() == "PRO-999"
    assert _default_number() == "PRO-1000"   # 3-digit pad is a minimum, not a cap


def test_manual_high_number_pushes_sequence(repo, seed):
    repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"], order_number="PRO-050"),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    # The next automatic reservation must jump past the manual PRO-050.
    assert repo.reserve_order_number() == "PRO-051"


def test_manual_low_number_does_not_move_sequence_backward(repo, seed):
    assert repo.reserve_order_number() == "PRO-001"
    assert repo.reserve_order_number() == "PRO-002"
    # A low manual number must not regress the sequence.
    repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"], order_number="PRO-001b"),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    assert repo.reserve_order_number() == "PRO-003"


# --- insert + generated deviation -------------------------------------------

def test_insert_header_and_lines_with_generated_deviation(repo, seed):
    result = repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"], qty="10"),
        [
            _po_line(seed["comp1"], "5", "50", "52", "10.00"),  # +2
            _po_line(seed["comp2"], "2", "20", "18", "4.00"),   # -2
        ],
    )
    header = result["header"]
    assert header["id"] is not None
    assert header["production_quantity"] == Decimal("10.000")
    assert header["bom_id"] == seed["bom_id"]
    lines = result["lines"]
    assert len(lines) == 2
    # deviation is the STORED generated column actual - expected.
    assert lines[0]["deviation"] == Decimal("2.000")
    assert lines[1]["deviation"] == Decimal("-2.000")
    assert [ln["line_number"] for ln in lines] == [1, 2]


def test_zero_deviation_stored(repo, seed):
    result = repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    assert result["lines"][0]["deviation"] == Decimal("0.000")


def test_load_order_by_number(repo, seed):
    created = repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    number = created["header"]["order_number"]
    loaded = repo.load_order_by_number(number)
    assert loaded is not None
    assert loaded["header"]["id"] == created["header"]["id"]


# --- unique constraints -----------------------------------------------------

def test_unique_order_number_rejected(repo, seed):
    repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"], order_number="PRO-900"),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.insert_order(
            _po_header(repo, seed["finished"]["id"], seed["bom_id"], order_number="PRO-900"),
            [_po_line(seed["comp2"], "2", "20", "20", "4.00")],
        )


def test_duplicate_component_rejected_at_db(repo, seed):
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.insert_order(
            _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
            [
                _po_line(seed["comp1"], "5", "50", "50", "10.00"),
                _po_line(seed["comp1"], "5", "50", "50", "10.00"),  # same component
            ],
        )
    # Atomic rollback: no orphan header was left behind.
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM production_orders")["c"] == 0


# --- FK integrity + cascade / restrict --------------------------------------

def test_cascade_delete_removes_lines(repo, seed):
    created = repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
        [
            _po_line(seed["comp1"], "5", "50", "50", "10.00"),
            _po_line(seed["comp2"], "2", "20", "20", "4.00"),
        ],
    )
    order_id = created["header"]["id"]
    assert repo.db.fetch_one(
        "SELECT COUNT(*) c FROM production_order_lines WHERE production_order_id=%s",
        [order_id],
    )["c"] == 2
    assert repo.delete_order(order_id) is True
    assert repo.db.fetch_one(
        "SELECT COUNT(*) c FROM production_order_lines WHERE production_order_id=%s",
        [order_id],
    )["c"] == 0


def test_referenced_component_product_cannot_be_deleted(repo, seed):
    repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    with pytest.raises(psycopg.errors.RestrictViolation):
        repo.db.execute("DELETE FROM products WHERE id=%s", [seed["comp1"]["id"]])


def test_referenced_finished_product_cannot_be_deleted(repo, seed):
    repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    # RESTRICT via the order's product_id FK (the BOM also references it).
    with pytest.raises((psycopg.errors.RestrictViolation,
                        psycopg.errors.ForeignKeyViolation)):
        repo.db.execute("DELETE FROM products WHERE id=%s", [seed["finished"]["id"]])


def test_referenced_bom_cannot_be_deleted(repo, seed):
    repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    # RESTRICT: a BOM consumed by an order cannot be deleted while referenced.
    with pytest.raises((psycopg.errors.RestrictViolation,
                        psycopg.errors.ForeignKeyViolation)):
        repo.db.execute("DELETE FROM boms WHERE id=%s", [seed["bom_id"]])


def test_unknown_component_fk_rejected_and_rolled_back(repo, seed):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repo.insert_order(
            _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
            [{
                "component_product_id": 999999,  # does not exist
                "item_code_snapshot": None,
                "item_name_snapshot": "شبح",
                "unit_snapshot": "",
                "bom_quantity_per_unit": Decimal("1"),
                "expected_quantity": Decimal("1"),
                "actual_quantity": Decimal("1"),
                "bom_price_snapshot": Decimal("0"),
            }],
        )
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM production_orders")["c"] == 0


def test_unknown_bom_fk_rejected_and_rolled_back(repo, seed):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repo.insert_order(
            _po_header(repo, seed["finished"]["id"], 999999),  # bom_id does not exist
            [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
        )
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM production_orders")["c"] == 0


# --- CHECK constraint + atomic rollback -------------------------------------

def test_negative_actual_rolls_back_whole_order(repo, seed):
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.insert_order(
            _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
            [
                _po_line(seed["comp1"], "5", "50", "50", "10.00"),   # valid
                _po_line(seed["comp2"], "2", "20", "-1", "4.00"),    # actual < 0
            ],
        )
    # No orphan header, no partial first line.
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM production_orders")["c"] == 0
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM production_order_lines")["c"] == 0


# --- update replaces lines atomically ---------------------------------------

def test_update_replaces_lines(repo, seed):
    created = repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"], qty="10"),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    order_id = created["header"]["id"]
    updated = repo.update_order(
        order_id,
        {"production_quantity": Decimal("12.000")},
        [
            _po_line(seed["comp1"], "5", "60", "52", "10.00"),   # dev -8
            _po_line(seed["comp2"], "2", "24", "24", "4.00"),
        ],
    )
    assert updated["header"]["production_quantity"] == Decimal("12.000")
    assert len(updated["lines"]) == 2
    by_component = {ln["component_product_id"]: ln for ln in updated["lines"]}
    assert by_component[seed["comp1"]["id"]]["deviation"] == Decimal("-8.000")


def test_update_missing_order_returns_none(repo):
    assert repo.update_order(
        123456, {"production_quantity": Decimal("1.000")}, []
    ) is None


# --- snapshot stability ------------------------------------------------------

def test_snapshots_unchanged_when_product_master_later_edited(repo, seed):
    created = repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"]),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00",
                  name="أسمنت", unit="شيكارة")],
    )
    order_id = created["header"]["id"]
    # Rename + re-price the component master AFTER the order was saved.
    repo.db.execute(
        "UPDATE products SET item_name=%s, unit=%s, price=%s WHERE id=%s",
        ["أسمنت مقاوم", "طن", Decimal("99.00"), seed["comp1"]["id"]],
    )
    reloaded = repo.load_order(order_id)
    line = reloaded["lines"][0]
    # The order keeps its historical snapshots, untouched by the master edit.
    assert line["item_name_snapshot"] == "أسمنت"
    assert line["unit_snapshot"] == "شيكارة"
    assert line["bom_price_snapshot"] == Decimal("10.00")
    assert line["expected_quantity"] == Decimal("50.000")


def test_open_after_bom_edit_keeps_stored_snapshots(repo, seed):
    """Opening a saved order must not silently refresh from a newer BOM (§10)."""
    created = repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"], qty="10"),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00", name="أسمنت")],
    )
    order_id = created["header"]["id"]
    # Edit the BOM AFTER the order was saved: change أسمنت 5/unit -> 8/unit @ 99.00.
    repo.bom_repository.update_bom(
        seed["bom_id"],
        {"total_material_cost": Decimal("0")},
        [{
            "component_product_id": seed["comp1"]["id"],
            "item_code_snapshot": seed["comp1"]["item_code"],
            "item_name_snapshot": "أسمنت", "unit_snapshot": "شيكارة",
            "quantity": Decimal("8"), "price": Decimal("99.00"),
        }],
    )
    reloaded = repo.load_order(order_id)
    line = reloaded["lines"][0]
    # Stored snapshots stay frozen at BOM-v1 values (5 per unit @ 10.00, expected 50).
    assert line["bom_quantity_per_unit"] == Decimal("5.000")
    assert line["bom_price_snapshot"] == Decimal("10.00")
    assert line["expected_quantity"] == Decimal("50.000")


# --- search ------------------------------------------------------------------

def test_search_orders_by_number_and_product(repo, seed):
    repo.insert_order(
        _po_header(repo, seed["finished"]["id"], seed["bom_id"], order_number="PRO-777"),
        [_po_line(seed["comp1"], "5", "50", "50", "10.00")],
    )
    by_number = repo.search_orders("PRO-777")
    assert len(by_number) == 1 and by_number[0]["order_number"] == "PRO-777"
    by_product = repo.search_orders("خرسانة")
    assert len(by_product) == 1
    assert repo.search_orders("لا-يوجد") == []
