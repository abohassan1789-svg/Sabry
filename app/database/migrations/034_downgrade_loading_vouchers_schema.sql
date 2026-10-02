-- Migration 034 (DOWNGRADE): reverse 034_create_loading_vouchers_schema.sql.
--
-- Removes ONLY the objects that migration 034 created: the loading_vouchers table
-- (and its indexes), the numbering sequence, the updated_at trigger + the
-- loading_voucher_set_updated_at function, and the loading_voucher_format_number
-- function used by the column DEFAULT. It does not touch any other table or data
-- (customers, products, app_users, receipt_vouchers, production_orders, ... are all
-- left intact).
--
-- NOTE: dropping loading_vouchers discards the rows in that table (the table itself
-- is what this migration introduced). No pre-existing / unrelated data is affected.
-- Safe to run repeatedly (every drop uses IF EXISTS). loading_voucher_number_seq is
-- OWNED BY loading_vouchers.voucher_number, so it is dropped with the table; the
-- explicit DROP SEQUENCE below is a belt-and-braces no-op.

BEGIN;

DROP TRIGGER IF EXISTS trg_loading_vouchers_set_updated_at ON loading_vouchers;

-- The table holds its own indexes, so dropping it also removes them.
DROP TABLE IF EXISTS loading_vouchers;

-- Voucher numbering sequence (belt-and-braces; already owned by the column).
DROP SEQUENCE IF EXISTS loading_voucher_number_seq;

-- Loading-Voucher-specific functions (not shared with other modules), safe to
-- drop once the table (and its trigger above) is gone: the updated_at trigger
-- setter and the voucher-number formatter used by the column DEFAULT.
DROP FUNCTION IF EXISTS loading_voucher_set_updated_at();
DROP FUNCTION IF EXISTS loading_voucher_format_number(bigint);

COMMIT;
