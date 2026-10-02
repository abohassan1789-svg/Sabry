-- Migration 027 (DOWNGRADE): drop the Treasury Deposits schema.
--
-- Reverses 027_create_treasury_deposits_schema.sql. Removes the table (its
-- indexes/constraints go with it) and the owned sequence. Guarded with IF EXISTS
-- so it is safe to run even if the objects are already gone.
--
-- WARNING: dropping the table permanently deletes every stored treasury deposit
-- movement. Only run this to fully roll back the feature.

BEGIN;

DROP TABLE IF EXISTS treasury_deposits;
DROP SEQUENCE IF EXISTS treasury_deposits_id_seq;

COMMIT;
