-- Migration 030 (DOWNGRADE): remove نوع الصنف (item type) from products.
--
-- Reverses 030_add_product_item_type.sql. Dropping the column discards any
-- item-type data stored in it. Safe to run repeatedly (IF EXISTS).

BEGIN;

ALTER TABLE products
    DROP COLUMN IF EXISTS item_type;

COMMIT;
