"""Unit tests for the Access -> Tawrid import (no Access file, no database).

The mapping is where a migration silently corrupts data, so every conversion the
importer performs on the real ``tbgrarat`` rows is pinned here:

* plate numbers become text (Access stores them as integers),
* NULL money becomes 0 (the target columns are NOT NULL),
* names are trimmed (the UNIQUE index is on ``btrim(driver_name)``),
* a negative opening balance is carried across unchanged — one real driver is
  overpaid, and "fixing" that would invent money,
* and each of those is reported so a human can check it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.migrations.tawrid_import import (
    COLUMN_ORDER,
    ImportReport,
    import_tractors,
    map_tractor,
)

# A row exactly as pyodbc returns it from tbgrarat.
BASE_ROW = {
    "id": 11, "number1": 3, "NAME123": "السعيد معروف",
    "numbmaatora": 3581, "numbwesh": 7814,
    "sen": 140.0, "raml": 90.0, "BalancFirst": 209816.0,
    "date123": date(2024, 3, 27),
}


def mapped(**overrides):
    report = ImportReport(table="t")
    values = map_tractor({**BASE_ROW, **overrides}, report)
    return values, report


# --- straightforward mapping ------------------------------------------------

def test_maps_every_column_from_the_access_row():
    values, report = mapped()
    assert values == {
        "legacy_id": 11, "tractor_code": 3, "driver_name": "السعيد معروف",
        "trailer_no": "3581", "head_no": "7814",
        "price_sen": Decimal("140.0"), "price_raml": Decimal("90.0"),
        "opening_balance": Decimal("209816.0"),
        "opening_date": date(2024, 3, 27), "is_active": True,
    }
    assert report.adjustments == []


def test_column_order_matches_the_mapped_keys():
    """The INSERT uses positional params, so drift here would shuffle columns."""
    values, _ = mapped()
    assert set(COLUMN_ORDER) == set(values)
    assert len(COLUMN_ORDER) == len(values)


# --- plate numbers ----------------------------------------------------------

def test_plate_numbers_become_text():
    values, _ = mapped()
    assert values["trailer_no"] == "3581"
    assert isinstance(values["trailer_no"], str)


def test_missing_plate_becomes_none_not_the_string_none():
    values, _ = mapped(numbmaatora=None, numbwesh=None)
    assert values["trailer_no"] is None
    assert values["head_no"] is None


# --- money ------------------------------------------------------------------

def test_null_price_becomes_zero_and_is_reported():
    """One real row (محمد عفيفي) has a NULL سن; the column is NOT NULL."""
    values, report = mapped(id=51, NAME123="محمد عفيفي", sen=None)
    assert values["price_sen"] == Decimal("0")
    assert any("سعر السن" in note for _, _, note in report.adjustments)


def test_null_opening_balance_becomes_zero_and_is_reported():
    values, report = mapped(BalancFirst=None)
    assert values["opening_balance"] == Decimal("0")
    assert any("رصيد" in note for _, _, note in report.adjustments)


def test_negative_opening_balance_is_carried_across_unchanged():
    """ماهر الشرقاوي 2 is overpaid — the sign is real data, not an error."""
    values, report = mapped(id=40, NAME123="ماهر الشرقاوي 2", BalancFirst=-55738.0)
    assert values["opening_balance"] == Decimal("-55738.0")
    assert any("سالب" in note for _, _, note in report.adjustments)


def test_money_is_decimal_never_float():
    values, _ = mapped()
    for key in ("price_sen", "price_raml", "opening_balance"):
        assert isinstance(values[key], Decimal), key


# --- names ------------------------------------------------------------------

def test_name_is_trimmed_and_reported():
    """' دفعات  حسن' has outer spaces; the UNIQUE index is on btrim(name)."""
    values, report = mapped(id=60, NAME123=" دفعات  حسن")
    assert values["driver_name"] == "دفعات  حسن"      # inner spacing preserved
    assert any("مسافات" in note for _, _, note in report.adjustments)


def test_inner_spacing_is_left_alone():
    values, _ = mapped(NAME123="ربيع بصل 1")
    assert values["driver_name"] == "ربيع بصل 1"


# --- the run ----------------------------------------------------------------

class FakeReader:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def rows(self, query):
        return iter(self._rows)


class FakeDb:
    def __init__(self, inserted=True):
        self.calls = []
        self.inserted = inserted

    def fetch_one(self, query, params=None):
        self.calls.append(params)
        return {"inserted": self.inserted}

    def fetch_all(self, query, params=None):
        # import_tractors reads the codes already in the app to steer a new card
        # clear of a taken مسلسل. An empty app means no collision — the fresh
        # import these tests pin — so every row keeps its own tractor_code.
        return []


@pytest.fixture
def patch_reader(monkeypatch):
    def install(rows):
        monkeypatch.setattr("app.migrations.tawrid_import.AccessReader",
                            lambda *a, **k: FakeReader(rows))
    return install


def test_dry_run_reads_but_never_writes(patch_reader):
    patch_reader([BASE_ROW])
    db = FakeDb()
    report = import_tractors(db=db, dry_run=True)
    assert report.read == 1
    assert (report.inserted, report.updated) == (0, 0)
    assert db.calls == []


def test_import_writes_one_row_per_source_row(patch_reader):
    patch_reader([BASE_ROW, {**BASE_ROW, "id": 13, "number1": 4, "NAME123": "احمد معروف"}])
    db = FakeDb()
    report = import_tractors(db=db)
    assert report.read == 2
    assert report.inserted == 2
    assert len(db.calls) == 2
    # Params are positional and must follow COLUMN_ORDER.
    assert db.calls[0][COLUMN_ORDER.index("driver_name")] == "السعيد معروف"
    assert db.calls[0][COLUMN_ORDER.index("legacy_id")] == 11


def test_rerun_counts_as_updated_not_inserted(patch_reader):
    patch_reader([BASE_ROW])
    report = import_tractors(db=FakeDb(inserted=False))
    assert (report.inserted, report.updated) == (0, 1)


def test_blank_name_is_skipped_and_recorded_as_an_error(patch_reader):
    patch_reader([{**BASE_ROW, "NAME123": "   "}])
    db = FakeDb()
    report = import_tractors(db=db)
    assert report.skipped == 1
    assert report.inserted == 0
    assert db.calls == []
    assert report.errors and "فارغ" in report.errors[0][2]


def test_a_failing_row_does_not_abort_the_rest(patch_reader):
    class Flaky(FakeDb):
        def fetch_one(self, query, params=None):
            self.calls.append(params)
            if len(self.calls) == 1:
                raise RuntimeError("duplicate key")
            return {"inserted": True}

    patch_reader([BASE_ROW, {**BASE_ROW, "id": 13, "number1": 4, "NAME123": "احمد معروف"}])
    report = import_tractors(db=Flaky())
    assert report.skipped == 1
    assert report.inserted == 1
    assert len(report.errors) == 1


def test_report_text_lists_adjustments_and_errors():
    report = ImportReport(table="tawrid_tractors", read=2, inserted=1, skipped=1)
    report.note(51, "محمد عفيفي", "سعر السن كان فارغاً -> 0")
    report.errors.append((99, "بدون اسم", "اسم السائق فارغ"))
    text = report.as_text()
    assert "tawrid_tractors" in text
    assert "محمد عفيفي" in text
    assert "بدون اسم" in text
