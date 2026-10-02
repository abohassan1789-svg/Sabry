"""Widget tests for شاشة عقود المقاولين — النموذجان 7 و8 كتبويبين (headless Qt, no database).

Covers what the user asked for:

* The screen has two tabs: the company → project → contracts tree (نموذج 7)
  and the contractor's card with his contracts (نموذج 8).
* A contract has a date, a contractor, a company + project, a value and four
  percentages; each percentage's amount is computed live, and الصافي is the
  value less works insurance, taxes and social insurance.
* Numbers «A-H/CT-<n>» start at 1001, are suggested, and stay editable.
* مسودة / معتمد (2026-10-02): «حفظ» keeps a draft, «اعتماد» / «إلغاء الاعتماد»
  move it, and an approved contract is locked except for an admin.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.contractor_contract_service import (
    ContractError,
    ContractorContractService,
    contract_amounts,
    next_contract_no_from,
    to_decimal,
)
from app.ui.screens import contractor_contracts_screen as screen_module
from app.ui.screens.contractor_contracts_screen import (
    TAB_CONTRACTOR,
    TAB_TREE,
    ContractorContractsScreen,
)

CONTRACTORS = [
    {"contractor_id": 1, "contractor_code": "A-H/CD-1001", "contractor_name": "أحمد للمقاولات", "contractor_type": "مقاول"},
    {"contractor_id": 2, "contractor_code": "A-H/CD-1002", "contractor_name": "البناء الحديث", "contractor_type": "مقاول"},
]
COMPANIES = [
    {"company_id": 1, "company_code": "A-H/CO-1001", "company_name": "شركة الأهرام"},
    {"company_id": 2, "company_code": "A-H/CO-1002", "company_name": "مجموعة النيل"},
]
PROJECTS = {
    1: [{"project_id": 10, "project_code": "A-H/CO-1001/PR-01", "project_name": "برج الأهرام"},
        {"project_id": 11, "project_code": "A-H/CO-1001/PR-02", "project_name": "كمبوند الياسمين"}],
    2: [{"project_id": 20, "project_code": "A-H/CO-1002/PR-01", "project_name": "أبراج النيل"}],
}
PROJECT_COMPANY = {10: 1, 11: 1, 20: 2}


def _contract(contract_id, number, contractor_id, project_id, value, rates, status="draft"):
    company_id = PROJECT_COMPANY[project_id]
    project = next(p for p in PROJECTS[company_id] if p["project_id"] == project_id)
    company = next(c for c in COMPANIES if c["company_id"] == company_id)
    contractor = next(c for c in CONTRACTORS if c["contractor_id"] == contractor_id)
    adv, ins, tax, soc = rates
    return {
        "contract_id": contract_id, "contract_no": number, "contract_date": datetime.date(2026, 9, 1),
        "contractor_id": contractor_id, "project_id": project_id, "contract_value": Decimal(value),
        "advance_payment_pct": Decimal(adv), "works_insurance_pct": Decimal(ins),
        "tax_discount_pct": Decimal(tax), "social_insurance_pct": Decimal(soc),
        "contractor_code": contractor["contractor_code"], "contractor_name": contractor["contractor_name"],
        "project_code": project["project_code"], "project_name": project["project_name"],
        "company_id": company_id, "company_code": company["company_code"], "company_name": company["company_name"],
        "status": status,
    }


CONTRACTS = {
    100: _contract(100, "A-H/CT-1001", 1, 11, "2500000", ("10", "5", "1", "2"), status="approved"),
    101: _contract(101, "A-H/CT-1002", 2, 20, "4800000", ("15", "5", "1", "2")),
    102: _contract(102, "A-H/CT-1003", 1, 10, "1200000", ("10", "10", "1", "2")),
}


class FakeService:
    def __init__(self):
        self.saved = []
        self.deleted = []
        self.approved = []
        self.unapproved = []
        self.allow_approved = []

    def contractor_choices(self):
        return [dict(c) for c in CONTRACTORS]

    def company_choices(self):
        return [dict(c) for c in COMPANIES]

    def project_choices(self, company_id):
        return [dict(p) for p in PROJECTS.get(company_id, [])]

    def contracts(self, keyword="", contractor_id=None):
        rows = [dict(c) for c in CONTRACTS.values()]
        if contractor_id is not None:
            rows = [c for c in rows if c["contractor_id"] == contractor_id]
        if keyword:
            rows = [c for c in rows if keyword in c["contract_no"] or keyword in c["contractor_name"]]
        return rows

    def tree(self, keyword=""):
        contracts = self.contracts(keyword)
        out = []
        for company in COMPANIES:
            projects = []
            for project in PROJECTS[company["company_id"]]:
                kids = [c for c in contracts if c["project_id"] == project["project_id"]]
                projects.append(dict(project, contracts=kids))
            out.append(dict(company, projects=projects))
        return out

    def get_contract(self, contract_id):
        record = CONTRACTS.get(int(contract_id))
        return dict(record) if record else None

    def contractor_card(self, contractor_id):
        contractor = next(c for c in CONTRACTORS if c["contractor_id"] == contractor_id)
        mine = [c for c in CONTRACTS.values() if c["contractor_id"] == contractor_id]
        return dict(contractor, phone=None, contract_count=len(mine),
                    total_value=sum(c["contract_value"] for c in mine),
                    total_advance=sum(c["contract_value"] * c["advance_payment_pct"] / 100 for c in mine))

    def next_contract_no(self):
        return "A-H/CT-1004"

    def save_contract(self, data, contract_id=None, allow_approved=False):
        self.saved.append((dict(data), contract_id))
        self.allow_approved.append(allow_approved)
        return contract_id or 100

    def delete_contract(self, contract_id, allow_approved=False):
        self.deleted.append(contract_id)
        self.allow_approved.append(allow_approved)

    def approve(self, contract_id, user_id=None):
        self.approved.append(contract_id)

    def unapprove(self, contract_id):
        self.unapproved.append(contract_id)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name, lambda *a, **k: None)
    monkeypatch.setattr(screen_module.QMessageBox, "question",
                        lambda *a, **k: screen_module.QMessageBox.Yes)
    return ContractorContractsScreen(FakeService())


# --- numbers and amounts ------------------------------------------------------------

@pytest.mark.parametrize("codes,expected", [
    ([], "A-H/CT-1001"),
    (["A-H/CT-1001", " a-h/ct-1007 "], "A-H/CT-1008"),
    (["X", None, "A-H/CD-1500"], "A-H/CT-1001"),
])
def test_next_contract_no(codes, expected):
    assert next_contract_no_from(codes) == expected


def test_amounts_and_net_leave_the_advance_payment_out():
    amounts = contract_amounts("2,500,000.00", {"advance_payment_pct": 10, "works_insurance_pct": 5,
                                                "tax_discount_pct": 1, "social_insurance_pct": 2})
    assert amounts["advance_payment_pct"] == Decimal("250000.00")
    assert amounts["works_insurance_pct"] == Decimal("125000.00")
    assert amounts["tax_discount_pct"] == Decimal("25000.00")
    assert amounts["social_insurance_pct"] == Decimal("50000.00")
    assert amounts["deductions"] == Decimal("200000.00")
    assert amounts["net"] == Decimal("2300000.00")


def test_to_decimal_reads_typed_numbers():
    assert to_decimal("1,234.50") == Decimal("1234.50")
    assert to_decimal("10 %") == Decimal("10")
    assert to_decimal("") == Decimal("0")
    assert to_decimal("abc") == Decimal("0")


class _NoDb:
    def fetch_one(self, *_a, **_k):
        return None


@pytest.mark.parametrize("change,message", [
    ({"contract_no": " "}, "رقم العقد"),
    ({"contractor_id": None}, "المقاول"),
    ({"project_id": None}, "المشروع"),
    ({"contract_value": "0"}, "قيمة العقد"),
    ({"tax_discount_pct": "120"}, "الضرائب"),
])
def test_save_refuses_incomplete_contracts(change, message):
    data = {"contract_no": "A-H/CT-1001", "contract_date": "2026-09-01", "contractor_id": 1,
            "project_id": 10, "contract_value": "1000", "advance_payment_pct": 10,
            "works_insurance_pct": 5, "tax_discount_pct": 1, "social_insurance_pct": 2}
    data.update(change)
    with pytest.raises(ContractError, match=message):
        ContractorContractService(_NoDb()).save_contract(data)


# --- the two tabs ---------------------------------------------------------------------

def test_the_screen_has_both_mockups_as_tabs(screen):
    assert screen.tabs.count() == 2
    assert "نموذج 7" in screen.tabs.tabText(TAB_TREE)
    assert "نموذج 8" in screen.tabs.tabText(TAB_CONTRACTOR)


def test_the_tree_holds_companies_projects_and_contracts(screen):
    assert {("company", 1), ("company", 2), ("project", 10), ("project", 11), ("project", 20),
            ("contract", 100), ("contract", 101), ("contract", 102)} <= set(screen._tree_items)


def test_clicking_a_contract_in_the_tree_fills_both_forms(screen):
    screen._on_tree_clicked(screen._tree_items[("contract", 100)], 0)
    assert screen.current_id == 100
    for form in screen.forms:
        assert form.contract_no.text() == "A-H/CT-1001"
        assert form.project.currentData() == 11
        assert form.company.currentData() == 1
        assert form.contractor.currentData() == 1
        assert form.amounts["advance_payment_pct"].text() == "250,000.00"
        assert form.contract_no.isReadOnly()
    assert screen.contractor_picker.currentData() == 1


def test_the_contractor_tab_shows_only_his_contracts_and_totals(screen):
    screen.tabs.setCurrentIndex(TAB_CONTRACTOR)
    screen.contractor_picker.setCurrentIndex(screen.contractor_picker.findData(1))
    assert set(screen._cards) == {100, 102}
    assert screen.stat_labels["count"].text() == "2"
    assert screen.stat_labels["total"].text() == "3,700,000.00"
    assert screen.stat_labels["advance"].text() == "370,000.00"


def test_picking_another_contractor_opens_his_first_contract(screen):
    screen.load_contract(100)
    screen.contractor_picker.setCurrentIndex(screen.contractor_picker.findData(2))
    assert set(screen._cards) == {101}
    assert screen.current_id == 101


# --- new / save / delete ----------------------------------------------------------------

def test_new_from_a_tree_project_preselects_it(screen):
    screen.tree.setCurrentItem(screen._tree_items[("project", 20)])
    screen.new_contract()
    form = screen.tree_form
    assert screen.mode == "new"
    assert form.contract_no.text() == "A-H/CT-1004" and not form.contract_no.isReadOnly()
    assert form.company.currentData() == 2 and form.project.currentData() == 20


def test_new_from_the_contractor_tab_uses_the_picked_contractor(screen):
    screen.tabs.setCurrentIndex(TAB_CONTRACTOR)
    screen.contractor_picker.setCurrentIndex(screen.contractor_picker.findData(2))
    screen.new_contract()
    assert screen.card_form.contractor.currentData() == 2
    assert not screen.tabs.tabBar().isEnabled()  # tabs lock while editing
    assert screen.tree_form.contract_no.isReadOnly()  # only the front tab's form is editable


def test_changing_the_company_narrows_the_projects(screen):
    screen.new_contract()
    form = screen.tree_form
    form.company.setCurrentIndex(form.company.findData(2))
    assert [form.project.itemData(i) for i in range(form.project.count())] == [20]


def test_amounts_update_while_typing(screen):
    screen.new_contract()
    form = screen.tree_form
    form.contract_value.setText("1000000")
    form.rates["works_insurance_pct"].setValue(5)
    form.rates["social_insurance_pct"].setValue(2.5)
    assert form.amounts["works_insurance_pct"].text() == "50,000.00"
    assert form.amounts["social_insurance_pct"].text() == "25,000.00"


def test_saving_a_new_contract_sends_every_field(screen):
    screen.tree.setCurrentItem(screen._tree_items[("project", 10)])
    screen.new_contract()
    form = screen.tree_form
    form.contractor.setCurrentIndex(form.contractor.findData(2))
    form.contract_value.setText("750000")
    form.rates["advance_payment_pct"].setValue(10)
    screen.save_record()
    data, record_id = screen.service.saved[-1]
    assert record_id is None
    assert data["contract_no"] == "A-H/CT-1004"
    assert data["contractor_id"] == 2 and data["project_id"] == 10
    assert data["contract_value"] == "750000"
    assert data["advance_payment_pct"] == Decimal("10.0")
    assert screen.mode == "view"


def test_edit_then_cancel_restores_the_contract(screen):
    screen.load_contract(101)
    screen.edit_record()
    screen.tree_form.contract_value.setText("1")
    screen.cancel_edit()
    assert screen.tree_form.contract_value.text() == "4,800,000.00"
    assert screen.mode == "view"


def test_selection_is_blocked_while_editing(screen):
    screen.load_contract(101)
    screen.edit_record()
    screen._on_tree_clicked(screen._tree_items[("contract", 102)], 0)
    assert screen.current_id == 101


def test_delete_removes_the_contract_and_clears_the_forms(screen):
    screen.load_contract(102)
    screen.delete_record()
    assert screen.service.deleted == [102]
    assert screen.current_id is None
    assert screen.tree_form.contract_no.text() == ""


def test_deductions_total_and_net_are_not_shown(screen):
    """The user asked to hide إجمالي الاستقطاعات and الصافي from both tabs."""
    for form in screen.forms:
        assert not hasattr(form, "net_label") and not hasattr(form, "deductions_label")


# --- مسودة / معتمد --------------------------------------------------------------------------

def test_a_draft_can_be_edited_deleted_and_approved(screen):
    screen.load_contract(101)
    assert screen.approval.badge.text() == "مسودة"
    assert screen.edit_button.isEnabled() and screen.delete_button.isEnabled()
    assert screen.approval.approve_button.isEnabled()
    assert not screen.approval.unapprove_button.isEnabled()
    screen.approve_record()
    assert screen.service.approved == [101]


def test_an_approved_contract_is_locked_until_unapproved(screen):
    screen.load_contract(100)
    assert screen.approval.badge.text() == "معتمد"
    assert not screen.edit_button.isEnabled()
    assert not screen.delete_button.isEnabled()
    assert not screen.approval.approve_button.isEnabled()
    assert screen.approval.unapprove_button.isEnabled()
    screen.edit_record()
    assert screen.mode == "view"
    screen.delete_record()
    assert screen.service.deleted == []
    screen.unapprove_record()
    assert screen.service.unapproved == [100]


def test_an_admin_may_edit_and_delete_an_approved_contract(screen):
    screen.approval.is_admin = True
    screen.load_contract(100)
    assert screen.edit_button.isEnabled() and screen.delete_button.isEnabled()
    screen.edit_record()
    screen.save_record()
    assert screen.service.allow_approved[-1] is True
    screen.load_contract(100)
    screen.delete_record()
    assert screen.service.deleted == [100]


def test_approve_and_unapprove_follow_their_own_permissions(screen):
    screen.approval.can_approve = False
    screen.load_contract(101)
    assert not screen.approval.approve_button.isEnabled()
    screen.approve_record()
    assert screen.service.approved == []
    screen.approval.can_unapprove = False
    screen.load_contract(100)
    assert not screen.approval.unapprove_button.isEnabled()


def test_drafts_are_marked_in_the_tree(screen):
    assert "مسودة" in screen._tree_items[("contract", 101)].text(0)
    assert "مسودة" not in screen._tree_items[("contract", 100)].text(0)


def test_the_buttons_are_off_while_editing(screen):
    screen.load_contract(101)
    screen.edit_record()
    assert not screen.approval.approve_button.isEnabled()
    assert not screen.approval.unapprove_button.isEnabled()


# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_announces_a_change(screen, data_changes):
    screen.load_contract(101)
    screen.edit_record()
    screen.save_record()
    assert data_changes == [screen]


def test_cancel_announces_nothing(screen, data_changes):
    screen.load_contract(101)
    screen.edit_record()
    screen.cancel_edit()
    assert data_changes == []


def test_delete_and_approve_announce_a_change(screen, data_changes):
    screen.load_contract(101)
    screen.approve_record()
    screen.load_contract(102)
    screen.delete_record()
    assert data_changes == [screen, screen]


def test_reload_lists_shows_a_contractor_approved_elsewhere(screen, monkeypatch):
    screen.load_contract(101)
    extra = {"contractor_id": 9, "contractor_code": "A-H/CD-1009", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.reload_lists()
    assert screen.tree_form.contractor.findData(9) >= 0
    assert screen.current_id == 101  # the open contract stays open


def test_reload_lists_keeps_the_tree_scroll_position(screen):
    """Review fix: a reload must not jump the tree back to the top."""
    screen.show()
    screen.tree.setFixedHeight(70)
    QApplication.processEvents()
    bar = screen.tree.verticalScrollBar()
    assert bar.maximum() > 0, "the fake tree must be taller than the box"
    screen.load_contract(102)  # a contract low in the tree
    bar.setValue(0)  # the user scrolled back up to look at something else
    screen.reload_lists()
    QApplication.processEvents()
    assert bar.value() == 0
    screen.hide()


def test_reload_after_the_first_contractor_is_approved_does_not_crash(qt_app, monkeypatch):
    """Review fix: rebuilding the contractor tab crashed on its «no contractor» caption."""
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name, lambda *a, **k: None)
    service = FakeService()
    real = service.contractor_choices
    service.contractor_choices = lambda: []  # a fresh database: nobody approved yet
    screen = ContractorContractsScreen(service)
    service.contractor_choices = real  # one approved in «المقاولين»
    screen.reload_lists()
    assert screen.contractor_picker.count() == len(CONTRACTORS)
