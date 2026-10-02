"""Unit tests for the tractor-payment service (phase 8), no real database.

They pin the parts that are not the shared CRUD path:

* the payment number is allocated off MAX (numbering survives gaps),
* ``account_for`` takes the payment's own amount back out of «المصروف» so the
  screen can show the balance before/after it, and
* the «بحث عن سند صرف جرار» query matches number / driver name / بيان, newest first.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tawrid_tractor_payment_service import (
    PaymentAccount,
    TawridTractorPaymentService,
)
from app.services.tawrid_tractor_service import TractorBalance


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


def service(**kwargs) -> TawridTractorPaymentService:
    return TawridTractorPaymentService(FakeDb(**kwargs))


# --- numbering ---------------------------------------------------------------

def test_next_payment_no_is_max_plus_one():
    svc = service(one={"COALESCE(MAX(payment_no)": {"n": 741}})
    assert svc.next_payment_no() == 741
    assert "COALESCE(MAX(payment_no), 0) + 1" in svc._db.queries[-1]


def test_payment_no_exists_excludes_the_current_row():
    svc = service(one={"WHERE payment_no = %s AND payment_id": {"x": 1}})
    assert svc.payment_no_exists(5, exclude_id=3) is True
    assert svc._db.params[-1] == [5, 3]


def test_a_blank_payment_no_is_never_taken():
    svc = service()
    assert svc.payment_no_exists("") is False
    assert svc._db.queries == []


# --- picker rows -------------------------------------------------------------

def test_tractor_picker_rows_are_active_first():
    rows = [{"tractor_id": 1, "driver_name": "أحمد", "is_active": True}]
    svc = service(many={"FROM tawrid_tractors": rows})
    out = svc.tractor_picker_rows()
    assert out and out[0]["tractor_id"] == 1
    assert "ORDER BY is_active DESC" in svc._db.queries[-1]


# --- the account summary excludes the payment on screen ----------------------

class FakeTractors:
    def __init__(self, balance: TractorBalance):
        self._balance = balance

    def for_tractor(self, tractor_id):
        return self._balance


def test_account_for_a_new_payment_takes_nothing_out():
    # opening 20k + earned 500k = 520k owed; 300k already paid.
    svc = service()
    svc._tractors = FakeTractors(
        TractorBalance(
            opening_balance=Decimal("20000"),
            earned=Decimal("500000"),
            paid=Decimal("300000"),
            trips_count=8,
            movements_available=True,
        )
    )
    account = svc.account_for(7, exclude_payment_id=None)
    assert account.total_owed == Decimal("520000")
    assert account.base_paid == Decimal("300000")  # nothing removed
    assert account.movements_available is True


def test_account_for_a_saved_payment_removes_its_own_amount():
    svc = service(one={"amount FROM tawrid_tractor_payments WHERE payment_id": {"amount": Decimal("100000")}})
    svc._tractors = FakeTractors(
        TractorBalance(
            opening_balance=Decimal("20000"),
            earned=Decimal("500000"),
            paid=Decimal("400000"),
            movements_available=True,
        )
    )
    account = svc.account_for(7, exclude_payment_id=99)
    # paid 400k minus this payment's own 100k = 300k base.
    assert account.base_paid == Decimal("300000")
    assert svc._db.params[-1] == [99]


def test_account_for_no_tractor_is_empty():
    account = service().account_for(None)
    assert account == PaymentAccount()
    assert account.total_owed == Decimal("0")


def test_overpaid_tractor_survives_as_a_negative_balance():
    # 100k owed, 111,125 paid -> balance −11,125.
    svc = service()
    svc._tractors = FakeTractors(
        TractorBalance(
            opening_balance=Decimal("0"),
            earned=Decimal("100000"),
            paid=Decimal("111125"),
            movements_available=True,
        )
    )
    account = svc.account_for(7, exclude_payment_id=None)
    assert account.total_owed - account.base_paid == Decimal("-11125")


# --- the search dialog rows --------------------------------------------------

def test_search_with_a_keyword_matches_number_name_and_statement():
    rows = [{"payment_id": 1, "payment_no": 5, "driver_name": "أحمد", "amount": Decimal("20000")}]
    svc = service(many={"LEFT JOIN tawrid_tractors": rows})
    out = svc.search_payments("أحمد")
    assert out and out[0]["payment_id"] == 1
    q = svc._db.queries[-1]
    assert "ILIKE" in q and "ORDER BY p.payment_no DESC" in q
    # number, name, statement -> three LIKE params + the limit.
    assert svc._db.params[-1] == ["%أحمد%", "%أحمد%", "%أحمد%", 300]


def test_empty_search_lists_the_recent_payments_without_a_where():
    svc = service(many={"LEFT JOIN tawrid_tractors": []})
    svc.search_payments("")
    q = svc._db.queries[-1]
    assert "WHERE" not in q and "ORDER BY p.payment_no DESC" in q
