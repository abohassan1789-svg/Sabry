-- Migration 022 (DOWNGRADE): drop the expenses table and its sequence.
--
-- Reverses 022_create_expenses_schema.sql. Idempotent (IF EXISTS). This discards
-- all expense rows.

BEGIN;

DROP TABLE IF EXISTS expenses;
DROP SEQUENCE IF EXISTS expenses_id_seq;

COMMIT;
