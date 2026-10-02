"""Unit tests for the Purchase-report repository (تقرير المشتريات).

These do NOT need a live database: a fake ``Database`` records every SQL string
and its parameters, so we can pin the query contract without Postgres —

* only **approved** invoices are counted (``document_status = ANY([...])``),
* date / supplier-name / item-name / payment-type filters are added only when
  provided, and in a deterministic, injection-safe (parametrised) way,
* the JOIN to lines + LEFT JOIN to suppliers (for the name fallback), the
  الوحدة / payment_type columns, and the deterministic ordering are present.
"""

from __future__ import annotations

from typing import Any

from app.repositories.purchase_report_repository import (
    PurchaseReportFilters,
    PurchaseReportRepository,
)


class _FakeDB:
    """Captures (sql, params) for each call and returns canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, list[Any]]] = []

    def fetch_all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        self.calls.append((sql, list(params) if params is not None else []))
        return list(self.rows)


def _repo(rows=None):
    db = _FakeDB(rows)
    return PurchaseReportRepository(db=db), db


def test_fetch_lines_defaults_to_approved_only():
    repo, db = _repo()
    repo.fetch_lines(PurchaseReportFilters())
    sql, params = db.calls[0]
    assert "pi.document_status = ANY(%s)" in sql
    assert params[0] == ["approved"]
    # no other filter clauses when nothing is selected
    assert "ILIKE" not in sql
    assert "pi.payment_type = %s" not in sql


def test_fetch_lines_joins_lines_and_suppliers_and_orders_deterministically():
    repo, db = _repo()
    repo.fetch_lines(PurchaseReportFilters())
    sql, _ = db.calls[0]
    assert "FROM purchase_invoices pi" in sql
    assert "JOIN purchase_invoice_lines l ON l.invoice_id = pi.id" in sql
    assert "LEFT JOIN suppliers s ON s.supplier_id = pi.supplier_id" in sql
    assert "l.unit_snapshot" in sql       # الوحدة carried on every row
    assert "pi.payment_type" in sql       # طريقة الدفع carried on every row
    assert "ORDER BY pi.issue_datetime ASC, pi.id ASC, l.line_number ASC" in sql


def test_fetch_lines_adds_all_filters_when_present():
    repo, db = _repo()
    repo.fetch_lines(PurchaseReportFilters(
        date_from="2026-08-01", date_to="2026-08-15",
        supplier_name="النخيل", item_name="أعلاف", payment_type="credit"))
    sql, params = db.calls[0]
    assert "pi.issue_datetime::date >= %s::date" in sql
    assert "pi.issue_datetime::date <= %s::date" in sql
    assert "pi.supplier_name_snapshot ILIKE %s OR s.supplier_name ILIKE %s" in sql
    assert "l.item_name_snapshot ILIKE %s" in sql
    assert "pi.payment_type = %s" in sql
    # approved list first, then filter values in clause order
    assert params == [
        ["approved"], "2026-08-01", "2026-08-15",
        "%النخيل%", "%النخيل%", "%أعلاف%", "credit",
    ]


def test_fetch_lines_supplier_filter_matches_snapshot_or_live_name():
    repo, db = _repo()
    repo.fetch_lines(PurchaseReportFilters(supplier_name="الوادي"))
    sql, params = db.calls[0]
    assert "pi.supplier_name_snapshot ILIKE %s OR s.supplier_name ILIKE %s" in sql
    assert params == [["approved"], "%الوادي%", "%الوادي%"]


# --- supplier picker --------------------------------------------------------
def test_search_suppliers_without_keyword_returns_newest_capped():
    repo, db = _repo()
    repo.search_suppliers("", limit=500)
    sql, params = db.calls[0]
    assert "FROM suppliers" in sql
    assert "ORDER BY supplier_id DESC LIMIT %s" in sql
    assert "ILIKE" not in sql
    assert params == [500]


def test_search_suppliers_with_keyword_filters_whole_table():
    repo, db = _repo()
    repo.search_suppliers("النخيل", limit=250)
    sql, params = db.calls[0]
    assert "supplier_name" in sql and "ILIKE %s" in sql
    assert "CAST(supplier_id AS text) LIKE %s" in sql
    assert params == ["%النخيل%", "النخيل%", 250]


# --- item picker (distinct free-text names) ---------------------------------
def test_search_item_names_without_keyword_groups_and_orders_by_usage():
    repo, db = _repo()
    repo.search_item_names("", limit=500)
    sql, params = db.calls[0]
    assert "FROM purchase_invoice_lines" in sql
    assert "GROUP BY item_name_snapshot" in sql
    assert "ORDER BY COUNT(*) DESC, item_name_snapshot ASC LIMIT %s" in sql
    assert "ILIKE" not in sql
    assert params == [500]


def test_search_item_names_with_keyword_adds_ilike_before_limit():
    repo, db = _repo()
    repo.search_item_names("أعلاف", limit=100)
    sql, params = db.calls[0]
    assert "item_name_snapshot ILIKE %s" in sql
    assert params == ["%أعلاف%", 100]
