"""Printable Profit Report (تقرير الأرباح) — «النموذج الأول» (Model-6 print).

Renders the report as a single A4 **portrait** HTML sheet through
``QWebEngineView`` — the same Chromium path the production-orders report and the
invoice templates use (one source of truth for preview, print and PDF; it
paginates, so the movement list flows and the column header repeats per page).

The sheet carries the company **letterhead** (Arabic right · logo centre ·
English left), reusing ``company_logo_data_uri`` and reading the company row
straight from ``companies``. The letterhead is intentionally PRINT/PDF ONLY —
the on-screen report never shows it. Presentation only: every value comes
pre-formatted from the read-only service.

Layout (chosen by the user, 2026-08-19): three gradient KPI cards (المبيعات أخضر ·
المشتريات أحمر · صافي الربح أزرق) + a sales-vs-purchases donut + the 5-column
detail table (التاريخ · نوع الحركة · البيان · المبيعات · المشتريات) with a totals row.
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

# --- design tokens (the reports' brand green + card gradients) ---------------
_GREEN = "#0F6B30"
_GREEN_DARK = "#0B5326"
_GREEN_TINT = "#EFF5F0"
_RULE = "#D6E3DA"
_MUTED = "#5A6180"
_POS = "#047857"
_NEG = "#B91C1C"
_ZEBRA = "#F7FAF8"
_FONTS = 'Tahoma, Arial, "Segoe UI", "Helvetica Neue", sans-serif'

_MARGIN_MM = 12.0


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
    chips = (
        f"الفترة: {data.get('date_from_label') or '—'} إلى {data.get('date_to_label') or '—'}",
        f"نوع الحركة: {data.get('movement_type_label') or 'كل الحركات'}",
        f"عدد الحركات: {(data.get('summary') or {}).get('movement_count_label') or '0'}",
    )
    return "".join(
        f'<span style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; padding:3px 9px; '
        f'border-radius:3px; margin-inline-start:6px;">{_esc(text)}</span>'
        for text in chips
    )


def _cards(summary: dict[str, Any]) -> str:
    cards = (
        ("💰 إجمالي المبيعات", summary.get("total_sales_label"),
         f"{summary.get('sales_count_label') or '0'} فاتورة بيع",
         "linear-gradient(135deg,#047857,#065F46)"),
        ("🛒 إجمالي المشتريات", summary.get("total_purchases_label"),
         f"{summary.get('purchase_count_label') or '0'} فاتورة شراء",
         "linear-gradient(135deg,#B91C1C,#991B1B)"),
        ("📈 صافي الربح", summary.get("net_profit_label"),
         f"هامش الربح {summary.get('margin_label') or '—'}",
         "linear-gradient(135deg,#1D4ED8,#1E40AF)"),
    )
    cells = "".join(
        f'<div style="flex:1; background:{bg}; border-radius:11px; padding:11px 13px; color:#fff;">'
        f'<div style="font-size:11px; color:#E6F4EA;">{_esc(label)}</div>'
        f'<div class="num" style="font-size:20px; font-weight:900; margin-top:2px;">{_esc(value)}</div>'
        f'<div style="font-size:9px; color:#DCEAF7; margin-top:2px;">{_esc(sub)}</div></div>'
        for label, value, sub, bg in cards
    )
    return f'<div style="display:flex; gap:9px; margin:12px 0;">{cells}</div>'


def _donut(data: dict[str, Any]) -> str:
    """Sales-vs-purchases donut (conic-gradient) + legend + net-profit centre."""
    pie = data.get("pie") or []
    summary = data.get("summary") or {}
    if not pie:
        return ""
    stops: list[str] = []
    legend: list[str] = []
    acc = 0.0
    for slice_ in pie:
        share = float(slice_.get("share") or 0.0)
        color = str(slice_.get("color") or _GREEN)
        start = acc / 100 * 360
        acc += share
        end = acc / 100 * 360
        stops.append(f"{color} {start:.2f}deg {end:.2f}deg")
        legend.append(
            f'<div style="margin-bottom:5px;"><span style="display:inline-block; width:11px; '
            f'height:11px; border-radius:3px; background:{color}; margin-inline-start:6px; '
            f'vertical-align:-1px;"></span>{_esc(slice_.get("label"))} '
            f'{_esc(slice_.get("value_label"))} ({share:.1f}%)</div>'
        )
    gradient = ", ".join(stops)
    net = _esc(summary.get("net_profit_label"))
    return (
        '<div style="display:flex; align-items:center; gap:18px; justify-content:center; margin:6px 0 12px;">'
        f'<div style="width:96px; height:96px; border-radius:50%; background:conic-gradient({gradient}); '
        'position:relative;">'
        '<div style="position:absolute; inset:24px; background:#fff; border-radius:50%; display:flex; '
        'flex-direction:column; align-items:center; justify-content:center;">'
        f'<span style="font-size:8px; color:{_MUTED};">صافي الربح</span>'
        f'<span class="num" style="font-size:10.5px; font-weight:900; color:{_GREEN};">{net}</span>'
        '</div></div>'
        f'<div style="font-size:10.5px;">{"".join(legend)}</div>'
        '</div>'
    )


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
        ("التاريخ", "14%"), ("نوع الحركة", "12%"), ("البيان", "40%"),
        ("المبيعات", "17%"), ("المشتريات", "17%"),
    )
    head = "".join(
        f'<th style="background:{_GREEN}; color:#fff; font-weight:700; padding:7px 4px; '
        f'width:{width};">{label}</th>'
        for label, width in head_cols
    )
    body: list[str] = []
    for index, row in enumerate(rows):
        zebra = f" background:{_ZEBRA};" if index % 2 else ""
        cell = f'<td style="border:1px solid {_RULE}; padding:5px 4px; text-align:center;{zebra}">'
        type_color = _POS if row.get("type_code") == "sale" else _NEG
        sales = row.get("sales_amount") or ""
        purchases = row.get("purchase_amount") or ""
        sales_cell = (
            f'{cell}<span class="num" style="color:{_POS}; font-weight:700;">{_esc(sales)}</span></td>'
            if sales
            else f'{cell}<span style="color:#9CA3AF;">—</span></td>'
        )
        purchases_cell = (
            f'{cell}<span class="num" style="color:{_NEG}; font-weight:700;">{_esc(purchases)}</span></td>'
            if purchases
            else f'{cell}<span style="color:#9CA3AF;">—</span></td>'
        )
        body.append(
            "<tr>"
            f'{cell}<span class="num">{_esc(row.get("date"))}</span></td>'
            f'{cell}<span style="color:{type_color}; font-weight:700;">{_esc(row.get("type_label"))}</span></td>'
            f'{cell}{_esc(row.get("statement"))}</td>'
            f'{sales_cell}{purchases_cell}</tr>'
        )
    foot = (
        f'<tr><td colspan="3" style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; font-weight:900; '
        'text-align:center; padding:7px; border:1px solid ' + _RULE + ';">الإجمالي</td>'
        f'<td class="num" style="background:{_GREEN_TINT}; color:{_POS}; font-weight:900; '
        f'text-align:center; border:1px solid {_RULE};">{_esc(summary.get("total_sales_label"))}</td>'
        f'<td class="num" style="background:{_GREEN_TINT}; color:{_NEG}; font-weight:900; '
        f'text-align:center; border:1px solid {_RULE};">{_esc(summary.get("total_purchases_label"))}</td></tr>'
    )
    return (
        '<table style="font-size:10.5px;"><thead><tr>'
        f"{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        f"<tfoot>{foot}</tfoot></table>"
    )


def build_report_html(data: dict[str, Any]) -> str:
    """The single profit-report sheet (A4 portrait)."""
    summary = data.get("summary") or {}
    body = (
        f"{_letterhead(data.get('company'))}"
        '<div style="text-align:center; font-size:20px; font-weight:700; '
        f'color:{_GREEN};">{_esc(data.get("title") or "تقرير الأرباح")}</div>'
        '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; '
        f'justify-content:center; margin:10px 0; font-size:10.5px;">{_chips(data)}</div>'
        f"{_cards(summary)}"
        f"{_donut(data)}"
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
  .sheet {{ width: 794px; margin: 0 auto; padding: 18px 22px; }}
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
    """A4 portrait (five narrow columns fit portrait comfortably)."""
    return QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Portrait,
        QMarginsF(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM, _MARGIN_MM),
        QPageLayout.Millimeter,
    )


def _default_pdf_name(data: dict[str, Any]) -> str:
    return "تقرير الأرباح.pdf"


# ---------------------------------------------------------------------------
# Preview dialog (معاينة + طباعة + تصدير PDF)
# ---------------------------------------------------------------------------
class ProfitReportPreviewDialog(QDialog):
    """On-screen preview of the printable report, with export/print/close."""

    def __init__(self, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self.setWindowTitle("معاينة تقرير الأرباح")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 820)

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
            self, "حفظ تقرير الأرباح PDF", _default_pdf_name(self._data), "PDF (*.pdf)"
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
        parent, "حفظ تقرير الأرباح PDF", _default_pdf_name(data), "PDF (*.pdf)"
    )
    if not path:
        return

    from PySide6.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage(parent)
    holder = getattr(parent, "_profit_report_pdf_pages", None)
    if holder is None:
        holder = []
        parent._profit_report_pdf_pages = holder  # type: ignore[attr-defined]
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
    "ProfitReportPreviewDialog",
    "export_report_to_pdf",
]
