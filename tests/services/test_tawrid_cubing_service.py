"""Unit tests for the Tawrid cubing-sheet service, phase 5 (no real database).

The cubing sheet (``sallesHead`` / ``Sallesdata``) is a master→detail document
that records تكعيب (volume) only — there is no price anywhere. These pin what the
service must get right:

* ``next_sheet_no`` continues from MAX (the legacy numbers are 1..21 with no gaps,
  but a delete leaves a gap the count would reuse).
* one line's driver/plate is read from the tractor card, and only falls back to
  the stored snapshot for a deleted tractor.
* a line with no live active tractor is flagged deleted (45 of 125 legacy lines).
* the per-sheet totals — sum / average / max / zeros / deleted.
* ``add_line`` appends at ``MAX(line_seq)+1`` so order is stable.

The DB-backed guarantees (UNIQUE sheet_no, the FKs, ON DELETE CASCADE) live in
``schema/full_schema.sql`` and are covered by the end-to-end run, not here.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.review_data_service import TABLE_SPECS
from app.services.tawrid_cubing_service import (
    CubingLine,
    CubingTotals,
    TawridCubingService,
)

CUBING_ID = 1


class FakeDb:
    """Minimal ``Database`` stand-in that answers by matching the SQL text."""

    def __init__(self, *, max_no=0, exists=False, line_rows=None, totals_row=None,
                 max_seq=0, search_rows=None, count=0):
        self.max_no = max_no
        self.exists = exists
        self.line_rows = line_rows or []
        self.totals_row = totals_row
        self.max_seq = max_seq
        self.search_rows = search_rows or []
        self.count = count
        self.queries: list[str] = []
        self.params: list[list] = []

    def _rec(self, query, params):
        self.queries.append(" ".join(str(query).split()))
        self.params.append(list(params) if params else [])

    def fetch_one(self, query, params=None):
        self._rec(query, params)
        text = str(query)
        if "MAX(sheet_no)" in text:
            return {"n": self.max_no + 1}
        if "WHERE sheet_no" in text and "LIMIT 1" in text:
            return {"x": 1} if self.exists else None
        if "MAX(line_seq)" in text:
            return {"n": self.max_seq + 1}
        if "INSERT INTO tawrid_crusher_cubing_lines" in text:
            return {"line_id": 777}
        if "COUNT(*) AS n FROM tawrid_crusher_cubing_lines" in text:
            return {"n": self.count}
        if "line_count" in text:  # totals aggregate
            return self.totals_row
        if "FROM tawrid_crusher_cubing h" in text:  # for_cubing
            return {"cubing_id": CUBING_ID, "sheet_no": 15, "sheet_date": "2025-12-01",
                    "crusher_id": 3, "notes": "", "supplier_name": "الهدي", "supplier_code": 1}
        return None

    def fetch_all(self, query, params=None):
        self._rec(query, params)
        text = str(query)
        if "FROM tawrid_crusher_cubing_lines l" in text:
            return list(self.line_rows)
        if "GROUP BY" in text:  # search_cubing
            return list(self.search_rows)
        return []

    def execute(self, query, params=None):
        self._rec(query, params)


def service(**kwargs) -> TawridCubingService:
    return TawridCubingService(FakeDb(**kwargs))


# --- numbering ---------------------------------------------------------------

def test_next_sheet_no_continues_from_the_maximum():
    assert service(max_no=21).next_sheet_no() == 22


def test_next_sheet_no_query_counts_this_table_not_a_count():
    svc = service(max_no=5)
    svc.next_sheet_no()
    assert "MAX(sheet_no)" in svc._db.queries[-1]


def test_sheet_no_exists_is_true_when_taken():
    assert service(exists=True).sheet_no_exists(15) is True


def test_sheet_no_exists_is_false_for_a_blank():
    svc = service()
    assert svc.sheet_no_exists(None) is False
    assert svc._db.queries == []


def test_sheet_no_exists_can_exclude_the_row_being_edited():
    svc = service(exists=False)
    svc.sheet_no_exists(15, exclude_id=1)
    assert "cubing_id <> %s" in svc._db.queries[-1]


# --- the lines ---------------------------------------------------------------

def _line_row(**over):
    base = {
        "line_id": 1, "cubing_id": CUBING_ID, "line_seq": 1, "tractor_id": 7,
        "driver_name_snapshot": "قديم", "trailer_no_snapshot": "9999", "volume": Decimal("58"),
        "driver_name": "عمرو كمال", "trailer_no": "4925", "head_no": "4925", "is_active": True,
    }
    base.update(over)
    return base


def test_line_reads_the_driver_and_plate_from_the_live_card():
    line = service(line_rows=[_line_row()]).lines(CUBING_ID)[0]
    assert line.driver_name == "عمرو كمال"      # not the snapshot "قديم"
    assert line.trailer_no == "4925"
    assert line.is_deleted is False


def test_line_falls_back_to_the_snapshot_when_the_tractor_is_gone():
    row = _line_row(tractor_id=None, driver_name=None, trailer_no=None,
                    head_no=None, is_active=None)
    line = service(line_rows=[row]).lines(CUBING_ID)[0]
    assert line.driver_name == "قديم"           # the stored snapshot
    assert line.trailer_no == "9999"
    assert line.is_deleted is True


def test_a_موقوف_tractor_line_is_flagged_deleted():
    """A recovered/stopped tractor (is_active False) still counts as deleted."""
    line = service(line_rows=[_line_row(is_active=False)]).lines(CUBING_ID)[0]
    assert line.is_deleted is True


def test_lines_of_an_empty_id_are_empty_without_a_query():
    svc = service()
    assert svc.lines(None) == []
    assert svc._db.queries == []


# --- add / update / delete ---------------------------------------------------

def test_add_line_appends_at_the_next_sequence():
    svc = service(max_seq=3)
    new_id = svc.add_line(CUBING_ID, 7, Decimal("58"), "عمرو", "4925")
    assert new_id == 777
    insert = next(p for q, p in zip(svc._db.queries, svc._db.params)
                  if "INSERT INTO tawrid_crusher_cubing_lines" in q)
    # cubing_id, line_seq(=4), tractor_id, driver_snap, trailer_snap, volume
    assert insert[1] == 4
    assert insert[2] == 7
    assert insert[5] == Decimal("58")


def test_add_line_stores_null_for_a_blank_tractor():
    svc = service(max_seq=0)
    svc.add_line(CUBING_ID, "", 0)
    insert = next(p for q, p in zip(svc._db.queries, svc._db.params)
                  if "INSERT INTO tawrid_crusher_cubing_lines" in q)
    assert insert[2] is None


def test_update_line_volume_writes_only_the_volume():
    svc = service()
    svc.update_line_volume(5, Decimal("60"))
    q = svc._db.queries[-1]
    assert "UPDATE tawrid_crusher_cubing_lines SET volume" in q


def test_delete_line_removes_one_row():
    svc = service()
    svc.delete_line(5)
    assert "DELETE FROM tawrid_crusher_cubing_lines WHERE line_id" in svc._db.queries[-1]


# --- totals ------------------------------------------------------------------

def test_totals_compute_the_average_from_sum_and_count():
    row = {"line_count": 2, "total_volume": Decimal("118.5"),
           "max_volume": Decimal("60"), "zero_count": 0, "deleted_count": 1}
    totals = service(totals_row=row).totals(CUBING_ID)
    assert totals.total_volume == Decimal("118.5")
    assert totals.average_volume == Decimal("59.25")
    assert totals.max_volume == Decimal("60")
    assert totals.deleted_count == 1


def test_totals_of_an_empty_sheet_are_all_zero():
    row = {"line_count": 0, "total_volume": 0, "max_volume": 0,
           "zero_count": 0, "deleted_count": 0}
    totals = service(totals_row=row).totals(CUBING_ID)
    assert totals == CubingTotals(line_count=0, total_volume=Decimal("0"),
                                  average_volume=Decimal("0"), max_volume=Decimal("0"),
                                  zero_count=0, deleted_count=0)


def test_totals_of_an_empty_id_do_not_touch_the_database():
    svc = service()
    assert svc.totals(None) == CubingTotals()
    assert svc._db.queries == []


# --- search ------------------------------------------------------------------

def test_search_filters_by_sheet_number_or_crusher_name():
    svc = service(search_rows=[{"cubing_id": 1, "sheet_no": 15}])
    svc.search_cubing("الهدي")
    q = svc._db.queries[-1]
    assert "ILIKE" in q and "GROUP BY" in q


def test_empty_search_returns_recent_sheets_ordered():
    svc = service(search_rows=[{"cubing_id": 1, "sheet_no": 15}])
    svc.search_cubing("")
    assert "ORDER BY h.sheet_no DESC" in svc._db.queries[-1]


# --- the spec the screen is built from ---------------------------------------

def test_the_spec_uses_its_own_header_table():
    spec = TABLE_SPECS["tawrid_crusher_cubing"]
    assert spec.table_name == "tawrid_crusher_cubing"
    assert spec.primary_key == "cubing_id"


def test_the_spec_has_no_price_field_at_all():
    """The whole point: sallesHead/Sallesdata carry no price, so neither do we."""
    spec = TABLE_SPECS["tawrid_crusher_cubing"]
    names = {f.name for f in spec.fields}
    assert not any("price" in n for n in names)
    assert {"sheet_no", "sheet_date", "crusher_id", "notes"} <= names


def test_the_crusher_id_is_readonly_but_not_the_primary_key():
    """It is filled by the picker, and must still be written on save."""
    spec = TABLE_SPECS["tawrid_crusher_cubing"]
    crusher = next(f for f in spec.fields if f.name == "crusher_id")
    assert crusher.readonly is True
    assert spec.primary_key != "crusher_id"
