"""Tests for داشبورد المقاولين — نموذجا 9 و 8 as tabs (headless Qt, no database).

What the user asked each section to show (2026-10-02):

* المقاولين: العدد، الرصيد الجاري، ضرائب الخصم والإضافة، التأمينات، تأمين الأعمال، الخصومات الأخرى.
* الشركات والمشاريع: عدد الشركات وعدد المشاريع لكل شركة.
* العقود: العدد، أكبر عقد (المقاول والقيمة)، الدفعات المقدمة، تأمين الأعمال، الضرائب والخصومات، التأمينات.
* المستخلصات: صافي الأعمال، إجمالي المستخلص، المقدمة، ضرائب الخصم، تأمين الأعمال، التأمينات، الخصومات الأخرى.
* الدفعات: إجمالي المدفوع، أكبر مقاول أخد فلوس، وكارت لكل نوع حساب (2026-10-14).
* فلتر بين تاريخين، الشركة، المشروع، المقاول.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.contractor_statement_report_service import (
    _with_accounts,
    build_accounts,
    contract_advance,
    withholding_total,
)
from app.services.contractors_dashboard_service import account_figures, build_dashboard, empty_dashboard
from app.ui.screens.contractors_dashboard_screen import TAB_DARK, TAB_LEADERS, ContractorsDashboardScreen

AHMED, SAFA, BENAA = "م. أحمد عبد الرحمن", "الصفا للكهرباء", "البناء الحديث"

CONTRACTORS = [
    {"contractor_id": 1, "contractor_name": AHMED, "contractor_type": "مقاول", "current_balance": Decimal("85000"),
     "withholding_tax_amount": Decimal("12500"), "social_insurance_amount": Decimal("4200"),
     "works_insurance_amount": Decimal("22500"), "other_deductions_amount": Decimal("1200")},
    {"contractor_id": 2, "contractor_name": SAFA, "contractor_type": "مورد", "current_balance": Decimal("0"),
     "withholding_tax_amount": Decimal("8300"), "social_insurance_amount": Decimal("11900"),
     "works_insurance_amount": Decimal("9250"), "other_deductions_amount": Decimal("2500")},
]
COMPANIES = [{"company_id": 10, "company_code": "C10", "company_name": "الأفق للتطوير"},
             {"company_id": 11, "company_code": "C11", "company_name": "الدلتا العقارية"}]
PROJECTS = [{"project_id": 1, "company_id": 10}, {"project_id": 2, "company_id": 10}, {"project_id": 3, "company_id": 11}]
CONTRACTS = [
    {"contract_id": 1, "contract_no": "A-H/CT-1001", "contract_value": Decimal("2400000"), "contractor_name": AHMED,
     "project_name": "برج الأفق", "advance_payment_pct": Decimal("10"), "works_insurance_pct": Decimal("5"),
     "tax_discount_pct": Decimal("1"), "social_insurance_pct": Decimal("0.365")},
    {"contract_id": 2, "contract_no": "A-H/CT-1007", "contract_value": Decimal("6200000"), "contractor_name": BENAA,
     "project_name": "مستشفى المستقبل", "advance_payment_pct": Decimal("12"), "works_insurance_pct": Decimal("5"),
     "tax_discount_pct": Decimal("1"), "social_insurance_pct": Decimal("3.6")},
]


def _extract(name, works, other="0"):
    return {"contractor_name": name, "works_value": Decimal(works), "vat_pct": Decimal("14"),
            "advance_payment_pct": Decimal("10"), "withholding_tax_pct": Decimal("1"),
            "works_insurance_pct": Decimal("5"), "social_insurance_pct": Decimal("0"),
            "other_deductions": Decimal(other)}


EXTRACTS = [_extract(AHMED, "456000"), _extract(SAFA, "228000", other="1000")]
PAYMENTS = [
    {"contractor_name": AHMED, "amount": Decimal("100000"), "payment_method": "تحويل", "account_type": "دفعة مقدمة"},
    {"contractor_name": SAFA, "amount": Decimal("150000"), "payment_method": "شيك", "account_type": "رصيد جاري"},
    {"contractor_name": AHMED, "amount": Decimal("80000"), "payment_method": "نقدي", "account_type": "رصيد جاري"},
]


def _dashboard():
    return build_dashboard(CONTRACTORS, COMPANIES, PROJECTS, CONTRACTS, EXTRACTS, PAYMENTS)


# -- the arithmetic ------------------------------------------------------------------------


def test_contractors_figures():
    c = _dashboard()["contractors"]
    assert c["count"] == 2
    assert c["balance"] == Decimal("85000.00")
    assert c["withholding_tax"] == Decimal("20800.00")
    assert c["social_insurance"] == Decimal("16100.00")
    assert c["works_insurance"] == Decimal("31750.00")
    assert c["other_deductions"] == Decimal("3700.00")
    assert c["deductions"] == Decimal("72350.00")
    assert c["types"]["مقاول"] == 1 and c["types"]["مورد"] == 1


def test_projects_per_company():
    companies = _dashboard()["companies"]
    assert companies["count"] == 2 and companies["projects"] == 3
    assert companies["per_company"] == [("الأفق للتطوير", 2), ("الدلتا العقارية", 1)]


def test_contracts_figures_and_the_biggest():
    k = _dashboard()["contracts"]
    assert k["count"] == 2
    assert k["value"] == Decimal("8600000.00")
    assert k["advance"] == Decimal("240000.00") + Decimal("744000.00")
    assert k["works_insurance"] == Decimal("430000.00")
    assert k["tax"] == Decimal("86000.00")
    assert k["social"] == Decimal("8760.00") + Decimal("223200.00")
    assert k["biggest"]["contractor_name"] == BENAA
    assert k["biggest"]["contract_value"] == Decimal("6200000.00")


def test_extracts_figures():
    x = _dashboard()["extracts"]
    assert x["count"] == 2
    assert x["works_value"] == Decimal("684000.00")
    assert x["before_tax"] == Decimal("600000.00")          # ÷ 1.14
    assert x["advance_payment"] == Decimal("68400.00")
    assert x["withholding_tax"] == Decimal("6000.00")        # on صافي الأعمال
    assert x["works_insurance"] == Decimal("34200.00")
    assert x["other_deductions"] == Decimal("1000.00")
    assert x["net"] == Decimal("684000") - Decimal("68400") - Decimal("6000") - Decimal("34200") - Decimal("1000")
    assert x["ranking"][0][0] == AHMED


def test_payments_top_payee_and_methods():
    d = _dashboard()
    p = d["payments"]
    assert p["total"] == Decimal("330000.00") and p["count"] == 3
    assert p["top"] == (AHMED, Decimal("180000.00"), 2)
    assert p["methods"]["شيك"] == (Decimal("150000.00"), 1)
    assert "remaining" not in p  # «المتبقي للمقاولين» is gone (user, 2026-10-14)


def _statement(date_from=None):
    """كشف حساب مقاول for «الكل» over the sample: cards + extracts + typed payments."""
    card = {"current_balance": Decimal("85000"), "works_insurance_amount": Decimal("22500"),
            "social_insurance_amount": Decimal("4200")}
    extracts = [{**x, "extract_id": i, "extract_date": datetime.date(2026, 3, i + 1)} for i, x in enumerate(EXTRACTS)]
    payments = [{**p, "payment_id": i, "payment_date": datetime.date(2026, 4, i + 1)} for i, p in enumerate(PAYMENTS)]
    payments.append({"contractor_name": SAFA, "amount": Decimal("5000"), "payment_method": "نقدي",
                     "account_type": "تأمين أعمال", "payment_id": 9, "payment_date": datetime.date(2026, 4, 9)})
    return _with_accounts(build_accounts(card, extracts, payments, date_from),
                          contract_advance(CONTRACTS, extracts, None, payments), withholding_total(0, extracts))


def test_each_account_type_has_due_paid_and_remaining():
    """The user (2026-10-14): a tile per نوع الحساب, worked out as كشف حساب مقاول does."""
    accounts = account_figures(_statement())
    assert list(accounts) == ["رصيد جاري", "تأمين أعمال", "تأمينات اجتماعية", "دفعة مقدمة"]
    net = _dashboard()["extracts"]["net"]
    current = accounts["رصيد جاري"]
    assert current["due"] == Decimal("85000.00") + net  # the cards + صافي المستخلصات
    assert current["paid"] == Decimal("230000.00")      # 150,000 + 80,000; not the advance one
    assert current["remaining"] == current["due"] - current["paid"]
    works = accounts["تأمين أعمال"]
    assert works["due"] == Decimal("22500.00") + Decimal("34200.00") and works["paid"] == Decimal("5000.00")
    assert accounts["تأمينات اجتماعية"]["due"] == Decimal("4200.00") and accounts["تأمينات اجتماعية"]["paid"] == 0
    advance = accounts["دفعة مقدمة"]
    # 2,400,000 × 10% + 6,200,000 × 12% = 984,000, less the 68,400 the extracts took back
    assert advance["due"] == Decimal("984000.00") - Decimal("68400.00")
    assert advance["paid"] == Decimal("100000.00")
    assert advance["remaining"] == Decimal("815600.00")


def test_a_period_moves_the_earlier_movements_into_the_due():
    """As the statement: what came before «من» is in رصيد أول المدة, so المتبقي is the same."""
    whole, later = account_figures(_statement()), account_figures(_statement(datetime.date(2026, 4, 3)))
    current = later["رصيد جاري"]
    assert current["paid"] == Decimal("80000.00")  # the 150,000 of 2 April went into the opening
    assert current["remaining"] == whole["رصيد جاري"]["remaining"]


def test_the_advance_total_adds_the_advance_payments():
    # The user (2026-10-13): the dashboard's advance also sums the «دفعة مقدمة» payments.
    a = _dashboard()["advance"]
    assert a["deducted"] == Decimal("68400.00") and a["paid_out"] == Decimal("100000.00")
    assert a["total"] == Decimal("168400.00")


def test_empty_dashboard():
    d = empty_dashboard()
    assert d["contracts"]["biggest"] is None
    assert d["payments"]["top"] is None
    assert all(figures["remaining"] == 0 for figures in d["accounts"].values())


# -- every filter narrows every section (user, 2026-10-14) -------------------------------------


class RecordingDb:
    """Answers nothing; keeps every query so the WHERE clauses can be checked."""

    def __init__(self):
        self.queries = []

    def fetch_all(self, sql, params=()):
        assert sql.count("%s") == len(params), sql
        self.queries.append((sql, list(params)))
        return []

    def fetch_one(self, sql, params=()):  # the statement's cards
        assert sql.count("%s") == len(params), sql
        self.queries.append((sql, list(params)))
        return {}


def _run(**filters):
    from app.services.contractors_dashboard_service import ContractorsDashboardService

    db = RecordingDb()
    service = ContractorsDashboardService.__new__(ContractorsDashboardService)
    service._db = db
    service.dashboard(**filters)
    # the contractors query, then the projects one
    return {"FROM contractors d": db.queries[0],
            "FROM company_projects p": next(q for q in db.queries if q[0].startswith("SELECT p.project_id"))}


def test_no_filter_counts_everyone():
    queries = _run()
    assert "UNION ALL" not in queries["FROM contractors d"][0]
    assert "UNION ALL" not in queries["FROM company_projects p"][0]


def test_a_period_keeps_the_contractors_and_projects_with_activity():
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 3, 31)
    queries = _run(date_from=start, date_to=end)
    for name in ("FROM contractors d", "FROM company_projects p"):
        sql, params = queries[name]
        for column in ("k.contract_date", "x.extract_date", "y.payment_date"):
            assert f"{column} >= %s" in sql and f"{column} <= %s" in sql
        assert params.count(start) == 3 and params.count(end) == 3


def test_a_contractor_keeps_only_his_companies_and_projects():
    sql, params = _run(contractor_id=7)["FROM company_projects p"]
    assert "a.contractor_id = %s" in sql and params == [7]


def test_a_company_keeps_the_contractors_with_activity_there():
    sql, params = _run(company_id=10)["FROM contractors d"]
    assert "UNION ALL" in sql and "p.company_id = %s" in sql and params == [10]


# -- the screen -----------------------------------------------------------------------------


class FakeService:
    def __init__(self):
        self.last_filters = None

    def company_choices(self):
        return COMPANIES

    def project_choices(self, company_id=None):
        return [{"project_id": 1, "project_code": "P1", "project_name": "برج الأفق", "company_id": 10}]

    def contractor_choices(self):
        return [{"contractor_id": 1, "contractor_code": "D1", "contractor_name": AHMED}]

    def dashboard(self, **filters):
        self.last_filters = filters
        if filters["contractor_id"] == 99:
            return empty_dashboard()
        return {**_dashboard(), "accounts": account_figures(_statement())}


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app):
    widget = ContractorsDashboardScreen(FakeService())
    widget.resize(1450, 830)
    yield widget
    widget.close()


def test_two_tabs_nine_then_eight(screen):
    assert screen.tabs.count() == 2
    assert "9" in screen.tabs.tabText(TAB_DARK) and "8" in screen.tabs.tabText(TAB_LEADERS)


def test_the_filter_bar(screen):
    screen.all_dates.setChecked(False)
    screen.run_report()
    filters = screen.service.last_filters
    assert set(filters) == {"date_from", "date_to", "company_id", "project_id", "contractor_id"}
    assert isinstance(filters["date_from"], datetime.date)


def test_dark_tab(screen):
    assert screen.hero["contractors"].value.text() == "2"
    assert screen.hero["companies"].value.text() == "2 شركات · 3 مشاريع"
    assert screen.dark["c_balance"].value.text() == "85,000.00"
    assert screen.dark["k_biggest"].value.text() == "6,200,000.00"
    assert screen.dark["k_biggest"].hint.text() == BENAA
    assert screen.dark["x_before_tax"].value.text() == "600,000.00"
    assert screen.dark["x_advance"].value.text() == "168,400.00"
    assert screen.dark["x_advance"].hint.text() == "منها دفعات مقدمة 100,000.00"
    assert screen.dark["x_advance"].toolTip() == "مستخلصات 68,400.00 + دفعات مقدمة 100,000.00"
    assert screen.dark["p_top"].value.text() == "180,000.00"
    assert AHMED in screen.dark["p_top"].hint.text()
    assert "p_remaining" not in screen.dark and "p_نقدي" not in screen.dark
    assert "دفعات شيك: 150,000.00 (1 دفعات)" in screen.dark["p_total"].toolTip()


def test_dark_tab_a_tile_per_account_type(screen):
    tiles = [screen.dark[f"a_{index}"] for index in range(4)]
    assert [tile.caption.text() for tile in tiles] == [
        "مدفوع — رصيد جاري", "مدفوع — تأمين أعمال", "مدفوع — تأمينات اجتماعية", "مدفوع — دفعة مقدمة"]
    assert tiles[0].value.text() == "230,000.00"
    assert tiles[3].value.text() == "100,000.00"
    assert tiles[3].hint.text() == "المستحق 915,600.00\nالمتبقي 815,600.00"
    assert "المخصوم على المستخلصات 68,400.00" in tiles[3].toolTip()
    assert tiles[1].toolTip().endswith("= المتبقي 51,700.00")


def test_leaders_tab(screen):
    assert screen.board_contracts.win_name.text() == BENAA
    assert screen.board_payments.win_name.text() == AHMED
    assert screen.board_payments.win_amount.text() == "180,000.00"
    assert screen.board_payments.rows[0].name.text() == SAFA
    assert not screen.board_payments.rows[1].isVisibleTo(screen)
    assert screen.minis["k_tax"].text() == "86,000.00"
    assert screen.minis["x_advance"].text() == "168,400.00"


def test_no_data(screen):
    screen.contractor_combo.addItem("x", 99)
    screen.contractor_combo.setCurrentIndex(screen.contractor_combo.count() - 1)
    screen.run_report()
    assert screen.dark["k_biggest"].value.text() == "—"
    assert screen.board_payments.win_name.text() == "—"


def test_fits_without_scrolling(screen):
    """Both tabs fit the content area (about 1450×830 beside the sidebar) with room to spare."""
    screen.show()
    QApplication.processEvents()
    assert screen.minimumSizeHint().height() <= 830
    for index in (TAB_DARK, TAB_LEADERS):
        page = screen.tabs.widget(index)
        assert page.minimumSizeHint().height() <= page.height()
