-- Migration 020 (DOWNGRADE): drop the suppliers table and its sequence.
--
-- Reverses 020_create_suppliers_schema.sql. Idempotent (IF EXISTS). This
-- discards all supplier rows.

BEGIN;

DROP TABLE IF EXISTS suppliers;
DROP SEQUENCE IF EXISTS suppliers_supplier_id_seq;

COMMIT;
