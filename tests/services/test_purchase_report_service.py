"""Service-level tests for the Purchase report (تقرير المشتريات).

These use a fake repository (no database) to pin the pure logic: the row mapping
and the eight-column order (matching the simplified purchase invoice), the
fixed-decimal money / trimmed-quantity formatting, the four dashboard KPIs
(إجمالي المشتريات + invoice count + line count + top supplier), the two donut
datasets (top-5 suppliers by الإجمالي, and the نقدي/آجل payment breakdown with
correct shares), the empty state, and filter validation. The service must never
write anything.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.purchase_report_service import (
    EMPTY_MESSAGE,
    REPORT_COLUMNS,
    PurchaseReportRequest,
    PurchaseReportService,
    PurchaseReportValidationError,
)


class _FakeRepo:
    def __init__(self, rows):
        self._rows = rows
        self.fetch_calls: list = []

    def fetch_lines(self, filters):
        self.fetch_calls.append(filters)
        return list(self._rows)


def _line(number, supplier_id, supplier, item, *, payment="cash",
          unit="كيس", count="0", price="0", count_total="0"):
    return {
        "issue_date": "2026-08-14",
        "invoice_number": number,
        "supplier_id": supplier_id,
        "supplier_name": supplier,
        "payment_type": payment,
        "item_name": item,
        "unit": unit,
        "item_count": Decimal(count),
        "unit_price": Decimal(price),
        "count_price_total": Decimal(count_total),
    }


def _service(rows):
    repo = _FakeRepo(rows)
    return PurchaseReportService(repository=repo), repo


# --- columns / mapping ------------------------------------------------------
def test_columns_are_the_eight_required_ones_in_order():
    service, _ = _service([])
    assert [c.key for c in service.columns] == [
        "issue_date", "invoice_number", "supplier_name", "item_name",
        "unit", "item_count", "unit_price", "count_price_total",
    ]
    assert [c.label for c in REPORT_COLUMNS] == [
        "التاريخ", "رقم الفاتورة", "اسم المورد", "اسم الصنف",
        "الوحدة", "الكمية", "السعر", "الإجمالي",
    ]


def test_row_mapping_formats_money_and_trimmed_quantities():
    service, _ = _service([_line(
        "Pur-1042", 1, "مزرعة النخيل", "أعلاف مركّزة", unit="كيس",
        count="120", price="18.50", count_total="2220.00")])
    row = service.fetch_report(PurchaseReportRequest()).export_rows[0]
    assert row["issue_date"] == "2026-08-14"
    assert row["invoice_number"] == "Pur-1042"
    assert row["supplier_name"] == "مزرعة النخيل"
    assert row["item_name"] == "أعلاف مركّزة"
    assert row["unit"] == "كيس"
    assert row["item_count"] == "120"          # whole number trimmed
    assert row["unit_price"] == "18.50"        # money 2dp
    assert row["count_price_total"] == "2,220.00"


def test_fractional_quantity_is_trimmed_not_padded():
    service, _ = _service([_line("Pur-1", 1, "م", "شعير", count="2.5")])
    assert service.fetch_report(PurchaseReportRequest()).export_rows[0]["item_count"] == "2.5"


# --- KPIs -------------------------------------------------------------------
def test_summary_sums_total_invoice_count_and_line_count():
    service, _ = _service([
        _line("Pur-1", 1, "أ", "ذرة", count_total="100"),
        _line("Pur-1", 1, "أ", "شعير", count_total="40"),
        _line("Pur-2", 2, "ب", "فول", count_total="10"),
    ])
    summary = service.fetch_report(PurchaseReportRequest()).summary
    assert summary["total_count_price"] == Decimal("150.00")
    assert summary["total_count_price_label"] == "150.00"
    assert summary["invoice_count"] == 2       # Pur-1 counted once
    assert summary["invoice_count_label"] == "2"
    assert summary["line_count"] == 3          # three detail rows
    assert summary["line_count_label"] == "3"


def test_summary_reports_top_supplier_by_total():
    service, _ = _service([
        _line("P1", 1, "مورد1", "ص", count_total="50"),
        _line("P2", 2, "مورد2", "ص", count_total="120"),
        _line("P3", 2, "مورد2", "ص", count_total="30"),
    ])
    summary = service.fetch_report(PurchaseReportRequest()).summary
    assert summary["top_supplier_name"] == "مورد2"
    assert summary["top_supplier_value"] == Decimal("150.00")
    assert summary["top_supplier_value_label"] == "150.00"


def test_top_suppliers_ranked_by_total_desc_capped_at_five_with_shares():
    rows = [
        _line("P1", 1, "مورد1", "ص", count_total="50"),
        _line("P2", 2, "مورد2", "ص", count_total="40"),
        _line("P3", 3, "مورد3", "ص", count_total="30"),
        _line("P4", 4, "مورد4", "ص", count_total="20"),
        _line("P5", 5, "مورد5", "ص", count_total="10"),
        _line("P6", 6, "مورد6", "ص", count_total="5"),   # 6th — dropped
    ]
    chart = service_result(rows).top_suppliers
    assert len(chart) == 5
    assert [c["label"] for c in chart] == ["مورد1", "مورد2", "مورد3", "مورد4", "مورد5"]
    assert chart[0]["value"] == Decimal("50.00")
    # total = 155; first share = 50/155*100 ≈ 32.3
    assert chart[0]["share"] == pytest.approx(32.3, abs=0.1)


def test_payment_breakdown_splits_by_type_ordered_cash_then_credit():
    rows = [
        _line("P1", 1, "أ", "ص", payment="cash", count_total="30"),
        _line("P2", 2, "ب", "ص", payment="credit", count_total="70"),
        _line("P3", 3, "ج", "ص", payment="cash", count_total="20"),
    ]
    breakdown = service_result(rows).payment_breakdown
    labels = [b["label"] for b in breakdown]
    assert labels == ["نقدي", "آجل"]          # stable order: نقدي then آجل
    by_label = {b["label"]: b for b in breakdown}
    assert by_label["نقدي"]["value"] == Decimal("50.00")
    assert by_label["آجل"]["value"] == Decimal("70.00")
    assert by_label["آجل"]["share"] == pytest.approx(58.3, abs=0.1)


def test_unknown_payment_type_buckets_as_unknown():
    rows = [_line("P1", 1, "أ", "ص", payment=None, count_total="10")]
    breakdown = service_result(rows).payment_breakdown
    assert breakdown[0]["label"] == "غير محدد"


# --- empty / validation -----------------------------------------------------
def test_empty_result_flags_is_empty_and_zero_kpis():
    service, _ = _service([])
    result = service.fetch_report(PurchaseReportRequest())
    assert result.is_empty is True
    assert result.summary["total_count_price"] == Decimal("0.00")
    assert result.summary["invoice_count"] == 0
    assert result.summary["line_count"] == 0
    assert result.top_suppliers == []
    assert result.payment_breakdown == []
    assert EMPTY_MESSAGE


def test_filters_pass_through_to_repository():
    service, repo = _service([])
    service.fetch_report(PurchaseReportRequest(
        date_from="2026-08-01", date_to="2026-08-15",
        supplier_name=" النخيل ", item_name=" أعلاف ", payment_type="credit"))
    f = repo.fetch_calls[0]
    assert f.date_from == "2026-08-01" and f.date_to == "2026-08-15"
    assert f.supplier_name == "النخيل" and f.item_name == "أعلاف"   # trimmed
    assert f.payment_type == "credit"


def test_blank_filters_become_none():
    service, repo = _service([])
    service.fetch_report(PurchaseReportRequest(supplier_name="   ", item_name="", payment_type=None))
    f = repo.fetch_calls[0]
    assert f.supplier_name is None and f.item_name is None and f.payment_type is None


def test_reversed_date_range_raises_validation_error():
    service, _ = _service([])
    with pytest.raises(PurchaseReportValidationError):
        service.fetch_report(PurchaseReportRequest(date_from="2026-08-20", date_to="2026-08-01"))


# --- picker wrappers --------------------------------------------------------
def test_search_wrappers_pass_through_repository_rows():
    class _PickRepo:
        def search_suppliers(self, keyword="", limit=500):
            return [{"supplier_id": 1, "supplier_name": "مزرعة النخيل"}]

        def search_item_names(self, keyword="", limit=500):
            return [{"item_name": "أعلاف مركّزة", "usage_count": 5}]

    service = PurchaseReportService(repository=_PickRepo())
    assert service.search_suppliers("نخيل")[0]["supplier_name"] == "مزرعة النخيل"
    assert service.search_items("أعلاف")[0]["item_name"] == "أعلاف مركّزة"


def test_search_wrappers_never_crash_the_screen():
    class _BoomRepo:
        def search_suppliers(self, keyword="", limit=500):
            raise RuntimeError("db down")

        def search_item_names(self, keyword="", limit=500):
            raise RuntimeError("db down")

    service = PurchaseReportService(repository=_BoomRepo())
    assert service.search_suppliers("x") == []
    assert service.search_items("x") == []


def service_result(rows):
    service, _ = _service(rows)
    return service.fetch_report(PurchaseReportRequest())
