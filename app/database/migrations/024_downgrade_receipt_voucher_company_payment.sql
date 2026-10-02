-- Migration 024 (DOWNGRADE): restore NOT NULL on receipt_vouchers.company_id
-- and payment_type.
--
-- Reverses 024_relax_receipt_voucher_company_payment.sql. This will FAIL if any
-- voucher created after the upgrade has a NULL company_id or payment_type (that
-- is expected — those rows must be backfilled before the columns can be made
-- mandatory again). Run only to fully roll the feature back.

BEGIN;

ALTER TABLE receipt_vouchers ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE receipt_vouchers ALTER COLUMN payment_type SET NOT NULL;

COMMIT;
