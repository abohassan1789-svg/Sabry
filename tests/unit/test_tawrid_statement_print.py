"""Tests for the statement print builder + options (النموذج الثاني, bank style).

QtWebEngine is never touched here — the HTML builder is a pure function and the
options widget is plain QtWidgets. These pin:

* all twelve columns print by default, and a column subset drops the rest;
* the ملخص البونات is appended below only when asked;
* the dark closing row shows the column sums (opening line included) so the
  printed debit/credit columns visibly add up;
* the options widget reports the selected columns and the summary flag.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import os

from app.ui.screens.tawrid_statement_print import (
    ALL_COLUMN_KEYS,
    DEFAULT_COLUMN_KEYS,
    PRINT_COLUMNS,
    StatementPrintOptions,
    _default_pdf_name,
    _remove_quietly,
    _write_temp_html,
    build_statement_html,
)

DATA = {
    "title": "كشف حساب عميل",
    "customer_label": "عصام ابو جبل",
    "customer_code": 13,
    "date_from_label": "2026-01-01",
    "date_to_label": "2026-08-22",
    "movement_count": 88,
    "empty_message": "لا توجد حركات",
    "rows": [
        {"serial": "", "date": "2025-12-31", "kind": "رصيد سابق",
         "description": "رصيد ما قبل الفترة", "price": "", "volume": "",
         "bon_no": "", "eissal": "", "trailer": "",
         "debit": "235,227.50", "credit": "", "running": "235,227.50", "is_opening": True},
        {"serial": "1", "date": "2026-01-04", "kind": "بون عميل",
         "description": "سن 6 بالبودرة", "price": "290.00", "volume": "62",
         "bon_no": "2286", "eissal": "49987", "trailer": "7386",
         "debit": "17,980.00", "credit": "", "running": "228,207.50", "is_opening": False},
        {"serial": "2", "date": "2026-01-03", "kind": "سداد دفعات",
         "description": "—", "price": "", "volume": "",
         "bon_no": "", "eissal": "797", "trailer": "",
         "debit": "", "credit": "25,000.00", "running": "210,227.50", "is_opening": False},
    ],
    "summary": {
        "opening_label": "رصيد سابق", "opening": "235,227.50",
        "debit": "1,160,490.00", "credit": "1,218,874.00", "closing": "176,843.50",
        "col_debit": "1,395,717.50", "col_credit": "1,218,874.00",
    },
    "bon": {
        "rows": [{"item": "سن 6 بالبودرة", "count": "12", "price": "290.00",
                  "volume": "62", "gross": "215,760.00", "meters": "744"}],
        "value": "1,160,490.00", "count": "49", "meters": "2988.5",
    },
}


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


# --- the builder -------------------------------------------------------------

def test_default_columns_print_but_head_is_opt_in():
    html = build_statement_html(DATA)
    for col in PRINT_COLUMNS:
        if col["key"] in DEFAULT_COLUMN_KEYS:
            assert col["label"] in html
    # رقم الوش is opt-in — not shown unless a statement asks for it.
    assert "رقم الوش" not in html
    assert "رقم الوش" in build_statement_html(DATA, list(ALL_COLUMN_KEYS))
    # bank-style closing row shows the column sums (opening included)
    assert "1,395,717.50" in html
    assert "الرصيد الختامي المستحق على العميل" in html


def test_a_column_subset_drops_the_rest():
    html = build_statement_html(DATA, ["date", "description", "debit", "credit", "running"])
    assert "رقم المقطورة" not in html
    assert "رقم الإيصال" not in html
    assert "التاريخ" in html and "رصيد جارٍ" in html


def test_summary_is_appended_only_when_asked():
    without = build_statement_html(DATA, list(ALL_COLUMN_KEYS), include_bon_summary=False)
    withit = build_statement_html(DATA, list(ALL_COLUMN_KEYS), include_bon_summary=True)
    assert "ملخص البونات" not in without
    assert "ملخص البونات" in withit
    # the three footer totals appear
    assert "2988.5" in withit and "1,160,490.00" in withit


def test_bon_summary_column_header_defaults_to_item():
    # The customer/crusher callers pass no item_label → «الصنف».
    withit = build_statement_html(DATA, list(ALL_COLUMN_KEYS), include_bon_summary=True)
    assert "الصنف" in withit


def test_bon_summary_column_header_uses_item_label_for_the_tractor():
    # The tractor groups by customer, so it passes item_label «اسم العميل».
    data = {**DATA, "bon": {**DATA["bon"], "item_label": "اسم العميل"}}
    withit = build_statement_html(data, list(ALL_COLUMN_KEYS), include_bon_summary=True)
    assert "اسم العميل" in withit


def test_empty_rows_print_the_empty_note():
    data = {**DATA, "rows": []}
    html = build_statement_html(data)
    assert "لا توجد حركات" in html


def test_no_columns_falls_back_to_all():
    html = build_statement_html(DATA, [])
    assert "رقم المقطورة" in html  # empty selection never prints a column-less table


# --- the options widget ------------------------------------------------------

def test_options_default_columns_on_summary_off(qt_app):
    opts = StatementPrintOptions()
    # Default offers every column except the opt-in رقم الوش.
    assert set(opts.columns()) == set(DEFAULT_COLUMN_KEYS)
    assert opts.include_summary() is False


def test_options_offer_head_when_allowed(qt_app):
    """A statement passing its own keys (كشف حساب عميل) gets رقم الوش too."""
    opts = StatementPrintOptions(allowed_keys=ALL_COLUMN_KEYS)
    assert "head" in opts.columns()


def test_options_reflect_toggles(qt_app):
    changed = []
    opts = StatementPrintOptions(on_change=lambda: changed.append(1))
    opts._checks["trailer"].setChecked(False)
    opts.summary_check.setChecked(True)
    assert "trailer" not in opts.columns()
    assert opts.include_summary() is True
    assert changed  # on_change fired


# --- the crusher variant (no ملخص بونات) -------------------------------------

def test_options_without_summary_checkbox_never_includes_it(qt_app):
    opts = StatementPrintOptions(show_summary_checkbox=False)
    assert not opts.summary_check.isVisibleTo(opts)
    # even if the underlying checkbox is forced on, include_summary stays False
    opts.summary_check.setChecked(True)
    assert opts.include_summary() is False


def test_caller_supplied_closing_label_is_used():
    data = {**DATA, "summary": {**DATA["summary"],
                                "closing_label": "الرصيد الختامي المستحق للكسّارة"}}
    html = build_statement_html(data)
    assert "الرصيد الختامي المستحق للكسّارة" in html
    assert "على العميل" not in html


def test_default_closing_label_falls_back_to_customer():
    html = build_statement_html(DATA)  # no closing_label key
    assert "الرصيد الختامي المستحق على العميل" in html


# --- the temp-file loader (setHtml ~2 MB cap workaround) ----------------------

def test_write_temp_html_roundtrips_utf8_then_removes():
    big = build_statement_html(DATA)  # real Arabic HTML
    path = _write_temp_html(big)
    try:
        assert path.endswith(".html") and os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            assert f.read() == big
    finally:
        _remove_quietly(path)
    assert not os.path.exists(path)
    _remove_quietly(path)  # removing a gone file is a no-op, never raises


def test_default_pdf_name_uses_the_report_title():
    name = _default_pdf_name({"title": "كشف حساب الكسارات", "customer_label": "الهدي"})
    assert name == "كشف حساب الكسارات - الهدي.pdf"
    # no party label → just the title
    assert _default_pdf_name({"title": "كشف حساب الكسارات"}) == "كشف حساب الكسارات.pdf"
