"""Unit tests for the customer-receipt service (phase 6), no real database.

They pin the parts that are not the shared CRUD path:

* the receipt number is allocated off MAX (numbering survives gaps),
* ``account_for`` takes the receipt's own amount back out of «المحصّل» so the
  screen can show the balance before/after it, and
* the «بحث عن سند» query matches number / customer name / بيان, newest first.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tawrid_customer_receipt_service import (
    ReceiptAccount,
    TawridCustomerReceiptService,
)
from app.services.tawrid_customer_service import CustomerBalance


class FakeDb:
    """Routes each query to a canned row by a substring of its text."""

    def __init__(self, one=None, many=None):
        self._one = one or {}
        self._many = many or {}
        self.queries: list[str] = []
        self.params: list[list] = []

    def _match(self, table: dict, text: str):
        for needle, value in table.items():
            if needle in text:
                return value
        return None

    def fetch_one(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text)
        self.params.append(list(params or []))
        return self._match(self._one, text)

    def fetch_all(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text)
        self.params.append(list(params or []))
        return list(self._match(self._many, text) or [])


def service(**kwargs) -> TawridCustomerReceiptService:
    return TawridCustomerReceiptService(FakeDb(**kwargs))


# --- numbering ---------------------------------------------------------------

def test_next_receipt_no_is_max_plus_one():
    svc = service(one={"COALESCE(MAX(receipt_no)": {"n": 1214}})
    assert svc.next_receipt_no() == 1214
    assert "COALESCE(MAX(receipt_no), 0) + 1" in svc._db.queries[-1]


def test_receipt_no_exists_excludes_the_current_row():
    svc = service(one={"WHERE receipt_no = %s AND receipt_id": {"x": 1}})
    assert svc.receipt_no_exists(5, exclude_id=3) is True
    assert svc._db.params[-1] == [5, 3]


def test_a_blank_receipt_no_is_never_taken():
    svc = service()
    assert svc.receipt_no_exists("") is False
    assert svc._db.queries == []


# --- the account summary excludes the receipt on screen ----------------------

class FakeCustomers:
    def __init__(self, balance: CustomerBalance):
        self._balance = balance

    def for_customer(self, customer_id):
        return self._balance


def test_account_for_a_new_receipt_takes_nothing_out():
    # opening 100k + invoiced 1,240k = 1,340k due; 750k already collected.
    svc = service()
    svc._customers = FakeCustomers(
        CustomerBalance(
            opening_balance=Decimal("100000"),
            invoiced=Decimal("1240000"),
            collected=Decimal("750000"),
            tickets_count=5,
            movements_available=True,
        )
    )
    account = svc.account_for(7, exclude_receipt_id=None)
    assert account.total_due == Decimal("1340000")
    assert account.base_collected == Decimal("750000")  # nothing removed
    assert account.movements_available is True


def test_account_for_a_saved_receipt_removes_its_own_amount():
    svc = service(one={"amount FROM tawrid_customer_receipts WHERE receipt_id": {"amount": Decimal("250000")}})
    svc._customers = FakeCustomers(
        CustomerBalance(
            opening_balance=Decimal("100000"),
            invoiced=Decimal("1240000"),
            collected=Decimal("1000000"),
            movements_available=True,
        )
    )
    account = svc.account_for(7, exclude_receipt_id=99)
    # collected 1,000k minus this receipt's own 250k = 750k base.
    assert account.base_collected == Decimal("750000")
    assert svc._db.params[-1] == [99]


def test_account_for_no_customer_is_empty():
    account = service().account_for(None)
    assert account == ReceiptAccount()
    assert account.total_due == Decimal("0")


# --- the search dialog rows --------------------------------------------------

def test_search_with_a_keyword_matches_number_name_and_statement():
    rows = [{"receipt_id": 1, "receipt_no": 5, "customer_name": "محمد", "amount": Decimal("20000")}]
    svc = service(many={"LEFT JOIN tawrid_customers": rows})
    out = svc.search_receipts("محمد")
    assert out and out[0]["receipt_id"] == 1
    q = svc._db.queries[-1]
    assert "ILIKE" in q and "ORDER BY r.receipt_no DESC" in q
    # number, name, statement -> three LIKE params + the limit.
    assert svc._db.params[-1] == ["%محمد%", "%محمد%", "%محمد%", 300]


def test_empty_search_lists_the_recent_receipts_without_a_where():
    svc = service(many={"LEFT JOIN tawrid_customers": []})
    svc.search_receipts("")
    q = svc._db.queries[-1]
    assert "WHERE" not in q and "ORDER BY r.receipt_no DESC" in q
