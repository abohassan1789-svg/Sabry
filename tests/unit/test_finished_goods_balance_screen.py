"""Screen-level tests for the Finished-Goods Warehouse (مخزن الإنتاج التام), Model 2.

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

from app.services.finished_goods_balance_service import (
    REPORT_COLUMNS,
    FinishedGoodsBalanceRequest,
    FinishedGoodsBalanceResult,
)
from app.ui.screens.finished_goods_balance_screen import FinishedGoodsBalanceScreen


def _app():
    return QApplication.instance() or QApplication([])


def _result(rows):
    numeric = []
    export = []
    total_produced = Decimal("0")
    total_sold = Decimal("0")
    total_balance = Decimal("0")
    for r in rows:
        opening = Decimal(str(r["opening_balance"]))
        produced = Decimal(str(r["produced"]))
        sold = Decimal(str(r["sold"]))
        balance = opening + produced - sold
        status = "جيد" if balance > 100 else ("منخفض" if balance > 0 else "بدون رصيد")
        total_produced += produced
        total_sold += sold
        total_balance += balance
        numeric.append({**r, "balance": balance, "status": status})
        export.append({
            "item_code": str(r["item_code"]), "item_name": r["item_name"],
            "unit": r["unit"], "opening_balance": str(opening),
            "produced": str(produced), "sold": str(sold),
            "balance": str(balance), "status": status,
        })
    summary = {
        "item_count": len(rows), "item_count_label": str(len(rows)),
        "total_opening": Decimal("0"), "total_opening_label": "0",
        "total_produced": total_produced, "total_produced_label": f"{int(total_produced):,}",
        "total_sold": total_sold, "total_sold_label": f"{int(total_sold):,}",
        "total_balance": total_balance, "total_balance_label": f"{int(total_balance):,}",
    }
    return FinishedGoodsBalanceResult(
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
        self.last_request: FinishedGoodsBalanceRequest | None = None

    def fetch_report(self, request: FinishedGoodsBalanceRequest) -> FinishedGoodsBalanceResult:
        self.last_request = request
        return _result(self._rows)

    def search_items(self, keyword="", limit=500):
        return [{"item_code": 2001, "item_name": "خرسانة", "unit": "م³"}]


_SAMPLE = [
    {"item_code": 2001, "item_name": "خرسانة", "unit": "م³",
     "opening_balance": "100", "produced": "500", "sold": "450"},
    {"item_code": 2002, "item_name": "بلوك", "unit": "قطعة",
     "opening_balance": "20", "produced": "1000", "sold": "1005"},
]


def test_screen_builds_with_eight_columns_in_order():
    _app()
    screen = FinishedGoodsBalanceScreen(service=_FakeService(_SAMPLE))
    assert screen.table.columnCount() == 8
    labels = [screen.table.horizontalHeaderItem(i).text() for i in range(8)]
    assert labels == [
        "رقم الصنف", "اسم الصنف", "الوحدة", "رصيد أول المدة",
        "الكميات المنتجة", "المبيعات", "الرصيد الحالي", "الحالة",
    ]


def test_apply_filters_fills_table_and_kpis():
    _app()
    screen = FinishedGoodsBalanceScreen(service=_FakeService(_SAMPLE))
    screen.apply_filters()
    assert screen.table.rowCount() == 2
    assert screen.kpi_count["value"].text() == "2"
    assert "1,500" in screen.kpi_produced["value"].text()   # 500 + 1000
    assert "1,455" in screen.kpi_sold["value"].text()         # 450 + 1005
    assert "165" in screen.kpi_balance["value"].text()         # 150 + 15


def test_empty_result_shows_empty_state():
    _app()
    screen = FinishedGoodsBalanceScreen(service=_FakeService([]))
    screen.apply_filters()
    assert screen.table.rowCount() == 0
    assert not screen.empty_label.isHidden()
    assert screen.table.isHidden()


def test_request_carries_item_name():
    _app()
    service = _FakeService(_SAMPLE)
    screen = FinishedGoodsBalanceScreen(service=service)
    screen.item_field.setText("خرسانة")
    screen.apply_filters()
    assert service.last_request.item_name == "خرسانة"


def test_screen_has_no_date_filters():
    _app()
    screen = FinishedGoodsBalanceScreen(service=_FakeService(_SAMPLE))
    assert not hasattr(screen, "from_date")
    assert not hasattr(screen, "to_date")


def test_item_field_is_a_double_click_picker():
    _app()
    screen = FinishedGoodsBalanceScreen(service=_FakeService(_SAMPLE))
    assert hasattr(screen.item_field, "doubleClicked")
    screen.item_field.setText("بلوك")
    screen.apply_filters()
    assert screen.service.last_request.item_name == "بلوك"


def test_reset_clears_table_filters_and_kpis():
    _app()
    screen = FinishedGoodsBalanceScreen(service=_FakeService(_SAMPLE))
    screen.item_field.setText("خرسانة")
    screen.apply_filters()
    screen.reset_filters()
    assert screen.item_field.text() == ""
    assert screen.table.rowCount() == 0
    assert screen.kpi_count["value"].text() == "—"
    assert screen.kpi_balance["value"].text() == "—"
