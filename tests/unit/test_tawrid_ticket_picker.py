"""Tests for نافذة «بحث عن بون» (headless Qt, no database).

The البون screen carries no ticket list, so this dialog is the only way to reach
an earlier bon. Its search is LIVE against a caller-supplied ``search_fn``, so
the tests drive a stub function and pin: the money column, that typing re-runs
the search, and that a pick returns the ``ticket_id``.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from app.ui.dialogs.tawrid_ticket_picker import (
    COLUMNS,
    TawridTicketPickerDialog,
    _money,
)

TICKETS = [
    {"ticket_id": 10, "ticket_no": 4118, "receipt_no": "504", "ticket_date": "2026-08-22",
     "customer_name": "مؤسسة النور", "supplier_name": "مكة ستون",
     "item_name": "سن 1", "safi_cus": Decimal("4791.60")},
    {"ticket_id": 11, "ticket_no": 4117, "receipt_no": "777", "ticket_date": "2026-08-22",
     "customer_name": "الفهد", "supplier_name": "الجزيرة",
     "item_name": "رملة", "safi_cus": Decimal("3120.00")},
]


def _search(keyword: str):
    needle = keyword.strip()
    if not needle:
        return list(TICKETS)
    return [t for t in TICKETS if needle in str(t["ticket_no"]) or needle in t["customer_name"]]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qt_app):
    return TawridTicketPickerDialog(_search)


@pytest.mark.parametrize("value,expected", [
    (Decimal("4791.60"), "4,791.60"),
    (Decimal("0"), "0.00"),
    (Decimal("-50"), "50.00-"),
    (None, "0.00"),
])
def test_money_formatting(value, expected):
    assert _money(value) == expected


def test_columns_include_the_receipt_no_and_end_with_the_customer_net():
    assert [key for key, _label, _money in COLUMNS] == [
        "ticket_no", "receipt_no", "ticket_date", "customer_name", "item_name", "safi_cus",
    ]


def test_it_opens_showing_the_recent_tickets(dialog):
    assert dialog.table.rowCount() == len(TICKETS)
    assert dialog.count_label.text() == f"عدد البونات: {len(TICKETS)}"


def test_typing_reruns_the_live_search(dialog):
    dialog.search_text.setText("الفهد")
    dialog._run_search()
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 3).text() == "الفهد"  # customer moved to col 3


def test_the_receipt_number_is_shown(dialog):
    assert dialog.table.item(0, 1).text() == "504"


def test_searching_by_ticket_number(dialog):
    dialog.search_text.setText("4118")
    dialog._run_search()
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "4118"


def test_the_net_is_money_formatted(dialog):
    assert dialog.table.item(0, 5).text() == "4,791.60"


def test_choosing_a_row_returns_its_ticket_id(dialog):
    dialog.table.setCurrentCell(1, 0)
    dialog.accept_selected()
    assert dialog.selected_id == 11
    assert dialog.result() == QDialog.Accepted


def test_enter_picks_the_only_match(dialog):
    dialog.search_text.setText("4118")
    dialog._accept_if_unambiguous()
    assert dialog.selected_id == 10


def test_a_failing_search_does_not_crash(qt_app):
    def boom(_keyword):
        raise RuntimeError("db down")

    view = TawridTicketPickerDialog(boom)
    assert view.table.rowCount() == 0
    assert view.choose_button.isEnabled() is False
