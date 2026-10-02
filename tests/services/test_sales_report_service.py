"""Service-level tests for the Sales report (تقرير المبيعات).

These use a fake repository (no database) to pin the pure logic: the row mapping
and column order, the fixed-decimal money / trimmed-quantity formatting, the unit
label mapping, the three dashboard KPIs (total sales, top customer by value, top
item by quantity), the "top 5 customers" chart with correct shares and ordering,
the empty state, and filter validation. The service must never write anything.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.sales_report_service import (
    EMPTY_MESSAGE,
    REPORT_COLUMNS,
    SalesReportRequest,
    SalesReportService,
    SalesReportValidationError,
)


class _FakeRepo:
    """Returns canned line rows; records filters and asserts read-only usage."""

    def __init__(self, rows):
        self._rows = rows
        self.fetch_calls: list = []

    def fetch_lines(self, filters):
        self.fetch_calls.append(filters)
        return list(self._rows)

    def search_customers(self, keyword="", limit=500):
        return [{"customer_id": 1, "customer_name": "عميل", "phone_number": "0100"}]

    def search_products(self, keyword="", limit=500):
        return [{"id": 7, "item_code": 7, "item_name": "طماطم", "price": Decimal("13")}]

    def get_customer_name(self, customer_id):
        return "عميل تجريبي"

    def get_product_name(self, product_id):
        return "طماطم"


def _line(customer_id, customer_name, number, product, qty, total, *,
          d=date(2026, 8, 14), unit="PCE", price="0"):
    return {
        "issue_date": d,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "invoice_number": number,
        "product_id": None,
        "product_name": product,
        "unit_code": unit,
        "quantity": Decimal(str(qty)),
        "unit_price": Decimal(str(price)),
        "line_total": Decimal(str(total)),
    }


def _service(rows):
    repo = _FakeRepo(rows)
    return SalesReportService(repository=repo), repo


# --- columns / mapping ------------------------------------------------------
def test_columns_are_the_required_ones_in_order():
    service, _ = _service([])
    assert [c.key for c in service.columns] == [
        "issue_date", "customer_name", "invoice_number",
        "product_name", "unit", "quantity", "unit_price", "line_total",
        "vat_amount", "line_total_including_vat",
    ]
    # الإجمالي (الصافي) ثم الضريبة ثم الإجمالي شامل الضريبة
    assert [c.label for c in REPORT_COLUMNS][-3:] == [
        "الإجمالي", "الضريبة", "الإجمالي شامل الضريبة"
    ]


def test_row_mapping_formats_money_quantity_price_and_unit():
    service, _ = _service([_line(1, "شركة النور", "INV-1", "طماطم", 320, "4160.00", unit="PCE", price="13")])
    result = service.fetch_report(SalesReportRequest())
    row = result.export_rows[0]
    assert row["issue_date"] == "2026-08-14"
    assert row["invoice_number"] == "INV-1"
    assert row["unit"] == "قطعة"          # PCE mapped to Arabic
    assert row["quantity"] == "320"        # whole number trimmed
    assert row["unit_price"] == "13.00"    # unit price, money 2dp
    assert row["line_total"] == "4,160.00" # money with thousands + 2dp


def test_unknown_unit_code_falls_back_to_raw():
    service, _ = _service([_line(1, "ع", "INV-1", "خيار", 3, "10", unit="XYZ")])
    assert service.fetch_report(SalesReportRequest()).export_rows[0]["unit"] == "XYZ"


def test_fractional_quantity_is_trimmed_not_padded():
    service, _ = _service([_line(1, "ع", "INV-1", "لحم", "2.5", "50", unit="KGM")])
    assert service.fetch_report(SalesReportRequest()).export_rows[0]["quantity"] == "2.5"


# --- KPIs -------------------------------------------------------------------
def test_total_sales_is_sum_of_all_line_totals():
    service, _ = _service([
        _line(1, "أ", "INV-1", "طماطم", 10, "100"),
        _line(2, "ب", "INV-2", "خيار", 5, "50.50"),
    ])
    summary = service.fetch_report(SalesReportRequest()).summary
    assert summary["total_sales"] == Decimal("150.50")
    assert summary["total_sales_label"] == "150.50"


def test_top_customer_is_by_summed_value_across_lines():
    service, _ = _service([
        _line(1, "شركة النور", "INV-1", "طماطم", 10, "100"),
        _line(1, "شركة النور", "INV-2", "خيار", 5, "60"),   # النور total 160
        _line(2, "مزرعة الوادي", "INV-3", "طماطم", 20, "150"),  # الوادي total 150
    ])
    summary = service.fetch_report(SalesReportRequest()).summary
    assert summary["top_customer_name"] == "شركة النور"
    assert summary["top_customer_value"] == Decimal("160.00")
    assert summary["top_customer_value_label"] == "160.00"


def test_top_item_is_by_summed_quantity_across_lines():
    service, _ = _service([
        _line(1, "أ", "INV-1", "طماطم", 10, "100"),
        _line(2, "ب", "INV-2", "طماطم", 15, "90"),   # طماطم qty 25
        _line(3, "ج", "INV-3", "خيار", 20, "200"),   # خيار qty 20
    ])
    summary = service.fetch_report(SalesReportRequest()).summary
    assert summary["top_item_name"] == "طماطم"
    assert summary["top_item_quantity"] == Decimal("25")
    assert summary["top_item_quantity_label"] == "25"


def test_top_customers_chart_is_sorted_desc_capped_at_five_with_shares():
    rows = [
        _line(1, "ع1", "I1", "ص", 1, "50"),
        _line(2, "ع2", "I2", "ص", 1, "40"),
        _line(3, "ع3", "I3", "ص", 1, "30"),
        _line(4, "ع4", "I4", "ص", 1, "20"),
        _line(5, "ع5", "I5", "ص", 1, "10"),
        _line(6, "ع6", "I6", "ص", 1, "5"),   # 6th — must be dropped
    ]
    result = _service(rows)[0].fetch_report(SalesReportRequest())
    chart = result.top_customers
    assert len(chart) == 5
    assert [c["label"] for c in chart] == ["ع1", "ع2", "ع3", "ع4", "ع5"]
    assert [c["value"] for c in chart][0] == Decimal("50.00")
    # total = 155; first share = 50/155*100 ≈ 32.3
    assert chart[0]["share"] == pytest.approx(32.3, abs=0.1)


# --- empty / validation -----------------------------------------------------
def test_empty_result_flags_is_empty_and_zero_kpis():
    service, _ = _service([])
    result = service.fetch_report(SalesReportRequest())
    assert result.is_empty is True
    assert result.summary["total_sales"] == Decimal("0.00")
    assert result.summary["top_customer_name"] == "—"
    assert result.top_customers == []
    assert EMPTY_MESSAGE  # message constant exists for the screen


def test_filters_are_passed_through_to_repository():
    service, repo = _service([])
    service.fetch_report(SalesReportRequest(customer_id=3, product_id=9,
                                            date_from="2026-08-01", date_to="2026-08-15"))
    f = repo.fetch_calls[0]
    assert f.customer_id == 3 and f.product_id == 9
    assert f.date_from == "2026-08-01" and f.date_to == "2026-08-15"


def test_reversed_date_range_raises_validation_error():
    service, _ = _service([])
    with pytest.raises(SalesReportValidationError):
        service.fetch_report(SalesReportRequest(date_from="2026-08-20", date_to="2026-08-01"))


def test_non_numeric_customer_id_raises_validation_error():
    service, _ = _service([])
    with pytest.raises(SalesReportValidationError):
        service.fetch_report(SalesReportRequest(customer_id="abc"))
