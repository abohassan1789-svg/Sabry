"""Widget tests for the purchase-invoice screen (headless / offscreen Qt).

The real :class:`PurchaseInvoiceService` is driven by an in-memory fake
repository, so no database is touched. These verify the UI contract: RTL, the
required controls, an automatic + editable "Pur-" number in New mode, the six
detail columns (كود الصنف، اسم الصنف، الوحدة، الكمية، السعر، الإجمالي), the
quantity × price line maths shown in the grid, the single invoice total
(إجمالي الفاتورة), view-mode locking, and that an approved invoice loads locked.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from app.services.purchase_invoice_service import PurchaseInvoiceService
from app.ui.screens.purchase_invoice_page import (
    COL_CODE,
    COL_NAME,
    COL_PRICE,
    COL_QTY,
    COL_TOTAL,
    COL_UNIT,
    PurchaseInvoicePage,
)


class FakeRepo:
    def __init__(self):
        self.suppliers = {
            1001: {"supplier_id": 1001, "supplier_name": "مورد أ", "mobile": "0500000001"},
            1002: {"supplier_id": 1002, "supplier_name": "مورد ب", "mobile": "0500000002"},
        }
        self.loaded = None
        self.next_reserved_seq = 1001

    def list_suppliers(self, limit=100):
        return list(self.suppliers.values())

    def search_suppliers(self, kw, limit=100):
        return self.list_suppliers()

    def search_products(self, kw, limit=100):
        return [
            {"id": 1, "item_code": 1001, "item_name": "صنف تجريبي", "unit": "قطعة", "price": Decimal("50")},
            {"id": 2, "item_code": 1002, "item_name": "صنف ثانٍ", "unit": "كرتون", "price": Decimal("30")},
        ]

    def get_supplier(self, i):
        return self.suppliers.get(int(i))

    def invoice_number_exists(self, *a, **k):
        return False

    def reserve_invoice_number(self):
        from app.models.purchase_invoice import format_invoice_number
        number = format_invoice_number(self.next_reserved_seq)
        self.next_reserved_seq += 1
        return number

    def load_invoice(self, i):
        return self.loaded

    def search_invoices(self, *a, **k):
        return []


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def page(qapp):
    service = PurchaseInvoiceService(repository=FakeRepo())
    return PurchaseInvoicePage(service=service)


REQUIRED_CONTROLS = [
    "search_button", "new_button", "duplicate_button", "save_button",
    "edit_button", "update_button", "approve_button",
    "delete_button", "delete_all_button", "cancel_button", "back_button",
    "invoice_number_input", "issue_datetime_input", "supplier_combo",
    "payment_combo",
    "lines_table", "invoice_total_value",
    "item_name_input", "unit_input", "count_input", "price_input",
    "add_line_button", "new_line_button", "remove_line_button", "notes_input",
]


def test_screen_is_rtl(page):
    from PySide6.QtCore import Qt
    assert page.layoutDirection() == Qt.RightToLeft


def test_required_controls_exist(page):
    for name in REQUIRED_CONTROLS:
        assert hasattr(page, name), f"missing control: {name}"


def test_account_type_field_is_hidden(page):
    # نوع الحساب is tracked internally but never shown on the screen.
    assert not page.supplier_account_type_display.isVisible()


def test_details_table_has_six_columns_with_expected_headers(page):
    table = page.lines_table
    assert table.columnCount() == 6
    headers = [table.horizontalHeaderItem(c).text() for c in range(6)]
    assert headers == [
        "كود الصنف", "اسم الصنف", "الوحدة", "الكمية", "السعر", "الإجمالي",
    ]


def test_new_mode_reserves_editable_pur_number(page):
    page.enter_new_mode()
    assert page.invoice_number_input.text() == "Pur-1001"
    assert not page.invoice_number_input.isReadOnly()


def test_view_mode_is_locked(page):
    # Fresh screen opens idle/locked.
    assert page.invoice_number_input.isReadOnly()
    assert not page.supplier_combo.isEnabled()
    assert not page.add_line_button.isEnabled()


def test_add_line_computes_total_and_invoice_total(page):
    page.enter_new_mode()
    page.item_name_input.setText("طماطم")
    page.unit_input.setText("كيلو")
    page.count_input.setText("10")
    page.price_input.setText("3")
    page._on_add_line()

    table = page.lines_table
    assert table.rowCount() == 1
    assert table.item(0, COL_NAME).text() == "طماطم"
    assert table.item(0, COL_UNIT).text() == "كيلو"
    assert table.item(0, COL_QTY).text() == "10"
    assert table.item(0, COL_PRICE).text() == "3"
    # الإجمالي = 10 × 3 = 30
    assert table.item(0, COL_TOTAL).text() == "30.00"

    # Single invoice total: إجمالي الفاتورة = Σ الإجمالي.
    assert page.invoice_total_value.text() == "30.00"


def test_second_line_accumulates_total(page):
    page.enter_new_mode()
    for name, c, p in [("طماطم", "10", "3"), ("خيار", "4", "7")]:
        page.item_name_input.setText(name)
        page.count_input.setText(c)
        page.price_input.setText(p)
        page._on_add_line()
    # invoice total: 30 + 28 = 58
    assert page.invoice_total_value.text() == "58.00"


def test_editing_quantity_cell_recomputes_row(page):
    page.enter_new_mode()
    page.item_name_input.setText("طماطم")
    page.count_input.setText("10")
    page.price_input.setText("3")
    page._on_add_line()
    # Change the quantity in-grid from 10 to 20.
    page.lines_table.item(0, COL_QTY).setText("20")
    assert page.lines_table.item(0, COL_TOTAL).text() == "60.00"
    assert page.invoice_total_value.text() == "60.00"


def test_add_line_requires_a_name(page, monkeypatch):
    page.enter_new_mode()
    warned = {"n": 0}
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.__setitem__("n", warned["n"] + 1))
    page.item_name_input.setText("   ")
    page._on_add_line()
    assert page.lines_table.rowCount() == 0
    assert warned["n"] == 1


def test_approved_invoice_loads_locked(page):
    repo = page.service.repository
    repo.loaded = {
        "header": {
            "id": 5, "invoice_number": "Pur-1005",
            "issue_datetime": datetime.datetime(2026, 8, 14, 9, 0),
            "supplier_id": 1001, "supplier_name_snapshot": "مورد أ",
            "payment_type": "cash", "notes": None,
            "total_count_price": Decimal("30.00"), "total_weight_price": Decimal("0.00"),
            "document_status": "approved", "row_version": 2,
        },
        "lines": [
            {"id": 1, "item_code_snapshot": 1001, "item_name_snapshot": "طماطم",
             "unit_snapshot": "كيلو", "item_count": Decimal("10"),
             "unit_weight": Decimal("0"), "unit_price": Decimal("3")},
        ],
    }
    page.load_invoice(5)
    assert page.invoice_number_input.text() == "Pur-1005"
    assert page.invoice_number_input.isReadOnly()
    assert not page.supplier_combo.isEnabled()
    # Approved => cannot edit or delete.
    assert not page.edit_button.isEnabled()
    assert not page.delete_button.isEnabled()
    # The line loaded and recomputed: code / unit / total shown.
    assert page.lines_table.item(0, COL_CODE).text() == "1001"
    assert page.lines_table.item(0, COL_UNIT).text() == "كيلو"
    assert page.lines_table.item(0, COL_TOTAL).text() == "30.00"


def test_item_lookup_adds_every_picked_product(page, monkeypatch):
    """The اسم الصنف magnifier adds every ticked product as a line (qty 1)."""
    from PySide6.QtCore import Qt
    picked = [
        {"id": 1, "item_code": 1001, "item_name": "صنف تجريبي", "unit": "قطعة", "price": Decimal("50")},
        {"id": 2, "item_code": 1002, "item_name": "صنف ثانٍ", "unit": "كرتون", "price": Decimal("30")},
    ]

    class FakeDialog:
        def __init__(self, *a, **k):
            self.kwargs = k
            self.selected_rows = picked
            self.selected = picked[0]
            FakeDialog.instance = self

        def exec(self):
            return 1

    monkeypatch.setattr(
        "app.ui.screens.purchase_invoice_page.EntityPickerDialog", FakeDialog
    )
    page.enter_new_mode()
    page._search_item()

    # The popup is opened in multi-select mode.
    assert FakeDialog.instance.kwargs["multi_select"] is True
    # Both products land on the invoice, in order, at count 1 with their code/unit/price.
    assert page.lines_table.rowCount() == 2
    assert page.lines_table.item(0, COL_NAME).text() == "صنف تجريبي"
    assert page.lines_table.item(1, COL_NAME).text() == "صنف ثانٍ"
    assert page.lines_table.item(0, COL_CODE).text() == "1001"
    assert page.lines_table.item(0, COL_UNIT).text() == "قطعة"
    metas = [page.lines_table.item(r, COL_NAME).data(Qt.UserRole) for r in range(2)]
    assert [m["item_name"] for m in metas] == ["صنف تجريبي", "صنف ثانٍ"]
    assert [m["count"] for m in metas] == [Decimal("1"), Decimal("1")]
    assert [m["price"] for m in metas] == [Decimal("50"), Decimal("30")]
    assert [m["unit"] for m in metas] == ["قطعة", "كرتون"]
