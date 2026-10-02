"""Tests for the التقرير الشامل service (no real DB — a fake records queries).

The service re-creates the Access ``ReportAll`` query: a flat detail listing over
``tawrid_tickets`` with **five optional filters** and **five footer totals**.
These pin, without touching a database:

* each filter is applied only when set (the Access ``= param OR param IS NULL``);
* an all-blank filter emits no WHERE clause (returns everything);
* the five totals sum the three price layers across the returned rows;
* ``export_rows`` formats money / volume; deleted parties fall back to a label.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.tawrid_comprehensive_report_service import (
    REPORT_COLUMNS,
    ReportFilters,
    TawridComprehensiveReportService,
)


class FakeDB:
    """Records the last (query, params) and returns preset rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.last_query: str | None = None
        self.last_params: list[Any] | None = None

    def fetch_all(self, query, params=None):
        self.last_query = query
        self.last_params = list(params or [])
        # distinct_items / picker queries return their own shapes; the build query
        # returns the ticket rows.
        if "DISTINCT item_name" in query:
            return [{"item_name": "سن 1"}, {"item_name": "سن 2"}]
        if "FROM tawrid_suppliers" in query:
            return [{"supplier_id": 1, "supplier_code": 10, "supplier_name": "الهدي", "is_active": True}]
        if "FROM tawrid_customers" in query and "tawrid_tickets" not in query:
            return [{"customer_id": 2, "customer_code": 20, "customer_name": "عصام", "is_active": True}]
        if "FROM tawrid_tractors" in query and "tawrid_tickets" not in query:
            return [{"tractor_id": 3, "driver_name": "سائق", "head_no": "1", "trailer_no": "3581", "is_active": True}]
        return self.rows

    def fetch_one(self, query, params=None):
        return None


def _ticket_rows() -> list[dict[str, Any]]:
    return [
        {
            "d": "2025-01-04", "item": "سن 2",
            "price_cus": Decimal("310"), "cus_volume": Decimal("61"), "total_cus": Decimal("18910"),
            "price_man": Decimal("140"), "total_man": Decimal("8540"),
            "price_res": Decimal("145"), "res_volume": Decimal("59"), "total_res": Decimal("8555"),
            "receipt_no": "185500", "supplier": "الهدي", "customer": None, "trailer": "3581",
            "ticket_no": 1,
        },
        {
            "d": "2025-01-05", "item": "سن 1",
            "price_cus": Decimal("300"), "cus_volume": Decimal("60"), "total_cus": Decimal("18000"),
            "price_man": Decimal("130"), "total_man": Decimal("7800"),
            "price_res": Decimal("150"), "res_volume": Decimal("58"), "total_res": Decimal("8700"),
            "receipt_no": None, "supplier": None, "customer": "عصام", "trailer": None,
            "ticket_no": 2,
        },
    ]


def _service(rows=None) -> tuple[TawridComprehensiveReportService, FakeDB]:
    db = FakeDB(rows if rows is not None else _ticket_rows())
    return TawridComprehensiveReportService(db=db), db


# --- filters -----------------------------------------------------------------

def test_empty_filters_emit_no_where_clause():
    svc, db = _service()
    svc.build(ReportFilters())
    assert "WHERE" not in db.last_query
    assert db.last_params == []


def test_each_filter_is_applied_only_when_set():
    svc, db = _service()
    svc.build(ReportFilters(
        date_from="2026-01-01", date_to="2026-06-30",
        supplier_id=7, customer_id=9, tractor_id=11, item_name="سن 2",
    ))
    q = db.last_query
    assert "t.ticket_date >= %s" in q and "t.ticket_date <= %s" in q
    assert "t.supplier_id = %s" in q
    assert "t.customer_id = %s" in q
    assert "t.tractor_id = %s" in q
    assert "t.item_name = %s" in q
    assert db.last_params == ["2026-01-01", "2026-06-30", 7, 9, 11, "سن 2"]


def test_only_customer_and_period_filter():
    svc, db = _service()
    svc.build(ReportFilters(customer_id=9, date_from="2026-01-01", date_to="2026-06-30"))
    q = db.last_query
    assert "t.customer_id = %s" in q
    # the JOINs always name t.supplier_id / t.tractor_id; assert no WHERE predicate
    assert "t.supplier_id = %s" not in q
    assert "t.tractor_id = %s" not in q
    assert "t.item_name = %s" not in q
    assert db.last_params == ["2026-01-01", "2026-06-30", 9]


def test_report_filters_is_empty_flag():
    assert ReportFilters().is_empty
    assert not ReportFilters(item_name="سن 2").is_empty
    assert not ReportFilters(customer_id=1).is_empty


# --- totals + rows -----------------------------------------------------------

def test_the_five_totals_sum_the_three_layers():
    svc, _ = _service()
    result = svc.build(ReportFilters())
    t = result.totals
    assert t.count == 2
    assert t.total_cus == Decimal("36910")   # 18910 + 18000
    assert t.total_man == Decimal("16340")   # 8540 + 7800
    assert t.total_res == Decimal("17255")   # 8555 + 8700
    assert t.cus_volume == Decimal("121")    # 61 + 60
    assert t.res_volume == Decimal("117")    # 59 + 58


def test_rows_carry_the_three_price_layers_and_serial():
    svc, _ = _service()
    rows = svc.build(ReportFilters()).rows
    assert rows[0].serial == 1 and rows[1].serial == 2
    r = rows[0]
    assert (r.price_cus, r.cus_volume, r.total_cus) == (Decimal("310"), Decimal("61"), Decimal("18910"))
    assert (r.price_man, r.total_man) == (Decimal("140"), Decimal("8540"))
    assert (r.price_res, r.res_volume, r.total_res) == (Decimal("145"), Decimal("59"), Decimal("8555"))


def test_missing_party_falls_back_to_deleted_label():
    svc, _ = _service()
    rows = svc.build(ReportFilters()).rows
    assert rows[0].customer == svc._DELETED_LABEL   # customer was None
    assert rows[1].supplier == svc._DELETED_LABEL   # supplier was None
    assert rows[1].trailer == "" and rows[1].receipt_no == ""


def test_empty_result_has_zero_totals():
    svc, _ = _service(rows=[])
    result = svc.build(ReportFilters())
    assert result.is_empty
    assert result.totals.count == 0
    assert result.totals.total_cus == Decimal("0")


# --- export + lookups --------------------------------------------------------

def test_export_rows_formats_money_and_volume():
    svc, _ = _service()
    cells = svc.export_rows(svc.build(ReportFilters()))
    assert cells[0]["total_cus"] == "18,910.00"
    assert cells[0]["cus_volume"] == "61"
    assert cells[0]["price_res"] == "145.00"
    assert set(cells[0]) == {c.key for c in REPORT_COLUMNS}


def test_distinct_items_and_picker_rows():
    svc, _ = _service()
    assert svc.distinct_items() == ["سن 1", "سن 2"]
    assert svc.supplier_picker_rows()[0]["supplier_name"] == "الهدي"
    assert svc.customer_picker_rows()[0]["customer_name"] == "عصام"
    assert svc.tractor_picker_rows()[0]["trailer_no"] == "3581"


def test_columns_expose_the_three_layers():
    keys = [c.key for c in REPORT_COLUMNS]
    for k in ("total_cus", "total_man", "total_res", "cus_volume", "res_volume"):
        assert k in keys
    labels = [c.label for c in REPORT_COLUMNS]
    assert "سعر العميل" in labels and "سعر السائق" in labels and "سعر المورد" in labels
