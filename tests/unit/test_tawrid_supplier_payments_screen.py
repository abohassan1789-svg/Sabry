"""Widget tests for شاشة سند صرف الكسّارة — قسم التوريدات (headless Qt, no db).

Layout is the same "Model 9" as سندات قبض العملاء, in amber: entry cards on the
right, and on the left a «الرصيد الجديد» callout, a payment-ratio donut and three
stat cards. These pin:

* the voucher list is built and hidden — the base drives selection through it;
* the analytics read «قبل → السند → بعده» off the account summary, and the donut
  shows the payment ratio — with the LABEL exceeding 100% when overpaid while the
  ring stays clamped;
* the amount is spelled out in Arabic (المبلغ بالحروف);
* a payment cannot be saved without a crusher, and a blank amount becomes 0.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.tawrid_supplier_payment_service import PaymentAccount
from app.ui.screens import tawrid_supplier_payments_screen as screen_module
from app.ui.screens.tawrid_supplier_payments_screen import (
    TawridSupplierPaymentsScreen,
    _amount_in_words,
    _int_words,
)

LIST_ROWS = [
    {"payment_id": 10, "payment_no": 149, "payment_date": "2026-08-22", "amount": Decimal("250000")},
    {"payment_id": 11, "payment_no": 148, "payment_date": "2026-08-20", "amount": Decimal("-15000")},
]

RECORD_10 = {
    "payment_id": 10, "payment_no": 149, "payment_date": "2026-08-22",
    "supplier_id": 7, "amount": "250000", "statement": "دفعة",
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
        # crusher 7: opening 50k + purchased 900k = 950k owed; 400k paid before.
        self.account = PaymentAccount(
            opening_balance=Decimal("50000"),
            purchased=Decimal("900000"),
            base_paid=Decimal("400000"),
            tickets_count=5,
            movements_available=True,
        )
        # crusher 8: overpaid — 100k owed, 111,125 already paid (like «مكة ستون»).
        self.overpaid = PaymentAccount(
            opening_balance=Decimal("0"),
            purchased=Decimal("100000"),
            base_paid=Decimal("111125"),
            movements_available=True,
        )

    def next_payment_no(self):
        return 150

    def payment_no_exists(self, payment_no, exclude_id=None):
        return False

    def supplier_picker_rows(self):
        return [{"supplier_id": 7, "supplier_code": 8, "supplier_name": "الهدي", "is_active": True}]

    def account_for(self, supplier_id, exclude_payment_id=None):
        if str(supplier_id) == "7":
            return self.account
        if str(supplier_id) == "8":
            return self.overpaid
        return PaymentAccount()

    def for_payment(self, payment_id):
        return {**RECORD_10, "supplier_name": "الهدي", "supplier_code": 8}

    def search_payments(self, keyword="", limit=300):
        return list(LIST_ROWS)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(screen_module, "TawridSupplierPaymentService", lambda: backend)
    view = TawridSupplierPaymentsScreen(FakeService())
    view._fake_backend = backend
    return view


# --- layout ------------------------------------------------------------------

def test_the_list_is_built_but_hidden(screen):
    assert screen.list_panel.isVisibleTo(screen) is False
    assert screen.table.rowCount() == len(LIST_ROWS)


def test_the_search_and_nav_buttons_replace_the_list(screen):
    assert screen.find_button.text() == "بحث عن سند صرف"
    assert set(screen.nav_buttons) == {"first", "prev", "next", "last"}


def test_the_analytics_widgets_exist(screen):
    assert screen._donut is not None
    assert set(screen._stat_values) == {"prev", "this", "after"}
    assert set(screen._legend) == {"paid", "remaining", "due"}


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

def test_picking_a_crusher_and_amount_previews_the_balance(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["supplier_id"], 7)
    screen._set_editor_value(screen.inputs["amount"], "250000")
    screen._recompute()
    # 950,000 owed, 400,000 paid before -> 550,000 balance, minus 250,000.
    assert screen._stat_values["prev"].text() == "550,000.00"
    assert screen._stat_values["this"].text() == "250,000.00-"
    assert screen._stat_values["after"].text() == "300,000.00"
    assert screen._callout_value.text() == "300,000.00"
    assert screen._callout_was.text() == "كان 550,000.00"


def test_the_donut_shows_the_payment_ratio(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["supplier_id"], 7)
    screen._set_editor_value(screen.inputs["amount"], "250000")
    screen._recompute()
    # paid after = 650,000 of 950,000 = 68.4%.
    assert screen._donut._label == "68.4%"
    assert screen._legend["paid"].text() == "650,000.00"
    assert screen._legend["due"].text() == "950,000.00"


def test_overpayment_shows_over_100_percent_and_a_negative_balance(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["supplier_id"], 8)
    screen._set_editor_value(screen.inputs["amount"], "0")
    screen._recompute()
    # 100,000 owed, 111,125 paid -> 111.1% and a −11,125 balance.
    assert screen._donut._label == "111.1%"
    # the drawn ring is clamped to a full circle even though the label is >100%.
    assert screen._donut._ratio == 1.0
    assert screen._callout_value.text() == "11,125.00-"


def test_no_crusher_leaves_the_analytics_blank(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["supplier_id"], None)
    screen._recompute()
    assert screen._callout_value.text() == "—"
    assert screen._donut._label == "—"


# --- new record --------------------------------------------------------------

def test_new_record_suggests_the_next_number_and_today(screen):
    screen.new_record()
    assert screen.inputs["payment_no"].text() == "150"
    assert screen.inputs["payment_date"].date().toString("yyyy-MM-dd")


# --- save validation ---------------------------------------------------------

def test_save_without_a_crusher_warns_and_does_not_save(screen, monkeypatch):
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("msg", a))
    screen.new_record()
    screen._set_editor_value(screen.inputs["supplier_id"], None)
    screen.save_record()
    assert "msg" in warned
    assert screen.service.saved is None


def test_save_with_a_crusher_blank_amount_becomes_zero(screen, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    screen.new_record()
    screen._set_editor_value(screen.inputs["supplier_id"], 7)
    screen._set_editor_value(screen.inputs["amount"], "")  # blank -> 0
    screen.save_record()
    assert screen.service.saved is not None
    assert str(screen.service.saved["amount"]) == "0"
    assert str(screen.service.saved["supplier_id"]) == "7"
