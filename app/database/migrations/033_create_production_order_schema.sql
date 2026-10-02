-- Migration 033 (UPGRADE): Production Order schema (أمر الإنتاج).
--
-- Creates the standalone ``production_orders`` (header) and
-- ``production_order_lines`` (materials) tables and their supporting objects
-- (numbering sequence, unique/report indexes, updated_at trigger). Does NOT
-- touch, drop, or alter any existing table or data. The tables reference the
-- existing ``products`` (finished product + component) and ``boms`` (the BOM
-- consumed) tables; no duplicate item / BOM master is created and NO BOM data is
-- modified.
--
-- WHAT / WHY
--   production_orders.id                  : PostgreSQL IDENTITY primary key. Never MAX(id)+1.
--   production_orders.order_number         : user-facing document number. Automatic
--                                            values come from the sequence
--                                            ``production_order_number_seq`` (first
--                                            nextval = 1, rendered as PRO-001, then
--                                            PRO-002, ...). Atomic and concurrency-safe;
--                                            the UNIQUE index is the final guard. Stays
--                                            editable — a manual PRO-<n> re-seeds the
--                                            sequence past <n> so a future automatic
--                                            number cannot collide. Padding (3 digits)
--                                            is a minimum -> grows past 999 to PRO-1000.
--                                            Never MAX(order_number)+1.
--   production_orders.order_date           : date, defaults to CURRENT_DATE.
--   production_orders.product_id           : NOT NULL, RESTRICT FK -> products(id)
--                                            (finished product).
--   production_orders.bom_id               : NOT NULL, RESTRICT FK -> boms(id) — the
--                                            exact BOM consumed by this order.
--   production_orders.production_quantity  : numeric(18,3), CHECK > 0 (الكمية المطلوب إنتاجها).
--   production_order_lines.production_order_id : NOT NULL, CASCADE FK -> production_orders(id).
--   production_order_lines.component_product_id: NOT NULL, RESTRICT FK -> products(id).
--   production_order_lines.bom_quantity_per_unit : numeric(18,3), CHECK > 0 — snapshot of
--                                            the BOM component quantity per finished unit.
--   production_order_lines.expected_quantity : numeric(18,3), CHECK >= 0 — stored snapshot of
--                                            production_quantity × bom_quantity_per_unit.
--   production_order_lines.actual_quantity : numeric(18,3), CHECK >= 0 — editable; defaults to
--                                            expected. Zero allowed; negative rejected.
--   production_order_lines.deviation       : STORED generated column
--                                            (actual_quantity - expected_quantity). Negative,
--                                            zero and positive are all valid (no CHECK).
--   production_order_lines.bom_price_snapshot : numeric(18,2) — historical price snapshot.
--                                            No cost total is computed/exposed in this version.
--   A component must not appear twice in the same order: UNIQUE (production_order_id,
--   component_product_id). Lines are also UNIQUE (production_order_id, line_number).
--   created_at / updated_at : timestamptz; updated_at maintained by a BEFORE UPDATE
--                             trigger. created_by / updated_by are nullable FKs ->
--                             app_users(id), ON DELETE SET NULL.
--
-- There is deliberately no document_status / workflow / warehouse / material-total
-- column — this is a simple document with no approval lifecycle, no inventory
-- posting and no costing in this version.
--
-- Mirrors app/models/production_order.py (PRODUCTION_ORDER_SCHEMA_SQL) and
-- app/database/schema/full_schema.sql. Reverse with
-- 033_downgrade_production_order_schema.sql.
--
-- Safe to run repeatedly: every statement uses CREATE ... IF NOT EXISTS /
-- CREATE OR REPLACE / a forward-only re-seed, and nothing is dropped or deleted.

BEGIN;

-- Sequence feeding automatic order numbers. A freshly-created sequence returns 1
-- on the FIRST nextval() (so the first document is PRO-001).
CREATE SEQUENCE IF NOT EXISTS production_order_number_seq AS bigint MINVALUE 1;

-- Formatter: 'PRO-' + zero-padded sequence value, MINIMUM 3 digits, unbounded
-- growth (PRO-001 ... PRO-999, PRO-1000, ...). Identical to Python format_number().
-- A fixed to_char mask (FM000) was avoided: it overflows to '###' past 3 digits.
CREATE OR REPLACE FUNCTION production_order_format_number(seq_value bigint)
    RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT 'PRO-' || lpad(seq_value::text, GREATEST(3, length(seq_value::text)), '0') $$;

CREATE TABLE IF NOT EXISTS production_orders (
    id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_number          varchar(30) NOT NULL
                            DEFAULT production_order_format_number(nextval('production_order_number_seq')),
    order_date            date NOT NULL DEFAULT CURRENT_DATE,
    product_id            integer NOT NULL,
    product_name_snapshot varchar(200) NOT NULL,
    bom_id                integer NOT NULL,
    production_quantity   numeric(18, 3) NOT NULL,
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
    CONSTRAINT fk_production_orders_product
        FOREIGN KEY (product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_production_orders_bom
        FOREIGN KEY (bom_id) REFERENCES boms (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_production_orders_created_by
        FOREIGN KEY (created_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_production_orders_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

ALTER SEQUENCE production_order_number_seq OWNED BY production_orders.order_number;

-- Forward-only re-seed (idempotent). On a fresh table this is a no-op, so the
-- first nextval() stays 1 (PRO-001). On a re-run over existing PRO-<n> data it
-- advances the sequence past the greatest existing <n>; it never regresses.
DO $$
DECLARE
    max_existing bigint;
    seq_last     bigint;
BEGIN
    SELECT COALESCE(
             MAX(CAST(substring(order_number FROM '^PRO-([0-9]+)$') AS bigint)),
             0)
      INTO max_existing
      FROM production_orders
     WHERE order_number ~ '^PRO-[0-9]+$';

    SELECT last_value INTO seq_last FROM production_order_number_seq;

    IF max_existing > seq_last THEN
        PERFORM setval('production_order_number_seq', max_existing, true);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS production_order_lines (
    id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    production_order_id   integer NOT NULL,
    line_number           integer NOT NULL,
    component_product_id  integer NOT NULL,
    item_code_snapshot    integer,
    item_name_snapshot    varchar(200) NOT NULL,
    unit_snapshot         varchar(50) NOT NULL DEFAULT '',
    bom_quantity_per_unit numeric(18, 3) NOT NULL,
    expected_quantity     numeric(18, 3) NOT NULL,
    actual_quantity       numeric(18, 3) NOT NULL,
    deviation             numeric(19, 3) GENERATED ALWAYS AS (actual_quantity - expected_quantity) STORED,
    bom_price_snapshot    numeric(18, 2) NOT NULL DEFAULT 0,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_po_lines_line_number_positive       CHECK (line_number > 0),
    CONSTRAINT ck_po_lines_bom_qty_per_unit_positive  CHECK (bom_quantity_per_unit > 0),
    CONSTRAINT ck_po_lines_expected_nonnegative       CHECK (expected_quantity >= 0),
    CONSTRAINT ck_po_lines_actual_nonnegative         CHECK (actual_quantity >= 0),
    CONSTRAINT ck_po_lines_bom_price_nonnegative      CHECK (bom_price_snapshot >= 0),
    CONSTRAINT ck_po_lines_item_name_not_blank
        CHECK (char_length(btrim(item_name_snapshot)) > 0),
    CONSTRAINT fk_po_lines_order
        FOREIGN KEY (production_order_id) REFERENCES production_orders (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_po_lines_component_product
        FOREIGN KEY (component_product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- Unique order number (final guard for automatic and manual numbers).
CREATE UNIQUE INDEX IF NOT EXISTS uq_production_orders_order_number
    ON production_orders (order_number);

-- One row per (order, line position) and one row per (order, component).
CREATE UNIQUE INDEX IF NOT EXISTS uq_po_lines_order_line
    ON production_order_lines (production_order_id, line_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_po_lines_order_component
    ON production_order_lines (production_order_id, component_product_id);

-- Report / lookup indexes.
CREATE INDEX IF NOT EXISTS idx_production_orders_order_date
    ON production_orders (order_date);
CREATE INDEX IF NOT EXISTS idx_production_orders_product_id
    ON production_orders (product_id);
CREATE INDEX IF NOT EXISTS idx_production_orders_bom_id
    ON production_orders (bom_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_order_id
    ON production_order_lines (production_order_id);
CREATE INDEX IF NOT EXISTS idx_po_lines_component_product_id
    ON production_order_lines (component_product_id);

-- Keep updated_at accurate on every UPDATE. A dedicated function name avoids
-- clashing with the other modules' trigger functions.
CREATE OR REPLACE FUNCTION production_order_set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_production_orders_set_updated_at ON production_orders;
CREATE TRIGGER trg_production_orders_set_updated_at
    BEFORE UPDATE ON production_orders
    FOR EACH ROW EXECUTE FUNCTION production_order_set_updated_at();

DROP TRIGGER IF EXISTS trg_po_lines_set_updated_at ON production_order_lines;
CREATE TRIGGER trg_po_lines_set_updated_at
    BEFORE UPDATE ON production_order_lines
    FOR EACH ROW EXECUTE FUNCTION production_order_set_updated_at();

COMMIT;

-- Post-conditions (informational): both tables exist + current row counts.
SELECT 'production_orders' AS table_created,
       (SELECT COUNT(*) FROM production_orders) AS row_count
UNION ALL
SELECT 'production_order_lines',
       (SELECT COUNT(*) FROM production_order_lines);
