-- 035_add_company_phone.sql
-- Adds a phone / mobile number to the companies master.
--
-- The printed loading voucher (سند تحميل) — and any future document — shows a
-- letterhead built from the first company record: Arabic name + phone + address
-- on the right, English name on the left, logo in the middle. The companies
-- table had no phone column, so this adds one.
--
-- The column is nullable free text (a company may carry more than one number,
-- e.g. "٠٥٣٦٩٦٠٨٥٠ - ٠٥٥٧٦٨٦٨٥٠"), and the companies_normalize() trigger trims it
-- and collapses a blank value to NULL like the other optional text fields.

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS phone varchar(50);

-- Extend the normalize trigger so a blank phone is stored as NULL (trimmed),
-- matching name_en / address_ar / address_en.
CREATE OR REPLACE FUNCTION companies_normalize() RETURNS trigger AS $$
BEGIN
    NEW.name_ar := btrim(NEW.name_ar);
    NEW.commercial_registration := btrim(NEW.commercial_registration);
    NEW.vat_number := btrim(NEW.vat_number);
    NEW.name_en := NULLIF(btrim(NEW.name_en), '');
    NEW.address_ar := NULLIF(btrim(NEW.address_ar), '');
    NEW.address_en := NULLIF(btrim(NEW.address_en), '');
    NEW.phone := NULLIF(btrim(NEW.phone), '');
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
