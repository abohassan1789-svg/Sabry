"""Unit tests for the Finished-Goods Warehouse service (مخزن الإنتاج التام).

A fake repository returns canned per-product rows (opening / produced / sold);
the tests pin the balance arithmetic (opening + produced − sold), the trimmed
quantity formatting, the per-row status thresholds, the four KPI totals, the
picker guard and the item-name filter passthrough. No database, no Qt.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.finished_goods_balance_service import (
    REPORT_COLUMNS,
    STATUS_LOW,
    STATUS_MID,
    STATUS_NONE,
    STATUS_OK,
    FinishedGoodsBalanceRequest,
    FinishedGoodsBalanceService,
)


class _FakeRepo:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []
        self.last_filters = None
        self.picker_calls: list[tuple[str, int]] = []

    def fetch_balances(self, filters):
        self.last_filters = filters
        return list(self._rows)

    def search_finished_goods(self, keyword="", limit=500):
        self.picker_calls.append((keyword, limit))
        return [{"item_code": 2001, "item_name": "خرسانة", "unit": "م³"}]


def _svc(rows=None):
    repo = _FakeRepo(rows)
    return FinishedGoodsBalanceService(repository=repo), repo


_ROWS = [
    {"product_id": 1, "item_code": 2001, "item_name": "خرسانة", "unit": "م³",
     "opening_balance": Decimal("100"), "produced": Decimal("500"), "sold": Decimal("450")},
    {"product_id": 2, "item_code": 2002, "item_name": "بلوك", "unit": "قطعة",
     "opening_balance": Decimal("20"), "produced": Decimal("1000"), "sold": Decimal("1005")},
    {"product_id": 3, "item_code": 2003, "item_name": "طوب", "unit": "ألف",
     "opening_balance": Decimal("5"), "produced": Decimal("40"), "sold": Decimal("30")},
]


def test_columns_are_the_eight_balance_columns_in_order():
    svc, _ = _svc()
    keys = [c.key for c in REPORT_COLUMNS]
    assert keys == ["item_code", "item_name", "unit", "opening_balance",
                    "produced", "sold", "balance", "status"]
    assert svc.columns == list(REPORT_COLUMNS)


def test_balance_is_opening_plus_produced_minus_sold():
    svc, _ = _svc(_ROWS)
    result = svc.fetch_report(FinishedGoodsBalanceRequest())
    by_code = {r["item_code"]: r for r in result.rows}
    assert by_code[2001]["balance"] == Decimal("150")   # 100 + 500 − 450
    assert by_code[2002]["balance"] == Decimal("15")     # 20 + 1000 − 1005
    assert by_code[2003]["balance"] == Decimal("15")     # 5 + 40 − 30


def test_status_thresholds():
    svc, _ = _svc([
        {"product_id": 1, "item_code": 1, "item_name": "أ", "unit": "",
         "opening_balance": Decimal("0"), "produced": Decimal("10"), "sold": Decimal("0")},   # 10 → low
        {"product_id": 2, "item_code": 2, "item_name": "ب", "unit": "",
         "opening_balance": Decimal("0"), "produced": Decimal("60"), "sold": Decimal("0")},   # 60 → mid
        {"product_id": 3, "item_code": 3, "item_name": "ج", "unit": "",
         "opening_balance": Decimal("0"), "produced": Decimal("500"), "sold": Decimal("0")},  # 500 → ok
        {"product_id": 4, "item_code": 4, "item_name": "د", "unit": "",
         "opening_balance": Decimal("0"), "produced": Decimal("5"), "sold": Decimal("40")},   # −35 → none
    ])
    result = svc.fetch_report(FinishedGoodsBalanceRequest())
    by_code = {r["item_code"]: r["status"] for r in result.rows}
    assert by_code[1] == STATUS_LOW
    assert by_code[2] == STATUS_MID
    assert by_code[3] == STATUS_OK
    assert by_code[4] == STATUS_NONE


def test_summary_totals_across_all_rows():
    svc, _ = _svc(_ROWS)
    summary = svc.fetch_report(FinishedGoodsBalanceRequest()).summary
    assert summary["item_count"] == 3
    assert summary["total_produced"] == Decimal("1540")   # 500+1000+40
    assert summary["total_sold"] == Decimal("1485")        # 450+1005+30
    assert summary["total_balance"] == Decimal("180")       # 150+15+15
    assert summary["total_produced_label"] == "1,540"
    assert summary["total_balance_label"] == "180"


def test_quantity_formatting_trims_and_keeps_sign():
    svc, _ = _svc([
        {"product_id": 1, "item_code": 1, "item_name": "أ", "unit": "م³",
         "opening_balance": Decimal("10.500"), "produced": Decimal("0"), "sold": Decimal("0")},
        {"product_id": 2, "item_code": 2, "item_name": "ب", "unit": "م³",
         "opening_balance": Decimal("0"), "produced": Decimal("0"), "sold": Decimal("35")},
    ])
    export = {e["item_code"]: e
              for e in svc.fetch_report(FinishedGoodsBalanceRequest()).export_rows}
    assert export["1"]["opening_balance"] == "10.5"
    assert export["2"]["balance"] == "-35"


def test_empty_rows_give_empty_result_and_zero_kpis():
    svc, _ = _svc([])
    result = svc.fetch_report(FinishedGoodsBalanceRequest())
    assert result.is_empty
    assert result.rows == []
    assert result.summary["item_count"] == 0
    assert result.summary["total_balance_label"] == "0"


def test_request_item_name_flows_to_filters_trimmed():
    svc, repo = _svc(_ROWS)
    svc.fetch_report(FinishedGoodsBalanceRequest(item_name=" خرسانة "))
    assert repo.last_filters.item_name == "خرسانة"       # trimmed


def test_blank_item_name_becomes_none():
    svc, repo = _svc(_ROWS)
    svc.fetch_report(FinishedGoodsBalanceRequest(item_name="   "))
    assert repo.last_filters.item_name is None


def test_search_items_delegates_to_repo():
    svc, repo = _svc()
    out = svc.search_items("خرسانة", limit=50)
    assert repo.picker_calls == [("خرسانة", 50)]
    assert out[0]["item_name"] == "خرسانة"


def test_search_items_never_crashes_the_screen():
    class _Boom:
        def search_finished_goods(self, *a, **k):
            raise RuntimeError("db down")
    svc = FinishedGoodsBalanceService(repository=_Boom())
    assert svc.search_items("x") == []
