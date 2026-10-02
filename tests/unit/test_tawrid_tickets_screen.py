"""Widget tests for شاشة البون — قسم التوريدات (headless Qt, no database).

Layout is "Model 3": four stacked cards (a shared header + the three party
cards), no ticket list on the screen, «بحث عن بون» and الاول/السابق/التالي/الاخير
instead. These pin the contract the البون depends on:

* The list is built and hidden — the base class drives selection through it.
* The five money totals are DB-generated, so they are NOT in the save payload;
  the screen only previews them, with the exact formulas.
* The item combo is the price mapping, and picking parties/item auto-fills the
  three prices from the cards.
* A ticket cannot be saved without a customer and a crusher (both NOT NULL).
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.tawrid_ticket_service import ItemDef, TicketPrices
from app.ui.screens import tawrid_tickets_screen as screen_module
from app.ui.screens.tawrid_tickets_screen import TawridTicketsScreen

LIST_ROWS = [
    {"ticket_id": 10, "ticket_no": 4118, "ticket_date": "2026-08-22", "item_name": "سن 1"},
    {"ticket_id": 11, "ticket_no": 4117, "ticket_date": "2026-08-21", "item_name": "رملة"},
]

# What get_record (writable columns only) returns for ticket 10.
RECORD_10 = {
    "ticket_id": 10, "ticket_no": 4118, "ticket_date": "2026-08-22",
    "receipt_no": "104233", "customer_id": 2, "supplier_id": 4, "tractor_id": 7,
    "item_id": 1, "item_name": "سن 1", "item_family": "سن",
    "cus_volume": "60.5", "price_cus": "80", "discount_percent": "1",
    "res_volume": "59", "price_res": "55", "price_man": "15",
}

ITEMS = [
    ItemDef(1, "سن 1", "سن", "price_sen1"),
    ItemDef(8, "رملة", "رمل", "price_raml"),
]


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
        self.prices = TicketPrices(price_cus=80, price_res=55, price_man=15, discount_percent=1)

    def items(self):
        return list(ITEMS)

    def item(self, item_id):
        return next((i for i in ITEMS if i.item_id == item_id), None)

    def prices_for(self, customer_id, supplier_id, tractor_id, item_id):
        return self.prices

    def customer_picker_rows(self):
        return [{"customer_id": 2, "customer_code": 8, "customer_name": "مؤسسة النور", "is_active": True}]

    def supplier_picker_rows(self):
        return [{"supplier_id": 4, "supplier_code": 4, "supplier_name": "مكة ستون", "is_active": True}]

    def tractor_picker_rows(self):
        return [{"tractor_id": 7, "driver_name": "محمد أحمد", "head_no": "1234", "trailer_no": "5678"}]

    def customer_tractor_picker_rows(self, customer_id):
        if str(customer_id) == "2":
            return [{"tractor_id": 7, "driver_name": "محمد أحمد", "head_no": "1234", "trailer_no": "5678"}]
        return []

    def crusher_tractor_picker_rows(self, supplier_id):
        if str(supplier_id) == "4":
            return [{"tractor_id": 7, "driver_name": "محمد أحمد", "head_no": "1234", "trailer_no": "5678"}]
        return []

    def crusher_volume(self, supplier_id, tractor_id):
        # Crusher 4 hauled 59.0 on tractor 7 in the تكعيب الكسّارات sheets.
        return {("4", "7"): Decimal("59")}.get((str(supplier_id), str(tractor_id)))

    def for_ticket(self, ticket_id):
        return {**RECORD_10, "customer_name": "مؤسسة النور", "supplier_name": "مكة ستون",
                "driver_name": "محمد أحمد", "head_no": "1234", "trailer_no": "5678"}

    def search_tickets(self, keyword="", limit=300):
        return list(LIST_ROWS)

    def grid_volume(self, customer_id, tractor_id):
        # Loads set up for customer 2 on the customers grid: tractor 7 -> 40,
        # tractor 9 -> 55. Any other pair has no grid row.
        return {("2", "7"): Decimal("40"), ("2", "9"): Decimal("55")}.get(
            (str(customer_id), str(tractor_id))
        )

    def next_ticket_no(self):
        return 4119

    def ticket_no_exists(self, ticket_no, exclude_id=None):
        return False


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    backend = FakeBackend()
    # Patch before construction so _reload_items() during __init__ never hits a DB.
    monkeypatch.setattr(screen_module, "TawridTicketService", lambda: backend)
    view = TawridTicketsScreen(FakeService())
    view._fake_backend = backend
    return view


# --- layout ------------------------------------------------------------------

def test_the_list_is_built_but_hidden(screen):
    assert screen.list_panel.isVisibleTo(screen) is False
    assert screen.table.rowCount() == len(LIST_ROWS)


def test_the_search_and_nav_buttons_replace_the_list(screen):
    assert screen.find_button.text() == "بحث عن بون"
    assert set(screen.nav_buttons) == {"first", "prev", "next", "last"}


def test_the_three_party_cards_and_header_exist(screen):
    assert set(screen._party_labels) == {"customer", "supplier", "tractor"}
    for key in ("safi_cus", "total_res", "total_man"):
        assert key in screen._calc


def test_the_item_combo_is_the_catalogue(screen):
    # blank + the two catalogue items.
    assert screen._item_combo.count() == 1 + len(ITEMS)
    assert screen._item_combo.itemText(1) == "سن 1"


# --- live totals use the exact DB formulas -----------------------------------

def test_live_totals(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["cus_volume"], "60.5")
    screen._set_editor_value(screen.inputs["price_cus"], "80")
    screen._set_editor_value(screen.inputs["discount_percent"], "1")
    screen._set_editor_value(screen.inputs["res_volume"], "59")
    screen._set_editor_value(screen.inputs["price_res"], "55")
    screen._set_editor_value(screen.inputs["price_man"], "15")
    screen._recompute()
    assert screen._calc["safi_cus"].text() == "4,791.60"
    assert screen._calc["total_res"].text() == "3,245.00"
    assert screen._calc["total_man"].text() == "907.50"


# --- auto-fill prices from the cards -----------------------------------------

def test_choosing_parties_and_item_autofills_the_three_prices(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["customer_id"], 2)
    screen._set_editor_value(screen.inputs["supplier_id"], 4)
    screen._set_editor_value(screen.inputs["tractor_id"], 7)
    screen._item_combo.setCurrentIndex(1)  # سن 1 -> fires autofill
    assert screen.inputs["price_cus"].text().startswith("80")
    assert screen.inputs["price_res"].text().startswith("55")
    assert screen.inputs["price_man"].text().startswith("15")


# --- volume auto-fills from the customer×tractor grid ------------------------

def test_customer_plus_tractor_fills_the_volume_from_the_grid(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["customer_id"], 2)
    screen._set_editor_value(screen.inputs["tractor_id"], 7)
    screen._autofill_volume()
    assert screen.inputs["cus_volume"].text().startswith("40")


def test_repicking_a_tractor_updates_to_the_new_pairs_volume(screen):
    """The reported bug: changing the tractor must not keep the first volume."""
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["customer_id"], 2)
    screen._set_editor_value(screen.inputs["tractor_id"], 7)
    screen._autofill_volume()
    assert screen.inputs["cus_volume"].text().startswith("40")
    screen._set_editor_value(screen.inputs["tractor_id"], 9)
    screen._autofill_volume()
    assert screen.inputs["cus_volume"].text().startswith("55")


def test_repicking_a_tractor_without_a_grid_row_clears_the_stale_volume(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["customer_id"], 2)
    screen._set_editor_value(screen.inputs["tractor_id"], 7)
    screen._autofill_volume()
    assert screen.inputs["cus_volume"].text().startswith("40")
    screen._set_editor_value(screen.inputs["tractor_id"], 99)  # no grid row
    screen._autofill_volume()
    assert screen.inputs["cus_volume"].text() == ""


def test_choosing_the_crusher_and_tractor_fills_res_volume_from_the_cubing(screen):
    """The crusher's own volume for the tractor comes from تكعيب الكسّارات."""
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["supplier_id"], 4)
    screen._set_editor_value(screen.inputs["tractor_id"], 7)
    screen._autofill_res_volume()
    assert screen.inputs["res_volume"].text().startswith("59")


def test_res_volume_is_not_cleared_when_the_pair_has_no_cubing_row(screen):
    """Unlike cus_volume, a manual crusher volume survives a pair with no sheet."""
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["supplier_id"], 4)
    screen._set_editor_value(screen.inputs["tractor_id"], 99)  # no cubing row
    screen._set_editor_value(screen.inputs["res_volume"], "40")
    screen._autofill_res_volume()
    assert screen.inputs["res_volume"].text() == "40"


def test_changing_the_item_does_not_touch_the_volume(screen):
    """Volume comes from (customer, tractor), so an item switch must not wipe it."""
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["customer_id"], 2)
    screen._set_editor_value(screen.inputs["tractor_id"], 7)
    screen._set_editor_value(screen.inputs["cus_volume"], "55")  # user override
    screen._item_combo.setCurrentIndex(2)  # switch صنف -> autofills prices only
    assert screen.inputs["cus_volume"].text() == "55"


# --- new record --------------------------------------------------------------

def test_new_record_suggests_the_next_number_and_today(screen):
    screen.new_record()
    assert screen.inputs["ticket_no"].text() == "4119"
    assert screen.summary_label.text() == "بون جديد"


# --- save validation ---------------------------------------------------------

def test_save_refuses_without_a_customer(screen, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))
    screen.new_record()
    screen.service.saved = None
    screen._set_editor_value(screen.inputs["supplier_id"], 4)  # customer left blank
    screen.save_record()
    assert warned, "expected a warning"
    assert screen.service.saved is None


def test_a_valid_save_writes_only_the_writable_columns(screen, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    screen.new_record()
    screen._set_editor_value(screen.inputs["customer_id"], 2)
    screen._set_editor_value(screen.inputs["supplier_id"], 4)
    screen._item_combo.setCurrentIndex(1)
    screen._set_editor_value(screen.inputs["cus_volume"], "60.5")
    screen._set_editor_value(screen.inputs["price_cus"], "80")
    screen.save_record()
    payload = screen.service.saved
    assert payload is not None
    # generated columns must never be written
    for gen in ("total_cus", "amount_dis", "safi_cus", "total_res", "total_man"):
        assert gen not in payload
    assert payload["customer_id"] == "2"
    assert payload["item_id"] == 1


# --- loading a stored ticket -------------------------------------------------

def test_loading_a_ticket_fills_the_party_labels(screen):
    screen._load_ticket(10)
    assert screen.mode == "view"
    assert screen._party_labels["customer"].text() == "مؤسسة النور"
    assert screen._party_labels["supplier"].text() == "مكة ستون"
    assert "محمد أحمد" in screen._party_labels["tractor"].text()
    assert screen._calc["safi_cus"].text() == "4,791.60"
