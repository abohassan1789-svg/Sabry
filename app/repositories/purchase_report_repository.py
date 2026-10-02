"""Read-only database layer for the Purchase report (تقرير المشتريات).

This is the ONLY place SQL for this report lives. It returns plain, read-only row
dicts; the service (``app/services/purchase_report_service.py``) does all Arabic
labels, money / quantity formatting, totals and the dashboard KPIs, and the UI
never sees SQL.

Data source
-----------
One report row per **purchase-invoice line**: ``purchase_invoices`` (header)
JOINed to ``purchase_invoice_lines`` (detail) and LEFT JOINed to ``suppliers``
(only to fall back to the live supplier name). Each line carries its ``الوحدة``
(``unit_snapshot``) and the header's ``payment_type`` (نقدي / آجل). By the same
rule the sales report uses, only **approved** invoices are counted — a purchase
report should reflect real, finalised purchases, so drafts are excluded
(``document_status = 'approved'``).

The purchase screen no longer captures weight, so the weight columns
(``unit_weight`` / ``total_weight`` / ``weight_price_total``) stay zero in the
database and this report no longer reads them; the line total is
``count_price_total`` (الكمية × السعر).

Filters (all optional): a date range on ``issue_datetime``, a supplier-name
contains-search (matched against the stored snapshot or the live supplier name),
an item-name contains-search on the free-text ``item_name_snapshot`` (purchase
lines have no products link), and an exact ``payment_type`` (cash / credit).

Read-only contract: this module only ``SELECT``s. It never inserts, updates or
deletes any invoice, line or supplier row, and never issues DDL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.db import Database
from app.models.purchase_invoice import STATUS_APPROVED

# Default picker page size — "آخر 500" (newest, then searchable beyond).
DEFAULT_PICKER_LIMIT = 500


@dataclass(frozen=True)
class PurchaseReportFilters:
    """Normalised query input. Every field is optional (``None`` = no restriction
    on that dimension); dates are ``YYYY-MM-DD`` strings or ``None`` (open-ended).

    ``payment_type`` is the stored code on ``purchase_invoices.payment_type``
    ('cash' or 'credit'); ``supplier_name`` / ``item_name`` are free-text
    contains-searches. ``statuses`` defaults to approved-only but stays a
    parameter so the rule can change in one place.
    """

    date_from: str | None = None
    date_to: str | None = None
    supplier_name: str | None = None
    item_name: str | None = None
    payment_type: str | None = None
    statuses: tuple[str, ...] = (STATUS_APPROVED,)


class PurchaseReportRepository:
    """Read-only SQL for the purchase-report detail rows."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

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

    def fetch_lines(self, filters: PurchaseReportFilters) -> list[dict[str, Any]]:
        """Return every purchase-invoice line matching the filters, oldest first.

        Ordered deterministically on the real ``issue_datetime`` then invoice id
        then line number, so the on-screen order matches any later export/print.
        The supplier name prefers the invoice's stored snapshot and falls back to
        the live ``suppliers`` row.
        """
        conditions: list[str] = []
        params: list[Any] = []

        statuses = tuple(filters.statuses) or (STATUS_APPROVED,)
        conditions.append("pi.document_status = ANY(%s)")
        params.append(list(statuses))

        if filters.date_from:
            conditions.append("pi.issue_datetime::date >= %s::date")
            params.append(filters.date_from)
        if filters.date_to:
            conditions.append("pi.issue_datetime::date <= %s::date")
            params.append(filters.date_to)
        if filters.supplier_name:
            conditions.append(
                "(pi.supplier_name_snapshot ILIKE %s OR s.supplier_name ILIKE %s)"
            )
            like = f"%{filters.supplier_name}%"
            params.append(like)
            params.append(like)
        if filters.item_name:
            conditions.append("l.item_name_snapshot ILIKE %s")
            params.append(f"%{filters.item_name}%")
        if filters.payment_type:
            conditions.append("pi.payment_type = %s")
            params.append(filters.payment_type)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT
                pi.issue_datetime::date                                        AS issue_date,
                pi.invoice_number                                              AS invoice_number,
                pi.supplier_id                                                 AS supplier_id,
                COALESCE(NULLIF(TRIM(pi.supplier_name_snapshot), ''),
                         s.supplier_name, '')                                  AS supplier_name,
                pi.payment_type                                                AS payment_type,
                l.item_name_snapshot                                           AS item_name,
                l.unit_snapshot                                                AS unit,
                l.item_count                                                   AS item_count,
                l.unit_price                                                   AS unit_price,
                l.count_price_total                                            AS count_price_total
            FROM purchase_invoices pi
            JOIN purchase_invoice_lines l ON l.invoice_id = pi.id
            LEFT JOIN suppliers s ON s.supplier_id = pi.supplier_id
            WHERE {where}
            ORDER BY pi.issue_datetime ASC, pi.id ASC, l.line_number ASC
        """
        return self.db.fetch_all(sql, params)

    # --- pickers (read-only, "newest 500 but searchable beyond") ------------
    def search_suppliers(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        """Supplier picker source. No keyword → newest ``limit`` suppliers; with a
        keyword → the whole table filtered by name / id, then capped at ``limit``."""
        kw = (keyword or "").strip()
        if kw == "":
            return self.db.fetch_all(
                "SELECT supplier_id, supplier_name, account_type, mobile "
                "FROM suppliers ORDER BY supplier_id DESC LIMIT %s",
                [int(limit)],
            )
        like = f"%{kw}%"
        return self.db.fetch_all(
            "SELECT supplier_id, supplier_name, account_type, mobile "
            "FROM suppliers "
            "WHERE COALESCE(supplier_name,'') ILIKE %s OR CAST(supplier_id AS text) LIKE %s "
            "ORDER BY supplier_id DESC LIMIT %s",
            [like, f"{kw}%", int(limit)],
        )

    def search_item_names(
        self, keyword: str = "", limit: int = DEFAULT_PICKER_LIMIT
    ) -> list[dict[str, Any]]:
        """Item picker source. Purchase items are free text (no products table), so
        the picker lists the DISTINCT item names actually used on purchase lines,
        most-used first, with how many lines used each. Filtered by an ILIKE
        contains-search once a keyword is typed, then capped at ``limit``."""
        kw = (keyword or "").strip()
        conditions = ["item_name_snapshot IS NOT NULL",
                      "char_length(btrim(item_name_snapshot)) > 0"]
        params: list[Any] = []
        if kw != "":
            conditions.append("item_name_snapshot ILIKE %s")
            params.append(f"%{kw}%")
        where = " AND ".join(conditions)
        params.append(int(limit))
        return self.db.fetch_all(
            "SELECT item_name_snapshot AS item_name, COUNT(*) AS usage_count "
            "FROM purchase_invoice_lines "
            f"WHERE {where} "
            "GROUP BY item_name_snapshot "
            "ORDER BY COUNT(*) DESC, item_name_snapshot ASC LIMIT %s",
            params,
        )


__all__ = [
    "PurchaseReportRepository",
    "PurchaseReportFilters",
    "DEFAULT_PICKER_LIMIT",
]
