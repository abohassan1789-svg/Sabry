"""Unit tests for the purchase-invoice numbering repository boundary."""

from __future__ import annotations

from collections import deque

import pytest

from app.repositories.purchase_invoice_repository import PurchaseInvoiceRepository


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
    repo = object.__new__(PurchaseInvoiceRepository)
    repo.db = db or RecordingDatabase()
    repo._url = "unused"
    return repo


def _with_transaction(rows=()):
    repo = _repo()
    cursor = RecordingCursor(rows)
    connection = RecordingConnection(cursor)
    repo._txn = lambda: connection
    return repo, cursor


def test_reserve_invoice_number_returns_pur_prefixed_value():
    repo, cursor = _with_transaction([{"n": 1001}, None])

    assert repo.reserve_invoice_number() == "Pur-1001"
    assert any(
        "nextval('purchase_invoice_number_seq')" in sql for sql, _ in cursor.calls
    )


def test_reservation_skips_number_already_stored_manually():
    repo, cursor = _with_transaction(
        [{"n": 1001}, {"exists": 1}, {"n": 1002}, None]
    )

    assert repo.reserve_invoice_number() == "Pur-1002"


def test_global_duplicate_lookup_has_no_supplier_predicate():
    db = RecordingDatabase({"exists": 1})
    repo = _repo(db)

    assert repo.invoice_number_exists("Pur-1001") is True

    sql, params = db.fetch_one_calls[-1]
    assert "supplier_id" not in sql
    assert params == ["Pur-1001"]


def test_global_duplicate_lookup_can_exclude_current_invoice():
    db = RecordingDatabase(None)
    repo = _repo(db)

    assert repo.invoice_number_exists("Pur-1001", exclude_id=7) is False

    sql, params = db.fetch_one_calls[-1]
    assert "id <> %s" in sql
    assert params == ["Pur-1001", 7]


def test_forward_sync_moves_sequence_to_higher_manual_number():
    repo, cursor = _with_transaction([{"last_value": 1002, "is_called": True}])

    repo._sync_invoice_number_sequence(cursor, "Pur-1010")

    assert any(
        "setval('purchase_invoice_number_seq'" in sql and params == [1010]
        for sql, params in cursor.calls
    )


def test_forward_sync_accepts_a_bare_numeric_manual_number():
    repo, cursor = _with_transaction([{"last_value": 1002, "is_called": True}])

    repo._sync_invoice_number_sequence(cursor, "1010")

    assert any(
        "setval('purchase_invoice_number_seq'" in sql and params == [1010]
        for sql, params in cursor.calls
    )


def test_forward_sync_consumes_the_uncalled_first_value_when_saved_manually():
    repo, cursor = _with_transaction([{"last_value": 1001, "is_called": False}])

    repo._sync_invoice_number_sequence(cursor, "Pur-1001")

    assert any(
        "setval('purchase_invoice_number_seq'" in sql and params == [1001]
        for sql, params in cursor.calls
    )


@pytest.mark.parametrize("manual", ["Pur-1001", "1001", "999", "MANUAL-A", "", None])
def test_forward_sync_never_moves_back_or_for_non_standard_values(manual):
    repo, cursor = _with_transaction([{"last_value": 1010, "is_called": True}])

    repo._sync_invoice_number_sequence(cursor, manual)

    assert not any("setval(" in sql for sql, _ in cursor.calls)


def test_insert_synchronizes_number_inside_write_transaction():
    repo, cursor = _with_transaction([{"id": 4, "invoice_number": "Pur-1010"}])
    synchronized: list[str] = []
    repo._insert_lines = lambda *args: None
    repo._sync_invoice_number_sequence = (
        lambda cur, number: synchronized.append(str(number))
    )
    repo.load_invoice = lambda invoice_id: {"header": {"id": invoice_id}}

    repo.insert_invoice({"invoice_number": "Pur-1010"}, [])

    assert synchronized == ["Pur-1010"]


def test_update_synchronizes_final_number_inside_write_transaction():
    repo, cursor = _with_transaction([{"id": 4, "invoice_number": "Pur-1020"}])
    synchronized: list[str] = []
    repo._insert_lines = lambda *args: None
    repo._sync_invoice_number_sequence = (
        lambda cur, number: synchronized.append(str(number))
    )
    repo.load_invoice = lambda invoice_id: {"header": {"id": invoice_id}}

    repo.update_invoice(4, 1, {"invoice_number": "Pur-1020"}, [])

    assert synchronized == ["Pur-1020"]
