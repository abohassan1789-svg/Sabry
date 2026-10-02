-- Migration 023 (DOWNGRADE): drop the Supplier Payment Vouchers schema.
--
-- Reverses 023_create_supplier_payment_vouchers_schema.sql. Removes the table
-- (its indexes/constraints go with it) and the two owned sequences. Guarded with
-- IF EXISTS so it is safe to run even if the objects are already gone.
--
-- WARNING: dropping the table permanently deletes every stored supplier payment
-- voucher. Only run this to fully roll back the feature.

BEGIN;

DROP TABLE IF EXISTS supplier_payment_vouchers;
DROP SEQUENCE IF EXISTS supplier_payment_voucher_number_seq;
DROP SEQUENCE IF EXISTS supplier_payment_vouchers_id_seq;

COMMIT;
