"""Read-only database access for the Profit Report (تقرير الأرباح).

This repository performs **SELECTs only** — the report never writes. It reads two
existing header tables and combines them, at the service layer, into a single
movement list:

* ``sales_invoices``    — one row per sales invoice; the invoice total lives in
  ``total_including_vat`` (فاتورة المبيعات has no VAT, so this is quantity×price).
* ``purchase_invoices`` — one row per purchase invoice; there is **no single
  total column**, so the invoice total is ``total_count_price + total_weight_price``.

Only **approved** documents are counted by default (mirrors
``SalesReportRepository`` / ``PurchaseReportRepository``): a draft is not a real
sale/purchase and must not move the profit figure. The date range filters on
``issue_datetime::date`` on both sides, exactly like the two existing reports.

The company letterhead lookup (first registered company) is kept here for the
printable sheet, which is a later stage — the on-screen report does not use it.

Built on the shared psycopg ``Database`` helper.
"""

from __future__ import annotations

from typing import Any

from app.database.db import Database
from app.models.sales_invoice import STATUS_APPROVED


class ProfitReportRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    # ======================================================================
    # Company letterhead (the FIRST registered company — read-only)
    # ======================================================================
    def fetch_company_letterhead(self) -> dict[str, Any] | None:
        """Return the first registered company for the printable letterhead.

        Kept for the print/PDF stage; the on-screen report does not render it.
        ``None`` if no company is registered yet.
        """
        return self.db.fetch_one(
            "SELECT id, name_ar, name_en, commercial_registration, vat_number, "
            "phone, address_ar, address_en, logo, logo_mime "
            "FROM companies ORDER BY id LIMIT 1"
        )

    # ======================================================================
    # Sales invoice headers (one row per invoice)
    # ======================================================================
    def fetch_sales_invoices(
        self,
        *,
        date_from: Any = None,
        date_to: Any = None,
        statuses: tuple[str, ...] = (STATUS_APPROVED,),
    ) -> list[dict[str, Any]]:
        """Approved sales-invoice headers in the date range (oldest first).

        Each row: id, invoice_number, issue_datetime (for deterministic sorting),
        issue_date (::date for display) and ``total`` (``total_including_vat``).
        """
        conds = ["si.document_status = ANY(%s)"]
        params: list[Any] = [list(statuses or (STATUS_APPROVED,))]
        if date_from is not None:
            conds.append("si.issue_datetime::date >= %s::date")
            params.append(date_from)
        if date_to is not None:
            conds.append("si.issue_datetime::date <= %s::date")
            params.append(date_to)
        where = " AND ".join(conds)
        sql = (
            "SELECT si.id AS id, "
            "si.invoice_number AS invoice_number, "
            "si.issue_datetime AS issue_datetime, "
            "si.issue_datetime::date AS issue_date, "
            "COALESCE(si.total_including_vat, 0) AS total "
            "FROM sales_invoices si "
            f"WHERE {where} "
            "ORDER BY si.issue_datetime ASC, si.id ASC"
        )
        return self.db.fetch_all(sql, params)

    # ======================================================================
    # Purchase invoice headers (one row per invoice)
    # ======================================================================
    def fetch_purchase_invoices(
        self,
        *,
        date_from: Any = None,
        date_to: Any = None,
        statuses: tuple[str, ...] = (STATUS_APPROVED,),
    ) -> list[dict[str, Any]]:
        """Approved purchase-invoice headers in the date range (oldest first).

        The invoice total has no single column, so it is
        ``total_count_price + total_weight_price``. Each row: id, invoice_number,
        issue_datetime, issue_date and ``total``.
        """
        conds = ["pi.document_status = ANY(%s)"]
        params: list[Any] = [list(statuses or (STATUS_APPROVED,))]
        if date_from is not None:
            conds.append("pi.issue_datetime::date >= %s::date")
            params.append(date_from)
        if date_to is not None:
            conds.append("pi.issue_datetime::date <= %s::date")
            params.append(date_to)
        where = " AND ".join(conds)
        sql = (
            "SELECT pi.id AS id, "
            "pi.invoice_number AS invoice_number, "
            "pi.issue_datetime AS issue_datetime, "
            "pi.issue_datetime::date AS issue_date, "
            "(COALESCE(pi.total_count_price, 0) + COALESCE(pi.total_weight_price, 0)) AS total "
            "FROM purchase_invoices pi "
            f"WHERE {where} "
            "ORDER BY pi.issue_datetime ASC, pi.id ASC"
        )
        return self.db.fetch_all(sql, params)


__all__ = ["ProfitReportRepository"]
