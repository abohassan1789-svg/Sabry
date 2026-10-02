-- Migration 032 (UPGRADE): Bill of Materials schema (قائمة المواد).
--
-- Creates the standalone ``boms`` (header) and ``bom_lines`` (components) tables
-- and their supporting objects (numbering sequence, unique/report indexes,
-- updated_at trigger). Does NOT touch, drop, or alter any existing table or data.
-- The two tables reference the existing ``products`` table (finished product +
-- component); no duplicate item master is created.
--
-- WHAT / WHY
--   boms.id                    : PostgreSQL IDENTITY primary key. Never MAX(id)+1.
--   boms.bom_number            : user-facing document number. Automatic values
--                                come from the sequence ``bom_number_seq`` (first
--                                nextval = 1, rendered as BOM-0001, then BOM-0002,
--                                ...). Atomic and concurrency-safe; the UNIQUE
--                                index is the final guard. Stays editable — a
--                                manual BOM-<n> re-seeds the sequence past <n> so a
--                                future automatic number cannot collide. Never
--                                MAX(bom_number)+1.
--   boms.bom_date              : date, defaults to CURRENT_DATE for a new BOM.
--   boms.product_id            : NOT NULL, RESTRICT FK -> products(id) (finished
--                                product). A product used by a BOM cannot be deleted.
--   boms.product_name_snapshot : finished-product name captured at save time.
--   boms.total_material_cost   : numeric(18,2), CHECK >= 0. Recomputed server-side
--                                (sum of the line totals) and stored.
--   bom_lines.bom_id           : NOT NULL, CASCADE FK -> boms(id). Deleting a BOM
--                                removes its lines.
--   bom_lines.component_product_id : NOT NULL, RESTRICT FK -> products(id).
--   bom_lines.item_code_snapshot   : integer — mirrors products.item_code's type
--                                (there is no products.code column).
--   bom_lines.quantity         : numeric(18,3), CHECK > 0.
--   bom_lines.price            : numeric(18,2), CHECK >= 0 (snapshot of the price
--                                used in this BOM).
--   bom_lines.line_total       : STORED generated column (quantity * price) — the
--                                same convention as products.total; never written.
--   A component must not appear twice in the same BOM: UNIQUE (bom_id,
--   component_product_id). Lines are also UNIQUE (bom_id, line_number).
--   created_at / updated_at    : timestamptz; updated_at maintained by a BEFORE
--                                UPDATE trigger. created_by / updated_by are
--                                nullable FKs -> app_users(id), ON DELETE SET NULL.
--
-- There is deliberately no document_status / workflow / row_version column — this
-- is a simple material-cost document with no approval lifecycle.
--
-- Mirrors app/models/bom.py (BOM_SCHEMA_SQL) and app/database/schema/full_schema.sql.
-- Reverse with 032_downgrade_bom_schema.sql.
--
-- Safe to run repeatedly: every statement uses CREATE ... IF NOT EXISTS /
-- CREATE OR REPLACE / a forward-only re-seed, and nothing is dropped or deleted.

BEGIN;

-- Sequence feeding automatic BOM numbers. A freshly-created sequence returns 1 on
-- the FIRST nextval() (so the first document is BOM-0001).
CREATE SEQUENCE IF NOT EXISTS bom_number_seq AS bigint MINVALUE 1;

CREATE TABLE IF NOT EXISTS boms (
    id                    integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bom_number            varchar(30) NOT NULL
                            DEFAULT ('BOM-' || to_char(nextval('bom_number_seq'), 'FM0000')),
    bom_date              date NOT NULL DEFAULT CURRENT_DATE,
    product_id            integer NOT NULL,
    product_name_snapshot varchar(200) NOT NULL,
    total_material_cost   numeric(18, 2) NOT NULL DEFAULT 0,
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
    CONSTRAINT fk_boms_product
        FOREIGN KEY (product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_boms_created_by
        FOREIGN KEY (created_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_boms_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_users (id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

ALTER SEQUENCE bom_number_seq OWNED BY boms.bom_number;

-- Forward-only re-seed (idempotent). On a fresh table this is a no-op, so the
-- first nextval() stays 1 (BOM-0001). On a re-run over existing BOM-<n> data it
-- advances the sequence past the greatest existing <n>; it never regresses.
DO $$
DECLARE
    max_existing bigint;
    seq_last     bigint;
BEGIN
    SELECT COALESCE(
             MAX(CAST(substring(bom_number FROM '^BOM-([0-9]+)$') AS bigint)),
             0)
      INTO max_existing
      FROM boms
     WHERE bom_number ~ '^BOM-[0-9]+$';

    SELECT last_value INTO seq_last FROM bom_number_seq;

    IF max_existing > seq_last THEN
        PERFORM setval('bom_number_seq', max_existing, true);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS bom_lines (
    id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bom_id               integer NOT NULL,
    line_number          integer NOT NULL,
    component_product_id integer NOT NULL,
    item_code_snapshot   integer,
    item_name_snapshot   varchar(200) NOT NULL,
    unit_snapshot        varchar(50) NOT NULL DEFAULT '',
    quantity             numeric(18, 3) NOT NULL,
    price                numeric(18, 2) NOT NULL DEFAULT 0,
    line_total           numeric(23, 5) GENERATED ALWAYS AS (quantity * price) STORED,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_bom_lines_line_number_positive CHECK (line_number > 0),
    CONSTRAINT ck_bom_lines_quantity_positive    CHECK (quantity > 0),
    CONSTRAINT ck_bom_lines_price_nonnegative    CHECK (price >= 0),
    CONSTRAINT ck_bom_lines_item_name_not_blank
        CHECK (char_length(btrim(item_name_snapshot)) > 0),
    CONSTRAINT fk_bom_lines_bom
        FOREIGN KEY (bom_id) REFERENCES boms (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_bom_lines_component_product
        FOREIGN KEY (component_product_id) REFERENCES products (id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- Unique BOM number (final guard for automatic and manual numbers).
CREATE UNIQUE INDEX IF NOT EXISTS uq_boms_bom_number ON boms (bom_number);

-- One row per (bom, line position) and one row per (bom, component).
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_lines_bom_line
    ON bom_lines (bom_id, line_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bom_lines_bom_component
    ON bom_lines (bom_id, component_product_id);

-- Report / lookup indexes.
CREATE INDEX IF NOT EXISTS idx_boms_bom_date ON boms (bom_date);
CREATE INDEX IF NOT EXISTS idx_boms_product_id ON boms (product_id);
CREATE INDEX IF NOT EXISTS idx_bom_lines_bom_id ON bom_lines (bom_id);
CREATE INDEX IF NOT EXISTS idx_bom_lines_component_product_id
    ON bom_lines (component_product_id);

-- Keep updated_at accurate on every UPDATE. A dedicated function name avoids
-- clashing with the other modules' trigger functions.
CREATE OR REPLACE FUNCTION bom_set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_boms_set_updated_at ON boms;
CREATE TRIGGER trg_boms_set_updated_at
    BEFORE UPDATE ON boms
    FOR EACH ROW EXECUTE FUNCTION bom_set_updated_at();

DROP TRIGGER IF EXISTS trg_bom_lines_set_updated_at ON bom_lines;
CREATE TRIGGER trg_bom_lines_set_updated_at
    BEFORE UPDATE ON bom_lines
    FOR EACH ROW EXECUTE FUNCTION bom_set_updated_at();

COMMIT;

-- Post-conditions (informational): both tables exist + current row counts.
SELECT 'boms' AS table_created, (SELECT COUNT(*) FROM boms) AS row_count
UNION ALL
SELECT 'bom_lines', (SELECT COUNT(*) FROM bom_lines);
