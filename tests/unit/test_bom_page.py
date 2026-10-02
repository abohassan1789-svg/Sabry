"""Headless UI tests for the BOM screen (Model 4 — split header).

Qt runs offscreen. The screen is driven by a real :class:`BomService` wired to
the in-memory fake repository from the service tests, so the widget wiring
(build, live line/total maths, collect-form, save round-trip) is exercised
without a database or a visible window.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.bom_service import BomService  # noqa: E402
from tests.services.test_bom_service import FakeBomRepo, FINISHED_ID  # noqa: E402


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _silence_dialogs(monkeypatch):
    """Stop modal QMessageBox calls from blocking the offscreen run."""
    import app.ui.screens.bom_page as mod

    monkeypatch.setattr(mod.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mod.QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mod.QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        mod.QMessageBox, "question", staticmethod(lambda *a, **k: mod.QMessageBox.Yes)
    )


def _make_page(qt_app):
    from app.ui.screens.bom_page import BomPage

    return BomPage(service=BomService(repository=FakeBomRepo()))


def _add(page, component_id, qty, price, *, code=None, name="خشب", unit="متر"):
    page._append_line(
        component_product_id=component_id, item_code=code, name=name, unit=unit,
        quantity=Decimal(qty), price=Decimal(price),
    )


# --- build ------------------------------------------------------------------

def test_screen_builds_with_six_columns(qt_app):
    page = _make_page(qt_app)
    assert page.lines_table.columnCount() == 6
    headers = [page.lines_table.horizontalHeaderItem(c).text() for c in range(6)]
    assert headers == ["كود الصنف", "اسم الصنف", "الوحدة", "الكمية", "السعر", "الإجمالي"]
    # Split-header widgets + read-only document fields exist.
    assert page.product_input.isReadOnly()
    assert page.bom_number_value.isReadOnly()
    assert page.total_value.text() == "0.00"


# --- live line + total maths ------------------------------------------------

def test_line_and_total_update_live(qt_app):
    page = _make_page(qt_app)
    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "منتج تام"}
    _add(page, 1, "2.5", "10.00")   # 25.00
    _add(page, 2, "3", "4.00")      # 12.00
    # الإجمالي cell of the first row and the header total.
    assert page.lines_table.item(0, 5).text() == "25.00"
    assert page.total_value.text() == "37.00"


def test_bom_number_is_reserved_and_readonly_on_new(qt_app):
    page = _make_page(qt_app)
    page.enter_new_mode()
    assert page.bom_number_value.text() == "BOM-0001"
    assert page.bom_number_value.isReadOnly()


# --- collect form + save round-trip -----------------------------------------

def test_save_sends_component_lines_to_service(qt_app):
    svc = BomService(repository=FakeBomRepo())
    from app.ui.screens.bom_page import BomPage
    page = BomPage(service=svc)

    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "منتج تام"}
    page.product_input.setText("منتج تام")
    _add(page, 1, "2", "10.00")   # 20.00
    _add(page, 2, "5", "4.00")    # 20.00

    form = page._collect_form()
    assert form["product_id"] == FINISHED_ID
    assert form["bom_number"] == "BOM-0001"
    assert [ln["component_product_id"] for ln in form["lines"]] == [1, 2]

    page.on_save()
    # The fake repo recorded the saved header + lines; the screen reloaded it.
    stored = svc.repository.inserted_headers[0]
    assert stored["total_material_cost"] == Decimal("40.00")
    assert page._current is not None
    assert page.bom_number_value.text() == "BOM-0001"


def test_editable_columns_are_quantity_and_price_only(qt_app):
    from PySide6.QtCore import Qt

    page = _make_page(qt_app)
    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "منتج تام"}
    _add(page, 1, "2", "10.00")
    # code/name/unit are not editable; quantity/price are.
    assert not (page.lines_table.item(0, 0).flags() & Qt.ItemIsEditable)
    assert not (page.lines_table.item(0, 1).flags() & Qt.ItemIsEditable)
    assert not (page.lines_table.item(0, 2).flags() & Qt.ItemIsEditable)
    assert page.lines_table.item(0, 3).flags() & Qt.ItemIsEditable
    assert page.lines_table.item(0, 4).flags() & Qt.ItemIsEditable
    # total is derived (read-only).
    assert not (page.lines_table.item(0, 5).flags() & Qt.ItemIsEditable)


# ---------------------------------------------------------------------------
# Full journey helpers
# ---------------------------------------------------------------------------
from datetime import date  # noqa: E402


def _new_form(**overrides):
    form = {
        "bom_number": "",
        "bom_date": date(2026, 8, 17),
        "product_id": FINISHED_ID,
        "lines": [
            {"component_product_id": 1, "quantity": "2", "price": "10.00"},  # 20.00
            {"component_product_id": 2, "quantity": "5", "price": "4.00"},   # 20.00
        ],
    }
    form.update(overrides)
    return form


def _page_with_saved(qt_app):
    """A page whose service already holds one saved BOM; returns (page, bom_id)."""
    from app.ui.screens.bom_page import BomPage

    svc = BomService(repository=FakeBomRepo())
    saved = svc.create_bom(_new_form())
    page = BomPage(service=svc)
    return page, saved["header"]["id"]


# --- New resets previous state ----------------------------------------------

def test_new_clears_previous_document_state(qt_app):
    page, bom_id = _page_with_saved(qt_app)
    page.load_bom(bom_id)
    assert page.lines_table.rowCount() == 2
    page.on_new()
    assert page._current is None
    assert page._product is None
    assert page.product_input.text() == ""
    assert page.lines_table.rowCount() == 0
    assert page.total_value.text() == "0.00"
    # A fresh automatic number is reserved (the first BOM consumed BOM-0001).
    assert page.bom_number_value.text() == "BOM-0002"


# --- Open existing shows stored snapshots -----------------------------------

def test_open_existing_loads_stored_snapshots(qt_app):
    page, bom_id = _page_with_saved(qt_app)
    page.load_bom(bom_id)
    assert page.bom_number_value.text() == "BOM-0001"
    assert page._product["id"] == FINISHED_ID
    assert page.product_input.text() == "منتج تام"
    assert page.lines_table.rowCount() == 2
    # Row 0 = component 1 (code 1001 / خشب / متر), qty 2 × 10 = 20.00.
    assert page.lines_table.item(0, 0).text() == "1001"
    assert page.lines_table.item(0, 1).text() == "خشب"
    assert page.lines_table.item(0, 2).text() == "متر"
    assert page.lines_table.item(0, 5).text() == "20.00"
    assert page.total_value.text() == "40.00"
    # Opened document sits in a safe view state: Save disabled, Edit enabled.
    assert not page.save_button.isEnabled()
    assert page.edit_button.isEnabled()


# --- Edit → update recalculates and does not add a header -------------------

def test_edit_then_update_recalculates(qt_app):
    page, bom_id = _page_with_saved(qt_app)
    page.load_bom(bom_id)
    page.on_edit()
    assert page._mode == "edit"
    # Change row 0 quantity 2 -> 4 (line 40) so the total becomes 60.
    page.lines_table.item(0, 3).setText("4")
    assert page.total_value.text() == "60.00"
    page.on_save()
    assert page._current["header"]["total_material_cost"] == Decimal("60.00")
    # Update must not create a second header.
    assert len(page.service.repository.inserted_headers) == 1


# --- Remove component recalculates ------------------------------------------

def test_remove_component_recalculates(qt_app):
    page = _make_page(qt_app)
    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "منتج تام"}
    _add(page, 1, "2", "10.00")  # 20
    _add(page, 2, "5", "4.00")   # 20
    assert page.total_value.text() == "40.00"
    page.lines_table.setCurrentCell(0, 0)
    page._on_remove_component()
    assert page.lines_table.rowCount() == 1
    assert page.total_value.text() == "20.00"


# --- Add component: dedup + self-reference are skipped -----------------------

class _FakePicker:
    """Stand-in for EntityPickerDialog: returns preset rows without a UI."""

    rows: list = []

    def __init__(self, *a, **k):
        self.selected_rows = list(_FakePicker.rows)
        self.selected = self.selected_rows[0] if self.selected_rows else None

    def exec(self):  # noqa: A003 - mirror the Qt API
        return True


def test_add_components_skips_duplicate_and_self_reference(qt_app, monkeypatch):
    import app.ui.screens.bom_page as mod

    page = _make_page(qt_app)
    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "منتج تام"}
    monkeypatch.setattr(mod, "EntityPickerDialog", _FakePicker)

    _FakePicker.rows = [
        {"id": 1, "item_code": 1001, "item_name": "خشب", "unit": "متر", "price": Decimal("10"), "item_type": "مادة خام"},
        {"id": 1, "item_code": 1001, "item_name": "خشب", "unit": "متر", "price": Decimal("10"), "item_type": "مادة خام"},  # dup
        {"id": FINISHED_ID, "item_code": 2001, "item_name": "منتج تام", "unit": "قطعة", "price": Decimal("0"), "item_type": "منتج تام"},  # self
        {"id": 2, "item_code": 1002, "item_name": "مسامير", "unit": "كيس", "price": Decimal("4"), "item_type": "مادة خام"},
    ]
    page._add_components()
    # Only the two distinct non-finished components are added.
    assert page.lines_table.rowCount() == 2
    codes = {page.lines_table.item(r, 0).text() for r in range(2)}
    assert codes == {"1001", "1002"}


# --- Permission gating -------------------------------------------------------

def test_permission_denied_disables_actions(qt_app, monkeypatch):
    import app.ui.screens.bom_page as mod

    monkeypatch.setattr(mod.SESSION, "can", lambda code: code == "manufacturing.boms.view")
    page, bom_id = _page_with_saved(qt_app)
    # New/Save need save; Edit needs edit; Delete needs delete — all denied here.
    page.load_bom(bom_id)
    assert not page.new_button.isEnabled()
    assert not page.edit_button.isEnabled()
    assert not page.delete_button.isEnabled()


# --- Delete resets to a clean state -----------------------------------------

def test_delete_removes_bom_and_resets(qt_app):
    page, bom_id = _page_with_saved(qt_app)
    page.load_bom(bom_id)
    page.on_delete()  # question() is monkeypatched to Yes by the autouse fixture
    assert page._current is None
    assert page.lines_table.rowCount() == 0
    assert page.service.repository.load_bom(bom_id) is None


# --- Re-saving does not create a duplicate document -------------------------

def test_second_save_updates_not_duplicates(qt_app):
    page = _make_page(qt_app)
    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "منتج تام"}
    _add(page, 1, "2", "10.00")
    page.on_save()               # creates BOM #1, screen -> view
    page.on_save()               # _current is set -> update path, no new header
    assert len(page.service.repository.inserted_headers) == 1
