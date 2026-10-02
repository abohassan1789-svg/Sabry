-- 017_add_company_stamp.sql
-- Adds an embedded company stamp (ختم الشركة) to the companies master.
--
-- Like the logo (migration 014), the stamp is stored *inside the database* as
-- raw image bytes (BYTEA) — never a filesystem path — so each company carries
-- its own official seal. ``stamp_mime`` records the image type (e.g.
-- ``image/png``) so the print layer can build a correct ``data:`` URI.
--
-- Unlike the logo — which is part of every printed document's measured header —
-- the stamp is OPTIONAL per printout: the sales-invoice screen has an «إظهار
-- الختم» checkbox that decides whether it is drawn in the invoice footer.
--
-- Both columns are nullable: a company without a stamp simply prints without one.

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS stamp      bytea,
    ADD COLUMN IF NOT EXISTS stamp_mime varchar(64);
