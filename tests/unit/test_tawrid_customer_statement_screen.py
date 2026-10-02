"""Widget tests for شاشة كشف حساب عميل — قسم التوريدات (headless Qt, no DB).

Model 1 («الكلاسيكي»): green header, filter row, stat cards + donut, then the
running-balance ledger with a totals strip. These pin:

* picking a customer then «عرض» fills the ledger, the cards and the totals;
* the opening card is labelled «رصيد أول المدة» unfiltered and «رصيد سابق» when a
  date filter carries a balance forward;
* the donut shows the collection ratio (and may exceed 100% when overpaid);
* بون rows show in the debit column, سند rows in the credit column;
* «عرض» without a customer warns; «مسح» clears everything;
* export/print refuse before a statement has been shown.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.tawrid_customer_statement_service import (
    BON_SUMMARY_COLUMNS,
    BonSummary,
    BonSummaryRow,
    CUSTOMER_COLUMNS,
    StatementResult,
    StatementRow,
    TawridStatementService,
)
from app.ui.screens import tawrid_customer_statement_screen as screen_module
from app.ui.screens.tawrid_customer_statement_screen import (
    TawridCustomerStatementScreen,
    _money,
)


def _result(carry: bool = False) -> StatementResult:
    opening = StatementRow(
        serial=None, date="2024-03-27",
        kind="رصيد سابق" if carry else "رصيد أول المدة",
        bon_no="", eissal="", trailer="",
        description="رصيد", price=None, volume=None,
        debit=Decimal("219000"), credit=Decimal("0"),
        running=Decimal("219000"), is_opening=True,
    )
    bon = StatementRow(
        serial=1, date="2025-01-09", kind="بون عميل",
        bon_no="1", eissal="4026", trailer="3581", description="سن 2",
        price=Decimal("320"), volume=Decimal("61"),
        debit=Decimal("19520"), credit=Decimal("0"), running=Decimal("238520"),
    )
    sanad = StatementRow(
        serial=2, date="2025-01-18", kind="سداد دفعات",
        bon_no="", eissal="31", trailer="", description="دفعة",
        price=None, volume=None,
        debit=Decimal("0"), credit=Decimal("30000"), running=Decimal("208520"),
    )
    return StatementResult(
        party_id=24, party_name="عصام ابو جبل", party_code=13,
        date_from="2025-01-01" if carry else None, date_to=None,
        opening_balance=Decimal("219000"), opening_is_carry=carry,
        rows=[opening, bon, sanad],
        period_debit=Decimal("19520"), period_credit=Decimal("30000"),
        closing_balance=Decimal("208520"), columns=CUSTOMER_COLUMNS,
    )


class FakeService:
    CONFIG = type("C", (), {"columns": CUSTOMER_COLUMNS,
                            "bon_summary_columns": BON_SUMMARY_COLUMNS})

    def __init__(self):
        self.built = None
        self.bon_called = None
        self._result = _result()
        self._summary = BonSummary(
            rows=[BonSummaryRow(item="سن 2", count=3, price=Decimal("320"),
                                volume=Decimal("61"), gross=Decimal("58560"),
                                meters=Decimal("183"))],
            total_value=Decimal("58560"), total_count=3, total_meters=Decimal("183"),
        )

    def party_picker_rows(self):
        return [{"party_id": 24, "code": 13, "name": "عصام ابو جبل", "is_active": True}]

    def build(self, party_id, date_from=None, date_to=None):
        self.built = (party_id, date_from, date_to)
        return self._result

    def bon_summary(self, party_id, date_from=None, date_to=None):
        self.bon_called = (party_id, date_from, date_to)
        return self._summary

    # Reuse the real formatting (money / volume) so the screen sees real strings.
    _money = staticmethod(TawridStatementService._money)
    _vol = staticmethod(TawridStatementService._vol)
    export_rows = TawridStatementService.export_rows


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app):
    view = TawridCustomerStatementScreen(service=FakeService())
    return view


# --- layout ------------------------------------------------------------------

def test_the_cards_and_donut_exist(screen):
    assert set(screen.cards) == {"opening", "debit", "credit", "balance"}
    assert screen.donut is not None
    assert [c.label for c in screen.columns][-1] == "رصيد جارٍ"


def test_the_ledger_has_the_three_number_columns(screen):
    keys = [c.key for c in screen.columns]
    assert "bon_no" in keys and "eissal" in keys and "trailer" in keys
    labels = [c.label for c in screen.columns]
    assert "رقم البون" in labels and "رقم الإيصال" in labels and "رقم المقطورة" in labels


def test_it_starts_empty_with_a_prompt(screen):
    assert screen.empty_label.isVisibleTo(screen)
    assert screen.table.rowCount() == 0


# --- showing a statement -----------------------------------------------------

def test_show_fills_the_ledger_cards_and_totals(screen):
    screen.selected_customer = {"customer_id": 24, "customer_name": "عصام ابو جبل", "customer_code": 13}
    screen.show_statement()
    assert screen.table.rowCount() == 3            # opening + 2 movements
    assert screen.cards["opening"].text() == "219,000.00"
    assert screen.cards["debit"].text() == "19,520.00"
    assert screen.cards["credit"].text() == "30,000.00"
    assert screen.cards["balance"].text() == "208,520.00"
    assert screen.closing_label.text() == "الرصيد الحالي: 208,520.00"
    assert screen.count_label.text() == "عدد الحركات: 2"


def test_unfiltered_opening_card_is_labelled_opening_balance(screen):
    screen.selected_customer = {"customer_id": 24, "customer_name": "x", "customer_code": 1}
    screen.show_statement()
    assert screen._card_captions["opening"].text() == "رصيد أول المدة"


def test_filtered_opening_card_is_labelled_carry_forward(screen):
    screen.service._result = _result(carry=True)
    screen.selected_customer = {"customer_id": 24, "customer_name": "x", "customer_code": 1}
    screen.show_statement()
    assert screen._card_captions["opening"].text() == "رصيد سابق"


def test_the_donut_shows_the_collection_ratio(screen):
    screen.selected_customer = {"customer_id": 24, "customer_name": "x", "customer_code": 1}
    screen.show_statement()
    # collected 30,000 / (opening 219,000 + debit 19,520 = 238,520) = 12.6%
    assert screen.donut._label == "12.6%"


def test_debit_and_credit_land_in_their_columns(screen):
    screen.selected_customer = {"customer_id": 24, "customer_name": "x", "customer_code": 1}
    screen.show_statement()
    labels = [c.key for c in screen.columns]
    debit_col = labels.index("debit")
    credit_col = labels.index("credit")
    # row 1 is the بون: debit filled, credit blank.
    assert screen.table.item(1, debit_col).text() == "19,520.00"
    assert screen.table.item(1, credit_col).text() == ""
    # row 2 is the سند: credit filled, debit blank.
    assert screen.table.item(2, credit_col).text() == "30,000.00"
    assert screen.table.item(2, debit_col).text() == ""


def test_the_number_columns_render_bon_eissal_trailer(screen):
    screen.selected_customer = {"customer_id": 24, "customer_name": "x", "customer_code": 1}
    screen.show_statement()
    keys = [c.key for c in screen.columns]
    bon_col = keys.index("bon_no")
    eissal_col = keys.index("eissal")
    trailer_col = keys.index("trailer")
    # row 1 is the بون.
    assert screen.table.item(1, bon_col).text() == "1"
    assert screen.table.item(1, eissal_col).text() == "4026"
    assert screen.table.item(1, trailer_col).text() == "3581"
    # the سند row (2) has only رقم الإيصال.
    assert screen.table.item(2, bon_col).text() == ""
    assert screen.table.item(2, eissal_col).text() == "31"
    assert screen.table.item(2, trailer_col).text() == ""


# --- ملخص البونات button -----------------------------------------------------

def test_bon_summary_button_disabled_until_a_statement_is_shown(screen):
    assert screen.bon_button.isEnabled() is False
    screen.selected_customer = {"customer_id": 24, "customer_name": "x", "customer_code": 1}
    screen.show_statement()
    assert screen.bon_button.isEnabled() is True
    screen.reset_filters()
    assert screen.bon_button.isEnabled() is False


def test_open_bon_summary_asks_the_service_for_the_shown_customer_and_period(screen, monkeypatch):
    opened = {}

    class FakeDialog:
        def __init__(self, summary, suffix="", parent=None):
            opened["summary"] = summary
            opened["suffix"] = suffix

        def exec(self):
            opened["shown"] = True
            return 1

    monkeypatch.setattr(screen_module, "TawridBonSummaryDialog", FakeDialog)
    screen.service._result = _result(carry=True)  # has date_from 2025-01-01
    screen.selected_customer = {"customer_id": 24, "customer_name": "عصام", "customer_code": 1}
    screen.show_statement()
    screen.open_bon_summary()
    assert screen.service.bon_called == (24, "2025-01-01", None)
    assert opened["shown"] is True
    assert opened["summary"].total_count == 3


# --- validation --------------------------------------------------------------

def test_show_without_a_customer_warns(screen, monkeypatch):
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.setdefault("w", a))
    screen.selected_customer = None
    screen.show_statement()
    assert "w" in warned
    assert screen.service.built is None


def test_reset_clears_everything(screen):
    screen.selected_customer = {"customer_id": 24, "customer_name": "x", "customer_code": 1}
    screen.show_statement()
    screen.reset_filters()
    assert screen.selected_customer is None
    assert screen.current_result is None
    assert screen.table.rowCount() == 0
    assert screen.cards["balance"].text() == "—"
    assert screen.customer_label.text() == "— لم يُختَر —"


def test_export_before_showing_refuses(screen, monkeypatch):
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.setdefault("w", a))
    screen.export_excel()
    assert "w" in warned


# --- معاينة / طباعة / PDF ----------------------------------------------------

def test_print_buttons_exist(screen):
    assert screen.preview_button.text() == "معاينة"
    assert screen.print_button.text() == "طباعة"
    assert screen.pdf_button.text() == "PDF"
    assert screen.excel_button.text() == "تصدير Excel"


def test_print_actions_refuse_before_showing(screen, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    screen.preview_report()
    screen.print_report()
    screen.export_pdf()
    assert len(warned) == 3  # each refuses without a shown statement


def test_print_data_has_rows_summary_and_bon(screen):
    screen.selected_customer = {"customer_id": 24, "customer_name": "عصام", "customer_code": 13}
    screen.show_statement()
    data = screen._print_data()
    assert data["title"] == "كشف حساب عميل"
    assert data["customer_label"] == "عصام ابو جبل"  # from the result
    assert len(data["rows"]) == 3 and data["rows"][0]["is_opening"] is True
    # column sums (opening 219,000 + بون 19,520) computed for the closing row
    assert data["summary"]["col_debit"] == "238,520.00"
    assert data["summary"]["closing"] == "208,520.00"
    assert data["bon"]["count"] == "3"  # from FakeService.bon_summary


# --- helper ------------------------------------------------------------------

def test_money_helper_formats_negatives():
    assert _money(Decimal("-500")) == "500.00-"
    assert _money(Decimal("1234.5")) == "1,234.50"
    assert _money(None) == "0.00"
