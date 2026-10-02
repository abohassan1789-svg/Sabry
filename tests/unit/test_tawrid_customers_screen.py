"""Widget tests for شاشة العملاء — قسم التوريدات (headless Qt, no database).

The screen is "Model 2": the shared CRUD form plus an account summary strip,
with the two price sets in tabs underneath. These cover the UI contract that
depends on, plus the defects a user would otherwise hit on the first record:

* ``get_record`` returns only the columns the TableSpec declares, so the record
  handed to ``_fill_form`` has **no** ``customer_id`` — the summary and the
  price grid both have to read the id from ``current_id`` instead.
* The ten item prices are ``hidden_on_form``, so the base ``_fill_form`` skips
  them; the screen must fill them itself or every saved price reads back blank.
* الحالة must never be blank and the money boxes must never be empty on save —
  those columns are NOT NULL, so a blank reached the user as a raw
  ``NotNullViolation`` instead of a saved record.
* Repainting the grid must not be mistaken for a user edit and written back.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.tawrid_customer_service import CustomerBalance, TractorPrice
from app.ui.screens import tawrid_customers_screen as screen_module
from app.ui.screens.tawrid_customers_screen import (
    PRICE_FIELDS,
    TawridCustomersScreen,
    _money,
    _parse_money,
)

CUSTOMER_ID = 5
OPENING = Decimal("297000")

GRID_ROW = TractorPrice(
    price_id=49,
    tractor_id=11,
    tractor_code=3,
    driver_name="السعيد معروف",
    trailer_no="3581",
    head_no="7814",
    load_volume=Decimal("60.50"),
    price_sen=Decimal("180.00"),
    price_raml=Decimal("0.00"),
    default_sen=Decimal("140.00"),
    default_raml=Decimal("0.00"),
)


class FakeService:
    """Stands in for ReviewDataService: the screen only lists/reads through it."""

    def list_records(self, spec, keyword="", limit=500):
        return []

    def list_records_with_columns(self, *args, **kwargs):
        return [], []

    def get_record(self, spec, record_id):
        return {}

    def next_id(self, spec):
        return 1


class FakeBackend:
    """Stands in for TawridCustomerService."""

    def __init__(self, rows=None):
        self.asked_for = []
        self.rows = list(rows or [])
        self.updates = []
        self.added = []
        self.deleted = []
        self.movement = 0

    def next_code(self):
        return 102

    def for_customer(self, customer_id):
        self.asked_for.append(customer_id)
        if customer_id is None:
            return CustomerBalance()
        return CustomerBalance(opening_balance=OPENING)

    def tractor_prices(self, customer_id):
        return list(self.rows) if customer_id is not None else []

    def available_tractors(self, customer_id):
        return [{"tractor_id": 13, "driver_name": "احمد معروف",
                 "trailer_no": "2175", "price_sen": Decimal("140"),
                 "price_raml": Decimal("0")}]

    def add_tractor_price(self, customer_id, tractor_id, load, sen, raml):
        self.added.append((customer_id, tractor_id, load, sen, raml))
        return 100

    def update_tractor_price(self, price_id, load, sen, raml):
        self.updates.append((price_id, load, sen, raml))

    def delete_tractor_price(self, price_id):
        self.deleted.append(price_id)

    def price_row_count(self, customer_id):
        return len(self.rows)

    def has_movement(self, customer_id):
        return self.movement


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    view = TawridCustomersScreen(FakeService())
    backend = FakeBackend([GRID_ROW])
    monkeypatch.setattr(view, "_backend", lambda: backend)
    view._fake_backend = backend
    return view


# --- money formatting -------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (Decimal("297000"), "297,000.00"),
    (Decimal("0"), "0.00"),
    (Decimal("-412530"), "412,530.00-"),
    (None, "0.00"),
])
def test_money_formatting(value, expected):
    assert _money(value) == expected


@pytest.mark.parametrize("text,expected", [
    ("1,234.50", Decimal("1234.50")),
    ("  180 ", Decimal("180")),
    ("", Decimal("0")),          # blank means zero, not NULL
    (None, Decimal("0")),
    ("55,738.00-", Decimal("-55738.00")),
    ("abc", None),               # unparseable -> caller puts the old value back
])
def test_parsing_a_grid_cell(text, expected):
    assert _parse_money(text) == expected


# --- the regression that made the summary useless ---------------------------

def test_summary_uses_current_id_when_the_record_omits_the_primary_key(screen):
    """``get_record`` never returns ``customer_id`` — the summary must still fill."""
    screen.current_id = CUSTOMER_ID
    screen._fill_form({"customer_name": "نيو جيزة", "customer_code": 5})

    assert screen._fake_backend.asked_for == [CUSTOMER_ID]
    assert screen._stat_values["opening"].text() == "297,000.00"
    assert screen._stat_values["balance"].text() == "297,000.00"


def test_summary_resets_when_the_form_is_cleared(screen):
    screen.current_id = CUSTOMER_ID
    screen._fill_form({"customer_name": "نيو جيزة"})
    screen.current_id = None
    screen._clear_form()
    assert screen._stat_values["opening"].text() == "0.00"
    assert screen._stat_values["balance"].text() == "0.00"


def test_movement_figures_show_a_dash_until_later_phases_land(screen):
    screen._show_balance(CustomerBalance(opening_balance=OPENING))
    assert screen._stat_values["tickets"].text() == screen_module._PENDING
    assert screen._ledger_values["invoiced"].text() == screen_module._PENDING
    assert screen._ledger_values["collected"].text() == screen_module._PENDING
    assert screen._ledger_values["opening"].text() == "297,000.00"


def test_ledger_shows_signed_movements_once_available(screen):
    screen._show_balance(CustomerBalance(
        opening_balance=OPENING, tickets_count=168,
        invoiced=Decimal("1004120"), collected=Decimal("888590"),
        movements_available=True))
    assert screen._stat_values["tickets"].text() == "168"
    assert screen._ledger_values["invoiced"].text() == "+ 1,004,120.00"
    assert screen._ledger_values["collected"].text() == "- 888,590.00"
    assert screen._ledger_values["net"].text() == "412,530.00"


def test_a_failing_summary_never_breaks_the_form(screen, monkeypatch):
    class Boom:
        def for_customer(self, _):
            raise RuntimeError("database down")

        def tractor_prices(self, _):
            raise RuntimeError("database down")

    monkeypatch.setattr(screen, "_backend", lambda: Boom())
    screen._fill_form({"customer_name": "نيو جيزة"})  # must not raise
    assert screen._stat_values["balance"].text() == "0.00"


# --- the hidden item prices -------------------------------------------------

def test_all_ten_item_price_editors_exist_on_the_screen(screen):
    """They are hidden_on_form, so only this screen's own tab creates them."""
    assert len(PRICE_FIELDS) == 10
    for name in PRICE_FIELDS:
        assert name in screen.inputs, f"{name} has no editor"


def test_hidden_item_prices_are_filled_even_though_the_base_skips_them(screen):
    """The base ``_fill_form`` skips hidden fields; without the override every
    saved price would read back blank."""
    screen.current_id = CUSTOMER_ID
    screen._fill_form({
        "customer_name": "نيو جيزة",
        "price_sen1": "372.50",
        "price_sen6_bodra": "340.00",
    })
    assert screen.inputs["price_sen1"].text() == "372.50"
    assert screen.inputs["price_sen6_bodra"].text() == "340.00"


def test_blank_money_boxes_become_zero_on_save(screen, monkeypatch):
    saved = {}
    monkeypatch.setattr(TawridCustomersScreen.__bases__[0], "save_record",
                        lambda self: saved.update(
                            {n: self._editor_value(e) for n, e in self.inputs.items()}))
    for name in ("opening_balance", "discount_percent", *PRICE_FIELDS):
        screen._set_editor_value(screen.inputs[name], "")

    screen.save_record()

    for name in ("opening_balance", "discount_percent", *PRICE_FIELDS):
        assert str(saved[name]) == "0", f"{name} should have become 0, got {saved[name]!r}"


# --- the NOT NULL / status defects ------------------------------------------

def test_status_combo_has_no_blank_option_and_defaults_to_active(screen):
    combo = screen.inputs["is_active"]
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == ["نشط", "موقوف"]
    assert combo.currentText() == "نشط"


def test_clearing_the_form_keeps_status_meaningful(screen):
    screen._clear_form()
    assert screen.inputs["is_active"].currentText() == "نشط"


def test_new_record_prefills_the_next_code(screen):
    screen.new_record()
    assert screen.inputs["customer_code"].text() == "102"


@pytest.mark.parametrize("stored,shown", [(True, "نشط"), (False, "موقوف"), (None, "نشط")])
def test_stored_boolean_renders_as_the_arabic_label(screen, stored, shown):
    assert screen._display_value("is_active", stored) == shown


def test_current_record_label_names_the_customer(screen):
    screen.current_id = CUSTOMER_ID
    screen._fill_form({"customer_name": "نيو جيزة", "customer_code": 5})
    assert screen.summary_label.text() == "السجل الحالي: نيو جيزة — مسلسل 5"


# --- the customer × tractor grid --------------------------------------------

def test_the_grid_shows_the_plate_numbers_and_the_tractor_default(screen):
    screen.current_id = CUSTOMER_ID
    screen._refresh_grid()

    assert screen.grid.rowCount() == 1
    texts = [screen.grid.item(0, col).text() for col in range(screen.grid.columnCount())]
    assert texts[0] == "السعيد معروف"
    assert texts[1] == "3581"
    assert texts[2] == "7814"
    assert texts[3] == "60.50"
    assert texts[4] == "180.00"
    # The tractor's own rate, so the reason the row exists is visible.
    assert texts[6] == "سن 140.00 / رمل 0.00"


def test_the_tab_title_counts_the_grid_rows(screen):
    screen.current_id = CUSTOMER_ID
    screen._refresh_grid()
    assert screen._tabs.tabText(1) == "أسعار الجرارات (1)"


def test_only_the_three_typed_columns_are_editable(screen):
    from PySide6.QtCore import Qt

    screen.current_id = CUSTOMER_ID
    screen.set_mode("edit")
    screen._refresh_grid()

    editable = [
        bool(screen.grid.item(0, col).flags() & Qt.ItemIsEditable)
        for col in range(screen.grid.columnCount())
    ]
    # driver / trailer / head come from the tractor card; defaults are computed.
    assert editable == [False, False, False, True, True, True, False]


def test_repainting_the_grid_is_not_mistaken_for_a_user_edit(screen):
    """Without blocking signals, every refresh would write the rows back."""
    screen.current_id = CUSTOMER_ID
    screen._refresh_grid()
    screen._refresh_grid()
    assert screen._fake_backend.updates == []


def test_editing_a_cell_saves_the_whole_row(screen):
    screen.current_id = CUSTOMER_ID
    screen.set_mode("edit")
    screen._refresh_grid()

    screen.grid.item(0, 4).setText("185.00")  # سعر النقل - سن

    assert screen._fake_backend.updates == [
        (49, Decimal("60.50"), Decimal("185.00"), Decimal("0.00"))
    ]


def test_an_invalid_cell_is_refused_and_never_saved(screen, monkeypatch):
    monkeypatch.setattr(screen_module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))
    screen.current_id = CUSTOMER_ID
    screen.set_mode("edit")
    screen._refresh_grid()

    screen.grid.item(0, 3).setText("مش رقم")

    assert screen._fake_backend.updates == []
    # The stored value is put back on screen.
    assert screen.grid.item(0, 3).text() == "60.50"


def test_a_negative_price_is_refused(screen, monkeypatch):
    monkeypatch.setattr(screen_module.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))
    screen.current_id = CUSTOMER_ID
    screen.set_mode("edit")
    screen._refresh_grid()

    screen.grid.item(0, 5).setText("-10")

    assert screen._fake_backend.updates == []


def test_the_grid_is_locked_until_the_customer_is_saved(screen):
    screen.current_id = None
    screen.set_mode("new")
    assert screen.grid_add_button.isEnabled() is False
    assert "احفظ بيانات العميل أولاً" in screen.grid_hint.text()


def test_the_grid_is_read_only_in_view_mode(screen):
    screen.current_id = CUSTOMER_ID
    screen.set_mode("view")
    assert screen.grid_add_button.isEnabled() is False
    assert "اضغط «تعديل»" in screen.grid_hint.text()


def _stub_picker(monkeypatch, chosen, accepted=True):
    """Replace the picker dialog with one that returns a fixed answer."""
    from PySide6.QtWidgets import QDialog

    class StubPicker:
        def __init__(self, tractors, parent=None):
            StubPicker.offered = tractors
            self.selected = chosen

        def exec(self):
            return QDialog.Accepted if accepted else QDialog.Rejected

    monkeypatch.setattr(screen_module, "TawridTractorPickerDialog", StubPicker)
    return StubPicker


def test_adding_a_tractor_seeds_its_own_rates(screen, monkeypatch):
    """Access left a new subform row blank, which priced the haulage at zero."""
    _stub_picker(monkeypatch, {"tractor_id": 13, "driver_name": "احمد معروف",
                               "price_sen": Decimal("140"), "price_raml": Decimal("0")})
    screen.current_id = CUSTOMER_ID
    screen.add_tractor_price()

    assert screen._fake_backend.added == [(CUSTOMER_ID, 13, 0, Decimal("140"), Decimal("0"))]


def test_the_picker_is_offered_only_tractors_not_already_priced(screen, monkeypatch):
    stub = _stub_picker(monkeypatch, {"tractor_id": 13, "driver_name": "احمد معروف",
                                      "price_sen": 0, "price_raml": 0})
    screen.current_id = CUSTOMER_ID
    screen.add_tractor_price()

    assert [t["tractor_id"] for t in stub.offered] == [13]


def test_cancelling_the_tractor_picker_adds_nothing(screen, monkeypatch):
    _stub_picker(monkeypatch, None, accepted=False)
    screen.current_id = CUSTOMER_ID
    screen.add_tractor_price()

    assert screen._fake_backend.added == []


# --- the form panel the user asked to be scroll-free ------------------------

def test_the_screen_title_and_current_record_line_are_off_the_form(screen):
    """Both repeat what the header bar and the first two boxes already say, and
    they were what pushed the eight fields into a scrollbar."""
    assert screen.summary_label.isVisible() is False
    # Still a live widget: the base class writes to it on every load.
    screen.current_id = CUSTOMER_ID
    screen._fill_form({"customer_name": "نيو جيزة", "customer_code": 5})
    assert screen.summary_label.text() == "السجل الحالي: نيو جيزة — مسلسل 5"


# --- delete protection ------------------------------------------------------

def test_a_customer_with_movement_cannot_be_deleted(screen, monkeypatch):
    """The defect that left 911 legacy tickets pointing at nothing."""
    shown = {}
    monkeypatch.setattr(screen_module.QMessageBox, "warning",
                        staticmethod(lambda _p, title, text, *a, **k: shown.update(
                            {"title": title, "text": text})))
    deleted = []
    monkeypatch.setattr(TawridCustomersScreen.__bases__[0], "delete_record",
                        lambda self: deleted.append(self.current_id))

    screen.current_id = CUSTOMER_ID
    screen._fake_backend.movement = 168
    screen.delete_record()

    assert deleted == []
    assert shown["title"] == "لا يمكن الحذف"
    assert "موقوف" in shown["text"]


def test_a_customer_without_movement_still_deletes(screen, monkeypatch):
    deleted = []
    monkeypatch.setattr(TawridCustomersScreen.__bases__[0], "delete_record",
                        lambda self: deleted.append(self.current_id))

    screen.current_id = CUSTOMER_ID
    screen._fake_backend.movement = 0
    screen.delete_record()

    assert deleted == [CUSTOMER_ID]


def test_the_delete_warning_names_the_grid_rows_that_go_with_him(screen):
    screen.current_id = CUSTOMER_ID
    warning = screen._cascade_warning()
    assert warning is not None
    assert "1 صف من شبكة أسعار الجرارات" in warning
