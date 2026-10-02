"""Tests for نافذة اختيار الجرار (headless Qt, no database).

The picker exists because the Access subform offered a bare combo of driver
names: there was no way to find a tractor by the number painted on it, which is
what the staff actually read off the yard. So the search has to match the head
number and the trailer number as well as the name, including partial numbers.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from app.ui.dialogs.tawrid_tractor_picker import (
    COLUMNS,
    TawridTractorPickerDialog,
    filter_tractors,
)

TRACTORS = [
    {"tractor_id": 11, "driver_name": "السعيد معروف", "head_no": "7814", "trailer_no": "3581"},
    {"tractor_id": 13, "driver_name": "احمد معروف", "head_no": "3282", "trailer_no": "2175"},
    {"tractor_id": 32, "driver_name": "ربيع بصل 2", "head_no": "5479", "trailer_no": "3721"},
    {"tractor_id": 40, "driver_name": "ماهر الشرقاوي 2", "head_no": "5451", "trailer_no": "3763"},
]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qt_app):
    return TawridTractorPickerDialog(TRACTORS)


# --- filtering (pure, no widget) --------------------------------------------

def test_the_picker_shows_the_three_things_that_identify_a_tractor():
    assert [key for key, _label in COLUMNS] == ["driver_name", "head_no", "trailer_no"]


def test_an_empty_search_shows_everything():
    assert filter_tractors(TRACTORS, "") == TRACTORS
    assert filter_tractors(TRACTORS, "   ") == TRACTORS


def test_search_by_driver_name():
    found = filter_tractors(TRACTORS, "معروف")
    assert [t["tractor_id"] for t in found] == [11, 13]


def test_search_by_head_number():
    assert [t["tractor_id"] for t in filter_tractors(TRACTORS, "7814")] == [11]


def test_search_by_trailer_number():
    assert [t["tractor_id"] for t in filter_tractors(TRACTORS, "2175")] == [13]


def test_a_partial_plate_matches():
    """Plates are text, so typing the tail of a number still finds it."""
    assert [t["tractor_id"] for t in filter_tractors(TRACTORS, "581")] == [11]


def test_a_search_that_matches_nothing_returns_nothing():
    assert filter_tractors(TRACTORS, "مفيش") == []


# --- the dialog -------------------------------------------------------------

def test_the_table_lists_every_tractor_on_open(dialog):
    assert dialog.table.rowCount() == len(TRACTORS)
    assert dialog.count_label.text() == "عدد الجرارات: 4"


def test_typing_filters_the_table_live(dialog):
    dialog.search_text.setText("5479")
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "ربيع بصل 2"
    assert dialog.table.item(0, 1).text() == "5479"
    assert dialog.table.item(0, 2).text() == "3721"


def test_choosing_returns_the_whole_tractor_row(dialog):
    dialog.search_text.setText("احمد")
    dialog.accept_selected()
    assert dialog.selected["tractor_id"] == 13
    assert dialog.result() == QDialog.Accepted


def test_nothing_is_selected_until_the_user_chooses(dialog):
    assert dialog.selected is None


def test_the_choose_button_is_disabled_when_nothing_matches(dialog):
    dialog.search_text.setText("مفيش")
    assert dialog.choose_button.isEnabled() is False
    dialog.accept_selected()  # must not raise or select anything
    assert dialog.selected is None


def test_enter_picks_the_row_when_only_one_is_left(dialog):
    """Type the plate, press Enter — the reason this dialog replaced a combo."""
    dialog.search_text.setText("3282")
    dialog.search_text.returnPressed.emit()
    assert dialog.selected["tractor_id"] == 13


def test_enter_never_guesses_between_several_matches(dialog):
    dialog.search_text.setText("معروف")
    dialog.search_text.returnPressed.emit()
    assert dialog.selected is None


# --- the البون scope toggle (all tractors vs the customer's) -----------------

CUSTOMER_TRACTORS = [TRACTORS[0], TRACTORS[2]]  # ids 11 and 32


def test_no_scope_toggle_without_customer_rows(dialog):
    """The customers screen still calls it with one list — no toggle then."""
    assert not hasattr(dialog, "scope_all")


def test_scope_defaults_to_all_tractors(qt_app):
    view = TawridTractorPickerDialog(TRACTORS, customer_rows=CUSTOMER_TRACTORS, customer_name="النور")
    assert view.scope_all.isChecked() is True
    assert view.table.rowCount() == len(TRACTORS)
    assert "النور" in view.scope_customer.text()


def test_switching_to_customer_scope_narrows_the_list(qt_app):
    view = TawridTractorPickerDialog(TRACTORS, customer_rows=CUSTOMER_TRACTORS)
    view.scope_customer.setChecked(True)
    assert view.table.rowCount() == len(CUSTOMER_TRACTORS)
    assert {view.table.item(r, 0).text() for r in range(view.table.rowCount())} == {
        "السعيد معروف", "ربيع بصل 2"
    }


def test_switching_back_to_all_restores_the_full_list(qt_app):
    view = TawridTractorPickerDialog(TRACTORS, customer_rows=CUSTOMER_TRACTORS)
    view.scope_customer.setChecked(True)
    view.scope_all.setChecked(True)
    assert view.table.rowCount() == len(TRACTORS)


def test_search_still_works_within_the_customer_scope(qt_app):
    view = TawridTractorPickerDialog(TRACTORS, customer_rows=CUSTOMER_TRACTORS)
    view.scope_customer.setChecked(True)
    view.search_text.setText("بصل")
    assert view.table.rowCount() == 1
    assert view.table.item(0, 0).text() == "ربيع بصل 2"


def test_empty_customer_scope_shows_nothing(qt_app):
    view = TawridTractorPickerDialog(TRACTORS, customer_rows=[])
    view.scope_customer.setChecked(True)
    assert view.table.rowCount() == 0
    assert view.choose_button.isEnabled() is False


# --- the crusher scope («جرارات الكسّارة») -----------------------------------

CRUSHER_TRACTORS = [TRACTORS[1], TRACTORS[3]]  # ids 13 and 40


def test_no_crusher_radio_when_no_crusher_rows(dialog):
    assert dialog.scope_crusher is None


def test_the_crusher_radio_appears_with_its_name(qt_app):
    view = TawridTractorPickerDialog(TRACTORS, crusher_rows=CRUSHER_TRACTORS, crusher_name="الفهد")
    assert view.scope_crusher is not None
    assert "الفهد" in view.scope_crusher.text()
    assert view.scope_all.isChecked() is True  # default is still all


def test_switching_to_crusher_scope_narrows_the_list(qt_app):
    view = TawridTractorPickerDialog(TRACTORS, crusher_rows=CRUSHER_TRACTORS)
    view.scope_crusher.setChecked(True)
    assert view.table.rowCount() == len(CRUSHER_TRACTORS)
    assert {view.table.item(r, 0).text() for r in range(view.table.rowCount())} == {
        "احمد معروف", "ماهر الشرقاوي 2"
    }


def test_all_three_scopes_can_coexist(qt_app):
    view = TawridTractorPickerDialog(
        TRACTORS, customer_rows=CUSTOMER_TRACTORS, customer_name="النور",
        crusher_rows=CRUSHER_TRACTORS, crusher_name="الفهد",
    )
    assert view.scope_customer is not None and view.scope_crusher is not None
    view.scope_customer.setChecked(True)
    assert view.table.rowCount() == len(CUSTOMER_TRACTORS)
    view.scope_crusher.setChecked(True)
    assert view.table.rowCount() == len(CRUSHER_TRACTORS)
    view.scope_all.setChecked(True)
    assert view.table.rowCount() == len(TRACTORS)
