-- 017_downgrade_company_stamp.sql
-- Reverses 017_add_company_stamp.sql by dropping the embedded stamp columns.

ALTER TABLE companies
    DROP COLUMN IF EXISTS stamp,
    DROP COLUMN IF EXISTS stamp_mime;
