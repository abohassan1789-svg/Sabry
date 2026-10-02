"""Tests for نافذة «بحث عن سند» (headless Qt, no database).

The receipt screen carries no voucher list, so this dialog is the only way to
reach an earlier سند. Its search is LIVE against a caller-supplied ``search_fn``,
so the tests drive a stub and pin: the money column, that typing re-runs the
search, and that a pick returns the ``receipt_id``.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from app.ui.dialogs.tawrid_receipt_picker import (
    COLUMNS,
    TawridReceiptPickerDialog,
    _money,
)

RECEIPTS = [
    {"receipt_id": 10, "receipt_no": 1205, "receipt_date": "2026-08-22",
     "customer_name": "محمد عبد الله", "amount": Decimal("250000"), "statement": "قسط شقة"},
    {"receipt_id": 11, "receipt_no": 1204, "receipt_date": "2026-08-20",
     "customer_name": "الفهد", "amount": Decimal("-15000"), "statement": "مرتجع"},
]


def _search(keyword: str):
    needle = keyword.strip()
    if not needle:
        return list(RECEIPTS)
    return [r for r in RECEIPTS if needle in str(r["receipt_no"]) or needle in r["customer_name"]]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qt_app):
    return TawridReceiptPickerDialog(_search)


@pytest.mark.parametrize("value,expected", [
    (Decimal("250000"), "250,000.00"),
    (Decimal("0"), "0.00"),
    (Decimal("-15000"), "15,000.00-"),
    (None, "0.00"),
])
def test_money_formatting(value, expected):
    assert _money(value) == expected


def test_columns_are_number_date_customer_amount_statement():
    assert [key for key, _label, _money in COLUMNS] == [
        "receipt_no", "receipt_date", "customer_name", "amount", "statement",
    ]


def test_it_opens_showing_the_recent_receipts(dialog):
    assert dialog.table.rowCount() == len(RECEIPTS)
    assert dialog.count_label.text() == f"عدد السندات: {len(RECEIPTS)}"


def test_typing_reruns_the_live_search(dialog):
    dialog.search_text.setText("الفهد")
    dialog._run_search()
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == "الفهد"  # customer in col 2


def test_the_amount_is_money_formatted_including_a_reversal(dialog):
    assert dialog.table.item(0, 3).text() == "250,000.00"
    assert dialog.table.item(1, 3).text() == "15,000.00-"


def test_choosing_a_row_returns_its_receipt_id(dialog):
    dialog.table.setCurrentCell(1, 0)
    dialog.accept_selected()
    assert dialog.selected_id == 11
    assert dialog.result() == QDialog.Accepted


def test_enter_picks_the_only_match(dialog):
    dialog.search_text.setText("1205")
    dialog._accept_if_unambiguous()
    assert dialog.selected_id == 10


def test_a_failing_search_does_not_crash(qt_app):
    def boom(_keyword):
        raise RuntimeError("db down")

    view = TawridReceiptPickerDialog(boom)
    assert view.table.rowCount() == 0
    assert view.choose_button.isEnabled() is False
