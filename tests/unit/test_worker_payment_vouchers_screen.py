from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from app.services.review_data_service import TABLE_SPECS
from app.ui.screens.worker_payment_vouchers_screen import WorkerPaymentVouchersScreen


class _FakeVoucherService:
    def list_records(self, spec, keyword="", limit=500):
        return [
            {"id": 1, "voucher_number": "Paid - Wrk-01", "voucher_date": "2026-08-13",
             "worker_name": "عامل الحقل", "amount": 1500},
        ]

    def list_workers_for_selection(self):
        return [
            {"worker_id": 1, "worker_name": "عامل الحقل"},
            {"worker_id": 2, "worker_name": "عامل الحصاد"},
            {"worker_id": 3, "worker_name": "عامل الري"},
        ]

    def worker_vouchers_total(self):
        return Decimal("84200.00")

    def worker_vouchers_by_worker(self):
        return [
            {"worker_name": "عامل الحقل", "total": Decimal("21000")},
            {"worker_name": "عامل الحصاد", "total": Decimal("18000")},
            {"worker_name": "عامل الري", "total": Decimal("6200")},
        ]

    def top_worker_voucher(self):
        return self.worker_vouchers_by_worker()[0]

    def peek_next_worker_voucher_number(self):
        return "Paid - Wrk-02"


@pytest.fixture
def voucher_screen():
    app = QApplication.instance() or QApplication([])
    _ = app
    return WorkerPaymentVouchersScreen(_FakeVoucherService())


def test_spec_fields_and_grid_columns():
    spec = TABLE_SPECS["worker_payment_vouchers"]
    assert spec.primary_key == "id"
    assert spec.table_name == "worker_payment_vouchers"
    assert [f.name for f in spec.fields] == [
        "id",
        "voucher_number",
        "voucher_date",
        "worker_id",
        "amount",
        "description",
        "worker_name",
    ]
    # id is kept off the form (hidden) but present for selection.
    assert next(f for f in spec.fields if f.name == "id").hidden_on_form is True
    # voucher_number is shown but read-only (fully automatic).
    vnum = next(f for f in spec.fields if f.name == "voucher_number")
    assert vnum.readonly is True and vnum.hidden_on_form is False
    assert spec.list_columns == ("voucher_number", "voucher_date", "worker_name", "amount")


def test_form_shows_the_entry_fields(voucher_screen):
    assert set(voucher_screen.inputs.keys()) == {
        "voucher_number",
        "voucher_date",
        "worker_id",
        "amount",
        "description",
    }


def test_worker_is_a_dropdown_of_registered_workers(voucher_screen):
    combo = voucher_screen.inputs["worker_id"]
    assert isinstance(combo, QComboBox)
    items = [combo.itemText(i) for i in range(combo.count())]
    assert "عامل الحقل" in items and "عامل الحصاد" in items


def test_worker_combo_stores_the_worker_id(voucher_screen):
    combo = voucher_screen.inputs["worker_id"]
    combo.setCurrentText("عامل الحصاد")
    assert voucher_screen._editor_value(combo) == 2
    combo.setCurrentText("   ")
    assert voucher_screen._editor_value(combo) is None
    # An unknown worker name resolves to None (trips the required check).
    combo.setCurrentText("عامل غير موجود")
    assert voucher_screen._editor_value(combo) is None


def test_dashboard_cards_show_total_and_top_worker(voucher_screen):
    assert voucher_screen.kpi_total_value.text() == "84,200.00"
    assert voucher_screen.kpi_top_value.text() == "عامل الحقل"
    assert voucher_screen.kpi_top_sub.text() == "21,000.00"


def test_charts_show_top_five_workers_plus_an_other_bucket():
    app = QApplication.instance() or QApplication([])
    _ = app

    class _ManyService(_FakeVoucherService):
        def worker_vouchers_by_worker(self):
            vals = [
                ("حقل", 12100), ("حصاد", 9500), ("ري", 7500), ("رش", 1000),
                ("تعبئة", 800), ("نقل", 600), ("صيانة", 300),
            ]
            return [{"worker_name": n, "total": Decimal(v)} for n, v in vals]

    screen = WorkerPaymentVouchersScreen(_ManyService())
    bar_rows = {r["label"]: int(r["count"]) for r in screen.bar_chart._rows}
    bar_labels = [r["label"] for r in screen.bar_chart._rows]

    # Five biggest shown individually, everything else rolled into "أخرى".
    assert bar_labels == ["حقل", "حصاد", "ري", "رش", "تعبئة", "أخرى"]
    assert bar_rows["أخرى"] == 600 + 300
    assert [r["label"] for r in screen.donut_chart._rows][-1] == "أخرى"


def test_new_record_defaults_date_today_and_previews_number(voucher_screen):
    voucher_screen.new_record()
    today = datetime.date.today().strftime("%Y-%m-%d")
    assert voucher_screen.inputs["voucher_date"].text() == today
    # رقم السند shows the next automatic number as a read-only preview.
    assert voucher_screen.inputs["voucher_number"].text() == "Paid - Wrk-02"
    assert voucher_screen.inputs["voucher_number"].isReadOnly()


def test_search_button_present_and_bottom_list_is_hidden(voucher_screen):
    assert voucher_screen.search_button.text() == "بحث"
    assert voucher_screen._hidden_list.isHidden()


def test_search_dialog_defaults_to_latest_500():
    app = QApplication.instance() or QApplication([])
    _ = app
    from app.ui.dialogs.worker_voucher_search_dialog import WorkerVoucherSearchDialog

    class _Svc(_FakeVoucherService):
        last = None

        def search_worker_vouchers(self, date_from=None, date_to=None, worker_id=None, limit=500):
            self.last = (date_from, date_to, worker_id, limit)
            return [{"id": 7, "voucher_number": "Paid - Wrk-07", "voucher_date": "2026-08-13",
                     "worker_name": "عامل الحقل", "amount": Decimal("8500"), "description": "دفعة"}]

    svc = _Svc()
    dialog = WorkerVoucherSearchDialog(svc)
    # No date filter on open → latest 500, no worker filter.
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
