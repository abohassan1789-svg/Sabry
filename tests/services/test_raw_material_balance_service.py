"""Unit tests for the Raw-Material Warehouse service (مخزن مواد الخام).

A fake repository returns canned per-product rows (opening / purchased / issued);
the tests pin the balance arithmetic (opening + purchases − issued), the trimmed
quantity formatting, the per-row status thresholds, the four KPI totals, the
picker guard and the item-name filter passthrough. No database, no Qt.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.raw_material_balance_service import (
    REPORT_COLUMNS,
    STATUS_LOW,
    STATUS_MID,
    STATUS_NONE,
    STATUS_OK,
    RawMaterialBalanceRequest,
    RawMaterialBalanceService,
)


class _FakeRepo:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []
        self.last_filters = None
        self.picker_calls: list[tuple[str, int]] = []

    def fetch_balances(self, filters):
        self.last_filters = filters
        return list(self._rows)

    def search_raw_materials(self, keyword="", limit=500):
        self.picker_calls.append((keyword, limit))
        return [{"item_code": 1001, "item_name": "بتروميل", "unit": "كيس"}]


def _svc(rows=None):
    repo = _FakeRepo(rows)
    return RawMaterialBalanceService(repository=repo), repo


_ROWS = [
    {"product_id": 1, "item_code": 1001, "item_name": "بتروميل", "unit": "كيس",
     "opening_balance": Decimal("500"), "purchased": Decimal("1200"), "issued": Decimal("900")},
    {"product_id": 5, "item_code": 1005, "item_name": "حديد تسليح", "unit": "طن",
     "opening_balance": Decimal("15"), "purchased": Decimal("90"), "issued": Decimal("88")},
    {"product_id": 6, "item_code": 1006, "item_name": "إضافات", "unit": "لتر",
     "opening_balance": Decimal("300"), "purchased": Decimal("150"), "issued": Decimal("400")},
]


def test_columns_are_the_eight_balance_columns_in_order():
    svc, _ = _svc()
    keys = [c.key for c in REPORT_COLUMNS]
    assert keys == ["item_code", "item_name", "unit", "opening_balance",
                    "purchased", "issued", "balance", "status"]
    assert svc.columns == list(REPORT_COLUMNS)


def test_balance_is_opening_plus_purchases_minus_issued():
    svc, _ = _svc(_ROWS)
    result = svc.fetch_report(RawMaterialBalanceRequest())
    by_code = {r["item_code"]: r for r in result.rows}
    assert by_code[1001]["balance"] == Decimal("800")   # 500 + 1200 − 900
    assert by_code[1005]["balance"] == Decimal("17")     # 15 + 90 − 88
    assert by_code[1006]["balance"] == Decimal("50")     # 300 + 150 − 400


def test_status_thresholds():
    svc, _ = _svc([
        {"product_id": 1, "item_code": 1, "item_name": "أ", "unit": "",
         "opening_balance": Decimal("0"), "purchased": Decimal("10"), "issued": Decimal("0")},   # 10 → low
        {"product_id": 2, "item_code": 2, "item_name": "ب", "unit": "",
         "opening_balance": Decimal("0"), "purchased": Decimal("60"), "issued": Decimal("0")},   # 60 → mid
        {"product_id": 3, "item_code": 3, "item_name": "ج", "unit": "",
         "opening_balance": Decimal("0"), "purchased": Decimal("500"), "issued": Decimal("0")},  # 500 → ok
        {"product_id": 4, "item_code": 4, "item_name": "د", "unit": "",
         "opening_balance": Decimal("0"), "purchased": Decimal("5"), "issued": Decimal("40")},   # −35 → none
    ])
    result = svc.fetch_report(RawMaterialBalanceRequest())
    by_code = {r["item_code"]: r["status"] for r in result.rows}
    assert by_code[1] == STATUS_LOW
    assert by_code[2] == STATUS_MID
    assert by_code[3] == STATUS_OK
    assert by_code[4] == STATUS_NONE


def test_summary_totals_across_all_rows():
    svc, _ = _svc(_ROWS)
    summary = svc.fetch_report(RawMaterialBalanceRequest()).summary
    assert summary["item_count"] == 3
    assert summary["total_purchased"] == Decimal("1440")   # 1200+90+150
    assert summary["total_issued"] == Decimal("1388")       # 900+88+400
    assert summary["total_balance"] == Decimal("867")       # 800+17+50
    assert summary["total_purchased_label"] == "1,440"
    assert summary["total_balance_label"] == "867"


def test_quantity_formatting_trims_and_keeps_sign():
    svc, _ = _svc([
        {"product_id": 1, "item_code": 1, "item_name": "أ", "unit": "كجم",
         "opening_balance": Decimal("10.500"), "purchased": Decimal("0"), "issued": Decimal("0")},
        {"product_id": 2, "item_code": 2, "item_name": "ب", "unit": "كجم",
         "opening_balance": Decimal("0"), "purchased": Decimal("0"), "issued": Decimal("35")},
    ])
    export = {e["item_code"]: e
              for e in svc.fetch_report(RawMaterialBalanceRequest()).export_rows}
    assert export["1"]["opening_balance"] == "10.5"
    assert export["2"]["balance"] == "-35"


def test_empty_rows_give_empty_result_and_zero_kpis():
    svc, _ = _svc([])
    result = svc.fetch_report(RawMaterialBalanceRequest())
    assert result.is_empty
    assert result.rows == []
    assert result.summary["item_count"] == 0
    assert result.summary["total_balance_label"] == "0"


def test_request_item_name_flows_to_filters_trimmed():
    svc, repo = _svc(_ROWS)
    svc.fetch_report(RawMaterialBalanceRequest(item_name=" زلط "))
    assert repo.last_filters.item_name == "زلط"       # trimmed


def test_blank_item_name_becomes_none():
    svc, repo = _svc(_ROWS)
    svc.fetch_report(RawMaterialBalanceRequest(item_name="   "))
    assert repo.last_filters.item_name is None


def test_search_items_delegates_to_repo():
    svc, repo = _svc()
    out = svc.search_items("رمل", limit=50)
    assert repo.picker_calls == [("رمل", 50)]
    assert out[0]["item_name"] == "بتروميل"


def test_search_items_never_crashes_the_screen():
    class _Boom:
        def search_raw_materials(self, *a, **k):
            raise RuntimeError("db down")
    svc = RawMaterialBalanceService(repository=_Boom())
    assert svc.search_items("x") == []
