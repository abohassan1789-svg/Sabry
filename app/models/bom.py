"""Schema definition and domain constants for the Bill of Materials module
(قائمة المواد / حساب تكلفة الخامات).

Scope
-----
A BOM is a *material-cost* document only: a header naming the finished product
and a set of component lines (item + quantity + price). There is **no** labour,
machine, routing, production-order, overhead or multi-level-BOM data — those are
explicitly out of scope.

This module holds the *structure* (DDL) and reusable domain constants only — no
SQL execution and no business logic. The repository layer runs
``BOM_SCHEMA_SQL`` (every statement uses ``CREATE ... IF NOT EXISTS`` / is
otherwise idempotent, so it is safe to run repeatedly and never drops, resets, or
deletes anything). The same structure is mirrored in
``app/database/schema/full_schema.sql`` (runtime bootstrap) and
``app/database/migrations/032_create_bom_schema.sql`` (with its downgrade file),
so a fresh install and an already-provisioned install converge on the same shape.

Design notes
------------
* ``id`` on both tables is a PostgreSQL IDENTITY column (sequence-backed). Ids are
  never computed with ``MAX(id) + 1``.
* ``bom_number`` is a user-facing document number that starts at ``BOM-0001``.
  Automatic numbers come from the dedicated sequence ``bom_number_seq`` (the first
  ``nextval`` returns ``1``, formatted as ``BOM-0001``). ``nextval`` is atomic, so
  concurrent creators never receive the same number. A UNIQUE index is the final
  guard. The number stays editable: an authorised user may supply their own value,
  and the repository re-seeds the sequence past any manually-entered ``BOM-<n>`` so
  a high manual number can never collide with a future automatic one. The next
  number is never produced with ``MAX(bom_number) + 1``.
* ``bom_date`` defaults to ``CURRENT_DATE`` when a new BOM is created.
* ``product_id`` (finished product) and ``bom_lines.component_product_id`` are
  RESTRICT foreign keys to the existing ``products`` table (PK ``id``) — a product
  used by a BOM cannot be deleted. No duplicate item master is created.
* ``bom_lines.item_code_snapshot`` mirrors the physical type of the item code
  column on ``products`` — ``products.item_code`` is ``integer`` (there is no
  ``products.code`` column), so the snapshot is ``integer`` too.
* ``bom_lines.line_total`` is a STORED generated column ``quantity * price`` — the
  same project convention as ``products.total``; the application never writes it.
* ``boms.total_material_cost`` is the sum of the line totals. Unlike a single-row
  generated column it aggregates across rows, so it is recomputed server-side (in
  :mod:`app.services.bom_service`, always in :class:`decimal.Decimal`) and stored;
  a CHECK keeps it non-negative.
* Audit fields mirror the project's document convention (see ``receipt_vouchers``
  / ``purchase_invoices``): ``created_at`` / ``updated_at`` are ``timestamptz`` and
  ``updated_at`` is maintained by a BEFORE UPDATE trigger; ``created_by`` /
  ``updated_by`` are nullable FKs to ``app_users(id)`` with ``ON DELETE SET NULL``.
  There is deliberately **no** ``document_status`` / workflow / ``row_version``
  column — this simple material-cost document has no approval lifecycle.

The live application talks to PostgreSQL through the raw-psycopg
``BomRepository`` (mirroring the purchase-invoice module), so no SQLAlchemy ORM
model is defined here.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# --- table names ------------------------------------------------------------

TBL_BOMS = "boms"
TBL_BOM_LINES = "bom_lines"

# --- automatic numbering ("BOM-0001", "BOM-0002", ...) -----------------------
# The sequence yields 1, 2, 3, ... and the number is rendered as
# ``BOM-<zero-padded-to-4>`` -> BOM-0001, BOM-0002, ... (padding is a minimum, so
# it grows past 9999 -> BOM-10000). The SQL column DEFAULT formats the sequence
# value the same way ``format_number`` does (``to_char(n, 'FM0000')`` == f"{n:04d}").
BOM_NUMBER_SEQUENCE = "bom_number_seq"
BOM_NUMBER_PREFIX = "BOM-"
BOM_NUMBER_PAD = 4            # minimum digits (grows past 9999 -> BOM-10000)
FIRST_BOM_SEQ = 1            # first sequence value -> BOM-0001

# Recognises an automatic-style number: BOM- followed by digits only.
_AUTO_NUMBER_RE = re.compile(rf"^{re.escape(BOM_NUMBER_PREFIX)}(\d+)$")


def format_number(sequence_value: Any) -> str:
    """Render a raw sequence value as a ``BOM-<n>`` document number.

    ``format_number(1) == 'BOM-0001'``; padding is a minimum, not a cap, so
    ``format_number(10000) == 'BOM-10000'``.
    """
    return f"{BOM_NUMBER_PREFIX}{int(sequence_value):0{BOM_NUMBER_PAD}d}"


def parse_sequence_value(bom_number: Any) -> int | None:
    """Return the integer ``n`` from a ``BOM-<n>`` number, or ``None``.

    Only the canonical ``BOM-<digits>`` shape is recognised; anything else
    (a free-form manual string) returns ``None`` so it never moves the automatic
    sequence. The UNIQUE index remains the final duplicate guard in every case.
    """
    if bom_number is None:
        return None
    match = _AUTO_NUMBER_RE.match(str(bom_number).strip())
    return int(match.group(1)) if match else None


# --- numeric precision (must not exceed the physical column definitions) -----

QUANTITY_PRECISION, QUANTITY_SCALE = 18, 3   # numeric(18,3) — mirrors products.quantity
MONEY_PRECISION, MONEY_SCALE = 18, 2         # numeric(18,2) — mirrors products.price
# line_total = quantity(18,3) * price(18,2) -> numeric(23,5), mirrors products.total.
LINE_TOTAL_PRECISION = MONEY_PRECISION + QUANTITY_SCALE + 2
LINE_TOTAL_SCALE = MONEY_SCALE + QUANTITY_SCALE

MONEY_QUANT = Decimal("0.01")                # money rounds to 2 dp
QTY_QUANT = Decimal("0.001")                 # quantity rounds to 3 dp

# --- snapshot length limit (mirrors the physical varchar length) -------------
MAX_ITEM_NAME_LEN = 200                       # item_name_snapshot varchar(200)

# --- header columns the application is allowed to write ----------------------
# ``id`` (IDENTITY), ``bom_number`` (DB DEFAULT unless supplied) and the
# timestamps (DB defaults / trigger) are database-managed; ``bom_number`` may
# still be passed explicitly to store a manual number.
BOM_INSERT_COLUMNS: tuple[str, ...] = (
    "bom_number",
    "bom_date",
    "product_id",
    "product_name_snapshot",
    "total_material_cost",
    "created_by",
    "updated_by",
)

# Header columns read back / shown on the screen.
BOM_SELECT_COLUMNS: tuple[str, ...] = (
    "id",
    "bom_number",
    "bom_date",
    "product_id",
    "product_name_snapshot",
    "total_material_cost",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
)

# Detail-line columns the application writes. ``id`` is IDENTITY, ``line_total``
# is a generated column, and the timestamps default in the database.
LINE_INSERT_COLUMNS: tuple[str, ...] = (
    "bom_id",
    "line_number",
    "component_product_id",
    "item_code_snapshot",
    "item_name_snapshot",
    "unit_snapshot",
    "quantity",
    "price",
)

LINE_SELECT_COLUMNS: tuple[str, ...] = ("id",) + LINE_INSERT_COLUMNS + ("line_total",)


# --- raw DDL (source of truth, mirrored by migration 032 + full_schema.sql) --
#
# Fully idempotent and self-contained: every statement is CREATE ... IF NOT
# EXISTS / CREATE OR REPLACE / a guarded forward-only re-seed. The bom_number
# DEFAULT formats the sequence value exactly like ``format_number`` in Python
# (``to_char(n, 'FM0000')`` == f"{n:04d}"), so a number produced by the database
# DEFAULT and one produced by the app are identical.

BOM_SCHEMA_SQL = f"""
-- Sequence that feeds automatic BOM numbers. A freshly-created sequence returns
-- {FIRST_BOM_SEQ} on the FIRST nextval() (so the first document is BOM-0001).
-- nextval is atomic, so concurrent creators never share a number.
CREATE SEQUENCE IF NOT EXISTS {BOM_NUMBER_SEQUENCE} AS bigint MINVALUE 1;

-- BOM header (one row per finished-product material list).
CREATE TABLE IF NOT EXISTS {TBL_BOMS} (
    id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bom_number            varchar(30) NOT NULL
                            DEFAULT ('{BOM_NUMBER_PREFIX}' ||
                                     to_char(nextval('{BOM_NUMBER_SEQUENCE}'), 'FM0000')),
    bom_date              date NOT NULL DEFAULT CURRENT_DATE,
    product_id            integer NOT NULL,
    product_name_snapshot varchar({MAX_ITEM_NAME_LEN}) NOT NULL,
    total_material_cost   numeric({MONEY_PRECISION}, {MONEY_SCALE}) NOT NULL DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    created_by            integer,
    updated_by            integer,
    CONSTRAINT ck_boms_total_material_cost_nonnegative
        CHECK (total_material_cost >= 0),
    CONSTRAINT ck_boms_bom_number_not_blank
        CHECK (char_length(btrim(bom_number)) > 0),
    CONSTRAINT ck_boms_product_name_not_blank
        CHECK (char_length(btrim(product_name_snapshot)) > 0),
    -- RESTRICT: a finished product referenced by a BOM cannot be deleted.
    CONSTRAINT fk_boms_product
        FOREIGN KEY (product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    -- Audit user refs: nullable; deleting a user nulls the reference.
    CONSTRAINT fk_boms_created_by
        FOREIGN KEY (created_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_boms_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

-- Bind the sequence to the column so it is owned/dropped together and reported
-- by pg_get_serial_sequence. (No-op if already owned.)
ALTER SEQUENCE {BOM_NUMBER_SEQUENCE} OWNED BY {TBL_BOMS}.bom_number;

-- Idempotent, forward-only re-seed: on a re-run over a table that already holds
-- BOM-<n> numbers, advance the sequence past the greatest existing <n> so the
-- next automatic number cannot collide. Never regresses, so a fresh table keeps
-- its first nextval() = {FIRST_BOM_SEQ} (BOM-0001).
DO $$
DECLARE
    max_existing bigint;
    seq_last     bigint;
BEGIN
    SELECT COALESCE(
             MAX(CAST(substring(bom_number FROM '^{BOM_NUMBER_PREFIX}([0-9]+)$') AS bigint)),
             0)
      INTO max_existing
      FROM {TBL_BOMS}
     WHERE bom_number ~ '^{BOM_NUMBER_PREFIX}[0-9]+$';

    SELECT last_value INTO seq_last FROM {BOM_NUMBER_SEQUENCE};

    IF max_existing > seq_last THEN
        PERFORM setval('{BOM_NUMBER_SEQUENCE}', max_existing, true);
    END IF;
END $$;

-- BOM component lines. line_total is a STORED generated column (never written).
CREATE TABLE IF NOT EXISTS {TBL_BOM_LINES} (
    id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bom_id               integer NOT NULL,
    line_number          integer NOT NULL,
    component_product_id integer NOT NULL,
    item_code_snapshot   integer,
    item_name_snapshot   varchar({MAX_ITEM_NAME_LEN}) NOT NULL,
    unit_snapshot        varchar(50) NOT NULL DEFAULT '',
    quantity             numeric({QUANTITY_PRECISION}, {QUANTITY_SCALE}) NOT NULL,
    price                numeric({MONEY_PRECISION}, {MONEY_SCALE}) NOT NULL DEFAULT 0,
    line_total           numeric({LINE_TOTAL_PRECISION}, {LINE_TOTAL_SCALE})
                            GENERATED ALWAYS AS (quantity * price) STORED,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_bom_lines_line_number_positive CHECK (line_number > 0),
    CONSTRAINT ck_bom_lines_quantity_positive    CHECK (quantity > 0),
    CONSTRAINT ck_bom_lines_price_nonnegative    CHECK (price >= 0),
    CONSTRAINT ck_bom_lines_item_name_not_blank
        CHECK (char_length(btrim(item_name_snapshot)) > 0),
    -- CASCADE: deleting a BOM removes its lines.
    CONSTRAINT fk_bom_lines_bom
        FOREIGN KEY (bom_id) REFERENCES {TBL_BOMS} (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    -- RESTRICT: a component product referenced by a BOM line cannot be deleted.
    CONSTRAINT fk_bom_lines_component_product
        FOREIGN KEY (component_product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- Unique BOM number (final guard for automatic and manual numbers).
CREATE UNIQUE INDEX IF NOT EXISTS uq_boms_bom_number ON {TBL_BOMS} (bom_number);

-- One row per (bom, line position) and one row per (bom, component): a component
-- must not appear twice in the same BOM (DB guard for the service-level rule).
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_lines_bom_line
    ON {TBL_BOM_LINES} (bom_id, line_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_lines_bom_component
    ON {TBL_BOM_LINES} (bom_id, component_product_id);

-- Report / lookup indexes.
CREATE INDEX IF NOT EXISTS idx_boms_bom_date ON {TBL_BOMS} (bom_date);
CREATE INDEX IF NOT EXISTS idx_boms_product_id ON {TBL_BOMS} (product_id);
CREATE INDEX IF NOT EXISTS idx_bom_lines_bom_id ON {TBL_BOM_LINES} (bom_id);
CREATE INDEX IF NOT EXISTS idx_bom_lines_component_product_id
    ON {TBL_BOM_LINES} (component_product_id);

-- Keep updated_at accurate on every UPDATE, whoever performs it. A dedicated
-- function name avoids clashing with the other modules' trigger functions and
-- keeps this schema block fully self-contained.
CREATE OR REPLACE FUNCTION bom_set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_boms_set_updated_at ON {TBL_BOMS};
CREATE TRIGGER trg_boms_set_updated_at
    BEFORE UPDATE ON {TBL_BOMS}
    FOR EACH ROW EXECUTE FUNCTION bom_set_updated_at();

DROP TRIGGER IF EXISTS trg_bom_lines_set_updated_at ON {TBL_BOM_LINES};
CREATE TRIGGER trg_bom_lines_set_updated_at
    BEFORE UPDATE ON {TBL_BOM_LINES}
    FOR EACH ROW EXECUTE FUNCTION bom_set_updated_at();
"""


__all__ = [name for name in dir() if not name.startswith("_")]
