"""Widget tests for شاشة سند قبض العميل — قسم التوريدات (headless Qt, no database).

Layout is the refined "Model 9": entry cards on the right, and on the left a
«الرصيد الجديد» callout, a collection-ratio donut and three stat cards. These pin:

* the voucher list is built and hidden — the base drives selection through it;
* the analytics read «قبل → السند → بعده» off the account summary, and the donut
  shows the collection ratio;
* the amount is spelled out in Arabic (المبلغ بالحروف);
* a receipt cannot be saved without a customer, and a blank amount becomes 0.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.tawrid_customer_receipt_service import ReceiptAccount
from app.ui.screens import tawrid_customer_receipts_screen as screen_module
from app.ui.screens.tawrid_customer_receipts_screen import (
    TawridCustomerReceiptsScreen,
    _amount_in_words,
    _int_words,
)

LIST_ROWS = [
    {"receipt_id": 10, "receipt_no": 1205, "receipt_date": "2026-08-22", "amount": Decimal("250000")},
    {"receipt_id": 11, "receipt_no": 1204, "receipt_date": "2026-08-20", "amount": Decimal("-15000")},
]

RECORD_10 = {
    "receipt_id": 10, "receipt_no": 1205, "receipt_date": "2026-08-22",
    "customer_id": 7, "amount": "250000", "statement": "قسط شقة",
}


class FakeService:
    def __init__(self):
        self.saved = None

    def list_records(self, spec, keyword="", limit=500):
        return list(LIST_ROWS)

    def get_record(self, spec, record_id):
        return dict(RECORD_10) if int(record_id) == 10 else {}

    def save_record(self, spec, payload, record_id):
        self.saved = dict(payload)
        return record_id or 99

    def next_id(self, spec):
        return 1

    def delete_record(self, spec, record_id):
        pass


class FakeBackend:
    def __init__(self):
        # opening 100k + invoiced 1,240k = 1,340k due; 750k collected before this.
        self.account = ReceiptAccount(
            opening_balance=Decimal("100000"),
            invoiced=Decimal("1240000"),
            base_collected=Decimal("750000"),
            tickets_count=5,
            movements_available=True,
        )

    def next_receipt_no(self):
        return 1215

    def receipt_no_exists(self, receipt_no, exclude_id=None):
        return False

    def customer_picker_rows(self):
        return [{"customer_id": 7, "customer_code": 8, "customer_name": "محمد عبد الله", "is_active": True}]

    def account_for(self, customer_id, exclude_receipt_id=None):
        return self.account if str(customer_id) == "7" else ReceiptAccount()

    def for_receipt(self, receipt_id):
        return {**RECORD_10, "customer_name": "محمد عبد الله", "customer_code": 8}

    def search_receipts(self, keyword="", limit=300):
        return list(LIST_ROWS)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(screen_module, "TawridCustomerReceiptService", lambda: backend)
    view = TawridCustomerReceiptsScreen(FakeService())
    view._fake_backend = backend
    return view


# --- layout ------------------------------------------------------------------

def test_the_list_is_built_but_hidden(screen):
    assert screen.list_panel.isVisibleTo(screen) is False
    assert screen.table.rowCount() == len(LIST_ROWS)


def test_the_search_and_nav_buttons_replace_the_list(screen):
    assert screen.find_button.text() == "بحث عن سند"
    assert set(screen.nav_buttons) == {"first", "prev", "next", "last"}


def test_the_analytics_widgets_exist(screen):
    assert screen._donut is not None
    assert set(screen._stat_values) == {"prev", "this", "after"}
    assert set(screen._legend) == {"collected", "remaining", "due"}


# --- amount in words ---------------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (0, "صفر"),
    (1, "واحد"),
    (11, "أحد عشر"),
    (100, "مائة"),
    (250000, "مئتان وخمسون ألف"),
])
def test_int_words(n, expected):
    assert _int_words(n) == expected


def test_amount_in_words_reads_pounds_and_piastres():
    assert _amount_in_words(Decimal("250000")) == "فقط مئتان وخمسون ألف جنيه لا غير"
    assert "قرش" in _amount_in_words(Decimal("20000.50"))
    assert _amount_in_words(Decimal("-15000")).startswith("فقط يُخصم")


# --- live analytics: قبل → السند → بعده --------------------------------------

def test_picking_a_customer_and_amount_previews_the_balance(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["customer_id"], 7)
    screen._set_editor_value(screen.inputs["amount"], "250000")
    screen._recompute()
    # 1,340,000 due, 750,000 collected before -> 590,000 balance, minus 250,000.
    assert screen._stat_values["prev"].text() == "590,000.00"
    assert screen._stat_values["this"].text() == "250,000.00-"
    assert screen._stat_values["after"].text() == "340,000.00"
    assert screen._callout_value.text() == "340,000.00"
    assert screen._callout_was.text() == "كان 590,000.00"


def test_the_donut_shows_the_collection_ratio(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["customer_id"], 7)
    screen._set_editor_value(screen.inputs["amount"], "250000")
    screen._recompute()
    # collected after = 1,000,000 of 1,340,000 = 74.6%.
    assert screen._donut._label == "74.6%"
    assert screen._legend["collected"].text() == "1,000,000.00"
    assert screen._legend["due"].text() == "1,340,000.00"


def test_no_customer_leaves_the_analytics_blank(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["customer_id"], None)
    screen._recompute()
    assert screen._callout_value.text() == "—"
    assert screen._donut._label == "—"


# --- new record --------------------------------------------------------------

def test_new_record_suggests_the_next_number_and_today(screen):
    screen.new_record()
    assert screen.inputs["receipt_no"].text() == "1215"
    assert screen.inputs["receipt_date"].date().toString("yyyy-MM-dd")


# --- save validation ---------------------------------------------------------

def test_save_without_a_customer_warns_and_does_not_save(screen, monkeypatch):
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("msg", a))
    screen.new_record()
    screen._set_editor_value(screen.inputs["customer_id"], None)
    screen.save_record()
    assert "msg" in warned
    assert screen.service.saved is None


def test_save_with_a_customer_blank_amount_becomes_zero(screen, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    screen.new_record()
    screen._set_editor_value(screen.inputs["customer_id"], 7)
    screen._set_editor_value(screen.inputs["amount"], "")  # blank -> 0
    screen.save_record()
    assert screen.service.saved is not None
    assert str(screen.service.saved["amount"]) == "0"
    assert str(screen.service.saved["customer_id"]) == "7"
