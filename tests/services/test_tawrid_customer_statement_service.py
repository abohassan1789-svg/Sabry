"""Unit tests for the customer statement service (كشف حساب عميل), no real DB.

They pin the parts that are the point of this phase:

* the ledger is built in date order with a **running balance**;
* with a «من تاريخ» the first line is a **carry-forward** («رصيد سابق») whose
  value is opening + debits-before − credits-before, and the running balance
  starts from it;
* with no filter the first line is «رصيد أول المدة» and no carry query runs;
* بون rows carry price/volume and land in the debit column, سند rows in credit;
* the export rows format money (negatives, blanks) and trim volume zeros;
* an unknown customer yields an empty result, not an exception.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tawrid_customer_statement_service import (
    CARRY_KIND,
    OPENING_KIND,
    TawridStatementService,
    TawridCustomerStatementService,
    CUSTOMER_STATEMENT_CONFIG,
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
    "party_id": 24, "code": 13, "name": "عصام ابو جبل",
    "opening": Decimal("219000.00"), "opening_date": "2024-03-27",
}

# Three movements: a سند then two بون. Each carries رقم البون (bon), رقم الإيصال
# (eissal), رقم المقطورة (trailer) and رقم الوش (head); vouchers have only an eissal.
MOVES = [
    {"d": "2025-01-07", "kind": "سداد دفعات", "bon": None, "eissal": 9, "trailer": None,
     "head": None, "descr": "", "price": None, "volume": None,
     "debit": Decimal("0"), "credit": Decimal("20000.00"), "ord": 1},
    {"d": "2025-01-09", "kind": "بون عميل", "bon": 1, "eissal": "4026", "trailer": "3581",
     "head": "7814", "descr": "سن 2", "price": Decimal("320.00"), "volume": Decimal("61.000"),
     "debit": Decimal("19520.00"), "credit": Decimal("0"), "ord": 0},
    {"d": "2025-01-12", "kind": "بون عميل", "bon": 58, "eissal": "4099", "trailer": "3581",
     "head": "7814", "descr": "سن 2", "price": Decimal("320.00"), "volume": Decimal("64.000"),
     "debit": Decimal("20480.00"), "credit": Decimal("0"), "ord": 0},
]


class _Bare(TawridStatementService):
    CONFIG = CUSTOMER_STATEMENT_CONFIG


def svc(one=None, many=None):
    return _Bare(FakeDb(one=one, many=many))


# --- unfiltered --------------------------------------------------------------

def test_unfiltered_opens_on_opening_balance_and_runs():
    s = svc(
        one={"FROM tawrid_customers WHERE customer_id": HEADER},
        many={"UNION ALL": MOVES},
    )
    result = s.build(24)
    rows = result.rows
    assert rows[0].is_opening and rows[0].kind == OPENING_KIND
    assert rows[0].running == Decimal("219000.00")
    # running: 219,000 -20,000 -> 199,000 +19,520 -> 218,520 +20,480 -> 239,000
    assert [r.running for r in rows[1:]] == [
        Decimal("199000.00"), Decimal("218520.00"), Decimal("239000.00")
    ]
    assert result.period_debit == Decimal("40000.00")
    assert result.period_credit == Decimal("20000.00")
    assert result.closing_balance == Decimal("239000.00")
    assert result.movement_count == 3 and not result.is_empty
    # No carry queries when there is no date_from.
    assert not any("< %s" in q for q in s._db.queries)


def test_bon_rows_carry_number_eissal_trailer_and_are_debit():
    s = svc(one={"FROM tawrid_customers WHERE customer_id": HEADER}, many={"UNION ALL": MOVES})
    rows = s.build(24).rows
    bon = rows[2]  # the first بون
    assert bon.kind == "بون عميل"
    assert bon.debit == Decimal("19520.00") and bon.credit == Decimal("0")
    assert bon.price == Decimal("320.00") and bon.volume == Decimal("61.000")
    assert bon.bon_no == "1" and bon.eissal == "4026" and bon.trailer == "3581"
    assert bon.head == "7814"   # رقم الوش joined from the tractor card
    assert bon.serial == 2
    # the سند carries only the receipt number in رقم الإيصال, no bon/trailer/head
    sanad = rows[1]
    assert sanad.bon_no == "" and sanad.eissal == "9" and sanad.trailer == ""
    assert sanad.head == ""


# --- filtered: carry-forward -------------------------------------------------

def test_filtered_opens_on_carry_forward_line():
    s = svc(
        one={
            "FROM tawrid_customers WHERE customer_id": HEADER,
            "SUM(safi_cus)": {"s": Decimal("500000.00")},   # debits before window
            "SUM(amount)": {"s": Decimal("300000.00")},     # credits before window
        },
        many={"UNION ALL": MOVES},
    )
    result = s.build(24, "2025-01-01", "2025-12-31")
    carry = result.rows[0]
    assert carry.is_opening and carry.kind == CARRY_KIND
    # 219,000 + 500,000 - 300,000 = 419,000
    assert carry.running == Decimal("419000.00")
    assert result.opening_balance == Decimal("419000.00") and result.opening_is_carry
    # running continues from the carry line
    assert result.rows[1].running == Decimal("399000.00")  # 419,000 - 20,000
    assert result.closing_balance == Decimal("419000.00") + Decimal("40000.00") - Decimal("20000.00")
    # the carry queries were bounded by the from-date
    assert s._db.params[1] == [24, "2025-01-01"]


def test_negative_carry_shows_in_credit_column():
    s = svc(
        one={
            "FROM tawrid_customers WHERE customer_id": {**HEADER, "opening": Decimal("0")},
            "SUM(safi_cus)": {"s": Decimal("0")},
            "SUM(amount)": {"s": Decimal("50000.00")},  # overpaid before window
        },
        many={"UNION ALL": []},
    )
    carry = s.build(24, "2025-06-01", None).rows[0]
    assert carry.running == Decimal("-50000.00")
    assert carry.debit == Decimal("0") and carry.credit == Decimal("50000.00")


# --- empties / unknown -------------------------------------------------------

def test_unknown_customer_is_empty_not_an_error():
    s = svc(one={}, many={})  # header lookup returns None
    result = s.build(999)
    assert result.party_name == "" and result.rows == []
    assert result.is_empty and result.movement_count == 0


def test_no_movements_still_shows_the_opening_line():
    s = svc(one={"FROM tawrid_customers WHERE customer_id": HEADER}, many={"UNION ALL": []})
    result = s.build(24)
    assert len(result.rows) == 1 and result.rows[0].is_opening
    assert result.is_empty  # the opening line alone is not a movement
    assert result.closing_balance == Decimal("219000.00")


# --- export formatting -------------------------------------------------------

def test_export_rows_format_money_and_volume():
    s = svc(one={"FROM tawrid_customers WHERE customer_id": HEADER}, many={"UNION ALL": MOVES})
    rows = s.export_rows(s.build(24))
    opening, sanad, bon1 = rows[0], rows[1], rows[2]
    assert opening["debit"] == "219,000.00" and opening["credit"] == ""
    assert sanad["credit"] == "20,000.00" and sanad["debit"] == ""
    assert bon1["price"] == "320.00" and bon1["volume"] == "61"   # trailing zeros trimmed
    assert bon1["bon_no"] == "1" and bon1["eissal"] == "4026" and bon1["trailer"] == "3581"
    assert bon1["running"] == "218,520.00"


def test_money_shows_negative_with_trailing_dash():
    assert TawridStatementService._money(Decimal("-1234.5")) == "1,234.50-"
    assert TawridStatementService._money(Decimal("1000")) == "1,000.00"
    assert TawridStatementService._vol(Decimal("60.500")) == "60.5"
    assert TawridStatementService._vol(Decimal("62.000")) == "62"


# --- picker rows -------------------------------------------------------------

def test_party_picker_rows_are_active_first():
    rows = [{"party_id": 1, "code": 5, "name": "أ", "is_active": True}]
    s = svc(many={"FROM tawrid_customers ORDER BY is_active DESC": rows})
    out = s.party_picker_rows()
    assert out == rows
    assert "ORDER BY is_active DESC" in s._db.queries[-1]


# --- ملخص البونات (the Access subreport Test) --------------------------------

BON_GROUPS = [
    {"item": "سن 2", "price": Decimal("320.00"), "volume": Decimal("61.000"),
     "cnt": 3, "gross": Decimal("58560.00"), "meters": Decimal("183.000")},
    {"item": "سن 6 بالبودرة", "price": Decimal("290.00"), "volume": Decimal("62.000"),
     "cnt": 2, "gross": Decimal("35960.00"), "meters": Decimal("124.000")},
]


def test_bon_summary_groups_and_totals():
    s = svc(many={"GROUP BY": BON_GROUPS})
    summary = s.bon_summary(24, "2025-01-01", "2025-12-31")
    assert [g.item for g in summary.rows] == ["سن 2", "سن 6 بالبودرة"]
    assert summary.rows[0].count == 3 and summary.rows[0].gross == Decimal("58560.00")
    # totals: value = Σgross, count = Σcnt, meters = Σmeters
    assert summary.total_value == Decimal("94520.00")
    assert summary.total_count == 5
    assert summary.total_meters == Decimal("307.000")
    # bounded by the from/to dates
    q = s._db.queries[-1]
    assert "GROUP BY" in q and "<> ''" in q  # excludes n1="" (vouchers/opening)


def test_bon_summary_no_customer_is_empty():
    summary = svc().bon_summary(None)
    assert summary.rows == [] and summary.total_count == 0


# --- the customer subclass wires the customer config -------------------------

def test_customer_service_uses_the_customer_config():
    assert TawridCustomerStatementService.CONFIG is CUSTOMER_STATEMENT_CONFIG
    cfg = TawridCustomerStatementService.CONFIG
    assert cfg.debit_amount_col == "safi_cus"
    assert cfg.credit_table == "tawrid_customer_receipts"
    assert cfg.debit_bon_col == "ticket_no" and cfg.debit_eissal_col == "receipt_no"
    assert cfg.debit_join_col == "trailer_no" and cfg.debit_gross_col == "total_cus"
