"""Printable Sales Report (تقرير المبيعات) — «النموذج السابع» (semantic cards).

Renders the report as a single A4 **landscape** HTML sheet through
``QWebEngineView`` — the same Chromium path the profit / purchase / production
reports use (one source of truth for preview, print and PDF; it paginates, so
the detail list flows and the column header repeats per page).

The sheet carries the company **letterhead** (Arabic right · logo centre ·
English left), reusing ``company_logo_data_uri`` and reading the company row
straight from ``companies`` — identical to the other reports. The letterhead is
PRINT/PDF ONLY; the on-screen report never shows it. Presentation only: every
value comes pre-formatted from the read-only service.

Layout (chosen by the user from ten print mock-ups, 2026-08-20): the Model-7
"semantic cards" — four colour-coded KPI cards (إجمالي المبيعات أخضر · عدد
الفواتير أزرق · أكبر عميل بنفسجي · الأكثر مبيعاً كهرماني), **no donut**, then the
ten-column detail table with a soft (light) header and a totals row carrying the
net, the VAT and the total-including-VAT. Landscape fits the ten columns
(including الضريبة and الإجمالي شامل الضريبة) comfortably.
"""

from __future__ import annotations

import html
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

from app.ui.common.saudi_invoice_style import si_icon, style_button
from app.ui.screens.saudi_invoice_print import company_logo_data_uri

# --- design tokens (the reports' brand green + semantic card colours) --------
_GREEN = "#0F6B30"
_GREEN_DARK = "#0B5326"
_GREEN_TINT = "#EFF5F0"
_RULE = "#D6E3DA"
_MUTED = "#5A6180"
_ZEBRA = "#F7FAF8"
_FONTS = 'Tahoma, Arial, "Segoe UI", "Helvetica Neue", sans-serif'

# Semantic card gradients (match the Model-7 mock-up).
_CARD_GREEN = "linear-gradient(135deg,#0F7A38,#0B5326)"
_CARD_BLUE = "linear-gradient(135deg,#1D4ED8,#1E40AF)"
_CARD_VIOLET = "linear-gradient(135deg,#7C3AED,#5B21B6)"
_CARD_AMBER = "linear-gradient(135deg,#D97706,#B45309)"

_MARGIN_MM = 10.0


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


# ---------------------------------------------------------------------------
# Letterhead — Arabic right, logo centre, English left (PRINT ONLY)
# ---------------------------------------------------------------------------
def _letterhead(company: dict[str, Any] | None) -> str:
    """The company's letterhead. ``None`` (no company registered) prints nothing."""
    if not isinstance(company, dict):
        return ""
    name_ar = _esc(company.get("name_ar"))
    name_en = _esc(company.get("name_en"))
    vat = _esc(company.get("vat_number"))
    cr = _esc(company.get("commercial_registration"))
    address_ar = _esc(company.get("address_ar"))
    address_en = _esc(company.get("address_en") or company.get("address_ar"))
    logo = company_logo_data_uri(company)

    def line(text: str) -> str:
        return (
            f'<div style="font-size:9.5px; color:{_MUTED}; margin-top:2px; '
            f'overflow-wrap:anywhere;">{text}</div>'
            if text
            else ""
        )

    arabic = (
        '<div dir="rtl" style="text-align:right; min-width:0;">'
        f'<div style="font-size:14px; font-weight:700; color:{_GREEN}; '
        f'overflow-wrap:anywhere;">{name_ar}</div>'
        + line(f"الرقم الضريبي: {vat}" if vat else "")
        + line(f"السجل التجاري: {cr}" if cr else "")
        + line(address_ar)
        + "</div>"
    )
    english = (
        '<div dir="ltr" style="text-align:left; min-width:0;">'
        f'<div style="font-size:13px; font-weight:700; color:{_GREEN}; '
        f'overflow-wrap:anywhere;">{name_en}</div>'
        + line(f"VAT No.: {vat}" if vat else "")
        + line(f"C.R. No.: {cr}" if cr else "")
        + line(address_en)
        + "</div>"
    )
    centre = (
        '<div style="display:flex; align-items:center; justify-content:center;">'
        f'<img src="{logo}" alt="logo" style="max-width:130px; max-height:64px; '
        'width:auto; height:auto; object-fit:contain; display:block;" /></div>'
        if logo
        else "<div></div>"
    )
    return (
        '<div style="direction:ltr; display:grid; '
        'grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); '
        'gap:14px; align-items:center; padding-bottom:10px; margin-bottom:10px; '
        f'border-bottom:2px solid {_GREEN};">{english}{centre}{arabic}</div>'
    )


def _chips(data: dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    chips = (
        f"الفترة: {data.get('date_from_label') or '—'} إلى {data.get('date_to_label') or '—'}",
        f"العميل: {data.get('customer_label') or 'الكل'}",
        f"الصنف: {data.get('product_label') or 'الكل'}",
        f"عدد الفواتير: {summary.get('invoice_count_label') or '0'}",
    )
    return "".join(
        f'<span style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; padding:3px 9px; '
        f'border-radius:3px; margin-inline-start:6px;">{_esc(text)}</span>'
        for text in chips
    )


def _cards(summary: dict[str, Any]) -> str:
    cards = (
        ("💰 إجمالي المبيعات", summary.get("total_sales_label"), "قبل الضريبة", _CARD_GREEN),
        ("🧾 عدد الفواتير", summary.get("invoice_count_label"), "فاتورة معتمدة", _CARD_BLUE),
        ("👑 أكبر عميل", summary.get("top_customer_name") or "—",
         (summary.get("top_customer_value_label") or "0") + " ر.س", _CARD_VIOLET),
        ("🏆 الأكثر مبيعاً", summary.get("top_item_name") or "—",
         (summary.get("top_item_quantity_label") or "0") + " (الكمية)", _CARD_AMBER),
    )
    cells = "".join(
        f'<div style="flex:1; background:{bg}; border-radius:11px; padding:11px 13px; color:#fff; min-width:0;">'
        f'<div style="font-size:11px; color:#E9F1FF;">{_esc(label)}</div>'
        f'<div class="num" style="font-size:19px; font-weight:900; margin-top:2px; overflow-wrap:anywhere;">{_esc(value)}</div>'
        f'<div style="font-size:9px; color:#E4ECF7; margin-top:2px;">{_esc(sub)}</div></div>'
        for label, value, sub, bg in cards
    )
    return f'<div style="display:flex; gap:9px; margin:12px 0;">{cells}</div>'


def _table(data: dict[str, Any]) -> str:
    rows = data.get("export_rows") or []
    summary = data.get("summary") or {}
    if not rows:
        return (
            '<div style="text-align:center; padding:28px 10px; color:#64748B; '
            f'font-size:13px; border:1px dashed {_RULE}; margin-top:10px;">'
            f'{_esc(data.get("empty_message") or "لا توجد بيانات")}</div>'
        )
    head_cols = (
        ("التاريخ", "8.5%"), ("اسم العميل", "16%"), ("رقم الفاتورة", "9%"),
        ("اسم الصنف", "15%"), ("الوحدة", "6%"), ("الكمية", "6.5%"),
        ("السعر", "9%"), ("الإجمالي", "9%"), ("الضريبة", "8%"),
        ("الإجمالي شامل الضريبة", "10.5%"),
    )
    head = "".join(
        f'<th style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; font-weight:800; '
        f'padding:7px 4px; border-bottom:2px solid {_GREEN}; width:{width};">{label}</th>'
        for label, width in head_cols
    )
    # date · customer · invoice# · item · unit · quantity · price · net · VAT · incl
    num_cols = {"issue_date", "invoice_number", "quantity", "unit_price",
                "line_total", "vat_amount", "line_total_including_vat"}
    keys = ("issue_date", "customer_name", "invoice_number", "product_name",
            "unit", "quantity", "unit_price", "line_total", "vat_amount",
            "line_total_including_vat")
    body: list[str] = []
    for index, row in enumerate(rows):
        zebra = f" background:{_ZEBRA};" if index % 2 else ""
        cells = ""
        for key in keys:
            value = _esc(row.get(key))
            inner = f'<span class="num">{value}</span>' if key in num_cols else value
            cells += (
                f'<td style="border:1px solid {_RULE}; padding:5px 4px; '
                f'text-align:center;{zebra}">{inner}</td>'
            )
        body.append(f"<tr>{cells}</tr>")
    tint, dark, rule = _GREEN_TINT, _GREEN_DARK, _RULE
    foot = (
        f'<tr><td colspan="7" style="background:{tint}; color:{dark}; font-weight:900; '
        f'text-align:center; padding:7px; border:1px solid {rule};">الإجمالي العام</td>'
        f'<td class="num" style="background:{tint}; color:{dark}; font-weight:900; '
        f'text-align:center; border:1px solid {rule};">{_esc(summary.get("total_sales_label"))}</td>'
        f'<td class="num" style="background:{tint}; color:{dark}; font-weight:900; '
        f'text-align:center; border:1px solid {rule};">{_esc(summary.get("total_vat_label"))}</td>'
        f'<td class="num" style="background:{tint}; color:{dark}; font-weight:900; '
        f'text-align:center; border:1px solid {rule};">{_esc(summary.get("total_including_vat_label"))}</td></tr>'
    )
    return (
        '<table style="font-size:10px;"><thead><tr>'
        f"{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        f"<tfoot>{foot}</tfoot></table>"
    )


def build_report_html(data: dict[str, Any]) -> str:
    """The single sales-report sheet (A4 landscape, Model-7 semantic cards)."""
    summary = data.get("summary") or {}
    body = (
        f"{_letterhead(data.get('company'))}"
        '<div style="text-align:center; font-size:20px; font-weight:700; '
        f'color:{_GREEN};">{_esc(data.get("title") or "تقرير المبيعات")}</div>'
        '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; '
        f'justify-content:center; margin:10px 0; font-size:10.5px;">{_chips(data)}</div>'
        f"{_cards(summary)}"
        f"{_table(data)}"
    )
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: {_FONTS}; color: #111; background: #fff;
    -webkit-font-smoothing: antialiased;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }}
  .sheet {{ width: 1090px; margin: 0 auto; padding: 16px 20px; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  thead {{ display: table-header-group; }}
  tfoot {{ display: table-row-group; }}
  tr {{ page-break-inside: avoid; }}
  td, th {{ overflow-wrap: anywhere; }}
  .num {{ direction: ltr; unicode-bidi: embed; }}
  @media print {{ .sheet {{ width: auto; padding: 0; }} }}
</style>
</head>
<body><div class="sheet">{body}</div></body>
</html>"""


def report_page_layout() -> QPageLayout:
    """A4 landscape — the ten columns (incl. VAT) need the extra width."""
    return QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Landscape,
        QMarginsF(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM, _MARGIN_MM),
        QPageLayout.Millimeter,
    )


def _default_pdf_name(data: dict[str, Any]) -> str:
    return "تقرير المبيعات.pdf"


# ---------------------------------------------------------------------------
# Preview dialog (معاينة + طباعة + تصدير PDF)
# ---------------------------------------------------------------------------
class SalesReportPreviewDialog(QDialog):
    """On-screen preview of the printable report, with export/print/close."""

    def __init__(self, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self.setWindowTitle("معاينة تقرير المبيعات")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1040, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.export_button = QPushButton("تصدير PDF")
        self.export_button.setFixedHeight(36)
        self.export_button.setMinimumWidth(130)
        self.export_button.setCursor(Qt.PointingHandCursor)
        self.export_button.setIcon(si_icon("fa5s.file-pdf", color="#FFFFFF"))
        style_button(self.export_button, "red")
        self.export_button.clicked.connect(self._on_export)

        self.print_button = QPushButton("طباعة")
        self.print_button.setFixedHeight(36)
        self.print_button.setMinimumWidth(110)
        self.print_button.setCursor(Qt.PointingHandCursor)
        self.print_button.setIcon(si_icon("fa5s.print", color="#374151"))
        style_button(self.print_button, "white")
        self.print_button.clicked.connect(self._on_print)

        close_button = QPushButton("إغلاق")
        close_button.setFixedHeight(36)
        close_button.setMinimumWidth(100)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setIcon(si_icon("fa5s.times", color="#374151"))
        style_button(close_button, "white")
        close_button.clicked.connect(self.reject)

        bar.addWidget(self.export_button)
        bar.addWidget(self.print_button)
        bar.addStretch(1)
        bar.addWidget(close_button)
        root.addLayout(bar)

        self.view = QWebEngineView(self)
        self.view.setStyleSheet("background:#e9e9ea; border:1px solid #E5E7EB; border-radius:8px;")
        self.view.setHtml(build_report_html(data))
        root.addWidget(self.view, 1)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ تقرير المبيعات PDF", _default_pdf_name(self._data), "PDF (*.pdf)"
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
                QMessageBox.information(self, "تم", f"تم تصدير التقرير إلى:\n{file_path}")
            else:
                QMessageBox.warning(self, "تعذّر التصدير", "حدث خطأ أثناء إنشاء ملف PDF.")

        self.view.page().pdfPrintingFinished.connect(_finished)
        self.view.page().printToPdf(path, report_page_layout())

    def _on_print(self) -> None:
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, "الطباعة", "خدمة الطباعة غير متاحة.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageLayout(report_page_layout())
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.Accepted:
            return
        self._printer = printer  # keep a reference during the async print

        def _done(success: bool) -> None:  # noqa: ARG001
            try:
                self.view.printFinished.disconnect(_done)
            except (RuntimeError, TypeError):
                pass

        self.view.printFinished.connect(_done)
        self.view.print(printer)


# ---------------------------------------------------------------------------
# Direct PDF export (no preview window)
# ---------------------------------------------------------------------------
def export_report_to_pdf(parent: QWidget, data: dict[str, Any]) -> None:
    """Ask for a path and render the report straight to a PDF file."""
    path, _ = QFileDialog.getSaveFileName(
        parent, "حفظ تقرير المبيعات PDF", _default_pdf_name(data), "PDF (*.pdf)"
    )
    if not path:
        return

    from PySide6.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage(parent)
    holder = getattr(parent, "_sales_report_pdf_pages", None)
    if holder is None:
        holder = []
        parent._sales_report_pdf_pages = holder  # type: ignore[attr-defined]
    holder.append(page)

    def _cleanup() -> None:
        try:
            holder.remove(page)
        except ValueError:
            pass
        page.deleteLater()

    def _on_pdf(file_path: str, success: bool) -> None:
        if success:
            QMessageBox.information(parent, "تم", f"تم تصدير التقرير إلى:\n{file_path}")
        else:
            QMessageBox.warning(parent, "تعذّر التصدير", "حدث خطأ أثناء إنشاء ملف PDF.")
        _cleanup()

    def _on_load(ok: bool) -> None:
        if not ok:
            QMessageBox.warning(parent, "تعذّر التصدير", "تعذّر تجهيز مستند التقرير.")
            _cleanup()
            return
        QTimer.singleShot(150, lambda: page.printToPdf(path, report_page_layout()))

    page.pdfPrintingFinished.connect(_on_pdf)
    page.loadFinished.connect(_on_load)
    page.setHtml(build_report_html(data))


__all__ = [
    "build_report_html",
    "report_page_layout",
    "SalesReportPreviewDialog",
    "export_report_to_pdf",
]
