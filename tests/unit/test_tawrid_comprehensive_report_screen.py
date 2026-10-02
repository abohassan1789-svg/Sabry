"""Widget tests for شاشة التقرير الشامل — قسم التوريدات (headless Qt, no DB).

Slate accent, five optional filters, a wide three-layer table and five totals
cards (no donut, unlike the statements). These pin:

* the five totals cards exist and the table carries the three price layers;
* «عرض» with no filters still runs (all filters optional) and fills the cards,
  the totals strip and the table;
* the five filters flow into the service's ReportFilters (party pickers + item
  combo + dates);
* «مسح» clears everything; export/print refuse before the report has been shown.
"""

from __future__ import annotations

import os
from datetime import date as _date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.tawrid_comprehensive_report_service import (
    REPORT_COLUMNS,
    ReportFilters,
    ReportResult,
    ReportRow,
    ReportTotals,
    TawridComprehensiveReportService,
)
from app.ui.screens.tawrid_comprehensive_report_screen import (
    TawridComprehensiveReportScreen,
    _money,
    _vol,
)


def _rows() -> list[ReportRow]:
    return [
        ReportRow(
            serial=1, date="2025-01-04", item="سن 2",
            price_cus=Decimal("310"), cus_volume=Decimal("61"), total_cus=Decimal("18910"),
            price_man=Decimal("140"), total_man=Decimal("8540"),
            price_res=Decimal("145"), res_volume=Decimal("59"), total_res=Decimal("8555"),
            receipt_no="185500", supplier="الهدي", customer="عصام", trailer="3581",
        ),
        ReportRow(
            serial=2, date="2025-01-05", item="سن 1",
            price_cus=Decimal("300"), cus_volume=Decimal("60"), total_cus=Decimal("18000"),
            price_man=Decimal("130"), total_man=Decimal("7800"),
            price_res=Decimal("150"), res_volume=Decimal("58"), total_res=Decimal("8700"),
            receipt_no="", supplier="— محذوف —", customer="عصام", trailer="",
        ),
    ]


def _result(filters: ReportFilters | None = None) -> ReportResult:
    rows = _rows()
    totals = ReportTotals(
        total_cus=Decimal("36910"), total_man=Decimal("16340"), total_res=Decimal("17255"),
        cus_volume=Decimal("121"), res_volume=Decimal("117"), count=2,
    )
    return ReportResult(rows=rows, totals=totals, filters=filters or ReportFilters(),
                        columns=REPORT_COLUMNS)


class FakeService:
    columns = REPORT_COLUMNS

    def __init__(self):
        self.built_with: ReportFilters | None = None

    def distinct_items(self):
        return ["سن 1", "سن 2"]

    def supplier_picker_rows(self):
        return [{"supplier_id": 1, "supplier_code": 10, "supplier_name": "الهدي", "is_active": True}]

    def customer_picker_rows(self):
        return [{"customer_id": 2, "customer_code": 20, "customer_name": "عصام", "is_active": True}]

    def tractor_picker_rows(self):
        return [{"tractor_id": 3, "driver_name": "سائق", "head_no": "1", "trailer_no": "3581", "is_active": True}]

    def build(self, filters=None):
        self.built_with = filters or ReportFilters()
        return _result(self.built_with)

    export_rows = TawridComprehensiveReportService.export_rows
    _money = staticmethod(TawridComprehensiveReportService._money)
    _vol = staticmethod(TawridComprehensiveReportService._vol)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app):
    return TawridComprehensiveReportScreen(service=FakeService())


# --- layout ------------------------------------------------------------------

def test_the_five_totals_cards_exist_and_no_donut(screen):
    assert set(screen.cards) == {"total_cus", "total_man", "total_res", "cus_volume", "res_volume"}
    assert not hasattr(screen, "donut")


def test_the_table_has_the_three_price_layers(screen):
    keys = [c.key for c in screen.columns]
    for k in ("price_cus", "total_cus", "price_man", "total_man", "price_res", "total_res",
              "cus_volume", "res_volume", "supplier", "customer", "trailer", "item"):
        assert k in keys


def test_the_item_combo_starts_with_all_then_distinct(screen):
    assert screen.item_combo.count() == 3  # «كل الأصناف» + 2
    assert screen.item_combo.itemData(0) is None
    assert screen.item_combo.itemData(1) == "سن 1"


def test_it_starts_empty_with_a_prompt(screen):
    assert screen.empty_label.isVisibleTo(screen)
    assert screen.table.rowCount() == 0


# --- showing the report ------------------------------------------------------

def test_show_with_no_filters_runs_and_fills(screen):
    screen.show_report()
    assert screen.table.rowCount() == 2
    assert screen.cards["total_cus"].text() == "36,910.00"
    assert screen.cards["total_man"].text() == "16,340.00"
    assert screen.cards["total_res"].text() == "17,255.00"
    assert screen.cards["cus_volume"].text() == "121"
    assert screen.cards["res_volume"].text() == "117"
    assert screen.count_label.text() == "عدد البونات: 2"
    assert screen.total_cus_label.text() == "ت.العميل: 36,910.00"
    # The date filters now DEFAULT to today (per user request — no 1-1-1900); the
    # other four filters are still optional and stay unset.
    today = _date.today().isoformat()
    f = screen.service.built_with
    assert f.date_from == today and f.date_to == today
    assert f.supplier_id is None and f.customer_id is None
    assert f.tractor_id is None and f.item_name is None


def test_the_five_filters_flow_into_the_service(screen):
    screen.selected_supplier = {"supplier_id": 1, "supplier_name": "الهدي"}
    screen.selected_customer = {"customer_id": 2, "customer_name": "عصام"}
    screen.selected_tractor = {"tractor_id": 3, "tractor_name": "سائق", "trailer_no": "3581"}
    screen.item_combo.setCurrentIndex(2)  # سن 2
    screen.from_date.setDate(screen.from_date.date().fromString("2026-01-01", "yyyy-MM-dd"))
    screen.to_date.setDate(screen.to_date.date().fromString("2026-06-30", "yyyy-MM-dd"))
    screen.show_report()
    f = screen.service.built_with
    assert f.supplier_id == 1 and f.customer_id == 2 and f.tractor_id == 3
    assert f.item_name == "سن 2"
    assert f.date_from == "2026-01-01" and f.date_to == "2026-06-30"


def test_table_cell_shows_a_layer_value(screen):
    screen.show_report()
    labels = [c.label for c in screen.columns]
    idx = labels.index("تكلفة المورد")
    assert screen.table.item(0, idx).text() == "8,555.00"


def test_reset_clears_everything(screen):
    screen.selected_customer = {"customer_id": 2, "customer_name": "عصام"}
    screen.show_report()
    screen.reset_filters()
    assert screen.selected_customer is None
    assert screen.current_result is None
    assert screen.customer_label.text() == "— الكل —"
    assert screen.item_combo.currentIndex() == 0
    assert screen.cards["total_cus"].text() == "—"
    assert screen.table.rowCount() == 0


def test_export_refuses_before_a_run(screen, monkeypatch):
    warned = {}
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.setdefault("w", a))
    screen.export_excel()
    assert "w" in warned


def test_money_and_vol_helpers():
    assert _money(Decimal("-11125")) == "11,125.00-"
    assert _money(1234.5) == "1,234.50"
    assert _vol(Decimal("61.000")) == "61"
    assert _vol(Decimal("0")) == "0"
