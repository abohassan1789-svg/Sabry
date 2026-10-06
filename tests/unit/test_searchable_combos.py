"""Drop lists searchable by any part of an item (user, 2026-10-07; headless Qt, no database).

The user's rule: typing any part of a name in a drop list filters it down to the items
that contain it. Phase 1 = the screens of «المقاولات» only.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QVBoxLayout, QWidget

from app.ui import main_window
from app.ui.common.searchable_combos import _ComboSearch, enable_combo_search, matches, normalize_search_text

NAMES = ["أحمد سعيد", "محمد علي", "مؤسسة الأمل", "شركة النور", "سعيد حسن", "علي أسامة", "مقاول البناء"]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _type(widget, text):
    # QTest.keyClicks crashes on Arabic strings in PySide; one key event per letter.
    for letter in text:
        QTest.sendKeyEvent(QTest.KeyAction.Click, widget, Qt.Key_unknown, letter, Qt.NoModifier)


def _shown(combo):
    return [combo.itemText(row) for row in range(combo.count()) if not combo.view().isRowHidden(row)]


@pytest.fixture
def combo(qt_app):
    host = QWidget()
    QVBoxLayout(host)
    box = QComboBox()
    host.layout().addWidget(box)
    box.addItem("", None)
    for index, name in enumerate(NAMES, start=1):
        box.addItem(name, index)
    enable_combo_search(host)
    host.resize(400, 300)
    host.show()
    qt_app.processEvents()
    yield box
    box.hidePopup()
    host.close()


# --- matching -------------------------------------------------------------------------------

def test_arabic_spelling_variants_match():
    assert normalize_search_text("أسامة") == normalize_search_text("اسامه")
    assert matches("مصطفى إبراهيم", "مصطفي ابراهيم")
    assert matches("مُحَمَّد", "محمد")
    assert matches("Ahmed Co", "co")
    assert not matches("محمد علي", "حسن")


# --- a pick-only list -----------------------------------------------------------------------

def test_typing_opens_the_list_with_only_the_matching_items(combo):
    _type(combo, "س")
    _type(combo.view(), "عيد")
    assert combo.view().isVisible()
    assert _shown(combo) == ["أحمد سعيد", "سعيد حسن"]
    assert combo.view().currentIndex().data() == "أحمد سعيد"
    assert combo.findChild(_ComboSearch).edit.text() == "سعيد"


def test_the_match_is_anywhere_in_the_name_and_enter_picks_it(combo):
    _type(combo, "اسامه")
    assert _shown(combo) == ["علي أسامة"]
    QTest.keyClick(combo.view(), Qt.Key_Return)
    assert not combo.view().isVisible()
    assert (combo.currentText(), combo.currentData()) == ("علي أسامة", 6)


def test_backspace_and_escape(combo):
    _type(combo, "زز")
    assert _shown(combo) == []
    QTest.keyClick(combo.view(), Qt.Key_Backspace)
    assert combo.findChild(_ComboSearch).text == "ز"
    QTest.keyClick(combo.view(), Qt.Key_Escape)  # first Esc clears the search
    assert combo.view().isVisible() and len(_shown(combo)) == len(NAMES) + 1
    QTest.keyClick(combo.view(), Qt.Key_Escape)  # the second closes the list
    assert not combo.view().isVisible() and combo.currentIndex() == 0


def test_reopening_shows_every_item_again(combo):
    _type(combo, "علي")
    QTest.keyClick(combo.view(), Qt.Key_Escape)
    QTest.keyClick(combo.view(), Qt.Key_Escape)
    combo.showPopup()
    assert len(_shown(combo)) == len(NAMES) + 1 and combo.findChild(_ComboSearch).edit.text() == ""


def test_the_popup_makes_room_for_the_matches(combo, qt_app):
    _type(combo, "سعيد")
    qt_app.processEvents()
    container = combo.view().parentWidget()
    view = combo.view()
    needed = sum(view.sizeHintForRow(row) for row in range(combo.count()) if not view.isRowHidden(row))
    assert view.height() >= needed
    assert container.geometry().top() >= combo.mapToGlobal(combo.rect().bottomLeft()).y()


def test_a_read_only_editable_list_is_searched_the_same_way(qt_app):
    host = QWidget()
    QVBoxLayout(host)
    box = QComboBox()
    box.setEditable(True)
    box.lineEdit().setReadOnly(True)
    box.addItems(NAMES)
    host.layout().addWidget(box)
    enable_combo_search(host)
    host.show()
    _type(box.lineEdit(), "نور")
    assert _shown(box) == ["شركة النور"]
    box.hidePopup()


def test_a_free_typing_list_gets_a_contains_completer(qt_app):
    host = QWidget()
    QVBoxLayout(host)
    box = QComboBox()
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.NoInsert)
    box.addItems(NAMES)
    host.layout().addWidget(box)
    enable_combo_search(host)
    assert box.completer().filterMode() == Qt.MatchContains


def test_lists_outside_an_enabled_screen_stay_as_they_were(qt_app):
    host = QWidget()
    QVBoxLayout(host)
    box = QComboBox()
    box.addItems(NAMES)
    host.layout().addWidget(box)
    host.show()
    qt_app.processEvents()
    assert box.findChild(_ComboSearch) is None
    _type(box, "م")
    assert not box.view().isVisible()


def test_a_list_can_opt_out(qt_app):
    host = QWidget()
    QVBoxLayout(host)
    box = QComboBox()
    box.setProperty("noSearch", True)
    host.layout().addWidget(box)
    enable_combo_search(host)
    assert box.findChild(_ComboSearch) is None


def test_a_dialog_of_an_enabled_screen_is_covered_too(qt_app):
    host = QWidget()
    enable_combo_search(host)
    dialog = QWidget(host, Qt.Dialog)
    QVBoxLayout(dialog)
    box = QComboBox()
    box.addItems(NAMES)
    dialog.layout().addWidget(box)
    dialog.show()
    qt_app.processEvents()
    assert box.findChild(_ComboSearch) is not None
    dialog.close()


# --- the screens covered: 1 = «المقاولات», 2 = «التقارير», 3 = dashboards + «النظام» ----------

def _visible_sidebar_keys(section_id):
    items = next(items for section, _t, _i, items in main_window.NAV_SECTIONS if section == section_id)
    return {key for key, _label, _icon in items if key not in main_window.HIDDEN_NAV_KEYS}


def test_every_screen_shown_in_the_sidebar_is_covered():
    reports = _visible_sidebar_keys("reports")
    assert reports == {
        "contractor_contracts_report", "contractor_extracts_report",
        "contractor_advance_report", "contractor_statement_report",
    }
    visible_sections = {
        section for section, _t, _i, _items in main_window.NAV_SECTIONS
        if section not in main_window.HIDDEN_NAV_SECTIONS
    }
    assert visible_sections == {"contracting", "reports", "system"}
    pinned = {"crm_dashboard", "executive_dashboard"}  # لوحة التحكم is enabled where it's built
    expected = pinned.union(*(_visible_sidebar_keys(section) for section in visible_sections))
    assert main_window.SEARCHABLE_COMBO_SCREENS == expected


def test_hidden_screens_are_not_covered():
    assert not main_window.SEARCHABLE_COMBO_SCREENS & main_window.HIDDEN_NAV_KEYS


def test_payments_screen_contractor_list_is_searchable(qt_app, monkeypatch):
    from tests.unit.test_contractor_payments_screen import FakeService
    from app.ui.screens import contractor_payments_screen as screen_module

    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name, lambda *a, **k: None)
    screen = screen_module.ContractorPaymentsScreen(FakeService())
    enable_combo_search(screen)
    screen.resize(1700, 860)
    screen.show()
    qt_app.processEvents()
    picker = screen.board_contractor
    picker.setFocus()
    _type(picker, "حديث")
    assert _shown(picker) == [picker.itemText(picker.findData(2))]
    QTest.keyClick(picker.view(), Qt.Key_Return)
    assert picker.currentData() == 2
    assert (screen.company_id, screen.project_id) == (20, 21)  # the screen's own cascade still runs
    screen.close()


def test_report_contractor_filter_is_searchable(qt_app, tmp_path):
    from PySide6.QtCore import QSettings

    from tests.unit.test_contractor_statement_report import FakeService
    from app.ui.screens.contractor_statement_report_screen import ContractorStatementReportScreen

    settings = QSettings(str(tmp_path / "report.ini"), QSettings.IniFormat)
    screen = ContractorStatementReportScreen(FakeService(), settings=settings)
    enable_combo_search(screen)
    screen.resize(1700, 900)
    screen.show()
    qt_app.processEvents()
    picker = screen.contractor_combo
    picker.setFocus()
    _type(picker, "الصفا")
    assert [text for text in _shown(picker) if text] == [picker.itemText(picker.findData(2))]
    QTest.keyClick(picker.view(), Qt.Key_Return)
    assert picker.currentData() == 2
    screen.close()


def test_letters_typed_while_the_list_rolls_open_are_kept(qt_app):
    """On Windows an editable list rolls open over ~150 ms instead of showing at once.
    The user's complaint (2026-10-07, شاشة المقاولين): typing on a closed list did
    nothing until an item had been picked from it once, because the letters typed
    before the list had finished opening were wiped when it appeared."""
    host = QWidget()
    QVBoxLayout(host)
    box = QComboBox()  # like the read-only choice lists of BaseCrudScreen
    box.setEditable(True)
    box.lineEdit().setReadOnly(True)
    box.addItem("", None)
    box.addItems(NAMES)
    host.layout().addWidget(box)
    enable_combo_search(host)
    host.resize(400, 300)
    host.show()
    box.showPopup = lambda: None  # still rolling open: not shown yet
    try:
        for letter in "سعيد":
            _type(box.lineEdit(), letter)
        assert not box.view().isVisible()
        QComboBox.showPopup(box)  # the animation ends: the list appears
        qt_app.processEvents()
        assert box.findChild(_ComboSearch).text == "سعيد"
        assert _shown(box) == ["أحمد سعيد", "سعيد حسن"]
    finally:
        box.hidePopup()
        host.close()


class _Anything:
    """A service stand-in: every call answers an empty list."""

    def __init__(self, **answers):
        self._answers = answers

    def __getattr__(self, name):
        return lambda *a, **k: self._answers.get(name, [])


def test_users_screen_role_list_is_searchable(qt_app):
    from app.ui.screens.users_page import UsersPage

    roles = [{"id": 1, "role_name_ar": "مدير النظام"}, {"id": 2, "role_name_ar": "محاسب"},
             {"id": 3, "role_name_ar": "مدخل بيانات"}]
    page = UsersPage(_Anything(), _Anything(list_roles=roles))
    enable_combo_search(page)
    page.show()
    page.set_mode("new")
    qt_app.processEvents()
    page.role_combo.setFocus()
    _type(page.role_combo, "بيان")
    assert _shown(page.role_combo) == ["مدخل بيانات"]
    QTest.keyClick(page.role_combo.view(), Qt.Key_Return)
    assert page.role_combo.currentData() == 3
    page.close()


def test_connection_settings_ssl_list_is_searchable_and_address_stays_free(qt_app):
    """إعدادات الاتصال: «وضع SSL» is searched; the server address accepts any text."""
    from app.ui.screens.connection_screen import ConnectionSettingsScreen

    screen = ConnectionSettingsScreen()
    enable_combo_search(screen)
    screen.show()
    qt_app.processEvents()
    ssl = screen.widget.cmb_ssl
    ssl.setFocus()
    _type(ssl, "full")
    assert _shown(ssl) == ["verify-full"]
    ssl.hidePopup()
    address = screen.widget.cmb_address
    address.lineEdit().setFocus()
    address.lineEdit().clear()
    _type(address.lineEdit(), "10.0.0.5")
    assert not address.view().isVisible() and address.currentText() == "10.0.0.5"
    screen.close()


# --- phase 4: an item picked by searching is the one that gets saved -----------------------

def _pick(combo, text):
    combo.setFocus()
    _type(combo.lineEdit() if combo.isEditable() else combo, text)
    assert combo.view().isVisible() and len([t for t in _shown(combo) if t]) == 1, _shown(combo)
    QTest.keyClick(combo.view(), Qt.Key_Return)
    assert not combo.view().isVisible()


def _quiet(monkeypatch, *modules):
    for module in modules:
        for name in ("information", "warning", "critical"):
            monkeypatch.setattr(module.QMessageBox, name, lambda *a, **k: None)
        monkeypatch.setattr(module.QMessageBox, "question", lambda *a, **k: module.QMessageBox.Yes)


def test_contracts_saves_the_contractor_found_by_search(qt_app, monkeypatch):
    from tests.unit.test_contractor_contracts_screen import FakeService
    from app.ui.screens import contractor_contracts_screen as screen_module

    _quiet(monkeypatch, screen_module)
    screen = screen_module.ContractorContractsScreen(FakeService())
    enable_combo_search(screen)
    screen.resize(1700, 860)
    screen.show()
    screen.tree.setCurrentItem(screen._tree_items[("project", 10)])
    screen.new_contract()
    form = screen.tree_form
    _pick(form.contractor, "حديث")
    form.contract_value.setText("750000")
    screen.save_record()
    data, record_id = screen.service.saved[-1]
    assert record_id is None and data["contractor_id"] == 2 and data["project_id"] == 10
    screen.close()


def test_contractors_saves_the_type_found_by_search(qt_app, monkeypatch):
    from tests.unit.test_contractors_screen import FakeBackend, FakeService
    from app.ui.screens import base_crud_screen
    from app.ui.screens import contractors_screen as screen_module

    _quiet(monkeypatch, screen_module, base_crud_screen)
    backend = FakeBackend()
    monkeypatch.setattr(screen_module.ContractorsScreen, "_backend", lambda self: backend)
    screen = screen_module.ContractorsScreen(FakeService())
    enable_combo_search(screen)
    screen.resize(1700, 860)
    screen.show()
    screen.new_record()
    screen.inputs["contractor_name"].setText("مقاول جديد")
    _pick(screen.inputs["contractor_type"], "اعلان")  # «دعاية وإعلان», typed without the hamza
    screen.save_record()
    payload, record_id = screen.service.saved[-1]
    assert record_id is None and payload["contractor_type"] == "دعاية وإعلان"
    screen.close()


def test_payments_saves_the_method_found_by_search(qt_app, monkeypatch):
    from tests.unit.test_contractor_payments_screen import FakeService
    from app.ui.screens import contractor_payments_screen as screen_module

    _quiet(monkeypatch, screen_module)
    screen = screen_module.ContractorPaymentsScreen(FakeService())
    enable_combo_search(screen)
    screen.resize(1700, 860)
    screen.show()
    screen.new_payment()
    fields = screen.tree_fields
    fields.amount.setText("30000")
    _pick(fields.method, "حويل")
    fields.reference.setText("784512")
    screen.save_record()
    data, record_id = screen.service.saved[-1]
    assert record_id is None and data["payment_method"] == "تحويل" and data["extract_id"] == 501
    screen.close()


def test_users_saves_the_role_found_by_search(qt_app, monkeypatch):
    from app.ui.screens import users_page as page_module

    _quiet(monkeypatch, page_module)
    created = []

    class Auth(_Anything):
        def create_user(self, payload, password):
            created.append(payload)
            return 7

    roles = [{"id": 1, "role_name_ar": "مدير النظام"}, {"id": 2, "role_name_ar": "محاسب"},
             {"id": 3, "role_name_ar": "مدخل بيانات"}]
    page = page_module.UsersPage(Auth(), _Anything(list_roles=roles))
    enable_combo_search(page)
    page.show()
    page.new_user()
    page.username.setText("mona")
    _pick(page.role_combo, "محاس")
    page.save_user()
    assert created and created[-1]["role_id"] == 2
    page.close()
