"""Tests for the التقرير الشامل print builder + options (النموذج الثاني, slate).

QtWebEngine is never touched — the HTML builder is a pure function and the
options widget is plain QtWidgets. These pin:

* all fifteen columns print by default, and a column subset drops the rest;
* the dark totals row carries the five totals + the count;
* the five KPI cards show the totals; an empty result prints a note;
* the options widget reports the selected columns.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.screens.tawrid_comprehensive_report_print import (
    ALL_COLUMN_KEYS,
    PRINT_COLUMNS,
    ReportPrintOptions,
    _default_pdf_name,
    _remove_quietly,
    _write_temp_html,
    build_report_html,
)

DATA = {
    "title": "التقرير الشامل",
    "filter_label": "العميل: عصام · الصنف: سن 2",
    "date_from_label": "2026-01-01",
    "date_to_label": "2026-06-30",
    "empty_message": "لا توجد بونات",
    "rows": [
        {"serial": "1", "date": "2025-01-04", "item": "سن 2",
         "price_cus": "310.00", "cus_volume": "61", "total_cus": "18,910.00",
         "price_man": "140.00", "total_man": "8,540.00",
         "price_res": "145.00", "res_volume": "59", "total_res": "8,555.00",
         "receipt_no": "185500", "supplier": "الهدي", "customer": "عصام", "trailer": "3581"},
    ],
    "totals": {
        "total_cus": "18,910.00", "total_man": "8,540.00", "total_res": "8,555.00",
        "cus_volume": "61", "res_volume": "59", "count": "1",
    },
}


def _app():
    return QApplication.instance() or QApplication([])


def test_all_columns_present_by_default():
    html = build_report_html(DATA)
    for col in PRINT_COLUMNS:
        assert col["label"] in html
    assert "18,910.00" in html and "الهدي" in html


def test_totals_row_and_cards_carry_the_five_totals():
    html = build_report_html(DATA)
    assert "الإجماليات" in html
    assert "عدد البونات" in html
    for label in ("إجمالي تكلفة العميل", "إجمالي تكلفة السائق", "إجمالي تكلفة المورد",
                  "إجمالي تكعيب العميل", "إجمالي تكعيب المورد"):
        assert label in html


def test_a_column_subset_drops_the_rest():
    # Kept: receipt column header (not a substring of any KPI card label). Dropped:
    # the three price headers (also not card substrings) must be gone.
    html = build_report_html(DATA, columns=["serial", "date", "receipt_no"])
    assert "رقم الإيصال" in html      # kept column header
    assert "سعر العميل" not in html   # dropped
    assert "سعر السائق" not in html   # dropped
    assert "سعر المورد" not in html   # dropped


def test_empty_result_prints_a_note():
    empty = {**DATA, "rows": [], "totals": {"count": "0"}}
    html = build_report_html(empty)
    assert "لا توجد بونات" in html


def test_filter_label_appears_in_the_header():
    html = build_report_html(DATA)
    assert "العميل: عصام" in html


def test_options_widget_reports_selected_columns():
    _app()
    opts = ReportPrintOptions()
    assert set(opts.columns()) == set(ALL_COLUMN_KEYS)
    opts._checks["price_man"].setChecked(False)
    assert "price_man" not in opts.columns()


def test_default_pdf_name_uses_the_title():
    assert _default_pdf_name(DATA) == "التقرير الشامل.pdf"


def test_temp_html_roundtrip():
    path = _write_temp_html("<html>مرحبا</html>")
    try:
        with open(path, encoding="utf-8") as fh:
            assert "مرحبا" in fh.read()
    finally:
        _remove_quietly(path)
        assert not os.path.exists(path)
