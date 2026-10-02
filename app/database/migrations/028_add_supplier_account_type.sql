-- Migration 028 (UPGRADE): add the account-type column to suppliers (نوع الحساب).
--
-- Adds one OPTIONAL text column to the existing ``suppliers`` table, using the
-- project's lowercase snake_case naming convention (same as supplier_name,
-- mobile, opening_balance):
--   account_type varchar(10) — نوع الحساب: a fixed choice of 'عدد' or 'وزن'.
--
-- Non-destructive: ADD COLUMN IF NOT EXISTS with no default, so existing rows
-- keep NULL (unset) and new rows carry whatever the supplier screen stores.
-- The عدد/وزن constraint is enforced by the UI dropdown, not the database, so a
-- future third value never needs a schema change. Safe to run repeatedly.
--
-- Reverse with 028_downgrade_supplier_account_type.sql.

BEGIN;

ALTER TABLE suppliers
    ADD COLUMN IF NOT EXISTS account_type varchar(10);

COMMIT;
