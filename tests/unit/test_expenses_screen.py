from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from app.services.review_data_service import TABLE_SPECS
from app.ui.screens.expenses_screen import ExpensesScreen


class _FakeExpenseService:
    def list_records(self, spec, keyword="", limit=500):
        return [
            {"id": 1, "expense_date": "2026-08-13", "expense_type": "الكهرباء", "amount": 1500, "statement": "فاتورة"},
        ]

    def list_expense_types(self):
        return ["الإيجار", "الكهرباء", "المياه"]

    def expenses_total(self):
        return Decimal("84200.00")

    def expenses_by_type(self):
        return [
            {"expense_type": "الكهرباء", "total": Decimal("21000")},
            {"expense_type": "الإيجار", "total": Decimal("18000")},
            {"expense_type": "المياه", "total": Decimal("6200")},
        ]

    def top_expense_type(self):
        return self.expenses_by_type()[0]


@pytest.fixture
def expenses_screen():
    app = QApplication.instance() or QApplication([])
    _ = app
    return ExpensesScreen(_FakeExpenseService())


def test_expenses_spec_fields_and_grid_columns():
    spec = TABLE_SPECS["expenses"]
    assert spec.primary_key == "id"
    assert [f.name for f in spec.fields] == [
        "id",
        "expense_date",
        "amount",
        "expense_type",
        "statement",
    ]
    # id is kept off the form (hidden) but present for selection.
    assert next(f for f in spec.fields if f.name == "id").hidden_on_form is True
    assert spec.list_columns == ("expense_date", "expense_type", "amount")


def test_form_shows_the_four_entry_fields(expenses_screen):
    assert set(expenses_screen.inputs.keys()) == {
        "expense_date",
        "amount",
        "expense_type",
        "statement",
    }


def test_expense_type_is_an_editable_learning_combo(expenses_screen):
    combo = expenses_screen.inputs["expense_type"]
    assert isinstance(combo, QComboBox)
    assert combo.isEditable()
    # Dropdown is seeded from the distinct stored types (plus a blank).
    items = [combo.itemText(i) for i in range(combo.count())]
    assert "الكهرباء" in items and "المياه" in items and "الإيجار" in items


def test_expense_type_accepts_free_text_as_its_value(expenses_screen):
    combo = expenses_screen.inputs["expense_type"]
    combo.setCurrentText("صيانة")
    # A newly typed type is saved as plain text (it will be learned next load).
    assert expenses_screen._editor_value(combo) == "صيانة"
    combo.setCurrentText("   ")
    assert expenses_screen._editor_value(combo) is None


def test_dashboard_cards_show_total_and_top_type(expenses_screen):
    assert expenses_screen.kpi_total_value.text() == "84,200.00"
    assert expenses_screen.kpi_top_value.text() == "الكهرباء"
    assert expenses_screen.kpi_top_sub.text() == "21,000.00"


def test_charts_show_top_five_types_plus_an_other_bucket():
    app = QApplication.instance() or QApplication([])
    _ = app

    class _ManyTypesService(_FakeExpenseService):
        def expenses_by_type(self):
            vals = [
                ("كهرباء", 12100), ("نت", 9500), ("مياه", 7500), ("أرضي", 1000),
                ("صيانة", 800), ("بنزين", 600), ("قرطاسية", 300),
            ]
            return [{"expense_type": n, "total": Decimal(v)} for n, v in vals]

    screen = ExpensesScreen(_ManyTypesService())
    bar_rows = {r["label"]: int(r["count"]) for r in screen.bar_chart._rows}
    bar_labels = [r["label"] for r in screen.bar_chart._rows]

    # Five biggest shown individually, everything else rolled into "أخرى".
    assert bar_labels == ["كهرباء", "نت", "مياه", "أرضي", "صيانة", "أخرى"]
    # صيانة (800) is the 5th biggest → shown; only بنزين + قرطاسية roll up.
    assert bar_rows["أخرى"] == 600 + 300
    # The donut buckets the same way.
    assert [r["label"] for r in screen.donut_chart._rows][-1] == "أخرى"


def test_few_types_show_no_other_bucket(expenses_screen):
    # The default fake has only three types → nothing to roll up.
    assert "أخرى" not in [r["label"] for r in expenses_screen.bar_chart._rows]


def test_new_record_defaults_the_date_to_today(expenses_screen):
    expenses_screen.new_record()
    today = datetime.date.today().strftime("%Y-%m-%d")
    assert expenses_screen.inputs["expense_date"].text() == today


def test_search_button_present_and_bottom_list_is_hidden(expenses_screen):
    # The bottom list is removed from view; searching is via the popup dialog.
    assert expenses_screen.search_button.text() == "بحث"
    assert expenses_screen._hidden_list.isHidden()


def test_expenses_search_dialog_defaults_to_latest_500():
    app = QApplication.instance() or QApplication([])
    _ = app
    from app.ui.dialogs.expenses_search_dialog import ExpensesSearchDialog

    class _Svc(_FakeExpenseService):
        last = None

        def search_expenses(self, date_from=None, date_to=None, expense_type=None, limit=500):
            self.last = (date_from, date_to, expense_type, limit)
            return [{"id": 7, "expense_date": "2026-08-13", "expense_type": "الكهرباء",
                     "amount": Decimal("8500"), "statement": "فاتورة"}]

    svc = _Svc()
    dialog = ExpensesSearchDialog(svc)
    # No date filter on open → latest 500.
    assert svc.last == (None, None, None, 500)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).data(256) == 7  # id in UserRole

    # Enabling the date filter drops the 500 cap and passes the range.
    dialog.enable_dates.setChecked(True)
    dialog.refresh_table()
    assert svc.last[0] is not None and svc.last[1] is not None
    assert svc.last[3] is None  # limit removed


def test_toolbar_has_the_same_crud_buttons(expenses_screen):
    labels = [
        b.text()
        for b in (
            expenses_screen.new_button,
            expenses_screen.edit_button,
            expenses_screen.save_button,
            expenses_screen.delete_button,
            expenses_screen.cancel_button,
            expenses_screen.refresh_button,
            expenses_screen.exit_button,
        )
    ]
    assert labels == ["جديد", "تعديل", "حفظ", "حذف", "إلغاء", "تحديث", "خروج"]
