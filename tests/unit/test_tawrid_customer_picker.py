"""Tests for نافذة اختيار العميل (headless Qt, no database).

The البون screen attaches a customer to a ticket through this picker. It is the
twin of the crusher picker, so the same two guarantees are pinned: the name and
the code are searchable (the status is not, or a typed digit becomes noise), and
a stopped card reads as «موقوف» and is greyed.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog

from app.ui.dialogs.tawrid_customer_picker import (
    COLUMNS,
    SEARCH_KEYS,
    TawridCustomerPickerDialog,
    filter_customers,
)

CUSTOMERS = [
    {"customer_id": 1, "customer_code": 5, "customer_name": "نيو جيزة", "is_active": True},
    {"customer_id": 2, "customer_code": 8, "customer_name": "مؤسسة النور", "is_active": True},
    {"customer_id": 3, "customer_code": 12, "customer_name": "الفهد", "is_active": True},
    {"customer_id": 4, "customer_code": 20, "customer_name": "عميل قديم", "is_active": False},
]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qt_app):
    return TawridCustomerPickerDialog(CUSTOMERS)


def test_columns_are_code_name_status():
    assert [key for key, _label in COLUMNS] == ["customer_code", "customer_name", "is_active"]


def test_only_name_and_code_are_searched():
    assert SEARCH_KEYS == ("customer_code", "customer_name")


def test_empty_search_shows_everything():
    assert filter_customers(CUSTOMERS, "") == CUSTOMERS
    assert filter_customers(CUSTOMERS, "   ") == CUSTOMERS


def test_search_by_name():
    found = filter_customers(CUSTOMERS, "النور")
    assert [c["customer_id"] for c in found] == [2]


def test_search_by_code():
    assert [c["customer_id"] for c in filter_customers(CUSTOMERS, "12")] == [3]


def test_search_keeps_order():
    # النور and الفهد both contain «ال» — the dialog returns them in the given
    # order (active first), never re-sorted.
    found = filter_customers(CUSTOMERS, "ال")
    assert [c["customer_id"] for c in found] == [2, 3]


def test_no_match_returns_nothing():
    assert filter_customers(CUSTOMERS, "زززز") == []


def test_table_starts_with_every_customer(dialog):
    assert dialog.table.rowCount() == len(CUSTOMERS)
    assert dialog.count_label.text() == f"عدد العملاء: {len(CUSTOMERS)}"


def test_typing_filters_the_table(dialog):
    dialog.search_text.setText("النور")
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 1).text() == "مؤسسة النور"


def test_a_stopped_card_reads_as_stopped_and_is_greyed(dialog):
    row = next(i for i, c in enumerate(CUSTOMERS) if c["customer_id"] == 4)
    assert dialog.table.item(row, 2).text() == "موقوف"
    assert dialog.table.item(row, 1).foreground().color() == QColor("#94A3B8")


def test_choosing_a_row_returns_that_customer(dialog):
    dialog.table.setCurrentCell(1, 0)
    dialog.accept_selected()
    assert dialog.selected["customer_id"] == 2
    assert dialog.result() == QDialog.Accepted


def test_enter_picks_the_only_match(dialog):
    dialog.search_text.setText("الفهد")
    dialog._accept_if_unambiguous()
    assert dialog.selected["customer_id"] == 3


def test_enter_does_not_guess_between_several(dialog):
    dialog.search_text.setText("ة")
    dialog._accept_if_unambiguous()
    assert dialog.selected is None


def test_an_empty_list_opens_without_selection(qt_app):
    empty = TawridCustomerPickerDialog([])
    assert empty.table.rowCount() == 0
    assert empty.choose_button.isEnabled() is False


# --- tractor scope (the «بون 2» tractor-first flow) --------------------------

TRACTOR_CUSTOMERS = [
    {"customer_id": 2, "customer_code": 8, "customer_name": "مؤسسة النور", "is_active": True},
]


def test_scope_toggle_opens_on_the_tractors_customers(qt_app):
    dlg = TawridCustomerPickerDialog(
        CUSTOMERS, tractor_rows=TRACTOR_CUSTOMERS, tractor_name="محمد أحمد"
    )
    # Opens filtered to the tractor's customers; the toggle exists.
    assert dlg.scope_tractor is not None
    assert dlg.scope_tractor.isChecked() is True
    assert dlg.table.rowCount() == len(TRACTOR_CUSTOMERS)
    # Widening to «كل العملاء» shows the full list.
    dlg.scope_all.setChecked(True)
    assert dlg.table.rowCount() == len(CUSTOMERS)


def test_no_toggle_without_tractor_rows(dialog):
    assert getattr(dialog, "scope_tractor", None) is None
