"""Unit tests for the Sales-report repository (تقرير المبيعات).

These do NOT need a live database: a fake ``Database`` records every SQL string
and its parameters, so we can pin the query contract without Postgres —

* only **approved** invoices are counted (``document_status = ANY([...])``),
* customer / product / date filters are added only when provided, and in a
  deterministic, injection-safe (parametrised) way,
* the two selectors implement "newest 500 with no keyword, whole-table ILIKE
  search once a keyword is typed", ordered newest-first and capped at the limit.

A separate DB-backed integration test can later assert the JOIN/GROUP semantics;
this file guards the SQL the repository emits.
"""

from __future__ import annotations

from typing import Any

from app.repositories.sales_report_repository import (
    SalesReportFilters,
    SalesReportRepository,
)


class _FakeDB:
    """Captures (sql, params) for each call and returns canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, list[Any]]] = []

    def fetch_all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        self.calls.append((sql, list(params) if params is not None else []))
        return list(self.rows)

    def fetch_one(self, sql: str, params: Any = None):
        self.calls.append((sql, list(params) if params is not None else []))
        return self.rows[0] if self.rows else None


def _repo(rows=None):
    db = _FakeDB(rows)
    return SalesReportRepository(db=db), db


# --- fetch_lines ------------------------------------------------------------
def test_fetch_lines_defaults_to_approved_only():
    repo, db = _repo()
    repo.fetch_lines(SalesReportFilters())
    sql, params = db.calls[0]
    assert "document_status = ANY(%s)" in sql
    assert params[0] == ["approved"]
    # no other filter clauses when nothing is selected
    assert "customer_id = %s" not in sql
    assert "product_id = %s" not in sql


def test_fetch_lines_joins_lines_and_orders_deterministically():
    repo, db = _repo()
    repo.fetch_lines(SalesReportFilters())
    sql, _ = db.calls[0]
    assert "FROM sales_invoices si" in sql
    assert "JOIN sales_invoice_lines l ON l.invoice_id = si.id" in sql
    assert "ORDER BY si.issue_datetime ASC, si.id ASC, l.line_number ASC" in sql


def test_fetch_lines_adds_customer_product_and_date_filters_when_present():
    repo, db = _repo()
    repo.fetch_lines(SalesReportFilters(
        customer_id=3, product_id=9, date_from="2026-08-01", date_to="2026-08-15"))
    sql, params = db.calls[0]
    assert "si.customer_id = %s" in sql
    assert "l.product_id = %s" in sql
    assert "si.issue_datetime::date >= %s::date" in sql
    assert "si.issue_datetime::date <= %s::date" in sql
    # approved list first, then the four filter values in clause order
    assert params == [["approved"], 3, 9, "2026-08-01", "2026-08-15"]


def test_fetch_lines_honours_custom_status_set():
    repo, db = _repo()
    repo.fetch_lines(SalesReportFilters(statuses=("approved", "draft")))
    _sql, params = db.calls[0]
    assert params[0] == ["approved", "draft"]


# --- customer selector ------------------------------------------------------
def test_search_customers_without_keyword_returns_newest_capped():
    repo, db = _repo()
    repo.search_customers("", limit=500)
    sql, params = db.calls[0]
    assert "ORDER BY customer_id DESC LIMIT %s" in sql
    assert "ILIKE" not in sql
    assert params == [500]


def test_search_customers_with_keyword_filters_whole_table():
    repo, db = _repo()
    repo.search_customers("نور", limit=500)
    sql, params = db.calls[0]
    assert "ILIKE %s" in sql
    assert params == ["%نور%", "نور%", "%نور%", 500]


# --- product selector -------------------------------------------------------
def test_search_products_without_keyword_returns_newest_capped():
    repo, db = _repo()
    repo.search_products("", limit=500)
    sql, params = db.calls[0]
    assert "FROM products" in sql
    assert "ORDER BY id DESC LIMIT %s" in sql
    assert params == [500]


def test_search_products_with_keyword_filters_by_name_and_code():
    repo, db = _repo()
    repo.search_products("طماطم", limit=250)
    sql, params = db.calls[0]
    assert "item_name ILIKE %s" in sql
    assert "CAST(item_code AS text) LIKE %s" in sql
    assert params == ["%طماطم%", "طماطم%", 250]
