"""Tests for تقرير مستخلصات المقاولين — نموذج 6 (headless Qt, no database).

The user's rules (2026-09-26):

* الأعمدة بالترتيب: تاريخ المستخلص، اسم الشركة، اسم المشروع، اسم المقاول، رقم
  المستخلص، إجمالي المستخلص، نسبة الضريبة، صافي الأعمال، نسبة/قيمة الدفعة
  المقدمة، نسبة/قيمة ضرائب الخصم، نسبة/قيمة تأمين الأعمال، نسبة/قيمة التأمينات
  الاجتماعية، خصومات أخرى، صافي المستخلص.
* ثمانية كروت إجماليات.
* زر «تحديد أعمدة الجدول» بقائمة Checkboxes لكل الأعمدة.
* المبالغ هي نفس ``extract_amounts`` بتاعة شاشة المستخلصات.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.services.contractor_extracts_report_service import (
    GROUP_COMPANY,
    GROUP_CONTRACTOR,
    GROUP_NONE,
    ContractorExtractsReportService,
    group_rows,
    report_row,
    report_totals,
)
from app.ui.screens.contractor_extracts_report_screen import (
    CARDS,
    COLUMN_KEYS,
    COLUMNS,
    DEFAULT_COLUMNS,
    ROW_COLLAPSED,
    ROW_EXTRACT,
    ROW_GROUP,
    ROW_SUBTOTAL,
    ROW_TOTAL,
    ContractorExtractsReportScreen,
)


def _extract(extract_id, date, company_id, company, project_id, project, contractor_id, contractor, works,
             advance="10", withholding="1", social="0.365", other="0"):
    return {"extract_id": extract_id, "extract_no": f"A-H/CT-100{contractor_id}/EX-0{extract_id}",
            "extract_date": datetime.date(*date), "contract_id": contractor_id, "contract_no": "",
            "company_id": company_id, "company_name": company, "project_id": project_id, "project_name": project,
            "contractor_id": contractor_id, "contractor_name": contractor, "works_value": Decimal(works),
            "vat_pct": Decimal("14"), "advance_payment_pct": Decimal(advance),
            "withholding_tax_pct": Decimal(withholding), "works_insurance_pct": Decimal("5"),
            "social_insurance_pct": Decimal(social), "other_deductions": Decimal(other)}


EXTRACTS = [
    _extract(1, (2026, 2, 15), 10, "الأفق للتطوير", 11, "برج الأفق", 1, "م. أحمد عبد الرحمن", "456000"),
    _extract(2, (2026, 2, 28), 10, "الأفق للتطوير", 11, "برج الأفق", 2, "الصفا للكهرباء", "185000",
             advance="15", withholding="3", social="2.8", other="2500"),
    _extract(3, (2026, 3, 10), 20, "الدلتا العقارية", 21, "كمبوند الياسمين", 3, "البناء الحديث", "620000",
             social="3.6"),
    _extract(4, (2026, 3, 25), 10, "الأفق للتطوير", 12, "فيلات الأفق", 1, "م. أحمد عبد الرحمن", "380000",
             other="1200"),
]


# -- the arithmetic ------------------------------------------------------------------------


def test_row_matches_the_extracts_screen():
    row = report_row(EXTRACTS[0])
    assert row["works_value"] == Decimal("456000.00")
    assert row["before_tax"] == Decimal("400000.00")        # 456,000 ÷ 1.14
    assert row["advance_payment"] == Decimal("45600.00")    # 10% of the total
    assert row["withholding_tax"] == Decimal("4000.00")     # 1% of صافي الأعمال
    assert row["works_insurance"] == Decimal("22800.00")    # 5%
    assert row["social_insurance"] == Decimal("1664.40")    # 0.365%
    assert row["net"] == Decimal("381935.60")
    assert row["vat_pct"] == Decimal("14") and row["social_insurance_pct"] == Decimal("0.365")


def test_totals_add_every_amount():
    totals = report_totals([report_row(x) for x in EXTRACTS])
    assert totals["count"] == 4
    assert totals["works_value"] == Decimal("1641000.00")
    assert totals["other_deductions"] == Decimal("3700.00")
    assert totals["net"] == totals["works_value"] - sum(
        totals[k] for k in ("advance_payment", "withholding_tax", "works_insurance", "social_insurance",
                            "other_deductions"))


def test_groups_by_contractor_keep_their_rows_and_totals():
    groups = group_rows([report_row(x) for x in EXTRACTS], GROUP_CONTRACTOR)
    assert [g["name"] for g in groups] == ["البناء الحديث", "الصفا للكهرباء", "م. أحمد عبد الرحمن"]
    ahmed = groups[2]
    assert [r["extract_id"] for r in ahmed["rows"]] == [1, 4]
    assert ahmed["totals"]["works_value"] == Decimal("836000.00")
    assert group_rows([report_row(x) for x in EXTRACTS], GROUP_NONE) == []


# -- the SQL filters -----------------------------------------------------------------------


class _RecordingDb:
    def __init__(self):
        self.calls = []

    def fetch_all(self, query, params=None):
        self.calls.append((query, list(params or [])))
        return EXTRACTS[:1]


def test_the_period_filters_on_the_extract_date():
    db = _RecordingDb()
    rows = ContractorExtractsReportService(db).report(
        date_from=datetime.date(2026, 1, 1), date_to=datetime.date(2026, 6, 30), company_id=None,
        project_id=11, contractor_id=None)
    query, params = db.calls[0]
    assert "x.extract_date >= %s" in query and "x.extract_date <= %s" in query and "k.project_id = %s" in query
    assert "p.company_id = %s" not in query and "k.contractor_id = %s" not in query
    assert params == [datetime.date(2026, 1, 1), datetime.date(2026, 6, 30), 11]
    assert "ORDER BY x.extract_date, x.extract_no" in query
    assert rows[0]["net"] == Decimal("381935.60")


# -- the screen ------------------------------------------------------------------------------


class FakeService:
    def __init__(self):
        self.last_filters = None

    def company_choices(self):
        return [{"company_id": 10, "company_code": "C10", "company_name": "الأفق للتطوير"},
                {"company_id": 20, "company_code": "C20", "company_name": "الدلتا العقارية"}]

    def project_choices(self, company_id=None):
        projects = [{"project_id": 11, "project_code": "P11", "project_name": "برج الأفق", "company_id": 10},
                    {"project_id": 21, "project_code": "P21", "project_name": "كمبوند الياسمين", "company_id": 20}]
        return [p for p in projects if company_id in (None, p["company_id"])]

    def contractor_choices(self):
        return [{"contractor_id": 1, "contractor_code": "D1", "contractor_name": "م. أحمد عبد الرحمن"}]

    def report(self, **filters):
        self.last_filters = filters
        return [report_row(x) for x in EXTRACTS
                if filters.get("company_id") in (None, x["company_id"])
                and filters.get("contractor_id") in (None, x["contractor_id"])]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "report.ini"), QSettings.IniFormat)


@pytest.fixture
def screen(qt_app, settings):
    widget = ContractorExtractsReportScreen(FakeService(), settings=settings)
    widget.resize(1700, 900)
    yield widget
    widget.close()


def _kinds(screen):
    return [kind for kind, _key in screen.row_kinds]


def _visible(screen):
    return [key for i, key in enumerate(COLUMN_KEYS) if not screen.table.isColumnHidden(i)]


def test_columns_are_the_users_in_order(screen):
    headers = [screen.table.horizontalHeaderItem(i).text().replace("\n", " ") for i in range(len(COLUMNS))]
    assert headers == ["تاريخ المستخلص", "اسم الشركة", "اسم المشروع", "اسم المقاول", "رقم المستخلص",
                       "إجمالي المستخلص", "نسبة الضريبة", "صافي الأعمال", "نسبة الدفعة المقدمة",
                       "قيمة الدفعة المقدمة", "نسبة ضرائب الخصم", "قيمة ضرائب الخصم", "نسبة تأمين الأعمال",
                       "قيمة تأمين الأعمال", "نسبة التأمينات الاجتماعية", "قيمة التأمينات الاجتماعية",
                       "خصومات أخرى", "صافي المستخلص"]


def test_the_eight_cards(screen):
    assert [title for _key, title in CARDS] == [
        "إجمالي المستخلص", "إجمالي صافي الأعمال", "إجمالي الدفعة المقدمة", "إجمالي ضرائب الخصم",
        "إجمالي تأمين الأعمال", "إجمالي التأمينات الاجتماعية", "إجمالي الخصومات الأخرى", "إجمالي صافي المستخلص"]
    assert screen.card_values["works_value"].text() == "1,641,000.00"
    assert screen.card_values["other_deductions"].text() == "3,700.00"
    assert screen.card_values["net"].text() == f"{screen.totals['net']:,.2f}"


def test_default_columns_are_the_mockups_and_rates_are_hidden(screen):
    assert _visible(screen) == list(DEFAULT_COLUMNS)
    assert "vat_pct" not in DEFAULT_COLUMNS and len(DEFAULT_COLUMNS) == 13
    assert screen.columns_count.text() == "ظاهر 13 من 18 عمود"


def test_the_chooser_has_a_checkbox_per_column(screen):
    assert list(screen.chooser.boxes) == list(COLUMN_KEYS)
    assert [k for k, box in screen.chooser.boxes.items() if box.isChecked()] == list(DEFAULT_COLUMNS)
    screen.chooser.boxes["vat_pct"].setChecked(True)
    assert "vat_pct" in _visible(screen)
    screen.chooser.boxes["company_name"].setChecked(False)
    assert "company_name" not in _visible(screen)
    assert screen.columns_count.text() == "ظاهر 13 من 18 عمود"
    screen.chooser.all_button.click()
    assert _visible(screen) == list(COLUMN_KEYS)
    screen.chooser.none_button.click()
    assert _visible(screen) == []
    screen.chooser.default_button.click()
    assert _visible(screen) == list(DEFAULT_COLUMNS)


def test_the_column_choice_is_kept_for_next_time(qt_app, settings):
    first = ContractorExtractsReportScreen(FakeService(), settings=settings)
    first.set_visible_columns(["extract_no", "works_value", "net"])
    first.close()
    second = ContractorExtractsReportScreen(FakeService(), settings=settings)
    assert _visible(second) == ["extract_no", "works_value", "net"]
    assert second.chooser.boxes["net"].isChecked() and not second.chooser.boxes["vat_pct"].isChecked()
    second.close()


def test_grouped_by_contractor_by_default(screen):
    # 3 contractors: title, rows, إجمالي — then الإجمالي العام
    assert _kinds(screen) == [ROW_GROUP, ROW_EXTRACT, ROW_SUBTOTAL,
                              ROW_GROUP, ROW_EXTRACT, ROW_SUBTOTAL,
                              ROW_GROUP, ROW_EXTRACT, ROW_EXTRACT, ROW_SUBTOTAL, ROW_TOTAL]
    table = screen.table
    assert "البناء الحديث" in table.item(0, 0).text() and "1 مستخلص" in table.item(0, 0).text()
    subtotal = 9
    assert table.item(subtotal, 0).text() == "إجمالي م. أحمد عبد الرحمن"
    assert table.item(subtotal, COLUMN_KEYS.index("works_value")).text() == "836,000.00"
    last = table.rowCount() - 1
    assert table.item(last, 0).text() == "الإجمالي العام — 4 مستخلصات"
    assert table.item(last, COLUMN_KEYS.index("works_value")).text() == "1,641,000.00"
    assert table.item(last, COLUMN_KEYS.index("vat_pct")).text() == ""
    assert screen.count_label.text() == "عدد المستخلصات: 4"


def test_extract_row_cells(screen):
    table = screen.table
    row = 7  # م. أحمد عبد الرحمن's first extract
    assert table.item(row, 0).text() == "2026-02-15"
    assert table.item(row, COLUMN_KEYS.index("extract_no")).text() == "A-H/CT-1001/EX-01"
    assert table.item(row, COLUMN_KEYS.index("before_tax")).text() == "400,000.00"
    assert table.item(row, COLUMN_KEYS.index("social_insurance_pct")).text() == "0.365%"
    assert table.item(row, COLUMN_KEYS.index("net")).text() == "381,935.60"


def test_a_group_closes_and_opens_by_clicking_it(screen):
    screen._row_clicked(0, 0)  # البناء الحديث
    assert _kinds(screen)[0] == ROW_COLLAPSED
    assert "البناء الحديث" in screen.table.item(0, 0).text()
    assert screen.table.item(0, COLUMN_KEYS.index("works_value")).text() == "620,000.00"
    assert screen.table.rowCount() == 9
    screen._row_clicked(0, 3)
    assert _kinds(screen)[:3] == [ROW_GROUP, ROW_EXTRACT, ROW_SUBTOTAL]
    screen.collapse_button.click()
    assert _kinds(screen) == [ROW_COLLAPSED] * 3 + [ROW_TOTAL]
    screen.expand_button.click()
    assert _kinds(screen).count(ROW_GROUP) == 3


def test_other_groupings(screen):
    screen.set_group_mode(GROUP_COMPANY)
    assert _kinds(screen).count(ROW_GROUP) == 2
    screen.set_group_mode(GROUP_NONE)
    assert _kinds(screen) == [ROW_EXTRACT] * 4 + [ROW_TOTAL]
    assert screen.table.item(4, 0).text() == "الإجمالي — 4 مستخلصات"
    assert not screen.expand_button.isEnabled()


def test_labels_follow_hidden_text_columns(screen):
    screen.set_visible_columns([k for k in COLUMN_KEYS if k not in ("extract_date", "company_name")])
    first = COLUMN_KEYS.index("project_name")
    assert "البناء الحديث" in screen.table.item(0, first).text()
    assert screen.table.item(2, first).text() == "إجمالي البناء الحديث"


def test_filters_and_rerun_leave_no_stale_rows(screen):
    assert screen.filters()["date_from"] is None  # «كل الفترات» by default
    screen.company_combo.setCurrentIndex(screen.company_combo.findData(20))
    screen.run_report()
    assert screen.service.last_filters["company_id"] == 20
    assert _kinds(screen) == [ROW_GROUP, ROW_EXTRACT, ROW_SUBTOTAL, ROW_TOTAL]
    assert screen.card_values["works_value"].text() == "620,000.00"
    assert screen.table.rowCount() == 4
