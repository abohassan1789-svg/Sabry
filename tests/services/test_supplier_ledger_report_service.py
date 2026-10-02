"""Service tests for the item-level Supplier Ledger (كشف حساب المورد - تفصيلي).

A fake repository (no database) pins: invoice lines expanded per item, the نوع
العملية / البيان per kind, the القيمة vs التحصيلات split (each side blank on the
other), the opening row under القيمة, the voucher-number cleanup, and the closing
formula الرصيد المتبقي = رصيد أول + مشتريات − تحصيلات.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.supplier_ledger_report_service import (
    SupplierLedgerReportService,
    SupplierLedgerRequest,
    SupplierLedgerValidationError,
)


class _FakeRepo:
    def __init__(self, rows, opening=Decimal("0.00")):
        self._rows = rows
        self._opening = opening

    def fetch_statement_lines(self, filters):
        return list(self._rows)

    def fetch_supplier_name(self, supplier_id):
        return "مورد تجريبي"

    def fetch_supplier_opening_balance(self, supplier_id):
        return self._opening

    def fetch_supplier_openings(self, supplier_ids):
        return {sid: self._opening for sid in supplier_ids}


def _line(group_id, invoice_number, item_name, qty, price, value, *,
          unit_weight="0", total_weight="0", weight_value="0", d=date(2026, 1, 10)):
    return {
        "source_type": "purchase_invoice_line",
        "order_seq": 0,
        "group_id": group_id,
        "line_number": 1,
        "transaction_date": d,
        "supplier_id": 1001,
        "supplier_name": "مورد تجريبي",
        "movement_number": invoice_number,
        "item_name": item_name,
        "item_count": Decimal(str(qty)),
        "unit_weight": Decimal(str(unit_weight)),
        "total_weight": Decimal(str(total_weight)),
        "unit_price": Decimal(str(price)),
        "count_price_total": Decimal(str(value)),
        "weight_price_total": Decimal(str(weight_value)),
        "collections": None,
        "invoice_status": "approved",
        "voucher_description": None,
    }


def _payment(group_id, voucher_number, amount, *, d=date(2026, 1, 12)):
    return {
        "source_type": "supplier_payment_voucher",
        "order_seq": 1,
        "group_id": group_id,
        "line_number": 0,
        "transaction_date": d,
        "supplier_id": 1001,
        "supplier_name": "مورد تجريبي",
        "movement_number": voucher_number,
        "item_name": None,
        "item_count": None,
        "unit_weight": None,
        "total_weight": None,
        "unit_price": None,
        "count_price_total": None,
        "weight_price_total": None,
        "collections": Decimal(str(amount)),
        "invoice_status": None,
        "voucher_description": "دفعة",
    }


def _service(rows, opening=Decimal("0.00")):
    return SupplierLedgerReportService(repository=_FakeRepo(rows, opening))


def _service_weight(rows, opening=Decimal("0.00")):
    return SupplierLedgerReportService(repository=_FakeRepo(rows, opening), account_type="وزن")


def test_invoice_line_row_shape():
    svc = _service([_line(1, "Pur-1", "مانجة", 50, 60, 3000)], opening=Decimal("1000.00"))
    result = svc.fetch_report(SupplierLedgerRequest(supplier_id=1001))
    line = [r for r in result.export_rows if r["operation_type"] == "فاتورة مشتريات"][0]
    assert line["description"] == "مانجة"
    assert line["movement_number"] == "Pur-1"
    assert line["quantity"] == "50"
    assert line["price"] == "60.00"
    assert line["value"] == "3,000.00"
    assert line["collections"] == ""  # blank on the collections side


def test_payment_row_shape_and_number_cleanup():
    svc = _service([_payment(9, "Paid - Sub-5", "8000.00")])
    result = svc.fetch_report(SupplierLedgerRequest(supplier_id=1001))
    pay = [r for r in result.export_rows if r["operation_type"] == "سداد"][0]
    assert pay["description"] == "السداد"
    assert pay["movement_number"] == "5"
    assert pay["collections"] == "8,000.00"
    assert pay["value"] == ""  # blank on the value side


def test_opening_row_under_value_column():
    svc = _service([_line(1, "Pur-1", "مانجة", 1, 60, 60)], opening=Decimal("5000.00"))
    rows = svc.fetch_report(SupplierLedgerRequest(supplier_id=1001)).export_rows
    opening = rows[0]
    assert opening["operation_type"] == "رصيد أول مدة"
    assert opening["description"] == "رصيد أول مدة"
    assert opening["value"] == "5,000.00"
    assert opening["collections"] == ""


def test_remaining_equals_opening_plus_purchases_minus_collections():
    svc = _service(
        [_line(1, "Pur-1", "أ", 1, 60, 60), _line(1, "Pur-1", "ب", 1, 40, 40),
         _payment(9, "Paid - Sub-1", "30.00")],
        opening=Decimal("100.00"),
    )
    s = svc.fetch_report(SupplierLedgerRequest(supplier_id=1001)).summary
    assert s["total_opening"] == Decimal("100.00")
    assert s["total_purchases"] == Decimal("100.00")   # 60 + 40
    assert s["total_collections"] == Decimal("30.00")
    assert s["remaining"] == Decimal("170.00")         # 100 + 100 - 30


def test_weight_profile_columns_and_value():
    # وزن ledger adds الوزن / إجمالي الوزن and القيمة = إجمالي سعر الوزن.
    svc = _service_weight([
        _line(1, "Pur-9", "مانجة", qty=10, price=5, value=50,
              unit_weight="2", total_weight="20", weight_value="200"),
    ])
    keys = [c.key for c in svc.columns]
    assert keys == [
        "transaction_date", "movement_number", "operation_type", "description",
        "quantity", "unit_weight", "total_weight", "price", "value", "collections",
    ]
    line = [r for r in svc.fetch_report(SupplierLedgerRequest(supplier_id=1001)).export_rows
            if r["operation_type"] == "فاتورة مشتريات"][0]
    assert line["quantity"] == "10"
    assert line["unit_weight"] == "2"
    assert line["total_weight"] == "20"
    assert line["value"] == "200.00"   # weight_price_total, not count_price_total


def test_count_profile_has_no_weight_columns():
    svc = _service([_line(1, "Pur-1", "أ", 1, 60, 60)])
    keys = [c.key for c in svc.columns]
    assert "unit_weight" not in keys and "total_weight" not in keys


def test_invalid_date_range_raises():
    with pytest.raises(SupplierLedgerValidationError):
        _service([]).fetch_report(
            SupplierLedgerRequest(date_from="2026-02-01", date_to="2026-01-01")
        )
