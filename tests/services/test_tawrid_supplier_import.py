"""Tests for the phase-3 import: Access ``pruduct`` -> ``tawrid_suppliers``.

No Access file and no database — these exercise the mapping and the two
decisions the importer has to make on its own, using the real legacy rows.

What has to be right:

* **The duplicate مسلسل.** ``Fproduct`` defaulted its مسلسل to
  ``DMax("[number1]","fanii")+1`` — the *customers* table — so 26, 31 and 46 are
  each used twice in ``pruduct``. ``supplier_code`` is UNIQUE in the new table,
  so the later claimant of each pair has to move, and the assignment has to be
  **stable**: re-running the import must land on the same numbers, not walk them
  forward every pass.
* **The nameless row.** ``pruduct`` id 23 has no name at all, and
  ``supplier_name`` is NOT NULL and UNIQUE.
* **The dead cards.** 7 of the 23 have no ticket, no voucher and no opening
  balance. They come across موقوف rather than being dropped — dropping is what
  orphaned crusher 22's tickets.
* **Nothing is invented.** ``pruduct`` has no phone column, and ``notees`` is
  empty in all 23 rows; neither may be filled with a placeholder.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from app.migrations.tawrid_import import (
    ImportReport,
    SUPPLIER_COLUMN_ORDER,
    _supplier_code_overrides,
    map_supplier,
)

# The real duplicate pairs out of ``pruduct``, in id order.
ROWS = [
    {"id": 9, "number1": 26, "productName": "فراج الغول"},
    {"id": 10, "number1": 26, "productName": "الجزيرة"},
    {"id": 11, "number1": 31, "productName": "عتاقة"},
    {"id": 12, "number1": 31, "productName": "مشال فقط"},
    {"id": 16, "number1": 46, "productName": "نقدي"},
    {"id": 17, "number1": 46, "productName": "الفهد"},
    {"id": 24, "number1": 84, "productName": "بسام كاوتش"},
]


def report() -> ImportReport:
    return ImportReport(table="tawrid_suppliers")


# --- the duplicate مسلسل -----------------------------------------------------

def test_only_the_duplicated_codes_are_moved():
    assert set(_supplier_code_overrides(ROWS)) == {10, 12, 17}


def test_the_first_row_to_use_a_number_keeps_it():
    """Lowest Access id wins: فراج الغول (9) keeps 26, الجزيرة (10) moves."""
    overrides = _supplier_code_overrides(ROWS)
    assert 9 not in overrides and 11 not in overrides and 16 not in overrides


def test_moved_codes_start_past_the_highest_number_in_use():
    assert _supplier_code_overrides(ROWS) == {10: 85, 12: 86, 17: 87}


def test_the_assignment_is_stable_across_runs():
    """Computed from the Access rows only — never from the target table, which
    would make every re-run push the numbers further along."""
    assert _supplier_code_overrides(ROWS) == _supplier_code_overrides(ROWS)


def test_a_table_with_no_duplicates_moves_nothing():
    clean = [{"id": 1, "number1": 1}, {"id": 2, "number1": 5}]
    assert _supplier_code_overrides(clean) == {}


def test_a_missing_code_is_treated_as_needing_one():
    moved = _supplier_code_overrides([{"id": 1, "number1": 7}, {"id": 2, "number1": None}])
    assert moved == {2: 8}


# --- mapping one row ---------------------------------------------------------

def test_a_normal_row_maps_straight_across():
    row = {
        "id": 1, "number1": 1, "productName": "الهدي", "notees": None,
        "BalancFirst": 1511010.0, "date123": datetime.datetime(2024, 3, 27),
        "sen1": 180.0, "sen2": 165.0, "sen3": 160.0, "sen6safi": 120.0,
        "sen6bodra": 100.0, "sen3adsa": 170.0, "bodra": 55.0, "raml": 0.0,
        "sen_plus": 160.0, "SeenModarg": 150.0,
    }
    values = map_supplier(row, report())
    assert values["legacy_id"] == 1
    assert values["supplier_code"] == 1
    assert values["supplier_name"] == "الهدي"
    assert values["is_active"] is True
    assert values["opening_balance"] == Decimal("1511010")
    assert values["price_sen1"] == Decimal("180")
    # sen3 carries the label «سن عتاقة», which is what Fproduct showed.
    assert values["price_sen_ataqa"] == Decimal("160")
    assert values["price_sen_plus"] == Decimal("160")
    assert values["price_sen_modarag"] == Decimal("150")
    assert values["price_raml"] == Decimal("0")


def test_nothing_is_invented_for_columns_pruduct_does_not_have():
    row = {"id": 2, "number1": 2, "productName": "ابو شمة", "notees": None,
           "BalancFirst": 515304.0, "date123": None}
    values = map_supplier(row, report())
    assert values["phone"] is None      # pruduct has no contact column
    assert values["notes"] is None      # notees is empty in all 23 rows


def test_an_empty_note_becomes_null_not_an_empty_string():
    row = {"id": 2, "number1": 2, "productName": "ابو شمة", "notees": "   "}
    assert map_supplier(row, report())["notes"] is None


def test_a_real_note_survives():
    row = {"id": 2, "number1": 2, "productName": "ابو شمة", "notees": " مورد رملة "}
    assert map_supplier(row, report())["notes"] == "مورد رملة"


def test_a_blank_opening_balance_becomes_zero_and_is_reported():
    rep = report()
    row = {"id": 6, "number1": 6, "productName": "النائب", "BalancFirst": None}
    assert map_supplier(row, rep)["opening_balance"] == Decimal("0")
    assert any("رصيد أول المدة كان فارغاً" in what for _i, _n, what in rep.adjustments)


def test_a_name_with_stray_spaces_is_trimmed_and_reported():
    rep = report()
    row = {"id": 3, "number1": 3, "productName": "  جولد ستون ", "BalancFirst": 0}
    assert map_supplier(row, rep)["supplier_name"] == "جولد ستون"
    assert any("مسافات زائدة" in what for _i, _n, what in rep.adjustments)


# --- the nameless row --------------------------------------------------------

def test_the_nameless_row_gets_a_name_that_says_what_it_is():
    """id 23: supplier_name is NOT NULL, so it cannot come across blank."""
    rep = report()
    row = {"id": 23, "number1": 82, "productName": "", "BalancFirst": 0}
    values = map_supplier(row, rep)
    assert values["supplier_name"] == "بدون اسم — مسلسل 82"
    assert values["is_active"] is False
    assert values["legacy_id"] == 23      # the legacy id still survives
    assert any("لا يوجد اسم" in what for _i, _n, what in rep.adjustments)


# --- the dead cards ----------------------------------------------------------

def test_a_card_with_no_movement_comes_across_stopped():
    rep = report()
    row = {"id": 6, "number1": 6, "productName": "النائب", "BalancFirst": 0}
    values = map_supplier(row, rep, no_movement=True)
    assert values["is_active"] is False
    assert any("لا حركة ولا رصيد" in what for _i, _n, what in rep.adjustments)


def test_a_card_with_movement_stays_active():
    row = {"id": 1, "number1": 1, "productName": "الهدي", "BalancFirst": 0}
    assert map_supplier(row, report(), no_movement=False)["is_active"] is True


def test_a_stopped_card_is_kept_not_dropped():
    """Deleting is what orphaned crusher 22's four tickets."""
    row = {"id": 13, "number1": 33, "productName": "بترميكس", "BalancFirst": 0}
    assert map_supplier(row, report(), no_movement=True)["legacy_id"] == 13


# --- the renumbering is reported ---------------------------------------------

def test_a_moved_code_is_reported_with_both_numbers():
    rep = report()
    row = {"id": 10, "number1": 26, "productName": "الجزيرة", "BalancFirst": 0}
    values = map_supplier(row, rep, code_override=85)
    assert values["supplier_code"] == 85
    assert any("26" in what and "85" in what for _i, _n, what in rep.adjustments)


# --- the insert contract -----------------------------------------------------

@pytest.mark.parametrize("column", SUPPLIER_COLUMN_ORDER)
def test_every_column_the_insert_needs_is_produced(column):
    row = {"id": 1, "number1": 1, "productName": "الهدي", "BalancFirst": 0}
    assert column in map_supplier(row, report())


def test_is_active_is_never_overwritten_by_an_update():
    """Once someone stops or restarts a crusher on the screen, re-running the
    import must not undo it — so the UPSERT's SET list leaves it alone."""
    from app.migrations.tawrid_import import _SUPPLIER_UPSERT

    set_clause = _SUPPLIER_UPSERT.split("DO UPDATE SET")[1]
    assert "is_active" not in set_clause
    assert "legacy_id" not in set_clause      # the conflict key, never reassigned
