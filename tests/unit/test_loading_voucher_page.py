"""Headless UI tests for the Loading Voucher screen (Model 3 — cards).

Qt runs offscreen. The screen is driven by a real
:class:`LoadingVoucherService` wired to the in-memory fake repository from the
service tests, so the widget wiring (build, pick customer/item, collect-form,
save round-trip, open existing snapshots, delete, permissions) is exercised
without a database or a visible window.
"""

from __future__ import annotations

import os
from datetime import date, time
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.loading_voucher_service import LoadingVoucherService  # noqa: E402
from tests.services.test_loading_voucher_service import (  # noqa: E402
    CUSTOMER_ID,
    PRODUCT_ID,
    FakeLoadingVoucherRepo,
)


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _silence_dialogs(monkeypatch):
    """Stop modal QMessageBox calls from blocking the offscreen run."""
    import app.ui.screens.loading_voucher_page as mod

    monkeypatch.setattr(mod.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mod.QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mod.QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        mod.QMessageBox, "question", staticmethod(lambda *a, **k: mod.QMessageBox.Yes)
    )


def _make_page(qt_app, repo=None):
    from app.ui.screens.loading_voucher_page import LoadingVoucherPage

    return LoadingVoucherPage(
        service=LoadingVoucherService(repository=repo or FakeLoadingVoucherRepo())
    )


def _fill_new(page, *, customer=True, item=True, qty="25.000",
              driver="محمد عبد الله", vehicle="أ ب ج 4213"):
    """Enter new mode and fill the form fields (customer/item via internal state)."""
    page.enter_new_mode()
    if customer:
        page._customer = {"id": CUSTOMER_ID, "name": "شركة النور للتجارة"}
        page.customer_input.setText("شركة النور للتجارة")
    if item:
        page._product = {"id": PRODUCT_ID, "name": "أسمنت مقاوم"}
        page.item_input.setText("أسمنت مقاوم")
    page.driver_input.setText(driver)
    page.vehicle_input.setText(vehicle)
    page.weight_before_input.setText("500k")
    page.weight_after_input.setText("750k")
    page.qty_input.setText(qty)


# --- build ------------------------------------------------------------------

def test_screen_builds(qt_app):
    page = _make_page(qt_app)
    assert page.title_label.text() == "سند تحميل"
    assert page.voucher_number_value.isReadOnly()
    # Customer / item fields are pick-only (read-only text, filled via the picker).
    assert page.customer_input.isReadOnly()
    assert page.item_input.isReadOnly()


def test_new_reserves_readonly_number(qt_app):
    page = _make_page(qt_app)
    page.enter_new_mode()
    assert page.voucher_number_value.text() == "LV-001"
    assert page.voucher_number_value.isReadOnly()


def test_view_mode_disables_editing(qt_app):
    page = _make_page(qt_app)  # starts in view/ready mode
    assert page.driver_input.isReadOnly()
    assert page.qty_input.isReadOnly()
    assert not page.save_button.isEnabled()


# --- collect form + save round-trip -----------------------------------------

def test_collect_form_maps_fields(qt_app):
    page = _make_page(qt_app)
    _fill_new(page, qty="12.750")
    form = page._collect_form()
    assert form["voucher_number"] == "LV-001"
    assert form["voucher_date"] == date.today()
    assert isinstance(form["voucher_time"], time)
    assert form["customer_id"] == CUSTOMER_ID
    assert form["product_id"] == PRODUCT_ID
    assert form["driver_name"] == "محمد عبد الله"
    assert form["vehicle_number"] == "أ ب ج 4213"
    assert form["weight_before_loading"] == "500k"
    assert form["weight_after_loading"] == "750k"
    assert form["quantity_tons"] == "12.750"


def test_save_creates_voucher_and_enters_view(qt_app):
    repo = FakeLoadingVoucherRepo()
    page = _make_page(qt_app, repo)
    _fill_new(page, qty="25.000")
    page.on_save()
    assert page._current is not None
    assert page.voucher_number_value.text() == "LV-001"
    assert len(repo.vouchers) == 1
    stored = repo.inserted[0]
    assert stored["customer_id"] == CUSTOMER_ID
    assert stored["quantity_tons"] == Decimal("25.000")
    # Re-saving must update, not create a second voucher.
    page.on_edit()
    page.on_save()
    assert len(repo.vouchers) == 1


def test_save_fully_blank_voucher_allowed(qt_app):
    """Everything optional: an empty voucher (only auto number + date/time) saves."""
    repo = FakeLoadingVoucherRepo()
    page = _make_page(qt_app, repo)
    page.enter_new_mode()  # no customer / item / driver / vehicle / qty
    page.on_save()
    assert len(repo.vouchers) == 1
    stored = repo.inserted[0]
    assert stored["voucher_number"] == "LV-001"
    assert stored["customer_id"] is None
    assert stored["product_id"] is None
    assert stored["quantity_tons"] is None


def test_invalid_quantity_blocks_save(qt_app):
    repo = FakeLoadingVoucherRepo()
    page = _make_page(qt_app, repo)
    _fill_new(page, qty="abc")   # present-but-non-numeric -> service rejects
    page.on_save()
    assert len(repo.vouchers) == 0
    assert page._current is None


# --- open existing shows stored snapshots -----------------------------------

def test_open_existing_loads_snapshots(qt_app):
    repo = FakeLoadingVoucherRepo()
    svc = LoadingVoucherService(repository=repo)
    created = svc.create_voucher({
        "voucher_number": "", "voucher_date": date(2026, 8, 18),
        "voucher_time": time(9, 30), "customer_id": CUSTOMER_ID,
        "driver_name": "خالد", "vehicle_number": "1234",
        "weight_before_loading": "500k", "weight_after_loading": "750 كجم",
        "product_id": PRODUCT_ID, "quantity_tons": "18.500", "notes": "ملاحظة",
    })
    from app.ui.screens.loading_voucher_page import LoadingVoucherPage
    page = LoadingVoucherPage(service=svc)
    page.load_voucher(created["id"])

    assert page.voucher_number_value.text() == "LV-001"
    assert page.customer_input.text() == "شركة النور للتجارة"
    assert page.item_input.text() == "أسمنت مقاوم"
    assert page.driver_input.text() == "خالد"
    assert page.vehicle_input.text() == "1234"
    assert page.weight_before_input.text() == "500k"
    assert page.weight_after_input.text() == "750 كجم"
    assert page.qty_input.text() == "18.5"
    assert page.notes_input.toPlainText() == "ملاحظة"
    # Opened document sits in a safe view state: Save disabled, Edit enabled.
    assert not page.save_button.isEnabled()
    assert page.edit_button.isEnabled()


# --- delete + permissions ----------------------------------------------------

def test_delete_removes_voucher_and_resets(qt_app):
    repo = FakeLoadingVoucherRepo()
    page = _make_page(qt_app, repo)
    _fill_new(page)
    page.on_save()
    voucher_id = page._current["id"]
    page.on_delete()  # question() monkeypatched to Yes
    assert page._current is None
    assert repo.load_voucher(voucher_id) is None


def test_permission_denied_disables_actions(qt_app, monkeypatch):
    import app.ui.screens.loading_voucher_page as mod

    monkeypatch.setattr(
        mod.SESSION, "can",
        lambda code: code == "logistics.loading_vouchers.view",
    )
    repo = FakeLoadingVoucherRepo()
    svc = LoadingVoucherService(repository=repo)
    created = svc.create_voucher({
        "voucher_number": "", "voucher_date": date(2026, 8, 18),
        "voucher_time": time(9, 30), "customer_id": CUSTOMER_ID,
        "product_id": PRODUCT_ID, "quantity_tons": "10",
    })
    page = mod.LoadingVoucherPage(service=LoadingVoucherService(
        repository=repo, permission_check=mod.SESSION.can))
    page.load_voucher(created["id"])
    assert not page.new_button.isEnabled()
    assert not page.edit_button.isEnabled()
    assert not page.delete_button.isEnabled()


__all__: list[str] = []
