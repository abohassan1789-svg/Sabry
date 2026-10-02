"""Read-only database layer for the Finished-Goods Warehouse balance (مخزن الإنتاج التام).

This is the ONLY place SQL for this screen lives. It returns plain, read-only row
dicts; the service (``app/services/finished_goods_balance_service.py``) does all
the Arabic labels, the ``opening + produced − sold`` arithmetic, the quantity
formatting, the KPI totals and the stock-level status, and the UI never sees SQL.

The balance per finished product
--------------------------------
``رصيد أول المدة`` + ``الكميات المنتجة`` − ``المبيعات`` and each input links to a
product by its real ``products.id`` FK (unlike the raw-material warehouse, whose
purchases join by item_code):

* opening balance — the product row itself: ``products.opening_balance``.
* produced — ``production_orders`` summed by the header ``production_quantity``
  (one value per order) and joined by ``product_id = products.id``. Production
  orders have no approval lifecycle, so every order counts.
* sold — ``sales_invoice_lines`` summed by ``quantity`` and joined by
  ``product_id = products.id`` (a line's product_id is NULLABLE for free-typed
  items, which then belong to no product and are skipped). Only **approved**
  Saudi sales invoices count (``document_status = 'approved'``), matching the
  existing sales report. Cashier/POS sales are a separate channel and, per the
  user's decision (2026-08-17), are NOT deducted here.

Only rows whose ``products.item_type`` is the finished-goods type ('منتج تام')
are returned — raw materials never appear here.

Filter: a single optional case-insensitive item-name contains-search. There is no
date filter — the balance is always the full cumulative stock for every finished
product.

Read-only contract: this module only ``SELECT``s. It never inserts, updates or
deletes any product, invoice, line or order row, and never issues DDL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.db import Database
from app.models.sales_invoice import STATUS_APPROVED
from app.schemas.product_schema import ITEM_TYPE_FINISHED

# Default picker page size — newest 500, then searchable beyond.
DEFAULT_PICKER_LIMIT = 500


@dataclass(frozen=True)
class FinishedGoodsBalanceFilters:
    """Normalised query input.

    ``item_name`` is the only filter: a free-text contains-search on
    ``products.item_name`` (``None`` = all finished products). ``sale_statuses``
    defaults to approved-only but stays a parameter so the rule can change in one
    place. ``item_type`` is pinned to the finished-goods type but stays a
    parameter for the same reason.
    """

    item_name: str | None = None
    sale_statuses: tuple[str, ...] = (STATUS_APPROVED,)
    item_type: str = ITEM_TYPE_FINISHED


class FinishedGoodsBalanceRepository:
    """Read-only SQL for the per-finished-product stock-balance rows."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def fetch_balances(self, filters: FinishedGoodsBalanceFilters) -> list[dict[str, Any]]:
        """Return one row per finished-goods product with its opening balance and
        the summed (all-time) produced and sold quantities, ordered by name then
        code.

        Products with no movement still appear (LEFT JOINs + COALESCE to 0), so
        the warehouse always lists every finished product, even one only carrying
        an opening balance. The balance itself is computed by the service.
        """
        # --- sales sub-aggregate (approved invoices, by product_id) -------------
        sale_params: list[Any] = [list(filters.sale_statuses) or [STATUS_APPROVED]]

        # --- finished-goods products (the driving set) --------------------------
        prod_conditions = ["p.item_type = %s"]
        prod_params: list[Any] = [filters.item_type]
        if filters.item_name:
            prod_conditions.append("p.item_name ILIKE %s")
            prod_params.append(f"%{filters.item_name}%")
        prod_where = " AND ".join(prod_conditions)

        sql = f"""
            WITH prod AS (
                SELECT po.product_id AS product_id,
                       COALESCE(SUM(po.production_quantity), 0) AS produced
                FROM production_orders po
                GROUP BY po.product_id
            ),
            sales AS (
                SELECT l.product_id AS product_id,
                       COALESCE(SUM(l.quantity), 0) AS sold
                FROM sales_invoice_lines l
                JOIN sales_invoices si ON si.id = l.invoice_id
                WHERE si.document_status = ANY(%s)
                  AND l.product_id IS NOT NULL
                GROUP BY l.product_id
            )
            SELECT
                p.id                              AS product_id,
                p.item_code                       AS item_code,
                p.item_name                       AS item_name,
                p.unit                            AS unit,
                COALESCE(p.opening_balance, 0)    AS opening_balance,
                COALESCE(prod.produced, 0)        AS produced,
                COALESCE(sales.sold, 0)           AS sold
            FROM products p
            LEFT JOIN prod ON prod.product_id = p.id
            LEFT JOIN sales ON sales.product_id = p.id
            WHERE {prod_where}
            ORDER BY p.item_name ASC, p.item_code ASC
        """
        params = [*sale_params, *prod_params]
        return self.db.fetch_all(sql, params)

    # --- item picker (finished goods only) ----------------------------------
    def search_finished_goods(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT,
        item_type: str = ITEM_TYPE_FINISHED,
    ) -> list[dict[str, Any]]:
        """Finished-goods picker source for the item-name field. No keyword →
        newest ``limit`` finished products; with a keyword → the finished products
        filtered by name / code, then capped at ``limit``. Only finished goods are
        ever listed."""
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
    "FinishedGoodsBalanceRepository",
    "FinishedGoodsBalanceFilters",
    "DEFAULT_PICKER_LIMIT",
]
