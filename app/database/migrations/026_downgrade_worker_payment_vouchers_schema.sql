-- Migration 026 (DOWNGRADE): drop the Worker Payment Vouchers schema.
--
-- Reverses 026_create_worker_payment_vouchers_schema.sql. Removes the table
-- (its indexes/constraints go with it) and the two owned sequences. Guarded with
-- IF EXISTS so it is safe to run even if the objects are already gone.
--
-- WARNING: dropping the table permanently deletes every stored worker payment
-- voucher. Only run this to fully roll back the feature.

BEGIN;

DROP TABLE IF EXISTS worker_payment_vouchers;
DROP SEQUENCE IF EXISTS worker_payment_voucher_number_seq;
DROP SEQUENCE IF EXISTS worker_payment_vouchers_id_seq;

COMMIT;
