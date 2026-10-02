-- Migration 018 (DOWNGRADE): restore seller-scoped invoice-number uniqueness.
--
-- Stored invoices and their numbers are left unchanged.

BEGIN;

DO $$
BEGIN
    EXECUTE format(
        'DROP INDEX IF EXISTS %I.uq_sales_invoices_invoice_number',
        current_schema()
    );
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = to_regclass(
                  format('%I.sales_invoices', current_schema())
              )
          AND conname = 'uq_sales_invoices_company_number'
    ) THEN
        EXECUTE format(
            'DROP INDEX IF EXISTS %I.uq_sales_invoices_company_number',
            current_schema()
        );
        EXECUTE format(
            'ALTER TABLE %I.sales_invoices '
            'ADD CONSTRAINT uq_sales_invoices_company_number '
            'UNIQUE (seller_company_id, invoice_number)',
            current_schema()
        );
    END IF;
END $$;

DROP SEQUENCE IF EXISTS sales_invoice_number_seq;

COMMIT;
