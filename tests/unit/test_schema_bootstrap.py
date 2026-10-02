"""Guards for the automatic idempotent full-schema bootstrap.

These run without a database: they assert the *shipped* ``full_schema.sql`` is
safe to run repeatedly (every object is IF NOT EXISTS / guarded, no psql-only
meta-commands that would break the psycopg runtime path) and that
``ensure_full_schema`` feeds it through the DB's script runner. The live
apply-twice / no-data-loss behaviour was verified against real databases during
development.
"""

from __future__ import annotations

import re

from app.database import schema_bootstrap


CORE_TABLES = (
    "customers", "app_users", "roles", "permissions", "companies", "products",
    "receipt_vouchers", "cashier_invoices", "cashier_invoice_lines",
    "sales_invoices", "sales_invoice_lines", "sales_invoice_zatca_data",
    "production_orders", "production_order_lines", "loading_vouchers",
)


def test_full_schema_sql_loads_and_covers_core_tables():
    sql = schema_bootstrap.full_schema_sql()
    assert sql.strip()
    for table in CORE_TABLES:
        assert f"public.{table}" in sql, f"missing schema for {table}"


def test_no_psql_meta_commands_leak_into_the_script():
    # pg_dump 18 emits \restrict / \unrestrict; psql tolerates them but psycopg
    # (the app's runtime) raises a syntax error. They must be stripped.
    for line in schema_bootstrap.full_schema_sql().splitlines():
        assert not line.lstrip().startswith("\\"), f"psql meta-command leaked: {line!r}"


def test_every_create_is_idempotent():
    sql = schema_bootstrap.full_schema_sql()
    assert not re.search(r"(?im)^\s*CREATE TABLE (?!IF NOT EXISTS)", sql), \
        "a CREATE TABLE is missing IF NOT EXISTS"
    assert not re.search(r"(?im)^\s*CREATE SEQUENCE (?!IF NOT EXISTS)", sql), \
        "a CREATE SEQUENCE is missing IF NOT EXISTS"
    assert not re.search(r"(?im)^\s*CREATE (UNIQUE )?INDEX (?!IF NOT EXISTS)", sql), \
        "a CREATE INDEX is missing IF NOT EXISTS"


def test_constraints_and_identity_and_triggers_are_guarded():
    sql = schema_bootstrap.full_schema_sql()
    # Every ADD CONSTRAINT sits inside its own pg_constraint-guarded DO block —
    # so the counts match exactly (a bare, unguarded one would break the balance).
    add_constraints = len(re.findall(r"\bADD CONSTRAINT\b", sql))
    guards = sql.count("FROM pg_constraint")
    assert add_constraints > 0 and add_constraints == guards, \
        f"{add_constraints} ADD CONSTRAINT vs {guards} guards — an unguarded one exists"
    # Identity columns are guarded via pg_attribute.attidentity.
    assert "attidentity" in sql
    # Triggers are dropped-if-exists before create (version-safe idempotency).
    assert "DROP TRIGGER IF EXISTS" in sql


def test_artifact_tables_are_excluded():
    sql = schema_bootstrap.full_schema_sql()
    assert "app_users_legacy" not in sql
    assert "backup_006" not in sql


def test_ensure_full_schema_runs_the_script_once():
    calls: list[str] = []

    class FakeDB:
        def execute_script(self, sql: str) -> None:
            calls.append(sql)

    schema_bootstrap.ensure_full_schema(FakeDB())
    assert len(calls) == 1
    assert "CREATE TABLE IF NOT EXISTS public.sales_invoices" in calls[0]
