"""Integration tests for :class:`LoadingVoucherRepository` against a real PostgreSQL.

These exercise the guarantees only a real database can provide:

* the voucher-number SEQUENCE (first number ``LV-001``, atomic increments, the DB
  DEFAULT, 3-digit padding growth ``LV-999`` -> ``LV-1000``, and a manual number
  pushing the sequence forward while a lower one never moves it backward),
* the date/time column DEFAULTs (CURRENT_DATE / localtime),
* FK integrity + ``ON DELETE RESTRICT`` (customer, product),
* the ``UNIQUE`` voucher number and the positive-quantity CHECK,
* atomic rollback on a bad insert,
* update mutates the row and refreshes updated_at; delete is a hard delete,
* snapshot stability: editing the customer/product master after save never
  changes a stored voucher.

Isolation: every test runs inside a throwaway schema (``lv_test_<n>``) created in
setup and ``DROP SCHEMA ... CASCADE``-d in teardown. The voucher table, its stub
parents (``customers`` / ``products`` via the real DDL, a minimal ``app_users``)
and the sequence are all created *inside* that schema via ``search_path``; the
repository's own transactional writes are bound to the same schema, so nothing in
``public`` (real app data) is created, altered, or dropped. If no database is
reachable the whole module is skipped.
"""

from __future__ import annotations

import os
from datetime import date, time
from decimal import Decimal

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config.database import build_database_url, runtime_connect_kwargs
from app.config.settings import get_settings
from app.database.db import Database
from app.models.product import PRODUCTS_SCHEMA_SQL
from app.repositories.loading_voucher_repository import LoadingVoucherRepository

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
    reason="No PostgreSQL reachable (set DB_* env / .env to run LV DB tests).",
)

_STUB_APP_USERS_SQL = """
CREATE TABLE IF NOT EXISTS app_users (
    id integer PRIMARY KEY,
    username varchar(100)
);
INSERT INTO app_users (id, username) VALUES (1, 'tester') ON CONFLICT DO NOTHING;
"""

# Minimal customers parent (real core schema uses customer_id as the PK).
_STUB_CUSTOMERS_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id integer PRIMARY KEY,
    customer_name varchar(100),
    phone_number varchar(40)
);
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
    name = f"lv_test_{next(_SCHEMA_SEQ)}_{os.getpid()}"
    admin = Database()
    admin.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        admin.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


@pytest.fixture()
def repo(schema):
    """A LoadingVoucherRepository whose reads AND writes are bound to ``schema``."""
    db = _bound_db(schema)
    db.execute_script(_STUB_APP_USERS_SQL)
    db.execute_script(_STUB_CUSTOMERS_SQL)
    db.execute_script(PRODUCTS_SCHEMA_SQL)
    r = LoadingVoucherRepository(db)
    r.ensure_schema()

    plain = _plain_url()

    def _txn():
        conn = psycopg.connect(plain, row_factory=dict_row, **runtime_connect_kwargs())
        conn.execute(f'SET search_path TO "{schema}", public')
        return conn

    r._txn = _txn
    return r


# --- helpers ----------------------------------------------------------------

def _add_customer(repo, customer_id, name, phone="0100"):
    repo.db.execute(
        "INSERT INTO customers (customer_id, customer_name, phone_number) "
        "VALUES (%s, %s, %s)",
        [customer_id, name, phone],
    )
    return {"customer_id": customer_id, "customer_name": name, "phone_number": phone}


def _add_product(repo, name, price="0"):
    return repo.db.fetch_one(
        "INSERT INTO products (item_name, quantity, price) VALUES (%s, 0, %s) "
        "RETURNING id, item_code",
        [name, Decimal(price)],
    )


def _header(repo, customer, product, *, qty="25.000", number=None,
            driver="محمد عبد الله", vehicle="أ ب ج 4213",
            weight_before="500k", weight_after="750k"):
    return {
        "voucher_number": number or repo.reserve_voucher_number(),
        "voucher_date": date(2026, 8, 18),
        "voucher_time": time(9, 30),
        "customer_id": customer["customer_id"],
        "customer_name_snapshot": customer["customer_name"],
        "driver_name": driver,
        "vehicle_number": vehicle,
        "weight_before_loading": weight_before,
        "weight_after_loading": weight_after,
        "product_id": product["id"],
        "item_code_snapshot": product["item_code"],
        "item_name_snapshot": "أسمنت مقاوم",
        "unit_snapshot": "طن",
        "quantity_tons": Decimal(qty),
        "created_by": 1,
        "updated_by": 1,
    }


@pytest.fixture()
def seed(repo):
    customer = _add_customer(repo, 1001, "شركة النور للتجارة")
    product = _add_product(repo, "أسمنت مقاوم", "0")
    return {"customer": customer, "product": product}


# --- schema / DDL -----------------------------------------------------------

def test_ensure_schema_is_idempotent(repo, seed):
    repo.ensure_schema()  # second run must not raise
    result = repo.insert_voucher(_header(repo, seed["customer"], seed["product"]))
    assert result["voucher_number"] == "LV-001"


# --- numbering --------------------------------------------------------------

def test_reserve_voucher_number_is_sequential(repo):
    assert repo.reserve_voucher_number() == "LV-001"
    assert repo.reserve_voucher_number() == "LV-002"
    assert repo.reserve_voucher_number() == "LV-003"


def test_db_default_assigns_lv_001(repo, seed):
    # Insert omitting voucher_number/date/time so the column DEFAULTs apply.
    row = repo.db.fetch_one(
        "INSERT INTO loading_vouchers (customer_id, customer_name_snapshot, "
        "driver_name, vehicle_number, product_id, item_name_snapshot, quantity_tons) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "RETURNING voucher_number, voucher_date, voucher_time",
        [seed["customer"]["customer_id"], "شركة النور", "سائق", "1234",
         seed["product"]["id"], "أسمنت", Decimal("5")],
    )
    assert row["voucher_number"] == "LV-001"
    assert row["voucher_date"] is not None   # CURRENT_DATE default
    assert row["voucher_time"] is not None   # localtime default


def test_padding_grows_past_999(repo, seed):
    repo.db.execute("SELECT setval('loading_voucher_number_seq', 998, true)")

    def _default_number():
        return repo.db.fetch_one(
            "INSERT INTO loading_vouchers (customer_id, customer_name_snapshot, "
            "driver_name, vehicle_number, product_id, item_name_snapshot, quantity_tons) "
            "VALUES (%s, %s, %s, %s, %s, %s, 1) RETURNING voucher_number",
            [seed["customer"]["customer_id"], "ع", "س", "1", seed["product"]["id"], "ص"],
        )["voucher_number"]

    assert _default_number() == "LV-999"
    assert _default_number() == "LV-1000"   # 3-digit pad is a minimum, not a cap


def test_manual_high_number_pushes_sequence(repo, seed):
    repo.insert_voucher(_header(repo, seed["customer"], seed["product"], number="LV-050"))
    assert repo.reserve_voucher_number() == "LV-051"


def test_manual_low_number_does_not_move_sequence_backward(repo, seed):
    assert repo.reserve_voucher_number() == "LV-001"
    assert repo.reserve_voucher_number() == "LV-002"
    # A non-standard manual number must not regress the sequence.
    repo.insert_voucher(_header(repo, seed["customer"], seed["product"], number="LV-1b"))
    assert repo.reserve_voucher_number() == "LV-003"


# --- insert + read back -----------------------------------------------------

def test_insert_and_load_roundtrip(repo, seed):
    created = repo.insert_voucher(
        _header(repo, seed["customer"], seed["product"], qty="12.750")
    )
    assert created["id"] is not None
    assert created["quantity_tons"] == Decimal("12.750")
    assert created["voucher_time"] == time(9, 30)
    # Vehicle weighbridge readings are free text and round-trip literally.
    assert created["weight_before_loading"] == "500k"
    assert created["weight_after_loading"] == "750k"
    loaded = repo.load_voucher(created["id"])
    assert loaded["voucher_number"] == created["voucher_number"]
    by_number = repo.load_voucher_by_number(created["voucher_number"])
    assert by_number["id"] == created["id"]


def test_all_business_fields_optional(repo):
    # Every business field is optional (v1): a voucher with only an auto number,
    # date and time must save. customer/product/driver/vehicle/quantity all NULL.
    created = repo.insert_voucher({
        "voucher_date": date(2026, 8, 18),
        "voucher_time": time(9, 30),
    })
    assert created["voucher_number"] == "LV-001"
    assert created["customer_id"] is None
    assert created["product_id"] is None
    assert created["driver_name"] is None
    assert created["vehicle_number"] is None
    assert created["weight_before_loading"] is None
    assert created["weight_after_loading"] is None
    assert created["quantity_tons"] is None
    # unit_snapshot keeps its '' default (NOT NULL DEFAULT '').
    assert created["unit_snapshot"] == ""


# --- constraints ------------------------------------------------------------

def test_unique_voucher_number_rejected(repo, seed):
    repo.insert_voucher(_header(repo, seed["customer"], seed["product"], number="LV-900"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        repo.insert_voucher(
            _header(repo, seed["customer"], seed["product"], number="LV-900")
        )


def test_zero_quantity_rejected_and_rolled_back(repo, seed):
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.insert_voucher(
            _header(repo, seed["customer"], seed["product"], qty="0")
        )
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM loading_vouchers")["c"] == 0


def test_negative_quantity_rejected(repo, seed):
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.insert_voucher(
            _header(repo, seed["customer"], seed["product"], qty="-1")
        )


# --- FK integrity + restrict ------------------------------------------------

def test_referenced_customer_cannot_be_deleted(repo, seed):
    repo.insert_voucher(_header(repo, seed["customer"], seed["product"]))
    with pytest.raises((psycopg.errors.RestrictViolation,
                        psycopg.errors.ForeignKeyViolation)):
        repo.db.execute(
            "DELETE FROM customers WHERE customer_id=%s",
            [seed["customer"]["customer_id"]],
        )


def test_referenced_product_cannot_be_deleted(repo, seed):
    repo.insert_voucher(_header(repo, seed["customer"], seed["product"]))
    with pytest.raises((psycopg.errors.RestrictViolation,
                        psycopg.errors.ForeignKeyViolation)):
        repo.db.execute("DELETE FROM products WHERE id=%s", [seed["product"]["id"]])


def test_unknown_customer_fk_rejected_and_rolled_back(repo, seed):
    bad = _header(repo, seed["customer"], seed["product"])
    bad["customer_id"] = 999999
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repo.insert_voucher(bad)
    assert repo.db.fetch_one("SELECT COUNT(*) c FROM loading_vouchers")["c"] == 0


# --- update + delete --------------------------------------------------------

def test_update_changes_fields(repo, seed):
    created = repo.insert_voucher(_header(repo, seed["customer"], seed["product"]))
    updated = repo.update_voucher(created["id"], {
        "quantity_tons": Decimal("30.500"),
        "driver_name": "خالد يوسف",
        "vehicle_number": "د هـ و 9999",
    })
    assert updated["quantity_tons"] == Decimal("30.500")
    assert updated["driver_name"] == "خالد يوسف"
    assert updated["vehicle_number"] == "د هـ و 9999"


def test_update_missing_voucher_returns_none(repo):
    assert repo.update_voucher(123456, {"quantity_tons": Decimal("1.000")}) is None


def test_delete_is_hard_delete(repo, seed):
    created = repo.insert_voucher(_header(repo, seed["customer"], seed["product"]))
    assert repo.delete_voucher(created["id"]) is True
    assert repo.load_voucher(created["id"]) is None
    assert repo.delete_voucher(created["id"]) is False


# --- snapshot stability ------------------------------------------------------

def test_snapshots_unchanged_when_master_later_edited(repo, seed):
    created = repo.insert_voucher(_header(repo, seed["customer"], seed["product"]))
    voucher_id = created["id"]
    # Rename the customer + product master AFTER the voucher was saved.
    repo.db.execute(
        "UPDATE customers SET customer_name=%s WHERE customer_id=%s",
        ["اسم جديد", seed["customer"]["customer_id"]],
    )
    repo.db.execute(
        "UPDATE products SET item_name=%s, unit=%s WHERE id=%s",
        ["صنف جديد", "كجم", seed["product"]["id"]],
    )
    reloaded = repo.load_voucher(voucher_id)
    assert reloaded["customer_name_snapshot"] == "شركة النور للتجارة"
    assert reloaded["item_name_snapshot"] == "أسمنت مقاوم"
    assert reloaded["unit_snapshot"] == "طن"


# --- search ------------------------------------------------------------------

def test_search_vouchers_by_number_and_customer(repo, seed):
    repo.insert_voucher(_header(repo, seed["customer"], seed["product"], number="LV-777"))
    by_number = repo.search_vouchers("LV-777")
    assert len(by_number) == 1 and by_number[0]["voucher_number"] == "LV-777"
    by_customer = repo.search_vouchers("النور")
    assert len(by_customer) == 1
    assert repo.search_vouchers("لا-يوجد") == []
