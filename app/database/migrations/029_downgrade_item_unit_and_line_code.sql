-- Migration 029 (DOWNGRADE): remove الوحدة from products and كود الصنف/الوحدة
-- from purchase-invoice lines.
--
-- Reverses 029_add_item_unit_and_line_code.sql. Dropping the columns discards any
-- unit / line-code data stored in them. Safe to run repeatedly (IF EXISTS).

BEGIN;

ALTER TABLE purchase_invoice_lines
    DROP COLUMN IF EXISTS unit_snapshot;

ALTER TABLE purchase_invoice_lines
    DROP COLUMN IF EXISTS item_code_snapshot;

ALTER TABLE products
    DROP COLUMN IF EXISTS unit;

COMMIT;
