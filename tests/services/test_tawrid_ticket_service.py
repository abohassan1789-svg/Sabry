"""Unit tests for the البون service's crusher-side cubing lookups (phase 5 link).

The البون tractor picker gained a «جرارات الكسّارة» scope, and picking one of the
crusher's own tractors auto-fills ``res_volume`` (تكعيب الكسّارة) from the
تكعيب الكسّارات sheets. These pin the two service methods behind that, and that a
database without the cubing tables degrades to empty/None rather than raising.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tawrid_ticket_service import TawridTicketService


class FakeDb:
    def __init__(self, *, rows=None, volume_row=None, raise_on=None):
        self.rows = rows or []
        self.volume_row = volume_row
        self.raise_on = raise_on          # substring that makes a query raise
        self.queries: list[str] = []
        self.params: list[list] = []

    def _maybe_raise(self, text):
        if self.raise_on and self.raise_on in text:
            raise RuntimeError("relation does not exist")

    def fetch_all(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text); self.params.append(list(params or []))
        self._maybe_raise(text)
        return list(self.rows)

    def fetch_one(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text); self.params.append(list(params or []))
        self._maybe_raise(text)
        return self.volume_row


def service(**kwargs) -> TawridTicketService:
    return TawridTicketService(FakeDb(**kwargs))


# --- جرارات الكسّارة ----------------------------------------------------------

def test_crusher_tractors_query_joins_the_cubing_sheets():
    svc = service(rows=[{"tractor_id": 13, "driver_name": "احمد معروف"}])
    out = svc.crusher_tractor_picker_rows(4)
    assert out and out[0]["tractor_id"] == 13
    q = svc._db.queries[-1]
    assert "tawrid_crusher_cubing_lines" in q and "h.crusher_id = %s" in q
    assert "l.tractor_id IS NOT NULL" in q
    assert svc._db.params[-1] == [4]


def test_crusher_tractors_of_an_empty_crusher_touch_no_database():
    svc = service()
    assert svc.crusher_tractor_picker_rows(None) == []
    assert svc._db.queries == []


def test_crusher_tractors_survive_a_missing_cubing_table():
    svc = service(raise_on="tawrid_crusher_cubing_lines")
    assert svc.crusher_tractor_picker_rows(4) == []   # degrades, does not raise


# --- crusher volume (auto-fill for res_volume) -------------------------------

def test_crusher_volume_returns_the_pair_volume():
    svc = service(volume_row={"volume": Decimal("62.5")})
    assert svc.crusher_volume(4, 13) == Decimal("62.5")


def test_crusher_volume_takes_the_most_recent_sheet():
    svc = service(volume_row={"volume": Decimal("60")})
    svc.crusher_volume(4, 13)
    q = svc._db.queries[-1]
    assert "ORDER BY h.sheet_date DESC" in q and "LIMIT 1" in q


def test_crusher_volume_of_a_pair_with_no_cubing_row_is_none():
    assert service(volume_row=None).crusher_volume(4, 999) is None


def test_crusher_volume_of_an_empty_side_touches_no_database():
    svc = service()
    assert svc.crusher_volume(None, 13) is None
    assert svc.crusher_volume(4, None) is None
    assert svc._db.queries == []


def test_crusher_volume_survives_a_missing_cubing_table():
    svc = service(raise_on="tawrid_crusher_cubing", volume_row={"volume": Decimal("5")})
    assert svc.crusher_volume(4, 13) is None
