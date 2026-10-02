"""Widget tests for شاشة كشف حساب الجرارات — قسم التوريدات (headless Qt, no DB).

The tractor twin of the customer statement (Model 1), in royal blue. These pin:

* picking a tractor then «عرض» fills the ledger, the cards and the totals;
* the opening card is «رصيد أول المدة» unfiltered and «رصيد سابق» when filtered;
* the donut shows the payment ratio (and may exceed 100% when overpaid);
* بون rows show in the debit column, سند rows in the credit column;
* the tractor statement **HAS a «ملخص البونات» button** (grouped by customer);
* «عرض» without a tractor warns; «مسح» clears everything;
* print/export refuse before a statement has been shown; the print data carries a
  ``bon`` block labelled «اسم العميل».
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.tawrid_customer_statement_service import (
    CUSTOMER_COLUMNS,
    BonSummary,
    BonSummaryRow,
    StatementResult,
    StatementRow,
    TawridStatementService,
)
from app.services.tawrid_tractor_statement_service import TRACTOR_BON_SUMMARY_COLUMNS
from app.ui.screens.tawrid_tractor_statement_screen import (
    TawridTractorStatementScreen,
)


def _result(carry: bool = False) -> StatementResult:
    opening = StatementRow(
        serial=None, date="2024-01-01",
        kind="رصيد سابق" if carry else "رصيد أول المدة",
        bon_no="", eissal="", trailer="",
        description="رصيد", price=None, volume=None,
        debit=Decimal("50000"), credit=Decimal("0"),
        running=Decimal("50000"), is_opening=True,
    )
    bon = StatementRow(
        serial=1, date="2025-01-09", kind="بون مندوب",
        bon_no="1", eissal="4026", trailer="3581", description="سن 2",
        price=Decimal("50"), volume=Decimal("59"),
        debit=Decimal("2950"), credit=Decimal("0"), running=Decimal("52950"),
    )
    sanad = StatementRow(
        serial=2, date="2025-01-18", kind="مدفوعات الجرارات",
        bon_no="", eissal="3", trailer="", description="دفعة",
        price=None, volume=None,
        debit=Decimal("0"), credit=Decimal("20000"), running=Decimal("32950"),
    )
    return StatementResult(
        party_id=7, party_name="محمد السائق", party_code=12,
        date_from="2025-01-01" if carry else None, date_to=None,
        opening_balance=Decimal("50000"), opening_is_carry=carry,
        rows=[opening, bon, sanad],
        period_debit=Decimal("2950"), period_credit=Decimal("20000"),
        closing_balance=Decimal("32950"), columns=CUSTOMER_COLUMNS,
    )


def _bon_summary() -> BonSummary:
    return BonSummary(
        rows=[
            BonSummaryRow(item="عصام ابو جبل", count=2, price=Decimal("50"),
                          volume=Decimal("59"), gross=Decimal("5900"), meters=Decimal("118")),
        ],
        total_value=Decimal("5900"), total_count=2, total_meters=Decimal("118"),
        columns=TRACTOR_BON_SUMMARY_COLUMNS,
    )


class FakeService:
    CONFIG = type("C", (), {"columns": CUSTOMER_COLUMNS})

    def __init__(self):
        self.built = None
        self._result = _result()

    def party_picker_rows(self):
        return [{"party_id": 7, "code": 12, "name": "محمد السائق",
                 "head_no": "و1", "trailer_no": "3581", "is_active": True}]

    def build(self, party_id, date_from=None, date_to=None):
        self.built = (party_id, date_from, date_to)
        return self._result

    def bon_summary(self, party_id, date_from=None, date_to=None):
        return _bon_summary()

    _money = staticmethod(TawridStatementService._money)
    _vol = staticmethod(TawridStatementService._vol)
    export_rows = TawridStatementService.export_rows


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app):
    return TawridTractorStatementScreen(service=FakeService())


# --- layout ------------------------------------------------------------------

def test_the_cards_and_donut_exist(screen):
    assert set(screen.cards) == {"opening", "debit", "credit", "balance"}
    assert screen.donut is not None
    assert [c.label for c in screen.columns][-1] == "رصيد جارٍ"


def test_there_is_a_bon_summary_button(screen):
    assert hasattr(screen, "bon_button")
    assert screen.bon_button.text() == "ملخص البونات"
    assert not screen.bon_button.isEnabled()   # disabled until a statement is shown


def test_the_ledger_has_the_three_number_columns(screen):
    keys = [c.key for c in screen.columns]
    assert "bon_no" in keys and "eissal" in keys and "trailer" in keys


def test_it_starts_empty_with_a_prompt(screen):
    assert screen.empty_label.isVisibleTo(screen)
    assert screen.table.rowCount() == 0


# --- showing a statement -----------------------------------------------------

def test_show_fills_the_ledger_cards_and_totals(screen):
    screen.selected_tractor = {"tractor_id": 7, "driver_name": "محمد السائق", "tractor_code": 12}
    screen.show_statement()
    assert screen.table.rowCount() == 3            # opening + 2 movements
    assert screen.cards["opening"].text() == "50,000.00"
    assert screen.cards["debit"].text() == "2,950.00"
    assert screen.cards["credit"].text() == "20,000.00"
    assert screen.cards["balance"].text() == "32,950.00"
    assert screen.closing_label.text() == "الرصيد الحالي: 32,950.00"
    assert screen.count_label.text() == "عدد الحركات: 2"
    assert screen.bon_button.isEnabled()           # enabled once shown


def test_unfiltered_opening_card_is_labelled_opening_balance(screen):
    screen.selected_tractor = {"tractor_id": 7, "driver_name": "x", "tractor_code": 1}
    screen.show_statement()
    assert screen._card_captions["opening"].text() == "رصيد أول المدة"


def test_filtered_opening_card_is_labelled_carry_forward(screen):
    screen.service._result = _result(carry=True)
    screen.selected_tractor = {"tractor_id": 7, "driver_name": "x", "tractor_code": 1}
    screen.show_statement()
    assert screen._card_captions["opening"].text() == "رصيد سابق"


def test_the_donut_shows_the_payment_ratio(screen):
    screen.selected_tractor = {"tractor_id": 7, "driver_name": "x", "tractor_code": 1}
    screen.show_statement()
    # paid 20,000 / (opening 50,000 + debit 2,950 = 52,950) = 37.77% -> 37.8%
    assert screen.donut._label == "37.8%"


def test_debit_and_credit_land_in_their_columns(screen):
    screen.selected_tractor = {"tractor_id": 7, "driver_name": "x", "tractor_code": 1}
    screen.show_statement()
    keys = [c.key for c in screen.columns]
    debit_col = keys.index("debit")
    credit_col = keys.index("credit")
    assert screen.table.item(1, debit_col).text() == "2,950.00"
    assert screen.table.item(1, credit_col).text() == ""
    assert screen.table.item(2, credit_col).text() == "20,000.00"
    assert screen.table.item(2, debit_col).text() == ""


# --- the bon summary ---------------------------------------------------------

def test_open_bon_summary_runs_after_showing(screen, monkeypatch):
    captured = {}

    def fake_exec(self):
        captured["cols"] = [c.label for c in self.summary.columns]
        captured["rows"] = len(self.summary.rows)
        return 0

    monkeypatch.setattr(
        "app.ui.dialogs.tawrid_bon_summary_dialog.TawridBonSummaryDialog.exec",
        fake_exec, raising=True,
    )
    screen.selected_tractor = {"tractor_id": 7, "driver_name": "محمد السائق", "tractor_code": 12}
    screen.show_statement()
    screen.open_bon_summary()
    assert captured["cols"][1] == "اسم العميل"   # grouped by customer
    assert captured["rows"] == 1


# --- validation --------------------------------------------------------------

def test_show_without_a_tractor_warns(screen, monkeypatch):
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.setdefault("w", a))
    screen.selected_tractor = None
    screen.show_statement()
    assert "w" in warned
    assert screen.service.built is None


def test_reset_clears_everything(screen):
    screen.selected_tractor = {"tractor_id": 7, "driver_name": "x", "tractor_code": 1}
    screen.show_statement()
    screen.reset_filters()
    assert screen.selected_tractor is None
    assert screen.current_result is None
    assert screen.table.rowCount() == 0
    assert screen.cards["balance"].text() == "—"
    assert screen.tractor_label.text() == "— لم يُختَر —"
    assert not screen.bon_button.isEnabled()


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


def test_print_data_has_rows_summary_and_bon(screen):
    screen.selected_tractor = {"tractor_id": 7, "driver_name": "محمد السائق", "tractor_code": 12}
    screen.show_statement()
    data = screen._print_data()
    assert data["title"] == "كشف حساب الجرارات"
    assert data["customer_label"] == "محمد السائق"  # party label reused by the template
    assert len(data["rows"]) == 3 and data["rows"][0]["is_opening"] is True
    # column sums (opening 50,000 + بون 2,950) computed for the closing row
    assert data["summary"]["col_debit"] == "52,950.00"
    assert data["summary"]["closing"] == "32,950.00"
    assert data["summary"]["closing_label"] == "الرصيد الختامي المستحق للجرار"
    # the tractor HAS a bon block, labelled «اسم العميل»
    assert data["bon"]["item_label"] == "اسم العميل"
    assert len(data["bon"]["rows"]) == 1
    assert data["bon"]["rows"][0]["item"] == "عصام ابو جبل"
    assert data["bon"]["count"] == "2"
