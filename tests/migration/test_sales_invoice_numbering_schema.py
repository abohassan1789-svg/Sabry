"""Isolated PostgreSQL tests for global Saudi invoice numbering migration 018."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from app.database.db import Database


_SCHEMA_SEQ = iter(range(1, 1_000_000))
_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "app" / "database" / "migrations"
)
_UPGRADE_SQL = _MIGRATIONS_DIR / "018_create_sales_invoice_numbering.sql"
_DOWNGRADE_SQL = _MIGRATIONS_DIR / "018_downgrade_sales_invoice_numbering.sql"


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
    reason="No PostgreSQL reachable for invoice-number migration tests.",
)


def _bound_db(schema: str) -> Database:
    db = Database()
    db.execute(f'SET search_path TO "{schema}", public')
    return db


@pytest.fixture()
def schema():
    name = f"sinum_test_{next(_SCHEMA_SEQ)}_{os.getpid()}"
    admin = Database()
    admin.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        admin.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


@pytest.fixture()
def db(schema):
    conn = _bound_db(schema)
    conn.execute_script(
        """
        CREATE TABLE sales_invoices (
            id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            seller_company_id integer NOT NULL,
            invoice_number varchar(100) NOT NULL
        );
        CREATE UNIQUE INDEX uq_sales_invoices_company_number
            ON sales_invoices (seller_company_id, invoice_number);
        """
    )
    return conn


def _upgrade(db: Database) -> None:
    db.execute_script(_UPGRADE_SQL.read_text(encoding="utf-8"))


def _downgrade(db: Database) -> None:
    db.execute_script(_DOWNGRADE_SQL.read_text(encoding="utf-8"))


def test_fresh_migration_starts_sequence_at_50001(db):
    _upgrade(db)

    assert db.fetch_one(
        "SELECT nextval('sales_invoice_number_seq') AS n"
    )["n"] == 50001


def test_migration_seeds_after_greatest_existing_numeric_number(db):
    db.execute(
        "INSERT INTO sales_invoices (seller_company_id, invoice_number) "
        "VALUES (1, '50010'), (2, 'MANUAL-A')"
    )

    _upgrade(db)

    assert db.fetch_one(
        "SELECT nextval('sales_invoice_number_seq') AS n"
    )["n"] == 50011


def test_global_unique_index_rejects_same_number_for_another_seller(db):
    _upgrade(db)
    db.execute(
        "INSERT INTO sales_invoices (seller_company_id, invoice_number) "
        "VALUES (1, '50001')"
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "INSERT INTO sales_invoices (seller_company_id, invoice_number) "
            "VALUES (2, '50001')"
        )


def test_migration_aborts_without_mutating_duplicate_history(db):
    db.execute(
        "INSERT INTO sales_invoices (seller_company_id, invoice_number) "
        "VALUES (1, 'SHARED'), (2, 'SHARED')"
    )

    with pytest.raises(Exception, match="duplicate invoice numbers"):
        _upgrade(db)
    db.execute("ROLLBACK")

    assert db.fetch_one(
        "SELECT COUNT(*) AS c FROM sales_invoices WHERE invoice_number = 'SHARED'"
    )["c"] == 2
    assert db.fetch_one(
        "SELECT to_regclass(format('%I.sales_invoice_number_seq', current_schema())) AS seq"
    )["seq"] is None


def test_upgrade_is_idempotent_and_never_moves_sequence_backward(db):
    _upgrade(db)
    assert db.fetch_one(
        "SELECT nextval('sales_invoice_number_seq') AS n"
    )["n"] == 50001

    _upgrade(db)

    assert db.fetch_one(
        "SELECT nextval('sales_invoice_number_seq') AS n"
    )["n"] == 50002


def test_upgrade_replaces_constraint_owned_seller_uniqueness(schema):
    conn = _bound_db(schema)
    conn.execute_script(
        """
        CREATE TABLE sales_invoices (
            id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            seller_company_id integer NOT NULL,
            invoice_number varchar(100) NOT NULL,
            CONSTRAINT uq_sales_invoices_company_number
                UNIQUE (seller_company_id, invoice_number)
        );
        """
    )

    _upgrade(conn)

    assert conn.fetch_one(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'sales_invoices'::regclass "
        "AND conname = 'uq_sales_invoices_company_number'"
    ) is None
    assert conn.fetch_one(
        "SELECT to_regclass('uq_sales_invoices_invoice_number') AS idx"
    )["idx"] is not None


def test_downgrade_restores_seller_scoped_index_and_drops_sequence(db):
    _upgrade(db)

    _downgrade(db)

    indexes = {
        row["indexname"]
        for row in db.fetch_all(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = 'sales_invoices'"
        )
    }
    assert "uq_sales_invoices_invoice_number" not in indexes
    assert "uq_sales_invoices_company_number" in indexes
    assert db.fetch_one(
        "SELECT to_regclass(format('%I.sales_invoice_number_seq', current_schema())) AS seq"
    )["seq"] is None
