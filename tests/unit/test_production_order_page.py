"""Headless UI tests for the Production Order screen (Model 1 — classic ERP).

Qt runs offscreen. The screen is driven by a real
:class:`ProductionOrderService` wired to the in-memory fake repository from the
service tests, so the widget wiring (build, صرف المواد الخام load, quantity
recalculation, actual-edit deviation, collect-form, save round-trip, permissions)
is exercised without a database or a visible window.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.production_order_service import ProductionOrderService  # noqa: E402
from tests.services.test_production_order_service import (  # noqa: E402
    FakeProductionOrderRepo,
    FINISHED_ID,
    OTHER_FINISHED_ID,
    _bom_line,
    _default_boms,
)

# Column indices (mirror the screen).
COL_CODE, COL_NAME, COL_UNIT, COL_EXPECTED, COL_ACTUAL, COL_DEV = range(6)


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _silence_dialogs(monkeypatch):
    """Stop modal QMessageBox calls from blocking the offscreen run."""
    import app.ui.screens.production_order_page as mod

    monkeypatch.setattr(mod.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mod.QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mod.QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        mod.QMessageBox, "question", staticmethod(lambda *a, **k: mod.QMessageBox.Yes)
    )


def _make_page(qt_app, repo=None):
    from app.ui.screens.production_order_page import ProductionOrderPage

    return ProductionOrderPage(
        service=ProductionOrderService(repository=repo or FakeProductionOrderRepo())
    )


def _issue(page, product_id=FINISHED_ID, qty="10"):
    """Enter new mode, pick a product, set quantity, and صرف المواد الخام."""
    page.enter_new_mode()
    page._product = {"id": product_id, "name": "خرسانة"}
    page.product_input.setText("خرسانة")
    page.qty_input.setText(qty)
    page.on_issue_materials()


# --- build ------------------------------------------------------------------

def test_screen_builds_with_six_columns(qt_app):
    page = _make_page(qt_app)
    assert page.lines_table.columnCount() == 6
    headers = [page.lines_table.horizontalHeaderItem(c).text() for c in range(6)]
    assert headers == ["كود الصنف", "اسم الصنف", "الوحدة",
                       "الكمية المفروض صرفها", "الكمية الفعلية", "الانحراف"]
    assert page.order_number_value.isReadOnly()


def test_new_reserves_readonly_order_number(qt_app):
    page = _make_page(qt_app)
    page.enter_new_mode()
    assert page.order_number_value.text() == "PRO-001"
    assert page.order_number_value.isReadOnly()


# --- صرف المواد الخام: load materials ---------------------------------------

def test_issue_materials_loads_bom_lines(qt_app):
    page = _make_page(qt_app)
    _issue(page, qty="10")
    assert page.lines_table.rowCount() == 2
    # أسمنت 5×10 = 50 expected, actual defaults to 50, deviation 0.
    assert page.lines_table.item(0, COL_CODE).text() == "1001"
    assert page.lines_table.item(0, COL_NAME).text() == "أسمنت"
    assert page.lines_table.item(0, COL_UNIT).text() == "شيكارة"
    assert page.lines_table.item(0, COL_EXPECTED).text() == "50"
    assert page.lines_table.item(0, COL_ACTUAL).text() == "50"
    assert page.lines_table.item(0, COL_DEV).text() == "0"
    # رمل 2×10 = 20
    assert page.lines_table.item(1, COL_EXPECTED).text() == "20"


def test_issue_requires_product(qt_app):
    page = _make_page(qt_app)
    page.enter_new_mode()
    page.qty_input.setText("10")
    page.on_issue_materials()  # no product chosen
    assert page.lines_table.rowCount() == 0


def test_issue_product_without_bom_loads_nothing(qt_app):
    page = _make_page(qt_app)
    _issue(page, product_id=OTHER_FINISHED_ID, qty="10")  # no BOM in the fake
    assert page.lines_table.rowCount() == 0


def test_issue_with_invalid_quantity_is_handled(qt_app):
    page = _make_page(qt_app)
    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "خرسانة"}
    page.qty_input.setText("abc")
    page.on_issue_materials()          # invalid -> warning, no crash
    assert page.lines_table.rowCount() == 0
    page.qty_input.setText("-5")
    page.on_issue_materials()          # negative -> warning, no crash
    assert page.lines_table.rowCount() == 0


def test_issue_only_in_new_or_edit_mode(qt_app):
    page = _make_page(qt_app)  # starts in view mode
    page._product = {"id": FINISHED_ID, "name": "خرسانة"}
    page.qty_input.setText("10")
    page.on_issue_materials()          # view mode -> no-op
    assert page.lines_table.rowCount() == 0


def test_only_actual_column_is_editable(qt_app):
    from PySide6.QtCore import Qt

    page = _make_page(qt_app)
    _issue(page, qty="10")
    for col in (COL_CODE, COL_NAME, COL_UNIT, COL_EXPECTED, COL_DEV):
        assert not (page.lines_table.item(0, col).flags() & Qt.ItemIsEditable)
    assert page.lines_table.item(0, COL_ACTUAL).flags() & Qt.ItemIsEditable


# --- actual edit → deviation -------------------------------------------------

def test_editing_actual_updates_deviation_positive(qt_app):
    page = _make_page(qt_app)
    _issue(page, qty="10")
    page.lines_table.item(0, COL_ACTUAL).setText("52")  # 52 - 50 = +2
    assert page.lines_table.item(0, COL_DEV).text() == "+2"


def test_editing_actual_updates_deviation_negative(qt_app):
    page = _make_page(qt_app)
    _issue(page, qty="10")
    page.lines_table.item(1, COL_ACTUAL).setText("18")  # 18 - 20 = -2
    assert page.lines_table.item(1, COL_DEV).text() == "-2"


def test_negative_actual_is_reverted(qt_app):
    page = _make_page(qt_app)
    _issue(page, qty="10")
    page.lines_table.item(0, COL_ACTUAL).setText("-5")  # rejected -> revert to 50
    assert page.lines_table.item(0, COL_ACTUAL).text() == "50"


# --- production-quantity change: expected recalculated, actual preserved -----

def test_quantity_change_recalculates_expected_preserves_actual(qt_app):
    page = _make_page(qt_app)
    _issue(page, qty="10")
    page.lines_table.item(0, COL_ACTUAL).setText("52")   # user override
    page.qty_input.setText("12")
    page._on_quantity_edited("12")
    # أسمنت: expected 5×12 = 60, actual preserved 52, deviation -8.
    assert page.lines_table.item(0, COL_EXPECTED).text() == "60"
    assert page.lines_table.item(0, COL_ACTUAL).text() == "52"
    assert page.lines_table.item(0, COL_DEV).text() == "-8"


# --- collect form + save round-trip -----------------------------------------

def test_save_creates_order_and_enters_view(qt_app):
    repo = FakeProductionOrderRepo()
    page = _make_page(qt_app, repo)
    _issue(page, qty="10")
    form = page._collect_form()
    assert form["product_id"] == FINISHED_ID
    assert form["bom_id"] == 10
    assert form["order_number"] == "PRO-001"
    assert [ln["component_product_id"] for ln in form["lines"]] == [1, 2]

    page.on_save()
    assert page._current is not None
    assert page.order_number_value.text() == "PRO-001"
    assert len(repo.orders) == 1
    # Re-saving must update, not create a second order.
    page.on_edit()
    page.on_save()
    assert len(repo.orders) == 1


def test_save_blocked_when_no_materials_loaded(qt_app):
    """The grid is the source of truth: an empty grid must never save a full BOM."""
    repo = FakeProductionOrderRepo()
    page = _make_page(qt_app, repo)
    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "خرسانة"}
    page.qty_input.setText("10")           # deliberately NOT pressing صرف
    page.on_save()
    assert len(repo.orders) == 0            # nothing persisted
    assert page._current is None            # stays in the new/unsaved state


def test_reload_in_edit_mode_resets_actual_to_expected(qt_app):
    """Explicit صرف المواد الخام on an existing order resets actual = expected."""
    repo = FakeProductionOrderRepo()
    page = _make_page(qt_app, repo)
    _issue(page, qty="10")
    page.lines_table.item(0, COL_ACTUAL).setText("52")
    page.on_save()                          # saved with actual 52 (deviation +2)
    page.on_edit()
    assert page.lines_table.item(0, COL_ACTUAL).text() == "52"
    page.on_issue_materials()               # explicit reload
    assert page.lines_table.item(0, COL_ACTUAL).text() == "50"   # reset to expected
    assert page.lines_table.item(0, COL_DEV).text() == "0"


# --- open existing shows stored snapshots -----------------------------------

def test_open_existing_loads_snapshots(qt_app):
    repo = FakeProductionOrderRepo()
    svc = ProductionOrderService(repository=repo)
    created = svc.create_order({
        "order_number": "", "order_date": __import__("datetime").date(2026, 8, 17),
        "product_id": FINISHED_ID, "bom_id": None, "production_quantity": "10",
        "lines": [{"component_product_id": 1, "actual_quantity": "52"}],
    })
    from app.ui.screens.production_order_page import ProductionOrderPage
    page = ProductionOrderPage(service=svc)
    page.load_order(created["header"]["id"])

    assert page.order_number_value.text() == "PRO-001"
    assert page.qty_input.text() == "10"
    assert page._product["id"] == FINISHED_ID
    assert page.lines_table.rowCount() == 2
    assert page.lines_table.item(0, COL_ACTUAL).text() == "52"
    assert page.lines_table.item(0, COL_DEV).text() == "+2"
    # Opened document sits in a safe view state: Save disabled, Edit enabled.
    assert not page.save_button.isEnabled()
    assert page.edit_button.isEnabled()


# --- multiple BOMs trigger the picker ---------------------------------------

class _FakePicker:
    """Stand-in for EntityPickerDialog: returns a preset selection without a UI."""

    selected_row: dict | None = None

    def __init__(self, *a, **k):
        self.selected = _FakePicker.selected_row
        self.selected_rows = [self.selected] if self.selected else []

    def exec(self):  # noqa: A003 - mirror the Qt API
        return True


def test_multiple_boms_open_picker(qt_app, monkeypatch):
    import app.ui.screens.production_order_page as mod

    boms = _default_boms()
    boms[11] = {"header": {"id": 11, "bom_number": "BOM-0002",
                           "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
                "lines": [_bom_line(1, "6", "10.00")]}
    page = _make_page(qt_app, FakeProductionOrderRepo(boms=boms))
    _FakePicker.selected_row = {"id": 11}
    monkeypatch.setattr(mod, "EntityPickerDialog", _FakePicker)

    page.enter_new_mode()
    page._product = {"id": FINISHED_ID, "name": "خرسانة"}
    page.qty_input.setText("10")
    page.on_issue_materials()
    assert page._bom_id == 11
    assert page.lines_table.rowCount() == 1
    assert page.lines_table.item(0, COL_EXPECTED).text() == "60"  # 6 × 10


# --- delete + permissions ----------------------------------------------------

def test_delete_removes_order_and_resets(qt_app):
    repo = FakeProductionOrderRepo()
    page = _make_page(qt_app, repo)
    _issue(page, qty="10")
    page.on_save()
    order_id = page._current["header"]["id"]
    page.on_delete()  # question() monkeypatched to Yes
    assert page._current is None
    assert page.lines_table.rowCount() == 0
    assert repo.load_order(order_id) is None


def test_permission_denied_disables_actions(qt_app, monkeypatch):
    import app.ui.screens.production_order_page as mod

    monkeypatch.setattr(
        mod.SESSION, "can",
        lambda code: code == "manufacturing.production_orders.view",
    )
    repo = FakeProductionOrderRepo()
    svc = ProductionOrderService(repository=repo)
    created = svc.create_order({
        "order_number": "", "order_date": __import__("datetime").date(2026, 8, 17),
        "product_id": FINISHED_ID, "bom_id": None, "production_quantity": "10", "lines": [],
    })
    page = mod.ProductionOrderPage(service=ProductionOrderService(
        repository=repo, permission_check=mod.SESSION.can))
    page.load_order(created["header"]["id"])
    assert not page.new_button.isEnabled()
    assert not page.edit_button.isEnabled()
    assert not page.delete_button.isEnabled()
