-- Migration 026 (UPGRADE): Worker Payment Vouchers schema (سندات صرف العمال).
--
-- A new standalone table for money PAID to workers/labour, modelled exactly on
-- supplier_payment_vouchers (migration 023) but keyed to the workers table.
-- Columns:
--   id             integer       — internal code (auto, hidden in the UI)
--   voucher_number varchar(40)   — رقم السند. Automatic values come from the
--                                  sequence ``worker_payment_voucher_number_seq``
--                                  rendered as ``Paid - Wrk-01``, ``Paid - Wrk-02``,
--                                  ``Paid - Wrk-03``, ... (first nextval = 1). The
--                                  DB DEFAULT assigns it atomically; never
--                                  MAX(voucher_number)+1. The UNIQUE index is the
--                                  final duplicate guard.
--   voucher_date   date          — التاريخ (NOT NULL, defaults to today)
--   worker_id      integer       — اسم العامل (NOT NULL, RESTRICT FK -> workers)
--   amount         numeric(18,2) — المبلغ (NOT NULL, CHECK > 0)
--   description    text          — البيان
--
-- Indexes on worker/date support the dashboard aggregates (total, by-worker,
-- top worker). Everything is IF NOT EXISTS / guarded, so the migration is safe
-- to run repeatedly.
--
-- Reverse with 026_downgrade_worker_payment_vouchers_schema.sql.

BEGIN;

CREATE SEQUENCE IF NOT EXISTS worker_payment_voucher_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE SEQUENCE IF NOT EXISTS worker_payment_vouchers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS worker_payment_vouchers (
    id             integer       NOT NULL DEFAULT nextval('worker_payment_vouchers_id_seq'),
    voucher_number varchar(40)   NOT NULL
                     DEFAULT ('Paid - Wrk-' ||
                              to_char(nextval('worker_payment_voucher_number_seq'), 'FM00')),
    voucher_date   date          NOT NULL DEFAULT CURRENT_DATE,
    worker_id      integer       NOT NULL,
    amount         numeric(18, 2) NOT NULL DEFAULT 0,
    description    text,
    CONSTRAINT ck_worker_payment_vouchers_amount_positive
        CHECK (amount > 0),
    CONSTRAINT ck_worker_payment_vouchers_voucher_number_not_blank
        CHECK (char_length(btrim(voucher_number)) > 0)
);

ALTER SEQUENCE worker_payment_vouchers_id_seq OWNED BY worker_payment_vouchers.id;
ALTER SEQUENCE worker_payment_voucher_number_seq
    OWNED BY worker_payment_vouchers.voucher_number;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'worker_payment_vouchers_pkey'
          AND conrelid = 'worker_payment_vouchers'::regclass
    ) THEN
        ALTER TABLE ONLY worker_payment_vouchers
            ADD CONSTRAINT worker_payment_vouchers_pkey PRIMARY KEY (id);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_worker_payment_vouchers_worker'
          AND conrelid = 'worker_payment_vouchers'::regclass
    ) THEN
        ALTER TABLE ONLY worker_payment_vouchers
            ADD CONSTRAINT fk_worker_payment_vouchers_worker
            FOREIGN KEY (worker_id) REFERENCES workers (worker_id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

-- Forward-only re-seed (idempotent). On a fresh table this is a no-op, so the
-- first nextval() stays 1 (Paid - Wrk-01). On a re-run over existing data it
-- advances the sequence past the greatest existing <n>; it never regresses.
DO $$
DECLARE
    max_existing bigint;
    seq_last     bigint;
BEGIN
    SELECT COALESCE(
             MAX(CAST(substring(voucher_number FROM '^Paid - Wrk-([0-9]+)$') AS bigint)),
             0)
      INTO max_existing
      FROM worker_payment_vouchers
     WHERE voucher_number ~ '^Paid - Wrk-[0-9]+$';

    SELECT last_value INTO seq_last FROM worker_payment_voucher_number_seq;

    IF max_existing > seq_last THEN
        PERFORM setval('worker_payment_voucher_number_seq', max_existing, true);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_worker_payment_vouchers_voucher_number
    ON worker_payment_vouchers (voucher_number);
CREATE INDEX IF NOT EXISTS idx_worker_payment_vouchers_worker
    ON worker_payment_vouchers (worker_id);
CREATE INDEX IF NOT EXISTS idx_worker_payment_vouchers_date
    ON worker_payment_vouchers (voucher_date);

COMMIT;
