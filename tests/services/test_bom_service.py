"""Unit tests for :class:`BomService` (no real database).

An in-memory fake repository stands in for ``BomRepository`` so all business
rules are verified deterministically: the quantity/price/money Decimal maths of
the line totals and the header total, server-side product snapshots (caller
totals never trusted), component-existence / self-reference / duplicate rules,
quantity/price validation, automatic ``BOM-<n>`` numbering, the create / update /
remove-line recalculation lifecycle, and permission enforcement.

The companion DB-backed guarantees (generated ``line_total`` column, FK/cascade,
unique constraints, atomic rollback, sequence) live in
``tests/repositories/test_bom_repository.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.bom import format_number, parse_sequence_value
from app.services.bom_service import (
    BomService,
    BomServicePermissionError,
    BomServiceValidationError,
)

# --- seed master data -------------------------------------------------------
# One finished product (منتج تام) and a handful of raw-material components
# (مادة خام). item_type is present but the service intentionally does not enforce
# it (legacy rows may be NULL); it is here only to prove that.
FINISHED_ID = 100
PRODUCTS = {
    FINISHED_ID: {"id": FINISHED_ID, "item_code": 2001, "item_name": "منتج تام",
                  "unit": "قطعة", "item_type": "منتج تام", "price": Decimal("0")},
    1: {"id": 1, "item_code": 1001, "item_name": "خشب", "unit": "متر",
        "item_type": "مادة خام", "price": Decimal("10.00")},
    2: {"id": 2, "item_code": 1002, "item_name": "مسامير", "unit": "كيس",
        "item_type": "مادة خام", "price": Decimal("4.00")},
    3: {"id": 3, "item_code": 1003, "item_name": "دهان", "unit": "لتر",
        "item_type": None, "price": Decimal("7.50")},
}


class FakeBomRepo:
    """In-memory stand-in for BomRepository."""

    def __init__(self, products=None):
        self.products = {pid: dict(p) for pid, p in (products or PRODUCTS).items()}
        self.boms: dict[int, dict] = {}
        self._next_id = 1
        self.next_reserved_seq = 1
        # instrumentation
        self.inserted_headers: list[dict] = []
        self.inserted_line_batches: list[list[dict]] = []

    # -- master data --
    def get_product(self, product_id):
        p = self.products.get(int(product_id))
        return dict(p) if p is not None else None

    def search_products(self, keyword, limit=100):
        return list(self.products.values())[:limit]

    # -- numbering --
    def reserve_bom_number(self):
        value = self.next_reserved_seq
        self.next_reserved_seq += 1
        return format_number(value)

    def peek_next_number(self):
        return format_number(self.next_reserved_seq)

    def bom_number_exists(self, number, exclude_id=None):
        for bom in self.boms.values():
            h = bom["header"]
            if h["bom_number"] == number and h["id"] != exclude_id:
                return True
        return False

    # -- writes --
    def _materialize(self, header, lines, bom_id):
        h = dict(header)
        h["id"] = bom_id
        h.setdefault("created_at", None)
        h.setdefault("updated_at", None)
        stored_lines = [
            {**line, "id": idx, "bom_id": bom_id, "line_number": idx}
            for idx, line in enumerate(lines, start=1)
        ]
        return {"header": h, "lines": stored_lines}

    def insert_bom(self, header, lines):
        self.inserted_headers.append(dict(header))
        self.inserted_line_batches.append([dict(x) for x in lines])
        bom_id = self._next_id
        self._next_id += 1
        self.boms[bom_id] = self._materialize(header, lines, bom_id)
        return self.boms[bom_id]

    def update_bom(self, bom_id, header_changes, lines):
        bom = self.boms.get(int(bom_id))
        if bom is None:
            return None
        bom["header"].update(header_changes)
        bom["lines"] = [
            {**line, "id": idx, "bom_id": int(bom_id), "line_number": idx}
            for idx, line in enumerate(lines, start=1)
        ]
        return bom

    def load_bom(self, bom_id):
        return self.boms.get(int(bom_id))

    def delete_bom(self, bom_id):
        return self.boms.pop(int(bom_id), None) is not None


def make_service(repo=None, permission_check=None):
    return BomService(repository=repo or FakeBomRepo(),
                      permission_check=permission_check)


def valid_form(**overrides):
    form = {
        "bom_number": "",  # blank -> reserve an automatic BOM-<n>
        "bom_date": date(2026, 8, 17),
        "product_id": FINISHED_ID,
        "lines": [
            {"component_product_id": 1, "quantity": "2", "price": "5"},
        ],
    }
    form.update(overrides)
    return form


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def test_number_formatting_and_parsing_roundtrip():
    assert format_number(1) == "BOM-0001"
    assert format_number(2) == "BOM-0002"
    assert format_number(10000) == "BOM-10000"  # padding is a minimum, not a cap
    assert parse_sequence_value("BOM-0001") == 1
    assert parse_sequence_value("BOM-0042") == 42
    assert parse_sequence_value("1") is None       # bare numeric is not BOM-<n>
    assert parse_sequence_value("INV-9") is None
    assert parse_sequence_value("") is None


def test_reserve_number_uses_bom_prefix():
    svc = make_service()
    assert svc.reserve_bom_number() == "BOM-0001"
    assert svc.reserve_bom_number() == "BOM-0002"


def test_blank_number_reserves_automatic_number_on_save():
    repo = FakeBomRepo()
    svc = make_service(repo)
    result = svc.create_bom(valid_form(bom_number=""))
    assert result["header"]["bom_number"] == "BOM-0001"


# ---------------------------------------------------------------------------
# Line + total maths
# ---------------------------------------------------------------------------
def test_line_total_is_quantity_times_price():
    svc = make_service()
    # 2.5 × 10.00 = 25.00
    assert svc.compute_line_total(Decimal("2.5"), Decimal("10.00")) == Decimal("25.00")


def test_total_material_cost_sums_all_line_totals():
    repo = FakeBomRepo()
    svc = make_service(repo)
    result = svc.create_bom(valid_form(lines=[
        {"component_product_id": 1, "quantity": "2.5", "price": "10.00"},  # 25.00
        {"component_product_id": 2, "quantity": "3", "price": "4.00"},     # 12.00
        {"component_product_id": 3, "quantity": "1.5", "price": "7.50"},   # 11.25
    ]))
    header = result["header"]
    assert header["total_material_cost"] == Decimal("48.25")
    lines = result["lines"]
    assert [ln["line_total"] for ln in lines] == [
        Decimal("25.00"), Decimal("12.00"), Decimal("11.25")
    ]


def test_amounts_are_decimal_never_float():
    svc = make_service()
    assert isinstance(svc.compute_line_total(Decimal("1.5"), Decimal("2")), Decimal)
    result = svc.create_bom(valid_form())
    assert isinstance(result["header"]["total_material_cost"], Decimal)
    for line in result["lines"]:
        assert isinstance(line["line_total"], Decimal)
        assert isinstance(line["quantity"], Decimal)
        assert isinstance(line["price"], Decimal)


def test_caller_supplied_total_is_ignored_and_recomputed():
    repo = FakeBomRepo()
    svc = make_service(repo)
    svc.create_bom(valid_form(
        total_material_cost="99999",  # bogus — must be ignored
        lines=[{"component_product_id": 1, "quantity": "2", "price": "10.00"}],
    ))
    stored = repo.inserted_headers[0]
    assert stored["total_material_cost"] == Decimal("20.00")


# ---------------------------------------------------------------------------
# Price behaviour + snapshots
# ---------------------------------------------------------------------------
def test_price_defaults_to_product_price_when_not_supplied():
    svc = make_service()
    # component 1 has master price 10.00; quantity 3 -> 30.00
    result = svc.create_bom(valid_form(lines=[
        {"component_product_id": 1, "quantity": "3"},
    ]))
    line = result["lines"][0]
    assert line["price"] == Decimal("10.00")
    assert line["line_total"] == Decimal("30.00")


def test_line_stores_item_snapshots_from_master():
    svc = make_service()
    result = svc.create_bom(valid_form(lines=[
        {"component_product_id": 2, "quantity": "1", "price": "4.00"},
    ]))
    line = result["lines"][0]
    assert line["item_code_snapshot"] == 1002
    assert line["item_name_snapshot"] == "مسامير"
    assert line["unit_snapshot"] == "كيس"


def test_product_name_snapshot_comes_from_master_not_caller():
    svc = make_service()
    result = svc.create_bom(valid_form(product_name_snapshot="مزيّف"))
    assert result["header"]["product_name_snapshot"] == "منتج تام"
    assert result["header"]["product_id"] == FINISHED_ID


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_at_least_one_line_required():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[]))


def test_bom_date_required():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(bom_date=None))


def test_finished_product_required():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(product_id=None))


def test_unknown_finished_product_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(product_id=999999))


def test_unknown_component_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[
            {"component_product_id": 888888, "quantity": "1", "price": "1"},
        ]))


def test_zero_quantity_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[
            {"component_product_id": 1, "quantity": "0", "price": "5"},
        ]))


def test_negative_quantity_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[
            {"component_product_id": 1, "quantity": "-2", "price": "5"},
        ]))


def test_negative_price_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[
            {"component_product_id": 1, "quantity": "2", "price": "-5"},
        ]))


def test_invalid_quantity_value_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[
            {"component_product_id": 1, "quantity": "abc", "price": "5"},
        ]))


def test_component_missing_id_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[
            {"component_product_id": None, "quantity": "2", "price": "5"},
        ]))


# ---------------------------------------------------------------------------
# Duplicate components + finished-product self-reference
# ---------------------------------------------------------------------------
def test_duplicate_component_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[
            {"component_product_id": 1, "quantity": "2", "price": "5"},
            {"component_product_id": 1, "quantity": "3", "price": "5"},
        ]))


def test_finished_product_cannot_be_its_own_component():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.create_bom(valid_form(lines=[
            {"component_product_id": FINISHED_ID, "quantity": "1", "price": "5"},
        ]))


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
def test_save_bom_with_multiple_components_returns_correct_totals():
    repo = FakeBomRepo()
    svc = make_service(repo)
    result = svc.create_bom(valid_form(lines=[
        {"component_product_id": 1, "quantity": "2", "price": "10.00"},  # 20.00
        {"component_product_id": 2, "quantity": "5", "price": "4.00"},   # 20.00
    ]))
    assert result["header"]["total_material_cost"] == Decimal("40.00")
    assert len(result["lines"]) == 2


# ---------------------------------------------------------------------------
# Update / remove line lifecycle
# ---------------------------------------------------------------------------
def test_update_recomputes_total_after_quantity_and_price_change():
    repo = FakeBomRepo()
    svc = make_service(repo)
    created = svc.create_bom(valid_form())
    bom_id = created["header"]["id"]
    updated = svc.update_bom(bom_id, valid_form(lines=[
        {"component_product_id": 1, "quantity": "4", "price": "10.00"},  # 40.00
        {"component_product_id": 2, "quantity": "2", "price": "4.00"},   # 8.00
    ]))
    assert updated["header"]["total_material_cost"] == Decimal("48.00")
    assert len(updated["lines"]) == 2


def test_removing_a_component_recomputes_total():
    repo = FakeBomRepo()
    svc = make_service(repo)
    created = svc.create_bom(valid_form(lines=[
        {"component_product_id": 1, "quantity": "2", "price": "10.00"},  # 20.00
        {"component_product_id": 2, "quantity": "5", "price": "4.00"},   # 20.00
    ]))
    bom_id = created["header"]["id"]
    assert created["header"]["total_material_cost"] == Decimal("40.00")
    # Remove the second component.
    updated = svc.update_bom(bom_id, valid_form(lines=[
        {"component_product_id": 1, "quantity": "2", "price": "10.00"},
    ]))
    assert updated["header"]["total_material_cost"] == Decimal("20.00")
    assert len(updated["lines"]) == 1


def test_update_missing_bom_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.update_bom(123456, valid_form())


def test_delete_missing_bom_rejected():
    svc = make_service()
    with pytest.raises(BomServiceValidationError):
        svc.delete_bom(123456)


def test_delete_ok():
    repo = FakeBomRepo()
    svc = make_service(repo)
    created = svc.create_bom(valid_form())
    assert svc.delete_bom(created["header"]["id"]) is True


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------
def test_save_requires_permission():
    svc = make_service(permission_check=lambda code: code != "manufacturing.boms.save")
    with pytest.raises(BomServicePermissionError):
        svc.create_bom(valid_form())


def test_update_requires_permission():
    repo = FakeBomRepo()
    svc = make_service(repo)  # permissive create
    created = svc.create_bom(valid_form())
    guarded = BomService(
        repository=repo,
        permission_check=lambda code: code != "manufacturing.boms.edit",
    )
    with pytest.raises(BomServicePermissionError):
        guarded.update_bom(created["header"]["id"], valid_form())


def test_delete_requires_permission():
    repo = FakeBomRepo()
    svc = make_service(repo)  # permissive create
    created = svc.create_bom(valid_form())
    guarded = BomService(
        repository=repo,
        permission_check=lambda code: code != "manufacturing.boms.delete",
    )
    with pytest.raises(BomServicePermissionError):
        guarded.delete_bom(created["header"]["id"])
