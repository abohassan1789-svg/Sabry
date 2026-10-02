from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication

from app.services.review_data_service import TABLE_SPECS
from app.ui.screens.treasury_deposits_screen import TreasuryDepositsScreen


class _FakeTreasuryService:
    def list_records(self, spec, keyword="", limit=500):
        return [
            {"id": 3001, "movement_date": "2026-08-13", "amount": 1500, "statement": "إيداع"},
        ]

    def next_id(self, spec):
        return 3002

    def treasury_total(self):
        return Decimal("84200.00")

    def treasury_top_date(self):
        return {"movement_date": "2026-08-13", "total": Decimal("21000")}

    def treasury_by_month(self):
        return [
            {"month": "2026-08", "total": Decimal("21000")},
            {"month": "2026-07", "total": Decimal("18000")},
            {"month": "2026-06", "total": Decimal("6200")},
        ]


@pytest.fixture
def treasury_screen():
    app = QApplication.instance() or QApplication([])
    _ = app
    return TreasuryDepositsScreen(_FakeTreasuryService())


def test_spec_fields_and_grid_columns():
    spec = TABLE_SPECS["treasury_deposits"]
    assert spec.primary_key == "id"
    assert spec.table_name == "treasury_deposits"
    assert [f.name for f in spec.fields] == [
        "id",
        "movement_date",
        "amount",
        "statement",
    ]
    # رقم الحركة is shown on the form but read-only (auto sequence).
    id_field = next(f for f in spec.fields if f.name == "id")
    assert id_field.readonly is True and id_field.hidden_on_form is False
    assert id_field.label == "رقم الحركة"
    assert spec.list_columns == ("id", "movement_date", "amount")


def test_form_shows_the_entry_fields(treasury_screen):
    assert set(treasury_screen.inputs.keys()) == {
        "id",
        "movement_date",
        "amount",
        "statement",
    }


def test_dashboard_cards_show_total_and_top_date(treasury_screen):
    assert treasury_screen.kpi_total_value.text() == "84,200.00"
    assert treasury_screen.kpi_top_value.text() == "2026-08-13"
    assert treasury_screen.kpi_top_sub.text() == "21,000.00"


def test_charts_show_top_five_months_plus_an_other_bucket():
    app = QApplication.instance() or QApplication([])
    _ = app

    class _ManyMonthsService(_FakeTreasuryService):
        def treasury_by_month(self):
            vals = [
                ("2026-08", 12100), ("2026-07", 9500), ("2026-06", 7500),
                ("2026-05", 1000), ("2026-04", 800), ("2026-03", 600), ("2026-02", 300),
            ]
            return [{"month": m, "total": Decimal(v)} for m, v in vals]

    screen = TreasuryDepositsScreen(_ManyMonthsService())
    bar_rows = {r["label"]: int(r["count"]) for r in screen.bar_chart._rows}
    bar_labels = [r["label"] for r in screen.bar_chart._rows]

    # Five biggest months shown individually, everything else rolled into "أخرى".
    assert bar_labels == ["2026-08", "2026-07", "2026-06", "2026-05", "2026-04", "أخرى"]
    assert bar_rows["أخرى"] == 600 + 300
    assert [r["label"] for r in screen.donut_chart._rows][-1] == "أخرى"


def test_new_record_defaults_date_today_and_previews_movement_number(treasury_screen):
    treasury_screen.new_record()
    today = datetime.date.today().strftime("%Y-%m-%d")
    assert treasury_screen.inputs["movement_date"].text() == today
    # رقم الحركة shows the next automatic number as a read-only preview.
    assert treasury_screen.inputs["id"].text() == "3002"
    assert treasury_screen.inputs["id"].isReadOnly()


def test_search_button_present_and_bottom_list_is_hidden(treasury_screen):
    assert treasury_screen.search_button.text() == "بحث"
    assert treasury_screen._hidden_list.isHidden()


def test_search_dialog_defaults_to_latest_500():
    app = QApplication.instance() or QApplication([])
    _ = app
    from app.ui.dialogs.treasury_search_dialog import TreasurySearchDialog

    class _Svc(_FakeTreasuryService):
        last = None

        def search_treasury(self, date_from=None, date_to=None, limit=500):
            self.last = (date_from, date_to, limit)
            return [{"id": 3007, "movement_date": "2026-08-13",
                     "amount": Decimal("8500"), "statement": "إيداع"}]

    svc = _Svc()
    dialog = TreasurySearchDialog(svc)
    # No date filter on open → latest 500.
    assert svc.last == (None, None, 500)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).data(256) == 3007  # id in UserRole

    # Enabling the date filter drops the 500 cap and passes the range.
    dialog.enable_dates.setChecked(True)
    dialog.refresh_table()
    assert svc.last[0] is not None and svc.last[1] is not None
    assert svc.last[2] is None  # limit removed


def test_toolbar_has_the_same_crud_buttons(treasury_screen):
    labels = [
        b.text()
        for b in (
            treasury_screen.new_button,
            treasury_screen.edit_button,
            treasury_screen.save_button,
            treasury_screen.delete_button,
            treasury_screen.cancel_button,
            treasury_screen.refresh_button,
            treasury_screen.exit_button,
        )
    ]
    assert labels == ["جديد", "تعديل", "حفظ", "حذف", "إلغاء", "تحديث", "خروج"]
