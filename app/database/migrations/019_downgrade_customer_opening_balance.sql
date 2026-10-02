-- Migration 019 (DOWNGRADE): remove the opening balance column from customers.
--
-- Reverses 019_add_customer_opening_balance.sql. DROP COLUMN IF EXISTS so the
-- rollback is idempotent. This discards any stored opening-balance values.

BEGIN;

ALTER TABLE customers DROP COLUMN IF EXISTS opening_balance;

COMMIT;
