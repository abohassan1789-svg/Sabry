-- Migration 022 (UPGRADE): create the expenses table (المصروفات).
--
-- A new table for expenses, mirroring the project's lowercase snake_case
-- convention. Columns:
--   id           integer       — internal code (auto)
--   expense_date date          — التاريخ (NOT NULL, defaults to today)
--   amount       numeric(18,2) — المبلغ (NOT NULL DEFAULT 0)
--   expense_type varchar(150)  — نوع المصروف (free text; the UI dropdown is
--                                built from the DISTINCT values already stored,
--                                so a newly typed type appears next time)
--   statement    text          — البيان
--
-- The id is assigned atomically by a PostgreSQL sequence. Indexes on type/date
-- support the dashboard aggregates (total, by-type, top type). Everything is
-- IF NOT EXISTS / guarded, so the migration is safe to run repeatedly.
--
-- Reverse with 022_downgrade_expenses_schema.sql.

BEGIN;

CREATE SEQUENCE IF NOT EXISTS expenses_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS expenses (
    id           integer       NOT NULL DEFAULT nextval('expenses_id_seq'),
    expense_date date          NOT NULL DEFAULT CURRENT_DATE,
    amount       numeric(18, 2) NOT NULL DEFAULT 0,
    expense_type varchar(150),
    statement    text
);

ALTER SEQUENCE expenses_id_seq OWNED BY expenses.id;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'expenses_pkey' AND conrelid = 'expenses'::regclass
    ) THEN
        ALTER TABLE ONLY expenses ADD CONSTRAINT expenses_pkey PRIMARY KEY (id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_expenses_type ON expenses (expense_type);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (expense_date);

COMMIT;
