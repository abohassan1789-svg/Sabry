"""Unit tests for the Tawrid customers module, phase 2 (no real database).

Covers what phase 2 must get right:

* :class:`CustomerBalance` arithmetic — الرصيد = أول المدة + البونات − المحصّل,
  including the "movements not built yet" state the screen renders as ``—``.
* :class:`TawridCustomerService` probing for ``tawrid_tickets`` /
  ``tawrid_customer_receipts``, which later phases create. Until they exist the
  summary must report the opening balance only and never query them, and
  ``has_movement`` must answer 0 so a customer can still be deleted.
* The customer × tractor price grid: the read joins the tractor card (so the
  head number is never a stored copy — three of the 236 legacy ``CarCus`` rows
  had drifted), the picker excludes tractors already priced (which is what
  makes the UNIQUE constraint unreachable rather than trapped, as Access did
  with error 3022), and a blank money value becomes 0 rather than NULL.

The DB-backed guarantees (UNIQUE مسلسل / اسم العميل, UNIQUE (customer, tractor),
the CHECKs, and the FKs Access never had) live in ``schema/full_schema.sql``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.review_data_service import TABLE_SPECS, ReviewDataService
from app.services.tawrid_customer_service import (
    PRICES_TABLE,
    RECEIPTS_TABLE,
    TICKETS_TABLE,
    CustomerBalance,
    TawridCustomerService,
    TractorPrice,
)

CUSTOMER_ID = 5


class FakeDb:
    """Minimal ``Database`` stand-in that answers by matching the SQL text."""

    def __init__(self, *, opening="0", tickets=None, receipts=None, existing=(), rows=None):
        self.opening = opening
        self.tickets = tickets          # (count, sum) or None
        self.receipts = receipts        # sum or None
        self.existing = set(existing)   # table names that "exist"
        self.rows = rows or []
        self.queries: list[str] = []
        self.executed: list[tuple[str, list]] = []

    def _record(self, query):
        self.queries.append(" ".join(str(query).split()))

    def fetch_one(self, query, params=None):
        self._record(query)
        text = str(query)
        if "to_regclass" in text:
            name = str(params[0]).split(".")[-1]
            return {"oid": 1 if name in self.existing else None}
        if "FROM tawrid_customers" in text and "opening_balance" in text:
            return {"opening_balance": self.opening}
        if "MAX(customer_code)" in text:
            return {"next_code": 102}
        if TICKETS_TABLE in text and "COUNT(*) AS n" in text:
            count, total = self.tickets or (0, 0)
            return {"n": count, "s": total}
        if TICKETS_TABLE in text and "COUNT(*) AS c" in text:
            count, _total = self.tickets or (0, 0)
            return {"c": count}
        if RECEIPTS_TABLE in text and "COUNT(*) AS c" in text:
            return {"c": 3 if self.receipts else 0}
        if RECEIPTS_TABLE in text:
            return {"s": self.receipts or 0}
        if PRICES_TABLE in text and "COUNT(*)" in text:
            return {"c": len(self.rows)}
        if "RETURNING price_id" in text:
            return {"price_id": 99}
        raise AssertionError(f"unexpected query: {query}")

    def fetch_all(self, query, params=None):
        self._record(query)
        return list(self.rows)

    def execute(self, query, params=None):
        self._record(query)
        self.executed.append((" ".join(str(query).split()), list(params or [])))


# --- balance arithmetic -----------------------------------------------------

def test_balance_is_opening_plus_invoiced_minus_collected():
    balance = CustomerBalance(
        opening_balance=Decimal("297000"),
        tickets_count=168,
        invoiced=Decimal("1004120"),
        collected=Decimal("888590"),
        movements_available=True,
    )
    assert balance.balance == Decimal("412530")


def test_balance_of_an_untouched_customer_is_zero():
    assert CustomerBalance().balance == Decimal("0")
    assert CustomerBalance().movements_available is False


# --- probing for the movement tables ----------------------------------------

def test_summary_reports_opening_only_while_movement_tables_are_missing():
    db = FakeDb(opening="297000")
    balance = TawridCustomerService(db).for_customer(CUSTOMER_ID)

    assert balance.opening_balance == Decimal("297000")
    assert balance.balance == Decimal("297000")
    assert balance.movements_available is False
    assert not any(TICKETS_TABLE in q and "SUM" in q for q in db.queries)
    assert not any(RECEIPTS_TABLE in q and "SUM" in q for q in db.queries)


def test_summary_reads_both_sides_once_the_tables_exist():
    db = FakeDb(
        opening="297000",
        tickets=(168, "1004120"),
        receipts="888590",
        existing=(TICKETS_TABLE, RECEIPTS_TABLE),
    )
    balance = TawridCustomerService(db).for_customer(CUSTOMER_ID)

    assert balance.tickets_count == 168
    assert balance.invoiced == Decimal("1004120")
    assert balance.collected == Decimal("888590")
    assert balance.balance == Decimal("412530")
    assert balance.movements_available is True


def test_an_unknown_customer_yields_an_empty_summary_instead_of_raising():
    db = FakeDb(existing=(TICKETS_TABLE,))
    assert TawridCustomerService(db).for_customer(None) == CustomerBalance()
    assert db.queries == []


def test_next_code_continues_from_the_maximum_not_the_count():
    """Legacy numbering runs 5..101 with 52 gaps, so MAX+1 is the only safe rule."""
    assert TawridCustomerService(FakeDb()).next_code() == 102


# --- delete protection ------------------------------------------------------

def test_has_movement_is_zero_while_the_movement_tables_do_not_exist():
    """Nothing can reference the customer yet, so deletion must stay possible."""
    assert TawridCustomerService(FakeDb()).has_movement(CUSTOMER_ID) == 0


def test_has_movement_counts_tickets_and_receipts_together():
    db = FakeDb(tickets=(168, "0"), receipts="1", existing=(TICKETS_TABLE, RECEIPTS_TABLE))
    assert TawridCustomerService(db).has_movement(CUSTOMER_ID) == 171  # 168 + 3


# --- the customer × tractor price grid --------------------------------------

GRID_ROW = {
    "price_id": 49,
    "tractor_id": 11,
    "tractor_code": 3,
    "driver_name": "السعيد معروف",
    "trailer_no": "3581",
    "head_no": "7814",
    "load_volume": "60.50",
    "price_sen": "180.00",
    "price_raml": "0.00",
    "default_sen": "140.00",
    "default_raml": "0.00",
}


def test_grid_rows_read_the_plate_numbers_from_the_tractor_card():
    """CarCus stored its own copy of the head number and 3 rows went stale."""
    db = FakeDb(rows=[GRID_ROW])
    rows = TawridCustomerService(db).tractor_prices(CUSTOMER_ID)

    assert len(rows) == 1
    assert rows[0] == TractorPrice(
        price_id=49,
        tractor_id=11,
        tractor_code=3,
        driver_name="السعيد معروف",
        trailer_no="3581",
        head_no="7814",
        load_volume=Decimal("60.50"),
        price_sen=Decimal("180.00"),
        price_raml=Decimal("0.00"),
        default_sen=Decimal("140.00"),
        default_raml=Decimal("0.00"),
    )
    assert "JOIN tawrid_tractors" in db.queries[0]


def test_grid_of_an_unsaved_customer_is_empty_and_queries_nothing():
    db = FakeDb(rows=[GRID_ROW])
    assert TawridCustomerService(db).tractor_prices(None) == []
    assert db.queries == []


def test_the_picker_excludes_tractors_already_priced_for_this_customer():
    """This is what makes the UNIQUE (customer, tractor) rule unreachable."""
    db = FakeDb(rows=[{"tractor_id": 11, "driver_name": "السعيد معروف"}])
    TawridCustomerService(db).available_tractors(CUSTOMER_ID)

    query = db.queries[0]
    assert "NOT EXISTS" in query
    assert PRICES_TABLE in query
    assert "t.is_active" in query


def test_adding_a_row_writes_the_seeded_rates():
    db = FakeDb()
    price_id = TawridCustomerService(db).add_tractor_price(CUSTOMER_ID, 11, 60.5, 180, 0)

    assert price_id == 99
    assert f"INSERT INTO {PRICES_TABLE}" in db.queries[0]


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_grid_value_is_stored_as_zero_not_null(blank):
    """Every price column is NOT NULL DEFAULT 0; blank means nothing, not unknown."""
    db = FakeDb()
    TawridCustomerService(db).update_tractor_price(49, blank, blank, blank)

    _query, params = db.executed[0]
    assert params[:3] == [Decimal("0"), Decimal("0"), Decimal("0")]


def test_a_non_numeric_grid_value_is_rejected_with_a_readable_message():
    with pytest.raises(ValueError, match="قيمة رقمية غير صحيحة"):
        TawridCustomerService(FakeDb()).update_tractor_price(49, "abc", 0, 0)


def test_deleting_a_grid_row_targets_only_that_row():
    db = FakeDb()
    TawridCustomerService(db).delete_tractor_price(49)

    query, params = db.executed[0]
    assert query == f"DELETE FROM {PRICES_TABLE} WHERE price_id = %s"
    assert params == [49]


# --- the TableSpec ----------------------------------------------------------

def test_the_customers_spec_is_a_brand_new_table_not_the_existing_one():
    """Rule from the user: never reuse the existing customers table or screen."""
    spec = TABLE_SPECS["tawrid_customers"]
    assert spec.table_name == "tawrid_customers"
    assert spec.table_name != TABLE_SPECS["customers"].table_name
    assert spec.key.startswith("tawrid_")


def test_the_ten_item_prices_are_hidden_from_the_base_form_panel():
    """The screen renders them itself inside the «أسعار الأصناف» tab."""
    spec = TABLE_SPECS["tawrid_customers"]
    prices = [f for f in spec.fields if f.name.startswith("price_")]
    assert len(prices) == 10
    assert all(f.hidden_on_form for f in prices)
    assert all(f.data_type == "float" for f in prices)


def test_the_opening_date_femp_never_showed_is_on_the_form():
    spec = TABLE_SPECS["tawrid_customers"]
    opening_date = next(f for f in spec.fields if f.name == "opening_date")
    assert opening_date.hidden_on_form is False
    assert opening_date.data_type == "date"


def test_the_sen3_column_carries_the_label_the_users_actually_read():
    spec = TABLE_SPECS["tawrid_customers"]
    field = next(f for f in spec.fields if f.name == "price_sen_ataqa")
    assert field.label == "سن عتاقة"


def test_a_tractor_priced_for_some_customer_cannot_be_deleted_silently():
    """The FK is ON DELETE RESTRICT; this turns it into a readable sentence."""
    children = ReviewDataService._CHILD_RELATIONSHIPS["tawrid_tractors"]
    tables = {table for table, _column, _message in children}
    assert PRICES_TABLE in tables
