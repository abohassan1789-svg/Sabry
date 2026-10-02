"""Unit tests for the Finished-Goods Warehouse repository (مخزن الإنتاج التام).

These do NOT need a live database: a fake ``Database`` records every SQL string
and its parameters, so we can pin the query contract without Postgres —

* only finished-goods products drive the result (``p.item_type = %s`` = 'منتج تام'),
* produced is summed from ``production_orders.production_quantity`` (header, one
  per order, no approval gate) joined by ``product_id``; sold is summed from
  **approved** ``sales_invoice_lines.quantity`` joined by the real ``product_id``
  FK — cashier sales are NOT included,
* the item-name filter (the only filter) is added only when provided; there is
  NO date filter,
* every finished product appears even with no movement (LEFT JOINs + COALESCE),
* the deterministic ordering (name, then code) is present.
"""

from __future__ import annotations

from typing import Any

from app.repositories.finished_goods_balance_repository import (
    FinishedGoodsBalanceFilters,
    FinishedGoodsBalanceRepository,
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
    return FinishedGoodsBalanceRepository(db=db), db


def test_fetch_balances_filters_to_finished_goods_only():
    repo, db = _repo()
    repo.fetch_balances(FinishedGoodsBalanceFilters())
    sql, params = db.calls[0]
    assert "p.item_type = %s" in sql
    # params are just the approved-status list then the finished-goods type
    assert params == [["approved"], "منتج تام"]
    # no name clause when nothing else is selected, and NO date filter at all
    assert "p.item_name ILIKE %s" not in sql
    assert "issue_datetime" not in sql
    assert "order_date" not in sql


def test_fetch_balances_joins_and_aggregates_the_three_sources():
    repo, db = _repo()
    repo.fetch_balances(FinishedGoodsBalanceFilters())
    sql, params = db.calls[0]
    # produced: header production_quantity, by product_id (no approval gate)
    assert "SUM(po.production_quantity)" in sql
    assert "FROM production_orders po" in sql
    assert "GROUP BY po.product_id" in sql
    assert "LEFT JOIN prod ON prod.product_id = p.id" in sql
    # sold: approved sales only, non-null product_id, summed quantity, by product_id
    assert "si.document_status = ANY(%s)" in sql
    assert "l.product_id IS NOT NULL" in sql
    assert "SUM(l.quantity)" in sql
    assert "JOIN sales_invoices si ON si.id = l.invoice_id" in sql
    assert "LEFT JOIN sales ON sales.product_id = p.id" in sql
    # cashier channel is NOT touched
    assert "cashier" not in sql.lower()
    # opening balance comes from the product row
    assert "p.opening_balance" in sql
    assert "ORDER BY p.item_name ASC, p.item_code ASC" in sql
    # the approved-status param leads the list
    assert params[0] == ["approved"]


def test_fetch_balances_adds_item_name_filter_only():
    repo, db = _repo()
    repo.fetch_balances(FinishedGoodsBalanceFilters(item_name="خرسانة"))
    sql, params = db.calls[0]
    assert "p.item_name ILIKE %s" in sql
    assert "issue_datetime" not in sql
    assert "order_date" not in sql
    # order: sales status, then product params (item_type, name)
    assert params == [["approved"], "منتج تام", "%خرسانة%"]


# --- item picker (finished goods only) --------------------------------------
def test_search_finished_goods_without_keyword_lists_finished_only_capped():
    repo, db = _repo()
    repo.search_finished_goods("", limit=500)
    sql, params = db.calls[0]
    assert "FROM products" in sql
    assert "item_type = %s" in sql
    assert "ORDER BY item_name ASC, item_code ASC LIMIT %s" in sql
    assert "ILIKE" not in sql
    assert params == ["منتج تام", 500]


def test_search_finished_goods_with_keyword_filters_name_or_code():
    repo, db = _repo()
    repo.search_finished_goods("خرسانة", limit=100)
    sql, params = db.calls[0]
    assert "item_name ILIKE %s OR CAST(item_code AS text) LIKE %s" in sql
    assert params == ["منتج تام", "%خرسانة%", "خرسانة%", 100]
