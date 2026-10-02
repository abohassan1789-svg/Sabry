"""Read-only database access for the Production Orders Report (تقرير أوامر الإنتاج).

This repository performs **SELECTs only** — the report never writes. It reads the
existing ``production_orders`` / ``production_order_lines`` tables (built by the
Production Order module, migration 033) plus two read-only lookups the screen
needs: the item picker (``products``) and the company letterhead (``companies``).
No schema is created or modified here.

Two filter roles for the «اسم الصنف» filter, kept strictly distinct because the
finished product lives on the **header** and the raw materials on the **lines**:

* :data:`ROLE_FINISHED` — filter on ``production_orders.product_id`` (the produced
  finished product).
* :data:`ROLE_RAW` — filter on orders that USED a raw material, via
  ``production_order_lines.component_product_id`` (an ``IN`` sub-select so the
  per-order aggregates stay whole, not narrowed to that one material's lines).

Built on the shared psycopg ``Database`` helper, mirroring
``ProductionOrderRepository`` / ``SalesReportRepository``.
"""

from __future__ import annotations

from typing import Any

from app.database.db import Database

# Item-filter roles (which side of the order the «اسم الصنف» filter matches).
ROLE_FINISHED = "finished"
ROLE_RAW = "raw"

DEFAULT_PICKER_LIMIT = 500

# Columns read back for one production-order summary row (header + line aggregates).
_ORDER_SUMMARY_SELECT = (
    "po.id, po.order_number, po.order_date, po.product_id, po.product_name_snapshot, "
    "po.bom_id, po.production_quantity, "
    "COUNT(l.id) AS material_count, "
    "COALESCE(SUM(l.expected_quantity), 0) AS total_expected, "
    "COALESCE(SUM(l.actual_quantity), 0)   AS total_actual, "
    "COALESCE(SUM(l.deviation), 0)         AS total_deviation"
)

_LINE_SELECT = (
    "production_order_id, line_number, component_product_id, item_code_snapshot, "
    "item_name_snapshot, unit_snapshot, bom_quantity_per_unit, expected_quantity, "
    "actual_quantity, deviation, bom_price_snapshot"
)


class ProductionOrderReportRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    # ======================================================================
    # Company letterhead (the FIRST registered company — read-only)
    # ======================================================================
    def fetch_company_letterhead(self) -> dict[str, Any] | None:
        """Return the first registered company for the printable letterhead.

        Arabic name / English name / CR / VAT / addresses / logo bytes — exactly
        the fields the shared ``_letterhead`` renderer consumes. ``None`` if no
        company is registered yet.
        """
        return self.db.fetch_one(
            "SELECT id, name_ar, name_en, commercial_registration, vat_number, "
            "phone, address_ar, address_en, logo, logo_mime "
            "FROM companies ORDER BY id LIMIT 1"
        )

    # ======================================================================
    # Item picker (products) — covers BOTH finished products and raw materials
    # ======================================================================
    def search_products(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        """Products for the «اسم الصنف» picker (id + code + name + unit + type).

        Returns every product; the finished/raw distinction is made by the report
        role, not by hiding items here (item_type can be NULL on legacy rows).
        """
        kw = (keyword or "").strip()
        if kw == "":
            return self.db.fetch_all(
                "SELECT id, item_code, item_name, unit, item_type, price "
                "FROM products ORDER BY item_code LIMIT %s",
                [int(limit)],
            )
        like = f"%{kw}%"
        return self.db.fetch_all(
            "SELECT id, item_code, item_name, unit, item_type, price FROM products "
            "WHERE item_name ILIKE %s OR CAST(item_code AS text) LIKE %s "
            "ORDER BY item_code LIMIT %s",
            [like, f"{kw}%", int(limit)],
        )

    def get_product_name(self, product_id: int) -> str | None:
        row = self.db.fetch_one(
            "SELECT item_name FROM products WHERE id = %s", [int(product_id)]
        )
        return None if row is None else row.get("item_name")

    # ======================================================================
    # Report data (read-only aggregates)
    # ======================================================================
    def fetch_order_summaries(
        self,
        *,
        date_from: Any = None,
        date_to: Any = None,
        item_id: int | None = None,
        item_role: str = ROLE_FINISHED,
    ) -> list[dict[str, Any]]:
        """One summary row per production order matching the filters.

        Each row carries the header fields plus the line aggregates
        (material_count, total_expected, total_actual, total_deviation). The
        aggregates are always the WHOLE order's totals — the raw-material filter
        selects *which orders* appear (via an ``IN`` sub-select) without narrowing
        the sums to a single material.
        """
        conds: list[str] = []
        params: list[Any] = []
        if date_from is not None:
            conds.append("po.order_date >= %s")
            params.append(date_from)
        if date_to is not None:
            conds.append("po.order_date <= %s")
            params.append(date_to)
        if item_id is not None:
            if item_role == ROLE_RAW:
                conds.append(
                    "po.id IN (SELECT production_order_id FROM production_order_lines "
                    "WHERE component_product_id = %s)"
                )
                params.append(int(item_id))
            else:  # ROLE_FINISHED
                conds.append("po.product_id = %s")
                params.append(int(item_id))

        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        sql = (
            f"SELECT {_ORDER_SUMMARY_SELECT} "
            "FROM production_orders po "
            "LEFT JOIN production_order_lines l ON l.production_order_id = po.id"
            f"{where} "
            "GROUP BY po.id "
            "ORDER BY po.order_date DESC, po.id DESC"
        )
        return self.db.fetch_all(sql, params)

    def fetch_lines_for_orders(
        self, order_ids: list[int]
    ) -> list[dict[str, Any]]:
        """All material lines for the given order ids (for the expandable detail
        and the raw-material analytics). One round-trip via ``= ANY``."""
        if not order_ids:
            return []
        return self.db.fetch_all(
            f"SELECT {_LINE_SELECT} FROM production_order_lines "
            "WHERE production_order_id = ANY(%s) "
            "ORDER BY production_order_id, line_number",
            [[int(oid) for oid in order_ids]],
        )


__all__ = [
    "ProductionOrderReportRepository",
    "ROLE_FINISHED",
    "ROLE_RAW",
    "DEFAULT_PICKER_LIMIT",
]
