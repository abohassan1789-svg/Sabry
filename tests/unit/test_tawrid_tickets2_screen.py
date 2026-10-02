"""Widget tests for شاشة «بون 2» — the second البون look (headless Qt, no DB).

«بون 2» edits the SAME ``tawrid_tickets`` row as the first البون screen, but
through an internal tab the user switches between (الأعمدة الثلاثة / شاشة بقسمين).
These pin the contract that makes the two-tab design safe:

* both tabs carry a complete editor set, and switching copies the values across;
* the live totals use the exact DB formulas on whichever tab is active;
* the جرار is chosen first and narrows the customer / crusher pickers
  (tractor-first filtering — the reverse of the first screen);
* a ticket still cannot be saved without a customer and a crusher.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.services.tawrid_ticket_service import ItemDef, TicketPrices
from app.ui.screens import tawrid_tickets2_screen as screen_module
from app.ui.screens.tawrid_tickets2_screen import TawridTickets2Screen

LIST_ROWS = [
    {"ticket_id": 10, "ticket_no": 4118, "ticket_date": "2026-08-22", "item_name": "سن 1"},
    {"ticket_id": 11, "ticket_no": 4117, "ticket_date": "2026-08-21", "item_name": "رملة"},
]

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

    # Tractor-first filtering: the two reverse-direction lookups «بون 2» adds.
    def customers_for_tractor(self, tractor_id):
        if str(tractor_id) == "7":
            return [{"customer_id": 2, "customer_code": 8, "customer_name": "مؤسسة النور", "is_active": True}]
        return []

    def crushers_for_tractor(self, tractor_id):
        if str(tractor_id) == "7":
            return [{"supplier_id": 4, "supplier_code": 4, "supplier_name": "مكة ستون", "is_active": True}]
        return []

    def crusher_volume(self, supplier_id, tractor_id):
        return {("4", "7"): Decimal("59")}.get((str(supplier_id), str(tractor_id)))

    def grid_volume(self, customer_id, tractor_id):
        return {("2", "7"): Decimal("40")}.get((str(customer_id), str(tractor_id)))

    def for_ticket(self, ticket_id):
        return {**RECORD_10, "customer_name": "مؤسسة النور", "supplier_name": "مكة ستون",
                "driver_name": "محمد أحمد", "head_no": "1234", "trailer_no": "5678"}

    def search_tickets(self, keyword="", limit=300):
        return list(LIST_ROWS)

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
    monkeypatch.setattr(screen_module, "TawridTicketService", lambda: backend)
    view = TawridTickets2Screen(FakeService())
    view._fake_backend = backend
    return view


# --- layout ------------------------------------------------------------------

def test_two_tabs_are_built(screen):
    assert screen.tabs.count() == 2
    assert screen.tabs.tabText(0) == "الأعمدة الثلاثة"
    assert screen.tabs.tabText(1) == "شاشة بقسمين"


def test_the_list_is_built_but_hidden(screen):
    assert screen.list_panel.isVisibleTo(screen) is False
    assert screen.table.rowCount() == len(LIST_ROWS)


def test_both_tabs_carry_a_complete_editor_set(screen):
    for tab in screen._tabs:
        for name in screen_module._FIELDS:
            assert name in tab.inputs, name
        assert set(tab.party_labels) == {"customer", "supplier", "tractor"}


def test_search_and_nav_buttons_replace_the_list(screen):
    assert screen.find_button.text() == "بحث عن بون"
    assert set(screen.nav_buttons) == {"first", "prev", "next", "last"}


# --- live totals use the exact DB formulas -----------------------------------

def test_live_totals_and_margin(screen):
    screen.set_mode("new")
    for name, value in [
        ("cus_volume", "60.5"), ("price_cus", "80"), ("discount_percent", "1"),
        ("res_volume", "59"), ("price_res", "55"), ("price_man", "15"),
    ]:
        screen._set_editor_value(screen.inputs[name], value)
    screen._recompute()
    assert screen._calc["safi_cus"].text() == "4,791.60"
    assert screen._calc["total_res"].text() == "3,245.00"
    assert screen._calc["total_man"].text() == "907.50"
    # margin = safi − res − man
    assert screen._calc["margin"].text() == "639.10"


# --- the tab is a view onto one shared record --------------------------------

def test_switching_tabs_carries_values_both_ways(screen):
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["cus_volume"], "60.5")
    screen._set_editor_value(screen.inputs["price_cus"], "80")
    screen._set_editor_value(screen.inputs["price_res"], "55")
    screen._set_editor_value(screen.inputs["res_volume"], "59")
    screen._recompute()

    screen.tabs.setCurrentIndex(1)
    assert screen._active == 1
    assert screen.inputs["cus_volume"].text() == "60.5"
    assert screen._calc["total_res"].text() == "3,245.00"

    # Edit on tab 1, switch back — the edit survives.
    screen._set_editor_value(screen.inputs["price_res"], "100")
    screen._recompute()
    screen.tabs.setCurrentIndex(0)
    assert screen.inputs["price_res"].text() == "100"
    assert screen._calc["total_res"].text() == "5,900.00"


# --- tractor-first filtering -------------------------------------------------

def test_picking_customer_after_tractor_scopes_the_dialog(screen, monkeypatch):
    """With a tractor chosen, the customer picker is handed that tractor's customers."""
    captured = {}

    class FakeDialog:
        def __init__(self, rows, parent=None, tractor_rows=None, tractor_name=None):
            captured["rows"] = rows
            captured["tractor_rows"] = tractor_rows
            captured["tractor_name"] = tractor_name
            self.selected = {"customer_id": 2, "customer_name": "مؤسسة النور"}

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(screen_module, "TawridCustomerPickerDialog", FakeDialog)
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["tractor_id"], 7)
    screen._party_labels["tractor"].setText("محمد أحمد — وش 1234")
    screen.pick_customer()
    assert captured["tractor_rows"] == screen._fake_backend.customers_for_tractor(7)
    assert captured["tractor_name"] == "محمد أحمد — وش 1234"


def test_picking_crusher_after_tractor_scopes_the_dialog(screen, monkeypatch):
    captured = {}

    class FakeDialog:
        def __init__(self, rows, parent=None, tractor_rows=None, tractor_name=None):
            captured["tractor_rows"] = tractor_rows
            self.selected = {"supplier_id": 4, "supplier_name": "مكة ستون"}

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(screen_module, "TawridSupplierPickerDialog", FakeDialog)
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["tractor_id"], 7)
    screen.pick_supplier()
    assert captured["tractor_rows"] == screen._fake_backend.crushers_for_tractor(7)


def test_picking_customer_without_tractor_passes_no_scope(screen, monkeypatch):
    captured = {}

    class FakeDialog:
        def __init__(self, rows, parent=None, tractor_rows=None, tractor_name=None):
            captured["tractor_rows"] = tractor_rows
            self.selected = None

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(screen_module, "TawridCustomerPickerDialog", FakeDialog)
    screen.new_record()  # a fresh blank بون, no tractor picked
    screen.pick_customer()
    assert captured["tractor_rows"] is None


# --- save validation ---------------------------------------------------------

def test_save_needs_customer_and_crusher(screen, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    screen.set_mode("new")
    screen._set_editor_value(screen.inputs["ticket_no"], 5000)
    screen.save_record()  # no customer yet
    assert screen.service.saved is None
    assert any("العميل" in w for w in warnings)


# --- loading a saved ticket fills the active tab -----------------------------

def test_loading_a_ticket_fills_the_cards(screen):
    screen._load_ticket(10)
    assert screen._party_labels["customer"].text() == "مؤسسة النور"
    assert screen._party_labels["supplier"].text() == "مكة ستون"
    assert screen.inputs["price_cus"].text() == "80"
    # And a switch carries the loaded record onto the other tab.
    screen.tabs.setCurrentIndex(1)
    assert screen._party_labels["customer"].text() == "مؤسسة النور"
    assert screen.inputs["price_cus"].text() == "80"
