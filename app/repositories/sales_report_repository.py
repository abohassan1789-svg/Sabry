"""Read-only database layer for the Sales report (تقرير المبيعات).

This is the ONLY place SQL for this report lives. It returns plain, read-only row
dicts; the service (``app/services/sales_report_service.py``) does all Arabic
labels, money/quantity formatting, totals and the dashboard KPIs, and the UI
never sees SQL.

Data source
-----------
One report row per **invoice line**: ``sales_invoices`` (header) JOINed to
``sales_invoice_lines`` (detail). By the user's decision (2026-08-15) only
**approved** invoices are counted — a sales report should reflect real, finalised
sales, so drafts are excluded (``document_status = 'approved'``).

Selectors (customer + item) follow the same "last 500, but searchable beyond it"
rule the invoice pickers use: with no keyword the picker shows the **newest 500**
rows (ORDER BY id DESC LIMIT 500); once the user types, the WHOLE table is
filtered with an indexed ``ILIKE`` / prefix match and only then capped at the
limit, so a match on record #900 is still found even though only 500 are
pre-loaded.

Read-only contract: this module only ``SELECT``s. It never inserts, updates or
deletes any invoice, line, customer or product row, and never issues DDL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.db import Database
from app.models.sales_invoice import STATUS_APPROVED

# Default selector page size — "آخر 500" per the report spec.
DEFAULT_PICKER_LIMIT = 500


@dataclass(frozen=True)
class SalesReportFilters:
    """Normalised query input. Every field is optional (``None`` = no restriction
    on that dimension); dates are ``YYYY-MM-DD`` strings or ``None`` (open-ended).

    ``statuses`` is the set of ``document_status`` values to include; it defaults
    to approved-only, but stays a parameter so the rule can change in one place.
    """

    customer_id: int | None = None
    product_id: int | None = None
    date_from: str | None = None
    date_to: str | None = None
    statuses: tuple[str, ...] = (STATUS_APPROVED,)


class SalesReportRepository:
    """Read-only SQL for the sales-report detail rows and its two selectors."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    # --- detail rows --------------------------------------------------------
    def fetch_company_letterhead(self) -> dict[str, Any] | None:
        """Return the first registered company for the printable letterhead.

        Print/PDF only; the on-screen report never renders it. ``None`` if no
        company is registered yet.
        """
        return self.db.fetch_one(
            "SELECT id, name_ar, name_en, commercial_registration, vat_number, "
            "phone, address_ar, address_en, logo, logo_mime "
            "FROM companies ORDER BY id LIMIT 1"
        )

    def fetch_lines(self, filters: SalesReportFilters) -> list[dict[str, Any]]:
        """Return every invoice line matching the filters, oldest first.

        Ordered deterministically on the real ``issue_datetime`` then invoice id
        then line number, so the on-screen order matches any later export/print.
        The customer name prefers the invoice's stored snapshot and falls back to
        the live ``customers`` row.
        """
        conditions: list[str] = []
        params: list[Any] = []

        statuses = tuple(filters.statuses) or (STATUS_APPROVED,)
        conditions.append("si.document_status = ANY(%s)")
        params.append(list(statuses))

        if filters.customer_id is not None:
            conditions.append("si.customer_id = %s")
            params.append(int(filters.customer_id))
        if filters.product_id is not None:
            conditions.append("l.product_id = %s")
            params.append(int(filters.product_id))
        if filters.date_from:
            conditions.append("si.issue_datetime::date >= %s::date")
            params.append(filters.date_from)
        if filters.date_to:
            conditions.append("si.issue_datetime::date <= %s::date")
            params.append(filters.date_to)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT
                si.issue_datetime::date                                       AS issue_date,
                si.customer_id                                                AS customer_id,
                COALESCE(NULLIF(TRIM(si.customer_name_snapshot), ''),
                         c.customer_name, '')                                 AS customer_name,
                si.invoice_number                                             AS invoice_number,
                l.product_id                                                  AS product_id,
                l.product_name_snapshot                                       AS product_name,
                l.unit_code                                                   AS unit_code,
                l.quantity                                                    AS quantity,
                l.unit_price                                                  AS unit_price,
                l.line_amount_before_vat                                      AS line_total,
                l.vat_amount                                                  AS vat_amount,
                l.line_total_including_vat                                    AS line_total_including_vat
            FROM sales_invoices si
            JOIN sales_invoice_lines l ON l.invoice_id = si.id
            LEFT JOIN customers c ON c.customer_id = si.customer_id
            WHERE {where}
            ORDER BY si.issue_datetime ASC, si.id ASC, l.line_number ASC
        """
        return self.db.fetch_all(sql, params)

    # --- selectors (read-only, "last 500 but searchable beyond") ------------
    def search_customers(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        """Customer picker source. No keyword → newest ``limit`` customers; with a
        keyword → the whole table filtered, then capped at ``limit``."""
        kw = (keyword or "").strip()
        if kw == "":
            return self.db.fetch_all(
                "SELECT customer_id, customer_name, phone_number "
                "FROM customers ORDER BY customer_id DESC LIMIT %s",
                [int(limit)],
            )
        like = f"%{kw}%"
        return self.db.fetch_all(
            "SELECT customer_id, customer_name, phone_number "
            "FROM customers "
            "WHERE COALESCE(customer_name,'') ILIKE %s "
            "OR CAST(customer_id AS text) LIKE %s "
            "OR COALESCE(phone_number,'') ILIKE %s "
            "ORDER BY customer_id DESC LIMIT %s",
            [like, f"{kw}%", like, int(limit)],
        )

    def search_products(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        """Item picker source. No keyword → newest ``limit`` items; with a keyword
        → the whole table filtered by name/code, then capped at ``limit``."""
        kw = (keyword or "").strip()
        if kw == "":
            return self.db.fetch_all(
                "SELECT id, item_code, item_name, price "
                "FROM products ORDER BY id DESC LIMIT %s",
                [int(limit)],
            )
        like = f"%{kw}%"
        return self.db.fetch_all(
            "SELECT id, item_code, item_name, price "
            "FROM products "
            "WHERE item_name ILIKE %s OR CAST(item_code AS text) LIKE %s "
            "ORDER BY id DESC LIMIT %s",
            [like, f"{kw}%", int(limit)],
        )

    def get_customer_name(self, customer_id: int) -> str | None:
        row = self.db.fetch_one(
            "SELECT customer_name FROM customers WHERE customer_id = %s",
            [int(customer_id)],
        )
        if not row:
            return None
        return (row.get("customer_name") or "").strip() or None

    def get_product_name(self, product_id: int) -> str | None:
        row = self.db.fetch_one(
            "SELECT item_name FROM products WHERE id = %s",
            [int(product_id)],
        )
        if not row:
            return None
        return (row.get("item_name") or "").strip() or None


__all__ = ["SalesReportRepository", "SalesReportFilters", "DEFAULT_PICKER_LIMIT"]
