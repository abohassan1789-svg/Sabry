"""Unit tests for the supplier-payment service (phase 7), no real database.

They pin the parts that are not the shared CRUD path:

* the payment number is allocated off MAX (numbering survives gaps),
* ``account_for`` takes the payment's own amount back out of «المدفوع» so the
  screen can show the balance before/after it, and
* the «بحث عن سند صرف» query matches number / crusher name / بيان, newest first.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tawrid_supplier_payment_service import (
    PaymentAccount,
    TawridSupplierPaymentService,
)
from app.services.tawrid_supplier_service import SupplierBalance


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


def service(**kwargs) -> TawridSupplierPaymentService:
    return TawridSupplierPaymentService(FakeDb(**kwargs))


# --- numbering ---------------------------------------------------------------

def test_next_payment_no_is_max_plus_one():
    svc = service(one={"COALESCE(MAX(payment_no)": {"n": 149}})
    assert svc.next_payment_no() == 149
    assert "COALESCE(MAX(payment_no), 0) + 1" in svc._db.queries[-1]


def test_payment_no_exists_excludes_the_current_row():
    svc = service(one={"WHERE payment_no = %s AND payment_id": {"x": 1}})
    assert svc.payment_no_exists(5, exclude_id=3) is True
    assert svc._db.params[-1] == [5, 3]


def test_a_blank_payment_no_is_never_taken():
    svc = service()
    assert svc.payment_no_exists("") is False
    assert svc._db.queries == []


# --- the account summary excludes the payment on screen ----------------------

class FakeSuppliers:
    def __init__(self, balance: SupplierBalance):
        self._balance = balance

    def for_supplier(self, supplier_id):
        return self._balance


def test_account_for_a_new_payment_takes_nothing_out():
    # opening 50k + purchased 900k = 950k owed; 400k already paid.
    svc = service()
    svc._suppliers = FakeSuppliers(
        SupplierBalance(
            opening_balance=Decimal("50000"),
            purchased=Decimal("900000"),
            paid=Decimal("400000"),
            tickets_count=5,
            movements_available=True,
        )
    )
    account = svc.account_for(7, exclude_payment_id=None)
    assert account.total_owed == Decimal("950000")
    assert account.base_paid == Decimal("400000")  # nothing removed
    assert account.movements_available is True


def test_account_for_a_saved_payment_removes_its_own_amount():
    svc = service(one={"amount FROM tawrid_supplier_payments WHERE payment_id": {"amount": Decimal("150000")}})
    svc._suppliers = FakeSuppliers(
        SupplierBalance(
            opening_balance=Decimal("50000"),
            purchased=Decimal("900000"),
            paid=Decimal("550000"),
            movements_available=True,
        )
    )
    account = svc.account_for(7, exclude_payment_id=99)
    # paid 550k minus this payment's own 150k = 400k base.
    assert account.base_paid == Decimal("400000")
    assert svc._db.params[-1] == [99]


def test_account_for_no_supplier_is_empty():
    account = service().account_for(None)
    assert account == PaymentAccount()
    assert account.total_owed == Decimal("0")


def test_overpaid_crusher_survives_as_a_negative_balance():
    # «مكة ستون»-like: 100k owed, 111,125 paid -> balance −11,125.
    svc = service()
    svc._suppliers = FakeSuppliers(
        SupplierBalance(
            opening_balance=Decimal("0"),
            purchased=Decimal("100000"),
            paid=Decimal("111125"),
            movements_available=True,
        )
    )
    account = svc.account_for(7, exclude_payment_id=None)
    # total owed 100k, base paid 111,125 -> the balance the screen shows is −11,125.
    assert account.total_owed - account.base_paid == Decimal("-11125")


# --- the search dialog rows --------------------------------------------------

def test_search_with_a_keyword_matches_number_name_and_statement():
    rows = [{"payment_id": 1, "payment_no": 5, "supplier_name": "الهدي", "amount": Decimal("20000")}]
    svc = service(many={"LEFT JOIN tawrid_suppliers": rows})
    out = svc.search_payments("الهدي")
    assert out and out[0]["payment_id"] == 1
    q = svc._db.queries[-1]
    assert "ILIKE" in q and "ORDER BY p.payment_no DESC" in q
    # number, name, statement -> three LIKE params + the limit.
    assert svc._db.params[-1] == ["%الهدي%", "%الهدي%", "%الهدي%", 300]


def test_empty_search_lists_the_recent_payments_without_a_where():
    svc = service(many={"LEFT JOIN tawrid_suppliers": []})
    svc.search_payments("")
    q = svc._db.queries[-1]
    assert "WHERE" not in q and "ORDER BY p.payment_no DESC" in q
