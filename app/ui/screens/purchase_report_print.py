"""Printable Purchase Report (تقرير المشتريات) — «النموذج الثالث» (green banner).

Renders the report as a single A4 **portrait** HTML sheet through
``QWebEngineView`` — the same Chromium path the profit report, production-orders
report and the invoice templates use (one source of truth for preview, print and
PDF; it paginates, so the detail list flows and the column header repeats per
page).

The sheet carries the company **letterhead** (Arabic right · logo centre ·
English left), reusing ``company_logo_data_uri`` and reading the company row
straight from ``companies`` — identical to the profit report. The letterhead is
PRINT/PDF ONLY; the on-screen report never shows it. Presentation only: every
value comes pre-formatted from the read-only service.

Layout (chosen by the user from ten print mock-ups, 2026-08-20): the Model-3
"green banner" — a dark-green band holding the payment-distribution donut
(نقدي / آجل) beside four glass KPI tiles (إجمالي المشتريات · عدد الفواتير ·
عدد الأصناف · أكبر مورد), then the eight-column detail table
(التاريخ · رقم الفاتورة · اسم المورد · اسم الصنف · الوحدة · الكمية · السعر ·
الإجمالي) with a total-general row.
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

from app.services.purchase_report_service import (
    PAYMENT_LABEL_CASH,
    PAYMENT_LABEL_CREDIT,
)
from app.ui.common.saudi_invoice_style import si_icon, style_button
from app.ui.screens.saudi_invoice_print import company_logo_data_uri

# --- design tokens (the reports' brand green) --------------------------------
_GREEN = "#0F6B30"
_GREEN_DARK = "#0B5326"
_GREEN_TINT = "#EFF5F0"
_RULE = "#D6E3DA"
_MUTED = "#5A6180"
_ZEBRA = "#F7FAF8"
_FONTS = 'Tahoma, Arial, "Segoe UI", "Helvetica Neue", sans-serif'

# Payment slice colours — tuned to read on the dark-green banner.
_PAY_COLORS = {PAYMENT_LABEL_CASH: "#63C88A", PAYMENT_LABEL_CREDIT: "#E9A23B"}
_PAY_FALLBACK = "#9CB3A2"

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
    summary = data.get("summary") or {}
    chips = (
        f"الفترة: {data.get('date_from_label') or '—'} إلى {data.get('date_to_label') or '—'}",
        f"طريقة الدفع: {data.get('payment_type_label') or 'الكل'}",
        f"عدد الفواتير: {summary.get('invoice_count_label') or '0'}",
    )
    return "".join(
        f'<span style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; padding:3px 9px; '
        f'border-radius:3px; margin-inline-start:6px;">{_esc(text)}</span>'
        for text in chips
    )


# ---------------------------------------------------------------------------
# Model-3 green banner: donut (نقدي / آجل) + four glass KPI tiles
# ---------------------------------------------------------------------------
def _donut_html(breakdown: list[dict[str, Any]], center_value: str) -> str:
    """A conic-gradient donut of the payment breakdown, sized for the banner."""
    if not breakdown:
        return (
            '<div style="width:112px; height:112px; border-radius:50%; '
            'background:rgba(255,255,255,.14);"></div>'
        )
    stops: list[str] = []
    acc = 0.0
    for slice_ in breakdown:
        share = float(slice_.get("share") or 0.0)
        color = _PAY_COLORS.get(str(slice_.get("label")), _PAY_FALLBACK)
        start = acc / 100 * 360
        acc += share
        end = acc / 100 * 360
        stops.append(f"{color} {start:.2f}deg {end:.2f}deg")
    gradient = ", ".join(stops)
    return (
        f'<div style="width:112px; height:112px; border-radius:50%; '
        f'background:conic-gradient({gradient}); position:relative;">'
        '<div style="position:absolute; inset:29px; background:#fff; border-radius:50%; '
        'display:flex; flex-direction:column; align-items:center; justify-content:center;">'
        f'<span style="font-size:7.5px; color:{_MUTED};">إجمالي المشتريات</span>'
        f'<span class="num" style="font-size:11px; font-weight:900; color:{_GREEN};">'
        f'{_esc(center_value)}</span>'
        '</div></div>'
    )


def _banner(data: dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    breakdown = data.get("payment_breakdown") or []
    donut = _donut_html(breakdown, summary.get("total_count_price_label") or "0")

    # Payment legend (white text on the dark band).
    legend_rows = "".join(
        '<div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">'
        f'<span style="width:10px; height:10px; border-radius:3px; '
        f'background:{_PAY_COLORS.get(str(s.get("label")), _PAY_FALLBACK)};"></span>'
        f'<span style="font-weight:700;">{_esc(s.get("label"))}</span>'
        f'<span style="color:#CBE7D4; font-size:9px;">{float(s.get("share") or 0):.1f}%</span>'
        f'<span class="num" style="margin-inline-start:auto; font-weight:800; color:#EAF6EE;">'
        f'{_esc(s.get("value_label"))}</span></div>'
        for s in breakdown
    )
    legend = (
        f'<div style="font-size:9.5px; color:#fff; margin-top:8px; min-width:0;">{legend_rows}</div>'
        if breakdown
        else ""
    )

    def tile(label: str, value: str, small: bool = False) -> str:
        size = "14px" if small else "19px"
        return (
            '<div style="background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.22); '
            'border-radius:10px; padding:9px 11px; min-width:0;">'
            f'<div style="font-size:9.5px; color:#CDE9D6;">{_esc(label)}</div>'
            f'<div class="num" style="font-size:{size}; font-weight:900; color:#fff; margin-top:2px; '
            'overflow-wrap:anywhere;">' + _esc(value) + '</div></div>'
        )

    tiles = (
        tile("💰 إجمالي المشتريات", summary.get("total_count_price_label"))
        + tile("🧾 عدد الفواتير", summary.get("invoice_count_label"))
        + tile("📦 عدد الأصناف", summary.get("line_count_label"))
        + tile("🏆 " + str(summary.get("top_supplier_name") or "—"),
               (summary.get("top_supplier_value_label") or "0") + " ر.س", small=True)
    )
    return (
        '<div style="background:linear-gradient(135deg,#0F6B30,#0A4D22); border-radius:13px; '
        'padding:14px; margin:12px 0; color:#fff; '
        'display:grid; grid-template-columns:auto 1fr; gap:16px; align-items:center;">'
        f'<div style="display:flex; flex-direction:column; align-items:center; min-width:0;">'
        f'<div style="font-size:10px; color:#CBE7D4; margin-bottom:6px; font-weight:700;">'
        'توزيع طرق الدفع</div>'
        f'{donut}{legend}</div>'
        '<div style="display:grid; grid-template-columns:1fr 1fr; gap:9px;">'
        f'{tiles}</div>'
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
        ("التاريخ", "12%"), ("رقم الفاتورة", "12%"), ("اسم المورد", "18%"),
        ("اسم الصنف", "20%"), ("الوحدة", "8%"), ("الكمية", "9%"),
        ("السعر", "10%"), ("الإجمالي", "11%"),
    )
    head = "".join(
        f'<th style="background:{_GREEN}; color:#fff; font-weight:700; padding:7px 4px; '
        f'width:{width};">{label}</th>'
        for label, width in head_cols
    )
    # date · invoice# · supplier · item · unit · quantity · price · total
    num_cols = {"issue_date", "invoice_number", "item_count", "unit_price", "count_price_total"}
    keys = ("issue_date", "invoice_number", "supplier_name", "item_name",
            "unit", "item_count", "unit_price", "count_price_total")
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
    foot = (
        f'<tr><td colspan="7" style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; '
        f'font-weight:900; text-align:center; padding:7px; border:1px solid {_RULE};">'
        'الإجمالي العام</td>'
        f'<td class="num" style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; font-weight:900; '
        f'text-align:center; border:1px solid {_RULE};">'
        f'{_esc(summary.get("total_count_price_label"))}</td></tr>'
    )
    return (
        '<table style="font-size:10.3px;"><thead><tr>'
        f"{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        f"<tfoot>{foot}</tfoot></table>"
    )


def build_report_html(data: dict[str, Any]) -> str:
    """The single purchase-report sheet (A4 portrait, Model-3 green banner)."""
    body = (
        f"{_letterhead(data.get('company'))}"
        '<div style="text-align:center; font-size:20px; font-weight:700; '
        f'color:{_GREEN};">{_esc(data.get("title") or "تقرير المشتريات")}</div>'
        '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; '
        f'justify-content:center; margin:10px 0; font-size:10.5px;">{_chips(data)}</div>'
        f"{_banner(data)}"
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
    """A4 portrait (matches the profit report; the banner + narrow columns fit)."""
    return QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Portrait,
        QMarginsF(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM, _MARGIN_MM),
        QPageLayout.Millimeter,
    )


def _default_pdf_name(data: dict[str, Any]) -> str:
    return "تقرير المشتريات.pdf"


# ---------------------------------------------------------------------------
# Preview dialog (معاينة + طباعة + تصدير PDF)
# ---------------------------------------------------------------------------
class PurchaseReportPreviewDialog(QDialog):
    """On-screen preview of the printable report, with export/print/close."""

    def __init__(self, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self.setWindowTitle("معاينة تقرير المشتريات")
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
            self, "حفظ تقرير المشتريات PDF", _default_pdf_name(self._data), "PDF (*.pdf)"
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
        parent, "حفظ تقرير المشتريات PDF", _default_pdf_name(data), "PDF (*.pdf)"
    )
    if not path:
        return

    from PySide6.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage(parent)
    holder = getattr(parent, "_purchase_report_pdf_pages", None)
    if holder is None:
        holder = []
        parent._purchase_report_pdf_pages = holder  # type: ignore[attr-defined]
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
    "PurchaseReportPreviewDialog",
    "export_report_to_pdf",
]
