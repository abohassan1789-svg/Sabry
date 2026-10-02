"""Unit tests for the crusher statement service (كشف حساب الكسارات), no real DB.

The service is the config-driven :class:`TawridStatementService` from the customer
statement, wired for the crusher. These pin the crusher-specific parts:

* the ledger is built in date order with a **running balance**;
* the debit layer is the crusher's ``total_res`` and the credit is a سند صرف;
* with a «من تاريخ» the first line is a **carry-forward** («رصيد سابق») whose value
  is opening + debits-before − credits-before;
* **there is NO «ملخص البونات»** — ``bon_summary`` is empty even with a period,
  because the crusher config leaves ``debit_gross_col`` unset;
* the config points at the crusher tables/columns.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tawrid_customer_statement_service import (
    CARRY_KIND,
    OPENING_KIND,
    TawridStatementService,
)
from app.services.tawrid_supplier_statement_service import (
    SUPPLIER_STATEMENT_CONFIG,
    TawridSupplierStatementService,
)


class FakeDb:
    """Routes each query to a canned result by a substring of its text."""

    def __init__(self, one=None, many=None):
        self._one = one or {}
        self._many = many or {}
        self.queries: list[str] = []
        self.params: list[list] = []

    def _match(self, table, text):
        for needle, value in table.items():
            if needle in text:
                return value
        return None

    def fetch_one(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text)
        self.params.append(list(params or []))
        return self._match(self._one, text)

    def fetch_all(self, query, params=None):
        text = " ".join(str(query).split())
        self.queries.append(text)
        self.params.append(list(params or []))
        return list(self._match(self._many, text) or [])


HEADER = {
    "party_id": 5, "code": 12, "name": "الهدي",
    "opening": Decimal("100000.00"), "opening_date": "2024-01-01",
}

# Three movements: a سند صرف then two بون مورد. بون carries price/volume and the
# three number columns; the voucher carries only رقم الإيصال.
MOVES = [
    {"d": "2025-01-07", "kind": "مدفوعات للمورد", "bon": None, "eissal": 3, "trailer": None,
     "descr": "دفعة", "price": None, "volume": None,
     "debit": Decimal("0"), "credit": Decimal("40000.00"), "ord": 1},
    {"d": "2025-01-09", "kind": "بون مورد", "bon": 1, "eissal": "4026", "trailer": "3581",
     "descr": "سن 2", "price": Decimal("300.00"), "volume": Decimal("59.000"),
     "debit": Decimal("17700.00"), "credit": Decimal("0"), "ord": 0},
    {"d": "2025-01-12", "kind": "بون مورد", "bon": 58, "eissal": "4099", "trailer": "3581",
     "descr": "سن 2", "price": Decimal("300.00"), "volume": Decimal("60.000"),
     "debit": Decimal("18000.00"), "credit": Decimal("0"), "ord": 0},
]


class _Bare(TawridStatementService):
    CONFIG = SUPPLIER_STATEMENT_CONFIG


def svc(one=None, many=None):
    return _Bare(FakeDb(one=one, many=many))


# --- unfiltered --------------------------------------------------------------

def test_unfiltered_opens_on_opening_balance_and_runs():
    s = svc(
        one={"FROM tawrid_suppliers WHERE supplier_id": HEADER},
        many={"UNION ALL": MOVES},
    )
    result = s.build(5)
    rows = result.rows
    assert rows[0].is_opening and rows[0].kind == OPENING_KIND
    assert rows[0].running == Decimal("100000.00")
    # 100,000 -40,000 -> 60,000 +17,700 -> 77,700 +18,000 -> 95,700
    assert [r.running for r in rows[1:]] == [
        Decimal("60000.00"), Decimal("77700.00"), Decimal("95700.00")
    ]
    assert result.period_debit == Decimal("35700.00")
    assert result.period_credit == Decimal("40000.00")
    assert result.closing_balance == Decimal("95700.00")
    assert result.movement_count == 3 and not result.is_empty
    assert not any("< %s" in q for q in s._db.queries)


def test_bon_rows_are_debit_and_carry_price_volume_numbers():
    s = svc(one={"FROM tawrid_suppliers WHERE supplier_id": HEADER}, many={"UNION ALL": MOVES})
    rows = s.build(5).rows
    bon = rows[2]  # the first بون
    assert bon.kind == "بون مورد"
    assert bon.debit == Decimal("17700.00") and bon.credit == Decimal("0")
    assert bon.price == Decimal("300.00") and bon.volume == Decimal("59.000")
    assert bon.bon_no == "1" and bon.eissal == "4026" and bon.trailer == "3581"
    sanad = rows[1]
    assert sanad.credit == Decimal("40000.00") and sanad.debit == Decimal("0")
    assert sanad.bon_no == "" and sanad.eissal == "3" and sanad.trailer == ""


# --- filtered: carry-forward -------------------------------------------------

def test_filtered_opens_on_carry_forward_line():
    s = svc(
        one={
            "FROM tawrid_suppliers WHERE supplier_id": HEADER,
            "SUM(total_res)": {"s": Decimal("400000.00")},   # debits before window
            "SUM(amount)": {"s": Decimal("250000.00")},      # credits before window
        },
        many={"UNION ALL": MOVES},
    )
    result = s.build(5, "2025-01-01", "2025-12-31")
    carry = result.rows[0]
    assert carry.is_opening and carry.kind == CARRY_KIND
    # 100,000 + 400,000 - 250,000 = 250,000
    assert carry.running == Decimal("250000.00")
    assert result.opening_balance == Decimal("250000.00") and result.opening_is_carry
    assert result.rows[1].running == Decimal("210000.00")  # 250,000 - 40,000
    assert s._db.params[1] == [5, "2025-01-01"]


def test_negative_carry_shows_in_credit_column():
    s = svc(
        one={
            "FROM tawrid_suppliers WHERE supplier_id": {**HEADER, "opening": Decimal("0")},
            "SUM(total_res)": {"s": Decimal("0")},
            "SUM(amount)": {"s": Decimal("11125.00")},  # overpaid before window
        },
        many={"UNION ALL": []},
    )
    carry = s.build(5, "2025-06-01", None).rows[0]
    assert carry.running == Decimal("-11125.00")
    assert carry.debit == Decimal("0") and carry.credit == Decimal("11125.00")


# --- empties / unknown -------------------------------------------------------

def test_unknown_supplier_is_empty_not_an_error():
    s = svc(one={}, many={})
    result = s.build(999)
    assert result.party_name == "" and result.rows == []
    assert result.is_empty and result.movement_count == 0


# --- NO ملخص بونات for the crusher -------------------------------------------

def test_bon_summary_is_always_empty_for_the_crusher():
    # Even handed matching group rows, the crusher config leaves debit_gross_col
    # unset, so the summary short-circuits to empty and no GROUP BY runs.
    s = svc(many={"GROUP BY": [{"item": "سن 2", "price": Decimal("300"),
                                "volume": Decimal("59"), "cnt": 3,
                                "gross": Decimal("53100"), "meters": Decimal("177")}]})
    summary = s.bon_summary(5, "2025-01-01", "2025-12-31")
    assert summary.rows == [] and summary.total_count == 0
    assert not any("GROUP BY" in q for q in s._db.queries)


# --- config wiring -----------------------------------------------------------

def test_supplier_service_uses_the_supplier_config():
    assert TawridSupplierStatementService.CONFIG is SUPPLIER_STATEMENT_CONFIG
    cfg = SUPPLIER_STATEMENT_CONFIG
    assert cfg.party_table == "tawrid_suppliers" and cfg.party_pk == "supplier_id"
    assert cfg.debit_amount_col == "total_res"
    assert cfg.debit_price_col == "price_res" and cfg.debit_volume_col == "res_volume"
    assert cfg.debit_gross_col is None          # the «no bon summary» switch
    assert cfg.credit_table == "tawrid_supplier_payments"
    assert cfg.credit_amount_col == "amount" and cfg.credit_date_col == "payment_date"
    assert cfg.debit_kind == "بون مورد" and cfg.credit_kind == "مدفوعات للمورد"
