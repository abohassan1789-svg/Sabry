"""Printable item-level Supplier Ledger (كشف حساب المورد - تفصيلي) — dashboard layout.

Eight columns: التاريخ / رقم الحركة / نوع العملية / البيان / الكمية / السعر / القيمة /
التحصيلات, with KPI cards (رصيد أول المدة / إجمالي المشتريات / إجمالي التحصيلات /
الرصيد المتبقي) and coloured نوع العملية badges. RTL, centred, bold — the same
«نموذج 10» identity as the summary statement.

Renders through ``QWebEngineView`` (Chromium): one HTML for preview, print and PDF,
paginating an unbounded row count. Presentation only — no database access.
"""

from __future__ import annotations

import html
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QMarginsF, Qt, QTimer
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

_GREEN = "#137A38"
_GREEN_DARK = "#0F6B30"
_DEBIT = "#A32D2D"
_DEBIT_BG = "#FCEBEB"
_CREDIT = "#27500A"
_CREDIT_BG = "#EAF3DE"
_BLUE = "#185FA5"
_BLUE_BG = "#E8F0FB"
_AMBER = "#8A5A00"
_AMBER_BG = "#FFF1CC"
_GREY = "#444441"
_GREY_BG = "#F1EFE8"
_RULE = "#E2E8F0"
_MUTED = "#94A3B8"

_FONTS = 'Tahoma, Arial, "Segoe UI", "Helvetica Neue", sans-serif'
_MARGIN_MM = 12.0
_ZERO = Decimal("0.00")


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _cell_text(value: Any) -> str:
    text = _esc(value).strip()
    return text if text else f'<span style="color:{_MUTED};">—</span>'


_BADGE = {
    "opening": (_AMBER_BG, _AMBER),
    "invoice": (_CREDIT_BG, _CREDIT),
    "payment": (_DEBIT_BG, _DEBIT),
}


def _badge(kind: str, text: str) -> str:
    bg, color = _BADGE.get(kind, (_GREY_BG, _GREY))
    return (
        f'<span style="display:inline-block; padding:2px 9px; border-radius:12px; '
        f'font-size:10.5px; font-weight:bold; background:{bg}; color:{color};">{text}</span>'
    )


def _card(label: str, value: str, *, bg: str, value_color: str) -> str:
    return (
        f'<div style="flex:1; background:{bg}; border-radius:10px; padding:9px 6px; '
        f'text-align:center;">'
        f'<div style="font-size:10px; font-weight:bold; color:#5F5E5A;">{label}</div>'
        f'<div style="font-size:18px; font-weight:bold; color:{value_color}; margin-top:3px;">'
        f"{value}</div></div>"
    )


def _empty_note(data: dict[str, Any]) -> str:
    if not data.get("is_empty"):
        return ""
    message = _esc(data.get("empty_message") or "لا توجد حركات")
    return (
        f'<div style="text-align:center; padding:28px 10px; color:#64748B; '
        f'font-size:13px; font-weight:bold; border:1px dashed {_RULE}; '
        f'margin-top:10px;">{message}</div>'
    )


_WIDTH_BY_KEY = {
    "transaction_date": "9%", "movement_number": "9%", "operation_type": "11%",
    "description": "18%", "quantity": "7%", "unit_weight": "7%",
    "total_weight": "9%", "price": "8%", "value": "9%", "collections": "8%",
}
# Numeric columns that carry a colour in the ledger.
_VALUE_KEYS = frozenset({"value"})
_COLLECTION_KEYS = frozenset({"collections"})


def build_supplier_ledger_html(data: dict[str, Any]) -> str:
    """Render the item-level ledger to one printable HTML document (landscape).

    Column-driven: ``data["columns"]`` is a list of ``(key, label)`` pairs, so the
    same builder draws the عدد layout (الكمية/السعر/القيمة) and the وزن layout
    (الكمية/الوزن/إجمالي الوزن/السعر/القيمة)."""
    summary = data.get("summary") or {}
    title = _esc(data.get("title") or "كشف حساب المورد")
    company = _esc(data.get("company_name") or "")
    supplier = _esc(data.get("supplier_label") or "الكل")
    period = f'من {_esc(data.get("date_from_label"))} إلى {_esc(data.get("date_to_label"))}'
    columns = list(data.get("columns") or [])

    cards = (
        _card("رصيد أول المدة", _esc(summary.get("total_opening_label")),
              bg=_AMBER_BG, value_color=_AMBER)
        + _card("إجمالي المشتريات", _esc(summary.get("total_purchases_label")),
                bg=_CREDIT_BG, value_color=_CREDIT)
        + _card("إجمالي التحصيلات", _esc(summary.get("total_collections_label")),
                bg=_DEBIT_BG, value_color=_DEBIT)
        + _card("الرصيد المتبقي", _esc(summary.get("remaining_label")),
                bg=_BLUE_BG, value_color=_BLUE)
    )

    head = "".join(
        f'<th style="background:{_GREEN}; color:#fff; font-weight:bold; '
        f'text-align:center; padding:8px 4px; width:{_WIDTH_BY_KEY.get(key, "9%")};">{_esc(label)}</th>'
        for key, label in columns
    )

    def _data_cell(row: dict[str, Any], key: str) -> str:
        cell = ('<td style="border-bottom:1px solid ' + _RULE
                + '; padding:6px 4px; text-align:center; font-weight:bold;">')
        if key == "operation_type":
            return f'{cell}{_badge(row.get("kind") or "payment", _esc(row.get(key)))}</td>'
        content = _cell_text(row.get(key))
        if key in _VALUE_KEYS:
            content = f'<span style="color:{_CREDIT};">{content}</span>'
        elif key in _COLLECTION_KEYS:
            content = f'<span style="color:{_DEBIT};">{content}</span>'
        return f"{cell}{content}</td>"

    body = []
    for row in data.get("rows") or []:
        body.append("<tr>" + "".join(_data_cell(row, key) for key, _label in columns) + "</tr>")

    # Footer: «الإجماليات (الرصيد المتبقي)» spans the columns before القيمة, then the
    # القيمة total and (last) the التحصيلات total sit under their own columns.
    keys = [key for key, _label in columns]
    value_index = keys.index("value") if "value" in keys else len(keys)
    footer_cells = [
        f'<td colspan="{value_index}" style="padding:8px 6px; text-align:center;">'
        f'الإجماليات &nbsp;(الرصيد المتبقي: '
        f'<span style="color:{_BLUE};">{_esc(summary.get("remaining_label"))}</span>)</td>'
    ]
    for key in keys[value_index:]:
        if key == "value":
            footer_cells.append(
                f'<td style="padding:8px 4px; text-align:center; color:{_CREDIT};">'
                f'{_esc(summary.get("total_value_label"))}</td>'
            )
        elif key == "collections":
            footer_cells.append(
                f'<td style="padding:8px 4px; text-align:center; color:{_DEBIT};">'
                f'{_esc(summary.get("total_collections_label"))}</td>'
            )
        else:
            footer_cells.append('<td style="padding:8px 4px;"></td>')
    closing = (
        f'<tr style="background:#F3F6F4; font-weight:bold;">{"".join(footer_cells)}</tr>'
        if body
        else ""
    )
    table = (
        f'<table style="font-size:10.5px;"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}{closing}</tbody></table>'
        if body
        else ""
    )

    company_line = (
        f'<div style="text-align:center; font-size:12px; font-weight:bold; '
        f'color:{_GREEN_DARK};">{company}</div>'
        if company
        else ""
    )
    body_html = (
        f"{company_line}"
        f'<div style="text-align:center; font-size:20px; font-weight:bold; '
        f'color:{_GREEN}; margin-top:2px;">{title}</div>'
        f'<div style="text-align:center; font-size:11.5px; font-weight:bold; '
        f'color:#5F5E5A; margin:5px 0 12px;">المورد: {supplier} &nbsp;•&nbsp; {period}</div>'
        f'<div style="display:flex; gap:10px; margin-bottom:14px;">{cards}</div>'
        f"{table}{_empty_note(data)}"
    )
    return _document(body_html)


build_supplier_ledger_html.landscape = True  # type: ignore[attr-defined]


def _document(body: str) -> str:
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: {_FONTS};
    color: #111827;
    background: #fff;
    -webkit-font-smoothing: antialiased;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }}
  .sheet {{ width: 1123px; margin: 0 auto; padding: 18px 20px; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  thead {{ display: table-header-group; }}
  tr {{ page-break-inside: avoid; }}
  td, th {{ overflow-wrap: anywhere; }}
  @media print {{
    .sheet {{ width: auto; padding: 0; }}
  }}
</style>
</head>
<body><div class="sheet">{body}</div></body>
</html>"""


def statement_page_layout() -> QPageLayout:
    return QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Landscape,
        QMarginsF(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM, _MARGIN_MM),
        QPageLayout.Millimeter,
    )


def _default_pdf_name(data: dict[str, Any]) -> str:
    label = str(data.get("supplier_label") or "").strip()
    safe = "".join(ch for ch in label if ch.isalnum() or ch in (" ", "-", "_")).strip()
    return f"كشف حساب مورد - {safe}.pdf" if safe and safe != "الكل" else "كشف حساب المورد.pdf"


class SupplierLedgerPreviewDialog(QDialog):
    """On-screen preview of the printable ledger, with export/print/close."""

    def __init__(self, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self.setWindowTitle("معاينة كشف حساب المورد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1120, 780)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.export_button = QPushButton("تصدير PDF")
        self.print_button = QPushButton("طباعة")
        close_button = QPushButton("إغلاق")
        for button in (self.export_button, self.print_button, close_button):
            button.setFixedHeight(36)
            button.setMinimumWidth(110)
            button.setCursor(Qt.PointingHandCursor)
        self.export_button.clicked.connect(self._on_export)
        self.print_button.clicked.connect(self._on_print)
        close_button.clicked.connect(self.reject)
        bar.addWidget(self.export_button)
        bar.addWidget(self.print_button)
        bar.addStretch(1)
        bar.addWidget(close_button)
        root.addLayout(bar)

        self.view = QWebEngineView(self)
        self.view.setStyleSheet(
            "background:#e9e9ea; border:1px solid #E5E7EB; border-radius:8px;"
        )
        self.view.setHtml(build_supplier_ledger_html(data))
        root.addWidget(self.view, 1)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ كشف الحساب PDF", _default_pdf_name(self._data), "PDF (*.pdf)"
        )
        if not path:
            return
        self.export_button.setEnabled(False)

        def _finished(file_path: str, success: bool) -> None:
            self.export_button.setEnabled(True)
            try:
                self.view.page().pdfPrintingFinished.disconnect(_finished)
            except (RuntimeError, TypeError):
                pass
            if success:
                QMessageBox.information(self, "تم", f"تم تصدير كشف الحساب إلى:\n{file_path}")
            else:
                QMessageBox.warning(self, "تعذّر التصدير", "حدث خطأ أثناء إنشاء ملف PDF.")

        self.view.page().pdfPrintingFinished.connect(_finished)
        self.view.page().printToPdf(path, statement_page_layout())

    def _on_print(self) -> None:
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, "الطباعة", "خدمة الطباعة غير متاحة.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageLayout(statement_page_layout())
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.Accepted:
            return
        self._printer = printer

        def _done(success: bool) -> None:  # noqa: ARG001
            try:
                self.view.printFinished.disconnect(_done)
            except (RuntimeError, TypeError):
                pass

        self.view.printFinished.connect(_done)
        self.view.print(printer)


def export_statement_to_pdf(parent: QWidget, data: dict[str, Any]) -> None:
    path, _ = QFileDialog.getSaveFileName(
        parent, "حفظ كشف الحساب PDF", _default_pdf_name(data), "PDF (*.pdf)"
    )
    if not path:
        return

    from PySide6.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage(parent)
    holder = getattr(parent, "_supplier_ledger_pdf_pages", None)
    if holder is None:
        holder = []
        parent._supplier_ledger_pdf_pages = holder  # type: ignore[attr-defined]
    holder.append(page)

    def _cleanup() -> None:
        try:
            holder.remove(page)
        except ValueError:
            pass
        page.deleteLater()

    def _on_pdf(file_path: str, success: bool) -> None:
        if success:
            QMessageBox.information(parent, "تم", f"تم تصدير كشف الحساب إلى:\n{file_path}")
        else:
            QMessageBox.warning(parent, "تعذّر التصدير", "حدث خطأ أثناء إنشاء ملف PDF.")
        _cleanup()

    def _on_load(ok: bool) -> None:
        if not ok:
            QMessageBox.warning(parent, "تعذّر التصدير", "تعذّر تجهيز مستند كشف الحساب.")
            _cleanup()
            return
        QTimer.singleShot(150, lambda: page.printToPdf(path, statement_page_layout()))

    page.pdfPrintingFinished.connect(_on_pdf)
    page.loadFinished.connect(_on_load)
    page.setHtml(build_supplier_ledger_html(data))


def print_statement(parent: QWidget, data: dict[str, Any]) -> None:
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter

    view = QWebEngineView(parent)
    view.setVisible(False)
    holder = getattr(parent, "_supplier_ledger_print_views", None)
    if holder is None:
        holder = []
        parent._supplier_ledger_print_views = holder  # type: ignore[attr-defined]
    holder.append(view)

    def _cleanup() -> None:
        try:
            holder.remove(view)
        except ValueError:
            pass
        view.deleteLater()

    def _on_load(ok: bool) -> None:
        if not ok:
            QMessageBox.warning(parent, "الطباعة", "تعذّر تجهيز مستند كشف الحساب.")
            _cleanup()
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageLayout(statement_page_layout())
        dialog = QPrintDialog(printer, parent)
        if dialog.exec() != QPrintDialog.Accepted:
            _cleanup()
            return

        def _done(success: bool) -> None:
            if not success:
                QMessageBox.warning(parent, "الطباعة", "تعذّرت طباعة كشف الحساب.")
            _cleanup()

        view.printFinished.connect(_done)
        view.print(printer)

    view.loadFinished.connect(_on_load)
    view.setHtml(build_supplier_ledger_html(data))


__all__ = [
    "build_supplier_ledger_html",
    "statement_page_layout",
    "SupplierLedgerPreviewDialog",
    "export_statement_to_pdf",
    "print_statement",
]
