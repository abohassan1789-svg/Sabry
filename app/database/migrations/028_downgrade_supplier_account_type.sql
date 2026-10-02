-- Migration 028 (DOWNGRADE): drop the account-type column from suppliers.
--
-- Reverses 028_add_supplier_account_type.sql. DROP COLUMN IF EXISTS so it is a
-- safe no-op if the column was never added. Destructive: any stored نوع الحساب
-- values are lost.

BEGIN;

ALTER TABLE suppliers
    DROP COLUMN IF EXISTS account_type;

COMMIT;
