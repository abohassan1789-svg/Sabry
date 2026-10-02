"""Schema definition and domain constants for the Loading Voucher module
(سند تحميل).

Scope
-----
A Loading Voucher is a *simple logistics document* recording that a quantity (in
tons) of one item was loaded for a customer onto a vehicle driven by a named
driver at a given date/time. It is a **single-item, flat document** — one header
row per voucher, no detail-line table:

    voucher number · date · time · customer · driver name · vehicle number ·
    vehicle weight before/after loading (free text) · item · quantity (tons) · notes

Design decisions confirmed for this version (v1):
* **One item per voucher** — a flat ``loading_vouchers`` table, no lines table.
* **Hard delete** — no cancel / void / document-status workflow.
* **No company link** — the confirmed fields do not include a company.
* Driver name and vehicle number are **free text** (no drivers / vehicles master
  exists in the project yet). They are stored as ``varchar``.
* **Every business field is optional** (v1, per the user's request): customer,
  driver name, vehicle number, item, quantity and notes may all be left blank.
  Only the auto ``voucher_number``, the ``voucher_date`` / ``voucher_time``
  (defaulted) and the audit columns are always present. The two foreign keys stay
  enforced *when a value is supplied* (an FK column accepts NULL), and a supplied
  quantity must still be positive — a blank quantity is allowed.

This module holds the *structure* (DDL) and reusable domain constants only — no
SQL execution and no business logic. The repository layer runs
``LOADING_VOUCHERS_SCHEMA_SQL`` (every statement is ``CREATE ... IF NOT EXISTS`` /
``CREATE OR REPLACE`` / a guarded forward-only re-seed, so it is safe to run
repeatedly and never drops, resets or deletes anything). The same structure is
mirrored in ``app/database/schema/full_schema.sql`` (runtime bootstrap) and
``app/database/migrations/034_create_loading_vouchers_schema.sql`` (with its
downgrade file), so a fresh install and an already-provisioned install converge
on the same shape.

Design notes
------------
* ``id`` is a PostgreSQL IDENTITY column (sequence-backed). Ids are never computed
  with ``MAX(id) + 1``.
* ``voucher_number`` is a user-facing document number that starts at ``LV-001``.
  Automatic numbers come from the dedicated sequence
  ``loading_voucher_number_seq`` (the first ``nextval`` returns ``1``, formatted as
  ``LV-001``). ``nextval`` is atomic, so concurrent creators never receive the same
  number. A UNIQUE index is the final guard. The number stays editable: an
  authorised user may supply their own value, and the repository re-seeds the
  sequence past any manually-entered ``LV-<n>`` so a high manual number can never
  collide with a future automatic one. The next number is never
  ``MAX(voucher_number) + 1``. Padding is a *minimum* (3 digits), so it grows past
  999 -> ``LV-1000``. The DB column DEFAULT formats the sequence value through the
  helper ``loading_voucher_format_number(bigint)`` (``'LV-' || lpad(...)`` with a
  ``GREATEST(3, length)`` width), byte-for-byte identical to the Python
  :func:`format_number` at every magnitude — a fixed ``to_char`` mask like
  ``FM000`` was deliberately avoided because it overflows to ``###`` past 999.
* ``voucher_date`` defaults to ``CURRENT_DATE`` and ``voucher_time`` to
  ``localtime`` when a new voucher is created (they are separate columns, mirroring
  the cashier-invoice convention of a distinct date and time).
* ``customer_id`` -> ``customers(customer_id)`` and ``product_id`` -> ``products(id)``
  are RESTRICT foreign keys to the existing master tables — a customer or item
  referenced by a voucher cannot be deleted. No duplicate customer / item master is
  created. Stable ``*_snapshot`` columns freeze the customer name and the item
  code/name/unit as they were at save time, so an old voucher never changes when
  the master data is later edited (same convention as sales invoices / production
  orders). ``item_code_snapshot`` mirrors the physical type of ``products.item_code``
  (``integer``).
* ``quantity_tons`` is ``numeric(18,3)`` and optional; the ``CHECK`` allows NULL but
  rejects zero and negative when a value is present. All quantity maths is
  :class:`decimal.Decimal` (never ``float``).
* Audit fields mirror the project's document convention (see ``receipt_vouchers`` /
  ``production_orders``): ``created_at`` / ``updated_at`` are ``timestamptz`` and
  ``updated_at`` is maintained by a BEFORE UPDATE trigger; ``created_by`` /
  ``updated_by`` are nullable FKs to ``app_users(id)`` with ``ON DELETE SET NULL``.
  There is deliberately **no** ``document_status`` / workflow / company / warehouse
  column — this simple document has no approval lifecycle and no inventory posting.

The live application talks to PostgreSQL through the raw-psycopg
``LoadingVoucherRepository`` (mirroring the Production Order / BOM modules), so no
SQLAlchemy ORM model is defined here.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# --- table name -------------------------------------------------------------

TBL_LOADING_VOUCHERS = "loading_vouchers"

# --- automatic numbering ("LV-001", "LV-002", ...) --------------------------
# The sequence yields 1, 2, 3, ... and the number is rendered as
# ``LV-<zero-padded-to-3>`` -> LV-001, LV-002, ... (padding is a minimum, so it
# grows past 999 -> LV-1000). The SQL column DEFAULT formats the sequence value
# through loading_voucher_format_number(), identical to ``format_number`` here.
LV_NUMBER_SEQUENCE = "loading_voucher_number_seq"
LV_NUMBER_PREFIX = "LV-"
LV_NUMBER_PAD = 3            # minimum digits (grows past 999 -> LV-1000)
FIRST_LV_SEQ = 1            # first sequence value -> LV-001

# Recognises an automatic-style number: LV- followed by digits only.
_AUTO_NUMBER_RE = re.compile(rf"^{re.escape(LV_NUMBER_PREFIX)}(\d+)$")


def format_number(sequence_value: Any) -> str:
    """Render a raw sequence value as an ``LV-<n>`` document number.

    ``format_number(1) == 'LV-001'``; padding is a minimum, not a cap, so
    ``format_number(1000) == 'LV-1000'``.
    """
    return f"{LV_NUMBER_PREFIX}{int(sequence_value):0{LV_NUMBER_PAD}d}"


def parse_sequence_value(voucher_number: Any) -> int | None:
    """Return the integer ``n`` from an ``LV-<n>`` number, or ``None``.

    Only the canonical ``LV-<digits>`` shape is recognised; anything else (a
    free-form manual string) returns ``None`` so it never moves the automatic
    sequence. The UNIQUE index remains the final duplicate guard in every case.
    """
    if voucher_number is None:
        return None
    match = _AUTO_NUMBER_RE.match(str(voucher_number).strip())
    return int(match.group(1)) if match else None


# --- numeric precision (must not exceed the physical column definitions) -----

QUANTITY_PRECISION, QUANTITY_SCALE = 18, 3   # numeric(18,3) — tons, mirrors products
QTY_QUANT = Decimal("0.001")                 # quantity rounds to 3 dp

# --- snapshot / free-text length limits (mirror the physical varchar lengths) -
MAX_CUSTOMER_NAME_LEN = 150                  # customer_name_snapshot varchar(150)
MAX_ITEM_NAME_LEN = 200                      # item_name_snapshot varchar(200)
MAX_UNIT_LEN = 50                            # unit_snapshot varchar(50)
MAX_DRIVER_NAME_LEN = 150                    # driver_name varchar(150)
MAX_VEHICLE_NUMBER_LEN = 50                  # vehicle_number varchar(50)
MAX_WEIGHT_LEN = 50                          # weight_before/after_loading varchar(50)

# --- columns the application is allowed to write ----------------------------
# ``id`` (IDENTITY), ``voucher_number`` (DB DEFAULT unless supplied), the date/time
# (DB defaults unless supplied) and the timestamps (DB defaults / trigger) are
# database-managed; ``voucher_number`` may still be passed explicitly to store a
# manual number.
VOUCHER_INSERT_COLUMNS: tuple[str, ...] = (
    "voucher_number",
    "voucher_date",
    "voucher_time",
    "customer_id",
    "customer_name_snapshot",
    "driver_name",
    "vehicle_number",
    "weight_before_loading",
    "weight_after_loading",
    "product_id",
    "item_code_snapshot",
    "item_name_snapshot",
    "unit_snapshot",
    "quantity_tons",
    "notes",
    "created_by",
    "updated_by",
)

# Columns read back / shown on the screen.
VOUCHER_SELECT_COLUMNS: tuple[str, ...] = (
    "id",
    "voucher_number",
    "voucher_date",
    "voucher_time",
    "customer_id",
    "customer_name_snapshot",
    "driver_name",
    "vehicle_number",
    "weight_before_loading",
    "weight_after_loading",
    "product_id",
    "item_code_snapshot",
    "item_name_snapshot",
    "unit_snapshot",
    "quantity_tons",
    "notes",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
)


# --- raw DDL (source of truth, mirrored by migration 034 + full_schema.sql) ---
#
# Fully idempotent and self-contained: every statement is CREATE ... IF NOT
# EXISTS / CREATE OR REPLACE / a guarded forward-only re-seed. The voucher_number
# DEFAULT formats the sequence value through loading_voucher_format_number(),
# identical to ``format_number`` in Python at every magnitude (min 3 digits,
# unbounded growth), so a number produced by the database DEFAULT and one produced
# by the app are identical.

LOADING_VOUCHERS_SCHEMA_SQL = f"""
-- Sequence that feeds automatic Loading Voucher numbers. A freshly-created
-- sequence returns {FIRST_LV_SEQ} on the FIRST nextval() (so the first document is
-- LV-001). nextval is atomic, so concurrent creators never share a number.
CREATE SEQUENCE IF NOT EXISTS {LV_NUMBER_SEQUENCE} AS bigint MINVALUE 1;

-- Formatter for the voucher number: '{LV_NUMBER_PREFIX}' + zero-padded sequence value
-- with a MINIMUM of {LV_NUMBER_PAD} digits that GROWS naturally (LV-001 ... LV-999,
-- LV-1000, ...). Identical to Python format_number(). A fixed to_char mask (FM000)
-- was avoided on purpose: it overflows to '###' once the value exceeds 3 digits.
CREATE OR REPLACE FUNCTION loading_voucher_format_number(seq_value bigint)
    RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT '{LV_NUMBER_PREFIX}' ||
          lpad(seq_value::text, GREATEST({LV_NUMBER_PAD}, length(seq_value::text)), '0') $$;

-- Loading Voucher (one row per voucher — a single item, no detail-line table).
CREATE TABLE IF NOT EXISTS {TBL_LOADING_VOUCHERS} (
    id                     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    voucher_number         varchar(30) NOT NULL
                             DEFAULT loading_voucher_format_number(
                                         nextval('{LV_NUMBER_SEQUENCE}')),
    voucher_date           date NOT NULL DEFAULT CURRENT_DATE,
    voucher_time           time NOT NULL DEFAULT localtime,
    customer_id            integer,
    customer_name_snapshot varchar({MAX_CUSTOMER_NAME_LEN}),
    driver_name            varchar({MAX_DRIVER_NAME_LEN}),
    vehicle_number         varchar({MAX_VEHICLE_NUMBER_LEN}),
    weight_before_loading  varchar({MAX_WEIGHT_LEN}),
    weight_after_loading   varchar({MAX_WEIGHT_LEN}),
    product_id             integer,
    item_code_snapshot     integer,
    item_name_snapshot     varchar({MAX_ITEM_NAME_LEN}),
    unit_snapshot          varchar({MAX_UNIT_LEN}) NOT NULL DEFAULT '',
    quantity_tons          numeric({QUANTITY_PRECISION}, {QUANTITY_SCALE}),
    notes                  text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    created_by             integer,
    updated_by             integer,
    -- Every business field is optional (v1). Only voucher_number (auto) is
    -- guarded not-blank; a supplied quantity must be positive, but NULL is allowed.
    CONSTRAINT ck_loading_vouchers_quantity_positive
        CHECK (quantity_tons IS NULL OR quantity_tons > 0),
    CONSTRAINT ck_loading_vouchers_voucher_number_not_blank
        CHECK (char_length(btrim(voucher_number)) > 0),
    -- RESTRICT: a customer referenced by a voucher cannot be deleted.
    CONSTRAINT fk_loading_vouchers_customer
        FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    -- RESTRICT: an item referenced by a voucher cannot be deleted.
    CONSTRAINT fk_loading_vouchers_product
        FOREIGN KEY (product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    -- Audit user refs: nullable; deleting a user nulls the reference.
    CONSTRAINT fk_loading_vouchers_created_by
        FOREIGN KEY (created_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_loading_vouchers_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

-- Bind the sequence to the column so it is owned/dropped together and reported
-- by pg_get_serial_sequence. (No-op if already owned.)
ALTER SEQUENCE {LV_NUMBER_SEQUENCE} OWNED BY {TBL_LOADING_VOUCHERS}.voucher_number;

-- Idempotent, forward-only re-seed: on a re-run over a table that already holds
-- LV-<n> numbers, advance the sequence past the greatest existing <n> so the next
-- automatic number cannot collide. Never regresses, so a fresh table keeps its
-- first nextval() = {FIRST_LV_SEQ} (LV-001).
DO $$
DECLARE
    max_existing bigint;
    seq_last     bigint;
BEGIN
    SELECT COALESCE(
             MAX(CAST(substring(voucher_number FROM '^{LV_NUMBER_PREFIX}([0-9]+)$') AS bigint)),
             0)
      INTO max_existing
      FROM {TBL_LOADING_VOUCHERS}
     WHERE voucher_number ~ '^{LV_NUMBER_PREFIX}[0-9]+$';

    SELECT last_value INTO seq_last FROM {LV_NUMBER_SEQUENCE};

    IF max_existing > seq_last THEN
        PERFORM setval('{LV_NUMBER_SEQUENCE}', max_existing, true);
    END IF;
END $$;

-- Unique voucher number (final guard for automatic and manual numbers).
CREATE UNIQUE INDEX IF NOT EXISTS uq_loading_vouchers_voucher_number
    ON {TBL_LOADING_VOUCHERS} (voucher_number);

-- Report / lookup indexes.
CREATE INDEX IF NOT EXISTS idx_loading_vouchers_voucher_date
    ON {TBL_LOADING_VOUCHERS} (voucher_date);
CREATE INDEX IF NOT EXISTS idx_loading_vouchers_customer_id
    ON {TBL_LOADING_VOUCHERS} (customer_id);
CREATE INDEX IF NOT EXISTS idx_loading_vouchers_product_id
    ON {TBL_LOADING_VOUCHERS} (product_id);

-- Keep updated_at accurate on every UPDATE, whoever performs it. A dedicated
-- function name avoids clashing with the other modules' trigger functions and
-- keeps this schema block fully self-contained.
CREATE OR REPLACE FUNCTION loading_voucher_set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_loading_vouchers_set_updated_at ON {TBL_LOADING_VOUCHERS};
CREATE TRIGGER trg_loading_vouchers_set_updated_at
    BEFORE UPDATE ON {TBL_LOADING_VOUCHERS}
    FOR EACH ROW EXECUTE FUNCTION loading_voucher_set_updated_at();
"""


__all__ = [name for name in dir() if not name.startswith("_")]
