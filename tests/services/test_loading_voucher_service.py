"""Unit tests for :class:`LoadingVoucherService` (no real database).

An in-memory fake repository stands in for ``LoadingVoucherRepository`` so all
business rules are verified deterministically:

* automatic ``LV-<n>`` numbering (blank -> reserved) and manual-number uniqueness,
* customer / item snapshots taken from the master (caller-supplied names ignored),
* quantity is Decimal (never float), 3 dp, optional (blank -> None) but > 0 if given,
* optional driver name / vehicle number / customer / item (blank -> None),
* date/time defaulting and parsing,
* notes trimmed to None when blank,
* permission enforcement (save / edit / delete).

The companion DB-backed guarantees (sequence, DEFAULTs, FK/restrict, unique
constraint, positive-quantity CHECK, hard delete, snapshot stability) live in
``tests/repositories/test_loading_voucher_repository.py``.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from app.models.loading_voucher import format_number, parse_sequence_value
from app.services.loading_voucher_service import (
    LoadingVoucherPermissionError,
    LoadingVoucherService,
    LoadingVoucherValidationError,
)

# --- seed master data -------------------------------------------------------
CUSTOMER_ID = 1001
OTHER_CUSTOMER_ID = 1002
PRODUCT_ID = 5
CUSTOMERS = {
    CUSTOMER_ID: {"customer_id": CUSTOMER_ID, "customer_name": "شركة النور للتجارة",
                  "phone_number": "0100"},
    OTHER_CUSTOMER_ID: {"customer_id": OTHER_CUSTOMER_ID, "customer_name": "مؤسسة الفجر",
                        "phone_number": "0111"},
}
PRODUCTS = {
    PRODUCT_ID: {"id": PRODUCT_ID, "item_code": 2001, "item_name": "أسمنت مقاوم",
                 "unit": "طن", "item_type": "منتج تام", "price": Decimal("0")},
}


class FakeLoadingVoucherRepo:
    """In-memory stand-in for LoadingVoucherRepository."""

    def __init__(self, customers=None, products=None):
        self.customers = {cid: dict(c) for cid, c in (customers or CUSTOMERS).items()}
        self.products = {pid: dict(p) for pid, p in (products or PRODUCTS).items()}
        self.vouchers: dict[int, dict] = {}
        self._next_id = 1
        self.next_reserved_seq = 1
        self.inserted: list[dict] = []

    # -- master data --
    def get_customer(self, customer_id):
        c = self.customers.get(int(customer_id))
        return dict(c) if c is not None else None

    def search_customers(self, keyword, limit=100):
        return list(self.customers.values())[:limit]

    def get_product(self, product_id):
        p = self.products.get(int(product_id))
        return dict(p) if p is not None else None

    def search_products(self, keyword, limit=100):
        return list(self.products.values())[:limit]

    # -- numbering --
    def reserve_voucher_number(self):
        value = self.next_reserved_seq
        self.next_reserved_seq += 1
        return format_number(value)

    def peek_next_number(self):
        return format_number(self.next_reserved_seq)

    def voucher_number_exists(self, number, exclude_id=None):
        for v in self.vouchers.values():
            if v["voucher_number"] == number and v["id"] != exclude_id:
                return True
        return False

    # -- writes --
    def insert_voucher(self, header):
        self.inserted.append(dict(header))
        vid = self._next_id
        self._next_id += 1
        row = dict(header)
        row["id"] = vid
        row.setdefault("created_at", None)
        row.setdefault("updated_at", None)
        self.vouchers[vid] = row
        return row

    def update_voucher(self, voucher_id, header_changes):
        v = self.vouchers.get(int(voucher_id))
        if v is None:
            return None
        v.update(header_changes)
        return v

    def load_voucher(self, voucher_id):
        return self.vouchers.get(int(voucher_id))

    def delete_voucher(self, voucher_id):
        return self.vouchers.pop(int(voucher_id), None) is not None

    def search_vouchers(self, keyword="", limit=300, **kwargs):
        return list(self.vouchers.values())[:limit]


def make_service(repo=None, permission_check=None):
    return LoadingVoucherService(repository=repo or FakeLoadingVoucherRepo(),
                                 permission_check=permission_check)


def valid_form(**overrides):
    form = {
        "voucher_number": "",   # blank -> reserve an automatic LV-<n>
        "voucher_date": date(2026, 8, 18),
        "voucher_time": time(9, 30),
        "customer_id": CUSTOMER_ID,
        "driver_name": "محمد عبد الله",
        "vehicle_number": "أ ب ج 4213",
        "product_id": PRODUCT_ID,
        "quantity_tons": "25.000",
        "notes": "",
    }
    form.update(overrides)
    return form


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def test_number_formatting_and_parsing_roundtrip():
    assert format_number(1) == "LV-001"
    assert format_number(999) == "LV-999"
    assert format_number(1000) == "LV-1000"   # padding is a minimum, not a cap
    assert parse_sequence_value("LV-001") == 1
    assert parse_sequence_value("LV-042") == 42
    assert parse_sequence_value("1") is None
    assert parse_sequence_value("PRO-9") is None
    assert parse_sequence_value("") is None


def test_reserve_number_uses_lv_prefix():
    svc = make_service()
    assert svc.reserve_voucher_number() == "LV-001"
    assert svc.reserve_voucher_number() == "LV-002"


def test_blank_number_reserves_automatic_number_on_save():
    svc = make_service()
    result = svc.create_voucher(valid_form(voucher_number=""))
    assert result["voucher_number"] == "LV-001"


def test_manual_number_uniqueness_enforced():
    repo = FakeLoadingVoucherRepo()
    svc = make_service(repo)
    svc.create_voucher(valid_form(voucher_number="LV-050"))
    with pytest.raises(LoadingVoucherValidationError):
        svc.create_voucher(valid_form(voucher_number="LV-050"))


# ---------------------------------------------------------------------------
# Snapshots (from master, not caller)
# ---------------------------------------------------------------------------
def test_customer_snapshot_from_master_not_caller():
    svc = make_service()
    result = svc.create_voucher(valid_form(customer_name_snapshot="مزيّف"))
    assert result["customer_name_snapshot"] == "شركة النور للتجارة"
    assert result["customer_id"] == CUSTOMER_ID


def test_item_snapshot_from_master_not_caller():
    svc = make_service()
    result = svc.create_voucher(valid_form(
        item_name_snapshot="مزيّف", item_code_snapshot=999, unit_snapshot="مزيّف"))
    assert result["item_name_snapshot"] == "أسمنت مقاوم"
    assert result["item_code_snapshot"] == 2001
    assert result["unit_snapshot"] == "طن"
    assert result["product_id"] == PRODUCT_ID


# ---------------------------------------------------------------------------
# Quantity
# ---------------------------------------------------------------------------
def test_quantity_is_decimal_three_dp():
    svc = make_service()
    result = svc.create_voucher(valid_form(quantity_tons="12.75"))
    assert isinstance(result["quantity_tons"], Decimal)
    assert result["quantity_tons"] == Decimal("12.750")


def test_zero_quantity_rejected():
    svc = make_service()
    with pytest.raises(LoadingVoucherValidationError):
        svc.create_voucher(valid_form(quantity_tons="0"))


def test_negative_quantity_rejected():
    svc = make_service()
    with pytest.raises(LoadingVoucherValidationError):
        svc.create_voucher(valid_form(quantity_tons="-5"))


def test_missing_quantity_allowed_stored_none():
    # Quantity is optional (v1): a blank quantity saves as None, not an error.
    svc = make_service()
    result = svc.create_voucher(valid_form(quantity_tons=None))
    assert result["quantity_tons"] is None
    result2 = svc.create_voucher(valid_form(quantity_tons=""))
    assert result2["quantity_tons"] is None


def test_invalid_quantity_value_rejected():
    # A present-but-non-numeric quantity is still an error.
    svc = make_service()
    with pytest.raises(LoadingVoucherValidationError):
        svc.create_voucher(valid_form(quantity_tons="abc"))


# ---------------------------------------------------------------------------
# Optional free-text driver / vehicle
# ---------------------------------------------------------------------------
def test_driver_name_optional_blank_to_none():
    svc = make_service()
    result = svc.create_voucher(valid_form(driver_name="   "))
    assert result["driver_name"] is None


def test_vehicle_number_optional_blank_to_none():
    svc = make_service()
    result = svc.create_voucher(valid_form(vehicle_number=""))
    assert result["vehicle_number"] is None


def test_driver_and_vehicle_trimmed():
    svc = make_service()
    result = svc.create_voucher(valid_form(
        driver_name="  خالد  ", vehicle_number="  1234  "))
    assert result["driver_name"] == "خالد"
    assert result["vehicle_number"] == "1234"


# ---------------------------------------------------------------------------
# Optional vehicle weights — FREE TEXT (stored literally, incl. any unit)
# ---------------------------------------------------------------------------
def test_weights_optional_stored_none_by_default():
    svc = make_service()
    result = svc.create_voucher(valid_form())  # no weights in valid_form
    assert result["weight_before_loading"] is None
    assert result["weight_after_loading"] is None


def test_weights_stored_literally_with_unit():
    # Free text: "500k" / "750 كجم" are kept exactly as typed — nothing stripped.
    svc = make_service()
    result = svc.create_voucher(valid_form(
        weight_before_loading="500k", weight_after_loading="750 كجم"))
    assert result["weight_before_loading"] == "500k"
    assert result["weight_after_loading"] == "750 كجم"


def test_weights_trimmed_and_blank_to_none():
    svc = make_service()
    result = svc.create_voucher(valid_form(
        weight_before_loading="  500 طن  ", weight_after_loading="   "))
    assert result["weight_before_loading"] == "500 طن"
    assert result["weight_after_loading"] is None


def test_quantity_with_unit_label_accepted():
    # Quantity stays numeric (tons) with tolerant parsing — unit label ignored.
    svc = make_service()
    result = svc.create_voucher(valid_form(quantity_tons="12.5 طن"))
    assert result["quantity_tons"] == Decimal("12.500")


def test_quantity_arabic_digits_accepted():
    svc = make_service()
    result = svc.create_voucher(valid_form(quantity_tons="١٠٠"))
    assert result["quantity_tons"] == Decimal("100.000")


# ---------------------------------------------------------------------------
# Customer / item — optional, but a supplied unknown id is still rejected
# ---------------------------------------------------------------------------
def test_missing_customer_allowed():
    svc = make_service()
    result = svc.create_voucher(valid_form(customer_id=None))
    assert result["customer_id"] is None
    assert result["customer_name_snapshot"] is None


def test_unknown_customer_rejected():
    svc = make_service()
    with pytest.raises(LoadingVoucherValidationError):
        svc.create_voucher(valid_form(customer_id=999999))


def test_missing_item_allowed():
    svc = make_service()
    result = svc.create_voucher(valid_form(product_id=None))
    assert result["product_id"] is None
    assert result["item_name_snapshot"] is None


def test_unknown_item_rejected():
    svc = make_service()
    with pytest.raises(LoadingVoucherValidationError):
        svc.create_voucher(valid_form(product_id=999999))


def test_fully_blank_voucher_allowed():
    # The extreme case of "everything optional": only an auto number + date/time.
    svc = make_service()
    result = svc.create_voucher(valid_form(
        customer_id=None, product_id=None, driver_name="",
        vehicle_number="", quantity_tons="", notes=""))
    assert result["voucher_number"] == "LV-001"
    assert result["customer_id"] is None
    assert result["product_id"] is None
    assert result["driver_name"] is None
    assert result["vehicle_number"] is None
    assert result["quantity_tons"] is None
    assert result["notes"] is None


# ---------------------------------------------------------------------------
# Date / time / notes
# ---------------------------------------------------------------------------
def test_blank_date_defaults_to_today():
    svc = make_service()
    result = svc.create_voucher(valid_form(voucher_date=""))
    assert result["voucher_date"] == date.today()


def test_blank_time_defaults_to_now():
    svc = make_service()
    result = svc.create_voucher(valid_form(voucher_time=""))
    assert isinstance(result["voucher_time"], time)


def test_iso_date_string_parsed():
    svc = make_service()
    result = svc.create_voucher(valid_form(voucher_date="2026-08-18"))
    assert result["voucher_date"] == date(2026, 8, 18)


def test_time_string_parsed():
    svc = make_service()
    result = svc.create_voucher(valid_form(voucher_time="14:05"))
    assert result["voucher_time"] == time(14, 5)


def test_blank_notes_stored_as_none():
    svc = make_service()
    result = svc.create_voucher(valid_form(notes="   "))
    assert result["notes"] is None


def test_notes_trimmed_and_kept():
    svc = make_service()
    result = svc.create_voucher(valid_form(notes="  تحميل من المستودع  "))
    assert result["notes"] == "تحميل من المستودع"


# ---------------------------------------------------------------------------
# Update / delete lifecycle
# ---------------------------------------------------------------------------
def test_update_changes_fields():
    repo = FakeLoadingVoucherRepo()
    svc = make_service(repo)
    created = svc.create_voucher(valid_form())
    vid = created["id"]
    updated = svc.update_voucher(vid, valid_form(
        quantity_tons="30.5", customer_id=OTHER_CUSTOMER_ID))
    assert updated["quantity_tons"] == Decimal("30.500")
    assert updated["customer_id"] == OTHER_CUSTOMER_ID
    assert updated["customer_name_snapshot"] == "مؤسسة الفجر"


def test_update_missing_voucher_rejected():
    svc = make_service()
    with pytest.raises(LoadingVoucherValidationError):
        svc.update_voucher(123456, valid_form())


def test_delete_missing_voucher_rejected():
    svc = make_service()
    with pytest.raises(LoadingVoucherValidationError):
        svc.delete_voucher(123456)


def test_delete_ok():
    repo = FakeLoadingVoucherRepo()
    svc = make_service(repo)
    created = svc.create_voucher(valid_form())
    assert svc.delete_voucher(created["id"]) is True


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------
def test_save_requires_permission():
    svc = make_service(
        permission_check=lambda code: code != "logistics.loading_vouchers.save")
    with pytest.raises(LoadingVoucherPermissionError):
        svc.create_voucher(valid_form())


def test_update_requires_permission():
    repo = FakeLoadingVoucherRepo()
    svc = make_service(repo)  # permissive create
    created = svc.create_voucher(valid_form())
    guarded = LoadingVoucherService(
        repository=repo,
        permission_check=lambda code: code != "logistics.loading_vouchers.edit",
    )
    with pytest.raises(LoadingVoucherPermissionError):
        guarded.update_voucher(created["id"], valid_form())


def test_delete_requires_permission():
    repo = FakeLoadingVoucherRepo()
    svc = make_service(repo)  # permissive create
    created = svc.create_voucher(valid_form())
    guarded = LoadingVoucherService(
        repository=repo,
        permission_check=lambda code: code != "logistics.loading_vouchers.delete",
    )
    with pytest.raises(LoadingVoucherPermissionError):
        guarded.delete_voucher(created["id"])
