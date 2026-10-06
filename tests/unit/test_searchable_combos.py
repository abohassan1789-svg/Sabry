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


# --- the screens covered: phase 1 = «المقاولات», phase 2 = «التقارير» -----------------------

def _visible_sidebar_keys(section_id):
    items = next(items for section, _t, _i, items in main_window.NAV_SECTIONS if section == section_id)
    return {key for key, _label, _icon in items if key not in main_window.HIDDEN_NAV_KEYS}


def test_the_contracting_screens_and_reports_are_covered():
    contracting = _visible_sidebar_keys("contracting")
    reports = _visible_sidebar_keys("reports")
    assert reports == {
        "contractor_contracts_report", "contractor_extracts_report",
        "contractor_advance_report", "contractor_statement_report",
    }
    assert main_window.SEARCHABLE_COMBO_SCREENS == contracting | reports


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
