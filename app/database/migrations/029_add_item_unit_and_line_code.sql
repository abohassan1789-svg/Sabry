-- Migration 029 (UPGRADE): add الوحدة to products and كود الصنف/الوحدة to
-- purchase-invoice lines.
--
-- Three OPTIONAL columns, all using the project's lowercase snake_case naming:
--   products.unit                         varchar(50)  — الوحدة (unit of measure)
--   purchase_invoice_lines.item_code_snapshot integer  — كود الصنف (snapshot)
--   purchase_invoice_lines.unit_snapshot  varchar(50)  — الوحدة (snapshot)
--
-- Non-destructive: ADD COLUMN IF NOT EXISTS. The text columns default to '' so
-- existing rows stay valid under NOT NULL; item_code_snapshot is nullable because
-- a free-typed purchase line need not carry a product code. Safe to run repeatedly.
--
-- Reverse with 029_downgrade_item_unit_and_line_code.sql.

BEGIN;

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS unit varchar(50) DEFAULT '' NOT NULL;

ALTER TABLE purchase_invoice_lines
    ADD COLUMN IF NOT EXISTS item_code_snapshot integer;

ALTER TABLE purchase_invoice_lines
    ADD COLUMN IF NOT EXISTS unit_snapshot varchar(50) DEFAULT '' NOT NULL;

COMMIT;
