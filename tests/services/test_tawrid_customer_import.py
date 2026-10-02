"""Unit tests for the phase-2 Access -> Tawrid import (no Access file, no database).

The mapping is where a migration silently corrupts data, so every conversion the
importer performs on the real ``fanii`` / ``CarCus`` rows is pinned here:

* the ten item-price columns land in the right new columns — in particular
  ``sen3`` becomes ``price_sen_ataqa``, because «سن عتاقة» is the label FEMP
  actually showed over that column,
* NULL money becomes 0 (the target columns are NOT NULL),
* names are trimmed (the UNIQUE index is on ``btrim(customer_name)``),
* the one customer with no name at all is carried across موقوف under a stated
  placeholder rather than dropped, so the ``legacy_id`` later phases join on
  survives,
* and the price grid resolves BOTH sides through ``legacy_id``, so it lines up
  with the tractor cards the الجرارات screen shows. A row whose tractor was
  deleted in Access is reported and skipped, never forced in.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.migrations.tawrid_import import (
    CUSTOMER_COLUMN_ORDER,
    ITEM_PRICE_MAP,
    ImportReport,
    import_customer_tractor_prices,
    import_customers,
    map_customer,
)

# A row exactly as pyodbc returns it from fanii (نيو جيزة, the busiest customer).
BASE_ROW = {
    "id": 494, "number1": 5, "NAME123": "نيو جيزة",
    "sen1": 372.5, "sen2": 372.5, "sen3": 372.5, "sen6safi": 372.5,
    "sen6bodra": 340.0, "sen3adsa": 372.5, "bodra": 0.0, "raml": 0.0,
    "sen_plus": 372.5, "SeenModarg": None,
    "Des": 0.0, "BalancFirst": 297000.0, "date123": date(2024, 3, 27),
}


def mapped(**overrides):
    report = ImportReport(table="t")
    values = map_customer({**BASE_ROW, **overrides}, report)
    return values, report


# --- straightforward mapping ------------------------------------------------

def test_maps_every_column_from_the_access_row():
    values, report = mapped()
    assert values == {
        "legacy_id": 494, "customer_code": 5, "customer_name": "نيو جيزة",
        "phone": None,
        "price_sen1": Decimal("372.5"), "price_sen2": Decimal("372.5"),
        "price_sen_ataqa": Decimal("372.5"), "price_sen6_safi": Decimal("372.5"),
        "price_sen6_bodra": Decimal("340.0"), "price_sen_adsa": Decimal("372.5"),
        "price_bodra": Decimal("0.0"), "price_raml": Decimal("0.0"),
        "price_sen_plus": Decimal("372.5"), "price_sen_modarag": Decimal("0"),
        "discount_percent": Decimal("0.0"), "opening_balance": Decimal("297000.0"),
        "opening_date": date(2024, 3, 27), "is_active": True,
    }
    assert report.adjustments == []


def test_column_order_matches_the_mapped_keys():
    """The INSERT uses positional placeholders; a drift here writes to the wrong column."""
    values, _ = mapped()
    assert set(CUSTOMER_COLUMN_ORDER) == set(values)


def test_sen3_lands_in_the_column_named_for_the_label_users_read():
    """FEMP labelled the ``sen3`` box «سن عتاقة»; the new column keeps that name."""
    assert dict(ITEM_PRICE_MAP)["sen3"] == "price_sen_ataqa"


def test_the_access_sen_plus_column_is_carried_across():
    """``sen++`` is not a legal Python/SQL identifier — it is aliased on the way out."""
    assert dict(ITEM_PRICE_MAP)["sen_plus"] == "price_sen_plus"
    values, _ = mapped(sen_plus=355.0)
    assert values["price_sen_plus"] == Decimal("355.0")


def test_all_ten_item_prices_are_mapped_exactly_once():
    targets = [target for _source, target in ITEM_PRICE_MAP]
    assert len(ITEM_PRICE_MAP) == 10
    assert len(set(targets)) == 10


# --- the conversions that would otherwise corrupt data ----------------------

def test_money_is_decimal_never_float():
    values, _ = mapped(sen1=372.5)
    assert isinstance(values["price_sen1"], Decimal)
    assert isinstance(values["opening_balance"], Decimal)


@pytest.mark.parametrize("column,target", ITEM_PRICE_MAP)
def test_a_null_item_price_becomes_zero(column, target):
    """Every price column is NOT NULL DEFAULT 0."""
    values, _ = mapped(**{column: None})
    assert values[target] == Decimal("0")


def test_null_opening_balance_becomes_zero_and_is_reported():
    values, report = mapped(BalancFirst=None)
    assert values["opening_balance"] == Decimal("0")
    assert "رصيد أول المدة" in report.adjustments[0][2]


def test_name_is_trimmed_and_reported():
    values, report = mapped(NAME123=" ريشة فتحي")
    assert values["customer_name"] == "ريشة فتحي"
    assert "مسافات" in report.adjustments[0][2]


def test_inner_spacing_is_left_alone():
    values, _ = mapped(NAME123="خالد الجواد 2026")
    assert values["customer_name"] == "خالد الجواد 2026"


def test_the_nameless_customer_is_carried_across_stopped_not_dropped():
    """Dropping it would lose the legacy id later phases join on."""
    values, report = mapped(NAME123=None, number1=96)
    assert values["customer_name"] == "بدون اسم — مسلسل 96"
    assert values["is_active"] is False
    assert values["legacy_id"] == 494
    assert "لا يوجد اسم" in report.adjustments[0][2]


def test_a_customer_with_a_name_stays_active():
    values, _ = mapped()
    assert values["is_active"] is True


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
    """Answers the two lookup queries the price import needs, then records writes."""

    def __init__(self, inserted=True, customers=(), tractors=()):
        self.calls = []
        self.inserted = inserted
        self.customers = list(customers)
        self.tractors = list(tractors)

    def fetch_all(self, query, params=None):
        if "tawrid_customers" in str(query):
            return self.customers
        if "tawrid_tractors" in str(query):
            return self.tractors
        raise AssertionError(f"unexpected query: {query}")

    def fetch_one(self, query, params=None):
        self.calls.append(params)
        return {"inserted": self.inserted}


@pytest.fixture
def patch_reader(monkeypatch):
    def install(rows):
        monkeypatch.setattr("app.migrations.tawrid_import.AccessReader",
                            lambda *a, **k: FakeReader(rows))
    return install


def test_dry_run_reads_but_never_writes(patch_reader):
    patch_reader([BASE_ROW])
    db = FakeDb()
    report = import_customers(db=db, dry_run=True)
    assert report.read == 1
    assert (report.inserted, report.updated) == (0, 0)
    assert db.calls == []


def test_import_writes_one_row_per_source_row(patch_reader):
    patch_reader([BASE_ROW, {**BASE_ROW, "id": 498, "number1": 7, "NAME123": "يحي زايد"}])
    db = FakeDb()
    report = import_customers(db=db)
    assert (report.read, report.inserted, report.updated) == (2, 2, 0)
    assert len(db.calls) == 2
    assert len(db.calls[0]) == len(CUSTOMER_COLUMN_ORDER)


def test_rerun_counts_as_updated_not_inserted(patch_reader):
    patch_reader([BASE_ROW])
    report = import_customers(db=FakeDb(inserted=False))
    assert (report.inserted, report.updated) == (0, 1)


def test_a_failing_row_does_not_abort_the_rest(patch_reader):
    class Flaky(FakeDb):
        def fetch_one(self, query, params=None):
            self.calls.append(params)
            if len(self.calls) == 1:
                raise RuntimeError("duplicate key")
            return {"inserted": True}

    patch_reader([BASE_ROW, {**BASE_ROW, "id": 498, "NAME123": "يحي زايد"}])
    db = Flaky()
    report = import_customers(db=db)
    assert report.inserted == 1
    assert report.skipped == 1
    assert len(report.errors) == 1


# --- the price grid ---------------------------------------------------------

GRID_ROW = {
    "id": 49, "inv_id": 494, "maatora_id": 11,
    "numberwesh": 7814, "tak3ib": 60.5, "PriceSen": 180.0, "PriceRaml": 0.0,
}
DB_CUSTOMERS = [{"legacy_id": 494, "customer_id": 5, "customer_name": "نيو جيزة"}]
DB_TRACTORS = [{"legacy_id": 11, "tractor_id": 3, "driver_name": "السعيد معروف",
                "head_no": "7814"}]


def test_the_grid_resolves_both_sides_through_legacy_id(patch_reader):
    """It must line up with the migrated tractor cards, not with raw Access ids."""
    patch_reader([GRID_ROW])
    db = FakeDb(customers=DB_CUSTOMERS, tractors=DB_TRACTORS)
    report = import_customer_tractor_prices(db=db)

    assert (report.read, report.inserted, report.skipped) == (1, 1, 0)
    legacy_id, customer_id, tractor_id, load, sen, raml = db.calls[0]
    assert (legacy_id, customer_id, tractor_id) == (49, 5, 3)
    assert (load, sen, raml) == (Decimal("60.5"), Decimal("180.0"), Decimal("0.0"))


def test_a_row_whose_tractor_was_deleted_is_reported_not_forced_in(patch_reader):
    """12 of the 236 real rows point at tractors Access no longer has."""
    patch_reader([{**GRID_ROW, "maatora_id": 27}])
    db = FakeDb(customers=DB_CUSTOMERS, tractors=DB_TRACTORS)
    report = import_customer_tractor_prices(db=db)

    assert (report.inserted, report.skipped) == (0, 1)
    assert db.calls == []
    assert "محذوف" in report.errors[0][2]


def test_a_row_whose_customer_did_not_migrate_is_reported(patch_reader):
    patch_reader([{**GRID_ROW, "inv_id": 999}])
    db = FakeDb(customers=DB_CUSTOMERS, tractors=DB_TRACTORS)
    report = import_customer_tractor_prices(db=db)

    assert (report.inserted, report.skipped) == (0, 1)
    assert db.calls == []


def test_a_stale_head_number_is_reported_and_the_tractor_card_wins(patch_reader):
    """CarCus kept its own copy of رقم الوش and 3 rows had drifted from the card."""
    patch_reader([{**GRID_ROW, "numberwesh": 5452}])
    db = FakeDb(customers=DB_CUSTOMERS, tractors=DB_TRACTORS)
    report = import_customer_tractor_prices(db=db)

    assert report.inserted == 1
    assert "5452" in report.adjustments[0][2]
    assert "7814" in report.adjustments[0][2]
    # The head number is never written: it is read from the tractor by JOIN.
    assert len(db.calls[0]) == 6


def test_the_grid_dry_run_writes_nothing(patch_reader):
    patch_reader([GRID_ROW])
    db = FakeDb(customers=DB_CUSTOMERS, tractors=DB_TRACTORS)
    report = import_customer_tractor_prices(db=db, dry_run=True)
    assert report.read == 1
    assert db.calls == []
