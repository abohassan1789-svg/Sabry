-- Migration 030 (UPGRADE): add نوع الصنف (item type) to products.
--
-- One OPTIONAL text column, lowercase snake_case like the rest of the table:
--   products.item_type varchar(20) — نوع الصنف: a fixed choice of
--   'مادة خام' (raw material) or 'منتج تام' (finished product).
--
-- Non-destructive: ADD COLUMN IF NOT EXISTS with no default, so existing rows
-- keep NULL (unset) and new rows carry whatever the أصناف screen stores. The
-- مادة خام / منتج تام constraint is enforced by the UI dropdown, not the database,
-- so a future third value never needs a schema change. Safe to run repeatedly.
--
-- Reverse with 030_downgrade_product_item_type.sql.

BEGIN;

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS item_type varchar(20);

COMMIT;
