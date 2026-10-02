"""Tests for the Receipt Vouchers screen stack (شاشة سندات قبض العملاء).

The screen was reworked to the same expenses-style dashboard as the supplier
payment vouchers: a five-field form (رقم السند / التاريخ / اسم العميل / المبلغ /
البيان) beside total + top-customer cards and by-customer charts, searching via a
popup, and رقم السند fully automatic (PA-<n>). الشركة / نوع الدفع were dropped from
the screen. The one extra kept over the supplier screen is the طباعة سند button.

These tests cover the receipt-voucher specifics:

* the ``receipt_vouchers`` TableSpec shape (grid columns, fields, no lookup layout),
* the service's joined list query + search + automatic-number save,
* the screen: customer dropdown, dashboard cards/charts, search + print buttons.

No real database is used — a fake connection/service records calls and returns
canned rows. Qt runs headless (offscreen).
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from app.services.review_data_service import ReviewDataService, TABLE_SPECS


# --------------------------------------------------------------------------- #
# TableSpec
# --------------------------------------------------------------------------- #
def test_receipt_vouchers_spec_basics():
    spec = TABLE_SPECS["receipt_vouchers"]
    assert spec.table_name == "receipt_vouchers"
    assert spec.primary_key == "id"
    assert spec.search_columns == ("voucher_number", "customer_name", "voucher_date")
    assert [f.name for f in spec.fields] == [
        "id",
        "voucher_number",
        "voucher_date",
        "customer_id",
        "amount",
        "description",
        "customer_name",
    ]
    field_by_name = {f.name: f for f in spec.fields}
    # id hidden but present for selection; voucher_number shown read-only (auto).
    assert field_by_name["id"].hidden_on_form is True
    assert field_by_name["voucher_number"].readonly is True
    assert field_by_name["voucher_number"].hidden_on_form is False
    # Required business fields.
    assert field_by_name["voucher_date"].required is True
    assert field_by_name["customer_id"].required is True
    assert field_by_name["amount"].required is True
    # customer_name is grid-only: from the JOIN, never an editor, never written.
    assert field_by_name["customer_name"].virtual is True
    assert field_by_name["customer_name"].hidden_on_form is True
    # الشركة / نوع الدفع are no longer part of the spec.
    assert "company_id" not in field_by_name
    assert "payment_type" not in field_by_name


def test_receipt_vouchers_no_longer_use_the_lookup_layout():
    from app.ui.common.theme import LOOKUP_LAYOUT_KEYS

    assert "receipt_vouchers" not in LOOKUP_LAYOUT_KEYS


def test_search_grid_columns_match_the_supplier_voucher_order():
    spec = TABLE_SPECS["receipt_vouchers"]
    assert spec.list_columns == ("voucher_number", "voucher_date", "customer_name", "amount")


# --------------------------------------------------------------------------- #
# Service: joined list query + search + automatic-number save
# --------------------------------------------------------------------------- #
def _render(query) -> str:
    try:
        return query.as_string(None)
    except Exception:  # pragma: no cover - defensive
        return str(query)


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple] = []
        self.closed = False

    def execute(self, query, params=None):
        self.calls.append((_render(query), params))
        return _Cursor(self.rows)


def _service_with(conn) -> ReviewDataService:
    service = ReviewDataService()
    service._connection = conn
    return service


def test_list_joins_customers_for_the_name_column():
    conn = _FakeConn([])
    service = _service_with(conn)

    service.list_records(TABLE_SPECS["receipt_vouchers"], "")

    sql, params = conn.calls[0]
    assert "FROM receipt_vouchers rv" in sql
    assert "LEFT JOIN customers c ON c.customer_id = rv.customer_id" in sql
    for alias in ("id", "voucher_number", "customer_name", "voucher_date", "amount"):
        assert f'"{alias}"' in sql
    assert "WHERE" not in sql
    assert params == [500]


def test_search_matches_number_name_or_date():
    conn = _FakeConn([])
    service = _service_with(conn)

    service.list_records(TABLE_SPECS["receipt_vouchers"], "PA-00")

    sql, params = conn.calls[0]
    assert sql.count("ILIKE") == 3
    assert "rv.voucher_number" in sql
    assert "c.customer_name" in sql
    assert "rv.voucher_date" in sql
    assert params == ["%PA-00%", "%PA-00%", "%PA-00%", 500]


def _valid_payload(**overrides):
    payload = {
        "voucher_number": "PA-005",  # a display preview — must be dropped on save
        "voucher_date": "2026-07-13",
        "customer_id": 29582,
        "amount": "150.00",
        "description": "",
    }
    payload.update(overrides)
    return payload


def test_voucher_number_is_always_dropped_so_db_default_numbers():
    conn = _FakeConn([{"id": 1}])
    service = _service_with(conn)

    service.save_record(TABLE_SPECS["receipt_vouchers"], _valid_payload(), None)

    sql, params = conn.calls[0]
    # INSERT without voucher_number: the DB DEFAULT (PA- sequence) assigns it,
    # even though the readonly field carried a preview value.
    assert "INSERT INTO" in sql
    assert "voucher_number" not in sql
    assert "PA-" not in str(params)


def test_voucher_number_dropped_on_update_too():
    conn = _FakeConn([{"id": 9}])
    service = _service_with(conn)

    service.save_record(TABLE_SPECS["receipt_vouchers"], _valid_payload(), 9)

    sql, _params = conn.calls[0]
    assert "UPDATE" in sql
    assert "voucher_number" not in sql


def test_missing_required_customer_raises_arabic_message():
    conn = _FakeConn([{"id": 1}])
    service = _service_with(conn)

    with pytest.raises(ValueError) as excinfo:
        service.save_record(
            TABLE_SPECS["receipt_vouchers"], _valid_payload(customer_id=None), None
        )
    assert "اسم العميل" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# UI: dashboard, dropdown, search + print buttons
# --------------------------------------------------------------------------- #
class _FakeVoucherService:
    def list_records(self, spec, keyword="", limit=500):
        return [
            {"id": 1, "voucher_number": "PA-001", "voucher_date": "2026-08-13",
             "customer_name": "عميل الشمال", "amount": 1500},
        ]

    def list_customers_for_selection(self):
        return [
            {"customer_id": 1001, "customer_name": "عميل الشمال", "phone_number": "0500000000"},
            {"customer_id": 1002, "customer_name": "عميل الجنوب", "phone_number": "0500000001"},
        ]

    def receipt_vouchers_total(self):
        return Decimal("84200.00")

    def receipt_vouchers_by_customer(self):
        return [
            {"customer_name": "عميل الشمال", "total": Decimal("21000")},
            {"customer_name": "عميل الجنوب", "total": Decimal("18000")},
        ]

    def top_receipt_voucher_customer(self):
        return self.receipt_vouchers_by_customer()[0]

    def get_record(self, spec, record_id):
        return None


class _FakeNumbering:
    def peek_next_number(self):
        return "PA-001"


@pytest.fixture
def voucher_screen(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app
    import app.ui.screens.receipt_vouchers_screen as mod

    monkeypatch.setattr(mod, "ReceiptVoucherNumberingService", _FakeNumbering)
    return mod.ReceiptVouchersScreen(_FakeVoucherService())


def test_form_shows_the_five_entry_fields(voucher_screen):
    assert set(voucher_screen.inputs.keys()) == {
        "voucher_number",
        "voucher_date",
        "customer_id",
        "amount",
        "description",
    }


def test_customer_is_a_dropdown_that_stores_the_id(voucher_screen):
    combo = voucher_screen.inputs["customer_id"]
    assert isinstance(combo, QComboBox)
    combo.setCurrentText("عميل الجنوب")
    assert voucher_screen._editor_value(combo) == 1002
    combo.setCurrentText("   ")
    assert voucher_screen._editor_value(combo) is None
    combo.setCurrentText("عميل غير موجود")
    assert voucher_screen._editor_value(combo) is None


def test_dashboard_cards_show_total_and_top_customer(voucher_screen):
    assert voucher_screen.kpi_total_value.text() == "84,200.00"
    assert voucher_screen.kpi_top_value.text() == "عميل الشمال"
    assert voucher_screen.kpi_top_sub.text() == "21,000.00"


def test_charts_show_top_five_customers_plus_other_bucket(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app
    import app.ui.screens.receipt_vouchers_screen as mod

    monkeypatch.setattr(mod, "ReceiptVoucherNumberingService", _FakeNumbering)

    class _Many(_FakeVoucherService):
        def receipt_vouchers_by_customer(self):
            vals = [
                ("شمال", 12100), ("جنوب", 9500), ("شرق", 7500), ("غرب", 1000),
                ("وسط", 800), ("ريف", 600), ("مدينة", 300),
            ]
            return [{"customer_name": n, "total": Decimal(v)} for n, v in vals]

    screen = mod.ReceiptVouchersScreen(_Many())
    bar_rows = {r["label"]: int(r["count"]) for r in screen.bar_chart._rows}
    bar_labels = [r["label"] for r in screen.bar_chart._rows]
    assert bar_labels == ["شمال", "جنوب", "شرق", "غرب", "وسط", "أخرى"]
    assert bar_rows["أخرى"] == 600 + 300
    assert [r["label"] for r in screen.donut_chart._rows][-1] == "أخرى"


def test_new_record_defaults_date_and_previews_number(voucher_screen):
    voucher_screen.new_record()
    today = datetime.date.today().strftime("%Y-%m-%d")
    assert voucher_screen.inputs["voucher_date"].text() == today
    assert voucher_screen.inputs["voucher_number"].text() == "PA-001"
    assert voucher_screen.inputs["voucher_number"].isReadOnly()


def test_search_and_print_buttons_present_and_list_hidden(voucher_screen):
    assert voucher_screen.search_button.text() == "بحث"
    assert voucher_screen.print_voucher_button.text() == "طباعة سند"
    assert voucher_screen._hidden_list.isHidden()


def test_print_collects_data_from_the_form(voucher_screen):
    voucher_screen.mode = "new"
    voucher_screen.inputs["voucher_number"].setText("PA-009")
    # التاريخ is now a calendar-popup QDateEdit; set it through the shared helper.
    voucher_screen._set_editor_value(voucher_screen.inputs["voucher_date"], "2026-04-02")
    voucher_screen.inputs["description"].setText("قيمة بضاعة")
    voucher_screen.inputs["amount"].setText("150.00")
    voucher_screen.voucher_customer_combo.setCurrentText("عميل الشمال")

    data = voucher_screen._collect_voucher_print_data()
    assert data is not None
    assert data["number"] == "PA-009"
    assert data["received_from"] == "عميل الشمال"
    assert str(data["amount"]) == "150.00"
    assert data["purpose"] == "قيمة بضاعة"
    assert data["issue_date"] == datetime.date(2026, 4, 2)
    # No company/payment inputs anymore → empty seller header.
    assert data["seller"]["name"] == ""


def test_print_on_empty_screen_returns_none(voucher_screen):
    voucher_screen.current_id = None
    voucher_screen.inputs["amount"].setText("")
    voucher_screen.voucher_customer_combo.setCurrentIndex(0)
    assert voucher_screen._collect_voucher_print_data() is None


def test_search_dialog_defaults_to_latest_500():
    app = QApplication.instance() or QApplication([])
    _ = app
    from app.ui.dialogs.receipt_voucher_search_dialog import ReceiptVoucherSearchDialog

    class _Svc(_FakeVoucherService):
        last = None

        def search_receipt_vouchers(self, date_from=None, date_to=None, customer_id=None, limit=500):
            self.last = (date_from, date_to, customer_id, limit)
            return [{"id": 7, "voucher_number": "PA-007", "voucher_date": "2026-08-13",
                     "customer_name": "عميل الشمال", "amount": Decimal("8500"), "description": "دفعة"}]

    svc = _Svc()
    dialog = ReceiptVoucherSearchDialog(svc)
    assert svc.last == (None, None, None, 500)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).data(256) == 7  # id in UserRole

    dialog.enable_dates.setChecked(True)
    dialog.refresh_table()
    assert svc.last[0] is not None and svc.last[1] is not None
    assert svc.last[3] is None


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
