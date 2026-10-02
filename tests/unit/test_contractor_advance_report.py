"""Tests for تقرير كشف حساب الدفعة المقدمة — النموذجان 7 و6 كتبويبين (headless Qt, no database).

The user's rules (2026-09-26):

* الأعمدة: تاريخ العقد، اسم الشركة، اسم المشروع، اسم المقاول، قيمة العقد، نسبة
  الدفعة المقدمة، قيمة الدفعة المقدمة من العقد، إجمالي المسدد من الدفعة
  المقدمة (من المستخلصات)، المتبقي.
* الضغط على عقد يعرض المستخلصات اللي سددت الدفعة المقدمة: التاريخ، رقم المستخلص،
  اسم المقاول، اسم المشروع، اسم الشركة، إجمالي المستخلص، نسبة وقيمة الدفعة المقدمة.
* فلتر الفترة على تاريخ العقد. زر «تحديد أعمدة الجدول».
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.services.contractor_advance_report_service import (
    ContractorAdvanceReportService,
    extract_lines,
    lines_totals,
)
from app.services.contractor_contracts_report_service import build_report
from app.ui.screens.contractor_advance_report_screen import (
    COLUMN_KEYS,
    LINE_KEYS,
    RED,
    REST_COLOR,
    ROW_CONTRACT,
    ROW_DETAIL,
    ROW_TOTAL,
    TAB_INLINE,
    TAB_POPUP,
    AdvanceBar,
    ContractorAdvanceReportScreen,
)


def _contract(contract_id, company_id, company, contractor_id, contractor, value, pct):
    return {"contract_id": contract_id, "contract_no": f"A-H/CT-{1000 + contract_id}",
            "contract_date": datetime.date(2026, contract_id, 10), "company_id": company_id,
            "company_name": company, "project_id": contract_id, "project_name": f"مشروع {contract_id}",
            "contractor_id": contractor_id, "contractor_name": contractor, "contract_value": Decimal(value),
            "advance_payment_pct": Decimal(pct)}


def _extract(extract_id, contract_id, date, works, pct):
    return {"extract_id": extract_id, "extract_no": f"A-H/CT-{1000 + contract_id}/EX-0{extract_id}",
            "extract_date": datetime.date(*date), "contract_id": contract_id, "works_value": Decimal(works),
            "vat_pct": Decimal("14"), "advance_payment_pct": Decimal(pct), "withholding_tax_pct": 1,
            "works_insurance_pct": 5, "social_insurance_pct": 0, "other_deductions": 0}


CONTRACTS = [
    _contract(1, 10, "الأفق للتطوير", 1, "م. أحمد عبد الرحمن", "2500000", "10"),   # advance 250,000
    _contract(2, 20, "الدلتا العقارية", 2, "البناء الحديث", "1900000", "10"),        # no extracts
    _contract(3, 10, "الأفق للتطوير", 1, "م. أحمد عبد الرحمن", "950000", "10"),     # over: 102,000 > 95,000
]
EXTRACTS = [
    _extract(2, 1, (2026, 3, 25), "380000", "10"),
    _extract(1, 1, (2026, 2, 15), "450000", "10"),
    _extract(3, 1, (2026, 5, 18), "620000", "10"),
    _extract(4, 3, (2026, 8, 5), "510000", "10"),
    _extract(5, 3, (2026, 9, 10), "510000", "10"),
]


def _lines(contract):
    return extract_lines(contract, [x for x in EXTRACTS if x["contract_id"] == contract["contract_id"]])


# -- the arithmetic ------------------------------------------------------------------------


def test_lines_are_oldest_first_and_carry_the_contracts_names():
    lines = _lines(CONTRACTS[0])
    assert [line["extract_date"] for line in lines] == [datetime.date(2026, 2, 15), datetime.date(2026, 3, 25),
                                                         datetime.date(2026, 5, 18)]
    assert [line["advance_payment"] for line in lines] == [Decimal("45000.00"), Decimal("38000.00"),
                                                           Decimal("62000.00")]
    assert lines[0]["contractor_name"] == "م. أحمد عبد الرحمن" and lines[0]["company_name"] == "الأفق للتطوير"
    assert lines[0]["works_value"] == Decimal("450000.00") and lines[0]["advance_payment_pct"] == Decimal("10")


def test_the_popup_total_equals_the_reports_paid_column():
    row = build_report(CONTRACTS[:1], EXTRACTS)[0]
    totals = lines_totals(_lines(CONTRACTS[0]))
    assert totals["advance_payment"] == row["advance_deducted"] == Decimal("145000.00")
    assert row["advance_agreed"] == Decimal("250000.00") and row["remaining_advance"] == Decimal("105000.00")
    assert totals["works_value"] == Decimal("1450000.00") and totals["count"] == 3


def test_contract_extracts_query():
    class Db:
        def fetch_all(self, query, params=None):
            self.query, self.params = query, params
            return [x for x in EXTRACTS if x["contract_id"] == 3]
    db = Db()
    lines = ContractorAdvanceReportService(db).contract_extracts(CONTRACTS[2])
    assert "WHERE contract_id = %s" in db.query and db.params == [3]
    assert len(lines) == 2 and lines[0]["project_name"] == "مشروع 3"


def test_bar_segments(qt_app):
    bar = AdvanceBar(Decimal("250000"), _lines(CONTRACTS[0]))
    segments = bar.segments()
    assert [round(width, 3) for _start, width, _color in segments] == [0.18, 0.152, 0.248, 0.42]
    assert segments[-1][2] == REST_COLOR
    over = AdvanceBar(Decimal("95000"), _lines(CONTRACTS[2])).segments()
    assert len(over) == 2 and REST_COLOR not in [color for *_x, color in over]  # nothing left to pay


# -- the screen ------------------------------------------------------------------------------


class FakeService:
    def __init__(self):
        self.last_filters = None
        self.extract_calls = 0

    def company_choices(self):
        return [{"company_id": 10, "company_code": "C10", "company_name": "الأفق للتطوير"},
                {"company_id": 20, "company_code": "C20", "company_name": "الدلتا العقارية"}]

    def project_choices(self, company_id=None):
        return []

    def contractor_choices(self):
        return [{"contractor_id": 1, "contractor_code": "D1", "contractor_name": "م. أحمد عبد الرحمن"}]

    def report(self, **filters):
        self.last_filters = filters
        contracts = [c for c in CONTRACTS if filters.get("company_id") in (None, c["company_id"])]
        return build_report(contracts, EXTRACTS)

    def contract_extracts(self, contract):
        self.extract_calls += 1
        return _lines(contract)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "report.ini"), QSettings.IniFormat)


@pytest.fixture
def screen(qt_app, settings):
    widget = ContractorAdvanceReportScreen(FakeService(), settings=settings)
    widget.resize(1700, 900)
    yield widget
    if widget.dialog is not None:
        widget.dialog.close()
    widget.close()


def _visible(table, offset=0):
    return [key for i, key in enumerate(COLUMN_KEYS) if not table.isColumnHidden(i + offset)]


def test_tabs_are_mockups_7_then_6(screen):
    assert screen.tabs.count() == 2
    assert "7" in screen.tabs.tabText(TAB_POPUP) and "6" in screen.tabs.tabText(TAB_INLINE)


def test_columns_are_the_users_in_order(screen):
    table = screen.popup_table
    headers = [table.horizontalHeaderItem(i).text().replace("\n", " ") for i in range(table.columnCount())]
    assert headers == ["تاريخ العقد", "اسم الشركة", "اسم المشروع", "اسم المقاول", "قيمة العقد",
                       "نسبة الدفعة المقدمة", "قيمة الدفعة المقدمة من العقد",
                       "إجمالي المسدد من الدفعة المقدمة", "المتبقي"]


def test_rows_and_totals(screen):
    table = screen.popup_table
    assert table.rowCount() == 4
    assert table.item(0, 0).text() == "2026-01-10"
    assert table.item(0, COLUMN_KEYS.index("advance_agreed")).text() == "250,000.00"
    assert table.item(0, COLUMN_KEYS.index("advance_deducted")).text() == "145,000.00"
    assert table.item(0, COLUMN_KEYS.index("remaining_advance")).text() == "105,000.00"
    over = table.item(2, COLUMN_KEYS.index("remaining_advance"))
    assert over.text() == "-7,000.00" and over.foreground().color().name().upper() == RED
    assert table.item(3, 0).text() == "الإجمالي — 3 عقود"
    assert table.item(3, COLUMN_KEYS.index("remaining_advance")).text() == "288,000.00"
    assert screen.count_label.text() == "عدد العقود: 3"


def test_the_four_total_cards(screen):
    titles = [screen.card_values[key].parent().findChildren(type(screen.count_label))[0].text()
              for key in screen.card_values]
    assert titles == ["إجمالي قيمة العقد", "إجمالي الدفعة المقدمة من العقد", "إجمالي المسدد من العقد",
                      "إجمالي المتبقي"]
    assert screen.card_values["contract_value"].text() == "5,350,000.00"
    assert screen.card_values["advance_agreed"].text() == "535,000.00"
    assert screen.card_values["advance_deducted"].text() == "247,000.00"
    assert screen.card_values["remaining_advance"].text() == "288,000.00"
    screen.company_combo.setCurrentIndex(screen.company_combo.findData(10))
    screen.run_report()  # contracts 1 and 3: 345,000 advanced − 247,000 paid
    assert screen.card_values["remaining_advance"].text() == "98,000.00"


def test_click_opens_the_statement_window(screen):
    screen._popup_clicked(0, 3)
    dialog = screen.dialog
    assert dialog is not None and dialog.isVisible()
    assert "A-H/CT-1001" in dialog.windowTitle()
    headers = [dialog.table.horizontalHeaderItem(i).text() for i in range(dialog.table.columnCount())]
    assert headers == ["التاريخ", "رقم المستخلص", "اسم المقاول", "اسم المشروع", "اسم الشركة",
                       "إجمالي المستخلص", "نسبة الدفعة المقدمة", "قيمة الدفعة المقدمة"]
    assert dialog.table.rowCount() == 4
    assert dialog.table.item(0, 1).text() == "A-H/CT-1001/EX-01"
    assert dialog.table.item(0, LINE_KEYS.index("advance_payment")).text() == "45,000.00"
    assert dialog.table.item(3, 0).text() == "إجمالي المسدد — 3 مستخلصات"
    assert dialog.table.item(3, LINE_KEYS.index("advance_payment")).text() == "145,000.00"
    assert dialog.summary_values["remaining_advance"].text() == "105,000.00"
    screen._popup_clicked(3, 0)  # the totals row opens nothing new
    assert screen.dialog is dialog


def test_contract_without_extracts(screen):
    dialog = screen.open_statement(screen.rows[1])
    assert dialog.table is None
    assert "المتبقي" in dialog.legend.text()


def test_inline_rows_open_and_close(screen):
    screen.tabs.setCurrentIndex(TAB_INLINE)
    table = screen.inline_table
    assert [kind for kind, _key in screen.inline_kinds] == [ROW_CONTRACT] * 3 + [ROW_TOTAL]
    assert table.item(0, 0).text() == "＋"
    screen._inline_clicked(0, 4)
    assert [kind for kind, _key in screen.inline_kinds] == [ROW_CONTRACT, ROW_DETAIL, ROW_CONTRACT,
                                                            ROW_CONTRACT, ROW_TOTAL]
    assert table.item(0, 0).text() == "－"
    detail = table.cellWidget(1, 0)
    assert detail.table.rowCount() == 4
    assert detail.table.item(1, 1).text() == "A-H/CT-1001/EX-02"
    assert table.rowHeight(1) == detail.wanted_height()
    screen._inline_clicked(1, 0)  # a click on the details does nothing
    assert len(screen.inline_kinds) == 5
    screen._inline_clicked(0, 0)
    assert len(screen.inline_kinds) == 4


def test_lines_are_fetched_once_per_run(screen):
    screen.open_statement(screen.rows[0])
    screen.toggle_contract(screen.rows[0]["contract_id"])
    assert screen.service.extract_calls == 1
    screen.run_report()
    screen.open_statement(screen.rows[0])
    assert screen.service.extract_calls == 2


def test_column_chooser_covers_both_tabs_and_is_saved(qt_app, settings):
    first = ContractorAdvanceReportScreen(FakeService(), settings=settings)
    assert list(first.chooser.boxes) == list(COLUMN_KEYS)
    assert first.columns_count.text() == "ظاهر 9 من 9 أعمدة"
    first.chooser.boxes["company_name"].setChecked(False)
    first.chooser.boxes["contract_value"].setChecked(False)
    assert _visible(first.popup_table) == _visible(first.inline_table, 1)
    assert "company_name" not in _visible(first.popup_table)
    assert not first.inline_table.isColumnHidden(0)  # the ＋/－ column always shows
    assert first.columns_count.text() == "ظاهر 7 من 9 أعمدة"
    # the totals label moves to the first visible text column
    assert first.popup_table.item(3, 0).text() == "الإجمالي — 3 عقود"
    first.set_visible_columns([k for k in COLUMN_KEYS if k != "contract_date"])
    assert first.popup_table.item(3, 1).text() == "الإجمالي — 3 عقود"
    first.close()
    second = ContractorAdvanceReportScreen(FakeService(), settings=settings)
    assert "contract_date" not in _visible(second.popup_table)
    second.chooser.default_button.click()
    assert _visible(second.popup_table) == list(COLUMN_KEYS)
    second.close()


def test_filters_run_on_the_contract_date(screen):
    assert screen.filters()["date_from"] is None  # «كل الفترات» by default
    screen.all_dates.setChecked(False)
    screen.company_combo.setCurrentIndex(screen.company_combo.findData(20))
    screen.run_report()
    assert isinstance(screen.service.last_filters["date_from"], datetime.date)
    assert screen.popup_table.rowCount() == 2
    assert screen.inline_table.rowCount() == 2
