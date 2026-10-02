"""Tests for شاشة مستخلصات المقاولين — النموذجان 8 و9 كتبويبين (headless Qt, no database).

The user's rules:

* إجمالي المستخلص → صافي الأعمال = الأعمال ÷ (1 + الضريبة)، الضريبة 14% افتراضياً.
* المقدمة / تأمين الأعمال (5% افتراضياً) / التأمينات = الأعمال × النسبة؛
  ضريبة الخصم = صافي الأعمال × النسبة؛ الخصم (0/1/3/5) والتأمينات
  (0/0.365/2.8/3.6) قوائم.
* الصافي = الأعمال − المقدمة − ض.الخصم − تأمين الأعمال − التأمينات − خصومات أخرى.
* رقم العقد يعرض بيانات العقد للعلم فقط؛ نسبة المقدمة تبدأ من العقد.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.contractor_extract_service import (
    ContractorExtractService,
    ExtractError,
    advance_balance,
    contract_progress,
    extract_amounts,
    next_extract_no_from,
)
from app.ui.screens import contractor_extracts_screen as screen_module
from app.ui.screens.contractor_extracts_screen import TAB_CARDS, TAB_KPI, ContractorExtractsScreen

CONTRACTORS = [
    {"contractor_id": 1, "contractor_code": "A-H/CD-1001", "contractor_name": "أحمد للمقاولات", "contractor_type": "مقاول"},
    {"contractor_id": 2, "contractor_code": "A-H/CD-1002", "contractor_name": "البناء الحديث", "contractor_type": "مقاول"},
]
CONTRACTS = {
    100: {"contract_id": 100, "contract_no": "A-H/CT-1001", "contractor_id": 1, "contract_value": Decimal("2500000"),
          "advance_payment_pct": Decimal("10"), "works_insurance_pct": Decimal("5"), "tax_discount_pct": Decimal("1"),
          "social_insurance_pct": Decimal("2"), "contractor_code": "A-H/CD-1001", "contractor_name": "أحمد للمقاولات",
          "contractor_type": "مقاول", "project_name": "كمبوند الياسمين", "company_name": "شركة الأهرام",
          "contract_date": datetime.date(2026, 9, 1), "project_id": 11},
    101: {"contract_id": 101, "contract_no": "A-H/CT-1002", "contractor_id": 2, "contract_value": Decimal("4800000"),
          "advance_payment_pct": Decimal("15"), "works_insurance_pct": Decimal("5"), "tax_discount_pct": Decimal("3"),
          "social_insurance_pct": Decimal("3.6"), "contractor_code": "A-H/CD-1002", "contractor_name": "البناء الحديث",
          "contractor_type": "مقاول", "project_name": "أبراج النيل", "company_name": "مجموعة النيل",
          "contract_date": datetime.date(2026, 9, 5), "project_id": 20},
}


def _extract(extract_id, contract_id, number, works, other="0", adv="10", wht="1", soc="3.6", day=5):
    contract = CONTRACTS[contract_id]
    return {"extract_id": extract_id, "extract_no": number, "extract_date": datetime.date(2026, 9, day),
            "contract_id": contract_id, "works_value": Decimal(works), "vat_pct": Decimal("14"),
            "advance_payment_pct": Decimal(adv), "withholding_tax_pct": Decimal(wht),
            "works_insurance_pct": Decimal("5"), "social_insurance_pct": Decimal(soc),
            "other_deductions": Decimal(other), "contract_no": contract["contract_no"],
            "contractor_id": contract["contractor_id"], "contractor_name": contract["contractor_name"]}


EXTRACTS = {
    500: _extract(500, 100, "A-H/CT-1001/EX-01", "342000", day=5),
    501: _extract(501, 100, "A-H/CT-1001/EX-02", "570000", other="2000", day=15),
    510: _extract(510, 101, "A-H/CT-1002/EX-01", "1140000", adv="15", wht="3", day=20),
}


class FakeService:
    """Every extract is approved, except the ids in *drafts*."""

    def __init__(self, drafts=()):
        self.saved = []
        self.deleted = []
        self.drafts = set(drafts)
        self.approved = []
        self.unapproved = []

    def _row(self, record):
        return dict(record, status="draft" if record["extract_id"] in self.drafts else "approved")

    def contractor_choices(self):
        return [dict(c) for c in CONTRACTORS]

    def contract_choices(self, contractor_id=None):
        rows = [dict(c) for c in CONTRACTS.values()]
        return [c for c in rows if contractor_id is None or c["contractor_id"] == contractor_id]

    def get_contract(self, contract_id):
        contract = CONTRACTS.get(contract_id)
        return dict(contract) if contract else None

    def extracts(self, contract_id):
        return [self._row(x) for x in EXTRACTS.values() if x["contract_id"] == contract_id]

    def get_extract(self, extract_id):
        record = EXTRACTS.get(extract_id)
        return self._row(record) if record else None

    def next_extract_no(self, contract_id):
        return {100: "A-H/CT-1001/EX-03", 101: "A-H/CT-1002/EX-02"}[contract_id]

    def save_extract(self, data, extract_id=None, allow_approved=False):
        self.saved.append((dict(data), extract_id))
        return extract_id or 501

    def delete_extract(self, extract_id, allow_approved=False):
        self.deleted.append(extract_id)

    def approve(self, extract_id, user_id=None):
        self.approved.append(extract_id)

    def unapprove(self, extract_id):
        self.unapproved.append(extract_id)

    def search_extracts(self, keyword=""):
        rows = []
        for x in EXTRACTS.values():
            contract = CONTRACTS[x["contract_id"]]
            row = dict(x, project_name=contract["project_name"], company_name=contract["company_name"],
                       net_works=extract_amounts(x)["before_tax"])
            text = " ".join(str(row[k]) for k in ("contractor_name", "extract_no", "contract_no",
                                                  "project_name", "company_name"))
            if keyword in text:
                rows.append(row)
        return rows


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name, lambda *a, **k: None)
    monkeypatch.setattr(screen_module.QMessageBox, "question",
                        lambda *a, **k: screen_module.QMessageBox.Yes)
    return ContractorExtractsScreen(FakeService())


@pytest.fixture
def draft_screen(screen):
    """The same screen with EX-02 (501, the one it opens on) as a draft."""
    screen.service.drafts = {501}
    screen.refresh_all()
    return screen


# --- the arithmetic ---------------------------------------------------------------------

def test_the_users_formulas():
    amounts = extract_amounts({"works_value": "570,000.00", "vat_pct": 14, "advance_payment_pct": 10,
                               "withholding_tax_pct": 1, "works_insurance_pct": 5, "social_insurance_pct": "3.6",
                               "other_deductions": "2,000"})
    assert amounts["before_tax"] == Decimal("500000.00")        # 570,000 ÷ 1.14
    assert amounts["vat_amount"] == Decimal("70000.00")
    assert amounts["advance_payment"] == Decimal("57000.00")     # × الأعمال
    assert amounts["withholding_tax"] == Decimal("5000.00")      # × صافي الأعمال
    assert amounts["works_insurance"] == Decimal("28500.00")
    assert amounts["social_insurance"] == Decimal("20520.00")
    assert amounts["other_deductions"] == Decimal("2000.00")
    assert amounts["net"] == Decimal("456980.00")


def test_changing_the_tax_rate_changes_the_total_before_tax():
    assert extract_amounts({"works_value": 1100, "vat_pct": 10})["before_tax"] == Decimal("1000.00")
    assert extract_amounts({"works_value": 1100, "vat_pct": 0})["before_tax"] == Decimal("1100.00")


@pytest.mark.parametrize("codes,expected", [
    ([], "A-H/CT-1001/EX-01"),
    (["A-H/CT-1001/EX-01", " a-h/ct-1001/ex-07 "], "A-H/CT-1001/EX-08"),
    (["A-H/CT-1002/EX-05", "X"], "A-H/CT-1001/EX-01"),
])
def test_next_extract_no_starts_with_the_contract_no(codes, expected):
    assert next_extract_no_from("A-H/CT-1001", codes) == expected


def test_contract_progress():
    progress = contract_progress(Decimal("2500000"), [EXTRACTS[500], EXTRACTS[501]])
    assert progress["works_total"] == Decimal("912000")
    assert progress["remaining"] == Decimal("1588000")
    assert progress["count"] == 2
    assert round(progress["percent"], 2) == Decimal("36.48")


class _NoDb:
    def fetch_one(self, *_a, **_k):
        return None


@pytest.mark.parametrize("change,message", [
    ({"extract_no": ""}, "رقم المستخلص"),
    ({"contract_id": None}, "رقم العقد"),
    ({"works_value": "0"}, "إجمالي المستخلص"),
    ({"withholding_tax_pct": "101"}, "ضرائب الخصم"),
    ({"social_insurance_pct": "-1"}, "التأمينات"),
    ({"vat_pct": "140"}, "الضريبة"),
])
def test_save_refuses_bad_extracts(change, message):
    data = {"extract_no": "A-H/CT-1001/EX-01", "extract_date": "2026-09-25", "contract_id": 100,
            "works_value": "1000", "vat_pct": 14, "advance_payment_pct": 10, "withholding_tax_pct": 1,
            "works_insurance_pct": 5, "social_insurance_pct": "3.6", "other_deductions": 0}
    data.update(change)
    with pytest.raises(ExtractError, match=message):
        ContractorExtractService(_NoDb()).save_extract(data)


# --- the two tabs -------------------------------------------------------------------------

def test_both_mockups_are_tabs(screen):
    assert "نموذج 8" in screen.tabs.tabText(TAB_CARDS)
    assert "نموذج 9" in screen.tabs.tabText(TAB_KPI)


def test_opens_on_the_first_contract_and_its_latest_extract(screen):
    assert screen.contract_id == 100
    assert set(screen._cards) == {500, 501}
    assert screen.current_id == 501
    for form in screen.forms:
        assert form.extract_no.text() == "A-H/CT-1001/EX-02"
        assert form.before_tax.text() == "500,000.00"
        assert form.amounts["withholding_tax"].text() == "5,000.00"
        assert form.net_label.text() == "456,980.00"
        assert "شركة الأهرام" in form.contract_info.text()  # the contract, for reference


def test_kpis_and_history_follow_the_contract(screen):
    assert screen.kpis["done"].text() == "912,000.00"
    assert screen.kpis["remaining"].text() == "1,588,000.00"
    assert screen.card_stats["count"].text() == "2"
    assert screen.history.rowCount() == 3  # two extracts + the totals row


def test_picking_a_contract_in_one_tab_moves_the_other(screen):
    screen.tabs.setCurrentIndex(TAB_KPI)
    screen.contract_picker_b.setCurrentIndex(screen.contract_picker_b.findData(101))
    assert screen.contract_id == 101 and screen.current_id == 510
    assert screen.contractor_picker.currentData() == 2
    assert screen.contract_picker_a.currentData() == 101
    assert set(screen._cards) == {510}


def test_clicking_a_card_loads_that_extract(screen):
    screen._cards[500].click()
    assert screen.current_id == 500
    assert screen.card_form.works_value.text() == "342,000.00"


# --- new / save / delete ------------------------------------------------------------------------

def test_new_extract_takes_the_defaults(screen):
    screen.new_extract()
    form = screen.card_form
    assert screen.mode == "new"
    assert form.extract_no.text() == "A-H/CT-1001/EX-03"
    assert form.vat_pct.value() == 14
    assert form.rates["works_insurance_pct"].value() == 5
    assert form.rates["advance_payment_pct"].value() == 10          # from the contract
    assert form.rates["withholding_tax_pct"].currentText() == "1%"   # the contract's rates,
    assert form.rates["social_insurance_pct"].currentText() == "2%"  # in the list or not
    assert not screen.tabs.tabBar().isEnabled()


def test_changing_the_contract_while_new_reseeds_it(screen):
    screen.new_extract()
    screen.contract_picker_a.setEnabled(True)
    screen.contractor_picker.setCurrentIndex(screen.contractor_picker.findData(2))
    form = screen.card_form
    assert screen.contract_id == 101 and screen.mode == "new"
    assert form.extract_no.text() == "A-H/CT-1002/EX-02"
    assert form.rates["advance_payment_pct"].value() == 15
    assert form.rates["withholding_tax_pct"].currentText() == "3%"
    assert form.rates["social_insurance_pct"].currentText() == "3.6%"


def test_amounts_update_while_typing(screen):
    screen.new_extract()
    form = screen.card_form
    form.works_value.setText("114000")
    form.rates["withholding_tax_pct"].setCurrentIndex(form.rates["withholding_tax_pct"].findData("5"))
    form.other_deductions.setText("1000")
    assert form.before_tax.text() == "100,000.00"
    assert form.amounts["withholding_tax"].text() == "5,000.00"
    # 114,000 − 11,400 − 5,000 − 5,700 − 2,280 (the contract's 2%) − 1,000
    assert form.net_label.text() == "88,620.00"


def test_list_rates_take_a_typed_value(screen):
    screen.new_extract()
    form = screen.card_form
    combo = form.rates["social_insurance_pct"]
    assert [combo.itemText(i) for i in range(combo.count())] == ["0%", "0.365%", "2.8%", "3.6%"]
    form.works_value.setText("100000")
    combo.setEditText("1.5")
    assert form.amounts["social_insurance"].text() == "1,500.00"
    combo.lineEdit().editingFinished.emit()
    assert combo.currentText() == "1.5%"
    assert form.values()["social_insurance_pct"] == Decimal("1.5")
    combo.setCurrentIndex(combo.findData("2.8"))  # the list still works
    assert form.values()["social_insurance_pct"] == Decimal("2.8")
    assert combo.lineEdit().validator().validate("abc", 0)[0].name != "Acceptable"


def test_saving_a_new_extract_sends_the_inputs(screen):
    screen.new_extract()
    form = screen.card_form
    form.works_value.setText("228000")
    screen.save_record()
    data, record_id = screen.service.saved[-1]
    assert record_id is None and data["contract_id"] == 100
    assert data["extract_no"] == "A-H/CT-1001/EX-03"
    assert data["works_value"] == "228000"
    assert data["vat_pct"] == Decimal("14.0")
    assert data["withholding_tax_pct"] == Decimal("1")
    assert screen.mode == "view"


def test_edit_keeps_the_extracts_contract_and_locks_the_pickers(draft_screen):
    screen = draft_screen
    screen.edit_record()
    assert not screen.contract_picker_a.isEnabled()
    screen.save_record()
    data, record_id = screen.service.saved[-1]
    assert record_id == 501 and data["contract_id"] == 100


def test_selection_is_blocked_while_editing(draft_screen):
    screen = draft_screen
    screen.edit_record()
    screen._on_extract_clicked(500)
    assert screen.current_id == 501


def test_delete(draft_screen):
    screen = draft_screen
    screen.delete_record()
    assert screen.service.deleted == [501]


# --- رصيد الدفعة المقدمة (user request: each extract's advance comes off the contract's) ---

def test_advance_balance_counts_only_earlier_extracts():
    contract = CONTRACTS[100]  # 2,500,000 × 10% = 250,000 advanced
    rows = [EXTRACTS[500], EXTRACTS[501]]  # 34,200 then 57,000
    second = advance_balance(contract, rows, EXTRACTS[501])
    assert second == {"agreed": Decimal("250000.00"), "previous": Decimal("34200.00"),
                      "this": Decimal("57000.00"), "remaining": Decimal("158800.00")}
    first = advance_balance(contract, rows, EXTRACTS[500])
    assert first["previous"] == 0 and first["remaining"] == Decimal("215800.00")
    new = dict(EXTRACTS[501], extract_id=None, extract_no="A-H/CT-1001/EX-03",
               extract_date=datetime.date(2026, 9, 25), works_value=Decimal("100000"))
    third = advance_balance(contract, rows, new)
    assert third["previous"] == Decimal("91200.00") and third["remaining"] == Decimal("148800.00")


def test_advance_balance_goes_negative_when_overdrawn():
    contract = dict(CONTRACTS[100], contract_value=Decimal("100000"))  # 10,000 advanced
    balance = advance_balance(contract, [], dict(EXTRACTS[500], extract_id=None))
    assert balance["remaining"] == Decimal("-24200.00")


def test_both_tabs_show_the_advance_balance(screen):
    for form in screen.forms:  # EX-02 is open
        assert form.advance_cells["agreed"].text() == "250,000.00"
        assert form.advance_cells["previous"].text() == "34,200.00"
        assert form.advance_cells["this"].text() == "57,000.00"
        assert form.advance_cells["remaining"].text() == "158,800.00"
        assert form.advance_warning.isHidden()


def test_new_extract_takes_off_the_remaining_advance(screen):
    from PySide6.QtCore import QDate
    screen.new_extract()
    form = screen.card_form
    form.extract_date.setDate(QDate(2026, 9, 25))
    form.works_value.setText("100000")
    assert form.advance_cells["previous"].text() == "91,200.00"
    assert form.advance_cells["this"].text() == "10,000.00"
    assert form.advance_cells["remaining"].text() == "148,800.00"
    form.works_value.setText("5000000")  # 500,000 advance > 158,800 left
    assert not form.advance_warning.isHidden()
    assert "341,200.00" in form.advance_warning.text()


# --- «بحث» (F1) -----------------------------------------------------------------------------

def test_search_dialog_has_the_users_columns_and_filters(qt_app):
    from app.ui.dialogs.contractor_extract_picker import ContractorExtractPickerDialog
    dialog = ContractorExtractPickerDialog(FakeService().search_extracts)
    headers = [dialog.table.horizontalHeaderItem(i).text() for i in range(dialog.table.columnCount())]
    assert headers == ["اسم المقاول", "رقم المستخلص", "إجمالي المستخلص", "صافي الأعمال",
                       "رقم العقد", "اسم المشروع", "اسم الشركة"]
    assert dialog.table.rowCount() == 3
    dialog.search_text.setText("مجموعة النيل")
    dialog._accept_if_unambiguous()  # one hit + Enter opens it
    assert dialog.selected["extract_id"] == 510
    assert dialog.table.item(0, 3).text() == "1,000,000.00"  # 1,140,000 ÷ 1.14


def test_search_opens_the_chosen_extract_on_its_contract(screen, monkeypatch):
    class Picked:
        Accepted = 1
        def __init__(self, search_fn, parent=None):
            self.selected = next(r for r in search_fn("") if r["extract_id"] == 510)
        def exec(self):
            return 1
    monkeypatch.setattr(screen_module, "ContractorExtractPickerDialog", Picked)
    screen.open_search()
    assert screen.contract_id == 101 and screen.current_id == 510
    assert screen.contract_picker_b.currentData() == 101


def test_search_is_blocked_while_editing(draft_screen):
    screen = draft_screen
    screen.edit_record()
    assert not screen.search_button.isEnabled()
    screen.open_search()  # F1 while editing: only the «احفظ أو ألغِ» message
    assert screen.current_id == 501


# --- مسودة / معتمد --------------------------------------------------------------------------

def test_a_draft_is_listed_but_left_out_of_the_figures(draft_screen):
    screen = draft_screen  # EX-02 (570,000) is a draft
    assert screen.kpis["done"].text() == "342,000.00"
    assert screen.card_stats["count"].text() == "1"
    assert screen.history.rowCount() == 3  # both extracts are listed + the totals row
    assert "مسودة" in screen.history.item(1, 0).text()
    assert "مسودة" not in screen.history.item(0, 0).text()
    assert set(screen._cards) == {500, 501}


def test_a_draft_takes_nothing_from_the_advance(draft_screen):
    draft_screen.new_extract()
    form = draft_screen.card_form
    from PySide6.QtCore import QDate
    form.extract_date.setDate(QDate(2026, 9, 25))
    form.works_value.setText("100000")
    assert form.advance_cells["previous"].text() == "34,200.00"  # EX-01 only


def test_approving_a_draft_extract(draft_screen):
    screen = draft_screen
    assert screen.current_id == 501 and screen.approval.badge.text() == "مسودة"
    assert screen.approval.approve_button.isEnabled()
    screen.approve_record()
    assert screen.service.approved == [501]


def test_an_approved_extract_is_locked(screen):
    assert screen.approval.badge.text() == "معتمد"
    assert not screen.edit_button.isEnabled() and not screen.delete_button.isEnabled()
    screen.edit_record()
    assert screen.mode == "view"
    screen.delete_record()
    assert screen.service.deleted == []
    assert screen.approval.unapprove_button.isEnabled()
    screen.unapprove_record()
    assert screen.service.unapproved == [501]


def test_an_admin_may_edit_an_approved_extract(screen):
    screen.approval.is_admin = True
    screen.set_mode("view")
    assert screen.edit_button.isEnabled() and screen.delete_button.isEnabled()


# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_and_deleting_announce_a_change(draft_screen, data_changes):
    screen = draft_screen
    screen.edit_record()
    screen.save_record()
    screen.delete_record()
    assert data_changes == [screen, screen]


def test_reload_lists_refreshes_the_pickers_but_never_mid_edit(screen, monkeypatch):
    extra = {"contractor_id": 9, "contractor_code": "A-H/CD-1009", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.new_extract()
    screen.reload_lists()  # «جديد»: untouched, and no «احفظ التعديلات» popup
    assert screen.mode == "new" and screen.contractor_picker.findData(9) < 0
    screen.cancel_edit()
    screen.reload_lists()
    assert screen.contractor_picker.findData(9) >= 0


def test_reload_keeps_a_picked_contractor_who_has_no_contracts_yet(screen, monkeypatch):
    """Review fix: the reload used to jump to the first contractor and contract."""
    extra = {"contractor_id": 9, "contractor_code": "A-H/CD-1009", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.reload_lists()
    screen.contractor_picker.setCurrentIndex(screen.contractor_picker.findData(9))
    assert screen.contract_id is None
    screen.reload_lists()
    assert screen.contractor_picker.currentData() == 9
    assert screen.contract_id is None


def test_first_open_shows_a_contract_even_when_the_first_contractor_has_none(qt_app, monkeypatch):
    """Review fix: keeping «the picked contractor» must not apply to index 0 picked by default."""
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name, lambda *a, **k: None)
    service = FakeService()
    first = {"contractor_id": 9, "contractor_code": "A-H/CD-1000", "contractor_name": "بدون عقود"}
    choices = service.contractor_choices
    service.contractor_choices = lambda: [first, *choices()]
    screen = ContractorExtractsScreen(service)
    assert screen.contract_id == 100


def test_the_first_contract_approved_for_another_contractor_opens_after_a_reload(qt_app, monkeypatch):
    """Review fix: a fresh database opens on contractor index 0 with nothing to show; that
    default is not the user's pick, so B's first approved contract must open on reload."""
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name, lambda *a, **k: None)
    service = FakeService()
    real = service.contract_choices
    service.contract_choices = lambda contractor_id=None: []  # no approved contract yet
    screen = ContractorExtractsScreen(service)
    assert screen.contract_id is None
    service.contract_choices = lambda contractor_id=None: [
        c for c in real(contractor_id) if c["contractor_id"] == 2]  # contractor 2's contract approved
    screen.reload_lists()
    assert screen.contract_id == 101


def test_a_contract_unapproved_elsewhere_is_closed_on_reload(screen, monkeypatch):
    """Review fix: a draft contract must not stay open (a new extract could be saved on it)."""
    assert screen.contract_id == 100
    real = screen.service.contract_choices
    monkeypatch.setattr(screen.service, "contract_choices",
                        lambda contractor_id=None: [c for c in real(contractor_id) if c["contract_id"] != 100])
    screen.reload_lists()
    assert screen.contract_id is None
    assert screen.contractor_picker.currentData() == 1  # still on its contractor


def test_no_open_contract_leaves_the_contract_list_unselected(screen, monkeypatch):
    """Review fix: with no contract open, the «all contracts» list must not show another one."""
    real = screen.service.contract_choices
    monkeypatch.setattr(screen.service, "contract_choices",
                        lambda contractor_id=None: [c for c in real(contractor_id) if c["contract_id"] != 100])
    screen.reload_lists()
    assert screen.contract_id is None
    assert screen.contract_picker_b.currentIndex() == -1


def test_a_contract_missing_from_a_stale_list_does_not_show_another_one(screen):
    """Review fix: opening a contract the «all contracts» list doesn't have yet must not
    leave that list on someone else's contract."""
    picker = screen.contract_picker_b
    picker.removeItem(picker.findData(101))  # the list predates contract 101's approval
    screen.set_contract(101)
    assert screen.contract_id == 101
    assert picker.currentIndex() == -1
