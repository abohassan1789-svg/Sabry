from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from app.services.review_data_service import TABLE_SPECS
from app.ui.screens.supplier_payment_vouchers_screen import SupplierPaymentVouchersScreen


class _FakeVoucherService:
    def list_records(self, spec, keyword="", limit=500):
        return [
            {"id": 1, "voucher_number": "Paid - Sub-01", "voucher_date": "2026-08-13",
             "supplier_name": "مورد السماد", "amount": 1500},
        ]

    def list_suppliers_for_selection(self):
        return [
            {"supplier_id": 1001, "supplier_name": "مورد السماد"},
            {"supplier_id": 1002, "supplier_name": "مورد البذور"},
            {"supplier_id": 1003, "supplier_name": "مورد الأعلاف"},
        ]

    def supplier_vouchers_total(self):
        return Decimal("84200.00")

    def supplier_vouchers_by_supplier(self):
        return [
            {"supplier_name": "مورد السماد", "total": Decimal("21000")},
            {"supplier_name": "مورد البذور", "total": Decimal("18000")},
            {"supplier_name": "مورد الأعلاف", "total": Decimal("6200")},
        ]

    def top_supplier_voucher(self):
        return self.supplier_vouchers_by_supplier()[0]

    def peek_next_supplier_voucher_number(self):
        return "Paid - Sub-02"


@pytest.fixture
def voucher_screen():
    app = QApplication.instance() or QApplication([])
    _ = app
    return SupplierPaymentVouchersScreen(_FakeVoucherService())


def test_spec_fields_and_grid_columns():
    spec = TABLE_SPECS["supplier_payment_vouchers"]
    assert spec.primary_key == "id"
    assert spec.table_name == "supplier_payment_vouchers"
    assert [f.name for f in spec.fields] == [
        "id",
        "voucher_number",
        "voucher_date",
        "supplier_id",
        "amount",
        "description",
        "supplier_name",
    ]
    # id is kept off the form (hidden) but present for selection.
    assert next(f for f in spec.fields if f.name == "id").hidden_on_form is True
    # voucher_number is shown but read-only (fully automatic).
    vnum = next(f for f in spec.fields if f.name == "voucher_number")
    assert vnum.readonly is True and vnum.hidden_on_form is False
    assert spec.list_columns == ("voucher_number", "voucher_date", "supplier_name", "amount")


def test_form_shows_the_entry_fields(voucher_screen):
    assert set(voucher_screen.inputs.keys()) == {
        "voucher_number",
        "voucher_date",
        "supplier_id",
        "amount",
        "description",
    }


def test_supplier_is_a_dropdown_of_registered_suppliers(voucher_screen):
    combo = voucher_screen.inputs["supplier_id"]
    assert isinstance(combo, QComboBox)
    items = [combo.itemText(i) for i in range(combo.count())]
    assert "مورد السماد" in items and "مورد البذور" in items


def test_supplier_combo_stores_the_supplier_id(voucher_screen):
    combo = voucher_screen.inputs["supplier_id"]
    combo.setCurrentText("مورد البذور")
    assert voucher_screen._editor_value(combo) == 1002
    combo.setCurrentText("   ")
    assert voucher_screen._editor_value(combo) is None
    # An unknown supplier name resolves to None (trips the required check).
    combo.setCurrentText("مورد غير موجود")
    assert voucher_screen._editor_value(combo) is None


def test_dashboard_cards_show_total_and_top_supplier(voucher_screen):
    assert voucher_screen.kpi_total_value.text() == "84,200.00"
    assert voucher_screen.kpi_top_value.text() == "مورد السماد"
    assert voucher_screen.kpi_top_sub.text() == "21,000.00"


def test_charts_show_top_five_suppliers_plus_an_other_bucket():
    app = QApplication.instance() or QApplication([])
    _ = app

    class _ManyService(_FakeVoucherService):
        def supplier_vouchers_by_supplier(self):
            vals = [
                ("سماد", 12100), ("بذور", 9500), ("أعلاف", 7500), ("مبيدات", 1000),
                ("ري", 800), ("وقود", 600), ("عبوات", 300),
            ]
            return [{"supplier_name": n, "total": Decimal(v)} for n, v in vals]

    screen = SupplierPaymentVouchersScreen(_ManyService())
    bar_rows = {r["label"]: int(r["count"]) for r in screen.bar_chart._rows}
    bar_labels = [r["label"] for r in screen.bar_chart._rows]

    # Five biggest shown individually, everything else rolled into "أخرى".
    assert bar_labels == ["سماد", "بذور", "أعلاف", "مبيدات", "ري", "أخرى"]
    assert bar_rows["أخرى"] == 600 + 300
    assert [r["label"] for r in screen.donut_chart._rows][-1] == "أخرى"


def test_new_record_defaults_date_today_and_previews_number(voucher_screen):
    voucher_screen.new_record()
    today = datetime.date.today().strftime("%Y-%m-%d")
    assert voucher_screen.inputs["voucher_date"].text() == today
    # رقم السند shows the next automatic number as a read-only preview.
    assert voucher_screen.inputs["voucher_number"].text() == "Paid - Sub-02"
    assert voucher_screen.inputs["voucher_number"].isReadOnly()


def test_search_button_present_and_bottom_list_is_hidden(voucher_screen):
    assert voucher_screen.search_button.text() == "بحث"
    assert voucher_screen._hidden_list.isHidden()


def test_search_dialog_defaults_to_latest_500():
    app = QApplication.instance() or QApplication([])
    _ = app
    from app.ui.dialogs.supplier_voucher_search_dialog import SupplierVoucherSearchDialog

    class _Svc(_FakeVoucherService):
        last = None

        def search_supplier_vouchers(self, date_from=None, date_to=None, supplier_id=None, limit=500):
            self.last = (date_from, date_to, supplier_id, limit)
            return [{"id": 7, "voucher_number": "Paid - Sub-07", "voucher_date": "2026-08-13",
                     "supplier_name": "مورد السماد", "amount": Decimal("8500"), "description": "دفعة"}]

    svc = _Svc()
    dialog = SupplierVoucherSearchDialog(svc)
    # No date filter on open → latest 500, no supplier filter.
    assert svc.last == (None, None, None, 500)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).data(256) == 7  # id in UserRole

    # Enabling the date filter drops the 500 cap and passes the range.
    dialog.enable_dates.setChecked(True)
    dialog.refresh_table()
    assert svc.last[0] is not None and svc.last[1] is not None
    assert svc.last[3] is None  # limit removed


def test_toolbar_has_the_same_crud_buttons(voucher_screen):
    labels = [
        b.text()
        for b in (
            voucher_screen.new_button,
            voucher_screen.edit_button,
            voucher_screen.save_button,
            voucher_screen.delete_button,
            voucher_screen.cancel_button,
            voucher_screen.refresh_button,
            voucher_screen.exit_button,
        )
    ]
    assert labels == ["جديد", "تعديل", "حفظ", "حذف", "إلغاء", "تحديث", "خروج"]
