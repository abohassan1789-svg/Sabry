from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.services.review_data_service import TABLE_SPECS
from app.ui.screens.suppliers_screen import SuppliersScreen


class _FakeSupplierService:
    def list_records(self, spec, keyword="", limit=500):
        return [
            {"supplier_id": 1001, "supplier_name": "شركة النور", "mobile": "0100", "opening_balance": 3900},
            {"supplier_id": 1002, "supplier_name": "مؤسسة الأمل", "mobile": "0122", "opening_balance": 0},
        ]

    def next_id(self, spec):
        return 1001


@pytest.fixture
def suppliers_screen():
    app = QApplication.instance() or QApplication([])
    _ = app
    return SuppliersScreen(_FakeSupplierService())


def test_suppliers_spec_has_five_fields_and_two_grid_columns():
    spec = TABLE_SPECS["suppliers"]
    assert spec.primary_key == "supplier_id"
    assert [f.name for f in spec.fields] == [
        "supplier_id",
        "supplier_name",
        "mobile",
        "account_type",
        "opening_balance",
    ]
    # نوع الحساب is retained in the spec (a fixed dropdown: عدد أو وزن) but hidden
    # from the form (user 2026-08-21), so stored values survive and it can be
    # un-hidden later without a schema change.
    account_type = next(f for f in spec.fields if f.name == "account_type")
    assert account_type.choices == ("عدد", "وزن")
    assert account_type.hidden_on_form is True
    # The list under the form shows only name + mobile.
    assert spec.list_columns == ("supplier_name", "mobile")


def test_suppliers_screen_builds_the_visible_inputs(suppliers_screen):
    # account_type is hidden_on_form (user 2026-08-21), so the screen builds no
    # input for it — only the four visible fields.
    assert set(suppliers_screen.inputs.keys()) == {
        "supplier_id",
        "supplier_name",
        "mobile",
        "opening_balance",
    }


def test_suppliers_grid_shows_only_name_and_mobile(suppliers_screen):
    table = suppliers_screen.table
    assert table.columnCount() == 2
    headers = [table.horizontalHeaderItem(i).text() for i in range(2)]
    assert headers == ["اسم المورد", "الموبايل"]
    # The supplier_id still rides along in UserRole for row selection/loading.
    assert table.item(0, 0).data(256) == 1001


def test_suppliers_new_record_previews_code_1001_and_zero_balance(suppliers_screen):
    suppliers_screen.new_record()
    assert suppliers_screen.inputs["supplier_id"].text() == "1001"
    assert suppliers_screen.inputs["opening_balance"].text() == "0.00"


def test_suppliers_toolbar_has_the_same_crud_buttons(suppliers_screen):
    labels = [
        b.text()
        for b in (
            suppliers_screen.new_button,
            suppliers_screen.edit_button,
            suppliers_screen.save_button,
            suppliers_screen.delete_button,
            suppliers_screen.cancel_button,
            suppliers_screen.refresh_button,
            suppliers_screen.exit_button,
        )
    ]
    assert labels == ["جديد", "تعديل", "حفظ", "حذف", "إلغاء", "تحديث", "خروج"]
