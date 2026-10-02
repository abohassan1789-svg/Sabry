"""Tests for the Worker Daily screen stack (شاشة يومية العمال).

A ``TableSpec`` drives the generic ``BaseCrudScreen`` + ``ReviewDataService``, so
these tests cover the worker-daily specifics: the spec shape (fields in the
requested order, the two computed columns virtual), the joined list query, the
three KPI cards + top-workers chart, the searchable worker dropdown, the live
formula previews (الراتب اليومي / الرصيد), and the automatic movement number.

No real database is used — a fake connection/service returns canned rows. Qt runs
headless (offscreen).
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
def test_worker_daily_spec_fields_in_requested_order():
    spec = TABLE_SPECS["worker_daily"]
    assert spec.table_name == "worker_daily"
    assert spec.primary_key == "id"
    # The nine on-form fields, in the exact order the user asked for.
    assert [f.name for f in spec.fields if not f.hidden_on_form] == [
        "id",
        "movement_date",
        "worker_id",
        "statement",
        "number_of_days",
        "daily_wage",
        "daily_salary",
        "cash",
        "balance",
    ]
    field_by_name = {f.name: f for f in spec.fields}
    # رقم الحركة is read-only (auto) and visible on the form.
    assert field_by_name["id"].readonly is True
    assert field_by_name["id"].hidden_on_form is False
    # The two formula fields are virtual (DB generated columns) + read-only.
    for name in ("daily_salary", "balance"):
        assert field_by_name[name].virtual is True
        assert field_by_name[name].readonly is True
    # Required: date + worker.
    assert field_by_name["movement_date"].required is True
    assert field_by_name["worker_id"].required is True


def test_worker_daily_not_in_lookup_layout():
    from app.ui.common.theme import LOOKUP_LAYOUT_KEYS

    assert "worker_daily" not in LOOKUP_LAYOUT_KEYS


# --------------------------------------------------------------------------- #
# Service: joined list query + search
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


def test_list_joins_workers_for_the_name_column():
    conn = _FakeConn([])
    service = _service_with(conn)

    service.list_records(TABLE_SPECS["worker_daily"], "")

    sql, params = conn.calls[0]
    assert "FROM worker_daily wd" in sql
    assert "LEFT JOIN workers w ON w.worker_id = wd.worker_id" in sql
    for alias in ("id", "worker_name", "daily_salary", "cash", "balance"):
        assert f'"{alias}"' in sql
    assert params == [500]


def test_search_matches_worker_statement_or_date():
    conn = _FakeConn([])
    service = _service_with(conn)

    service.list_records(TABLE_SPECS["worker_daily"], "احمد")

    sql, params = conn.calls[0]
    assert sql.count("ILIKE") == 3
    assert "w.worker_name" in sql
    assert "wd.statement" in sql
    assert "wd.movement_date" in sql
    assert params == ["%احمد%", "%احمد%", "%احمد%", 500]


def test_save_never_sends_the_generated_columns():
    conn = _FakeConn([{"id": 1}])
    service = _service_with(conn)

    payload = {
        "movement_date": "2026-08-13",
        "worker_id": 5,
        "statement": "شغل",
        "number_of_days": "10",
        "daily_wage": "25",
        "daily_salary": "250.00",   # a preview — must never be written
        "cash": "40",
        "balance": "210.00",        # a preview — must never be written
    }
    service.save_record(TABLE_SPECS["worker_daily"], payload, None)

    sql, params = conn.calls[0]
    assert "INSERT INTO" in sql
    # Generated columns are virtual → never in the INSERT column list.
    assert "daily_salary" not in sql
    assert "balance" not in sql


def test_missing_required_worker_raises_arabic_message():
    conn = _FakeConn([{"id": 1}])
    service = _service_with(conn)

    with pytest.raises(ValueError) as excinfo:
        service.save_record(
            TABLE_SPECS["worker_daily"],
            {"movement_date": "2026-08-13", "worker_id": None, "number_of_days": "1", "daily_wage": "1", "cash": "0"},
            None,
        )
    assert "اسم العامل" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# UI: cards, dropdown, live formulas, movement number
# --------------------------------------------------------------------------- #
class _FakeUiService:
    def list_records(self, spec, keyword="", limit=500):
        return [
            {"id": 1, "movement_date": "2026-08-13", "worker_name": "عامل أ",
             "daily_salary": Decimal("300"), "cash": Decimal("50"), "balance": Decimal("250")},
        ]

    def list_workers_for_selection(self):
        return [
            {"worker_id": 1, "worker_name": "عامل أ"},
            {"worker_id": 2, "worker_name": "عامل ب"},
        ]

    def worker_daily_total_salary(self):
        return Decimal("9000.00")

    def worker_daily_total_cash(self):
        return Decimal("1500.00")

    def worker_daily_total_balance(self):
        return Decimal("7500.00")

    def worker_daily_by_worker(self):
        return [
            {"worker_name": "عامل أ", "total": Decimal("5000")},
            {"worker_name": "عامل ب", "total": Decimal("4000")},
        ]

    def get_record(self, spec, record_id):
        return None

    def next_id(self, spec):
        return 7


@pytest.fixture
def worker_screen():
    app = QApplication.instance() or QApplication([])
    _ = app
    from app.ui.screens.worker_daily_screen import WorkerDailyScreen

    return WorkerDailyScreen(_FakeUiService())


def test_form_shows_all_nine_fields(worker_screen):
    assert set(worker_screen.inputs.keys()) == {
        "id",
        "movement_date",
        "worker_id",
        "statement",
        "number_of_days",
        "daily_wage",
        "daily_salary",
        "cash",
        "balance",
    }


def test_three_cards_show_the_totals(worker_screen):
    assert worker_screen.kpi_salary_value.text() == "9,000.00"
    assert worker_screen.kpi_cash_value.text() == "1,500.00"
    assert worker_screen.kpi_balance_value.text() == "7,500.00"


def test_worker_is_a_dropdown_that_stores_the_id(worker_screen):
    combo = worker_screen.inputs["worker_id"]
    assert isinstance(combo, QComboBox)
    combo.setCurrentText("عامل ب")
    assert worker_screen._editor_value(combo) == 2
    combo.setCurrentText("   ")
    assert worker_screen._editor_value(combo) is None
    combo.setCurrentText("عامل غير موجود")
    assert worker_screen._editor_value(combo) is None


def test_live_formulas_daily_salary_and_balance(worker_screen):
    worker_screen.inputs["number_of_days"].setText("10")
    worker_screen.inputs["daily_wage"].setText("25")
    # الراتب اليومي = 10 × 25 = 250 (balance = salary − 0 before any cash).
    assert worker_screen.inputs["daily_salary"].text() == "250.00"
    assert worker_screen.inputs["balance"].text() == "250.00"
    worker_screen.inputs["cash"].setText("40")
    # الرصيد = 250 − 40 = 210.
    assert worker_screen.inputs["balance"].text() == "210.00"
    # Clearing an input blanks the previews (nothing to compute).
    worker_screen.inputs["daily_wage"].setText("")
    assert worker_screen.inputs["daily_salary"].text() == ""
    assert worker_screen.inputs["balance"].text() == ""


def test_formula_fields_are_read_only(worker_screen):
    assert worker_screen.inputs["daily_salary"].isReadOnly()
    assert worker_screen.inputs["balance"].isReadOnly()


def test_top_workers_chart_data(worker_screen):
    labels = [r["label"] for r in worker_screen.bar_chart._rows]
    assert labels == ["عامل أ", "عامل ب"]


def test_new_record_defaults_date_and_previews_movement_number(worker_screen):
    worker_screen.new_record()
    today = datetime.date.today().strftime("%Y-%m-%d")
    assert worker_screen.inputs["movement_date"].text() == today
    # رقم الحركة shows the next id as a preview (real id assigned on save).
    assert worker_screen.inputs["id"].text() == "7"


def test_search_button_present_and_list_hidden(worker_screen):
    assert worker_screen.search_button.text() == "بحث"
    assert worker_screen._hidden_list.isHidden()


def test_blank_numeric_inputs_default_to_zero_on_save(worker_screen, monkeypatch):
    import app.ui.screens.base_crud_screen as bcs

    class _MB:
        @staticmethod
        def information(*a, **k):
            pass

        @staticmethod
        def critical(*a, **k):
            pass

    monkeypatch.setattr(bcs, "QMessageBox", _MB)
    saved = {}

    def _fake_save(spec, payload, record_id):
        saved.update(payload)
        return 1

    worker_screen.service.save_record = _fake_save  # type: ignore[attr-defined]
    worker_screen.mode = "new"
    worker_screen.inputs["worker_id"].setCurrentText("عامل أ")
    worker_screen.inputs["number_of_days"].setText("")
    worker_screen.inputs["daily_wage"].setText("")
    worker_screen.inputs["cash"].setText("")
    worker_screen.save_record()
    # Blank numeric editors were coerced to "0" before the save payload was built.
    assert saved.get("number_of_days") == "0"
    assert saved.get("daily_wage") == "0"
    assert saved.get("cash") == "0"


def test_search_dialog_defaults_to_latest_500():
    app = QApplication.instance() or QApplication([])
    _ = app
    from app.ui.dialogs.worker_daily_search_dialog import WorkerDailySearchDialog

    class _Svc(_FakeUiService):
        last = None

        def search_worker_daily(self, date_from=None, date_to=None, worker_id=None, limit=500):
            self.last = (date_from, date_to, worker_id, limit)
            return [{"id": 3, "movement_date": "2026-08-13", "worker_name": "عامل أ",
                     "number_of_days": Decimal("5"), "daily_wage": Decimal("30"),
                     "daily_salary": Decimal("150"), "cash": Decimal("20"),
                     "balance": Decimal("130"), "statement": "شغل"}]

    svc = _Svc()
    dialog = WorkerDailySearchDialog(svc)
    assert svc.last == (None, None, None, 500)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).data(256) == 3  # id in UserRole

    dialog.enable_dates.setChecked(True)
    dialog.refresh_table()
    assert svc.last[0] is not None and svc.last[1] is not None
    assert svc.last[3] is None


def test_toolbar_has_the_same_crud_buttons(worker_screen):
    labels = [
        b.text()
        for b in (
            worker_screen.new_button,
            worker_screen.edit_button,
            worker_screen.save_button,
            worker_screen.delete_button,
            worker_screen.cancel_button,
            worker_screen.refresh_button,
            worker_screen.exit_button,
        )
    ]
    assert labels == ["جديد", "تعديل", "حفظ", "حذف", "إلغاء", "تحديث", "خروج"]
