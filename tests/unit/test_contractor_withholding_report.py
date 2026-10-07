"""تقرير ضرائب الخصم (نموذج 7, 2026-10-07): the arithmetic, the card query and the screen."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.services.contractor_extracts_report_service import report_row
from app.services.contractor_withholding_report_service import (
    ContractorWithholdingReportService,
    build_report,
)
from app.ui.screens.contractor_withholding_report_screen import (
    COLUMN_KEYS,
    ContractorWithholdingReportScreen,
)


def _extract(extract_id, date, works, withholding="1", contractor="م. أحمد عبد الرحمن",
             project="كمبوند الأفق — المرحلة الأولى", company="الأفق للتطوير العقاري"):
    return report_row({
        "extract_id": extract_id, "extract_no": f"EX-0{extract_id}", "extract_date": datetime.date(*date),
        "works_value": Decimal(works), "vat_pct": Decimal("14"), "advance_payment_pct": Decimal("10"),
        "withholding_tax_pct": Decimal(withholding), "works_insurance_pct": Decimal("5"),
        "social_insurance_pct": Decimal("0"), "other_deductions": Decimal("0"),
        "contractor_id": 1, "contractor_name": contractor, "project_id": 21, "project_name": project,
        "company_id": 10, "company_name": company})


# 456,000 → صافي الأعمال 400,000 → 1% = 4,000; 171,000 → 150,000 → 3% = 4,500.
ROWS = [_extract(1, (2026, 1, 12), "456000"), _extract(2, (2026, 3, 10), "171000", "3")]
CARD = Decimal("36000")


# -- the arithmetic --------------------------------------------------------------------------


def test_net_is_the_opening_plus_the_extracts():
    """The user's example (2026-10-07): 36,000 on the cards + 4,000 on the extracts = 40,000."""
    report = build_report(CARD, ROWS[:1])
    assert report["opening"] == Decimal("36000.00")
    assert report["totals"]["withholding_tax"] == Decimal("4000.00")
    assert report["net"] == Decimal("40000.00")
    assert report["totals"]["works_value"] == Decimal("456000.00")
    assert report["totals"]["before_tax"] == Decimal("400000.00")


def test_extracts_before_from_go_into_the_opening():
    report = build_report(CARD, ROWS, datetime.date(2026, 2, 1))
    assert [row["extract_id"] for row in report["rows"]] == [2]
    assert report["earlier_extracts"] == Decimal("4000.00")
    assert report["opening"] == Decimal("40000.00")
    assert report["totals"]["withholding_tax"] == Decimal("4500.00")
    assert report["net"] == Decimal("44500.00")  # the same end as without «من»
    assert build_report(CARD, ROWS)["net"] == Decimal("44500.00")


class _Db:
    """Answers the report's queries, keeping them to look at."""

    def __init__(self, extracts=()):
        self.queries = []
        self.extracts = list(extracts)

    def fetch_one(self, sql, params=None):
        self.queries.append((sql, params))
        return {"amount": CARD}

    def fetch_all(self, sql, params=None):
        self.queries.append((sql, params))
        return list(self.extracts)


def test_service_reads_the_cards_the_filters_cover():
    db = _Db()
    ContractorWithholdingReportService(db).withholding_report(contractor_id=5)
    sql, params = db.queries[-1]  # the extracts first, then the cards
    assert "withholding_tax_amount" in sql and "contractor_id = %s" in sql and params == [5]
    db = _Db()
    ContractorWithholdingReportService(db).withholding_report()
    sql, params = db.queries[-1]  # the extracts first, then the cards
    assert "sum(d.withholding_tax_amount)" in sql and "IN (SELECT" not in sql and params == []
    db = _Db()
    ContractorWithholdingReportService(db).withholding_report(company_id=10, project_id=21)
    sql, params = db.queries[-1]  # the extracts first, then the cards
    assert "IN (SELECT k.contractor_id" in sql and params == [10, 21]


def test_service_lists_every_extract_up_to_to():
    db = _Db()
    ContractorWithholdingReportService(db).withholding_report(
        date_from=datetime.date(2026, 2, 1), date_to=datetime.date(2026, 12, 31))
    extracts_sql, params = db.queries[0]
    assert "x.extract_date <= %s" in extracts_sql and "x.extract_date >= %s" not in extracts_sql
    assert params == [datetime.date(2026, 12, 31)]


# -- the screen ------------------------------------------------------------------------------


class FakeService:
    def __init__(self):
        self.last_filters = None

    def company_choices(self):
        return [{"company_id": 10, "company_code": "C10", "company_name": "الأفق للتطوير العقاري"}]

    def project_choices(self, company_id=None):
        return []

    def contractor_choices(self):
        return [{"contractor_id": 1, "contractor_code": "D1", "contractor_name": "م. أحمد عبد الرحمن"}]

    def withholding_report(self, **filters):
        self.last_filters = filters
        return build_report(CARD, ROWS, filters["date_from"])


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "report.ini"), QSettings.IniFormat)


@pytest.fixture
def screen(qt_app, settings):
    widget = ContractorWithholdingReportScreen(FakeService(), settings=settings)
    widget.resize(1700, 900)
    widget.show()
    qt_app.processEvents()
    yield widget
    widget.close()


def _cell(screen, row, key):
    item = screen.table.item(row, COLUMN_KEYS.index(key))
    return item.text() if item else ""


def test_the_users_columns_in_order(screen):
    headers = [screen.table.horizontalHeaderItem(i).text().replace("\n", " ") for i in range(len(COLUMN_KEYS))]
    assert headers == ["التاريخ", "اسم المقاول", "اسم المشروع", "اسم الشركة", "إجمالي المستخلص",
                       "نسبة الضريبة", "صافي الأعمال", "نسبة ضرائب الخصم", "قيمة ضرائب الخصم"]
    assert not any(screen.table.isColumnHidden(i) for i in range(len(COLUMN_KEYS)))


def test_the_band_figures(screen):
    values = {key: label.text() for key, label in screen.figure_values.items()}
    assert values == {"works_value": "627,000.00", "before_tax": "550,000.00", "opening": "36,000.00",
                      "withholding_tax": "8,500.00", "net": "44,500.00"}
    assert screen.service.last_filters["contractor_id"] is None  # opens on «الكل»


def test_rows_and_the_totals_row(screen):
    assert screen.table.rowCount() == 3
    assert _cell(screen, 0, "extract_date") == "2026-01-12"
    assert _cell(screen, 0, "vat_pct") == "14%"
    assert _cell(screen, 0, "before_tax") == "400,000.00"
    assert _cell(screen, 1, "withholding_tax_pct") == "3%"
    assert _cell(screen, 1, "withholding_tax") == "4,500.00"
    assert _cell(screen, 2, "extract_date") == "الإجمالي — 2 مستخلصات"
    assert _cell(screen, 2, "withholding_tax") == "8,500.00"


def test_period_moves_older_extracts_into_the_opening(screen):
    screen.all_dates.setChecked(False)
    screen.date_from.setDate(datetime.date(2026, 2, 1))
    screen.date_to.setDate(datetime.date(2026, 12, 31))
    screen.run_report()
    assert screen.figure_values["opening"].text() == "40,000.00"
    assert screen.figure_values["withholding_tax"].text() == "4,500.00"
    assert screen.figure_values["net"].text() == "44,500.00"
    assert "قبل 2026-02-01" in screen.figure_hints["opening"].text()
    assert screen.table.rowCount() == 2


def test_column_chooser_hides_and_remembers(screen, settings):
    screen.set_visible_columns([key for key in COLUMN_KEYS if key not in ("extract_date", "company_name")])
    assert screen.table.isColumnHidden(COLUMN_KEYS.index("extract_date"))
    assert _cell(screen, 2, "contractor_name") == "الإجمالي — 2 مستخلصات"  # the label moves along
    assert screen.columns_count.text() == "7 من 9 أعمدة"
    again = ContractorWithholdingReportScreen(FakeService(), settings=settings)
    assert "extract_date" not in again.visible_columns and "project_name" in again.visible_columns
    again.close()


def test_wrap_text_shares_the_width_and_is_remembered(screen, settings, qt_app):
    assert not screen.wrap and not screen.table.wordWrap()
    assert "متوقف" in screen.wrap_button.text()
    screen.wrap_button.click()
    qt_app.processEvents()
    assert screen.wrap and screen.table.wordWrap() and "مفعّل" in screen.wrap_button.text()
    widths = [screen.table.columnWidth(i) for i in range(len(COLUMN_KEYS))]
    assert max(widths[:-1]) == min(widths)  # equal shares: a long name wraps instead of widening
    assert widths[-1] - widths[0] < len(COLUMN_KEYS)  # the last one takes the rounding pixels
    again = ContractorWithholdingReportScreen(FakeService(), settings=settings)
    assert again.wrap and again.wrap_button.isChecked()
    again.close()
