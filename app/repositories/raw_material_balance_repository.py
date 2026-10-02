"""Read-only database layer for the Raw-Material Warehouse balance (مخزن مواد الخام).

This is the ONLY place SQL for this screen lives. It returns plain, read-only row
dicts; the service (``app/services/raw_material_balance_service.py``) does all the
Arabic labels, the ``opening + purchases − issued`` arithmetic, the quantity
formatting, the KPI totals and the stock-level status, and the UI never sees SQL.

The balance per raw material
----------------------------
``رصيد أول المدة`` + ``المشتريات`` − ``صرف المواد الخام (الكمية الفعلية)`` and the
three inputs each link to a product a DIFFERENT way, so the query reconciles them:

* opening balance — the product row itself: ``products.opening_balance``.
* purchases — ``purchase_invoice_lines`` summed by ``item_count`` and joined to the
  product by ``item_code_snapshot = products.item_code`` (purchase lines have NO
  foreign key to products and are free text; a NULL snapshot belongs to no
  product and is skipped). Only **approved** invoices count, matching the
  purchase report (drafts are not real stock yet).
* issued — ``production_order_lines`` summed by ``actual_quantity`` (the real
  quantity issued, not the expected) and joined by the real FK
  ``component_product_id = products.id``.

Only rows whose ``products.item_type`` is the raw-material type ('مادة خام') are
returned — finished products never appear here.

Filter: a single optional case-insensitive item-name contains-search. There is no
date filter — the balance is always the full cumulative stock (opening balance +
all approved purchases − all actual issues) for every raw material.

Read-only contract: this module only ``SELECT``s. It never inserts, updates or
deletes any product, invoice, line or order row, and never issues DDL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.db import Database
from app.models.purchase_invoice import STATUS_APPROVED
from app.schemas.product_schema import ITEM_TYPE_RAW

# Default picker page size — newest 500, then searchable beyond.
DEFAULT_PICKER_LIMIT = 500


@dataclass(frozen=True)
class RawMaterialBalanceFilters:
    """Normalised query input.

    ``item_name`` is the only filter: a free-text contains-search on
    ``products.item_name`` (``None`` = all raw materials). ``purchase_statuses``
    defaults to approved-only but stays a parameter so the rule can change in one
    place. ``item_type`` is pinned to the raw-material type but stays a parameter
    for the same reason.
    """

    item_name: str | None = None
    purchase_statuses: tuple[str, ...] = (STATUS_APPROVED,)
    item_type: str = ITEM_TYPE_RAW


class RawMaterialBalanceRepository:
    """Read-only SQL for the per-raw-material stock-balance rows."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def fetch_balances(self, filters: RawMaterialBalanceFilters) -> list[dict[str, Any]]:
        """Return one row per raw-material product with its opening balance and the
        summed (all-time) purchases and issued quantities, ordered by name then code.

        Materials with no movement still appear (LEFT JOINs + COALESCE to 0), so
        the warehouse always lists every raw material, even one only carrying an
        opening balance. The balance itself is computed by the service.
        """
        # --- purchases sub-aggregate (approved invoices, by item_code) ----------
        pur_params: list[Any] = [list(filters.purchase_statuses) or [STATUS_APPROVED]]

        # --- raw-material products (the driving set) ----------------------------
        prod_conditions = ["p.item_type = %s"]
        prod_params: list[Any] = [filters.item_type]
        if filters.item_name:
            prod_conditions.append("p.item_name ILIKE %s")
            prod_params.append(f"%{filters.item_name}%")
        prod_where = " AND ".join(prod_conditions)

        sql = f"""
            WITH pur AS (
                SELECT l.item_code_snapshot AS item_code,
                       COALESCE(SUM(l.item_count), 0) AS purchased
                FROM purchase_invoice_lines l
                JOIN purchase_invoices pi ON pi.id = l.invoice_id
                WHERE pi.document_status = ANY(%s)
                  AND l.item_code_snapshot IS NOT NULL
                GROUP BY l.item_code_snapshot
            ),
            iss AS (
                SELECT ol.component_product_id AS product_id,
                       COALESCE(SUM(ol.actual_quantity), 0) AS issued
                FROM production_order_lines ol
                GROUP BY ol.component_product_id
            )
            SELECT
                p.id                              AS product_id,
                p.item_code                       AS item_code,
                p.item_name                       AS item_name,
                p.unit                            AS unit,
                COALESCE(p.opening_balance, 0)    AS opening_balance,
                COALESCE(pur.purchased, 0)        AS purchased,
                COALESCE(iss.issued, 0)           AS issued
            FROM products p
            LEFT JOIN pur ON pur.item_code = p.item_code
            LEFT JOIN iss ON iss.product_id = p.id
            WHERE {prod_where}
            ORDER BY p.item_name ASC, p.item_code ASC
        """
        params = [*pur_params, *prod_params]
        return self.db.fetch_all(sql, params)

    # --- item picker (raw materials only) -----------------------------------
    def search_raw_materials(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT,
        item_type: str = ITEM_TYPE_RAW,
    ) -> list[dict[str, Any]]:
        """Raw-material picker source for the item-name field. No keyword → newest
        ``limit`` raw materials; with a keyword → the raw materials filtered by
        name / code, then capped at ``limit``. Only raw materials are ever listed."""
        kw = (keyword or "").strip()
        conditions = ["item_type = %s"]
        params: list[Any] = [item_type]
        if kw != "":
            conditions.append("(item_name ILIKE %s OR CAST(item_code AS text) LIKE %s)")
            params.append(f"%{kw}%")
            params.append(f"{kw}%")
        where = " AND ".join(conditions)
        params.append(int(limit))
        return self.db.fetch_all(
            "SELECT item_code, item_name, unit "
            "FROM products "
            f"WHERE {where} "
            "ORDER BY item_name ASC, item_code ASC LIMIT %s",
            params,
        )


__all__ = [
    "RawMaterialBalanceRepository",
    "RawMaterialBalanceFilters",
    "DEFAULT_PICKER_LIMIT",
]
