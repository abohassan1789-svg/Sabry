"""Unit tests for the Saudi sales-invoice numbering repository boundary."""

from __future__ import annotations

from collections import deque

import pytest

from app.repositories.saudi_sales_invoice_repository import SaudiSalesInvoiceRepository


class RecordingDatabase:
    def __init__(self, result=None):
        self.result = result
        self.fetch_one_calls: list[tuple[str, list]] = []

    def fetch_one(self, sql, params=None):
        self.fetch_one_calls.append((str(sql), list(params or [])))
        return self.result


class RecordingCursor:
    def __init__(self, rows=()):
        self.rows = deque(rows)
        self.calls: list[tuple[str, list]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), list(params or [])))
        return self

    def fetchone(self):
        return self.rows.popleft()


class RecordingConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


def _repo(db=None):
    repo = object.__new__(SaudiSalesInvoiceRepository)
    repo.db = db or RecordingDatabase()
    repo._url = "unused"
    return repo


def _with_transaction(rows=()):
    repo = _repo()
    cursor = RecordingCursor(rows)
    connection = RecordingConnection(cursor)
    repo._txn = lambda: connection
    return repo, cursor


def test_reserve_invoice_number_returns_decimal_sequence_value():
    repo, cursor = _with_transaction([{"n": 50001}, None])

    assert repo.reserve_invoice_number() == "50001"
    assert any(
        "nextval('sales_invoice_number_seq')" in sql for sql, _ in cursor.calls
    )


def test_reservation_skips_number_already_stored_manually():
    repo, cursor = _with_transaction(
        [{"n": 50001}, {"exists": 1}, {"n": 50002}, None]
    )

    assert repo.reserve_invoice_number() == "50002"


def test_global_duplicate_lookup_has_no_seller_predicate():
    db = RecordingDatabase({"exists": 1})
    repo = _repo(db)

    assert repo.invoice_number_exists("50001") is True

    sql, params = db.fetch_one_calls[-1]
    assert "seller_company_id" not in sql
    assert params == ["50001"]


def test_global_duplicate_lookup_can_exclude_current_invoice():
    db = RecordingDatabase(None)
    repo = _repo(db)

    assert repo.invoice_number_exists("50001", exclude_id=7) is False

    sql, params = db.fetch_one_calls[-1]
    assert "id <> %s" in sql
    assert params == ["50001", 7]


def test_forward_sync_moves_sequence_to_higher_manual_number():
    repo, cursor = _with_transaction([{"last_value": 50002, "is_called": True}])

    repo._sync_invoice_number_sequence(cursor, "50010")

    assert any(
        "setval('sales_invoice_number_seq'" in sql and params == [50010]
        for sql, params in cursor.calls
    )


def test_forward_sync_consumes_the_uncalled_first_value_when_saved_manually():
    repo, cursor = _with_transaction(
        [{"last_value": 50001, "is_called": False}]
    )

    repo._sync_invoice_number_sequence(cursor, "50001")

    assert any(
        "setval('sales_invoice_number_seq'" in sql and params == [50001]
        for sql, params in cursor.calls
    )


@pytest.mark.parametrize("manual", ["50001", "49999", "MANUAL-A", "", None])
def test_forward_sync_never_moves_back_or_for_non_numeric_values(manual):
    repo, cursor = _with_transaction(
        [{"last_value": 50010, "is_called": True}]
    )

    repo._sync_invoice_number_sequence(cursor, manual)

    assert not any("setval(" in sql for sql, _ in cursor.calls)


def test_insert_synchronizes_number_inside_write_transaction():
    repo, cursor = _with_transaction([{"id": 4, "invoice_number": "50010"}])
    synchronized: list[str] = []
    repo._insert_lines = lambda *args: None
    repo._sync_invoice_number_sequence = (
        lambda cur, number: synchronized.append(str(number))
    )
    repo.load_invoice = lambda invoice_id: {"header": {"id": invoice_id}}

    repo.insert_invoice({"invoice_number": "50010"}, [])

    assert synchronized == ["50010"]


def test_update_synchronizes_final_number_inside_write_transaction():
    repo, cursor = _with_transaction([{"id": 4, "invoice_number": "50020"}])
    synchronized: list[str] = []
    repo._insert_lines = lambda *args: None
    repo._sync_invoice_number_sequence = (
        lambda cur, number: synchronized.append(str(number))
    )
    repo.load_invoice = lambda invoice_id: {"header": {"id": invoice_id}}

    repo.update_invoice(
        4,
        1,
        {"invoice_number": "50020"},
        [],
    )

    assert synchronized == ["50020"]
