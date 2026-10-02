"""Unit tests for rebuilding the tractor cards Access deleted (no Access, no DB).

``tbgrarat`` lost nine rows, but nothing that referenced them was cleaned up —
Access enforced no foreign keys. The tickets still name them: 264 rows of
``TBBOOn`` carry the driver's name in ``namemand`` and his plate in
``numberwesh``, and 53 vouchers in ``SanadCAR`` point at them too.

Those cards have to come back, or neither the 12 price-grid rows nor the 264
tickets can ever be imported. What this pins down is that the recovery states
what it did rather than guessing:

* the name and plate are the most frequent values on that tractor's own tickets,
* a ``namemand`` that is only digits (``22222``) is NOT a name and must not be
  stored as one,
* a plate recorded as ``0`` means "none", not a tractor with plate zero,
* recovered cards come across موقوف so they never appear in the tractor picker
  for new work, and
* re-running never creates a second card for the same Access id.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.migrations.tawrid_import import (
    COLUMN_ORDER,
    _is_a_real_name,
    _most_common,
    import_recovered_tractors,
)

LIVE = [{"id": 11}, {"id": 13}]


def ticket(tractor_id, name="تامر ماجد", wesh=5375):
    return {"maatora_id": tractor_id, "namemand": name, "numberwesh": wesh,
            "date123": date(2025, 1, 5)}


class FakeReader:
    """Answers the three queries the recovery runs, by matching the SQL text."""

    def __init__(self, live, tickets, vouchers):
        self.live = live
        self.tickets = tickets
        self.vouchers = vouchers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def rows(self, query):
        text = str(query)
        if "FROM tbgrarat" in text:
            return iter(self.live)
        if "TBBOOn" in text:
            return iter(self.tickets)
        if "SanadCAR" in text:
            return iter(self.vouchers)
        raise AssertionError(f"unexpected query: {query}")


class FakeDb:
    def __init__(self, next_code=45, existing=()):
        self.next_code = next_code
        self.existing = list(existing)
        self.calls = []

    def fetch_one(self, query, params=None):
        if "MAX(tractor_code)" in str(query):
            return {"c": self.next_code}
        self.calls.append(params)
        return {"inserted": True}

    def fetch_all(self, query, params=None):
        return [{"legacy_id": legacy_id} for legacy_id in self.existing]


@pytest.fixture
def patch_reader(monkeypatch):
    def install(tickets, vouchers=(), live=LIVE):
        # The reader yields dicts, one per row — same shape as pyodbc gives.
        rows = [{"Gararid": legacy_id} for legacy_id in vouchers]
        monkeypatch.setattr(
            "app.migrations.tawrid_import.AccessReader",
            lambda *a, **k: FakeReader(live, tickets, rows),
        )
    return install


def written(db):
    """The insert params as a dict, so tests read by column name."""
    return [dict(zip(COLUMN_ORDER, params)) for params in db.calls]


# --- the small helpers ------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("تامر ماجد", True),
    ("Ahmed", True),
    ("22222", False),
    ("6565656", False),
    ("", False),
    ("   ", False),
])
def test_a_name_needs_at_least_one_letter(text, expected):
    assert _is_a_real_name(text) is expected


def test_most_common_returns_the_value_and_its_count():
    assert _most_common(["5375"] * 3 + ["3762"]) == ("5375", 3)


def test_most_common_ignores_blanks_and_the_zero_plate():
    """Access stored an unset plate as the integer zero."""
    assert _most_common(["0", "0", None, "", "4743"]) == ("4743", 1)
    assert _most_common(["0", None, ""]) == (None, 0)


# --- the recovery -----------------------------------------------------------

def test_a_tractor_still_in_tbgrarat_is_not_recovered(patch_reader):
    patch_reader([ticket(11), ticket(13)])
    db = FakeDb()
    report = import_recovered_tractors(db=db)
    assert report.read == 0
    assert db.calls == []


def test_the_name_and_plate_come_from_the_tickets(patch_reader):
    patch_reader([ticket(27)] * 175)
    db = FakeDb()
    report = import_recovered_tractors(db=db)

    assert report.read == 1
    assert report.inserted == 1
    card = written(db)[0]
    assert card["legacy_id"] == 27
    assert card["driver_name"] == "تامر ماجد"
    assert card["head_no"] == "5375"


def test_the_most_frequent_plate_wins_and_the_count_is_reported(patch_reader):
    patch_reader([ticket(27, wesh=5375)] * 141 + [ticket(27, wesh=3762)] * 34)
    db = FakeDb()
    report = import_recovered_tractors(db=db)

    assert written(db)[0]["head_no"] == "5375"
    assert any("141 بون من أصل 175" in note for _id, _name, note in report.adjustments)


def test_a_numeric_namemand_is_not_stored_as_a_name(patch_reader):
    """Ticket 34 carries «22222» — a number someone typed, not a driver."""
    patch_reader([ticket(34, name="22222", wesh=0)] * 40)
    db = FakeDb()
    report = import_recovered_tractors(db=db)

    card = written(db)[0]
    assert card["driver_name"] == "جرار محذوف 34"
    assert card["head_no"] is None      # plate 0 means none
    assert any("مفيش اسم في البونات" in note for _id, _name, note in report.adjustments)


def test_recovered_cards_are_stopped_not_active(patch_reader):
    """They carry history; they must never show up for new work."""
    patch_reader([ticket(27)])
    db = FakeDb()
    import_recovered_tractors(db=db)
    assert written(db)[0]["is_active"] is False


def test_a_recovered_card_carries_no_invented_money_or_trailer(patch_reader):
    patch_reader([ticket(27)])
    db = FakeDb()
    import_recovered_tractors(db=db)
    card = written(db)[0]
    assert card["price_sen"] == Decimal("0")
    assert card["price_raml"] == Decimal("0")
    assert card["opening_balance"] == Decimal("0")
    assert card["opening_date"] is None
    # A trailer number is never recorded on a ticket, so it stays unknown.
    assert card["trailer_no"] is None


def test_codes_continue_after_the_highest_existing_one(patch_reader):
    patch_reader([ticket(27), ticket(46, name="حسن ماهر الشرقاوي", wesh=6581)])
    db = FakeDb(next_code=45)
    import_recovered_tractors(db=db)

    assert [card["tractor_code"] for card in written(db)] == [45, 46]


def test_the_voucher_count_is_reported_so_a_human_can_judge(patch_reader):
    patch_reader([ticket(27)] * 175, vouchers=[27] * 50)
    report = import_recovered_tractors(db=FakeDb())
    assert any("175 بون و50 سند صرف" in note for _id, _name, note in report.adjustments)


def test_an_already_recovered_card_is_skipped_not_duplicated(patch_reader):
    patch_reader([ticket(27)])
    db = FakeDb(existing=[27])
    report = import_recovered_tractors(db=db)

    assert report.skipped == 1
    assert report.inserted == 0
    assert db.calls == []


def test_dry_run_reports_but_writes_nothing(patch_reader):
    patch_reader([ticket(27)])
    db = FakeDb()
    report = import_recovered_tractors(db=db, dry_run=True)
    assert report.read == 1
    assert db.calls == []
    assert report.adjustments  # it still says what it would have done


def test_tickets_with_no_tractor_at_all_are_ignored(patch_reader):
    patch_reader([ticket(None), ticket(0), ticket(27)])
    db = FakeDb()
    report = import_recovered_tractors(db=db)
    assert report.read == 1
