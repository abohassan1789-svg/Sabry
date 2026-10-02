"""Tests for the phase-4 data import: Access ``TBBOOn`` → ``tawrid_tickets``.

A fake reader yields the real legacy shapes and a fake DB records the upserts, so
these pin the decisions the importer makes on its own:

* **Item mapping** — free-text ``productName`` → the catalogue, aliasing the
  legacy spellings (سن+ / سن 3 / س1 / س 2) and ignoring spaces; an unknown name
  leaves ``item_id`` NULL.
* **Discount** — ``TBBOOn.disc`` is a fraction, stored as a percent (× 100).
* **Placeholders** — a deleted/missing customer or crusher lands on the موقوف
  «محذوف» card, so no ticket is dropped and the NOT NULL FKs resolve.
* **``ticket_no`` > 0** — a legacy ``number1`` of 0 is renumbered to MAX+1.
* The five money totals are GENERATED, so they are never in the insert.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.migrations import tawrid_import
from app.migrations.tawrid_import import (
    _item_norm,
    _ITEM_ALIASES,
    _ticket_number_overrides,
    import_tickets,
)


class FakeReader:
    def __init__(self, rows):
        self._rows = rows

    def __call__(self, access_path=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def rows(self, query):
        return list(self._rows) if "TBBOOn" in str(query) else []


class FakeDb:
    def __init__(self, *, customers=None, suppliers=None, tractors=None, items=None):
        self.customers = customers or {}
        self.suppliers = suppliers or {}
        self.tractors = tractors or {}
        self.items = items or {}     # item_name -> item_id
        self.ticket_upserts: list[list] = []
        self.created_customer = False
        self.created_supplier = False

    def fetch_all(self, query, params=None):
        t = str(query)
        if "UPDATE tawrid_customers SET discount_percent" in t:
            return []
        if "FROM tawrid_customers" in t:
            return [{"legacy_id": k, "customer_id": v} for k, v in self.customers.items()]
        if "FROM tawrid_suppliers" in t:
            return [{"legacy_id": k, "supplier_id": v} for k, v in self.suppliers.items()]
        if "FROM tawrid_tractors" in t:
            return [{"legacy_id": k, "tractor_id": v} for k, v in self.tractors.items()]
        if "FROM tawrid_items" in t:
            return [{"item_id": v, "item_name": k} for k, v in self.items.items()]
        return []

    def fetch_one(self, query, params=None):
        t = str(query)
        if "WHERE legacy_id = %s" in t and "tawrid_customers" in t:
            return None
        if "WHERE legacy_id = %s" in t and "tawrid_suppliers" in t:
            return None
        if "MAX(customer_code)" in t:
            return {"c": 102}
        if "MAX(supplier_code)" in t:
            return {"c": 87}
        if "INSERT INTO tawrid_customers" in t:
            self.created_customer = True
            return {"customer_id": 500}
        if "INSERT INTO tawrid_suppliers" in t:
            self.created_supplier = True
            return {"supplier_id": 600}
        if "INSERT INTO tawrid_tickets" in t:
            self.ticket_upserts.append(list(params))
            return {"inserted": True}
        return None

    def execute(self, query, params=None):
        pass


ITEMS = {"سن 1": 1, "سن 2": 2, "سن عتاقة": 3, "رملة": 8, "سن +": 9}


def _row(**over):
    base = {
        "id": 100, "number1": 10, "NumberEissal": "504", "date123": "2025-01-04",
        "cus_id": 1, "res_id": 1, "maatora_id": 1,
        "productName": "سن 1", "typeharka": "سن",
        "PriceCus": 80, "Tak3ib": 60, "Priceres": 55, "Tak3ibres": 59,
        "Pricemand": 15, "disc": 0.0,
    }
    base.update(over)
    return base


@pytest.fixture
def patch_reader(monkeypatch):
    def _apply(rows):
        monkeypatch.setattr(tawrid_import, "AccessReader", FakeReader(rows))
    return _apply


def _db():
    return FakeDb(customers={1: 11}, suppliers={1: 21}, tractors={1: 31}, items=ITEMS)


# --- pure helpers ------------------------------------------------------------

def test_item_norm_ignores_spaces():
    assert _item_norm("سن +") == _item_norm("سن+")


def test_the_aliases_cover_the_measured_legacy_spellings():
    assert set(_ITEM_ALIASES) == {_item_norm("سن 3"), _item_norm("س1"), _item_norm("س 2")}


def test_zero_ticket_number_is_renumbered_past_the_max():
    rows = [_row(id=1, number1=10), _row(id=2, number1=0), _row(id=3, number1=4117)]
    assert _ticket_number_overrides(rows) == {2: 4118}


def test_only_illegal_numbers_are_overridden():
    rows = [_row(id=1, number1=10), _row(id=2, number1=4117)]
    assert _ticket_number_overrides(rows) == {}


# --- item mapping (through the importer) --------------------------------------

def _item_of(db, ticket_id):
    row = next(p for p in db.ticket_upserts if p[0] == ticket_id)
    return row[7]   # item_id is the 8th param


def test_exact_and_space_insensitive_names_map(patch_reader):
    patch_reader([_row(id=1, productName="سن 1"), _row(id=2, productName="سن+")])
    db = _db(); import_tickets(db=db)
    assert _item_of(db, 1) == 1
    assert _item_of(db, 2) == 9        # «سن+» → catalogue «سن +»


def test_the_legacy_aliases_map_to_the_right_item(patch_reader):
    patch_reader([_row(id=1, productName="سن 3"), _row(id=2, productName="س1"),
                  _row(id=3, productName="س 2")])
    db = _db(); import_tickets(db=db)
    assert _item_of(db, 1) == 3        # سن 3 → سن عتاقة
    assert _item_of(db, 2) == 1        # س1 → سن 1
    assert _item_of(db, 3) == 2        # س 2 → سن 2


def test_an_unknown_or_empty_name_leaves_item_id_null(patch_reader):
    patch_reader([_row(id=1, productName=""), _row(id=2, productName="حاجة غريبة")])
    db = _db(); import_tickets(db=db)
    assert _item_of(db, 1) is None and _item_of(db, 2) is None


# --- discount, name kept, placeholders ---------------------------------------

def test_discount_fraction_becomes_a_percent(patch_reader):
    patch_reader([_row(id=1, disc=0.01)])
    db = _db(); import_tickets(db=db)
    row = db.ticket_upserts[0]
    assert row[12] == Decimal("1.00")   # discount_percent = disc × 100


def test_the_printed_product_name_is_kept_verbatim(patch_reader):
    patch_reader([_row(id=1, productName="سن+", typeharka="سن")])
    db = _db(); import_tickets(db=db)
    row = db.ticket_upserts[0]
    assert row[8] == "سن+"              # item_name keeps the legacy spelling
    assert row[9] == "سن"


def test_a_deleted_customer_lands_on_the_placeholder(patch_reader):
    patch_reader([_row(id=1, cus_id=999)])          # 999 not in the map
    db = _db(); import_tickets(db=db)
    assert db.created_customer is True
    assert db.ticket_upserts[0][4] == 500           # customer_id = placeholder


def test_a_missing_customer_lands_on_the_placeholder(patch_reader):
    patch_reader([_row(id=1, cus_id=None)])
    db = _db(); import_tickets(db=db)
    assert db.ticket_upserts[0][4] == 500


def test_deleted_crusher_22_lands_on_the_placeholder(patch_reader):
    patch_reader([_row(id=1, res_id=22)])           # 22 not in the map
    db = _db(); import_tickets(db=db)
    assert db.created_supplier is True
    assert db.ticket_upserts[0][5] == 600           # supplier_id = placeholder


def test_an_unresolved_tractor_is_left_null(patch_reader):
    patch_reader([_row(id=1, maatora_id=777)])      # 777 not in the map
    db = _db(); import_tickets(db=db)
    assert db.ticket_upserts[0][6] is None          # tractor_id nullable


def test_the_generated_totals_are_never_written(patch_reader):
    patch_reader([_row(id=1)])
    db = _db(); import_tickets(db=db)
    # 16 base params only — no total_cus/amount_dis/safi_cus/total_res/total_man.
    assert len(db.ticket_upserts[0]) == 16
