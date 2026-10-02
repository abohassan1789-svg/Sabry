-- Migration 033 (DOWNGRADE): reverse 033_create_production_order_schema.sql.
--
-- Removes ONLY the objects that migration 033 created: the production_order_lines
-- and production_orders tables, their indexes, the numbering sequence, and the
-- updated_at triggers + the production_order_set_updated_at function. It does not
-- touch any other table or data (products, boms, bom_lines, app_users, ... are all
-- left intact). In particular NO BOM data is modified or removed.
--
-- NOTE: dropping production_order_lines / production_orders discards the rows in
-- those tables (the tables themselves are what this migration introduced). No
-- pre-existing / unrelated data is affected. Ordering removes the child table
-- first, then the parent, so the CASCADE FK never blocks. Safe to run repeatedly
-- (every drop uses IF EXISTS). The bom_set_updated_at() function is intentionally
-- NOT dropped here — it belongs to the BOM module (migration 032), not this one.

BEGIN;

DROP TRIGGER IF EXISTS trg_po_lines_set_updated_at ON production_order_lines;
DROP TRIGGER IF EXISTS trg_production_orders_set_updated_at ON production_orders;

-- 1) Order lines (child), 2) Order header (parent). Each table holds its own
-- indexes, so dropping the tables also removes them. production_order_number_seq
-- is OWNED BY production_orders.order_number, so it is dropped with the table; the
-- explicit DROP SEQUENCE below is a belt-and-braces no-op.
DROP TABLE IF EXISTS production_order_lines;
DROP TABLE IF EXISTS production_orders;

-- 3) Order numbering sequence.
DROP SEQUENCE IF EXISTS production_order_number_seq;

-- 4) Production-Order-specific functions (not shared with other modules), safe to
-- drop once the tables (and both triggers above) are gone: the updated_at trigger
-- setter and the order-number formatter used by the column DEFAULT.
DROP FUNCTION IF EXISTS production_order_set_updated_at();
DROP FUNCTION IF EXISTS production_order_format_number(bigint);

COMMIT;
