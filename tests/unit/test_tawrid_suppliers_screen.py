"""Widget tests for شاشة الكسّارات — قسم التوريدات (headless Qt, no database).

The screen is "Model 2-ب": the shared CRUD form plus an account summary strip,
the ten item prices in a panel beside the form, and **no list panel** — the
record list moved into a search dialog behind a button.

These cover the UI contract that depends on, plus the defects a user would
otherwise hit on the first record:

* The list panel is built and hidden, not deleted. The base class drives
  selection, the record count and ``_select_row_by_id`` through ``self.table``,
  so removing it would break navigation silently.
* With the list gone, الاول/السابق/التالي/الاخير are the only way to walk the
  cards — they are on ``Fproduct`` already, and they must not fire while a
  record is being edited.
* ``get_record`` returns only the columns the TableSpec declares, so the record
  handed to ``_fill_form`` has **no** ``supplier_id`` — the summary has to read
  the id from ``current_id`` instead.
* The ten item prices are ``hidden_on_form``, so the base ``_fill_form`` skips
  them; the screen must fill them itself or every saved price reads back blank.
* الحالة must never be blank and the money boxes must never be empty on save —
  those columns are NOT NULL, so a blank reached the user as a raw
  ``NotNullViolation`` instead of a saved record.
* A crusher with movement must not be deletable: crusher id 22 was deleted in
  Access while 4 tickets still referenced it, and ``TBBOOn`` records no crusher
  name to recover it from.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.tawrid_supplier_service import SupplierBalance
from app.ui.screens import tawrid_suppliers_screen as screen_module
from app.ui.screens.tawrid_suppliers_screen import (
    PRICE_FIELDS,
    TawridSuppliersScreen,
    _money,
)

SUPPLIER_ID = 1
OPENING = Decimal("1511010")

# Three cards, in the order the (hidden) list returns them.
RECORDS = {
    1: {"supplier_code": 1, "supplier_name": "الهدي", "phone": None,
        "is_active": True, "opening_balance": OPENING, "opening_date": None,
        "notes": None, "price_sen1": Decimal("180.00"), "price_sen2": Decimal("165.00"),
        "price_sen_ataqa": Decimal("160.00"), "price_sen6_safi": Decimal("120.00"),
        "price_sen6_bodra": Decimal("100.00"), "price_sen_adsa": Decimal("170.00"),
        "price_bodra": Decimal("55.00"), "price_raml": Decimal("0.00"),
        "price_sen_plus": Decimal("160.00"), "price_sen_modarag": Decimal("150.00")},
    3: {"supplier_code": 3, "supplier_name": "جولد ستون", "phone": None,
        "is_active": True, "opening_balance": Decimal("520000"), "opening_date": None,
        "notes": None, **{name: Decimal("0.00") for name in PRICE_FIELDS}},
    20: {"supplier_code": 60, "supplier_name": "محجر رملة", "phone": None,
         "is_active": True, "opening_balance": Decimal("0"), "opening_date": None,
         "notes": None, **{name: Decimal("0.00") for name in PRICE_FIELDS},
         "price_raml": Decimal("120.00")},
}
LIST_ROWS = [
    {"supplier_id": 1, "supplier_code": 1, "supplier_name": "الهدي"},
    {"supplier_id": 3, "supplier_code": 3, "supplier_name": "جولد ستون"},
    {"supplier_id": 20, "supplier_code": 60, "supplier_name": "محجر رملة"},
]


class FakeService:
    """Stands in for ReviewDataService: the screen only lists/reads through it."""

    def list_records(self, spec, keyword="", limit=500):
        return list(LIST_ROWS)

    def list_records_with_columns(self, *args, **kwargs):
        return list(LIST_ROWS), list(LIST_ROWS[0].keys())

    def get_record(self, spec, record_id):
        return dict(RECORDS.get(int(record_id), {}))

    def next_id(self, spec):
        return 1


class FakeBackend:
    """Stands in for TawridSupplierService."""

    def __init__(self):
        self.asked_for = []
        self.movement = 0
        self.rows = [
            {"supplier_id": 20, "supplier_code": 60, "supplier_name": "محجر رملة",
             "is_active": True, "balance": Decimal("7080")},
        ]

    def next_code(self):
        return 85

    def for_supplier(self, supplier_id):
        self.asked_for.append(supplier_id)
        if supplier_id is None:
            return SupplierBalance()
        return SupplierBalance(opening_balance=OPENING)

    def has_movement(self, supplier_id):
        return self.movement

    def picker_rows(self):
        return list(self.rows)

    def priced_item_count(self, supplier_id):
        return 9


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    view = TawridSuppliersScreen(FakeService())
    backend = FakeBackend()
    monkeypatch.setattr(view, "_backend", lambda: backend)
    view._fake_backend = backend
    return view


# --- money formatting -------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (Decimal("2623695"), "2,623,695.00"),
    (Decimal("0"), "0.00"),
    (Decimal("-11125"), "11,125.00-"),
    (None, "0.00"),
])
def test_money_formatting(value, expected):
    assert _money(value) == expected


# --- the list panel is hidden, not gone --------------------------------------

def test_the_record_list_is_built_but_hidden(screen):
    """The base class drives selection through it; deleting it breaks that."""
    assert screen.list_panel.isVisibleTo(screen) is False
    assert screen.table.rowCount() == len(LIST_ROWS)


def test_the_search_button_replaces_the_list(screen):
    assert screen.find_button.text() == "بحث عن كسّارة"


def test_the_first_card_is_loaded_on_open(screen):
    """refresh_table selects row 0, so the screen never opens on a blank form."""
    assert screen.current_id == 1
    assert screen.inputs["supplier_name"].text() == "الهدي"


# --- the item prices panel ---------------------------------------------------

def test_the_ten_prices_are_hidden_from_the_base_form(screen):
    hidden = {f.name for f in screen.spec.fields if f.hidden_on_form}
    assert hidden == set(PRICE_FIELDS)


def test_the_screen_builds_the_price_editors_itself(screen):
    """hidden_on_form means the base panel skipped them — they must still exist."""
    for name in PRICE_FIELDS:
        assert name in screen.inputs


def test_the_prices_are_filled_even_though_the_base_fill_skips_them(screen):
    assert screen.inputs["price_sen1"].text().startswith("180")
    assert screen.inputs["price_sen_modarag"].text().startswith("150")


def test_the_heading_counts_how_many_of_the_ten_are_priced(screen):
    """الهدي is priced for 9 of 10 — رملة is the one it does not sell."""
    assert screen._price_heading.text() == "أسعار الأصناف — 9 من 10"


def test_a_crusher_that_sells_one_item_says_so(screen):
    screen._load_supplier(20)
    assert screen._price_heading.text() == "أسعار الأصناف — 1 من 10"


# --- the two panels share the width the right way round ----------------------

def test_the_price_panel_is_the_wide_half(screen):
    """The regression this guards: the prices were pinned to a fixed 340px the
    ten label + money-box pairs did not fit into, so «180.00» rendered as
    «.00» while بيانات المورد — seven short boxes — had the whole rest of the
    row to itself."""
    from PySide6.QtWidgets import QScrollArea

    form = screen.findChild(QScrollArea)
    prices = screen._price_heading.parent()
    screen.resize(1690, 760)
    screen.show()
    QApplication.processEvents()
    try:
        assert form.width() < prices.width()
        assert form.horizontalScrollBar().isVisible() is False
        # Wide enough to print "1,511,010.00" without clipping.
        assert screen.inputs["price_sen1"].width() >= 150
    finally:
        screen.hide()


def test_the_price_panel_can_grow_and_is_not_pinned(screen):
    prices = screen._price_heading.parent()
    assert prices.minimumWidth() < prices.maximumWidth()


# --- the account summary -----------------------------------------------------

def test_the_summary_reads_the_id_from_current_id(screen):
    """get_record returns no supplier_id, so _fill_form must not rely on one."""
    assert "supplier_id" not in RECORDS[1]
    # Reloaded here because the fixture installs the fake backend after the
    # screen has already opened on the first card.
    screen._load_supplier(1)
    assert screen._fake_backend.asked_for[-1] == 1


def test_the_opening_balance_is_shown(screen):
    screen._load_supplier(1)
    assert screen._stat_values["opening"].text() == "1,511,010.00"


def test_movement_figures_read_as_pending_until_those_tables_exist(screen):
    assert screen._stat_values["tickets"].text() == "—"
    assert screen._ledger_values["purchased"].text() == "—"
    assert screen._ledger_values["paid"].text() == "—"


def test_the_tile_says_the_money_is_owed_to_the_crusher(screen):
    """The customer owes us; the crusher is owed by us."""
    captions = screen.findChildren(type(screen._stat_values["balance"]))
    assert any(label.text() == "المستحق له" for label in captions)


def test_the_ledger_names_the_supplier_side_of_the_account(screen):
    assert set(screen._ledger_values) == {"opening", "purchased", "paid", "net"}


# --- record navigation -------------------------------------------------------

def test_navigation_walks_the_hidden_list(screen):
    screen._navigate("next")
    assert screen.current_id == 3
    screen._navigate("next")
    assert screen.current_id == 20
    screen._navigate("first")
    assert screen.current_id == 1


def test_navigation_stops_at_the_ends(screen):
    screen._navigate("last")
    assert screen.current_id == 20
    screen._navigate("next")
    assert screen.current_id == 20


def test_the_back_buttons_are_disabled_on_the_first_card(screen):
    screen._navigate("first")
    assert screen.nav_buttons["first"].isEnabled() is False
    assert screen.nav_buttons["prev"].isEnabled() is False
    assert screen.nav_buttons["next"].isEnabled() is True


def test_navigation_and_search_are_disabled_while_editing(screen):
    screen.set_mode("edit")
    assert screen.find_button.isEnabled() is False
    assert all(b.isEnabled() is False for b in screen.nav_buttons.values())


def test_navigation_does_nothing_while_editing(screen):
    screen._navigate("first")
    before = screen.current_id
    screen.set_mode("edit")
    screen._navigate("next")
    assert screen.current_id == before


# --- the search dialog -------------------------------------------------------

def test_picking_a_crusher_loads_its_card(screen, monkeypatch):
    class FakeDialog:
        def __init__(self, rows, parent=None):
            self.selected = rows[0]

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.Accepted

    monkeypatch.setattr(screen_module, "TawridSupplierPickerDialog", FakeDialog)
    screen.open_lookup()
    assert screen.current_id == 20
    assert screen.inputs["supplier_name"].text() == "محجر رملة"


def test_cancelling_the_dialog_leaves_the_card_alone(screen, monkeypatch):
    class CancelledDialog:
        def __init__(self, rows, parent=None):
            self.selected = None

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.Rejected

    monkeypatch.setattr(screen_module, "TawridSupplierPickerDialog", CancelledDialog)
    before = screen.current_id
    screen.open_lookup()
    assert screen.current_id == before


def test_the_dialog_is_not_opened_while_editing(screen, monkeypatch):
    opened = []
    monkeypatch.setattr(
        screen_module.QMessageBox, "information",
        lambda *args, **kwargs: opened.append("warned")
    )
    monkeypatch.setattr(
        screen._fake_backend, "picker_rows",
        lambda: opened.append("listed") or []
    )
    screen.set_mode("edit")
    screen.open_lookup()
    assert opened == ["warned"]


# --- NOT NULL money boxes and الحالة ------------------------------------------

def test_the_status_combo_has_no_blank_option(screen):
    combo = screen.inputs["is_active"]
    assert [combo.itemText(i) for i in range(combo.count())] == ["نشط", "موقوف"]


def test_a_new_record_starts_active(screen):
    screen.new_record()
    assert screen.inputs["is_active"].currentText() == "نشط"


def test_a_new_record_gets_the_next_code_from_this_table(screen):
    screen.new_record()
    assert screen.inputs["supplier_code"].text() == "85"


def test_saving_turns_blank_money_boxes_into_zero(screen, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        screen_module.BaseCrudScreen, "save_record",
        lambda self: saved.update({n: self.inputs[n].text() for n in PRICE_FIELDS})
    )
    screen.set_mode("edit")
    for name in PRICE_FIELDS:
        screen.inputs[name].setText("")
    screen.inputs["opening_balance"].setText("")
    screen.save_record()
    assert set(saved.values()) == {"0"}
    assert screen.inputs["opening_balance"].text() == "0"


# --- the deletion guard ------------------------------------------------------

def test_a_crusher_with_movement_cannot_be_deleted(screen, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        screen_module.QMessageBox, "warning",
        lambda *args, **kwargs: warnings.append(args[2])
    )
    deleted = []
    monkeypatch.setattr(
        screen_module.BaseCrudScreen, "delete_record", lambda self: deleted.append(1)
    )
    screen._fake_backend.movement = 4
    screen.delete_record()
    assert deleted == []
    assert "4 حركة" in warnings[0]
    assert "موقوف" in warnings[0]


def test_a_crusher_with_no_movement_deletes_normally(screen, monkeypatch):
    deleted = []
    monkeypatch.setattr(
        screen_module.BaseCrudScreen, "delete_record", lambda self: deleted.append(1)
    )
    screen._fake_backend.movement = 0
    screen.delete_record()
    assert deleted == [1]
