-- Migration 031 (DOWNGRADE): remove رصيد أول المدة (opening balance) from products.
--
-- Reverses 031_add_product_opening_balance.sql. Dropping the column discards any
-- opening-balance data stored in it. Safe to run repeatedly (IF EXISTS).

BEGIN;

ALTER TABLE products
    DROP COLUMN IF EXISTS opening_balance;

COMMIT;
