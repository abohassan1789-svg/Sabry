from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app.services.review_data_service import TABLE_SPECS
from app.ui.screens.workers_screen import WorkersScreen


class _FakeWorkerService:
    def list_records(self, spec, keyword="", limit=500):
        return [
            {"worker_id": 1, "worker_name": "محمود عامل", "mobile": "0111", "opening_balance": 500},
            {"worker_id": 2, "worker_name": "سعيد أحمد", "mobile": "0122", "opening_balance": 0},
        ]

    def next_id(self, spec):
        return 1


@pytest.fixture
def workers_screen():
    app = QApplication.instance() or QApplication([])
    _ = app
    return WorkersScreen(_FakeWorkerService())


def test_workers_spec_has_four_fields_and_two_grid_columns():
    spec = TABLE_SPECS["workers"]
    assert spec.primary_key == "worker_id"
    assert [f.name for f in spec.fields] == [
        "worker_id",
        "worker_name",
        "mobile",
        "opening_balance",
    ]
    assert spec.list_columns == ("worker_name", "mobile")


def test_worker_code_is_displayed_zero_padded_to_four_digits(workers_screen):
    assert workers_screen._display_value("worker_id", 1) == "0001"
    assert workers_screen._display_value("worker_id", 42) == "0042"
    assert workers_screen._display_value("worker_id", 12345) == "12345"
    assert workers_screen._display_value("worker_id", None) is None
    # Other fields are returned unchanged.
    assert workers_screen._display_value("worker_name", "محمود") == "محمود"


def test_workers_grid_shows_only_name_and_mobile(workers_screen):
    table = workers_screen.table
    assert table.columnCount() == 2
    headers = [table.horizontalHeaderItem(i).text() for i in range(2)]
    assert headers == ["اسم العامل", "الموبايل"]
    # The raw worker_id rides along in UserRole for row selection/loading.
    assert table.item(0, 0).data(256) == 1


def test_workers_new_record_previews_code_0001_and_zero_balance(workers_screen):
    workers_screen.new_record()
    assert workers_screen.inputs["worker_id"].text() == "0001"
    assert workers_screen.inputs["opening_balance"].text() == "0.00"


def test_workers_toolbar_has_the_same_crud_buttons(workers_screen):
    labels = [
        b.text()
        for b in (
            workers_screen.new_button,
            workers_screen.edit_button,
            workers_screen.save_button,
            workers_screen.delete_button,
            workers_screen.cancel_button,
            workers_screen.refresh_button,
            workers_screen.exit_button,
        )
    ]
    assert labels == ["جديد", "تعديل", "حفظ", "حذف", "إلغاء", "تحديث", "خروج"]


def test_worker_next_id_is_plain_starting_at_one():
    from app.services.review_data_service import ReviewDataService

    class _Cur:
        def fetchone(self):
            return {"next_id": 1}

    class _Conn:
        def execute(self, query, params=None):
            return _Cur()

    service = ReviewDataService()
    # workers are NOT in the 1001-start set, so an empty table previews 1 (→0001).
    assert service._next_id(_Conn(), TABLE_SPECS["workers"]) == 1
