"""Service-level tests for the Supplier Statement report (كشف حساب المورد).

A fake repository (no database) pins the pure logic: the exact Arabic البيان, the
supplier debit/credit mapping (invoice = credit, payment = debit), the
opening-balance row, the running balance, the fixed-decimal totals and the
closing balance (credit − debit), the voucher-number cleanup, the empty state and
the date validation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.supplier_statement_report_service import (
    SupplierStatementReportService,
    SupplierStatementRequest,
    SupplierStatementValidationError,
    EMPTY_MESSAGE,
)


class _FakeRepo:
    def __init__(self, rows, opening=Decimal("0.00")):
        self._rows = rows
        self._opening = opening
        self.fetch_calls: list = []

    def fetch_statement(self, filters):
        self.fetch_calls.append(filters)
        return list(self._rows)

    def fetch_supplier_name(self, supplier_id):
        return "مورد تجريبي"

    def fetch_supplier_opening_balance(self, supplier_id):
        return self._opening

    def fetch_supplier_openings(self, supplier_ids):
        return {sid: self._opening for sid in supplier_ids}

    def fetch_supplier_options(self):
        return [{"id": 1001, "label": "مورد تجريبي"}]


def _invoice(source_id, number, total, *, d=date(2026, 1, 10), status="approved"):
    return {
        "source_type": "purchase_invoice",
        "source_id": source_id,
        "source_sequence": 0,
        "transaction_date": d,
        "supplier_id": 1001,
        "supplier_name": "مورد تجريبي",
        "document_number": number,
        "debit": Decimal("0"),
        "credit": Decimal(str(total)),
        "invoice_status": status,
        "voucher_description": None,
    }


def _payment(source_id, number, amount, *, description=None, d=date(2026, 1, 12)):
    return {
        "source_type": "supplier_payment_voucher",
        "source_id": source_id,
        "source_sequence": 1,
        "transaction_date": d,
        "supplier_id": 1001,
        "supplier_name": "مورد تجريبي",
        "document_number": number,
        "debit": Decimal(str(amount)),
        "credit": Decimal("0"),
        "invoice_status": None,
        "voucher_description": description,
    }


def _service(rows, opening=Decimal("0.00")):
    return SupplierStatementReportService(repository=_FakeRepo(rows, opening))


def _movements(rows):
    """Drop the per-supplier opening rows to assert on the movements alone."""
    return [r for r in rows if r["kind"] != "opening"]


def test_invoice_is_credit_and_payment_is_debit():
    svc = _service([_invoice(1, "1002", "12000.00"), _payment(2, "Paid - Sub-3", "8000.00")])
    result = svc.fetch_report(SupplierStatementRequest())
    inv, pay = _movements(result.rows)
    assert inv["credit"] == Decimal("12000.00") and inv["debit"] == Decimal("0.00")
    assert pay["debit"] == Decimal("8000.00") and pay["credit"] == Decimal("0.00")


def test_descriptions_are_exact():
    svc = _service([
        _invoice(1, "1002", "12000.00"),
        _payment(2, "Paid - Sub-3", "8000.00", description="دفعة أولى"),
        _payment(3, "Paid - Sub-4", "2000.00"),
    ])
    rows = _movements(svc.fetch_report(SupplierStatementRequest()).rows)
    assert rows[0]["description"] == "فاتورة مشتريات رقم 1002"
    assert rows[1]["description"] == "سند صرف رقم 3 عن دفعة أولى"
    assert rows[2]["description"] == "سند صرف رقم 4"  # no «عن» without a statement


def test_voucher_number_is_cleaned_to_trailing_digits():
    svc = _service([_payment(2, "Paid - Sub-7", "1000.00")])
    row = _movements(svc.fetch_report(SupplierStatementRequest()).rows)[0]
    assert row["document_number"] == "7"


def test_opening_balance_row_added_for_a_single_supplier():
    svc = _service([_invoice(1, "1002", "12000.00")], opening=Decimal("5000.00"))
    result = svc.fetch_report(SupplierStatementRequest(supplier_id=1001, date_from="2026-01-01"))
    first = result.rows[0]
    assert first["description"] == "رصيد أول المدة"
    assert first["credit"] == Decimal("5000.00")
    assert first["transaction_date"] == "2026-01-01"


def test_running_balance_and_closing_balance():
    svc = _service(
        [_invoice(1, "1002", "12000.00"), _payment(2, "Paid - Sub-3", "8000.00")],
        opening=Decimal("5000.00"),
    )
    result = svc.fetch_report(SupplierStatementRequest(supplier_id=1001))
    balances = [r["balance"] for r in result.rows]
    assert balances == [Decimal("5000.00"), Decimal("17000.00"), Decimal("9000.00")]
    # balance = total_credit - total_debit = (5000+12000) - 8000
    assert result.summary["balance"] == Decimal("9000.00")
    assert result.summary["total_credit"] == Decimal("17000.00")
    assert result.summary["total_debit"] == Decimal("8000.00")


def test_opening_row_shown_per_supplier_in_all_view():
    # Even with no specific supplier chosen, each supplier that has activity is led
    # by its own رصيد أول المدة (credit), and its running balance restarts there.
    svc = _service([_invoice(1, "1002", "12000.00")], opening=Decimal("5000.00"))
    rows = svc.fetch_report(SupplierStatementRequest()).rows
    assert rows[0]["description"] == "رصيد أول المدة"
    assert rows[0]["credit"] == Decimal("5000.00")
    assert rows[1]["balance"] == Decimal("17000.00")  # 5000 opening + 12000 invoice


def test_empty_state():
    result = _service([]).fetch_report(SupplierStatementRequest())
    assert result.is_empty
    assert result.rows == []


def test_invalid_date_range_raises():
    with pytest.raises(SupplierStatementValidationError):
        _service([]).fetch_report(
            SupplierStatementRequest(date_from="2026-02-01", date_to="2026-01-01")
        )
