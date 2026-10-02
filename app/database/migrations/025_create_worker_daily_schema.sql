-- Migration 025 (UPGRADE): create the worker daily table (يومية العمال).
--
-- A daily wage-sheet line per worker. Columns:
--   id             integer       — رقم الحركة (auto, starts at 1)
--   movement_date  date          — التاريخ (NOT NULL, defaults to today)
--   worker_id      integer       — اسم العامل (NOT NULL, RESTRICT FK -> workers)
--   statement      text          — البيان
--   number_of_days numeric(18,2) — عدد الأيام (NOT NULL DEFAULT 0, entered by hand)
--   daily_wage     numeric(18,2) — أجر اليوم (NOT NULL DEFAULT 0, entered by hand)
--   daily_salary   numeric(20,4) — الراتب اليومي = عدد الأيام × أجر اليوم
--                                  (STORED generated column — never manual)
--   cash           numeric(18,2) — نقديات (NOT NULL DEFAULT 0)
--   balance        numeric(20,4) — الرصيد = الراتب اليومي − النقديات
--                                  (STORED generated column — never manual)
--
-- The two totals are database generated columns, so the stored value can never
-- drift from (days × wage) / (salary − cash) no matter how a row is written. The
-- id is assigned atomically by a PostgreSQL sequence starting at 1. Indexes on
-- worker/date support the dashboard aggregates. Everything is IF NOT EXISTS /
-- guarded, so the migration is safe to run repeatedly.
--
-- Reverse with 025_downgrade_worker_daily_schema.sql.

BEGIN;

CREATE SEQUENCE IF NOT EXISTS worker_daily_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS worker_daily (
    id             integer       NOT NULL DEFAULT nextval('worker_daily_id_seq'),
    movement_date  date          NOT NULL DEFAULT CURRENT_DATE,
    worker_id      integer       NOT NULL,
    statement      text,
    number_of_days numeric(18, 2) NOT NULL DEFAULT 0,
    daily_wage     numeric(18, 2) NOT NULL DEFAULT 0,
    daily_salary   numeric(20, 4) GENERATED ALWAYS AS (number_of_days * daily_wage) STORED,
    cash           numeric(18, 2) NOT NULL DEFAULT 0,
    balance        numeric(20, 4) GENERATED ALWAYS AS (number_of_days * daily_wage - cash) STORED,
    CONSTRAINT ck_worker_daily_days_non_negative CHECK (number_of_days >= 0),
    CONSTRAINT ck_worker_daily_wage_non_negative CHECK (daily_wage >= 0)
);

ALTER SEQUENCE worker_daily_id_seq OWNED BY worker_daily.id;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'worker_daily_pkey' AND conrelid = 'worker_daily'::regclass
    ) THEN
        ALTER TABLE ONLY worker_daily ADD CONSTRAINT worker_daily_pkey PRIMARY KEY (id);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_worker_daily_worker' AND conrelid = 'worker_daily'::regclass
    ) THEN
        ALTER TABLE ONLY worker_daily
            ADD CONSTRAINT fk_worker_daily_worker
            FOREIGN KEY (worker_id) REFERENCES workers (worker_id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_worker_daily_worker ON worker_daily (worker_id);
CREATE INDEX IF NOT EXISTS idx_worker_daily_date ON worker_daily (movement_date);

COMMIT;
