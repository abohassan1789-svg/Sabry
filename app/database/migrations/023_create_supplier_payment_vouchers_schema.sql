-- Migration 023 (UPGRADE): Supplier Payment Vouchers schema (سندات صرف الموردين).
--
-- A new standalone table for money PAID to suppliers, modelled on the same
-- lowercase snake_case convention as the rest of the project. Columns:
--   id             integer       — internal code (auto, hidden in the UI)
--   voucher_number varchar(40)   — رقم السند. Automatic values come from the
--                                  sequence ``supplier_payment_voucher_number_seq``
--                                  rendered as ``Paid - Sub-01``, ``Paid - Sub-02``,
--                                  ``Paid - Sub-03``, ... (first nextval = 1). The
--                                  DB DEFAULT assigns it atomically; never
--                                  MAX(voucher_number)+1. The UNIQUE index is the
--                                  final duplicate guard.
--   voucher_date   date          — التاريخ (NOT NULL, defaults to today)
--   supplier_id    integer       — اسم المورد (NOT NULL, RESTRICT FK -> suppliers)
--   amount         numeric(18,2) — المبلغ (NOT NULL, CHECK > 0)
--   description    text          — البيان
--
-- Indexes on supplier/date support the dashboard aggregates (total, by-supplier,
-- top supplier). Everything is IF NOT EXISTS / guarded, so the migration is safe
-- to run repeatedly.
--
-- Reverse with 023_downgrade_supplier_payment_vouchers_schema.sql.

BEGIN;

CREATE SEQUENCE IF NOT EXISTS supplier_payment_voucher_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE SEQUENCE IF NOT EXISTS supplier_payment_vouchers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS supplier_payment_vouchers (
    id             integer       NOT NULL DEFAULT nextval('supplier_payment_vouchers_id_seq'),
    voucher_number varchar(40)   NOT NULL
                     DEFAULT ('Paid - Sub-' ||
                              to_char(nextval('supplier_payment_voucher_number_seq'), 'FM00')),
    voucher_date   date          NOT NULL DEFAULT CURRENT_DATE,
    supplier_id    integer       NOT NULL,
    amount         numeric(18, 2) NOT NULL DEFAULT 0,
    description    text,
    CONSTRAINT ck_supplier_payment_vouchers_amount_positive
        CHECK (amount > 0),
    CONSTRAINT ck_supplier_payment_vouchers_voucher_number_not_blank
        CHECK (char_length(btrim(voucher_number)) > 0)
);

ALTER SEQUENCE supplier_payment_vouchers_id_seq OWNED BY supplier_payment_vouchers.id;
ALTER SEQUENCE supplier_payment_voucher_number_seq
    OWNED BY supplier_payment_vouchers.voucher_number;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'supplier_payment_vouchers_pkey'
          AND conrelid = 'supplier_payment_vouchers'::regclass
    ) THEN
        ALTER TABLE ONLY supplier_payment_vouchers
            ADD CONSTRAINT supplier_payment_vouchers_pkey PRIMARY KEY (id);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_supplier_payment_vouchers_supplier'
          AND conrelid = 'supplier_payment_vouchers'::regclass
    ) THEN
        ALTER TABLE ONLY supplier_payment_vouchers
            ADD CONSTRAINT fk_supplier_payment_vouchers_supplier
            FOREIGN KEY (supplier_id) REFERENCES suppliers (supplier_id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

-- Forward-only re-seed (idempotent). On a fresh table this is a no-op, so the
-- first nextval() stays 1 (Paid - Sub-01). On a re-run over existing data it
-- advances the sequence past the greatest existing <n>; it never regresses.
DO $$
DECLARE
    max_existing bigint;
    seq_last     bigint;
BEGIN
    SELECT COALESCE(
             MAX(CAST(substring(voucher_number FROM '^Paid - Sub-([0-9]+)$') AS bigint)),
             0)
      INTO max_existing
      FROM supplier_payment_vouchers
     WHERE voucher_number ~ '^Paid - Sub-[0-9]+$';

    SELECT last_value INTO seq_last FROM supplier_payment_voucher_number_seq;

    IF max_existing > seq_last THEN
        PERFORM setval('supplier_payment_voucher_number_seq', max_existing, true);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_payment_vouchers_voucher_number
    ON supplier_payment_vouchers (voucher_number);
CREATE INDEX IF NOT EXISTS idx_supplier_payment_vouchers_supplier
    ON supplier_payment_vouchers (supplier_id);
CREATE INDEX IF NOT EXISTS idx_supplier_payment_vouchers_date
    ON supplier_payment_vouchers (voucher_date);

COMMIT;
