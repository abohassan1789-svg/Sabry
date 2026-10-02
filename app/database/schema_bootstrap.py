"""Automatic, idempotent full-schema bootstrap.

Runs the consolidated schema DDL in ``schema/full_schema.sql`` so that:

* a **fresh** database self-builds every table / sequence / index / constraint /
  trigger / function the application needs, and
* an **existing** database is left untouched — every statement is
  ``IF NOT EXISTS`` or guarded, so re-running it is a safe no-op that never
  changes data.

This is what lets a newly installed device work with **no manual migration
step**: the app runs this on startup and the installer runs it while
provisioning.

Adding a table or column later — the "no migrations" workflow
--------------------------------------------------------------
Edit ``schema/full_schema.sql`` and add an **idempotent** statement:

* new table  -> ``CREATE TABLE IF NOT EXISTS public.my_table (...);``
* new column -> ``ALTER TABLE public.my_table ADD COLUMN IF NOT EXISTS col TYPE;``
* new index  -> ``CREATE INDEX IF NOT EXISTS ... ;``

It then applies itself automatically on every device on the next launch. No
numbered migration files, no manual ``psql`` run. Complex one-off changes
(renames, type changes, data back-fills) still need a guarded ``DO $$ ... $$``
block, but they live in this same file.
"""

from __future__ import annotations

from pathlib import Path

from app.database.db import Database

# schema/full_schema.sql sits next to this module (bundled as data in the frozen
# app via the same mechanism as app/database/migrations).
_SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema" / "full_schema.sql"


def full_schema_sql() -> str:
    """Return the idempotent full-schema DDL text."""
    return _SCHEMA_SQL_PATH.read_text(encoding="utf-8")


def ensure_full_schema(db: Database | None = None) -> None:
    """Apply the idempotent full schema. Safe to run on every startup/provision.

    On a fresh database this creates the whole schema; on an existing one it is a
    no-op (nothing is dropped, no data is touched). Raises on a real database
    error (e.g. the server is unreachable) so callers can surface it.
    """
    (db or Database()).execute_script(full_schema_sql())
