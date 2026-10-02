-- Migration 025 (DOWNGRADE): drop the worker daily schema (يومية العمال).
--
-- Reverses 025_create_worker_daily_schema.sql. Removes the table (its indexes,
-- constraints, and generated columns go with it) and the owned id sequence.
-- Guarded with IF EXISTS so it is safe to run even if the objects are gone.
--
-- WARNING: dropping the table permanently deletes every stored worker daily
-- entry. Only run this to fully roll back the feature.

BEGIN;

DROP TABLE IF EXISTS worker_daily;
DROP SEQUENCE IF EXISTS worker_daily_id_seq;

COMMIT;
