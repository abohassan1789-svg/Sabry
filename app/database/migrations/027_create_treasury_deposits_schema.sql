-- Migration 027 (UPGRADE): create the treasury deposits table (إضافة أموال للخزينة).
--
-- Money added INTO the treasury/cashbox. Mirrors the expenses table (migration
-- 022) shape, but the id doubles as the user-facing رقم الحركة and its sequence
-- starts at 3001 (so the first movement is 3001, then 3002, 3003, ...). Columns:
--   id            integer       — رقم الحركة (auto, sequence from 3001, shown read-only)
--   movement_date date          — التاريخ (NOT NULL, defaults to today)
--   amount        numeric(18,2) — المبلغ (NOT NULL, CHECK > 0)
--   statement     text          — البيان
--
-- The id is assigned atomically by a PostgreSQL sequence (never MAX(id)+1).
-- An index on date supports the dashboard aggregates (total, top date, by-month).
-- Everything is IF NOT EXISTS / guarded, so the migration is safe to re-run.
--
-- Reverse with 027_downgrade_treasury_deposits_schema.sql.

BEGIN;

CREATE SEQUENCE IF NOT EXISTS treasury_deposits_id_seq
    START WITH 3001
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS treasury_deposits (
    id            integer       NOT NULL DEFAULT nextval('treasury_deposits_id_seq'),
    movement_date date          NOT NULL DEFAULT CURRENT_DATE,
    amount        numeric(18, 2) NOT NULL DEFAULT 0,
    statement     text,
    CONSTRAINT ck_treasury_deposits_amount_positive CHECK (amount > 0)
);

ALTER SEQUENCE treasury_deposits_id_seq OWNED BY treasury_deposits.id;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'treasury_deposits_pkey' AND conrelid = 'treasury_deposits'::regclass
    ) THEN
        ALTER TABLE ONLY treasury_deposits ADD CONSTRAINT treasury_deposits_pkey PRIMARY KEY (id);
    END IF;
END $$;

-- Forward-only re-seed (idempotent). On a fresh table this keeps the first
-- nextval at 3001; on a re-run over existing data it advances the sequence past
-- the greatest existing id so a new row never collides. It never regresses.
DO $$
DECLARE
    max_existing bigint;
    seq_last     bigint;
BEGIN
    SELECT COALESCE(MAX(id), 0) INTO max_existing FROM treasury_deposits;
    SELECT last_value INTO seq_last FROM treasury_deposits_id_seq;
    IF max_existing > seq_last THEN
        PERFORM setval('treasury_deposits_id_seq', max_existing, true);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_treasury_deposits_date ON treasury_deposits (movement_date);

COMMIT;
