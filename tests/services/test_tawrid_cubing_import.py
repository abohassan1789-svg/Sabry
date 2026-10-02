"""Tests for the phase-5 import: ``sallesHead``/``Sallesdata`` → the cubing tables.

No real Access file and no database — a fake reader yields the real legacy shapes
and a fake DB records the upserts, so these pin the two decisions the importer
makes on its own:

* **Orphan headers get a موقوف «كسّارة محذوفة» placeholder.** 3 sheets have no
  crusher and 1 points at deleted crusher 22; ``crusher_id`` is NOT NULL, so all
  four must resolve to the one shared placeholder rather than being dropped.
* **A deleted tractor's line is kept with a snapshot,** not dropped: ``tractor_id``
  NULL and the name/plate from ``namemand`` / ``numberwesh``. A live tractor
  resolves to its card and stores no snapshot.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.migrations import tawrid_import
from app.migrations.tawrid_import import (
    _DELETED_CRUSHER_LEGACY_ID,
    import_cubing_headers,
    import_cubing_lines,
)


class FakeReader:
    """Context-manager stand-in for AccessReader yielding configured rows."""

    def __init__(self, rows_by_marker):
        self._rows = rows_by_marker

    def __call__(self, access_path=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def rows(self, query):
        text = str(query)
        if "sallesHead" in text:
            return list(self._rows.get("headers", []))
        if "Sallesdata" in text:
            return list(self._rows.get("lines", []))
        return []


class FakeDb:
    def __init__(self, *, suppliers=None, tractors=None, headers=None, placeholder_exists=False):
        self.suppliers = suppliers or {}     # legacy_id -> supplier_id
        self.tractors = tractors or {}       # legacy_id -> (tractor_id, name)
        self.headers = headers or {}         # legacy_id -> cubing_id
        self.placeholder_exists = placeholder_exists
        self.header_upserts: list[list] = []
        self.line_upserts: list[list] = []
        self.created_placeholder = False

    def fetch_all(self, query, params=None):
        text = str(query)
        if "FROM tawrid_suppliers" in text and "legacy_id" in text:
            return [{"legacy_id": k, "supplier_id": v} for k, v in self.suppliers.items()]
        if "FROM tawrid_tractors" in text and "legacy_id" in text:
            return [{"legacy_id": k, "tractor_id": v[0], "driver_name": v[1]}
                    for k, v in self.tractors.items()]
        if "FROM tawrid_crusher_cubing" in text and "legacy_id" in text:
            return [{"legacy_id": k, "cubing_id": v} for k, v in self.headers.items()]
        return []

    def fetch_one(self, query, params=None):
        text = str(query)
        if "WHERE legacy_id = %s" in text and "tawrid_suppliers" in text:
            if self.placeholder_exists:
                return {"supplier_id": 900}
            return None
        if "MAX(supplier_code)" in text:
            return {"c": 88}
        if "INSERT INTO tawrid_suppliers" in text:
            self.created_placeholder = True
            return {"supplier_id": 900}
        if "INSERT INTO tawrid_crusher_cubing_lines" in text:
            self.line_upserts.append(list(params))
            return {"inserted": True}
        if "INSERT INTO tawrid_crusher_cubing" in text:
            self.header_upserts.append(list(params))
            return {"inserted": True}
        return None

    def execute(self, query, params=None):
        pass


@pytest.fixture
def patch_reader(monkeypatch):
    def _apply(rows):
        monkeypatch.setattr(tawrid_import, "AccessReader", FakeReader(rows))
    return _apply


# --- headers -----------------------------------------------------------------

HEADERS = [
    {"id": 1, "number1": 15, "inv_date": "2025-12-01", "productNam": 1},   # الهدي
    {"id": 16, "number1": 16, "inv_date": "2025-06-01", "productNam": None},  # no crusher
    {"id": 18, "number1": 18, "inv_date": "2025-06-02", "productNam": 22},   # deleted crusher
]


def test_a_resolvable_crusher_is_linked_directly(patch_reader):
    patch_reader({"headers": HEADERS})
    db = FakeDb(suppliers={1: 101})
    import_cubing_headers(db=db)
    # header for legacy id 1 -> crusher_id 101 (position 4 in the upsert params)
    row = next(p for p in db.header_upserts if p[0] == 1)
    assert row[3] == 101


def test_orphan_headers_share_one_placeholder_crusher(patch_reader):
    patch_reader({"headers": HEADERS})
    db = FakeDb(suppliers={1: 101})
    import_cubing_headers(db=db)
    assert db.created_placeholder is True
    orphan_crusher_ids = {p[3] for p in db.header_upserts if p[0] in (16, 18)}
    assert orphan_crusher_ids == {900}          # both on the one placeholder


def test_placeholder_is_reused_when_it_already_exists(patch_reader):
    patch_reader({"headers": HEADERS})
    db = FakeDb(suppliers={1: 101}, placeholder_exists=True)
    import_cubing_headers(db=db)
    assert db.created_placeholder is False
    assert {p[3] for p in db.header_upserts if p[0] in (16, 18)} == {900}


def test_the_placeholder_uses_the_reserved_sentinel_legacy_id():
    assert _DELETED_CRUSHER_LEGACY_ID < 0     # never collides with a pruduct.id


# --- lines -------------------------------------------------------------------

LINES = [
    {"id": 4, "inv_id": 1, "maatora_id": 7, "numberwesh": 4925, "namemand": "عمرو كمال", "tak3ib": 58.0},
    {"id": 6, "inv_id": 1, "maatora_id": 999, "numberwesh": 111, "namemand": "سائق محذوف", "tak3ib": 59.0},
]


def test_a_live_tractor_line_links_to_the_card_without_a_snapshot(patch_reader):
    patch_reader({"lines": LINES})
    db = FakeDb(headers={1: 500}, tractors={7: (70, "عمرو كمال")})
    import_cubing_lines(db=db)
    row = next(p for p in db.line_upserts if p[0] == 4)
    # params: legacy_id, cubing_id, line_seq, tractor_id, driver_snap, trailer_snap, volume
    assert row[1] == 500 and row[3] == 70
    assert row[4] == "" and row[5] == ""
    assert row[6] == Decimal("58")


def test_a_deleted_tractor_line_is_kept_with_a_name_snapshot(patch_reader):
    patch_reader({"lines": LINES})
    db = FakeDb(headers={1: 500}, tractors={7: (70, "عمرو كمال")})
    import_cubing_lines(db=db)
    row = next(p for p in db.line_upserts if p[0] == 6)
    assert row[3] is None                      # no tractor link
    assert row[4] == "سائق محذوف"              # name preserved
    assert row[5] == "111"                     # plate preserved
    assert row[6] == Decimal("59")


def test_line_sequence_increments_within_a_sheet(patch_reader):
    patch_reader({"lines": LINES})
    db = FakeDb(headers={1: 500}, tractors={7: (70, "عمرو كمال")})
    import_cubing_lines(db=db)
    seqs = {p[0]: p[2] for p in db.line_upserts}
    assert seqs == {4: 1, 6: 2}


def test_no_line_is_dropped_even_when_its_tractor_is_gone(patch_reader):
    patch_reader({"lines": LINES})
    db = FakeDb(headers={1: 500}, tractors={})   # every tractor "deleted"
    report = import_cubing_lines(db=db)
    assert len(db.line_upserts) == 2
    assert report.skipped == 0
