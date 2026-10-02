"""Schema definition and domain constants for the Production Order module
(أمر الإنتاج).

Scope
-----
A Production Order is a *simple manufacturing document* that consumes an existing
BOM (قائمة المواد) to work out the raw-material issue requirement for producing a
given quantity of a finished product. A header names the finished product, the
BOM actually used, the production date and the quantity to produce; each line
carries a component with its expected issue quantity (= production quantity × the
BOM's per-unit quantity), an editable actual issue quantity and the resulting
deviation. There is **no** warehouse, no real inventory posting, no labour /
machine / routing / production-stage / overhead / approval-workflow data — those
are explicitly out of scope for this version.

This module holds the *structure* (DDL) and reusable domain constants only — no
SQL execution and no business logic. The repository layer runs
``PRODUCTION_ORDER_SCHEMA_SQL`` (every statement uses ``CREATE ... IF NOT EXISTS``
/ is otherwise idempotent, so it is safe to run repeatedly and never drops,
resets, or deletes anything). The same structure is mirrored in
``app/database/schema/full_schema.sql`` (runtime bootstrap) and
``app/database/migrations/033_create_production_order_schema.sql`` (with its
downgrade file), so a fresh install and an already-provisioned install converge
on the same shape.

Design notes
------------
* ``id`` on both tables is a PostgreSQL IDENTITY column (sequence-backed). Ids are
  never computed with ``MAX(id) + 1``.
* ``order_number`` is a user-facing document number that starts at ``PRO-001``.
  Automatic numbers come from the dedicated sequence
  ``production_order_number_seq`` (the first ``nextval`` returns ``1``, formatted
  as ``PRO-001``). ``nextval`` is atomic, so concurrent creators never receive the
  same number. A UNIQUE index is the final guard. The number stays editable: an
  authorised user may supply their own value, and the repository re-seeds the
  sequence past any manually-entered ``PRO-<n>`` so a high manual number can never
  collide with a future automatic one. The next number is never produced with
  ``MAX(order_number) + 1``. Padding is a *minimum* (3 digits), so it grows past
  999 -> ``PRO-1000``. The DB column DEFAULT formats the sequence value through the
  helper ``production_order_format_number(bigint)`` (``'PRO-' || lpad(...)`` with a
  ``GREATEST(3, length)`` width), which is byte-for-byte identical to the Python
  :func:`format_number` at every magnitude — a fixed ``to_char`` mask like
  ``FM000`` was deliberately avoided because it overflows to ``###`` past 999.
* ``order_date`` defaults to ``CURRENT_DATE`` when a new order is created.
* ``product_id`` (finished product), ``bom_id`` (the BOM consumed) and
  ``production_order_lines.component_product_id`` are RESTRICT foreign keys to the
  existing ``products`` / ``boms`` tables — a product or BOM referenced by a
  Production Order cannot be deleted. No duplicate item / BOM master is created.
* ``production_order_lines.item_code_snapshot`` mirrors the physical type of
  ``products.item_code`` (``integer``) — the same convention as ``bom_lines``.
* ``production_order_lines.deviation`` is a STORED generated column
  ``actual_quantity - expected_quantity`` — the same project convention as
  ``bom_lines.line_total`` / ``products.total``; the application never writes it.
  Negative, zero and positive values are all valid, so there is deliberately **no**
  non-negative CHECK on it.
* ``bom_quantity_per_unit`` / ``expected_quantity`` / snapshots (item code / name /
  unit / BOM price) are stored so an old Production Order never changes when the
  product master or the BOM is later edited.
* ``bom_price_snapshot`` is stored now (historical snapshot) but no cost total is
  computed or exposed in this version — quantity issuing + deviation only.
* Audit fields mirror the project's document convention (see ``boms`` /
  ``purchase_invoices``): ``created_at`` / ``updated_at`` are ``timestamptz`` and
  ``updated_at`` is maintained by a BEFORE UPDATE trigger; ``created_by`` /
  ``updated_by`` are nullable FKs to ``app_users(id)`` with ``ON DELETE SET NULL``.
  There is deliberately **no** ``document_status`` / workflow / warehouse /
  material-total column — this simple document has no approval lifecycle, no
  inventory posting and no costing in this version.

The live application talks to PostgreSQL through the raw-psycopg
``ProductionOrderRepository`` (mirroring the BOM module), so no SQLAlchemy ORM
model is defined here.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# --- table names ------------------------------------------------------------

TBL_PRODUCTION_ORDERS = "production_orders"
TBL_PRODUCTION_ORDER_LINES = "production_order_lines"

# --- automatic numbering ("PRO-001", "PRO-002", ...) -------------------------
# The sequence yields 1, 2, 3, ... and the number is rendered as
# ``PRO-<zero-padded-to-3>`` -> PRO-001, PRO-002, ... (padding is a minimum, so it
# grows past 999 -> PRO-1000). The SQL column DEFAULT formats the sequence value
# the same way ``format_number`` does (``to_char(n, 'FM000')`` == f"{n:03d}").
PRO_NUMBER_SEQUENCE = "production_order_number_seq"
PRO_NUMBER_PREFIX = "PRO-"
PRO_NUMBER_PAD = 3            # minimum digits (grows past 999 -> PRO-1000)
FIRST_PRO_SEQ = 1            # first sequence value -> PRO-001

# Recognises an automatic-style number: PRO- followed by digits only.
_AUTO_NUMBER_RE = re.compile(rf"^{re.escape(PRO_NUMBER_PREFIX)}(\d+)$")


def format_number(sequence_value: Any) -> str:
    """Render a raw sequence value as a ``PRO-<n>`` document number.

    ``format_number(1) == 'PRO-001'``; padding is a minimum, not a cap, so
    ``format_number(1000) == 'PRO-1000'``.
    """
    return f"{PRO_NUMBER_PREFIX}{int(sequence_value):0{PRO_NUMBER_PAD}d}"


def parse_sequence_value(order_number: Any) -> int | None:
    """Return the integer ``n`` from a ``PRO-<n>`` number, or ``None``.

    Only the canonical ``PRO-<digits>`` shape is recognised; anything else
    (a free-form manual string) returns ``None`` so it never moves the automatic
    sequence. The UNIQUE index remains the final duplicate guard in every case.
    """
    if order_number is None:
        return None
    match = _AUTO_NUMBER_RE.match(str(order_number).strip())
    return int(match.group(1)) if match else None


# --- numeric precision (must not exceed the physical column definitions) -----

QUANTITY_PRECISION, QUANTITY_SCALE = 18, 3   # numeric(18,3) — mirrors products/bom
MONEY_PRECISION, MONEY_SCALE = 18, 2         # numeric(18,2) — mirrors bom price
# deviation = actual(18,3) - expected(18,3): one extra integer digit of headroom
# so a large positive-minus-negative can never overflow. numeric(19,3).
DEVIATION_PRECISION, DEVIATION_SCALE = 19, 3

MONEY_QUANT = Decimal("0.01")                # money rounds to 2 dp
QTY_QUANT = Decimal("0.001")                 # quantity rounds to 3 dp

# --- snapshot length limit (mirrors the physical varchar length) -------------
MAX_ITEM_NAME_LEN = 200                       # *_name_snapshot varchar(200)

# --- header columns the application is allowed to write ----------------------
# ``id`` (IDENTITY), ``order_number`` (DB DEFAULT unless supplied) and the
# timestamps (DB defaults / trigger) are database-managed; ``order_number`` may
# still be passed explicitly to store a manual number.
ORDER_INSERT_COLUMNS: tuple[str, ...] = (
    "order_number",
    "order_date",
    "product_id",
    "product_name_snapshot",
    "bom_id",
    "production_quantity",
    "created_by",
    "updated_by",
)

# Header columns read back / shown on the screen.
ORDER_SELECT_COLUMNS: tuple[str, ...] = (
    "id",
    "order_number",
    "order_date",
    "product_id",
    "product_name_snapshot",
    "bom_id",
    "production_quantity",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
)

# Detail-line columns the application writes. ``id`` is IDENTITY, ``deviation`` is
# a generated column, and the timestamps default in the database.
LINE_INSERT_COLUMNS: tuple[str, ...] = (
    "production_order_id",
    "line_number",
    "component_product_id",
    "item_code_snapshot",
    "item_name_snapshot",
    "unit_snapshot",
    "bom_quantity_per_unit",
    "expected_quantity",
    "actual_quantity",
    "bom_price_snapshot",
)

LINE_SELECT_COLUMNS: tuple[str, ...] = ("id",) + LINE_INSERT_COLUMNS + ("deviation",)


# --- raw DDL (source of truth, mirrored by migration 033 + full_schema.sql) --
#
# Fully idempotent and self-contained: every statement is CREATE ... IF NOT
# EXISTS / CREATE OR REPLACE / a guarded forward-only re-seed. The order_number
# DEFAULT formats the sequence value through production_order_format_number(),
# which is identical to ``format_number`` in Python at every magnitude (min 3
# digits, unbounded growth), so a number produced by the database DEFAULT and one
# produced by the app are identical.

PRODUCTION_ORDER_SCHEMA_SQL = f"""
-- Sequence that feeds automatic Production Order numbers. A freshly-created
-- sequence returns {FIRST_PRO_SEQ} on the FIRST nextval() (so the first document
-- is PRO-001). nextval is atomic, so concurrent creators never share a number.
CREATE SEQUENCE IF NOT EXISTS {PRO_NUMBER_SEQUENCE} AS bigint MINVALUE 1;

-- Formatter for the order number: '{PRO_NUMBER_PREFIX}' + zero-padded sequence value
-- with a MINIMUM of {PRO_NUMBER_PAD} digits that GROWS naturally (PRO-001 ... PRO-999,
-- PRO-1000, ...). Identical to Python format_number(). A fixed to_char mask (FM000)
-- was avoided on purpose: it overflows to '###' once the value exceeds 3 digits.
CREATE OR REPLACE FUNCTION production_order_format_number(seq_value bigint)
    RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT '{PRO_NUMBER_PREFIX}' ||
          lpad(seq_value::text, GREATEST({PRO_NUMBER_PAD}, length(seq_value::text)), '0') $$;

-- Production Order header (one row per manufacturing order).
CREATE TABLE IF NOT EXISTS {TBL_PRODUCTION_ORDERS} (
    id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_number          varchar(30) NOT NULL
                            DEFAULT production_order_format_number(
                                        nextval('{PRO_NUMBER_SEQUENCE}')),
    order_date            date NOT NULL DEFAULT CURRENT_DATE,
    product_id            integer NOT NULL,
    product_name_snapshot varchar({MAX_ITEM_NAME_LEN}) NOT NULL,
    bom_id                integer NOT NULL,
    production_quantity   numeric({QUANTITY_PRECISION}, {QUANTITY_SCALE}) NOT NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    created_by            integer,
    updated_by            integer,
    CONSTRAINT ck_production_orders_quantity_positive
        CHECK (production_quantity > 0),
    CONSTRAINT ck_production_orders_order_number_not_blank
        CHECK (char_length(btrim(order_number)) > 0),
    CONSTRAINT ck_production_orders_product_name_not_blank
        CHECK (char_length(btrim(product_name_snapshot)) > 0),
    -- RESTRICT: a finished product referenced by an order cannot be deleted.
    CONSTRAINT fk_production_orders_product
        FOREIGN KEY (product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    -- RESTRICT: the BOM consumed by an order cannot be deleted while referenced.
    CONSTRAINT fk_production_orders_bom
        FOREIGN KEY (bom_id) REFERENCES boms (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    -- Audit user refs: nullable; deleting a user nulls the reference.
    CONSTRAINT fk_production_orders_created_by
        FOREIGN KEY (created_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_production_orders_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

-- Bind the sequence to the column so it is owned/dropped together and reported
-- by pg_get_serial_sequence. (No-op if already owned.)
ALTER SEQUENCE {PRO_NUMBER_SEQUENCE} OWNED BY {TBL_PRODUCTION_ORDERS}.order_number;

-- Idempotent, forward-only re-seed: on a re-run over a table that already holds
-- PRO-<n> numbers, advance the sequence past the greatest existing <n> so the
-- next automatic number cannot collide. Never regresses, so a fresh table keeps
-- its first nextval() = {FIRST_PRO_SEQ} (PRO-001).
DO $$
DECLARE
    max_existing bigint;
    seq_last     bigint;
BEGIN
    SELECT COALESCE(
             MAX(CAST(substring(order_number FROM '^{PRO_NUMBER_PREFIX}([0-9]+)$') AS bigint)),
             0)
      INTO max_existing
      FROM {TBL_PRODUCTION_ORDERS}
     WHERE order_number ~ '^{PRO_NUMBER_PREFIX}[0-9]+$';

    SELECT last_value INTO seq_last FROM {PRO_NUMBER_SEQUENCE};

    IF max_existing > seq_last THEN
        PERFORM setval('{PRO_NUMBER_SEQUENCE}', max_existing, true);
    END IF;
END $$;

-- Production Order material lines. deviation is a STORED generated column.
CREATE TABLE IF NOT EXISTS {TBL_PRODUCTION_ORDER_LINES} (
    id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    production_order_id   integer NOT NULL,
    line_number           integer NOT NULL,
    component_product_id  integer NOT NULL,
    item_code_snapshot    integer,
    item_name_snapshot    varchar({MAX_ITEM_NAME_LEN}) NOT NULL,
    unit_snapshot         varchar(50) NOT NULL DEFAULT '',
    bom_quantity_per_unit numeric({QUANTITY_PRECISION}, {QUANTITY_SCALE}) NOT NULL,
    expected_quantity     numeric({QUANTITY_PRECISION}, {QUANTITY_SCALE}) NOT NULL,
    actual_quantity       numeric({QUANTITY_PRECISION}, {QUANTITY_SCALE}) NOT NULL,
    deviation             numeric({DEVIATION_PRECISION}, {DEVIATION_SCALE})
                            GENERATED ALWAYS AS (actual_quantity - expected_quantity) STORED,
    bom_price_snapshot    numeric({MONEY_PRECISION}, {MONEY_SCALE}) NOT NULL DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_po_lines_line_number_positive       CHECK (line_number > 0),
    CONSTRAINT ck_po_lines_bom_qty_per_unit_positive  CHECK (bom_quantity_per_unit > 0),
    CONSTRAINT ck_po_lines_expected_nonnegative       CHECK (expected_quantity >= 0),
    CONSTRAINT ck_po_lines_actual_nonnegative         CHECK (actual_quantity >= 0),
    CONSTRAINT ck_po_lines_bom_price_nonnegative      CHECK (bom_price_snapshot >= 0),
    CONSTRAINT ck_po_lines_item_name_not_blank
        CHECK (char_length(btrim(item_name_snapshot)) > 0),
    -- CASCADE: deleting an order removes its lines.
    CONSTRAINT fk_po_lines_order
        FOREIGN KEY (production_order_id) REFERENCES {TBL_PRODUCTION_ORDERS} (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    -- RESTRICT: a component product referenced by a line cannot be deleted.
    CONSTRAINT fk_po_lines_component_product
        FOREIGN KEY (component_product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- Unique order number (final guard for automatic and manual numbers).
CREATE UNIQUE INDEX IF NOT EXISTS uq_production_orders_order_number
    ON {TBL_PRODUCTION_ORDERS} (order_number);

-- One row per (order, line position) and one row per (order, component): a
-- component must not appear twice in the same order.
CREATE UNIQUE INDEX IF NOT EXISTS uq_po_lines_order_line
    ON {TBL_PRODUCTION_ORDER_LINES} (production_order_id, line_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_po_lines_order_component
    ON {TBL_PRODUCTION_ORDER_LINES} (production_order_id, component_product_id);

-- Report / lookup indexes.
CREATE INDEX IF NOT EXISTS idx_production_orders_order_date
    ON {TBL_PRODUCTION_ORDERS} (order_date);
CREATE INDEX IF NOT EXISTS idx_production_orders_product_id
    ON {TBL_PRODUCTION_ORDERS} (product_id);
CREATE INDEX IF NOT EXISTS idx_production_orders_bom_id
    ON {TBL_PRODUCTION_ORDERS} (bom_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_order_id
    ON {TBL_PRODUCTION_ORDER_LINES} (production_order_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_component_product_id
    ON {TBL_PRODUCTION_ORDER_LINES} (component_product_id);

-- Keep updated_at accurate on every UPDATE, whoever performs it. A dedicated
-- function name avoids clashing with the other modules' trigger functions and
-- keeps this schema block fully self-contained.
CREATE OR REPLACE FUNCTION production_order_set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_production_orders_set_updated_at ON {TBL_PRODUCTION_ORDERS};
CREATE TRIGGER trg_production_orders_set_updated_at
    BEFORE UPDATE ON {TBL_PRODUCTION_ORDERS}
    FOR EACH ROW EXECUTE FUNCTION production_order_set_updated_at();

DROP TRIGGER IF EXISTS trg_po_lines_set_updated_at ON {TBL_PRODUCTION_ORDER_LINES};
CREATE TRIGGER trg_po_lines_set_updated_at
    BEFORE UPDATE ON {TBL_PRODUCTION_ORDER_LINES}
    FOR EACH ROW EXECUTE FUNCTION production_order_set_updated_at();
"""


__all__ = [name for name in dir() if not name.startswith("_")]
