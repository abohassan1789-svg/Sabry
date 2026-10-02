"""Widget tests for شاشة الجرارات (headless / offscreen Qt, no database).

The screen is "Model 8": the shared CRUD form plus a live account summary. These
cover the UI contract that summary depends on, and two defects found while
building it that a user would otherwise hit on their very first record:

* ``get_record`` returns only the columns the TableSpec declares, so the record
  handed to ``_fill_form`` has **no** ``tractor_id``. Reading the id from there
  left the summary stuck on zero for every tractor.
* الحالة must never be blank and the money boxes must never be empty on save —
  all three columns are NOT NULL, so a blank reached the user as a raw
  ``NotNullViolation`` instead of a saved record.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.tawrid_tractor_service import TractorBalance
from app.ui.screens import tawrid_tractors_screen as screen_module
from app.ui.screens.tawrid_tractors_screen import TawridTractorsScreen, _money

TRACTOR_ID = 7
OPENING = Decimal("209816")


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
    """Stands in for TawridTractorService."""

    def __init__(self):
        self.asked_for = []

    def next_code(self):
        return 12

    def for_tractor(self, tractor_id):
        self.asked_for.append(tractor_id)
        if tractor_id is None:
            return TractorBalance()
        return TractorBalance(opening_balance=OPENING)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    view = TawridTractorsScreen(FakeService())
    backend = FakeBackend()
    monkeypatch.setattr(view, "_backend", lambda: backend)
    view._fake_backend = backend
    return view


# --- money formatting -------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (Decimal("209816"), "209,816.00"),
    (Decimal("0"), "0.00"),
    (Decimal("-55738"), "55,738.00-"),
    (None, "0.00"),
])
def test_money_formatting(value, expected):
    assert _money(value) == expected


# --- the regression that made the summary useless ---------------------------

def test_summary_uses_current_id_when_the_record_omits_the_primary_key(screen):
    """``get_record`` never returns ``tractor_id`` — the summary must still fill."""
    screen.current_id = TRACTOR_ID
    screen._fill_form({"driver_name": "السعيد معروف", "trailer_no": "3581"})

    assert screen._fake_backend.asked_for == [TRACTOR_ID]
    assert screen._stat_values["opening"].text() == "209,816.00"
    assert screen._stat_values["balance"].text() == "209,816.00"


def test_summary_resets_when_the_form_is_cleared(screen):
    screen.current_id = TRACTOR_ID
    screen._fill_form({"driver_name": "السعيد معروف"})
    screen._clear_form()
    assert screen._stat_values["opening"].text() == "0.00"
    assert screen._stat_values["balance"].text() == "0.00"


def test_movement_figures_show_a_dash_until_later_phases_land(screen):
    screen._show_balance(TractorBalance(opening_balance=OPENING))
    assert screen._stat_values["trips"].text() == screen_module._PENDING
    assert screen._ledger_values["earned"].text() == screen_module._PENDING
    assert screen._ledger_values["paid"].text() == screen_module._PENDING
    # The opening balance is real, so it is shown as a number either way.
    assert screen._ledger_values["opening"].text() == "209,816.00"


def test_ledger_shows_signed_movements_once_available(screen):
    screen._show_balance(TractorBalance(
        opening_balance=OPENING, trips_count=61,
        earned=Decimal("88430"), paid=Decimal("243148"), movements_available=True))
    assert screen._stat_values["trips"].text() == "61"
    assert screen._ledger_values["earned"].text() == "+ 88,430.00"
    assert screen._ledger_values["paid"].text() == "- 243,148.00"
    assert screen._ledger_values["net"].text() == "55,098.00"


def test_a_failing_summary_never_breaks_the_form(screen, monkeypatch):
    class Boom:
        def for_tractor(self, _):
            raise RuntimeError("database down")

    monkeypatch.setattr(screen, "_backend", lambda: Boom())
    screen._fill_form({"driver_name": "السعيد معروف"})  # must not raise
    assert screen._stat_values["balance"].text() == "0.00"


# --- the NOT NULL defects ---------------------------------------------------

def test_status_combo_has_no_blank_option_and_defaults_to_active(screen):
    combo = screen.inputs["is_active"]
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == ["نشط", "موقوف"]
    assert combo.currentText() == "نشط"


def test_clearing_the_form_keeps_status_meaningful(screen):
    screen._clear_form()
    assert screen.inputs["is_active"].currentText() == "نشط"


def test_blank_money_boxes_become_zero_on_save(screen, monkeypatch):
    saved = {}
    monkeypatch.setattr(TawridTractorsScreen.__bases__[0], "save_record",
                        lambda self: saved.update(
                            {n: self._editor_value(e) for n, e in self.inputs.items()}))
    for name in ("price_sen", "price_raml", "opening_balance"):
        screen._set_editor_value(screen.inputs[name], "")

    screen.save_record()

    for name in ("price_sen", "price_raml", "opening_balance"):
        assert str(saved[name]) == "0", f"{name} should have become 0, got {saved[name]!r}"


def test_new_record_prefills_the_next_code(screen):
    screen.new_record()
    assert screen.inputs["tractor_code"].text() == "12"


# --- boolean display --------------------------------------------------------

@pytest.mark.parametrize("stored,shown", [(True, "نشط"), (False, "موقوف"), (None, "نشط")])
def test_stored_boolean_renders_as_the_arabic_label(screen, stored, shown):
    assert screen._display_value("is_active", stored) == shown


def test_other_fields_are_displayed_unchanged(screen):
    assert screen._display_value("driver_name", "السعيد معروف") == "السعيد معروف"
    assert screen._display_value("trailer_no", "0345") == "0345"


def test_current_record_label_names_the_driver(screen):
    """The base label reads the absent primary key, so it must be set here."""
    screen.current_id = TRACTOR_ID
    screen._fill_form({"driver_name": "السعيد معروف", "tractor_code": 3})
    assert screen.summary_label.text() == "السجل الحالي: السعيد معروف — مسلسل 3"
