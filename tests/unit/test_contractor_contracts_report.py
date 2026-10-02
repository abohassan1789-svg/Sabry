"""Tests for تقرير عقود المقاولين — النموذجان 7 و5 كتبويبين (headless Qt, no database).

The user's rules (confirmed 2026-09-26):

* الأعمدة: تاريخ العقد، اسم الشركة، اسم المشروع، اسم المقاول، قيمة العقد، نسبة
  الدفعة المقدمة، إجمالي المستخلصات، إجمالي المقدمة المستقطعة، المتبقي من قيمة
  العقد، المتبقي من الدفعة المقدمة.
* المتبقي من قيمة العقد = قيمة العقد − إجمالي المستخلصات.
* المتبقي من المقدمة = قيمة العقد × نسبة المقدمة − المستقطعة من المستخلصات.
* لو المستخلصات عدّت العقد، المتبقي بالسالب وبالأحمر.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from app.services.contractor_contracts_report_service import (
    STATUS_DONE,
    STATUS_NOT_STARTED,
    STATUS_OVER,
    STATUS_RUNNING,
    ContractorContractsReportService,
    build_report,
    report_row,
    report_totals,
)
from app.ui.screens.contractor_contracts_report_screen import (
    BAND_KEYS,
    P_REMAINING_ADVANCE,
    P_REMAINING_VALUE,
    P_STATUS,
    PROGRESS_HEADERS,
    RED,
    TAB_BANDS,
    TAB_PROGRESS,
    ContractorContractsReportScreen,
)


def _contract(contract_id, date, company_id, company, project_id, project, contractor_id, contractor, value, pct):
    return {"contract_id": contract_id, "contract_no": f"A-H/CT-{1000 + contract_id}",
            "contract_date": datetime.date(*date), "company_id": company_id, "company_name": company,
            "project_id": project_id, "project_name": project, "contractor_id": contractor_id,
            "contractor_name": contractor, "contract_value": Decimal(value), "advance_payment_pct": Decimal(pct)}


def _extract(contract_id, works, pct):
    return {"contract_id": contract_id, "works_value": Decimal(works), "vat_pct": Decimal("14"),
            "advance_payment_pct": Decimal(pct), "withholding_tax_pct": 0, "works_insurance_pct": 5,
            "social_insurance_pct": 0, "other_deductions": 0}


CONTRACTS = [
    _contract(1, (2026, 1, 12), 10, "الأفق للتطوير", 11, "برج الأفق", 1, "م. أحمد عبد الرحمن", "2500000", "10"),
    _contract(2, (2026, 3, 15), 20, "الدلتا العقارية", 21, "كمبوند الياسمين", 2, "م. محمود السيد", "1150000", "5"),
    _contract(3, (2026, 5, 10), 20, "الدلتا العقارية", 22, "مول الدلتا", 3, "الصفا للكهرباء", "1900000", "10"),
    _contract(4, (2026, 7, 1), 10, "الأفق للتطوير", 12, "فيلات الأفق", 1, "م. أحمد عبد الرحمن", "950000", "10"),
]
EXTRACTS = [
    _extract(1, "800000", "10"), _extract(1, "650000", "10"),   # 1,450,000 → 145,000
    _extract(2, "1150000", "5"),                                # مكتمل
    # contract 3: no extracts (لم يبدأ)
    _extract(4, "600000", "10"), _extract(4, "420000", "10"),   # 1,020,000 > 950,000
]


# -- the arithmetic ------------------------------------------------------------------------


def test_row_follows_the_users_formulas():
    row = report_row(CONTRACTS[0], EXTRACTS[:2])
    assert row["extracts_total"] == Decimal("1450000.00")
    assert row["advance_deducted"] == Decimal("145000.00")
    assert row["advance_agreed"] == Decimal("250000.00")
    assert row["remaining_value"] == Decimal("1050000.00")      # 2,500,000 − 1,450,000
    assert row["remaining_advance"] == Decimal("105000.00")     # 250,000 − 145,000
    assert row["executed_pct"] == Decimal("58")
    assert row["status"] == STATUS_RUNNING


def test_deduction_uses_each_extracts_own_rate():
    """The deducted advance is the extracts screen's «الدفعة المقدمة» line, not the contract's rate."""
    row = report_row(CONTRACTS[0], [_extract(1, "100000", "12")])
    assert row["advance_deducted"] == Decimal("12000.00")


def test_over_executed_contract_goes_negative_and_is_not_clamped():
    row = report_row(CONTRACTS[3], EXTRACTS[3:])
    assert row["remaining_value"] == Decimal("-70000.00")
    assert row["remaining_advance"] == Decimal("-7000.00")      # 95,000 − 102,000
    assert row["status"] == STATUS_OVER


def test_statuses():
    rows = build_report(CONTRACTS, EXTRACTS)
    assert [r["status"] for r in rows] == [STATUS_RUNNING, STATUS_DONE, STATUS_NOT_STARTED, STATUS_OVER]
    assert rows[2]["extracts_total"] == 0 and rows[2]["remaining_advance"] == Decimal("190000.00")


def test_totals():
    totals = report_totals(build_report(CONTRACTS, EXTRACTS))
    assert totals["count"] == 4
    assert totals["contract_value"] == Decimal("6500000.00")
    assert totals["extracts_total"] == Decimal("3620000.00")
    assert totals["remaining_value"] == Decimal("2880000.00")
    assert totals["advance_agreed"] == Decimal("592500.00")
    assert totals["advance_deducted"] == Decimal("304500.00")
    assert totals["remaining_advance"] == Decimal("288000.00")


def test_empty_totals_do_not_divide_by_zero():
    totals = report_totals([])
    assert totals["count"] == 0 and totals["executed_pct"] == 0 and totals["recovered_pct"] == 0


# -- the SQL filters -----------------------------------------------------------------------------


class _RecordingDb:
    def __init__(self, contracts):
        self.calls = []
        self.contracts = contracts

    def fetch_all(self, query, params=None):
        self.calls.append((query, list(params or [])))
        return self.contracts if "FROM contractor_contracts" in query else []


def test_filters_reach_the_query():
    db = _RecordingDb(CONTRACTS[:1])
    rows = ContractorContractsReportService(db).report(
        date_from=datetime.date(2026, 1, 1), date_to=None, company_id=10, project_id=None, contractor_id=1)
    query, params = db.calls[0]
    assert "k.contract_date >= %s" in query and "p.company_id = %s" in query and "k.contractor_id = %s" in query
    assert "k.contract_date <= %s" not in query and "k.project_id = %s" not in query
    assert params == [datetime.date(2026, 1, 1), 10, 1]
    assert db.calls[1][1] == [[1]]  # the extracts of the found contracts only
    assert rows[0]["status"] == STATUS_NOT_STARTED


def test_no_contracts_skips_the_extracts_query():
    db = _RecordingDb([])
    assert ContractorContractsReportService(db).report() == []
    assert len(db.calls) == 1


# -- the screen ------------------------------------------------------------------------------------


class FakeService:
    def __init__(self):
        self.last_filters = None

    def company_choices(self):
        return [{"company_id": 10, "company_code": "A-H/CO-1001", "company_name": "الأفق للتطوير"},
                {"company_id": 20, "company_code": "A-H/CO-1002", "company_name": "الدلتا العقارية"}]

    def project_choices(self, company_id=None):
        projects = [{"project_id": 11, "project_code": "P11", "project_name": "برج الأفق", "company_id": 10},
                    {"project_id": 12, "project_code": "P12", "project_name": "فيلات الأفق", "company_id": 10},
                    {"project_id": 21, "project_code": "P21", "project_name": "كمبوند الياسمين", "company_id": 20}]
        return [p for p in projects if company_id in (None, p["company_id"])]

    def contractor_choices(self):
        return [{"contractor_id": 1, "contractor_code": "C1", "contractor_name": "م. أحمد عبد الرحمن"}]

    def report(self, **filters):
        self.last_filters = filters
        contracts = [c for c in CONTRACTS
                     if filters.get("company_id") in (None, c["company_id"])
                     and filters.get("contractor_id") in (None, c["contractor_id"])]
        return build_report(contracts, EXTRACTS)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app):
    widget = ContractorContractsReportScreen(FakeService())
    widget.resize(1700, 900)
    yield widget
    widget.close()


def test_tabs_are_mockups_7_then_5(screen):
    assert screen.tabs.count() == 2
    assert "7" in screen.tabs.tabText(TAB_PROGRESS) and "5" in screen.tabs.tabText(TAB_BANDS)


def test_progress_tab_has_the_users_columns_in_order(screen):
    headers = [screen.progress_table.horizontalHeaderItem(i).text().replace("\n", " ")
               for i in range(screen.progress_table.columnCount())]
    assert headers == [h.replace("\n", " ") for h in PROGRESS_HEADERS]
    assert headers[:10] == ["تاريخ العقد", "اسم الشركة", "اسم المشروع", "اسم المقاول", "قيمة العقد",
                            "نسبة الدفعة المقدمة", "إجمالي المستخلصات", "إجمالي المقدمة المستقطعة",
                            "المتبقي من قيمة العقد", "المتبقي من الدفعة المقدمة"]


def test_progress_rows_and_totals(screen):
    table = screen.progress_table
    assert table.rowCount() == 5  # 4 contracts + الإجمالي
    assert table.item(0, 0).text() == "2026-01-12"
    assert table.item(0, 4).text() == "2,500,000.00"
    assert table.item(0, 5).text() == "10%"
    assert table.item(0, 7).text() == "145,000.00"
    cell = table.cellWidget(0, P_REMAINING_VALUE)
    assert cell.value_label.text() == "1,050,000.00" and cell.bar.value() == 58
    assert table.cellWidget(0, P_REMAINING_ADVANCE).value_label.text() == "105,000.00"
    assert table.item(3, P_STATUS).text() == STATUS_OVER
    total = table.rowCount() - 1
    assert "الإجمالي" in table.item(total, 0).text()
    assert table.item(total, 4).text() == "6,500,000.00"
    assert table.cellWidget(total, P_REMAINING_ADVANCE).value_label.text() == "288,000.00"
    assert screen.progress_count.text() == "عدد العقود: 4"


def test_negative_remainders_are_red(screen):
    over = screen.progress_table.cellWidget(3, P_REMAINING_VALUE)
    assert over.value_label.text() == "-70,000.00" and RED in over.value_label.styleSheet()
    assert over.bar.value() == 100  # the bar is capped; the red colour tells it passed
    column = BAND_KEYS.index("remaining_advance")
    item = screen.band_table.item(3, column)
    assert item.text() == "-7,000.00" and item.foreground().color().name().upper() == RED


def test_bands_tab_adds_the_agreed_advance(screen):
    table = screen.band_table
    assert table.rowCount() == 5
    assert [label.text() for label in screen.band_header.labels] == ["بيانات العقد", "القيمة والتنفيذ", "الدفعة المقدمة"]
    assert table.item(0, BAND_KEYS.index("advance_agreed")).text() == "250,000.00"
    assert table.item(4, BAND_KEYS.index("advance_agreed")).text() == "592,500.00"


def _band_edges(screen):
    """Each band title's (left, right) on screen, and its columns' (left, right)."""
    header = screen.band_table.horizontalHeader()
    viewport = header.viewport()
    titles, columns, start = [], [], 0
    for label, count in zip(screen.band_header.labels, (4, 3, 4)):
        left = label.mapToGlobal(QPoint(0, 0)).x()
        titles.append((left, left + label.width()))
        xs = [viewport.mapToGlobal(QPoint(header.sectionViewportPosition(i), 0)).x() for i in range(start, start + count)]
        ends = [x + header.sectionSize(i) for x, i in zip(xs, range(start, start + count))]
        columns.append((min(xs), max(ends)))
        start += count
    return titles, columns


def test_band_titles_sit_exactly_over_their_columns(screen):
    screen.tabs.setCurrentIndex(TAB_BANDS)
    screen.show()
    QApplication.processEvents()
    titles, columns = _band_edges(screen)
    assert titles == columns
    # right-to-left: بيانات العقد on the right, الدفعة المقدمة on the left
    assert titles[0][0] > titles[1][0] > titles[2][0]


def test_running_the_report_again_does_not_move_anything(screen):
    """The user's bug: every «عرض التقرير» on نموذج 5 pushed the report sideways."""
    screen.tabs.setCurrentIndex(TAB_BANDS)
    screen.show()
    QApplication.processEvents()
    before = (screen.width(), screen.band_table.width(), _band_edges(screen))
    screen.company_combo.setCurrentIndex(screen.company_combo.findData(20))
    for _ in range(4):
        screen.show_button.click()
        QApplication.processEvents()
    assert screen.width() == before[0] and screen.band_table.width() == before[1]
    titles, columns = _band_edges(screen)
    assert titles == columns
    screen.company_combo.setCurrentIndex(0)
    screen.show_button.click()
    QApplication.processEvents()
    assert _band_edges(screen) == before[2]


def test_filters(screen):
    assert screen.filters()["date_from"] is None  # «كل الفترات» by default
    screen.company_combo.setCurrentIndex(screen.company_combo.findData(20))
    assert [screen.project_combo.itemText(i) for i in range(screen.project_combo.count())] == ["الكل", "كمبوند الياسمين"]
    screen.all_dates.setChecked(False)
    assert screen.date_from.isEnabled()
    screen.run_report()
    assert screen.service.last_filters["company_id"] == 20
    assert isinstance(screen.service.last_filters["date_from"], datetime.date)
    assert screen.progress_table.rowCount() == 3  # 2 contracts + الإجمالي
    assert screen.bands_count.text() == "عدد العقود: 2"


def test_rerun_with_fewer_rows_leaves_no_stale_widgets(screen):
    screen.contractor_combo.setCurrentIndex(screen.contractor_combo.findData(1))
    screen.run_report()
    table = screen.progress_table
    assert table.rowCount() == 3
    assert "الإجمالي" in table.item(2, 0).text()
    assert table.cellWidget(2, P_REMAINING_VALUE).value_label.text() == "980,000.00"
    # the totals row must not keep a data row's rate or status from the longer run before
    assert table.item(2, 5).text() == "" and table.item(2, P_STATUS).text() == ""
    bands = screen.band_table
    assert bands.item(2, BAND_KEYS.index("advance_payment_pct")).text() == ""
