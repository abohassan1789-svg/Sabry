"""Tests for نافذة «بحث عن كشف» (headless Qt, no database).

The cubing screen carries no sheet list, so this dialog is the only way to reach
an earlier كشف. Its search is LIVE against a caller-supplied ``search_fn``, so the
tests drive a stub function and pin the columns, that typing re-runs the search,
and that a pick returns the ``cubing_id``.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from app.ui.dialogs.tawrid_cubing_picker import COLUMNS, TawridCubingPickerDialog, _num

SHEETS = [
    {"cubing_id": 1, "sheet_no": 15, "sheet_date": "2025-12-01",
     "supplier_name": "الهدي", "line_count": 28, "total_volume": Decimal("1480.5")},
    {"cubing_id": 2, "sheet_no": 14, "sheet_date": "2025-04-19",
     "supplier_name": "المتحدة", "line_count": 1, "total_volume": Decimal("59")},
]


def _search(keyword: str):
    needle = keyword.strip()
    if not needle:
        return list(SHEETS)
    return [s for s in SHEETS if needle in str(s["sheet_no"]) or needle in s["supplier_name"]]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qt_app):
    return TawridCubingPickerDialog(_search)


@pytest.mark.parametrize("value,expected", [
    (Decimal("1480.5"), "1,480.50"),
    (Decimal("0"), "0.00"),
    (None, "0.00"),
])
def test_volume_formatting(value, expected):
    assert _num(value) == expected


def test_columns_are_sheet_no_date_crusher_count_total():
    assert [key for key, _label, _m in COLUMNS] == [
        "sheet_no", "sheet_date", "supplier_name", "line_count", "total_volume",
    ]


def test_it_opens_showing_recent_sheets(dialog):
    assert dialog.table.rowCount() == len(SHEETS)
    assert dialog.count_label.text() == f"عدد الكشوف: {len(SHEETS)}"


def test_typing_reruns_the_live_search(dialog):
    dialog.search_text.setText("المتحدة")
    dialog._run_search()
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == "المتحدة"


def test_searching_by_sheet_number(dialog):
    dialog.search_text.setText("15")
    dialog._run_search()
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "15"


def test_the_total_is_number_formatted(dialog):
    assert dialog.table.item(0, 4).text() == "1,480.50"


def test_choosing_a_row_returns_its_cubing_id(dialog):
    dialog.table.setCurrentCell(1, 0)
    dialog.accept_selected()
    assert dialog.selected_id == 2
    assert dialog.result() == QDialog.Accepted


def test_enter_picks_the_only_match(dialog):
    dialog.search_text.setText("15")
    dialog._accept_if_unambiguous()
    assert dialog.selected_id == 1


def test_a_failing_search_does_not_crash(qt_app):
    def boom(_keyword):
        raise RuntimeError("db down")

    view = TawridCubingPickerDialog(boom)
    assert view.table.rowCount() == 0
    assert view.choose_button.isEnabled() is False
