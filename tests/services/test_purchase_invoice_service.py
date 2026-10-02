"""Unit tests for :class:`PurchaseInvoiceService` (no real database).

An in-memory fake repository stands in for ``PurchaseInvoiceRepository`` so all
business rules are verified deterministically: the count/weight/money Decimal
maths of the three computed line columns and the two header totals, server-side
supplier snapshots + recalculation (UI totals never trusted), free-text item
rules, invoice-number rules + global uniqueness, draft-only edits, approved
delete rules, delete-all counts, optimistic concurrency, and permission
enforcement.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from app.models.purchase_invoice import format_invoice_number, parse_sequence_value
from app.repositories.purchase_invoice_repository import StalePurchaseInvoiceError
from app.services.purchase_invoice_service import (
    PurchaseInvoiceConcurrencyError,
    PurchaseInvoicePermissionError,
    PurchaseInvoiceService,
    PurchaseInvoiceValidationError,
)

# --- seed master data -------------------------------------------------------
# 150 suppliers so "search finds record #150" proves search is not capped at 100.
SUPPLIERS = [
    {"supplier_id": 1000 + i, "supplier_name": f"مورد {i}", "mobile": f"05000000{i:02d}"}
    for i in range(1, 151)
]

_INV_EXTRA_COLS = ("approved_at", "approved_by", "created_at", "updated_at")


class FakePurchaseRepo:
    """In-memory stand-in for PurchaseInvoiceRepository."""

    def __init__(self, suppliers=None):
        self.suppliers = {s["supplier_id"]: s for s in (suppliers or SUPPLIERS)}
        self.invoices: dict[int, dict] = {}
        self._next_id = 1
        self.next_reserved_seq = 1001
        # instrumentation
        self.inserted_headers: list[dict] = []
        self.inserted_line_batches: list[list[dict]] = []
        self.audit_actions: list[str] = []

    # -- master data --
    def get_supplier(self, i):
        return self.suppliers.get(int(i))

    def list_suppliers(self, limit=100):
        return list(self.suppliers.values())[:limit]

    def search_suppliers(self, kw, limit=100):
        kw = (kw or "").strip()
        rows = [s for s in self.suppliers.values()
                if kw in (s["supplier_name"] or "") or str(s["supplier_id"]).startswith(kw)]
        return (rows or list(self.suppliers.values()))[:limit]

    # -- numbering --
    def invoice_number_exists(self, number, exclude_id=None):
        for inv in self.invoices.values():
            h = inv["header"]
            if h["invoice_number"] == number and h["id"] != exclude_id:
                return True
        return False

    def reserve_invoice_number(self):
        value = self.next_reserved_seq
        self.next_reserved_seq += 1
        return format_invoice_number(value)

    # -- writes --
    def _materialize(self, header, lines, invoice_id):
        h = dict(header)
        h["id"] = invoice_id
        h.setdefault("row_version", 1)
        for col in _INV_EXTRA_COLS:
            h.setdefault(col, None)
        stored_lines = [
            {**line, "id": idx, "invoice_id": invoice_id, "line_number": idx}
            for idx, line in enumerate(lines, start=1)
        ]
        return {"header": h, "lines": stored_lines}

    def insert_invoice(self, header, lines, audit=None):
        self.inserted_headers.append(dict(header))
        self.inserted_line_batches.append([dict(x) for x in lines])
        if audit:
            self.audit_actions.append(audit["action"])
        invoice_id = self._next_id
        self._next_id += 1
        self.invoices[invoice_id] = self._materialize(header, lines, invoice_id)
        return self.invoices[invoice_id]

    def update_invoice(self, invoice_id, expected_row_version, header_changes, lines,
                       audit=None):
        inv = self.invoices.get(int(invoice_id))
        if inv is None or inv["header"]["row_version"] != expected_row_version \
                or inv["header"]["document_status"] != "draft":
            raise StalePurchaseInvoiceError("stale")
        inv["header"].update(header_changes)
        inv["header"]["row_version"] += 1
        inv["lines"] = [
            {**line, "id": idx, "invoice_id": int(invoice_id), "line_number": idx}
            for idx, line in enumerate(lines, start=1)
        ]
        if audit:
            self.audit_actions.append(audit["action"])
        return inv

    def approve_invoice(self, invoice_id, expected_row_version, *,
                        approved_by=None, audit=None):
        inv = self.invoices.get(int(invoice_id))
        if inv is None or inv["header"]["row_version"] != expected_row_version \
                or inv["header"]["document_status"] != "draft":
            raise StalePurchaseInvoiceError("stale")
        inv["header"]["document_status"] = "approved"
        inv["header"]["approved_by"] = approved_by
        inv["header"]["row_version"] += 1
        if audit:
            self.audit_actions.append(audit["action"])
        return inv

    def load_invoice(self, invoice_id):
        return self.invoices.get(int(invoice_id))

    def delete_draft(self, invoice_id, performed_by=None):
        inv = self.invoices.get(int(invoice_id))
        if inv is None or inv["header"]["document_status"] != "draft":
            return False
        del self.invoices[int(invoice_id)]
        self.audit_actions.append("delete_draft")
        return True

    def delete_all_eligible_drafts(self, supplier_id=None, performed_by=None):
        drafts = [
            i for i, inv in self.invoices.items()
            if inv["header"]["document_status"] == "draft"
            and (supplier_id is None or inv["header"]["supplier_id"] == supplier_id)
        ]
        for i in drafts:
            del self.invoices[i]
        return {"deleted": len(drafts), "protected": 0}

    def search_invoices(self, keyword="", status=None, limit=300, *,
                        supplier_id=None, date_from=None, date_to=None):
        rows = []
        for inv in self.invoices.values():
            h = inv["header"]
            if status and h["document_status"] != status:
                continue
            if supplier_id is not None and h.get("supplier_id") != supplier_id:
                continue
            rows.append(h)
        return rows[:limit]


def make_service(repo=None, permission_check=None):
    return PurchaseInvoiceService(repository=repo or FakePurchaseRepo(),
                                  permission_check=permission_check)


def valid_form(**overrides):
    form = {
        "invoice_number": "Pur-1001",
        "issue_datetime": datetime.datetime(2026, 8, 14, 10, 30),
        "supplier_id": 1001,
        "payment_type": "cash",
        "notes": "ملاحظة",
        "lines": [
            {"item_name": "طماطم", "item_count": "10", "unit_weight": "5", "unit_price": "3"},
        ],
    }
    form.update(overrides)
    return form


# ---------------------------------------------------------------------------
# Line + total maths
# ---------------------------------------------------------------------------
def test_compute_line_amounts_count_weight_and_money():
    svc = make_service()
    amounts = svc.compute_line_amounts(Decimal("10"), Decimal("5"), Decimal("3"))
    # total_weight = 10 × 5 = 50 ; count_price_total = 10 × 3 = 30 ;
    # weight_price_total = 50 × 3 = 150
    assert amounts["total_weight"] == Decimal("50.000000")
    assert amounts["count_price_total"] == Decimal("30.00")
    assert amounts["weight_price_total"] == Decimal("150.00")


def test_header_totals_sum_the_two_line_columns():
    svc = make_service()
    result = svc.create_draft(valid_form(lines=[
        {"item_name": "طماطم", "item_count": "10", "unit_weight": "5", "unit_price": "3"},
        {"item_name": "خيار", "item_count": "4", "unit_weight": "2", "unit_price": "7"},
    ]))
    header = result["header"]
    # line1: count_price = 30, weight_price = 150
    # line2: count_price = 28, weight_price = (4×2=8)×7 = 56
    assert header["total_count_price"] == Decimal("58.00")
    assert header["total_weight_price"] == Decimal("206.00")


def test_amounts_are_decimal_never_float():
    svc = make_service()
    amounts = svc.compute_line_amounts(Decimal("1.5"), Decimal("2.5"), Decimal("4"))
    for value in amounts.values():
        assert isinstance(value, Decimal)


def test_ui_supplied_totals_are_ignored_and_recomputed():
    repo = FakePurchaseRepo()
    svc = make_service(repo)
    # Inject bogus totals in the form; the service must recompute from lines.
    svc.create_draft(valid_form(total_count_price="99999", total_weight_price="88888"))
    stored = repo.inserted_headers[0]
    assert stored["total_count_price"] == Decimal("30.00")
    assert stored["total_weight_price"] == Decimal("150.00")


# ---------------------------------------------------------------------------
# Supplier snapshot (from DB, never the UI)
# ---------------------------------------------------------------------------
def test_supplier_name_snapshot_comes_from_the_database():
    svc = make_service()
    result = svc.create_draft(valid_form(supplier_id=1050, supplier_name_snapshot="مزيّف"))
    assert result["header"]["supplier_name_snapshot"] == "مورد 50"
    assert result["header"]["supplier_id"] == 1050


def test_unknown_supplier_is_rejected():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(supplier_id=999999))


def test_supplier_is_required():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(supplier_id=None))


# ---------------------------------------------------------------------------
# Line / header validation
# ---------------------------------------------------------------------------
def test_item_name_is_required():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(lines=[
            {"item_name": "  ", "item_count": "1", "unit_weight": "1", "unit_price": "1"},
        ]))


def test_at_least_one_line_required():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(lines=[]))


def test_count_must_be_positive():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(lines=[
            {"item_name": "طماطم", "item_count": "0", "unit_weight": "1", "unit_price": "1"},
        ]))


def test_negative_price_rejected():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(lines=[
            {"item_name": "طماطم", "item_count": "1", "unit_weight": "1", "unit_price": "-5"},
        ]))


def test_negative_weight_rejected():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(lines=[
            {"item_name": "طماطم", "item_count": "1", "unit_weight": "-2", "unit_price": "5"},
        ]))


def test_zero_weight_is_allowed():
    svc = make_service()
    result = svc.create_draft(valid_form(lines=[
        {"item_name": "بضاعة بالعدد فقط", "item_count": "10", "unit_weight": "0", "unit_price": "4"},
    ]))
    header = result["header"]
    assert header["total_count_price"] == Decimal("40.00")
    assert header["total_weight_price"] == Decimal("0.00")


def test_invalid_payment_type_rejected():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(payment_type="later"))


def test_credit_payment_type_accepted():
    svc = make_service()
    result = svc.create_draft(valid_form(payment_type="credit"))
    assert result["header"]["payment_type"] == "credit"


def test_invoice_number_required():
    svc = make_service()
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.create_draft(valid_form(invoice_number="   "))


def test_duplicate_invoice_number_rejected_globally():
    repo = FakePurchaseRepo()
    svc = make_service(repo)
    svc.create_draft(valid_form(invoice_number="Pur-1001", supplier_id=1001))
    with pytest.raises(PurchaseInvoiceValidationError):
        # Same number, different supplier — still rejected (global uniqueness).
        svc.create_draft(valid_form(invoice_number="Pur-1001", supplier_id=1002))


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def test_reserve_number_uses_pur_prefix():
    svc = make_service()
    assert svc.reserve_invoice_number() == "Pur-1001"
    assert svc.reserve_invoice_number() == "Pur-1002"


def test_number_formatting_and_parsing_roundtrip():
    assert format_invoice_number(1001) == "Pur-1001"
    assert parse_sequence_value("Pur-1001") == 1001
    assert parse_sequence_value("pur-2050") == 2050
    assert parse_sequence_value("1001") == 1001
    assert parse_sequence_value("INV-9") is None
    assert parse_sequence_value("") is None


# ---------------------------------------------------------------------------
# Edit / approve / delete lifecycle
# ---------------------------------------------------------------------------
def test_update_draft_replaces_lines_and_totals():
    repo = FakePurchaseRepo()
    svc = make_service(repo)
    created = svc.create_draft(valid_form())
    inv_id = created["header"]["id"]
    rv = created["header"]["row_version"]
    updated = svc.update_draft(inv_id, rv, valid_form(lines=[
        {"item_name": "بصل", "item_count": "2", "unit_weight": "3", "unit_price": "10"},
    ]))
    assert updated["header"]["total_count_price"] == Decimal("20.00")
    assert updated["header"]["total_weight_price"] == Decimal("60.00")
    assert len(updated["lines"]) == 1


def test_cannot_edit_approved_invoice():
    repo = FakePurchaseRepo()
    svc = make_service(repo)
    created = svc.create_draft(valid_form())
    inv_id = created["header"]["id"]
    rv = created["header"]["row_version"]
    svc.approve(inv_id, rv)
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.update_draft(inv_id, rv + 1, valid_form())


def test_stale_update_raises_concurrency_error():
    repo = FakePurchaseRepo()
    svc = make_service(repo)
    created = svc.create_draft(valid_form())
    inv_id = created["header"]["id"]
    with pytest.raises(PurchaseInvoiceConcurrencyError):
        svc.update_draft(inv_id, 999, valid_form())


def test_cannot_delete_approved_invoice():
    repo = FakePurchaseRepo()
    svc = make_service(repo)
    created = svc.create_draft(valid_form())
    inv_id = created["header"]["id"]
    rv = created["header"]["row_version"]
    svc.approve(inv_id, rv)
    with pytest.raises(PurchaseInvoiceValidationError):
        svc.delete_draft(inv_id)


def test_delete_draft_ok():
    repo = FakePurchaseRepo()
    svc = make_service(repo)
    created = svc.create_draft(valid_form())
    assert svc.delete_draft(created["header"]["id"]) is True


def test_delete_all_counts():
    repo = FakePurchaseRepo()
    svc = make_service(repo)
    svc.create_draft(valid_form(invoice_number="Pur-1001"))
    svc.create_draft(valid_form(invoice_number="Pur-1002"))
    result = svc.delete_all_drafts()
    assert result == {"deleted": 2, "protected": 0}


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------
def test_save_requires_permission():
    svc = make_service(permission_check=lambda code: code != "purchases.purchase_invoices.save")
    with pytest.raises(PurchaseInvoicePermissionError):
        svc.create_draft(valid_form())


def test_delete_requires_permission():
    repo = FakePurchaseRepo()
    svc = make_service(repo)  # permissive create
    created = svc.create_draft(valid_form())
    guarded = PurchaseInvoiceService(
        repository=repo,
        permission_check=lambda code: code != "purchases.purchase_invoices.delete",
    )
    with pytest.raises(PurchaseInvoicePermissionError):
        guarded.delete_draft(created["header"]["id"])
