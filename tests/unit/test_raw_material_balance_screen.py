"""Screen-level tests for the Raw-Material Warehouse (مخزن مواد الخام), Model 2.

Offscreen Qt with a fake service (no database): they pin that the screen builds
in the chosen Model-2 shape (eight columns, four KPI cards, filter bar with an
item-name field + locked type chip — no date filter), that running the report
fills the table + KPI cards, that reset clears everything, and that the item-name
filter flows into the request.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from decimal import Decimal

from PySide6.QtWidgets import QApplication

from app.services.raw_material_balance_service import (
    REPORT_COLUMNS,
    RawMaterialBalanceRequest,
    RawMaterialBalanceResult,
)
from app.ui.screens.raw_material_balance_screen import RawMaterialBalanceScreen


def _app():
    return QApplication.instance() or QApplication([])


def _result(rows):
    numeric = []
    export = []
    total_purchased = Decimal("0")
    total_issued = Decimal("0")
    total_balance = Decimal("0")
    for r in rows:
        opening = Decimal(str(r["opening_balance"]))
        purchased = Decimal(str(r["purchased"]))
        issued = Decimal(str(r["issued"]))
        balance = opening + purchased - issued
        status = "جيد" if balance > 100 else ("منخفض" if balance > 0 else "بدون رصيد")
        total_purchased += purchased
        total_issued += issued
        total_balance += balance
        numeric.append({**r, "balance": balance, "status": status})
        export.append({
            "item_code": str(r["item_code"]), "item_name": r["item_name"],
            "unit": r["unit"], "opening_balance": str(opening),
            "purchased": str(purchased), "issued": str(issued),
            "balance": str(balance), "status": status,
        })
    summary = {
        "item_count": len(rows), "item_count_label": str(len(rows)),
        "total_opening": Decimal("0"), "total_opening_label": "0",
        "total_purchased": total_purchased, "total_purchased_label": f"{int(total_purchased):,}",
        "total_issued": total_issued, "total_issued_label": f"{int(total_issued):,}",
        "total_balance": total_balance, "total_balance_label": f"{int(total_balance):,}",
    }
    return RawMaterialBalanceResult(
        columns=list(REPORT_COLUMNS),
        rows=numeric,
        export_rows=export,
        summary=summary,
        is_empty=not rows,
    )


class _FakeService:
    def __init__(self, rows):
        self.columns = list(REPORT_COLUMNS)
        self._rows = rows
        self.last_request: RawMaterialBalanceRequest | None = None

    def fetch_report(self, request: RawMaterialBalanceRequest) -> RawMaterialBalanceResult:
        self.last_request = request
        return _result(self._rows)

    def search_items(self, keyword="", limit=500):
        return [{"item_code": 1001, "item_name": "بتروميل", "unit": "كيس"}]


_SAMPLE = [
    {"item_code": 1001, "item_name": "بتروميل", "unit": "كيس",
     "opening_balance": "500", "purchased": "1200", "issued": "900"},
    {"item_code": 1005, "item_name": "حديد تسليح", "unit": "طن",
     "opening_balance": "15", "purchased": "90", "issued": "88"},
]


def test_screen_builds_with_eight_columns_in_order():
    _app()
    screen = RawMaterialBalanceScreen(service=_FakeService(_SAMPLE))
    assert screen.table.columnCount() == 8
    labels = [screen.table.horizontalHeaderItem(i).text() for i in range(8)]
    assert labels == [
        "رقم الصنف", "اسم الصنف", "الوحدة", "رصيد أول المدة",
        "المشتريات", "المصروف الفعلي", "الرصيد الحالي", "الحالة",
    ]


def test_apply_filters_fills_table_and_kpis():
    _app()
    screen = RawMaterialBalanceScreen(service=_FakeService(_SAMPLE))
    screen.apply_filters()
    assert screen.table.rowCount() == 2
    assert screen.kpi_count["value"].text() == "2"
    assert "1,290" in screen.kpi_purchased["value"].text()   # 1200 + 90
    assert "988" in screen.kpi_issued["value"].text()          # 900 + 88
    assert "817" in screen.kpi_balance["value"].text()         # 800 + 17


def test_empty_result_shows_empty_state():
    _app()
    screen = RawMaterialBalanceScreen(service=_FakeService([]))
    screen.apply_filters()
    assert screen.table.rowCount() == 0
    assert not screen.empty_label.isHidden()
    assert screen.table.isHidden()


def test_request_carries_item_name():
    _app()
    service = _FakeService(_SAMPLE)
    screen = RawMaterialBalanceScreen(service=service)
    screen.item_field.setText("زلط")
    screen.apply_filters()
    assert service.last_request.item_name == "زلط"


def test_screen_has_no_date_filters():
    _app()
    screen = RawMaterialBalanceScreen(service=_FakeService(_SAMPLE))
    assert not hasattr(screen, "from_date")
    assert not hasattr(screen, "to_date")


def test_item_field_is_a_double_click_picker():
    _app()
    screen = RawMaterialBalanceScreen(service=_FakeService(_SAMPLE))
    assert hasattr(screen.item_field, "doubleClicked")
    screen.item_field.setText("بتروميل")
    screen.apply_filters()
    assert screen.service.last_request.item_name == "بتروميل"


def test_reset_clears_table_filters_and_kpis():
    _app()
    screen = RawMaterialBalanceScreen(service=_FakeService(_SAMPLE))
    screen.item_field.setText("زلط")
    screen.apply_filters()
    screen.reset_filters()
    assert screen.item_field.text() == ""
    assert screen.table.rowCount() == 0
    assert screen.kpi_count["value"].text() == "—"
    assert screen.kpi_balance["value"].text() == "—"
