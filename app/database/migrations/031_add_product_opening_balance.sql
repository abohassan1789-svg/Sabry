-- Migration 031 (UPGRADE): add رصيد أول المدة (opening balance) to products.
--
-- One money column, mirroring customers / suppliers / workers:
--   products.opening_balance numeric(18,2) — رصيد أول المدة.
--
-- Non-destructive: ADD COLUMN IF NOT EXISTS with DEFAULT 0 NOT NULL, so existing
-- rows get 0 and the column never holds NULL. Safe to run repeatedly.
--
-- Reverse with 031_downgrade_product_opening_balance.sql.

BEGIN;

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS opening_balance numeric(18,2) DEFAULT 0 NOT NULL;

COMMIT;
