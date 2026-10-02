"""Widget + service tests for كشف حساب الخزينة — قسم التوريدات (headless Qt, no DB).

Gold accent, a single date-range filter, an eight-column cash-book table (النوع /
الطرف / مقبوضات / مدفوعات / رصيد تراكمي / البيان) and three totals cards. These pin:

* the three totals cards exist (مقبوضات / مدفوعات / الرصيد) and no donut;
* «عرض» with no filters still runs and fills the cards, totals strip and table;
* the date range flows into the service's ``ReportFilters``;
* «مسح» clears everything; export/print refuse before the report has been shown;
* the service ``build`` classifies receipts as dr and both payment tables as cr,
  carries a correct running balance, and falls back to «— محذوف —» for a NULL party.
"""

from __future__ import annotations

import os
from datetime import date as _date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.tawrid_treasury_statement_service import (
    REPORT_COLUMNS,
    ReportFilters,
    ReportResult,
    ReportRow,
    ReportTotals,
    TawridTreasuryStatementService,
)
from app.ui.screens.tawrid_treasury_statement_screen import (
    TawridTreasuryStatementScreen,
    _money,
)


def _rows() -> list[ReportRow]:
    return [
        ReportRow(
            serial=1, date="2025-01-07", source="قبض عميل", party="الشيخ عوض",
            dr=Decimal("250000"), cr=Decimal("0"), balance=Decimal("250000"), statement="",
        ),
        ReportRow(
            serial=2, date="2025-01-09", source="صرف كسّارة", party="مكة ستون",
            dr=Decimal("0"), cr=Decimal("90000"), balance=Decimal("160000"), statement="دفعة",
        ),
        ReportRow(
            serial=3, date="2025-01-10", source="صرف جرار", party="— محذوف —",
            dr=Decimal("0"), cr=Decimal("10000"), balance=Decimal("150000"), statement="",
        ),
    ]


def _result(filters: ReportFilters | None = None) -> ReportResult:
    totals = ReportTotals(
        total_dr=Decimal("250000"), total_cr=Decimal("100000"),
        balance=Decimal("150000"), count=3,
    )
    return ReportResult(rows=_rows(), totals=totals, filters=filters or ReportFilters(),
                        columns=REPORT_COLUMNS)


class FakeService:
    columns = REPORT_COLUMNS

    def __init__(self):
        self.built_with: ReportFilters | None = None

    def build(self, filters=None):
        self.built_with = filters or ReportFilters()
        return _result(self.built_with)

    export_rows = TawridTreasuryStatementService.export_rows
    _money = staticmethod(TawridTreasuryStatementService._money)


class FakeDb:
    """A stand-in Database whose ``fetch_all`` returns pre-ordered union rows."""

    def __init__(self, rows):
        self._rows = rows
        self.last_params = None

    def fetch_all(self, query, params=None):
        self.last_params = params
        return self._rows


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app):
    return TawridTreasuryStatementScreen(service=FakeService())


# --- layout ------------------------------------------------------------------

def test_the_three_totals_cards_exist_and_no_donut(screen):
    assert set(screen.cards) == {"total_dr", "total_cr", "balance"}
    assert not hasattr(screen, "donut")


def test_the_table_has_the_cash_book_columns(screen):
    keys = [c.key for c in screen.columns]
    assert keys == ["serial", "date", "source", "party", "dr", "cr", "balance", "statement"]


def test_it_starts_empty_with_a_prompt(screen):
    assert screen.empty_label.isVisibleTo(screen)
    assert screen.table.rowCount() == 0


# --- showing the report ------------------------------------------------------

def test_show_with_no_filters_runs_and_fills(screen):
    screen.show_report()
    assert screen.table.rowCount() == 3
    assert screen.cards["total_dr"].text() == "250,000.00"
    assert screen.cards["total_cr"].text() == "100,000.00"
    assert screen.cards["balance"].text() == "150,000.00"
    assert screen.count_label.text() == "عدد الحركات: 3"
    assert screen.total_dr_label.text() == "المقبوضات: 250,000.00"
    # The date range now DEFAULTS to today (per user request — no 1-1-1900).
    today = _date.today().isoformat()
    assert screen.service.built_with.date_from == today
    assert screen.service.built_with.date_to == today


def test_the_date_range_flows_into_the_service(screen):
    screen.from_date.setDate(screen.from_date.date().fromString("2025-01-01", "yyyy-MM-dd"))
    screen.to_date.setDate(screen.to_date.date().fromString("2025-06-30", "yyyy-MM-dd"))
    screen.show_report()
    f = screen.service.built_with
    assert f.date_from == "2025-01-01" and f.date_to == "2025-06-30"


def test_table_cell_shows_the_running_balance(screen):
    screen.show_report()
    labels = [c.label for c in screen.columns]
    idx = labels.index("رصيد تراكمي")
    assert screen.table.item(1, idx).text() == "160,000.00"


def test_reset_clears_everything(screen):
    screen.show_report()
    screen.reset_filters()
    assert screen.current_result is None
    assert screen.cards["balance"].text() == "—"
    assert screen.table.rowCount() == 0
    assert screen.balance_label.text() == "الرصيد: —"


def test_export_refuses_before_a_run(screen, monkeypatch):
    warned = {}
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.setdefault("w", a))
    screen.export_excel()
    assert "w" in warned


def test_money_helper():
    assert _money(Decimal("-11125")) == "11,125.00-"
    assert _money(1234.5) == "1,234.50"
    assert _money(0) == "0.00"


# --- service build() (fake DB) -----------------------------------------------

def test_build_classifies_legs_and_carries_a_running_balance():
    union_rows = [
        {"d": "2025-01-07", "source": "قبض عميل", "party": "الشيخ عوض",
         "dr": Decimal("250000"), "cr": Decimal("0"), "statement": None},
        {"d": "2025-01-09", "source": "صرف كسّارة", "party": "مكة ستون",
         "dr": Decimal("0"), "cr": Decimal("90000"), "statement": "دفعة"},
        {"d": "2025-01-10", "source": "صرف جرار", "party": None,
         "dr": Decimal("0"), "cr": Decimal("10000"), "statement": ""},
    ]
    svc = TawridTreasuryStatementService(db=FakeDb(union_rows))
    res = svc.build()
    assert [r.balance for r in res.rows] == [Decimal("250000"), Decimal("160000"), Decimal("150000")]
    assert res.totals.total_dr == Decimal("250000")
    assert res.totals.total_cr == Decimal("100000")
    assert res.totals.balance == Decimal("150000")
    assert res.rows[2].party == "— محذوف —"   # NULL party → placeholder
    assert res.rows[0].statement == ""          # NULL statement → empty


def test_build_passes_date_bounds_as_params():
    db = FakeDb([])
    svc = TawridTreasuryStatementService(db=db)
    svc.build(ReportFilters(date_from="2025-01-01", date_to="2025-12-31"))
    # each of the three union legs contributes its two source labels + two bounds
    assert db.last_params.count("2025-01-01") == 3
    assert db.last_params.count("2025-12-31") == 3
