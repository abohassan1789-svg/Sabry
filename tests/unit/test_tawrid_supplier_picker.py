"""Tests for نافذة اختيار الكسّارة (headless Qt, no database).

The dialog replaced the list panel on شاشة الكسّارات, and before that the combo
on the Access screen ``Fproduct`` — whose RowSource was
``SELECT id, productName FROM pruduct``: every card, active or dead, in creation
order, with nothing to tell them apart. 7 of the 23 cards have no ticket, no
voucher and no opening balance, and sat in that list next to «الهدي», which
carries 2,389 of the 4,072 tickets.

So the two things this dialog adds over the combo are what these tests pin down:
stopped cards are listed last and greyed, and the balance is visible before the
card is opened — including a negative one, which the Access screen could not
show at all.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog

from app.ui.dialogs.tawrid_supplier_picker import (
    COLUMNS,
    SEARCH_KEYS,
    TawridSupplierPickerDialog,
    filter_suppliers,
    format_money,
)

# Real rows out of ``pruduct``, in the order picker_rows() returns them:
# active first, then by name, stopped last.
SUPPLIERS = [
    {"supplier_id": 1, "supplier_code": 1, "supplier_name": "الهدي",
     "is_active": True, "balance": Decimal("2623695")},
    {"supplier_id": 4, "supplier_code": 4, "supplier_name": "المتحدة",
     "is_active": True, "balance": Decimal("708306")},
    {"supplier_id": 3, "supplier_code": 3, "supplier_name": "جولد ستون",
     "is_active": True, "balance": Decimal("1012965")},
    {"supplier_id": 18, "supplier_code": 53, "supplier_name": "مكة ستون",
     "is_active": True, "balance": Decimal("-11125")},
    {"supplier_id": 6, "supplier_code": 6, "supplier_name": "النائب",
     "is_active": False, "balance": Decimal("0")},
]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qt_app):
    return TawridSupplierPickerDialog(SUPPLIERS)


# --- filtering (pure, no widget) --------------------------------------------

def test_the_dialog_shows_status_and_balance_beside_the_name():
    assert [key for key, _label in COLUMNS] == [
        "supplier_code", "supplier_name", "is_active", "balance",
    ]


def test_only_the_name_and_the_code_are_searched():
    """Matching the balance would turn a typed digit into noise."""
    assert SEARCH_KEYS == ("supplier_code", "supplier_name")


def test_an_empty_search_shows_everything():
    assert filter_suppliers(SUPPLIERS, "") == SUPPLIERS
    assert filter_suppliers(SUPPLIERS, "   ") == SUPPLIERS


def test_search_by_name():
    found = filter_suppliers(SUPPLIERS, "ستون")
    assert [s["supplier_id"] for s in found] == [3, 18]


def test_search_by_code():
    assert [s["supplier_id"] for s in filter_suppliers(SUPPLIERS, "53")] == [18]


def test_search_keeps_the_order_it_was_given():
    """Active first, then by name — the dialog must not re-sort the rows."""
    found = filter_suppliers(SUPPLIERS, "ال")
    assert [s["supplier_id"] for s in found] == [1, 4, 6]


def test_a_search_that_matches_nothing_returns_nothing():
    assert filter_suppliers(SUPPLIERS, "زززز") == []


# --- money -------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (Decimal("2623695"), "2,623,695.00"),
    (Decimal("0"), "0.00"),
    (Decimal("-11125"), "11,125.00-"),
    (None, "0.00"),
    ("not a number", "0.00"),
])
def test_money_formatting(value, expected):
    assert format_money(value) == expected


# --- the widget --------------------------------------------------------------

def test_the_table_starts_showing_every_crusher(dialog):
    assert dialog.table.rowCount() == len(SUPPLIERS)
    assert dialog.count_label.text() == f"عدد الكسّارات: {len(SUPPLIERS)}"


def test_typing_filters_the_table(dialog):
    dialog.search_text.setText("المتحدة")
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 1).text() == "المتحدة"


def test_a_stopped_card_reads_as_stopped(dialog):
    row = next(i for i, s in enumerate(SUPPLIERS) if s["supplier_id"] == 6)
    assert dialog.table.item(row, 2).text() == "موقوف"


def test_a_stopped_card_is_greyed(dialog):
    row = next(i for i, s in enumerate(SUPPLIERS) if s["supplier_id"] == 6)
    assert dialog.table.item(row, 1).foreground().color() == QColor("#94A3B8")


def test_an_overpaid_crusher_is_called_out_in_red(dialog):
    row = next(i for i, s in enumerate(SUPPLIERS) if s["supplier_id"] == 18)
    balance = dialog.table.item(row, 3)
    assert balance.text() == "11,125.00-"
    assert balance.foreground().color() == QColor("#B91C1C")


def test_choosing_a_row_returns_that_crusher(dialog):
    dialog.table.setCurrentCell(1, 0)
    dialog.accept_selected()
    assert dialog.selected["supplier_id"] == 4
    assert dialog.result() == QDialog.Accepted


def test_enter_picks_the_row_when_only_one_is_left(dialog):
    dialog.search_text.setText("مكة")
    dialog._accept_if_unambiguous()
    assert dialog.selected["supplier_id"] == 18


def test_enter_does_not_guess_while_several_rows_match(dialog):
    dialog.search_text.setText("ستون")
    dialog._accept_if_unambiguous()
    assert dialog.selected is None


def test_the_choose_button_is_disabled_when_nothing_matches(dialog):
    dialog.search_text.setText("زززز")
    assert dialog.choose_button.isEnabled() is False


def test_an_empty_list_opens_without_a_selection(qt_app):
    empty = TawridSupplierPickerDialog([])
    assert empty.table.rowCount() == 0
    assert empty.choose_button.isEnabled() is False
    empty.accept_selected()
    assert empty.selected is None


# --- tractor scope (the «بون 2» tractor-first flow) --------------------------

def test_scope_toggle_opens_on_the_tractors_crushers(qt_app):
    tractor_rows = [SUPPLIERS[0], SUPPLIERS[3]]  # الهدي + مكة ستون
    dlg = TawridSupplierPickerDialog(
        SUPPLIERS, tractor_rows=tractor_rows, tractor_name="محمد أحمد"
    )
    assert dlg.scope_tractor is not None
    assert dlg.scope_tractor.isChecked() is True
    assert dlg.table.rowCount() == len(tractor_rows)
    dlg.scope_all.setChecked(True)
    assert dlg.table.rowCount() == len(SUPPLIERS)


def test_no_toggle_without_tractor_rows(qt_app):
    dlg = TawridSupplierPickerDialog(SUPPLIERS)
    assert getattr(dlg, "scope_tractor", None) is None
