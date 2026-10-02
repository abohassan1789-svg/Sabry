"""Screen-level tests for the Purchase report (تقرير المشتريات).

Offscreen Qt with a fake service (no database): they pin that the screen builds
in the chosen Model-1 shape (eight columns matching the invoice, inline filter
bar, four KPI cards, two donuts), that running the report fills the table + KPI
cards + both donut legends, that reset clears everything, and that the
filter-bar values (dates, supplier/item text, payment-type dropdown) flow into
the request.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from decimal import Decimal

from PySide6.QtWidgets import QApplication

from app.services.purchase_report_service import (
    REPORT_COLUMNS,
    PurchaseReportRequest,
    PurchaseReportResult,
)
from app.ui.screens.purchase_report_screen import PurchaseReportScreen


def _app():
    return QApplication.instance() or QApplication([])


def _result(rows):
    export_rows = list(rows)
    top = [
        {"label": "مزرعة النخيل", "value": Decimal("2220.00"), "value_label": "2,220.00", "share": 60.0},
        {"label": "مؤسسة الوادي", "value": Decimal("1480.00"), "value_label": "1,480.00", "share": 40.0},
    ]
    payments = [
        {"label": "نقدي", "value": Decimal("1480.00"), "value_label": "1,480.00", "share": 40.0},
        {"label": "آجل", "value": Decimal("2220.00"), "value_label": "2,220.00", "share": 60.0},
    ]
    summary = {
        "total_count_price": Decimal("3700.00"), "total_count_price_label": "3,700.00",
        "invoice_count": 2, "invoice_count_label": "2",
        "line_count": 2, "line_count_label": "2",
        "top_supplier_name": "مزرعة النخيل", "top_supplier_value": Decimal("2220.00"),
        "top_supplier_value_label": "2,220.00",
    }
    return PurchaseReportResult(
        columns=list(REPORT_COLUMNS),
        rows=[],
        export_rows=export_rows,
        summary=summary,
        top_suppliers=top if export_rows else [],
        payment_breakdown=payments if export_rows else [],
        is_empty=not export_rows,
    )


class _FakeService:
    def __init__(self, rows):
        self.columns = list(REPORT_COLUMNS)
        self._rows = rows
        self.last_request: PurchaseReportRequest | None = None

    def fetch_report(self, request: PurchaseReportRequest) -> PurchaseReportResult:
        self.last_request = request
        return _result(self._rows)

    def search_suppliers(self, keyword="", limit=500):
        return [{"supplier_id": 1, "supplier_name": "مزرعة النخيل",
                 "account_type": "وزن", "mobile": "0100"}]

    def search_items(self, keyword="", limit=500):
        return [{"item_name": "أعلاف مركّزة", "usage_count": 5}]


_SAMPLE_ROWS = [
    {"issue_date": "2026-08-14", "invoice_number": "Pur-1042", "supplier_name": "مزرعة النخيل",
     "item_name": "أعلاف مركّزة", "unit": "كيس", "item_count": "120",
     "unit_price": "18.50", "count_price_total": "2,220.00"},
    {"issue_date": "2026-08-13", "invoice_number": "Pur-1043", "supplier_name": "مؤسسة الوادي",
     "item_name": "ذرة صفراء", "unit": "طن", "item_count": "80",
     "unit_price": "15.20", "count_price_total": "1,216.00"},
]


def test_screen_builds_with_eight_columns_in_order():
    _app()
    screen = PurchaseReportScreen(service=_FakeService(_SAMPLE_ROWS))
    assert screen.table.columnCount() == 8
    labels = [screen.table.horizontalHeaderItem(i).text() for i in range(8)]
    assert labels == [
        "التاريخ", "رقم الفاتورة", "اسم المورد", "اسم الصنف",
        "الوحدة", "الكمية", "السعر", "الإجمالي",
    ]


def test_apply_filters_fills_table_kpis_and_both_legends():
    _app()
    screen = PurchaseReportScreen(service=_FakeService(_SAMPLE_ROWS))
    screen.apply_filters()

    assert screen.table.rowCount() == 2
    assert "3,700.00" in screen.kpi_total["value"].text()
    assert "ر.س" not in screen.kpi_total["value"].text()  # currency removed
    assert screen.kpi_invoices["value"].text() == "2"
    assert screen.kpi_items["value"].text() == "2"
    assert "مزرعة النخيل" in screen.kpi_top_supplier["value"].text()
    assert "2,220.00" in screen.kpi_top_supplier["value"].text()
    # both donuts + legends reflect two slices each
    assert len(screen.supplier_donut._slices) == 2
    assert len(screen.payment_donut._slices) == 2
    assert screen.supplier_legend.count() == 2
    assert screen.payment_legend.count() == 2
    assert "الفترة:" in screen.period_label.text()


def test_empty_result_shows_empty_state_and_no_chart_slices():
    _app()
    screen = PurchaseReportScreen(service=_FakeService([]))
    screen.apply_filters()
    assert screen.table.rowCount() == 0
    assert not screen.empty_label.isHidden()
    assert screen.table.isHidden()
    assert len(screen.supplier_donut._slices) == 0
    assert len(screen.payment_donut._slices) == 0
    # legends fall back to their single placeholder row
    assert screen.supplier_legend.count() == 1
    assert screen.payment_legend.count() == 1


def test_request_carries_filterbar_values():
    _app()
    service = _FakeService(_SAMPLE_ROWS)
    screen = PurchaseReportScreen(service=service)
    screen.from_date.setDate(screen.from_date.date().fromString("2026-08-01", "yyyy-MM-dd"))
    screen.to_date.setDate(screen.to_date.date().fromString("2026-08-15", "yyyy-MM-dd"))
    screen.supplier_field.setText("النخيل")
    screen.item_field.setText("أعلاف")
    screen.payment_combo.setCurrentText("آجل")
    screen.apply_filters()
    request = service.last_request
    assert request.date_from == "2026-08-01"
    assert request.date_to == "2026-08-15"
    assert request.supplier_name == "النخيل"
    assert request.item_name == "أعلاف"
    assert request.payment_type == "credit"


def test_payment_all_maps_to_none():
    _app()
    service = _FakeService(_SAMPLE_ROWS)
    screen = PurchaseReportScreen(service=service)
    screen.payment_combo.setCurrentText("الكل")
    screen.apply_filters()
    assert service.last_request.payment_type is None


def test_name_fields_are_double_click_pickers():
    _app()
    screen = PurchaseReportScreen(service=_FakeService(_SAMPLE_ROWS))
    # Both name fields expose a doubleClicked signal wired to open a picker.
    assert hasattr(screen.supplier_field, "doubleClicked")
    assert hasattr(screen.item_field, "doubleClicked")
    # Selecting a row fills the field with the chosen name (simulate the dialog
    # result without opening a modal by driving the fill directly).
    screen.supplier_field.setText("مزرعة النخيل")
    screen.item_field.setText("أعلاف مركّزة")
    screen.apply_filters()
    assert service_request(screen).supplier_name == "مزرعة النخيل"
    assert service_request(screen).item_name == "أعلاف مركّزة"


def service_request(screen):
    return screen.service.last_request


def test_reset_clears_table_filters_and_dashboard():
    _app()
    screen = PurchaseReportScreen(service=_FakeService(_SAMPLE_ROWS))
    screen.supplier_field.setText("النخيل")
    screen.item_field.setText("أعلاف")
    screen.payment_combo.setCurrentText("آجل")
    screen.apply_filters()
    screen.reset_filters()
    assert screen.supplier_field.text() == ""
    assert screen.item_field.text() == ""
    assert screen.payment_combo.currentText() == "الكل"
    assert screen.table.rowCount() == 0
    assert screen.kpi_total["value"].text() == "—"
