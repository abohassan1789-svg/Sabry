"""Unit tests for the tractor statement service (كشف حساب الجرارات), no real DB.

The service is the config-driven :class:`TawridStatementService` from the customer
statement, wired for the tractor, with **one override**: the «ملخص البونات» is
grouped by the customer (Access ``HisspCountcus``), not by the item. These pin:

* the ledger is built in date order with a **running balance**;
* the debit layer is the tractor's ``total_man`` and the credit is a سند صرف جرار;
* with a «من تاريخ» the first line is a **carry-forward** («رصيد سابق») whose value
  is opening + debits-before − credits-before;
* the tractor **HAS a «ملخص البونات»**, grouped by customer via a join, with NO
  ``cus_id > 0`` exclusion (orphan بونات on «عميل محذوف» stay in — the user's call);
* the config points at the tractor tables/columns and the real Access kind strings.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.tawrid_customer_statement_service import (
    CARRY_KIND,
    OPENING_KIND,
    TawridStatementService,
)
from app.services.tawrid_tractor_statement_service import (
    TRACTOR_BON_SUMMARY_COLUMNS,
    TRACTOR_STATEMENT_CONFIG,
    TawridTractorStatementService,
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
    "party_id": 7, "code": 12, "name": "محمد السائق",
    "opening": Decimal("50000.00"), "opening_date": "2024-01-01",
}

# Three movements: a سند صرف then two بون مندوب. بون carries price/volume and the
# three number columns; the voucher carries only رقم الإيصال.
MOVES = [
    {"d": "2025-01-07", "kind": "مدفوعات الجرارات", "bon": None, "eissal": 3, "trailer": None,
     "descr": "دفعة", "price": None, "volume": None,
     "debit": Decimal("0"), "credit": Decimal("20000.00"), "ord": 1},
    {"d": "2025-01-09", "kind": "بون مندوب", "bon": 1, "eissal": "4026", "trailer": "3581",
     "descr": "سن 2", "price": Decimal("50.00"), "volume": Decimal("59.000"),
     "debit": Decimal("2950.00"), "credit": Decimal("0"), "ord": 0},
    {"d": "2025-01-12", "kind": "بون مندوب", "bon": 58, "eissal": "4099", "trailer": "3581",
     "descr": "سن 2", "price": Decimal("50.00"), "volume": Decimal("60.000"),
     "debit": Decimal("3000.00"), "credit": Decimal("0"), "ord": 0},
]


class _Bare(TawridStatementService):
    CONFIG = TRACTOR_STATEMENT_CONFIG


def bare(one=None, many=None):
    return _Bare(FakeDb(one=one, many=many))


def full(one=None, many=None):
    return TawridTractorStatementService(FakeDb(one=one, many=many))


# --- unfiltered --------------------------------------------------------------

def test_unfiltered_opens_on_opening_balance_and_runs():
    s = bare(
        one={"FROM tawrid_tractors WHERE tractor_id": HEADER},
        many={"UNION ALL": MOVES},
    )
    result = s.build(7)
    rows = result.rows
    assert rows[0].is_opening and rows[0].kind == OPENING_KIND
    assert rows[0].running == Decimal("50000.00")
    # 50,000 -20,000 -> 30,000 +2,950 -> 32,950 +3,000 -> 35,950
    assert [r.running for r in rows[1:]] == [
        Decimal("30000.00"), Decimal("32950.00"), Decimal("35950.00")
    ]
    assert result.period_debit == Decimal("5950.00")
    assert result.period_credit == Decimal("20000.00")
    assert result.closing_balance == Decimal("35950.00")
    assert result.movement_count == 3 and not result.is_empty
    assert not any("< %s" in q for q in s._db.queries)


def test_bon_rows_are_debit_and_carry_price_volume_numbers():
    s = bare(one={"FROM tawrid_tractors WHERE tractor_id": HEADER}, many={"UNION ALL": MOVES})
    rows = s.build(7).rows
    bon = rows[2]  # the first بون مندوب
    assert bon.kind == "بون مندوب"
    assert bon.debit == Decimal("2950.00") and bon.credit == Decimal("0")
    assert bon.price == Decimal("50.00") and bon.volume == Decimal("59.000")
    assert bon.bon_no == "1" and bon.eissal == "4026" and bon.trailer == "3581"
    sanad = rows[1]
    assert sanad.kind == "مدفوعات الجرارات"
    assert sanad.credit == Decimal("20000.00") and sanad.debit == Decimal("0")
    assert sanad.bon_no == "" and sanad.eissal == "3" and sanad.trailer == ""


# --- filtered: carry-forward -------------------------------------------------

def test_filtered_opens_on_carry_forward_line():
    s = bare(
        one={
            "FROM tawrid_tractors WHERE tractor_id": HEADER,
            "SUM(total_man)": {"s": Decimal("200000.00")},   # debits before window
            "SUM(amount)": {"s": Decimal("120000.00")},      # credits before window
        },
        many={"UNION ALL": MOVES},
    )
    result = s.build(7, "2025-01-01", "2025-12-31")
    carry = result.rows[0]
    assert carry.is_opening and carry.kind == CARRY_KIND
    # 50,000 + 200,000 - 120,000 = 130,000
    assert carry.running == Decimal("130000.00")
    assert result.opening_balance == Decimal("130000.00") and result.opening_is_carry
    assert result.rows[1].running == Decimal("110000.00")  # 130,000 - 20,000
    assert s._db.params[1] == [7, "2025-01-01"]


def test_negative_carry_shows_in_credit_column_when_overpaid():
    # The recovered legacy tractor 27 is overpaid: opening 0, nothing earned but
    # a payment before the window -> a negative carry, shown in the credit column.
    s = bare(
        one={
            "FROM tawrid_tractors WHERE tractor_id": {**HEADER, "opening": Decimal("0")},
            "SUM(total_man)": {"s": Decimal("0")},
            "SUM(amount)": {"s": Decimal("13139.50")},
        },
        many={"UNION ALL": []},
    )
    carry = s.build(7, "2025-06-01", None).rows[0]
    assert carry.running == Decimal("-13139.50")
    assert carry.debit == Decimal("0") and carry.credit == Decimal("13139.50")


# --- empties / unknown -------------------------------------------------------

def test_unknown_tractor_is_empty_not_an_error():
    s = bare(one={}, many={})
    result = s.build(999)
    assert result.party_name == "" and result.rows == []
    assert result.is_empty and result.movement_count == 0


# --- the «ملخص البونات» grouped by CUSTOMER (the real new work) --------------

def test_bon_summary_groups_by_customer_and_totals():
    # Two customer groups; the summary column is «اسم العميل», and the totals are
    # Σgross / Σcount / Σmeters. The «عميل محذوف» orphan group stays in.
    groups = [
        {"item": "عصام ابو جبل", "price": Decimal("50"), "volume": Decimal("59"),
         "cnt": 2, "gross": Decimal("5900"), "meters": Decimal("118")},
        {"item": "عميل محذوف", "price": Decimal("45"), "volume": Decimal("60"),
         "cnt": 1, "gross": Decimal("2700"), "meters": Decimal("60")},
    ]
    s = full(many={"GROUP BY c.customer_name": groups})
    summary = s.bon_summary(7, "2025-01-01", "2025-12-31")
    assert [c.label for c in summary.columns] == [
        "م", "اسم العميل", "عدد النقلات", "السعر", "التكعيب", "الإجمالى", "إجمالى الأمتار"
    ]
    assert [r.item for r in summary.rows] == ["عصام ابو جبل", "عميل محذوف"]
    assert summary.rows[0].count == 2 and summary.rows[0].gross == Decimal("5900")
    assert summary.total_value == Decimal("8600.00")   # 5,900 + 2,700
    assert summary.total_count == 3                     # 2 + 1
    assert summary.total_meters == Decimal("178")       # 118 + 60
    # It joins tawrid_customers, groups by the customer name, and applies NO
    # cus_id/legacy exclusion (the user chose to keep «عميل محذوف»).
    joined = [q for q in s._db.queries if "GROUP BY c.customer_name" in q][0]
    assert "JOIN tawrid_customers c" in joined
    assert "HAVING" not in joined and "legacy_id" not in joined
    assert "cus_id" not in joined


def test_bon_summary_empty_for_no_party():
    s = full()
    summary = s.bon_summary(None)
    assert summary.rows == [] and summary.total_count == 0
    assert not any("GROUP BY" in q for q in s._db.queries)


def test_bon_summary_passes_the_date_filters():
    s = full(many={"GROUP BY c.customer_name": []})
    s.bon_summary(7, "2025-01-01", "2025-06-30")
    params = s._db.params[-1]
    assert params == [7, "2025-01-01", "2025-06-30"]


# --- picker rows carry the plate columns -------------------------------------

def test_party_picker_rows_include_the_plates():
    rows = [{"party_id": 7, "code": 12, "name": "محمد", "head_no": "و1",
             "trailer_no": "3581", "is_active": True}]
    s = full(many={"FROM tawrid_tractors ORDER BY": rows})
    got = s.party_picker_rows()
    assert got[0]["head_no"] == "و1" and got[0]["trailer_no"] == "3581"
    q = s._db.queries[-1]
    assert "head_no" in q and "trailer_no" in q and "driver_name AS name" in q


# --- config wiring -----------------------------------------------------------

def test_tractor_service_uses_the_tractor_config():
    assert TawridTractorStatementService.CONFIG is TRACTOR_STATEMENT_CONFIG
    cfg = TRACTOR_STATEMENT_CONFIG
    assert cfg.party_table == "tawrid_tractors" and cfg.party_pk == "tractor_id"
    assert cfg.party_name_col == "driver_name" and cfg.party_code_col == "tractor_code"
    assert cfg.debit_amount_col == "total_man"
    assert cfg.debit_price_col == "price_man" and cfg.debit_volume_col == "cus_volume"
    assert cfg.debit_gross_col == "total_man"    # enables the bon summary
    assert cfg.credit_table == "tawrid_tractor_payments"
    assert cfg.credit_amount_col == "amount" and cfg.credit_date_col == "payment_date"
    assert cfg.debit_kind == "بون مندوب" and cfg.credit_kind == "مدفوعات الجرارات"
    assert cfg.bon_summary_columns is TRACTOR_BON_SUMMARY_COLUMNS
