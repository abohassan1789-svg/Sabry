"""Widget tests for the F1 invoice search dialog (headless / offscreen Qt).

Cover the two filters added on top of the existing text + status search: a
seller-company dropdown fed from the coded companies, and an optional issue-date
range that only constrains the query while it is switched on.
"""

from __future__ import annotations

import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ui.dialogs.saudi_invoice_dialogs import SaudiInvoiceSearchDialog


_ROWS = [
    {"id": 88, "invoice_number": "INV-88", "seller_name_ar_snapshot": "شركة أ",
     "customer_name_snapshot": "عميل", "issue_datetime": None,
     "document_status": "draft", "total_including_vat": 115},
    {"id": 12, "invoice_number": "INV-12", "seller_name_ar_snapshot": "شركة ب",
     "customer_name_snapshot": "عميل ٢", "issue_datetime": None,
     "document_status": "approved", "total_including_vat": 230},
]


class FakeService:
    """Records every search_invoices call so the test can assert the filters."""

    def __init__(self):
        self.calls: list[dict] = []
        self.companies = [
            {"id": 10, "name_ar": "شركة أ", "name_en": "A"},
            {"id": 11, "name_ar": "شركة ب", "name_en": "B"},
        ]

    def list_companies(self, limit=100):
        return list(self.companies)

    def search_invoices(self, keyword="", status=None, limit=300, *,
                        company_id=None, date_from=None, date_to=None):
        self.calls.append({
            "keyword": keyword, "status": status, "limit": limit,
            "company_id": company_id, "date_from": date_from, "date_to": date_to,
        })
        return [dict(r) for r in _ROWS]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def dialog(qapp):
    return SaudiInvoiceSearchDialog(FakeService())


@pytest.fixture()
def exported(qapp):
    """A dialog wired to a recording print callback, plus that record."""
    calls: list[tuple] = []
    dlg = SaudiInvoiceSearchDialog(
        FakeService(), print_callback=lambda iid, parent: calls.append((iid, parent))
    )
    return dlg, calls


def test_company_combo_lists_all_companies_plus_all_option(dialog):
    combo = dialog.company_combo
    # first entry is the "all companies" sentinel with no id
    assert combo.itemData(0) is None
    assert combo.itemText(0) == "كل الشركات"
    # every coded company follows, in order
    assert combo.count() == 3
    assert combo.itemData(1) == 10
    assert combo.itemData(2) == 11
    assert combo.itemText(1) == "شركة أ"


def test_date_range_is_off_by_default(dialog):
    assert dialog.date_enable.isChecked() is False
    assert dialog.date_from.isEnabled() is False
    assert dialog.date_to.isEnabled() is False
    # the initial auto-search carries no company/date constraint
    first = dialog.service.calls[0]
    assert first["company_id"] is None
    assert first["date_from"] is None and first["date_to"] is None


def test_selecting_a_company_filters_by_its_id(dialog):
    dialog.service.calls.clear()
    dialog.company_combo.setCurrentIndex(2)  # شركة ب -> id 11
    assert dialog.service.calls[-1]["company_id"] == 11


def test_enabling_date_range_passes_from_and_to(dialog):
    dialog.date_from.setDate(dialog.date_from.date().addDays(0))  # keep default
    dialog.service.calls.clear()
    dialog.date_enable.setChecked(True)

    assert dialog.date_from.isEnabled() is True
    assert dialog.date_to.isEnabled() is True
    last = dialog.service.calls[-1]
    assert isinstance(last["date_from"], datetime.date)
    assert isinstance(last["date_to"], datetime.date)
    assert last["date_from"] <= last["date_to"]


def test_date_edits_do_not_query_while_range_is_off(dialog):
    assert dialog.date_enable.isChecked() is False
    dialog.service.calls.clear()
    dialog.date_from.setDate(dialog.date_from.date().addDays(-5))
    # changing a disabled date must not trigger a search
    assert dialog.service.calls == []


# --- the per-row «تصدير» PDF column ---------------------------------------

def test_export_column_is_the_last_column_named_tasdeer(dialog):
    table = dialog.table
    last = table.columnCount() - 1
    assert table.horizontalHeaderItem(last).text() == "تصدير"
    # it does not displace the invoice-number id carried on column 0
    assert table.item(0, 0).data(Qt.UserRole) == 88


def test_every_row_has_a_pdf_link_in_the_export_column(dialog):
    table = dialog.table
    last = table.columnCount() - 1
    assert table.rowCount() == 2
    for r in range(table.rowCount()):
        widget = table.cellWidget(r, last)
        assert widget is not None
        assert "PDF" in widget.text()


def test_clicking_pdf_link_invokes_the_print_callback_with_row_id(exported, qapp):
    dlg, calls = exported
    last = dlg.table.columnCount() - 1
    link = dlg.table.cellWidget(0, last)
    link.clicked.emit()  # simulate the click on the hyperlink
    # The print flow is deferred a tick so the click can unwind first.
    assert calls == []
    qapp.processEvents()
    assert calls == [(88, dlg)]


def test_pdf_link_fires_on_release_not_on_press(qapp):
    # Opening a modal dialog while the press's mouse grab is still held freezes
    # the app once nested a few modal loops deep — so the link must activate on
    # RELEASE (grab already dropped), never on press.
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    from app.ui.dialogs.saudi_invoice_dialogs import _PdfLinkLabel

    link = _PdfLinkLabel("PDF")
    link.resize(60, 30)
    fired = []
    link.clicked.connect(lambda: fired.append(1))

    pos = QPointF(10, 10)
    link.mousePressEvent(
        QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    )
    assert fired == []  # press alone must not activate

    link.mouseReleaseEvent(
        QMouseEvent(QEvent.MouseButtonRelease, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    )
    assert fired == [1]  # release inside the widget activates exactly once


def test_pdf_link_without_a_callback_does_not_raise(dialog, monkeypatch):
    # No print_callback wired: the link must degrade gracefully, not explode.
    infos = []
    monkeypatch.setattr(
        "app.ui.dialogs.saudi_invoice_dialogs.QMessageBox.information",
        lambda *a, **k: infos.append(a),
    )
    dialog._on_export_clicked(88)
    assert len(infos) == 1
