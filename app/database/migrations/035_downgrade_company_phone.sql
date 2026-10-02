-- 035_downgrade_company_phone.sql
-- Reverses 035_add_company_phone.sql: drops the phone column and restores the
-- companies_normalize() trigger function to its pre-035 body (no phone line).

CREATE OR REPLACE FUNCTION companies_normalize() RETURNS trigger AS $$
BEGIN
    NEW.name_ar := btrim(NEW.name_ar);
    NEW.commercial_registration := btrim(NEW.commercial_registration);
    NEW.vat_number := btrim(NEW.vat_number);
    NEW.name_en := NULLIF(btrim(NEW.name_en), '');
    NEW.address_ar := NULLIF(btrim(NEW.address_ar), '');
    NEW.address_en := NULLIF(btrim(NEW.address_en), '');
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

ALTER TABLE companies
    DROP COLUMN IF EXISTS phone;
