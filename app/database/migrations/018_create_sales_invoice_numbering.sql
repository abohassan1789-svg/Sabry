-- Migration 018 (UPGRADE): global editable Saudi sales-invoice numbering.
--
-- Automatic numbers start at 50001 and are shared by every seller company.
-- Existing rows are never renumbered. If historical numbers are duplicated
-- across sellers, the migration aborts before changing any schema object.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM sales_invoices
        GROUP BY invoice_number
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Cannot enable global invoice numbering: duplicate invoice numbers exist';
    END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS sales_invoice_number_seq
    AS bigint
    MINVALUE 50001
    START WITH 50001;

-- Seed forward from existing numeric values. Re-running the migration never
-- moves an already-used sequence backward.
DO $$
DECLARE
    max_numeric     bigint;
    sequence_last   bigint;
    sequence_called boolean;
BEGIN
    SELECT COALESCE(
        MAX(btrim(invoice_number)::bigint)
            FILTER (WHERE btrim(invoice_number) ~ '^[0-9]+$'),
        50000
    )
    INTO max_numeric
    FROM sales_invoices;

    SELECT last_value, is_called
    INTO sequence_last, sequence_called
    FROM sales_invoice_number_seq;

    IF max_numeric >= 50001
       AND (NOT sequence_called OR max_numeric > sequence_last) THEN
        PERFORM setval('sales_invoice_number_seq', max_numeric, true);
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = to_regclass(
                  format('%I.sales_invoices', current_schema())
              )
          AND conname = 'uq_sales_invoices_company_number'
    ) THEN
        EXECUTE format(
            'ALTER TABLE %I.sales_invoices '
            'DROP CONSTRAINT uq_sales_invoices_company_number',
            current_schema()
        );
    ELSE
        EXECUTE format(
            'DROP INDEX IF EXISTS %I.uq_sales_invoices_company_number',
            current_schema()
        );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_invoices_invoice_number
    ON sales_invoices (invoice_number);

COMMIT;
