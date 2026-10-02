"""Screen-level tests for the Sales report (تقرير المبيعات).

Offscreen Qt with a fake service (no database): they pin that the screen builds
in the chosen Model-4 shape, that running the report fills the table + the three
KPI cards + the donut legend, that the count line and period line update, that
reset clears everything, and that the chosen customer/item ids and the date range
flow into the request the service receives.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from decimal import Decimal

from PySide6.QtWidgets import QApplication

from app.services.sales_report_service import (
    REPORT_COLUMNS,
    SalesReportRequest,
    SalesReportResult,
)
from app.ui.screens.sales_report_screen import SalesReportFilterDialog, SalesReportScreen


def _app():
    return QApplication.instance() or QApplication([])


def _result(rows):
    export_rows = list(rows)
    top = [
        {"label": "شركة النور", "value": Decimal("160.00"), "value_label": "160.00", "share": 51.6},
        {"label": "مزرعة الوادي", "value": Decimal("150.00"), "value_label": "150.00", "share": 48.4},
    ]
    summary = {
        "total_sales": Decimal("310.00"),
        "total_sales_label": "310.00",
        "top_customer_name": "شركة النور",
        "top_customer_value": Decimal("160.00"),
        "top_customer_value_label": "160.00",
        "top_item_name": "طماطم",
        "top_item_quantity": Decimal("30"),
        "top_item_quantity_label": "30",
    }
    return SalesReportResult(
        columns=list(REPORT_COLUMNS),
        rows=[],
        export_rows=export_rows,
        summary=summary,
        top_customers=top if export_rows else [],
        is_empty=not export_rows,
    )


class _FakeService:
    def __init__(self, rows):
        self.columns = list(REPORT_COLUMNS)
        self._rows = rows
        self.last_request: SalesReportRequest | None = None

    def fetch_report(self, request: SalesReportRequest) -> SalesReportResult:
        self.last_request = request
        return _result(self._rows)

    def search_customers(self, keyword="", limit=500):
        return [{"customer_id": 1, "customer_name": "شركة النور", "phone_number": "0100"}]

    def search_products(self, keyword="", limit=500):
        return [{"id": 7, "item_code": 7, "item_name": "طماطم", "price": Decimal("13")}]


_SAMPLE_ROWS = [
    {"issue_date": "2026-08-14", "customer_name": "شركة النور", "invoice_number": "INV-1",
     "product_name": "طماطم", "unit": "قطعة", "quantity": "320", "unit_price": "0.50", "line_total": "160.00"},
    {"issue_date": "2026-08-13", "customer_name": "مزرعة الوادي", "invoice_number": "INV-2",
     "product_name": "خيار", "unit": "صندوق", "quantity": "45", "unit_price": "3.33", "line_total": "150.00"},
]


def test_screen_builds_with_ten_columns():
    _app()
    screen = SalesReportScreen(service=_FakeService(_SAMPLE_ROWS))
    assert screen.table.columnCount() == 10
    labels = [screen.table.horizontalHeaderItem(i).text() for i in range(10)]
    assert labels[0] == "التاريخ"
    assert labels[-3:] == ["الإجمالي", "الضريبة", "الإجمالي شامل الضريبة"]


def test_apply_filters_fills_table_kpis_and_legend():
    _app()
    service = _FakeService(_SAMPLE_ROWS)
    screen = SalesReportScreen(service=service)
    screen.apply_filters()

    assert screen.table.rowCount() == 2
    assert "310.00" in screen.kpi_total["value"].text()
    assert "ر.س" not in screen.kpi_total["value"].text()  # currency removed
    assert screen.kpi_customer["value"].text() == "شركة النور"
    assert screen.kpi_item["value"].text() == "طماطم"
    # donut + legend reflect the two ranked customers
    assert len(screen.donut._slices) == 2
    assert screen.legend_box.count() == 2
    assert "عدد السطور: 2" in screen.count_label.text()
    assert "الفترة:" in screen.period_label.text()


def test_empty_result_shows_empty_state_and_no_chart_slices():
    _app()
    screen = SalesReportScreen(service=_FakeService([]))
    screen.apply_filters()
    assert screen.table.rowCount() == 0
    assert not screen.empty_label.isHidden()   # shown when empty
    assert screen.table.isHidden()             # table hidden when empty
    # No customers ranked -> no donut slices, legend shows its placeholder row.
    assert len(screen.donut._slices) == 0
    assert screen.legend_box.count() == 1


def test_request_carries_selected_ids_and_dates():
    _app()
    service = _FakeService(_SAMPLE_ROWS)
    screen = SalesReportScreen(service=service)
    screen._customer_id = 5
    screen._product_id = 9
    screen._date_from = "2026-08-01"
    screen._date_to = "2026-08-15"
    screen.apply_filters()
    request = service.last_request
    assert request.customer_id == 5
    assert request.product_id == 9
    assert request.date_from == "2026-08-01"
    assert request.date_to == "2026-08-15"


def test_reset_clears_table_ids_and_dashboard():
    _app()
    screen = SalesReportScreen(service=_FakeService(_SAMPLE_ROWS))
    screen._customer_id = 5
    screen._customer_name = "شركة النور"
    screen._product_id = 9
    screen.apply_filters()
    screen.reset_filters()
    assert screen._customer_id is None
    assert screen._customer_name == ""
    assert screen._product_id is None
    assert screen.table.rowCount() == 0
    assert screen.kpi_total["value"].text() == "—"
    assert screen.count_label.text() == ""


def test_filter_dialog_roundtrips_and_clears_state():
    _app()
    service = _FakeService(_SAMPLE_ROWS)
    state = {"date_from": "2026-08-01", "date_to": "2026-08-15",
             "customer_id": 5, "customer_name": "شركة النور",
             "product_id": 9, "product_name": "طماطم"}
    dialog = SalesReportFilterDialog(service, state)
    out = dialog.result_state()
    assert out["date_from"] == "2026-08-01" and out["date_to"] == "2026-08-15"
    assert out["customer_id"] == 5 and out["customer_name"] == "شركة النور"
    assert out["product_id"] == 9 and out["product_name"] == "طماطم"
    # pre-filled fields mirror the passed-in names
    assert dialog.customer_field.text() == "شركة النور"
    assert dialog.product_field.text() == "طماطم"
    dialog._clear()
    cleared = dialog.result_state()
    assert cleared["customer_id"] is None and cleared["customer_name"] == ""
    assert cleared["product_id"] is None and cleared["product_name"] == ""
