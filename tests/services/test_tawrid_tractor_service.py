"""Unit tests for the Tawrid tractors module, phase 1 (no real database).

Covers the two things phase 1 must get right:

* :class:`TractorBalance` arithmetic — الرصيد = أول المدة + النقلات − المدفوع,
  including the "movements not built yet" state the screen renders as ``—``.
* :class:`TawridTractorService` probing for ``tawrid_tickets`` /
  ``tawrid_tractor_payments``, which phases 5 and 6 create. Until they exist the
  summary must report the opening balance only, and must never query them.

The DB-backed guarantees (UNIQUE مسلسل / اسم السائق, CHECK on prices, text plate
numbers, boolean round-trip) are enforced by constraints in
``schema/full_schema.sql`` and exercised against the live database.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.review_data_service import TABLE_SPECS, FieldSpec, ReviewDataService
from app.services.tawrid_tractor_service import (
    PAYMENTS_TABLE,
    TICKETS_TABLE,
    TawridTractorService,
    TractorBalance,
)


class FakeDb:
    """Minimal ``Database`` stand-in that answers by matching the SQL text."""

    def __init__(self, *, opening="0", tickets=None, payments=None, existing=()):
        self.opening = opening
        self.tickets = tickets            # (count, sum) or None
        self.payments = payments          # sum or None
        self.existing = set(existing)     # table names that "exist"
        self.queries: list[str] = []

    def fetch_one(self, query, params=None):
        self.queries.append(" ".join(str(query).split()))
        if "to_regclass" in str(query):
            name = str(params[0]).split(".")[-1]
            return {"oid": 1 if name in self.existing else None}
        if "FROM tawrid_tractors" in str(query) and "opening_balance" in str(query):
            return {"opening_balance": self.opening}
        if TICKETS_TABLE in str(query):
            count, total = self.tickets or (0, 0)
            return {"n": count, "s": total}
        if PAYMENTS_TABLE in str(query):
            return {"s": self.payments or 0}
        if "MAX(tractor_code)" in str(query):
            return {"next_code": 7}
        raise AssertionError(f"unexpected query: {query}")


# --- balance arithmetic -----------------------------------------------------

def test_balance_is_opening_plus_earned_minus_paid():
    balance = TractorBalance(
        opening_balance=Decimal("209816"),
        trips_count=61,
        earned=Decimal("88430"),
        paid=Decimal("243148"),
        movements_available=True,
    )
    assert balance.balance == Decimal("55098")


def test_balance_can_go_negative_when_overpaid():
    balance = TractorBalance(opening_balance=Decimal("0"), paid=Decimal("500"),
                             movements_available=True)
    assert balance.balance == Decimal("-500")


def test_empty_balance_is_all_zero_and_marked_unavailable():
    balance = TractorBalance()
    assert balance.balance == Decimal("0")
    assert balance.movements_available is False


# --- service ----------------------------------------------------------------

def test_missing_tractor_id_yields_zero_without_touching_the_database():
    db = FakeDb()
    assert TawridTractorService(db).for_tractor(None) == TractorBalance()
    assert db.queries == []


def test_reports_opening_only_while_movement_tables_do_not_exist():
    """Phase 1 state: the البون / سندات tables are not built yet."""
    db = FakeDb(opening="209816")
    balance = TawridTractorService(db).for_tractor(3)

    assert balance.opening_balance == Decimal("209816")
    assert balance.balance == Decimal("209816")
    assert balance.movements_available is False
    assert balance.trips_count == 0
    # It must not have tried to read tables that do not exist.
    assert not any(TICKETS_TABLE in q and "to_regclass" not in q for q in db.queries)
    assert not any(PAYMENTS_TABLE in q and "to_regclass" not in q for q in db.queries)


def test_sums_movements_once_both_tables_exist():
    db = FakeDb(opening="209816", tickets=(61, "88430"), payments="243148",
                existing=(TICKETS_TABLE, PAYMENTS_TABLE))
    balance = TawridTractorService(db).for_tractor(3)

    assert balance.trips_count == 61
    assert balance.earned == Decimal("88430")
    assert balance.paid == Decimal("243148")
    assert balance.balance == Decimal("55098")
    assert balance.movements_available is True


def test_handles_only_one_movement_table_existing():
    """Phase 5 may land before phase 6; the summary must still be usable."""
    db = FakeDb(opening="100", tickets=(2, "300"), existing=(TICKETS_TABLE,))
    balance = TawridTractorService(db).for_tractor(3)

    assert balance.earned == Decimal("300")
    assert balance.paid == Decimal("0")
    assert balance.balance == Decimal("400")
    assert balance.movements_available is True


def test_next_code_follows_the_highest_existing_code():
    assert TawridTractorService(FakeDb()).next_code() == 7


# --- table spec -------------------------------------------------------------

def test_spec_mirrors_the_access_screen_fields():
    spec = TABLE_SPECS["tawrid_tractors"]
    assert spec.table_name == "tawrid_tractors"
    assert spec.primary_key == "tractor_id"
    labels = [f.label for f in spec.fields]
    for expected in ("مسلسل", "إسم السائق", "رقم المقطورة", "رقم الوش",
                     "سعر السن", "سعر الرمل", "رصيد أول المدة"):
        assert expected in labels, expected


def test_plate_numbers_are_text_not_numbers():
    """They are identifiers; '0345' and Arabic-letter plates must survive."""
    spec = TABLE_SPECS["tawrid_tractors"]
    by_name = {f.name: f for f in spec.fields}
    assert by_name["trailer_no"].data_type == "text"
    assert by_name["head_no"].data_type == "text"


def test_plate_numbers_are_searchable():
    assert "trailer_no" in TABLE_SPECS["tawrid_tractors"].search_columns
    assert "head_no" in TABLE_SPECS["tawrid_tractors"].search_columns


def test_is_active_is_not_required_so_stopped_is_saveable():
    """``required`` rejects any falsey value, which would reject موقوف (False)."""
    by_name = {f.name: f for f in TABLE_SPECS["tawrid_tractors"].fields}
    assert by_name["is_active"].data_type == "bool"
    assert by_name["is_active"].required is False


# --- boolean coercion (added for this module) -------------------------------

@pytest.mark.parametrize("text,expected", [
    ("نشط", True), ("موقوف", False),
    ("true", True), ("false", False),
    ("1", True), ("0", False),
])
def test_bool_field_coercion_round_trip(text, expected):
    field = FieldSpec("is_active", "الحالة", "bool")
    assert ReviewDataService._coerce_value(None, field, text) is expected


def test_bool_field_rejects_nonsense_with_an_arabic_message():
    field = FieldSpec("is_active", "الحالة", "bool")
    with pytest.raises(ValueError, match="الحالة"):
        ReviewDataService._coerce_value(None, field, "ربما")
