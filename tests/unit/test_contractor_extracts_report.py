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

from app.services.contractor_contract_service import contract_label
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
            "extract_date": datetime.date(*date), "contract_id": contractor_id, "contract_no": f"A-H/CT-100{contractor_id}",
            "company_id": company_id, "company_name": company, "project_id": project_id, "project_name": project,
            "contractor_id": contractor_id, "contractor_name": contractor, "works_value": Decimal(works),
            "vat_pct": Decimal("14"), "advance_payment_pct": Decimal(advance),
            "withholding_tax_pct": Decimal(withholding), "works_insurance_pct": Decimal("5"),
            "social_insurance_pct": Decimal(social), "other_deductions": Decimal(other)}


EXTRACTS = [
    {**_extract(1, (2026, 2, 15), 10, "الأفق للتطوير", 11, "برج الأفق", 1, "م. أحمد عبد الرحمن", "456000"),
     "contract_name": "أعمال الخرسانة"},
    {**_extract(2, (2026, 2, 28), 10, "الأفق للتطوير", 11, "برج الأفق", 2, "الصفا للكهرباء", "185000",
                advance="15", withholding="3", social="2.8", other="2500"),
     # «خصومات أخرى» in detail (2026-10-14); extract 4's 1,200 has none: a total saved before the detail
     "deductions": [{"deduction_type": "غرامة تأخير", "reason": "تأخير 5 أيام", "amount": Decimal("2000")},
                    {"deduction_type": "مياه وكهرباء", "reason": "", "amount": Decimal("500")}]},
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
        if "contractor_extract_deductions" in query:
            return []
        return [dict(x) for x in EXTRACTS[:1]]  # copies: the report adds each one's deductions


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
        self.contract_calls = []

    def company_choices(self):
        return [{"company_id": 10, "company_code": "C10", "company_name": "الأفق للتطوير"},
                {"company_id": 20, "company_code": "C20", "company_name": "الدلتا العقارية"}]

    def project_choices(self, company_id=None):
        projects = [{"project_id": 11, "project_code": "P11", "project_name": "برج الأفق", "company_id": 10},
                    {"project_id": 21, "project_code": "P21", "project_name": "كمبوند الياسمين", "company_id": 20}]
        return [p for p in projects if company_id in (None, p["company_id"])]

    def contractor_choices(self):
        return [{"contractor_id": 1, "contractor_code": "D1", "contractor_name": "م. أحمد عبد الرحمن"}]

    def contract_choices(self, company_id=None, project_id=None, contractor_id=None):
        self.contract_calls.append((company_id, project_id, contractor_id))
        return [{"contract_id": c["contract_id"], "contract_label": contract_label(c)} for c in EXTRACTS
                if company_id in (None, c["company_id"]) and contractor_id in (None, c["contractor_id"])]

    def company_print_info(self, company_ids):
        return [{**c, "address": None, "tax_registration_no": None, "logo": None, "logo_mime": None}
                for c in self.company_choices() if c["company_id"] in company_ids]

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
    assert headers == ["تاريخ المستخلص", "اسم الشركة", "اسم المشروع", "اسم المقاول", "العقد", "رقم المستخلص",
                       "إجمالي المستخلص", "نسبة الضريبة", "صافي الأعمال", "نسبة الدفعة المقدمة",
                       "قيمة الدفعة المقدمة", "نسبة ضرائب الخصم", "قيمة ضرائب الخصم", "نسبة تأمين الأعمال",
                       "قيمة تأمين الأعمال", "نسبة التأمينات الاجتماعية", "قيمة التأمينات الاجتماعية",
                       "خصومات أخرى", "صافي المستخلص"]


def test_contract_column_is_number_and_name(screen):
    """«العقد» (2026-10-13): «رقم — اسم», the number alone when the contract has no name."""
    column = COLUMN_KEYS.index("contract_label")
    texts = {screen.table.item(row, column).text() for row in range(screen.table.rowCount() - 1)}
    assert {"A-H/CT-1001 — أعمال الخرسانة", "A-H/CT-1002"} <= texts


def test_the_eight_cards(screen):
    assert [title for _key, title in CARDS] == [
        "إجمالي المستخلص", "إجمالي صافي الأعمال", "إجمالي الدفعة المقدمة", "إجمالي ضرائب الخصم",
        "إجمالي تأمين الأعمال", "إجمالي التأمينات الاجتماعية", "إجمالي الخصومات الأخرى", "إجمالي صافي المستخلص"]
    assert screen.card_values["works_value"].text() == "1,641,000.00"
    assert screen.card_values["other_deductions"].text() == "3,700.00"
    assert screen.card_values["net"].text() == f"{screen.totals['net']:,.2f}"


def test_default_columns_are_the_mockups_and_rates_are_hidden(screen):
    assert _visible(screen) == list(DEFAULT_COLUMNS)
    assert "vat_pct" not in DEFAULT_COLUMNS and len(DEFAULT_COLUMNS) == 14
    assert screen.columns_count.text() == "ظاهر 14 من 19 عمود"


def test_the_chooser_has_a_checkbox_per_column(screen):
    assert list(screen.chooser.boxes) == list(COLUMN_KEYS)
    assert [k for k, box in screen.chooser.boxes.items() if box.isChecked()] == list(DEFAULT_COLUMNS)
    screen.chooser.boxes["vat_pct"].setChecked(True)
    assert "vat_pct" in _visible(screen)
    screen.chooser.boxes["company_name"].setChecked(False)
    assert "company_name" not in _visible(screen)
    assert screen.columns_count.text() == "ظاهر 14 من 19 عمود"
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


def test_reload_lists_refreshes_the_filters_and_keeps_the_pick(screen, monkeypatch):
    screen.contractor_combo.setCurrentIndex(screen.contractor_combo.findData(1))
    extra = {"contractor_id": 9, "contractor_code": "D9", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.reload_lists()
    assert screen.contractor_combo.findData(9) >= 0
    assert screen.contractor_combo.currentData() == 1


def test_reload_lists_reports_a_database_error_instead_of_raising(screen, monkeypatch):
    """Review fix: a reload on sidebar open must not escape as an exception (button seems dead)."""
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[1:3]))

    def down():
        raise RuntimeError("database is down")

    monkeypatch.setattr(screen.service, "contractor_choices", down)
    screen.reload_lists()
    assert shown and "database is down" in shown[0][1]


def test_the_refresh_button_reports_a_database_error_too(screen, monkeypatch):
    """Review fix: «تحديث» must behave like the automatic reload, not raise."""
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[1:3]))

    def down():
        raise RuntimeError("database is down")

    monkeypatch.setattr(screen.service, "contractor_choices", down)
    screen.refresh_button.click()
    assert shown and "database is down" in shown[0][1]


# -- «إظهار تفاصيل الخصومات» (user, 2026-10-14) ---------------------------------------------

from app.ui.screens.contractor_extracts_report_screen import ROW_DEDUCTION  # noqa: E402


def _texts(screen, kind):
    column = COLUMN_KEYS.index("extract_date")
    return [screen.table.item(row, column).text()
            for row, (k, _key) in enumerate(screen.row_kinds) if k == kind]


def test_report_rows_carry_their_deduction_lines():
    assert [line["deduction_type"] for line in report_row(EXTRACTS[1])["deductions"]] == ["غرامة تأخير",
                                                                                         "مياه وكهرباء"]
    legacy = report_row(EXTRACTS[3])["deductions"]
    assert legacy == [{"deduction_type": "أخرى", "reason": "رصيد سابق قبل التفصيل", "amount": Decimal("1200.00")}]
    assert report_row(EXTRACTS[0])["deductions"] == []


class _Db:
    def __init__(self):
        self.queries = []

    def fetch_all(self, sql, params=None):
        self.queries.append((sql, params))
        if "contractor_extract_deductions" in sql:
            return [{"extract_id": 9, "deduction_type": "غرامة", "reason": "", "amount": Decimal("100")}]
        return [{**EXTRACTS[0], "extract_id": 9, "other_deductions": Decimal("100")}]


def test_service_reads_each_extracts_deduction_lines():
    db = _Db()
    rows = ContractorExtractsReportService(db).report()
    sql, params = db.queries[1]
    assert "contractor_extract_deductions" in sql and params == [[9]]
    assert rows[0]["deductions"] == [{"extract_id": 9, "deduction_type": "غرامة", "reason": "",
                                      "amount": Decimal("100")}]


def test_the_details_button_starts_off_with_the_total_beside_it(screen):
    assert not screen.deductions_toggle.isChecked()
    assert screen.deductions_toggle.text() == "إظهار تفاصيل الخصومات"
    assert screen.deductions_total.text() == "إجمالي الخصومات: 3,700.00"
    assert ROW_DEDUCTION not in [kind for kind, _key in screen.row_kinds]


def test_the_details_open_a_line_under_each_extract(screen):
    screen.deductions_toggle.click()
    assert screen.deductions_toggle.text() == "إخفاء تفاصيل الخصومات"
    kinds = [kind for kind, _key in screen.row_kinds]
    # البناء الحديث (none), الصفا للكهرباء (2 lines), م. أحمد عبد الرحمن (EX-04's old total as one line)
    assert kinds == [ROW_GROUP, ROW_EXTRACT, ROW_SUBTOTAL,
                     ROW_GROUP, ROW_EXTRACT, ROW_DEDUCTION, ROW_DEDUCTION, ROW_SUBTOTAL,
                     ROW_GROUP, ROW_EXTRACT, ROW_EXTRACT, ROW_DEDUCTION, ROW_SUBTOTAL, ROW_TOTAL]
    assert _texts(screen, ROW_DEDUCTION) == ["• غرامة تأخير — تأخير 5 أيام", "• مياه وكهرباء",
                                             "• أخرى — رصيد سابق قبل التفصيل"]
    first = kinds.index(ROW_DEDUCTION)
    assert screen.table.item(first, COLUMN_KEYS.index("other_deductions")).text() == "2,000.00"
    assert screen.table.item(first, COLUMN_KEYS.index("net")).text() == ""


def test_without_the_deductions_column_the_amount_goes_under_the_net(screen):
    screen.deductions_toggle.click()
    screen.chooser.boxes["other_deductions"].setChecked(False)
    first = [kind for kind, _key in screen.row_kinds].index(ROW_DEDUCTION)
    assert screen.table.item(first, COLUMN_KEYS.index("net")).text() == "(2,000.00)"


def test_a_closed_group_hides_its_details_and_the_choice_is_kept(qt_app, screen, settings):
    screen.deductions_toggle.click()
    screen.collapse_all()
    assert ROW_DEDUCTION not in [kind for kind, _key in screen.row_kinds]
    screen.set_group_mode(GROUP_NONE)
    assert [kind for kind, _key in screen.row_kinds].count(ROW_DEDUCTION) == 3
    again = ContractorExtractsReportScreen(FakeService(), settings=settings)
    assert again.deductions_toggle.isChecked()
    again.close()


def test_the_deductions_card_lists_the_types(screen):
    tip = screen.deductions_card.toolTip()
    assert tip.splitlines() == ["الخصومات الأخرى حسب النوع:", "غرامة تأخير: 2,000.00", "أخرى: 1,200.00",
                                "مياه وكهرباء: 500.00"]


# -- print / PDF / Excel: نموذج 1 of the print mockups, with clear borders (user, 2026-10-14) ----


def _line_kinds(section):
    return [(line.kind, line.label) for line in section.lines]


def test_the_extracts_report_has_the_print_buttons(screen):
    assert list(screen.print_buttons) == ["preview", "print", "pdf", "excel"]


def test_print_follows_the_grouping_one_company_per_section(screen):
    screen.show_deductions = False
    document = screen.print_document()
    assert [s.company["company_name"] for s in document.sections] == ["الأفق للتطوير", "الدلتا العقارية"]
    first = document.sections[0]
    assert _line_kinds(first) == [
        ("group", "الصفا للكهرباء — 1 مستخلص"), ("row", ""), ("subtotal", "إجمالي الصفا للكهرباء"),
        ("group", "م. أحمد عبد الرحمن — 2 مستخلصات"), ("row", ""), ("row", ""),
        ("subtotal", "إجمالي م. أحمد عبد الرحمن")]
    assert document.subtitle == "مجمّع حسب المقاول"
    assert document.grand_totals is not None and [k for k, _c in document.cards][-1] == "net"


def test_a_closed_group_prints_as_one_totals_line(screen):
    screen.show_deductions = False
    screen.collapsed = {1}  # م. أحمد عبد الرحمن
    kinds = _line_kinds(screen.print_document().sections[0])
    assert ("subtotal", "م. أحمد عبد الرحمن (2 مستخلصات)") in kinds
    assert ("group", "م. أحمد عبد الرحمن — 2 مستخلصات") not in kinds


def test_deduction_lines_print_only_when_the_button_is_on(screen):
    screen.show_deductions = True
    lines = screen.print_document().sections[0].lines
    deductions = [(line.label, line.amount) for line in lines if line.kind == "deduction"]
    assert deductions[:2] == [("• غرامة تأخير — تأخير 5 أيام", Decimal("2000")), ("• مياه وكهرباء", Decimal("500"))]
    screen.show_deductions = False
    assert not [line for line in screen.print_document().sections[0].lines if line.kind == "deduction"]


def test_the_grouped_by_and_company_columns_do_not_print(screen):
    keys = [c.key for c in screen.print_document().columns]
    assert "company_name" not in keys and "contractor_name" not in keys
    assert keys[:3] == ["_serial", "extract_date", "project_name"]
    screen.set_group_mode("project")
    keys = [c.key for c in screen.print_document().columns]
    assert "project_name" not in keys and "contractor_name" in keys


def test_without_grouping_the_rows_print_one_by_one(screen):
    screen.set_group_mode("none")
    screen.show_deductions = False
    document = screen.print_document()
    assert [line.kind for line in document.sections[0].lines] == ["row", "row", "row"]
    assert document.subtitle == "بدون تجميع"
