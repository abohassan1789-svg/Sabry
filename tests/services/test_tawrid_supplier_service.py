"""Unit tests for the Tawrid crushers/suppliers module, phase 3 (no real database).

Covers what phase 3 must get right:

* :class:`SupplierBalance` arithmetic — الرصيد = أول المدة + البونات − المدفوع.
  The sign is the mirror of the customer's: a positive balance is what *we owe
  the crusher*. Overpayment is real («مكة ستون» is at −11,125 in the legacy
  data) and must not be clamped to zero.
* :class:`TawridSupplierService` probing for ``tawrid_tickets`` /
  ``tawrid_supplier_payments``, which later phases create. Until they exist the
  summary must report the opening balance only and never query them, and
  ``has_movement`` must answer 0 so a crusher can still be deleted.
* ``next_code`` counting **this** table's maximum. That is the whole fix for the
  worst defect on ``Fproduct``, whose مسلسل defaulted to
  ``DMax("[number1]","fanii")+1`` — the *customers* table — and produced 3
  duplicate codes inside ``pruduct`` plus 5 shared with a customer.
* ``picker_rows`` ordering stopped cards last: 7 of the 23 legacy cards have no
  movement of any kind and used to sit in the combo beside «الهدي», which
  carries 2,389 of the 4,072 tickets.
* ``priced_item_count`` — the legacy price grid is 76% empty (56 of 230 cells),
  so "how many of the ten" is worth stating on the panel heading.

The DB-backed guarantees (UNIQUE مسلسل / اسم المورد, the CHECKs, and the FKs
Access never had) live in ``schema/full_schema.sql``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.review_data_service import TABLE_SPECS
from app.services.tawrid_supplier_service import (
    PAYMENTS_TABLE,
    PRICE_COLUMNS,
    TICKETS_TABLE,
    SupplierBalance,
    TawridSupplierService,
)

SUPPLIER_ID = 1


class FakeDb:
    """Minimal ``Database`` stand-in that answers by matching the SQL text."""

    def __init__(self, *, opening="0", tickets=None, payments=None, existing=(),
                 rows=None, priced=0):
        self.opening = opening
        self.tickets = tickets        # (count, sum) or None
        self.payments = payments      # sum or None
        self.existing = set(existing)
        self.rows = rows or []
        self.priced = priced
        self.queries: list[str] = []

    def _record(self, query):
        self.queries.append(" ".join(str(query).split()))

    def fetch_one(self, query, params=None):
        self._record(query)
        text = str(query)
        if "to_regclass" in text:
            name = str(params[0]).split(".")[-1]
            return {"oid": 1 if name in self.existing else None}
        if "MAX(supplier_code)" in text:
            return {"next_code": 85}
        if "CASE WHEN" in text:
            return {"c": self.priced}
        if "FROM tawrid_suppliers" in text and "opening_balance" in text:
            return {"opening_balance": self.opening}
        if TICKETS_TABLE in text and "COUNT(*) AS n" in text:
            count, total = self.tickets or (0, 0)
            return {"n": count, "s": total}
        if TICKETS_TABLE in text and "COUNT(*) AS c" in text:
            count, _total = self.tickets or (0, 0)
            return {"c": count}
        if PAYMENTS_TABLE in text and "COUNT(*) AS c" in text:
            return {"c": 0 if self.payments is None else 1}
        if PAYMENTS_TABLE in text and "SUM(amount)" in text:
            return {"s": self.payments or 0}
        return None

    def fetch_all(self, query, params=None):
        self._record(query)
        return list(self.rows)

    def execute(self, query, params=None):
        self._record(query)


def service(**kwargs) -> TawridSupplierService:
    return TawridSupplierService(FakeDb(**kwargs))


# --- the balance dataclass ---------------------------------------------------

def test_balance_is_opening_plus_tickets_minus_paid():
    balance = SupplierBalance(
        opening_balance=Decimal("1511010"),
        purchased=Decimal("20962375"),
        paid=Decimal("19849690"),
    )
    assert balance.balance == Decimal("2623695")


def test_an_overpaid_crusher_keeps_its_negative_balance():
    """«مكة ستون»: 0 + 37,575 − 48,700. Money sitting with someone else."""
    balance = SupplierBalance(
        opening_balance=Decimal("0"),
        purchased=Decimal("37575"),
        paid=Decimal("48700"),
    )
    assert balance.balance == Decimal("-11125")


def test_a_fresh_balance_is_all_zero_and_flagged_as_having_no_movement():
    balance = SupplierBalance()
    assert balance.balance == Decimal("0")
    assert balance.movements_available is False


# --- probing for the tables later phases create ------------------------------

def test_without_the_movement_tables_only_the_opening_balance_is_reported():
    svc = service(opening="192525")
    balance = svc.for_supplier(SUPPLIER_ID)
    assert balance.opening_balance == Decimal("192525")
    assert balance.balance == Decimal("192525")
    assert balance.movements_available is False


def test_without_the_movement_tables_they_are_never_queried():
    svc = service(opening="1000")
    svc.for_supplier(SUPPLIER_ID)
    assert not any(TICKETS_TABLE in q for q in svc._db.queries)
    assert not any(PAYMENTS_TABLE in q for q in svc._db.queries)


def test_once_the_tables_exist_the_full_summary_is_computed():
    svc = service(
        opening="1511010",
        tickets=(2389, "20962375"),
        payments="19849690",
        existing=(TICKETS_TABLE, PAYMENTS_TABLE),
    )
    balance = svc.for_supplier(SUPPLIER_ID)
    assert balance.tickets_count == 2389
    assert balance.purchased == Decimal("20962375")
    assert balance.paid == Decimal("19849690")
    assert balance.balance == Decimal("2623695")
    assert balance.movements_available is True


def test_the_supplier_side_reads_total_res_not_the_customer_total():
    """The two volumes differ on 4,015 of the 4,072 legacy tickets."""
    svc = service(tickets=(1, "100"), existing=(TICKETS_TABLE,))
    svc.for_supplier(SUPPLIER_ID)
    ticket_queries = [q for q in svc._db.queries if TICKETS_TABLE in q]
    assert ticket_queries and all("total_res" in q for q in ticket_queries)
    assert not any("safi_cus" in q for q in ticket_queries)


def test_an_empty_id_yields_a_zero_summary_without_touching_the_database():
    svc = service(opening="500")
    for empty in (None, ""):
        assert svc.for_supplier(empty).balance == Decimal("0")
    assert svc._db.queries == []


# --- deletion guard ----------------------------------------------------------

def test_has_movement_is_zero_while_the_tables_do_not_exist():
    assert service().has_movement(SUPPLIER_ID) == 0


def test_has_movement_counts_tickets_once_the_table_exists():
    svc = service(tickets=(4, "0"), existing=(TICKETS_TABLE,))
    assert svc.has_movement(SUPPLIER_ID) == 4


def test_has_movement_of_an_empty_id_is_zero():
    assert service().has_movement(None) == 0


# --- the مسلسل ---------------------------------------------------------------

def test_next_code_counts_this_table_not_the_customers_table():
    """The defect: Fproduct.t1 defaulted to DMax("[number1]","fanii")+1."""
    svc = service()
    assert svc.next_code() == 85
    code_query = next(q for q in svc._db.queries if "MAX(supplier_code)" in q)
    assert "tawrid_suppliers" in code_query
    assert "tawrid_customers" not in code_query


# --- the picker rows ---------------------------------------------------------

def test_picker_rows_put_active_cards_first_then_sort_by_name():
    svc = service()
    svc.picker_rows()
    query = svc._db.queries[-1]
    assert "ORDER BY s.is_active DESC, s.supplier_name" in query


def test_picker_balance_is_the_opening_balance_until_the_tables_exist():
    svc = service()
    svc.picker_rows()
    query = svc._db.queries[-1]
    assert "s.opening_balance + 0 - 0 AS balance" in query
    assert TICKETS_TABLE not in query
    assert PAYMENTS_TABLE not in query


def test_picker_balance_adds_the_movement_once_the_tables_exist():
    svc = service(existing=(TICKETS_TABLE, PAYMENTS_TABLE))
    svc.picker_rows()
    query = svc._db.queries[-1]
    assert TICKETS_TABLE in query and "total_res" in query
    assert PAYMENTS_TABLE in query and "amount" in query


def test_picker_rows_are_returned_as_given():
    row = {"supplier_id": 1, "supplier_code": 1, "supplier_name": "الهدي",
           "is_active": True, "balance": Decimal("2623695")}
    assert service(rows=[row]).picker_rows() == [row]


# --- the priced-item count ---------------------------------------------------

def test_priced_item_count_asks_about_all_ten_columns():
    svc = service(priced=9)
    assert svc.priced_item_count(SUPPLIER_ID) == 9
    query = svc._db.queries[-1]
    for column in PRICE_COLUMNS:
        assert column in query


def test_priced_item_count_of_an_empty_id_is_zero():
    svc = service()
    assert svc.priced_item_count(None) == 0
    assert svc._db.queries == []


# --- the spec the screen is built from ---------------------------------------

def test_the_spec_uses_its_own_table_and_never_the_older_suppliers_table():
    spec = TABLE_SPECS["tawrid_suppliers"]
    assert spec.table_name == "tawrid_suppliers"
    assert spec.primary_key == "supplier_id"


def test_the_spec_carries_the_ten_item_prices_as_fixed_hidden_fields():
    spec = TABLE_SPECS["tawrid_suppliers"]
    hidden = [f.name for f in spec.fields if f.hidden_on_form]
    assert hidden == list(PRICE_COLUMNS)


def test_the_two_columns_fproduct_never_showed_are_on_the_form():
    """notees is empty in 23 rows of 23, and no opening balance has its date."""
    spec = TABLE_SPECS["tawrid_suppliers"]
    on_form = {f.name for f in spec.fields if not f.hidden_on_form}
    assert {"notes", "opening_date"} <= on_form


def test_sen3_keeps_the_label_the_users_read():
    spec = TABLE_SPECS["tawrid_suppliers"]
    label = next(f.label for f in spec.fields if f.name == "price_sen_ataqa")
    assert label == "سن عتاقة"


@pytest.mark.parametrize("column", PRICE_COLUMNS)
def test_every_price_column_is_right_aligned_on_the_screen(column):
    from app.ui.common.theme import RIGHT_ALIGNED_FIELDS

    assert column in RIGHT_ALIGNED_FIELDS["tawrid_suppliers"]
