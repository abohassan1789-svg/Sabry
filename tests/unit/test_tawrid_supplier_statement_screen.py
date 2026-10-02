"""Widget tests for شاشة كشف حساب الكسارات — قسم التوريدات (headless Qt, no DB).

The crusher twin of the customer statement (Model 1), in amber. These pin:

* picking a crusher then «عرض» fills the ledger, the cards and the totals;
* the opening card is «رصيد أول المدة» unfiltered and «رصيد سابق» when filtered;
* the donut shows the payment ratio (and may exceed 100% when overpaid);
* بون rows show in the debit column, سند rows in the credit column;
* **there is NO «ملخص البونات» button** (the crusher statement has no summary);
* «عرض» without a crusher warns; «مسح» clears everything;
* print/export refuse before a statement has been shown.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.tawrid_customer_statement_service import (
    CUSTOMER_COLUMNS,
    StatementResult,
    StatementRow,
    TawridStatementService,
)
from app.ui.screens.tawrid_supplier_statement_screen import (
    TawridSupplierStatementScreen,
)


def _result(carry: bool = False) -> StatementResult:
    opening = StatementRow(
        serial=None, date="2024-01-01",
        kind="رصيد سابق" if carry else "رصيد أول المدة",
        bon_no="", eissal="", trailer="",
        description="رصيد", price=None, volume=None,
        debit=Decimal("100000"), credit=Decimal("0"),
        running=Decimal("100000"), is_opening=True,
    )
    bon = StatementRow(
        serial=1, date="2025-01-09", kind="بون مورد",
        bon_no="1", eissal="4026", trailer="3581", description="سن 2",
        price=Decimal("300"), volume=Decimal("59"),
        debit=Decimal("17700"), credit=Decimal("0"), running=Decimal("117700"),
    )
    sanad = StatementRow(
        serial=2, date="2025-01-18", kind="مدفوعات للمورد",
        bon_no="", eissal="3", trailer="", description="دفعة",
        price=None, volume=None,
        debit=Decimal("0"), credit=Decimal("40000"), running=Decimal("77700"),
    )
    return StatementResult(
        party_id=5, party_name="الهدي", party_code=12,
        date_from="2025-01-01" if carry else None, date_to=None,
        opening_balance=Decimal("100000"), opening_is_carry=carry,
        rows=[opening, bon, sanad],
        period_debit=Decimal("17700"), period_credit=Decimal("40000"),
        closing_balance=Decimal("77700"), columns=CUSTOMER_COLUMNS,
    )


class FakeService:
    CONFIG = type("C", (), {"columns": CUSTOMER_COLUMNS})

    def __init__(self):
        self.built = None
        self._result = _result()

    def party_picker_rows(self):
        return [{"party_id": 5, "code": 12, "name": "الهدي",
                 "is_active": True, "balance": Decimal("77700")}]

    def build(self, party_id, date_from=None, date_to=None):
        self.built = (party_id, date_from, date_to)
        return self._result

    _money = staticmethod(TawridStatementService._money)
    _vol = staticmethod(TawridStatementService._vol)
    export_rows = TawridStatementService.export_rows


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app):
    return TawridSupplierStatementScreen(service=FakeService())


# --- layout ------------------------------------------------------------------

def test_the_cards_and_donut_exist(screen):
    assert set(screen.cards) == {"opening", "debit", "credit", "balance"}
    assert screen.donut is not None
    assert [c.label for c in screen.columns][-1] == "رصيد جارٍ"


def test_there_is_no_bon_summary_button(screen):
    assert not hasattr(screen, "bon_button")


def test_the_ledger_has_the_three_number_columns(screen):
    keys = [c.key for c in screen.columns]
    assert "bon_no" in keys and "eissal" in keys and "trailer" in keys


def test_it_starts_empty_with_a_prompt(screen):
    assert screen.empty_label.isVisibleTo(screen)
    assert screen.table.rowCount() == 0


# --- showing a statement -----------------------------------------------------

def test_show_fills_the_ledger_cards_and_totals(screen):
    screen.selected_supplier = {"supplier_id": 5, "supplier_name": "الهدي", "supplier_code": 12}
    screen.show_statement()
    assert screen.table.rowCount() == 3            # opening + 2 movements
    assert screen.cards["opening"].text() == "100,000.00"
    assert screen.cards["debit"].text() == "17,700.00"
    assert screen.cards["credit"].text() == "40,000.00"
    assert screen.cards["balance"].text() == "77,700.00"
    assert screen.closing_label.text() == "الرصيد الحالي: 77,700.00"
    assert screen.count_label.text() == "عدد الحركات: 2"


def test_unfiltered_opening_card_is_labelled_opening_balance(screen):
    screen.selected_supplier = {"supplier_id": 5, "supplier_name": "x", "supplier_code": 1}
    screen.show_statement()
    assert screen._card_captions["opening"].text() == "رصيد أول المدة"


def test_filtered_opening_card_is_labelled_carry_forward(screen):
    screen.service._result = _result(carry=True)
    screen.selected_supplier = {"supplier_id": 5, "supplier_name": "x", "supplier_code": 1}
    screen.show_statement()
    assert screen._card_captions["opening"].text() == "رصيد سابق"


def test_the_donut_shows_the_payment_ratio(screen):
    screen.selected_supplier = {"supplier_id": 5, "supplier_name": "x", "supplier_code": 1}
    screen.show_statement()
    # paid 40,000 / (opening 100,000 + debit 17,700 = 117,700) = 33.98% -> 34.0%
    assert screen.donut._label == "34.0%"


def test_debit_and_credit_land_in_their_columns(screen):
    screen.selected_supplier = {"supplier_id": 5, "supplier_name": "x", "supplier_code": 1}
    screen.show_statement()
    keys = [c.key for c in screen.columns]
    debit_col = keys.index("debit")
    credit_col = keys.index("credit")
    assert screen.table.item(1, debit_col).text() == "17,700.00"
    assert screen.table.item(1, credit_col).text() == ""
    assert screen.table.item(2, credit_col).text() == "40,000.00"
    assert screen.table.item(2, debit_col).text() == ""


# --- validation --------------------------------------------------------------

def test_show_without_a_supplier_warns(screen, monkeypatch):
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.setdefault("w", a))
    screen.selected_supplier = None
    screen.show_statement()
    assert "w" in warned
    assert screen.service.built is None


def test_reset_clears_everything(screen):
    screen.selected_supplier = {"supplier_id": 5, "supplier_name": "x", "supplier_code": 1}
    screen.show_statement()
    screen.reset_filters()
    assert screen.selected_supplier is None
    assert screen.current_result is None
    assert screen.table.rowCount() == 0
    assert screen.cards["balance"].text() == "—"
    assert screen.supplier_label.text() == "— لم تُختَر —"


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
    assert len(warned) == 3


def test_print_data_has_rows_and_summary_but_no_bon(screen):
    screen.selected_supplier = {"supplier_id": 5, "supplier_name": "الهدي", "supplier_code": 12}
    screen.show_statement()
    data = screen._print_data()
    assert data["title"] == "كشف حساب الكسارات"
    assert data["customer_label"] == "الهدي"  # party label reused by the template
    assert len(data["rows"]) == 3 and data["rows"][0]["is_opening"] is True
    # column sums (opening 100,000 + بون 17,700) computed for the closing row
    assert data["summary"]["col_debit"] == "117,700.00"
    assert data["summary"]["closing"] == "77,700.00"
    assert data["summary"]["closing_label"] == "الرصيد الختامي المستحق للكسّارة"
    assert "bon" not in data  # NO ملخص بونات for the crusher
