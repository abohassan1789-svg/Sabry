-- Migration 024 (UPGRADE): make receipt_vouchers.company_id and payment_type
-- optional (سندات القبض — الشركة ونوع الدفع اختياريان).
--
-- The customer receipt-voucher screen was simplified to the same five-field
-- dashboard form as the supplier payment vouchers (رقم السند / التاريخ / اسم
-- العميل / المبلغ / البيان). The الشركة and نوع الدفع inputs were removed from the
-- screen, so their columns must no longer be NOT NULL — otherwise a new voucher
-- (which no longer supplies them) would fail the constraint.
--
-- The columns and all existing data are KEPT (nothing is dropped): old vouchers
-- retain their company_id / payment_type, and the print feature still reads any
-- stored value. Only the NOT NULL requirement is relaxed. The payment_type CHECK
-- (IN ('cash','bank_transfer')) is unaffected — a NULL passes a CHECK.
--
-- Idempotent: DROP NOT NULL on an already-nullable column is a no-op.
--
-- Reverse with 024_downgrade_receipt_voucher_company_payment.sql.

BEGIN;

ALTER TABLE receipt_vouchers ALTER COLUMN company_id DROP NOT NULL;
ALTER TABLE receipt_vouchers ALTER COLUMN payment_type DROP NOT NULL;

COMMIT;
