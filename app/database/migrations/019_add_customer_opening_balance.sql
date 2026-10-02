-- Migration 019 (UPGRADE): add the opening balance column to customers.
--
-- Adds one OPTIONAL numeric column to the existing ``customers`` table, using the
-- project's lowercase snake_case naming convention (same as customer_name,
-- phone_number, ...):
--   opening_balance numeric(18,2) — رصيد أول المدة (customer's opening balance)
--
-- Non-destructive: ADD COLUMN IF NOT EXISTS with a NOT NULL DEFAULT 0, so every
-- existing row is backfilled with 0 and new rows default to 0 unless a value is
-- entered. Safe to run repeatedly.
--
-- Reverse with 019_downgrade_customer_opening_balance.sql.

BEGIN;

ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS opening_balance numeric(18, 2) NOT NULL DEFAULT 0;

COMMIT;
