-- Migration 021 (DOWNGRADE): drop the workers table and its sequence.
--
-- Reverses 021_create_workers_schema.sql. Idempotent (IF EXISTS). This discards
-- all worker rows.

BEGIN;

DROP TABLE IF EXISTS workers;
DROP SEQUENCE IF EXISTS workers_worker_id_seq;

COMMIT;
