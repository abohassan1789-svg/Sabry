"""Widget tests for شاشة المقاولين — النموذج 4 (headless Qt, no database).

The screen is an identity banner over three cards, with the record list hidden
behind «بحث عن مقاول». These cover what the user asked for and what the shared
CRUD path would otherwise get wrong:

* كود المقاول is suggested as «A-H/CD-<next>» on «جديد» but stays editable, and
  a code another contractor already uses is refused with a message instead of a
  raw UniqueViolation.
* نوع المقاول offers exactly the four types and never a blank one.
* The deductions are amounts (not percentages), including الخصومات الأخرى, and
  a blank amount saves as zero — the columns are NOT NULL.
* The banner follows the boxes while the user types; there is no deductions
  total (the user asked for it to be hidden).
* The card titles sit on the card's right edge.
* The five count cards show the totals per نوع, and clicking one lists who is
  behind it; picking a row opens that contractor.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.contractor_service import next_code_from
from app.ui.screens import contractors_screen as screen_module
from app.ui.screens.contractors_screen import (
    DEDUCTION_FIELDS,
    ContractorsScreen,
    _money,
)

RECORDS = {
    1: {"contractor_code": "A-H/CD-1001", "contractor_name": "مؤسسة الفجر للمقاولات",
        "contractor_type": "مقاول", "registration_no": "245-118-907",
        "address": "المنصورة", "phone": "01001234567",
        "current_balance": Decimal("125000.00"), "vat_amount": Decimal("1400.00"),
        "withholding_tax_amount": Decimal("100.00"), "social_insurance_amount": Decimal("300.00"),
        "works_insurance_amount": Decimal("500.00"), "other_deductions_amount": Decimal("50.00")},
    2: {"contractor_code": "A-H/CD-1002", "contractor_name": "شركة النيل للدعاية",
        "contractor_type": "دعاية وإعلان", "registration_no": None, "address": None,
        "phone": None, "current_balance": Decimal("0"),
        **{name: Decimal("0") for name in DEDUCTION_FIELDS}},
}
LIST_ROWS = [
    {"contractor_id": 1, "contractor_code": "A-H/CD-1001", "contractor_name": "مؤسسة الفجر للمقاولات"},
    {"contractor_id": 2, "contractor_code": "A-H/CD-1002", "contractor_name": "شركة النيل للدعاية"},
]


class FakeService:
    """Stands in for ReviewDataService."""

    def __init__(self):
        self.saved = []

    def list_records(self, spec, keyword="", limit=500):
        return list(LIST_ROWS)

    def get_record(self, spec, record_id):
        return dict(RECORDS.get(int(record_id), {}))

    def next_id(self, spec):
        return 3

    def save_record(self, spec, payload, record_id):
        self.saved.append((dict(payload), record_id))
        return record_id or 3


class FakeBackend:
    """Stands in for ContractorService."""

    def __init__(self):
        self.taken = False
        self.statuses = {1: "approved", 2: "draft", 3: "draft"}
        self.approved = []
        self.unapproved = []

    def status(self, contractor_id):
        return self.statuses.get(int(contractor_id))

    def approve(self, contractor_id, user_id=None):
        self.approved.append(contractor_id)
        self.statuses[int(contractor_id)] = "approved"

    def unapprove(self, contractor_id):
        self.unapproved.append(contractor_id)
        self.statuses[int(contractor_id)] = "draft"

    def next_code(self):
        return "A-H/CD-1003"

    def code_taken(self, code, except_id=None):
        return self.taken

    def type_counts(self):
        return {"مقاول": 1, "دعاية وإعلان": 1, "": 2}

    def list_rows(self, contractor_type=None):
        self.listed = contractor_type
        return [dict(row, contractor_type=RECORDS[row["contractor_id"]]["contractor_type"])
                for row in LIST_ROWS
                if contractor_type in (None, RECORDS[row["contractor_id"]]["contractor_type"])]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    monkeypatch.setattr(screen_module.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(screen_module.QMessageBox, "warning", lambda *a, **k: None)
    from app.ui.screens import base_crud_screen

    monkeypatch.setattr(base_crud_screen.QMessageBox, "information", lambda *a, **k: None)
    # «اعتماد» / «إلغاء الاعتماد» ask first: answer yes.
    monkeypatch.setattr(screen_module.QMessageBox, "question", lambda *a, **k: screen_module.QMessageBox.Yes)
    backend = FakeBackend()
    monkeypatch.setattr(ContractorsScreen, "_backend", lambda self: backend)
    view = ContractorsScreen(FakeService())
    view._fake_backend = backend
    return view


# --- the code ------------------------------------------------------------------

@pytest.mark.parametrize("codes,expected", [
    ([], "A-H/CD-1001"),
    (["A-H/CD-1001", "A-H/CD-1002"], "A-H/CD-1003"),
    ([" a-h/cd-1009 ", "A-H/CD-1004"], "A-H/CD-1010"),
    (["X-5000", None, "A-H/CD-12"], "A-H/CD-1001"),
])
def test_next_code(codes, expected):
    assert next_code_from(codes) == expected


def test_new_suggests_the_next_code_and_it_stays_editable(screen):
    screen.new_record()
    code = screen.inputs["contractor_code"]
    assert code.text() == "A-H/CD-1003"
    assert code.isReadOnly() is False


def test_a_duplicate_code_is_refused_before_saving(screen):
    screen.new_record()
    screen.inputs["contractor_name"].setText("مقاول")
    screen._fake_backend.taken = True
    screen.save_record()
    assert screen.service.saved == []
    assert screen.mode == "new"


# --- type and amounts -----------------------------------------------------------

def test_the_type_offers_exactly_four_choices(screen):
    combo = screen.inputs["contractor_type"]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "مقاول", "مورد", "استشاري", "دعاية وإعلان"]


def test_new_record_defaults_the_type(screen):
    screen.new_record()
    assert screen.inputs["contractor_type"].currentText() == "مقاول"


def test_blank_amounts_save_as_zero(screen):
    screen.new_record()
    screen.inputs["contractor_name"].setText("مقاول جديد")
    screen.save_record()
    payload, record_id = screen.service.saved[-1]
    assert record_id is None
    assert payload["contractor_code"] == "A-H/CD-1003"
    for name in ("current_balance", *DEDUCTION_FIELDS):
        assert str(payload[name]) == "0"


def test_other_deductions_is_on_the_form(screen):
    assert "other_deductions_amount" in screen.inputs


# --- banner and total -------------------------------------------------------------

def test_the_first_contractor_is_loaded_on_open(screen):
    assert screen.current_id == 1
    assert screen._banner["name"].text() == "مؤسسة الفجر للمقاولات"
    assert screen._banner["code"].text() == "A-H/CD-1001"
    assert screen._banner["balance"].text() == "125,000.00"


def test_there_is_no_deductions_total(screen):
    from PySide6.QtWidgets import QLabel

    texts = [label.text() for label in screen.findChildren(QLabel)]
    assert not any("الاستقطاعات" in text for text in texts)


def test_card_titles_are_on_the_right_edge(screen):
    """«top left» is what lands on the right under the RTL layout."""
    from PySide6.QtWidgets import QGroupBox

    cards = [box for box in screen.findChildren(QGroupBox) if box.title() in screen_module.CARD_GROUPS]
    assert len(cards) == 3
    for card in cards:
        assert "subcontrol-position:top left" in card.styleSheet()


def test_the_banner_follows_typing(screen):
    screen.set_mode("edit")
    screen.inputs["contractor_name"].setText("اسم تاني")
    assert screen._banner["name"].text() == "اسم تاني"


def test_navigation_walks_the_hidden_list(screen):
    assert screen.list_panel.isVisibleTo(screen) is False
    screen._navigate("next")
    assert screen.current_id == 2
    assert screen._banner["kind"].text() == "دعاية وإعلان"


@pytest.mark.parametrize("value,expected", [
    (Decimal("125000"), "125,000.00"), ("-150.5", "150.50-"), ("", "0.00"), (None, "0.00")])
def test_money(value, expected):
    assert _money(value) == expected


# --- count cards -------------------------------------------------------------------

def test_the_five_count_cards(screen):
    shown = {key: label.text() for key, label in screen._stat_values.items()}
    assert shown == {"": "2", "مورد": "0", "مقاول": "1", "استشاري": "0", "دعاية وإعلان": "1"}


class _PickSecond:
    """Stands in for ContractorListDialog: records what it was given, picks row 2."""

    def __init__(self, title, rows, parent=None):
        _PickSecond.seen = (title, rows)
        self.selected = rows[-1]

    def exec(self):
        from PySide6.QtWidgets import QDialog

        return QDialog.Accepted


def test_clicking_a_card_lists_that_type_and_opens_the_pick(screen, monkeypatch):
    monkeypatch.setattr(screen_module, "ContractorListDialog", _PickSecond)
    screen._open_type_list("دعاية وإعلان", "الدعاية والإعلان")
    title, rows = _PickSecond.seen
    assert screen._fake_backend.listed == "دعاية وإعلان"
    assert title == "الدعاية والإعلان (1)"
    assert [row["contractor_id"] for row in rows] == [2]
    assert screen.current_id == 2
    assert screen._banner["name"].text() == "شركة النيل للدعاية"


def test_the_total_card_lists_everyone(screen, monkeypatch):
    monkeypatch.setattr(screen_module, "ContractorListDialog", _PickSecond)
    screen._open_type_list("", "كل السجلات")
    assert screen._fake_backend.listed is None
    assert len(_PickSecond.seen[1]) == 2


def test_the_list_dialog_filters_and_formats(qt_app):
    from app.ui.dialogs.contractor_list_dialog import ContractorListDialog

    rows = [dict(LIST_ROWS[0], contractor_type="مقاول", registration_no="245", phone="0100",
                 current_balance=Decimal("-150.5")),
            dict(LIST_ROWS[1], contractor_type="مورد", registration_no=None, phone=None,
                 current_balance=Decimal("0"))]
    dialog = ContractorListDialog("كل السجلات (2)", rows)
    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, 5).text() == "150.50-"
    dialog.search_text.setText("النيل")
    assert dialog.table.rowCount() == 1
    dialog.accept_selected()
    assert dialog.selected["contractor_id"] == 2


# --- مسودة / معتمد --------------------------------------------------------------------------

def _open(screen, contractor_id):
    screen._load_contractor(contractor_id)
    assert screen.current_id == contractor_id


def test_a_draft_contractor_can_be_approved(screen):
    _open(screen, 2)
    assert screen.approval.badge.text() == "مسودة"
    assert screen.approval.approve_button.isEnabled()
    assert not screen.approval.unapprove_button.isEnabled()
    screen.approve_record()
    assert screen._fake_backend.approved == [2]
    assert screen.approval.badge.text() == "معتمد"


def test_an_approved_contractor_is_edited_but_not_deleted(screen):
    _open(screen, 1)
    assert screen.approval.badge.text() == "معتمد"
    assert screen.edit_button.isEnabled()
    assert not screen.delete_button.isEnabled()
    assert screen.approval.unapprove_button.isEnabled()
    screen.unapprove_record()
    assert screen._fake_backend.unapproved == [1]
    assert screen.delete_button.isEnabled()


def test_an_admin_may_delete_an_approved_contractor(screen):
    screen.approval.is_admin = True
    _open(screen, 1)
    assert screen.delete_button.isEnabled()


def test_a_new_contractor_is_saved_as_a_draft(screen):
    screen.new_record()
    assert not screen.approval.approve_button.isEnabled()
    assert screen.approval.badge.isHidden()
    screen.current_id, screen.mode = 3, "view"
    assert "كمسودة" in screen._saved_message()


# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_and_approving_a_contractor_announce_a_change(screen, data_changes):
    screen.new_record()
    screen.inputs["contractor_name"].setText("مقاول جديد")
    screen.save_record()
    _open(screen, 2)
    screen.approve_record()
    assert data_changes == [screen, screen]


def test_delete_all_announces_a_change(screen, data_changes, monkeypatch):
    """Review fix: the admin «حذف الكل» must refresh the other screens too."""
    from app.ui.screens import base_crud_screen

    screen._perm_delete_all = True
    monkeypatch.setattr(base_crud_screen.QMessageBox, "warning",
                        lambda *a, **k: base_crud_screen.QMessageBox.Ok)
    monkeypatch.setattr(screen.service, "delete_all_records", lambda spec: 2, raising=False)
    screen.delete_all_records()
    assert data_changes == [screen]
