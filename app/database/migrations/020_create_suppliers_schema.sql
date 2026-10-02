-- Migration 020 (UPGRADE): create the suppliers table (الموردين).
--
-- A brand-new master table for suppliers, mirroring the project's lowercase
-- snake_case convention. Four columns only:
--   supplier_id     integer       — كود المورد (auto, starts at 1001)
--   supplier_name   varchar(150)  — اسم المورد
--   mobile          varchar(40)   — الموبايل
--   opening_balance numeric(18,2) — رصيد أول المدة (NOT NULL DEFAULT 0)
--
-- The code is assigned atomically by a PostgreSQL sequence starting at 1001, so
-- the first supplier is 1001, then 1002, 1003, ... — never MAX(id)+1 (that path
-- is not concurrency-safe). Everything is IF NOT EXISTS / guarded, so the
-- migration is safe to run repeatedly.
--
-- Reverse with 020_downgrade_suppliers_schema.sql.

BEGIN;

CREATE SEQUENCE IF NOT EXISTS suppliers_supplier_id_seq
    START WITH 1001
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id     integer       NOT NULL DEFAULT nextval('suppliers_supplier_id_seq'),
    supplier_name   varchar(150),
    mobile          varchar(40),
    opening_balance numeric(18, 2) NOT NULL DEFAULT 0
);

ALTER SEQUENCE suppliers_supplier_id_seq OWNED BY suppliers.supplier_id;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'suppliers_pkey' AND conrelid = 'suppliers'::regclass
    ) THEN
        ALTER TABLE ONLY suppliers ADD CONSTRAINT suppliers_pkey PRIMARY KEY (supplier_id);
    END IF;
END $$;

COMMIT;
