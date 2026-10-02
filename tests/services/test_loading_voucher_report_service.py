"""Unit tests for the Loading Vouchers report service (تقرير سندات التحميل).

No database: a fake repository feeds canned rows, so these pin the service's own
logic — the free-text weight parsing, the three summary cards, the verbatim
weight display, date/time formatting and the filter pass-through.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.services.loading_voucher_report_service import (
    LoadingVoucherReportRequest,
    LoadingVoucherReportService,
    LoadingVoucherReportValidationError,
    REPORT_COLUMNS,
)


class _FakeRepo:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.last_filters = None

    def fetch_rows(self, filters):
        self.last_filters = filters
        return self._rows

    def fetch_customer_options(self):
        return [{"id": 5, "label": "محمد علي"}, {"id": 7, "label": None}]

    def fetch_item_options(self):
        return [{"id": 2, "label": "أسمنت"}]

    def fetch_vehicle_options(self):
        return [{"id": "ق ب ن 4521", "label": "ق ب ن 4521"}]


def _row(**over):
    base = {
        "voucher_number": "LV-001",
        "voucher_date": dt.date(2026, 8, 13),
        "voucher_time": dt.time(6, 20),
        "customer_name_snapshot": "محمد علي",
        "item_name_snapshot": "أسمنت",
        "driver_name": "سعيد",
        "vehicle_number": "ق ب ن 4521",
        "weight_before_loading": "12500",
        "weight_after_loading": "37500",
        "notes": None,
    }
    base.update(over)
    return base


def _service(rows):
    return LoadingVoucherReportService(repository=_FakeRepo(rows))


def test_columns_are_the_ten_required_in_order():
    keys = [c.key for c in REPORT_COLUMNS]
    assert keys == [
        "voucher_number", "voucher_date", "voucher_time", "customer_name",
        "item_name", "driver_name", "vehicle_number", "weight_before",
        "weight_after", "notes",
    ]


def test_summary_counts_vouchers_and_sums_both_weights():
    service = _service([
        _row(weight_before_loading="12500", weight_after_loading="37500"),
        _row(weight_before_loading="13200", weight_after_loading="31700"),
    ])
    result = service.fetch_report(LoadingVoucherReportRequest())
    assert result.summary["voucher_count"] == 2
    assert result.summary["total_weight_before"] == Decimal("25700")
    assert result.summary["total_weight_after"] == Decimal("69200")
    assert result.summary["voucher_count_label"] == "2"
    assert result.summary["total_weight_before_label"] == "25,700"


def test_weight_parsing_handles_commas_units_and_arabic_digits():
    service = _service([
        _row(weight_before_loading="12,500 كجم", weight_after_loading="١٢٥٠٠"),
    ])
    result = service.fetch_report(LoadingVoucherReportRequest())
    assert result.summary["total_weight_before"] == Decimal("12500")
    assert result.summary["total_weight_after"] == Decimal("12500")


def test_blank_or_non_numeric_weight_contributes_zero_not_error():
    service = _service([
        _row(weight_before_loading="", weight_after_loading="لا يوجد"),
        _row(weight_before_loading=None, weight_after_loading="10"),
    ])
    result = service.fetch_report(LoadingVoucherReportRequest())
    assert result.summary["total_weight_before"] == Decimal("0")
    assert result.summary["total_weight_after"] == Decimal("10")


def test_weights_are_shown_verbatim_in_the_rows():
    service = _service([_row(weight_before_loading="12,500 كجم")])
    result = service.fetch_report(LoadingVoucherReportRequest())
    # The detail cell keeps exactly what the user typed, not a reformatted number.
    assert result.rows[0]["weight_before"] == "12,500 كجم"


def test_date_and_time_are_formatted_for_display():
    service = _service([_row()])
    row = service.fetch_report(LoadingVoucherReportRequest()).rows[0]
    assert row["voucher_date"] == "2026-08-13"
    assert row["voucher_time"] == "06:20"


def test_filters_pass_through_to_the_repository():
    repo = _FakeRepo([])
    service = LoadingVoucherReportService(repository=repo)
    service.fetch_report(LoadingVoucherReportRequest(
        date_from="2026-08-01", date_to="2026-08-31",
        customer_id="5", product_id="2", vehicle_number="ق ب ن 4521",
    ))
    f = repo.last_filters
    assert (f.date_from, f.date_to) == ("2026-08-01", "2026-08-31")
    assert f.customer_id == 5 and f.product_id == 2
    assert f.vehicle_number == "ق ب ن 4521"


def test_empty_result_is_flagged():
    result = _service([]).fetch_report(LoadingVoucherReportRequest())
    assert result.is_empty is True
    assert result.rows == []
    assert result.summary["voucher_count"] == 0


def test_reversed_date_range_is_rejected():
    with pytest.raises(LoadingVoucherReportValidationError):
        _service([]).fetch_report(
            LoadingVoucherReportRequest(date_from="2026-08-31", date_to="2026-08-01")
        )


def test_option_loaders_normalise_missing_labels():
    service = _service([])
    customers = service.load_customer_options()
    assert customers[0] == {"id": 5, "label": "محمد علي"}
    assert customers[1] == {"id": 7, "label": "غير محدد"}
