"""Widget tests for شاشة تكعيب الكسّارات — قسم التوريدات (headless Qt, no DB).

Layout is "Model 9": a header band, each line rendered as a small card, a totals
footer, no sheet list on the screen («بحث عن كشف» + nav instead). These pin the
master→detail contract:

* The list is built and hidden — the base class drives selection through it.
* There is no price anywhere; the line card shows only the volume, and the totals
  are volume aggregates.
* Lines can only be added once the header is saved (a line needs a parent).
* Saving is refused without a crusher (crusher_id is NOT NULL).
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.tawrid_cubing_service import CubingLine, CubingTotals
from app.ui.screens import tawrid_cubing_screen as screen_module
from app.ui.screens.tawrid_cubing_screen import TawridCubingScreen

LIST_ROWS = [
    {"cubing_id": 1, "sheet_no": 15, "sheet_date": "2025-12-01"},
    {"cubing_id": 2, "sheet_no": 14, "sheet_date": "2025-04-19"},
]

RECORD_1 = {
    "cubing_id": 1, "sheet_no": 15, "sheet_date": "2025-12-01",
    "crusher_id": 3, "notes": "",
}

LINES_1 = [
    CubingLine(1, 1, 1, 7, "عمرو كمال", "4925", Decimal("58"), False),
    CubingLine(2, 1, 2, None, "مشال", "0", Decimal("0"), True),
]


class FakeService:
    def __init__(self):
        self.saved = None
        self.deleted = None

    def list_records(self, spec, keyword="", limit=500):
        return list(LIST_ROWS)

    def get_record(self, spec, record_id):
        return dict(RECORD_1) if int(record_id) == 1 else {}

    def save_record(self, spec, payload, record_id):
        self.saved = dict(payload)
        return record_id or 99

    def next_id(self, spec):
        return 1

    def delete_record(self, spec, record_id):
        self.deleted = record_id


class FakeBackend:
    def __init__(self):
        self.updated = []
        self.deleted_lines = []

    def next_sheet_no(self):
        return 22

    def sheet_no_exists(self, sheet_no, exclude_id=None):
        return False

    def supplier_picker_rows(self):
        return [{"supplier_id": 3, "supplier_code": 1, "supplier_name": "الهدي", "is_active": True}]

    def tractor_picker_rows(self):
        return [{"tractor_id": 7, "driver_name": "عمرو كمال", "head_no": "4925", "trailer_no": "4925"}]

    def lines(self, cubing_id):
        return list(LINES_1) if str(cubing_id) == "1" else []

    def line_count(self, cubing_id):
        return len(self.lines(cubing_id))

    def add_line(self, *a, **k):
        return 3

    def update_line_volume(self, line_id, volume):
        self.updated.append((line_id, volume))

    def delete_line(self, line_id):
        self.deleted_lines.append(line_id)

    def totals(self, cubing_id):
        if str(cubing_id) == "1":
            return CubingTotals(line_count=2, total_volume=Decimal("58"),
                                average_volume=Decimal("29"), max_volume=Decimal("58"),
                                zero_count=1, deleted_count=1)
        return CubingTotals()

    def for_cubing(self, cubing_id):
        return {**RECORD_1, "supplier_name": "الهدي", "supplier_code": 1}

    def search_cubing(self, keyword="", limit=300):
        return list(LIST_ROWS)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(screen_module, "TawridCubingService", lambda: backend)
    view = TawridCubingScreen(FakeService())
    view._fake_backend = backend
    return view


# --- layout ------------------------------------------------------------------

def test_the_list_is_built_but_hidden(screen):
    assert screen.list_panel.isVisibleTo(screen) is False
    assert screen.table.rowCount() == len(LIST_ROWS)


def test_the_search_and_nav_buttons_replace_the_list(screen):
    assert screen.find_button.text() == "بحث عن كشف"
    assert set(screen.nav_buttons) == {"first", "prev", "next", "last"}


def test_the_header_has_a_crusher_picker_and_totals_tiles(screen):
    assert screen._crusher_label is not None
    for key in ("total", "count", "average", "max", "deleted"):
        assert key in screen._stat_values


# --- loading a sheet renders header + line cards + totals --------------------

def test_loading_a_sheet_fills_the_header_and_cards(screen):
    screen._load_cubing(1)
    assert screen.current_id == 1
    assert "الهدي" in screen._crusher_label.text()
    assert len(screen._lines) == 2
    # one card editor per line
    assert set(screen._line_editors) == {1, 2}


def test_totals_footer_shows_the_volume_aggregates(screen):
    screen._load_cubing(1)
    assert screen._stat_values["total"].text() == "58"
    assert screen._stat_values["count"].text() == "2"
    assert screen._stat_values["deleted"].text() == "1"


def test_a_deleted_tractor_line_is_flagged(screen):
    screen._load_cubing(1)
    # LINES_1[1] is a deleted tractor; its meta must not crash and card exists.
    assert screen._lines[1].is_deleted is True


# --- new record --------------------------------------------------------------

def test_new_record_suggests_the_next_number_and_today(screen):
    screen.new_record()
    assert str(screen._val("sheet_no")) == "22"
    assert screen.summary_label.text() == "كشف جديد"


# --- line editing is gated on a saved header ---------------------------------

def test_lines_cannot_be_added_before_the_header_is_saved(screen):
    screen.new_record()          # current_id is None
    assert screen._can_edit_lines() is False
    assert screen.add_line_button.isEnabled() is False


def test_lines_become_editable_after_load_and_edit(screen):
    screen._load_cubing(1)
    screen.set_mode("edit")
    assert screen._can_edit_lines() is True
    assert screen.add_line_button.isEnabled() is True


# --- committing a volume -----------------------------------------------------

def test_editing_a_volume_persists_through_the_backend(screen):
    screen._load_cubing(1)
    screen.set_mode("edit")
    editor = screen._line_editors[1]
    editor.setText("70")
    screen._commit_volume(1, editor)
    assert (1, Decimal("70")) in screen._fake_backend.updated


def test_a_bad_volume_is_rejected(screen, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))
    screen._load_cubing(1)
    screen.set_mode("edit")
    editor = screen._line_editors[1]
    editor.setText("abc")
    screen._commit_volume(1, editor)
    assert warned


# --- save validation ---------------------------------------------------------

def test_save_refuses_without_a_crusher(screen, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))
    screen.new_record()
    screen.service.saved = None
    screen._set_editor_value(screen.inputs["sheet_no"], 22)  # crusher left blank
    screen.save_record()
    assert warned
    assert screen.service.saved is None


def test_save_writes_the_header_with_the_chosen_crusher(screen, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    screen.new_record()
    screen._set_editor_value(screen.inputs["sheet_no"], 22)
    screen._set_editor_value(screen.inputs["crusher_id"], 3)
    screen.save_record()
    assert screen.service.saved is not None
    assert str(screen.service.saved.get("crusher_id")) == "3"


# --- delete cascade warning --------------------------------------------------

def test_delete_warns_that_the_lines_go_too(screen):
    screen._load_cubing(1)
    warning = screen._cascade_warning()
    assert warning is not None and "2" in warning
