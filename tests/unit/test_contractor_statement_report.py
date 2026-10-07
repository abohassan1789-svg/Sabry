"""Tests for تقرير كشف حساب مقاول — نموذج 10 (headless Qt, no database).

The user's rules (2026-10-02):

* أول صف رصيد أول المدة، وبعده المستخلصات والدفعات بالتاريخ.
* الرصيد التراكمي = رصيد أول المدة + صافي المستخلص − التحصيلات.
* إجماليات: رصيد أول المدة، صافي المستخلص، التحصيلات، المتبقي، وكل قيمة نسبة.
* كروت إجمالي قيمة العقد والدفعة المقدمة منه ونسبتها والمخصوم على المستخلصات والمتبقي.
* زر «تحديد أعمدة الجدول» زي تقرير المستخلصات.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.services.contractor_statement_report_service import (
    ALL_ACCOUNTS,
    KIND_EXTRACT,
    KIND_PAYMENT,
    _with_accounts,
    account_timeline,
    build_accounts,
    build_statement,
    contract_advance,
    empty_statement,
)
from app.ui.screens.contractor_statement_report_screen import (
    COLUMN_KEYS,
    COLUMNS,
    DEFAULT_COLUMNS,
    ROW_EXTRACT,
    ROW_OPENING,
    ROW_PAYMENT,
    ROW_TOTAL,
    ContractorStatementReportScreen,
    payment_text,
)
from app.ui.screens.contracting_report_base import share_widths

NAME = "م. أحمد عبد الرحمن"


def _extract(extract_id, date, works, other="0"):
    return {"extract_id": extract_id, "extract_no": f"A-H/CT-1001/EX-0{extract_id}",
            "extract_date": datetime.date(*date), "contract_id": 100, "contractor_name": NAME,
            "works_value": Decimal(works), "vat_pct": Decimal("14"), "advance_payment_pct": Decimal("10"),
            "withholding_tax_pct": Decimal("1"), "works_insurance_pct": Decimal("5"),
            "social_insurance_pct": Decimal("0"), "other_deductions": Decimal(other)}


def _payment(payment_id, date, amount, method="نقدي", reference=None, extract_no=None):
    return {"payment_id": payment_id, "payment_date": datetime.date(*date), "amount": Decimal(amount),
            "payment_method": method, "reference_no": reference, "extract_no": extract_no, "contractor_name": NAME}


EXTRACTS = [_extract(1, (2026, 2, 15), "456000"), _extract(2, (2026, 3, 25), "228000", other="1000")]
PAYMENTS = [
    _payment(9, (2026, 1, 10), "30000"),
    _payment(10, (2026, 3, 1), "100000", "تحويل", "784512", "A-H/CT-1001/EX-01"),
    _payment(11, (2026, 3, 25), "50000"),  # same day as EX-02: after it
]
CONTRACTS = [{"contract_id": 100, "contract_value": Decimal("2000000"), "advance_payment_pct": Decimal("10")}]
OPENING = Decimal("85000")
# نوع الحساب (2026-10-07): the card's opening per type, and a تأمين أعمال payment.
CARD = {"current_balance": OPENING, "works_insurance_amount": Decimal("2000"), "social_insurance_amount": Decimal("750")}
WORKS_PAYMENT = dict(_payment(12, (2026, 4, 1), "5000"), account_type="تأمين أعمال")
FROM, TO = datetime.date(2026, 2, 1), datetime.date(2026, 12, 31)


# -- the arithmetic ------------------------------------------------------------------------


def test_extract_line_has_every_amount_of_the_extracts_screen():
    line = build_statement(0, EXTRACTS[:1], [])["lines"][0]
    assert line["kind"] == KIND_EXTRACT
    assert line["before_tax"] == Decimal("400000.00")       # 456,000 ÷ 1.14
    assert line["vat_amount"] == Decimal("56000.00")        # «الضرائب الخاصة»
    assert line["advance_payment"] == Decimal("45600.00")
    assert line["withholding_tax"] == Decimal("4000.00")
    assert line["works_insurance"] == Decimal("22800.00")
    assert line["net"] == Decimal("383600.00")              # VAT is not deducted
    assert line["paid"] == 0


def test_running_balance_over_the_period():
    statement = build_statement(OPENING, EXTRACTS, PAYMENTS, FROM, TO)
    # The January payment falls before «من»: 85,000 − 30,000.
    assert statement["opening"] == Decimal("55000.00")
    lines = statement["lines"]
    assert [line["kind"] for line in lines] == [KIND_EXTRACT, KIND_PAYMENT, KIND_EXTRACT, KIND_PAYMENT]
    assert [line["balance"] for line in lines] == [Decimal("438600.00"), Decimal("338600.00"),
                                                   Decimal("529400.00"), Decimal("479400.00")]
    totals = statement["totals"]
    assert totals["net"] == Decimal("574400.00")
    assert totals["paid"] == Decimal("150000.00")
    assert totals["balance"] == totals["opening"] + totals["net"] - totals["paid"] == Decimal("479400.00")
    assert totals["advance_payment"] == Decimal("68400.00")
    assert (totals["extracts_count"], totals["payments_count"]) == (2, 2)


def test_all_periods_start_from_the_contractors_balance():
    statement = build_statement(OPENING, EXTRACTS, PAYMENTS)
    assert statement["opening"] == OPENING
    assert statement["lines"][0]["payment_id"] == 9
    assert statement["totals"]["balance"] == Decimal("479400.00")  # same end, longer road


def test_lines_after_the_period_are_left_out():
    statement = build_statement(OPENING, EXTRACTS, PAYMENTS, FROM, datetime.date(2026, 3, 10))
    assert len(statement["lines"]) == 2
    assert statement["totals"]["balance"] == Decimal("338600.00")


def test_contract_advance():
    figures = contract_advance(CONTRACTS, EXTRACTS)
    assert figures["contract_value"] == Decimal("2000000.00")
    assert figures["advance_agreed"] == Decimal("200000.00")
    assert figures["advance_pct"] == Decimal("10")
    assert figures["advance_deducted"] == Decimal("68400.00")
    assert figures["remaining_advance"] == Decimal("131600.00")
    # Up to «إلى»: only the first extract had taken its share.
    assert contract_advance(CONTRACTS, EXTRACTS, datetime.date(2026, 3, 10))["advance_deducted"] == Decimal("45600.00")


def test_payment_text():
    assert payment_text(PAYMENTS[1] | {"kind": KIND_PAYMENT}) == "دفعة تحويل 784512 — A-H/CT-1001/EX-01"
    assert payment_text(PAYMENTS[2] | {"kind": KIND_PAYMENT}) == "دفعة نقدي — عامة"


# -- the screen -----------------------------------------------------------------------------


class FakeService:
    def __init__(self):
        self.last_filters = None

    def company_choices(self):
        return [{"company_id": 10, "company_code": "C10", "company_name": "الأفق للتطوير"}]

    def project_choices(self, company_id=None):
        return []

    def contractor_choices(self):
        return [{"contractor_id": 1, "contractor_code": "D1", "contractor_name": NAME},
                {"contractor_id": 2, "contractor_code": "D2", "contractor_name": "الصفا للكهرباء"}]

    def statement(self, **filters):
        self.last_filters = filters
        if filters["contractor_id"] != 1:
            return empty_statement()
        accounts = build_accounts(CARD, EXTRACTS, PAYMENTS + [WORKS_PAYMENT], filters["date_from"], filters["date_to"])
        return _with_accounts(accounts, contract_advance(CONTRACTS, EXTRACTS, filters["date_to"]))


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "report.ini"), QSettings.IniFormat)


@pytest.fixture
def screen(qt_app, settings):
    widget = ContractorStatementReportScreen(FakeService(), settings=settings)
    widget.resize(1700, 900)
    yield widget
    widget.close()


def _visible(table):
    return [key for i, key in enumerate(COLUMN_KEYS) if not table.isColumnHidden(i)]


def _cell(screen, row, key):
    item = screen.table.item(row, COLUMN_KEYS.index(key))
    return item.text() if item else ""


def test_opens_on_the_first_contractor(screen):
    assert screen.contractor_combo.currentData() == 1
    assert screen.service.last_filters["contractor_id"] == 1


def test_the_users_columns_in_order(screen):
    assert len(COLUMNS) == 20  # the user's 19 + «نوع الحساب» (2026-10-07)
    assert [header.replace("\n", " ") for _k, header, _t in COLUMNS[:5]] == [
        "التاريخ", "اسم المقاول", "رقم المستخلص", "نوع الحساب", "إجمالي المستخلص"]
    assert COLUMN_KEYS[-3:] == ("net", "paid", "balance")
    assert len(DEFAULT_COLUMNS) == 15  # every column but the five rates
    assert _visible(screen.table) == list(DEFAULT_COLUMNS)


def test_rows_start_with_the_opening_balance(screen):
    assert screen.row_kinds == [ROW_OPENING, ROW_PAYMENT, ROW_EXTRACT, ROW_PAYMENT, ROW_EXTRACT, ROW_PAYMENT,
                                ROW_TOTAL]
    assert "رصيد أول المدة" in _cell(screen, 0, "date")
    assert _cell(screen, 0, "balance") == "85,000.00"
    assert _cell(screen, 1, "extract_no") == "دفعة نقدي — عامة"
    assert _cell(screen, 1, "net") == ""          # a payment has no extract amounts
    assert _cell(screen, 2, "net") == "383,600.00"
    assert _cell(screen, 2, "paid") == ""
    assert _cell(screen, 3, "paid") == "100,000.00"
    assert _cell(screen, 5, "balance") == "479,400.00"
    assert _cell(screen, 6, "balance") == "479,400.00"
    assert _cell(screen, 6, "advance_payment") == "68,400.00"
    assert _cell(screen, 6, "paid") == "180,000.00"  # «كل الفترات»: the January payment too


def test_the_cards(screen):
    values = {key: label.text() for key, label in screen.card_values.items()}
    assert values == {
        ("رصيد جاري", "opening"): "85,000.00", ("رصيد جاري", "held"): "574,400.00",
        ("رصيد جاري", "paid"): "180,000.00", ("رصيد جاري", "balance"): "479,400.00",
        # تأمين الأعمال: 2,000 on the card + 5% of 456,000 and 228,000 − the 5,000 payment.
        ("تأمين أعمال", "opening"): "2,000.00", ("تأمين أعمال", "held"): "34,200.00",
        ("تأمين أعمال", "paid"): "5,000.00", ("تأمين أعمال", "balance"): "31,200.00",
        ("تأمينات اجتماعية", "opening"): "750.00", ("تأمينات اجتماعية", "held"): "0.00",
        ("تأمينات اجتماعية", "paid"): "0.00", ("تأمينات اجتماعية", "balance"): "750.00",
        ("contracts", "contract_value"): "2,000,000.00", ("contracts", "advance_agreed"): "200,000.00",
        ("contracts", "advance_deducted"): "68,400.00", ("contracts", "remaining_advance"): "131,600.00"}
    assert "10%" in screen.card_hints["contracts"].text()
    assert "1 دفعات" in screen.card_hints["تأمين أعمال"].text()


def test_period_moves_older_lines_into_the_opening_balance(screen):
    screen.all_dates.setChecked(False)
    screen.date_from.setDate(FROM)
    screen.date_to.setDate(TO)
    screen.run_report()
    assert screen.card_values[("رصيد جاري", "opening")].text() == "55,000.00"
    assert "قبل 2026-02-01" in _cell(screen, 0, "date")
    assert screen.row_kinds.count(ROW_PAYMENT) == 2


def test_column_chooser_hides_and_remembers(screen, settings):
    screen.set_visible_columns([key for key in COLUMN_KEYS if key not in ("date", "contractor_name")])
    assert screen.table.isColumnHidden(COLUMN_KEYS.index("date"))
    assert "رصيد أول المدة" in _cell(screen, 0, "extract_no")  # the label moves to a visible column
    again = ContractorStatementReportScreen(FakeService(), settings=settings)
    assert "date" not in again.visible_columns and "vat_pct" in again.visible_columns
    again.close()


def test_no_contractor_no_statement(screen):
    screen.contractor_combo.setCurrentIndex(0)  # «الكل»
    screen.run_report()
    assert screen.table.rowCount() == 0
    assert "اختار المقاول" in screen.count_label.text()


# -- column widths (user, 2026-10-02) ---------------------------------------------------------


def test_share_widths():
    assert share_widths([100, 100, 100], 900) == [300, 300, 300]          # equal shares
    assert share_widths([500, 100, 100], 900) == [500, 200, 200]          # a wide one keeps its need
    assert share_widths([600, 400], 900) == [600, 400]                    # too wide: needs, and the table scrolls
    assert sum(share_widths([90, 90, 90], 1000)) == 1000                  # no pixel lost to rounding


def test_a_few_columns_share_the_width(screen):
    screen.show()
    screen.set_visible_columns(["date", "contractor_name", "net", "paid", "balance"])
    header = screen.table.horizontalHeader()
    widths = [header.sectionSize(COLUMN_KEYS.index(key)) for key in ("date", "contractor_name", "net", "paid")]
    assert max(widths) - min(widths) <= 1                                 # the name no longer takes it all
    shown = sum(header.sectionSize(i) for i in range(len(COLUMN_KEYS)) if not screen.table.isColumnHidden(i))
    assert shown == screen.table.viewport().width()



# -- one statement per نوع الحساب (user, 2026-10-07) -----------------------------------------------


def test_each_account_type_opens_on_its_card_field_and_counts_its_own_payments():
    accounts = build_accounts(CARD, EXTRACTS, PAYMENTS + [WORKS_PAYMENT])
    current, works, social = accounts["رصيد جاري"], accounts["تأمين أعمال"], accounts["تأمينات اجتماعية"]
    assert current["totals"]["balance"] == Decimal("479400.00")  # the تأمين payment does not touch it
    assert [line["kind"] for line in works["lines"]] == [KIND_EXTRACT, KIND_EXTRACT, KIND_PAYMENT]
    assert [line["balance"] for line in works["lines"]] == [Decimal("24800.00"), Decimal("36200.00"),
                                                            Decimal("31200.00")]
    assert works["totals"]["held"] == Decimal("34200.00") and works["totals"]["paid"] == Decimal("5000.00")
    assert social["opening"] == Decimal("750.00") and social["totals"]["balance"] == Decimal("750.00")
    assert works["lines"][0]["account_type"] == ALL_ACCOUNTS and works["lines"][2]["account_type"] == "تأمين أعمال"


def test_a_payment_without_a_type_is_current_balance():
    untyped = {k: v for k, v in WORKS_PAYMENT.items() if k != "account_type"}
    accounts = build_accounts(CARD, [], [untyped])
    assert accounts["رصيد جاري"]["totals"]["paid"] == Decimal("5000.00")
    assert accounts["تأمين أعمال"]["totals"]["paid"] == 0


def test_the_timeline_moves_three_balances():
    points = account_timeline(build_accounts(CARD, EXTRACTS, PAYMENTS + [WORKS_PAYMENT]))
    assert points[0]["balances"] == {"رصيد جاري": Decimal("85000.00"), "تأمين أعمال": Decimal("2000.00"),
                                     "تأمينات اجتماعية": Decimal("750.00")}
    assert len(points) == 1 + 2 + 4  # the openings, 2 extracts, 3 رصيد جاري + 1 تأمين payment
    assert points[-1]["balances"]["رصيد جاري"] == Decimal("479400.00")
    assert points[-1]["balances"]["تأمين أعمال"] == Decimal("31200.00")


def test_one_tab_per_account_type(screen):
    tabs = screen.account_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["الرصيد الجاري", "تأمين الأعمال", "التأمينات الاجتماعية"]
    assert _cell(screen, 2, "account_type") == ALL_ACCOUNTS and _cell(screen, 1, "account_type") == "رصيد جاري"
    tabs.setCurrentIndex(1)
    assert screen.row_kinds == [ROW_OPENING, ROW_EXTRACT, ROW_EXTRACT, ROW_PAYMENT, ROW_TOTAL]
    assert "تأمين الأعمال في بطاقة المقاول" in _cell(screen, 0, "date")
    assert _cell(screen, 0, "balance") == "2,000.00"
    assert _cell(screen, 3, "account_type") == "تأمين أعمال" and _cell(screen, 3, "paid") == "5,000.00"
    assert _cell(screen, 4, "balance") == "31,200.00"
    assert "تأمين الأعمال" in screen.count_label.text()
    tabs.setCurrentIndex(0)
    assert screen.row_kinds.count(ROW_PAYMENT) == 3


def test_the_chart_draws_three_lines(screen):
    assert set(screen.chart.series) == {"رصيد جاري", "تأمين أعمال", "تأمينات اجتماعية"}
    assert screen.chart.series["تأمين أعمال"][-1] == 31200.0


def test_account_type_column_joins_an_older_saved_choice(qt_app, settings):
    from app.ui.screens.contracting_report_base import save_columns

    save_columns(settings, "contractor_statement_report/columns", ["date", "net", "balance"])  # before 2026-10-07
    widget = ContractorStatementReportScreen(FakeService(), settings=settings)
    assert widget.visible_columns == ("date", "account_type", "net", "balance")
    widget.set_visible_columns(["date", "net", "balance"])  # hidden on purpose: stays hidden
    again = ContractorStatementReportScreen(FakeService(), settings=settings)
    assert again.visible_columns == ("date", "net", "balance")
    widget.close()
    again.close()
