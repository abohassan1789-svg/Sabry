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
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.services.contractor_contract_service import contract_label
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
    PROGRESS_KEYS,
    RED,
    BANDS,
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
    {**_contract(1, (2026, 1, 12), 10, "الأفق للتطوير", 11, "برج الأفق", 1, "م. أحمد عبد الرحمن", "2500000", "10"),
     "contract_name": "أعمال الخرسانة"},
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
        self.contract_calls = []

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

    def contract_choices(self, company_id=None, project_id=None, contractor_id=None):
        self.contract_calls.append((company_id, project_id, contractor_id))
        return [{"contract_id": c["contract_id"], "contract_label": contract_label(c)} for c in CONTRACTS
                if company_id in (None, c["company_id"]) and contractor_id in (None, c["contractor_id"])]

    def report(self, **filters):
        self.last_filters = filters
        contracts = [c for c in CONTRACTS
                     if filters.get("company_id") in (None, c["company_id"])
                     and filters.get("contractor_id") in (None, c["contractor_id"])
                     and filters.get("contract_id") in (None, c["contract_id"])]
        return build_report(contracts, EXTRACTS)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "report.ini"), QSettings.IniFormat)


@pytest.fixture
def screen(qt_app, settings):
    widget = ContractorContractsReportScreen(FakeService(), settings=settings)
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
    assert headers[:12] == ["العقد", "تاريخ العقد", "اسم الشركة", "اسم المشروع", "اسم المقاول", "قيمة العقد",
                            "نسبة الدفعة المقدمة", "إجمالي المستخلصات", "إجمالي المقدمة المستقطعة",
                            "المصروف من الدفعات المقدمة", "المتبقي من قيمة العقد", "المتبقي من الدفعة المقدمة"]


def test_progress_rows_and_totals(screen):
    table = screen.progress_table
    assert table.rowCount() == 5  # 4 contracts + الإجمالي
    column = PROGRESS_KEYS.index
    assert table.item(0, column("contract_date")).text() == "2026-01-12"
    assert table.item(0, column("contract_value")).text() == "2,500,000.00"
    assert table.item(0, column("advance_payment_pct")).text() == "10%"
    assert table.item(0, column("advance_deducted")).text() == "145,000.00"
    cell = table.cellWidget(0, P_REMAINING_VALUE)
    assert cell.value_label.text() == "1,050,000.00" and cell.bar.value() == 58
    assert table.cellWidget(0, P_REMAINING_ADVANCE).value_label.text() == "105,000.00"
    assert table.item(3, P_STATUS).text() == STATUS_OVER
    total = table.rowCount() - 1
    assert "الإجمالي" in table.item(total, 0).text()
    assert table.item(total, column("contract_value")).text() == "6,500,000.00"
    assert table.cellWidget(total, P_REMAINING_ADVANCE).value_label.text() == "288,000.00"
    assert screen.progress_count.text() == "عدد العقود: 4"


def test_contract_column_is_number_and_name(screen):
    """«العقد» (2026-10-13): «رقم — اسم», the number alone when the contract has no name."""
    for table, keys in ((screen.progress_table, PROGRESS_KEYS), (screen.band_table, BAND_KEYS)):
        column = keys.index("contract_label")
        assert column == 0 and table.horizontalHeaderItem(column).text() == "العقد"
        assert table.item(0, column).text() == "A-H/CT-1001 — أعمال الخرسانة"
        assert table.item(1, column).text() == "A-H/CT-1002"


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
    for label, count in zip(screen.band_header.labels, [len(columns) for _t, _c, columns in BANDS]):
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
    assert table.item(2, PROGRESS_KEYS.index("advance_payment_pct")).text() == ""
    assert table.item(2, P_STATUS).text() == ""
    bands = screen.band_table
    assert bands.item(2, BAND_KEYS.index("advance_payment_pct")).text() == ""


# --- دفعات مقدمة from شاشة الدفعات (user, 2026-10-13) -----------------------------------------

from app.services.contractor_contracts_report_service import allocate_advance_payments  # noqa: E402


def _k(contract_id, contractor_id, project_id, value, pct):
    return {"contract_id": contract_id, "contractor_id": contractor_id, "project_id": project_id,
            "contract_value": Decimal(value), "advance_payment_pct": Decimal(pct)}


def test_an_advance_payment_on_an_extract_goes_to_that_extracts_contract():
    contracts = [_k(1, 7, 3, "100000", "10"), _k(2, 7, 3, "300000", "10")]
    payment = {"payment_id": 9, "contractor_id": 7, "project_id": 3, "amount": Decimal("5000"), "contract_id": 2}
    shares = allocate_advance_payments(contracts, [payment])
    assert list(shares) == [2] and shares[2][0]["share"] == Decimal("5000.00")


def test_a_general_advance_payment_is_split_by_each_contracts_advance():
    # The user's choice: proportional. Advances 10,000 and 30,000 → a 20,000 payment splits 5,000 / 15,000.
    contracts = [_k(1, 7, 3, "100000", "10"), _k(2, 7, 3, "300000", "10"), _k(3, 8, 3, "999999", "50")]
    payment = {"payment_id": 9, "contractor_id": 7, "project_id": 3, "amount": Decimal("20000"), "contract_id": None}
    shares = allocate_advance_payments(contracts, [payment])
    assert shares[1][0]["share"] == Decimal("5000.00") and shares[2][0]["share"] == Decimal("15000.00")
    assert 3 not in shares  # another contractor's contract on the same project


def test_the_split_shares_always_add_up_to_the_payment():
    contracts = [_k(i, 7, 3, "100000", "10") for i in (1, 2, 3)]
    payment = {"payment_id": 9, "contractor_id": 7, "project_id": 3, "amount": Decimal("100"), "contract_id": None}
    shares = allocate_advance_payments(contracts, [payment])
    assert sum(lines[0]["share"] for lines in shares.values()) == Decimal("100.00")


def test_a_payment_without_a_fitting_contract_is_left_out():
    contracts = [_k(1, 7, 3, "100000", "10")]
    payments = [{"payment_id": 1, "contractor_id": 7, "project_id": None, "amount": Decimal("1"), "contract_id": None},
                {"payment_id": 2, "contractor_id": 7, "project_id": 4, "amount": Decimal("1"), "contract_id": None}]
    assert allocate_advance_payments(contracts, payments) == {}


def test_the_advance_left_takes_off_the_extracts_and_the_payments():
    contract = {"contract_id": 1, "contract_value": Decimal("1000000"), "advance_payment_pct": Decimal("10")}
    extract = {"works_value": "100000", "vat_pct": "14", "advance_payment_pct": "50", "withholding_tax_pct": "0",
               "works_insurance_pct": "0", "social_insurance_pct": "0", "other_deductions": "0"}
    row = report_row(contract, [extract], [{"share": Decimal("20000")}])
    assert row["advance_agreed"] == Decimal("100000.00")
    assert row["advance_deducted"] == Decimal("50000.00") and row["advance_paid_out"] == Decimal("20000")
    assert row["remaining_advance"] == Decimal("30000.00")
    assert row["recovered_pct"] == Decimal("70")


# -- «العقد» filter (user, 2026-10-13) -------------------------------------------------------


def test_the_contract_filter_is_on_a_second_row(screen):
    combo = screen.contract_combo
    assert combo is not None and combo.itemText(0) == "الكل"
    assert [combo.itemText(i) for i in range(1, combo.count())] == [
        "A-H/CT-1001 — أعمال الخرسانة", "A-H/CT-1002", "A-H/CT-1003", "A-H/CT-1004"]
    screen.show()
    QApplication.processEvents()
    assert combo.mapTo(screen, combo.rect().topLeft()).y() > \
        screen.company_combo.mapTo(screen, screen.company_combo.rect().bottomLeft()).y()  # its own row
    assert screen.filters()["contract_id"] is None


def test_choosing_a_contract_narrows_the_report(screen):
    screen.contract_combo.setCurrentIndex(screen.contract_combo.findData(2))
    screen.run_report()
    assert screen.service.last_filters["contract_id"] == 2
    assert screen.progress_table.rowCount() == 2  # the contract + الإجمالي
    assert screen.progress_table.item(0, PROGRESS_KEYS.index("contract_label")).text() == "A-H/CT-1002"


def test_the_contract_list_follows_the_other_filters(screen):
    screen.contract_combo.setCurrentIndex(screen.contract_combo.findData(2))  # الدلتا العقارية's
    screen.company_combo.setCurrentIndex(screen.company_combo.findData(10))
    assert screen.service.contract_calls[-1] == (10, None, None)
    assert [screen.contract_combo.itemData(i) for i in range(screen.contract_combo.count())] == [None, 1, 4]
    assert screen.contract_combo.currentData() is None  # the pick no longer fits: back to «الكل»
    screen.contract_combo.setCurrentIndex(screen.contract_combo.findData(4))
    screen.contractor_combo.setCurrentIndex(screen.contractor_combo.findData(1))
    assert screen.service.contract_calls[-1] == (10, None, 1)
    assert screen.contract_combo.currentData() == 4  # still fits: kept
    screen.project_combo.setCurrentIndex(screen.project_combo.findData(12))
    assert screen.service.contract_calls[-1] == (10, 12, 1)


def test_the_dashboard_has_no_contract_filter():
    from app.ui.screens.contractors_dashboard_screen import ContractorsDashboardScreen
    assert not ContractorsDashboardScreen.CONTRACT_FILTER  # the user kept it out (2026-10-13)


class _Db:
    def __init__(self, rows=()):
        self.queries, self.rows = [], list(rows)

    def fetch_all(self, sql, params=None):
        self.queries.append((sql, params))
        return list(self.rows) if len(self.queries) == 1 else []


def test_service_contract_choices_and_filter():
    db = _Db([{"contract_id": 7, "contract_no": "A-H/CT-1007", "contract_name": "تشطيبات"}])
    service = ContractorContractsReportService(db)
    assert service.contract_choices(10, None, 3) == [
        {"contract_id": 7, "contract_no": "A-H/CT-1007", "contract_name": "تشطيبات",
         "contract_label": "A-H/CT-1007 — تشطيبات"}]
    sql, params = db.queries[0]
    assert "k.status = 'approved'" in sql and "p.company_id = %s" in sql and "k.contractor_id = %s" in sql
    assert "k.project_id = %s" not in sql and params == [10, 3]
    db = _Db()
    ContractorContractsReportService(db).report(contract_id=7)
    sql, params = db.queries[0]
    assert "k.contract_id = %s" in sql and params == [7]


# -- «تحديد أعمدة الجدول» (user, 2026-10-14) ----------------------------------------------------

from app.ui.screens.contractor_contracts_report_screen import COLUMN_KEYS, PROGRESS_COLUMNS  # noqa: E402


def _shown(table, keys):
    return [key for column, key in enumerate(keys) if not table.isColumnHidden(column)]


def test_the_chooser_lists_every_column_and_starts_with_all(screen):
    assert list(screen.chooser.boxes) == list(COLUMN_KEYS) and len(COLUMN_KEYS) == 14
    assert COLUMN_KEYS[0] == "contract_label" and screen.chooser.boxes["contract_label"].text() == "العقد"
    assert all(box.isChecked() for box in screen.chooser.boxes.values())
    assert screen.columns_count.text() == "ظاهر 14 من 14 عمود"
    assert _shown(screen.progress_table, PROGRESS_COLUMNS) == list(PROGRESS_COLUMNS)
    assert _shown(screen.band_table, BAND_KEYS) == list(BAND_KEYS)


def test_hiding_columns_applies_to_both_tabs_and_moves_the_total_label(screen):
    screen.chooser.boxes["contract_label"].setChecked(False)
    screen.chooser.boxes["contract_date"].setChecked(False)
    screen.chooser.boxes["status"].setChecked(False)
    for table, keys in ((screen.progress_table, PROGRESS_COLUMNS), (screen.band_table, BAND_KEYS)):
        shown = _shown(table, keys)
        assert "contract_label" not in shown and "contract_date" not in shown and "company_name" in shown
        total = table.rowCount() - 1
        assert table.item(total, keys.index("company_name")).text() == "الإجمالي — 4 عقود"
    assert screen.progress_table.isColumnHidden(P_STATUS)
    assert screen.columns_count.text() == "ظاهر 11 من 14 عمود"


def test_a_band_title_hides_with_all_its_columns(screen):
    screen.tabs.setCurrentIndex(TAB_BANDS)
    screen.show()
    QApplication.processEvents()
    identity = [key for key, _box in screen.chooser.boxes.items()][:5]
    screen.set_visible_columns([key for key in COLUMN_KEYS if key not in identity])
    QApplication.processEvents()
    assert [label.isVisible() for label in screen.band_header.labels] == [False, True, True]
    assert screen.band_table.item(screen.band_table.rowCount() - 1, 0).text() == ""  # no label to show


def test_the_column_choice_is_kept_per_user(qt_app, settings):
    first = ContractorContractsReportScreen(FakeService(), settings=settings)
    first.set_visible_columns(["contract_label", "contractor_name", "contract_value", "remaining_value"])
    first.close()
    second = ContractorContractsReportScreen(FakeService(), settings=settings)
    assert second.visible_columns == ("contract_label", "contractor_name", "contract_value", "remaining_value")
    assert _shown(second.band_table, BAND_KEYS) == ["contract_label", "contractor_name", "contract_value",
                                                     "remaining_value"]
    second.chooser.default_button.click()
    assert second.visible_columns == COLUMN_KEYS
    second.close()
