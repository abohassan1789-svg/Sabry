-- Migration 021 (UPGRADE): create the workers table (العمال).
--
-- A brand-new master table for workers/labour, mirroring the project's lowercase
-- snake_case convention. Four columns only:
--   worker_id       integer       — كود العامل (auto, starts at 1, shown 0001..)
--   worker_name     varchar(150)  — اسم العامل
--   mobile          varchar(40)   — الموبايل
--   opening_balance numeric(18,2) — رصيد أول المدة (NOT NULL DEFAULT 0)
--
-- The code is assigned atomically by a PostgreSQL sequence starting at 1, so the
-- first worker is 1, then 2, 3, ... The UI shows it zero-padded to four digits
-- (0001, 0002, 0003 ...). Allocation is never MAX(id)+1 (not concurrency-safe).
-- Everything is IF NOT EXISTS / guarded, so the migration is safe to re-run.
--
-- Reverse with 021_downgrade_workers_schema.sql.

BEGIN;

CREATE SEQUENCE IF NOT EXISTS workers_worker_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS workers (
    worker_id       integer       NOT NULL DEFAULT nextval('workers_worker_id_seq'),
    worker_name     varchar(150),
    mobile          varchar(40),
    opening_balance numeric(18, 2) NOT NULL DEFAULT 0
);

ALTER SEQUENCE workers_worker_id_seq OWNED BY workers.worker_id;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workers_pkey' AND conrelid = 'workers'::regclass
    ) THEN
        ALTER TABLE ONLY workers ADD CONSTRAINT workers_pkey PRIMARY KEY (worker_id);
    END IF;
END $$;

COMMIT;
