"""Unit tests for :class:`ProductionOrderService` (no real database).

An in-memory fake repository stands in for ``ProductionOrderRepository`` (and the
BOM reads it delegates to) so all business rules are verified deterministically:

* the expected-quantity Decimal maths (production_quantity × BOM per-unit),
* actual defaulting to expected, and deviation = actual − expected,
* production-quantity recalculation (expected recomputed, actual preserved),
* explicit BOM reload (expected rebuilt, actual reset, snapshots refreshed),
* BOM resolution (no BOM / one BOM / many BOMs / wrong product / empty BOM),
* validation (product, quantity, negative actual, duplicate, self-reference, ...),
* authoritative recomputation (caller-supplied expected/deviation are ignored),
* automatic ``PRO-<n>`` numbering, and permission enforcement.

The companion DB-backed guarantees (generated ``deviation`` column, FK/cascade,
unique constraints, atomic rollback, sequence, snapshot stability) live in
``tests/repositories/test_production_order_repository.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.production_order import format_number, parse_sequence_value
from app.services.production_order_service import (
    ProductionOrderPermissionError,
    ProductionOrderService,
    ProductionOrderValidationError,
)

# --- seed master data -------------------------------------------------------
FINISHED_ID = 100
OTHER_FINISHED_ID = 200
PRODUCTS = {
    FINISHED_ID: {"id": FINISHED_ID, "item_code": 2001, "item_name": "خرسانة",
                  "unit": "متر مكعب", "item_type": "منتج تام", "price": Decimal("0")},
    OTHER_FINISHED_ID: {"id": OTHER_FINISHED_ID, "item_code": 2002,
                        "item_name": "بلوك", "unit": "قطعة", "item_type": "منتج تام",
                        "price": Decimal("0")},
    1: {"id": 1, "item_code": 1001, "item_name": "أسمنت", "unit": "شيكارة",
        "item_type": "مادة خام", "price": Decimal("10.00")},
    2: {"id": 2, "item_code": 1002, "item_name": "رمل", "unit": "متر مكعب",
        "item_type": "مادة خام", "price": Decimal("4.00")},
    3: {"id": 3, "item_code": 1003, "item_name": "زلط", "unit": "متر مكعب",
        "item_type": None, "price": Decimal("7.50")},
}


def _bom_line(component_id, qty, price):
    p = PRODUCTS[component_id]
    return {
        "component_product_id": component_id,
        "item_code_snapshot": p["item_code"],
        "item_name_snapshot": p["item_name"],
        "unit_snapshot": p["unit"],
        "quantity": Decimal(str(qty)),
        "price": Decimal(str(price)),
    }


class FakeProductionOrderRepo:
    """In-memory stand-in for ProductionOrderRepository (incl. its BOM reads)."""

    def __init__(self, products=None, boms=None):
        self.products = {pid: dict(p) for pid, p in (products or PRODUCTS).items()}
        # boms: {bom_id: {"header": {...}, "lines": [...]}}
        self.boms: dict[int, dict] = boms if boms is not None else _default_boms()
        self.orders: dict[int, dict] = {}
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

    # -- BOM reads --
    def find_boms_for_product(self, product_id, limit=100):
        rows = [
            {"id": bid, **{k: v for k, v in b["header"].items() if k != "id"}}
            for bid, b in self.boms.items()
            if int(b["header"]["product_id"]) == int(product_id)
        ]
        # most recent first (highest id)
        return sorted(rows, key=lambda r: r["id"], reverse=True)[:limit]

    def load_bom(self, bom_id):
        bom = self.boms.get(int(bom_id))
        if bom is None:
            return None
        return {"header": dict(bom["header"]), "lines": [dict(x) for x in bom["lines"]]}

    # -- numbering --
    def reserve_order_number(self):
        value = self.next_reserved_seq
        self.next_reserved_seq += 1
        return format_number(value)

    def peek_next_number(self):
        return format_number(self.next_reserved_seq)

    def order_number_exists(self, number, exclude_id=None):
        for order in self.orders.values():
            h = order["header"]
            if h["order_number"] == number and h["id"] != exclude_id:
                return True
        return False

    # -- writes --
    def _materialize(self, header, lines, order_id):
        h = dict(header)
        h["id"] = order_id
        h.setdefault("created_at", None)
        h.setdefault("updated_at", None)
        stored_lines = []
        for idx, line in enumerate(lines, start=1):
            row = {**line, "id": idx, "production_order_id": order_id,
                   "line_number": idx}
            # DB computes deviation as a generated column; mirror that here.
            row["deviation"] = Decimal(str(line["actual_quantity"])) - Decimal(
                str(line["expected_quantity"]))
            stored_lines.append(row)
        return {"header": h, "lines": stored_lines}

    def insert_order(self, header, lines):
        self.inserted_headers.append(dict(header))
        self.inserted_line_batches.append([dict(x) for x in lines])
        order_id = self._next_id
        self._next_id += 1
        self.orders[order_id] = self._materialize(header, lines, order_id)
        return self.orders[order_id]

    def update_order(self, order_id, header_changes, lines):
        order = self.orders.get(int(order_id))
        if order is None:
            return None
        order["header"].update(header_changes)
        self.inserted_line_batches.append([dict(x) for x in lines])
        order["lines"] = self._materialize(order["header"], lines, int(order_id))["lines"]
        return order

    def load_order(self, order_id):
        return self.orders.get(int(order_id))

    def delete_order(self, order_id):
        return self.orders.pop(int(order_id), None) is not None

    def search_orders(self, keyword="", limit=300, **kwargs):
        return [dict(o["header"]) for o in self.orders.values()][:limit]


def _default_boms():
    """One BOM for FINISHED_ID: أسمنت ×5, رمل ×2 (per finished unit)."""
    return {
        10: {
            "header": {"id": 10, "bom_number": "BOM-0001",
                       "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
            "lines": [_bom_line(1, "5", "10.00"), _bom_line(2, "2", "4.00")],
        }
    }


def make_service(repo=None, permission_check=None):
    return ProductionOrderService(repository=repo or FakeProductionOrderRepo(),
                                  permission_check=permission_check)


def valid_form(**overrides):
    form = {
        "order_number": "",   # blank -> reserve an automatic PRO-<n>
        "order_date": date(2026, 8, 17),
        "product_id": FINISHED_ID,
        "bom_id": None,       # single BOM -> auto-resolved
        "production_quantity": "10",
        "lines": [],          # actual quantities default to expected
    }
    form.update(overrides)
    return form


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def test_number_formatting_and_parsing_roundtrip():
    assert format_number(1) == "PRO-001"
    assert format_number(2) == "PRO-002"
    assert format_number(999) == "PRO-999"
    assert format_number(1000) == "PRO-1000"   # padding is a minimum, not a cap
    assert parse_sequence_value("PRO-001") == 1
    assert parse_sequence_value("PRO-042") == 42
    assert parse_sequence_value("1") is None
    assert parse_sequence_value("BOM-9") is None
    assert parse_sequence_value("") is None


def test_reserve_number_uses_pro_prefix():
    svc = make_service()
    assert svc.reserve_order_number() == "PRO-001"
    assert svc.reserve_order_number() == "PRO-002"


def test_blank_number_reserves_automatic_number_on_save():
    svc = make_service()
    result = svc.create_order(valid_form(order_number=""))
    assert result["header"]["order_number"] == "PRO-001"


def test_manual_number_uniqueness_enforced():
    repo = FakeProductionOrderRepo()
    svc = make_service(repo)
    svc.create_order(valid_form(order_number="PRO-050"))
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(order_number="PRO-050"))


# ---------------------------------------------------------------------------
# Expected-quantity calculation
# ---------------------------------------------------------------------------
def test_expected_is_production_qty_times_bom_per_unit():
    svc = make_service()
    # 10 × 5 = 50
    assert svc.compute_expected(Decimal("10"), Decimal("5")) == Decimal("50.000")


def test_ten_times_five_equals_fifty_on_save():
    svc = make_service()
    result = svc.create_order(valid_form(production_quantity="10"))
    lines = {ln["component_product_id"]: ln for ln in result["lines"]}
    assert lines[1]["expected_quantity"] == Decimal("50.000")   # أسمنت 5 × 10
    assert lines[2]["expected_quantity"] == Decimal("20.000")   # رمل   2 × 10


def test_decimal_production_quantity():
    svc = make_service()
    result = svc.create_order(valid_form(production_quantity="2.5"))
    lines = {ln["component_product_id"]: ln for ln in result["lines"]}
    assert lines[1]["expected_quantity"] == Decimal("12.500")   # 5 × 2.5
    assert lines[2]["expected_quantity"] == Decimal("5.000")    # 2 × 2.5


def test_decimal_bom_quantity():
    # A BOM whose component per-unit quantity is fractional.
    boms = {
        10: {"header": {"id": 10, "bom_number": "BOM-0001",
                        "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
             "lines": [_bom_line(1, "1.25", "10.00")]},
    }
    repo = FakeProductionOrderRepo(boms=boms)
    svc = make_service(repo)
    result = svc.create_order(valid_form(production_quantity="4"))
    assert result["lines"][0]["expected_quantity"] == Decimal("5.000")   # 1.25 × 4


def test_multiple_components_all_calculated():
    boms = {
        10: {"header": {"id": 10, "bom_number": "BOM-0001",
                        "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
             "lines": [_bom_line(1, "5", "10.00"), _bom_line(2, "2", "4.00"),
                       _bom_line(3, "3", "7.50")]},
    }
    svc = make_service(FakeProductionOrderRepo(boms=boms))
    result = svc.create_order(valid_form(production_quantity="10"))
    assert len(result["lines"]) == 3
    lines = {ln["component_product_id"]: ln for ln in result["lines"]}
    assert lines[3]["expected_quantity"] == Decimal("30.000")


def test_amounts_are_decimal_never_float():
    svc = make_service()
    result = svc.create_order(valid_form())
    for line in result["lines"]:
        assert isinstance(line["expected_quantity"], Decimal)
        assert isinstance(line["actual_quantity"], Decimal)
        assert isinstance(line["bom_quantity_per_unit"], Decimal)


# ---------------------------------------------------------------------------
# Actual quantity + deviation
# ---------------------------------------------------------------------------
def test_actual_defaults_to_expected_when_not_supplied():
    svc = make_service()
    result = svc.create_order(valid_form())
    for line in result["lines"]:
        assert line["actual_quantity"] == line["expected_quantity"]
        assert line["deviation"] == Decimal("0.000")


def test_positive_deviation():
    svc = make_service()
    # أسمنت expected = 50; submit actual 52 -> +2
    result = svc.create_order(valid_form(lines=[
        {"component_product_id": 1, "actual_quantity": "52"},
    ]))
    line = {ln["component_product_id"]: ln for ln in result["lines"]}[1]
    assert line["expected_quantity"] == Decimal("50.000")
    assert line["actual_quantity"] == Decimal("52.000")
    assert line["deviation"] == Decimal("2.000")


def test_negative_deviation():
    svc = make_service()
    result = svc.create_order(valid_form(lines=[
        {"component_product_id": 1, "actual_quantity": "48"},
    ]))
    line = {ln["component_product_id"]: ln for ln in result["lines"]}[1]
    assert line["deviation"] == Decimal("-2.000")


def test_zero_deviation():
    svc = make_service()
    result = svc.create_order(valid_form(lines=[
        {"component_product_id": 1, "actual_quantity": "50"},
    ]))
    line = {ln["component_product_id"]: ln for ln in result["lines"]}[1]
    assert line["deviation"] == Decimal("0.000")


def test_actual_zero_allowed():
    svc = make_service()
    result = svc.create_order(valid_form(lines=[
        {"component_product_id": 1, "actual_quantity": "0"},
    ]))
    line = {ln["component_product_id"]: ln for ln in result["lines"]}[1]
    assert line["actual_quantity"] == Decimal("0.000")
    assert line["deviation"] == Decimal("-50.000")


def test_negative_actual_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(lines=[
            {"component_product_id": 1, "actual_quantity": "-1"},
        ]))


# ---------------------------------------------------------------------------
# Authoritative recomputation (caller values ignored)
# ---------------------------------------------------------------------------
def test_caller_supplied_expected_and_deviation_are_ignored():
    repo = FakeProductionOrderRepo()
    svc = make_service(repo)
    svc.create_order(valid_form(lines=[
        {"component_product_id": 1, "actual_quantity": "52",
         "expected_quantity": "999", "deviation": "999"},  # bogus — must be ignored
    ]))
    stored = repo.inserted_line_batches[0]
    by_component = {ln["component_product_id"]: ln for ln in stored}
    # Expected is recomputed (5 × 10 = 50), never the caller's bogus 999.
    assert by_component[1]["expected_quantity"] == Decimal("50.000")
    # The service's own deviation (actual − expected = 52 − 50) wins over caller 999.
    assert by_component[1]["deviation"] == Decimal("2.000")


def test_product_name_snapshot_comes_from_master_not_caller():
    svc = make_service()
    result = svc.create_order(valid_form(product_name_snapshot="مزيّف"))
    assert result["header"]["product_name_snapshot"] == "خرسانة"
    assert result["header"]["product_id"] == FINISHED_ID


def test_bom_id_stored_on_header():
    svc = make_service()
    result = svc.create_order(valid_form())
    assert result["header"]["bom_id"] == 10


# ---------------------------------------------------------------------------
# Production-quantity recalculation (expected recomputed, actual preserved)
# ---------------------------------------------------------------------------
def test_recalculate_for_quantity_preserves_actual():
    svc = make_service()
    # Initial: qty 10, per-unit 5 -> expected 50; user changes actual to 52.
    lines = [{
        "component_product_id": 1,
        "bom_quantity_per_unit": Decimal("5"),
        "expected_quantity": Decimal("50.000"),
        "actual_quantity": Decimal("52.000"),
    }]
    # Change production quantity to 12 -> expected 60; actual preserved 52; dev -8.
    updated = svc.recalculate_for_quantity(lines, "12")
    assert updated[0]["expected_quantity"] == Decimal("60.000")
    assert updated[0]["actual_quantity"] == Decimal("52.000")
    assert updated[0]["deviation"] == Decimal("-8.000")


def test_recalculate_for_quantity_multiple_lines():
    svc = make_service()
    lines = [
        {"component_product_id": 1, "bom_quantity_per_unit": Decimal("5"),
         "expected_quantity": Decimal("50.000"), "actual_quantity": Decimal("50.000")},
        {"component_product_id": 2, "bom_quantity_per_unit": Decimal("2"),
         "expected_quantity": Decimal("20.000"), "actual_quantity": Decimal("20.000")},
    ]
    updated = svc.recalculate_for_quantity(lines, "15")
    assert updated[0]["expected_quantity"] == Decimal("75.000")   # 5 × 15
    assert updated[1]["expected_quantity"] == Decimal("30.000")   # 2 × 15


def test_update_recomputes_expected_for_new_quantity_via_persistence():
    """Saving an update with a new production quantity recomputes expected."""
    repo = FakeProductionOrderRepo()
    svc = make_service(repo)
    created = svc.create_order(valid_form(production_quantity="10"))
    order_id = created["header"]["id"]
    # Preserve the user's actual (52 on أسمنت) while bumping quantity to 12.
    updated = svc.update_order(order_id, valid_form(
        production_quantity="12",
        lines=[{"component_product_id": 1, "actual_quantity": "52"}],
    ))
    line = {ln["component_product_id"]: ln for ln in updated["lines"]}[1]
    assert line["expected_quantity"] == Decimal("60.000")   # 5 × 12
    assert line["actual_quantity"] == Decimal("52.000")
    assert line["deviation"] == Decimal("-8.000")


# ---------------------------------------------------------------------------
# Explicit reload from BOM (expected rebuilt, actual reset, snapshots refreshed)
# ---------------------------------------------------------------------------
def test_load_materials_resets_actual_to_expected_and_refreshes_snapshots():
    svc = make_service()
    loaded = svc.load_materials(FINISHED_ID, "10")
    assert loaded["bom_id"] == 10
    assert loaded["production_quantity"] == Decimal("10.000")
    by_component = {ln["component_product_id"]: ln for ln in loaded["lines"]}
    assert by_component[1]["expected_quantity"] == Decimal("50.000")
    assert by_component[1]["actual_quantity"] == Decimal("50.000")  # reset to expected
    assert by_component[1]["deviation"] == Decimal("0.000")
    # snapshots refreshed from the BOM/master
    assert by_component[1]["item_code_snapshot"] == 1001
    assert by_component[1]["item_name_snapshot"] == "أسمنت"
    assert by_component[1]["unit_snapshot"] == "شيكارة"
    assert by_component[1]["bom_price_snapshot"] == Decimal("10.00")


def test_load_materials_requires_quantity_positive():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.load_materials(FINISHED_ID, "0")


# ---------------------------------------------------------------------------
# BOM resolution
# ---------------------------------------------------------------------------
def test_product_with_no_bom_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(product_id=OTHER_FINISHED_ID))  # no BOM


def test_single_bom_auto_selected():
    svc = make_service()
    bom_id, bom = svc.resolve_bom(FINISHED_ID, None)
    assert bom_id == 10
    assert len(bom["lines"]) == 2


def test_multiple_boms_without_selection_rejected():
    boms = _default_boms()
    boms[11] = {"header": {"id": 11, "bom_number": "BOM-0002",
                           "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
                "lines": [_bom_line(1, "6", "10.00")]}
    svc = make_service(FakeProductionOrderRepo(boms=boms))
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(bom_id=None))


def test_multiple_boms_with_explicit_selection_used():
    boms = _default_boms()
    boms[11] = {"header": {"id": 11, "bom_number": "BOM-0002",
                           "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
                "lines": [_bom_line(1, "6", "10.00")]}
    svc = make_service(FakeProductionOrderRepo(boms=boms))
    result = svc.create_order(valid_form(bom_id=11, production_quantity="10"))
    assert result["header"]["bom_id"] == 11
    assert len(result["lines"]) == 1
    assert result["lines"][0]["expected_quantity"] == Decimal("60.000")  # 6 × 10


def test_bom_not_belonging_to_product_rejected():
    # BOM 10 belongs to FINISHED_ID; pass it for OTHER_FINISHED_ID.
    boms = _default_boms()
    boms[12] = {"header": {"id": 12, "bom_number": "BOM-0003",
                           "product_id": OTHER_FINISHED_ID,
                           "product_name_snapshot": "بلوك"},
                "lines": [_bom_line(1, "1", "10.00")]}
    svc = make_service(FakeProductionOrderRepo(boms=boms))
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(product_id=OTHER_FINISHED_ID, bom_id=10))


def test_empty_bom_rejected():
    boms = {
        10: {"header": {"id": 10, "bom_number": "BOM-0001",
                        "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
             "lines": []},
    }
    svc = make_service(FakeProductionOrderRepo(boms=boms))
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_missing_product_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(product_id=None))


def test_unknown_product_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(product_id=999999))


def test_missing_production_quantity_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(production_quantity=None))


def test_zero_production_quantity_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(production_quantity="0"))


def test_negative_production_quantity_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(production_quantity="-5"))


def test_invalid_production_quantity_value_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(production_quantity="abc"))


def test_order_date_required():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form(order_date=None))


def test_duplicate_component_in_bom_rejected():
    # A malformed BOM with a repeated component: the order must reject it.
    boms = {
        10: {"header": {"id": 10, "bom_number": "BOM-0001",
                        "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
             "lines": [_bom_line(1, "5", "10.00"), _bom_line(1, "2", "10.00")]},
    }
    svc = make_service(FakeProductionOrderRepo(boms=boms))
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form())


def test_self_reference_component_rejected():
    # A BOM line whose component is the finished product itself.
    boms = {
        10: {"header": {"id": 10, "bom_number": "BOM-0001",
                        "product_id": FINISHED_ID, "product_name_snapshot": "خرسانة"},
             "lines": [_bom_line_self(FINISHED_ID, "1", "0.00")]},
    }
    svc = make_service(FakeProductionOrderRepo(boms=boms))
    with pytest.raises(ProductionOrderValidationError):
        svc.create_order(valid_form())


def _bom_line_self(component_id, qty, price):
    return {
        "component_product_id": component_id,
        "item_code_snapshot": PRODUCTS[component_id]["item_code"],
        "item_name_snapshot": PRODUCTS[component_id]["item_name"],
        "unit_snapshot": PRODUCTS[component_id]["unit"],
        "quantity": Decimal(str(qty)),
        "price": Decimal(str(price)),
    }


# ---------------------------------------------------------------------------
# Update / delete lifecycle
# ---------------------------------------------------------------------------
def test_update_missing_order_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.update_order(123456, valid_form())


def test_delete_missing_order_rejected():
    svc = make_service()
    with pytest.raises(ProductionOrderValidationError):
        svc.delete_order(123456)


def test_delete_ok():
    repo = FakeProductionOrderRepo()
    svc = make_service(repo)
    created = svc.create_order(valid_form())
    assert svc.delete_order(created["header"]["id"]) is True


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------
def test_save_requires_permission():
    svc = make_service(
        permission_check=lambda code: code != "manufacturing.production_orders.save")
    with pytest.raises(ProductionOrderPermissionError):
        svc.create_order(valid_form())


def test_update_requires_permission():
    repo = FakeProductionOrderRepo()
    svc = make_service(repo)  # permissive create
    created = svc.create_order(valid_form())
    guarded = ProductionOrderService(
        repository=repo,
        permission_check=lambda code: code != "manufacturing.production_orders.edit",
    )
    with pytest.raises(ProductionOrderPermissionError):
        guarded.update_order(created["header"]["id"], valid_form())


def test_delete_requires_permission():
    repo = FakeProductionOrderRepo()
    svc = make_service(repo)  # permissive create
    created = svc.create_order(valid_form())
    guarded = ProductionOrderService(
        repository=repo,
        permission_check=lambda code: code != "manufacturing.production_orders.delete",
    )
    with pytest.raises(ProductionOrderPermissionError):
        guarded.delete_order(created["header"]["id"])
