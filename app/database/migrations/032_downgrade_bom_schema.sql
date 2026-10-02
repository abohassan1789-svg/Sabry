-- Migration 032 (DOWNGRADE): reverse 032_create_bom_schema.sql.
--
-- Removes ONLY the objects that migration 032 created: the bom_lines and boms
-- tables, their indexes, the numbering sequence, and the updated_at triggers +
-- the bom_set_updated_at function. It does not touch any other table or data
-- (products, app_users, customers, invoices, ... are all left intact).
--
-- NOTE: dropping bom_lines / boms discards the rows in those tables (the tables
-- themselves are what this migration introduced). No pre-existing / unrelated
-- data is affected. Ordering removes the child table first, then the parent, so
-- the CASCADE FK never blocks. Safe to run repeatedly (every drop uses IF EXISTS).

BEGIN;

DROP TRIGGER IF EXISTS trg_bom_lines_set_updated_at ON bom_lines;
DROP TRIGGER IF EXISTS trg_boms_set_updated_at ON boms;

-- 1) BOM lines (child), 2) BOM header (parent). Each table holds its own indexes,
-- so dropping the tables also removes them. bom_number_seq is OWNED BY
-- boms.bom_number, so it is dropped with the table; the explicit DROP SEQUENCE
-- below is a belt-and-braces no-op.
DROP TABLE IF EXISTS bom_lines;
DROP TABLE IF EXISTS boms;

-- 3) BOM numbering sequence.
DROP SEQUENCE IF EXISTS bom_number_seq;

-- 4) The trigger function is BOM-specific (not shared with other modules), so it
-- is safe to drop once both triggers above are gone.
DROP FUNCTION IF EXISTS bom_set_updated_at();

COMMIT;
