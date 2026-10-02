"""Printable Production Orders Report (تقرير أوامر الإنتاج).

Renders the report as a single A4 **landscape** HTML sheet through
``QWebEngineView`` — the same Chromium path the customer-statement and invoice
templates use (one source of truth for preview, print and PDF; it paginates, so
the unbounded order list flows and the column header repeats on every page).

The sheet carries the company **letterhead** (Arabic right · logo centre ·
English left), reusing ``company_logo_data_uri`` and reading the company row
straight from ``companies`` (never a manually-entered copy). Presentation only:
every value comes pre-formatted from the read-only service.
"""

from __future__ import annotations

import html
from typing import Any, Callable

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

# --- design tokens (the reports' brand green) -------------------------------
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
# Letterhead — Arabic right, logo centre, English left
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
    # `direction:ltr` on the grid pins the column order (English left, Arabic
    # right) regardless of the RTL document; each block sets its own text `dir`.
    return (
        '<div style="direction:ltr; display:grid; '
        'grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); '
        'gap:14px; align-items:center; padding-bottom:10px; margin-bottom:10px; '
        f'border-bottom:2px solid {_GREEN};">{english}{centre}{arabic}</div>'
    )


def _chips(data: dict[str, Any]) -> str:
    chips = (
        f"الفترة: {data.get('date_from_label') or '—'} إلى {data.get('date_to_label') or '—'}",
        f"{data.get('item_role_label') or 'الصنف'}: {data.get('item_label') or 'الكل'}",
    )
    return "".join(
        f'<span style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; padding:3px 9px; '
        f'border-radius:3px; margin-inline-start:6px;">{_esc(text)}</span>'
        for text in chips
    )


def _kpi_strip(summary: dict[str, Any]) -> str:
    cards = (
        ("أوامر الإنتاج", summary.get("total_orders_label")),
        ("الكمية المخططة", summary.get("total_planned_label")),
        ("المنتجات التامة", summary.get("finished_products_label")),
        ("المواد الخام", summary.get("raw_materials_label")),
        ("إجمالي المتوقع", summary.get("total_expected_label")),
        ("إجمالي الفعلي", summary.get("total_actual_label")),
        ("صافي الانحراف", summary.get("total_deviation_label")),
    )
    cells = "".join(
        '<div style="flex:1; min-width:96px; background:#fff; border:1px solid '
        f'{_RULE}; border-radius:6px; padding:7px 9px; text-align:center;">'
        f'<div style="font-size:9px; color:{_MUTED};">{_esc(label)}</div>'
        f'<div style="font-size:14px; font-weight:700; color:{_GREEN_DARK};">'
        f'{_esc(value)}</div></div>'
        for label, value in cards
    )
    return (
        '<div style="display:flex; gap:7px; flex-wrap:wrap; margin:12px 0;">'
        f"{cells}</div>"
    )


def _dev_color(sign: Any) -> str:
    return _POS if sign == "pos" else _NEG if sign == "neg" else _MUTED


def _orders_table(data: dict[str, Any]) -> str:
    orders = data.get("export_orders") or []
    lines_by_order = data.get("lines_by_order") or {}
    if not orders:
        return (
            '<div style="text-align:center; padding:28px 10px; color:#64748B; '
            f'font-size:13px; border:1px dashed {_RULE}; margin-top:10px;">'
            f'{_esc(data.get("empty_message") or "لا توجد بيانات")}</div>'
        )
    head_cols = (
        ("رقم الأمر", "10%"), ("التاريخ", "10%"), ("المنتج التام", "24%"),
        ("الكمية المخططة", "11%"), ("عدد المواد", "8%"),
        ("إجمالي المتوقع", "12%"), ("إجمالي الفعلي", "12%"), ("الانحراف", "13%"),
    )
    head = "".join(
        f'<th style="background:{_GREEN}; color:#fff; font-weight:700; padding:7px 4px; '
        f'width:{width};">{label}</th>'
        for label, width in head_cols
    )
    body: list[str] = []
    for index, order in enumerate(orders):
        zebra = f" background:{_ZEBRA};" if index % 2 else ""
        cell = f'<td style="border:1px solid {_RULE}; padding:5px 4px; text-align:center;{zebra}">'
        dev_color = _dev_color(order.get("deviation_sign"))
        body.append(
            "<tr>"
            f'{cell}{_esc(order.get("order_number"))}</td>'
            f'{cell}<span class="num">{_esc(order.get("order_date"))}</span></td>'
            f'<td style="border:1px solid {_RULE}; padding:5px 6px; text-align:right;{zebra}">'
            f'{_esc(order.get("product_name"))}</td>'
            f'{cell}<span class="num">{_esc(order.get("production_quantity"))}</span></td>'
            f'{cell}<span class="num">{_esc(order.get("material_count"))}</span></td>'
            f'{cell}<span class="num">{_esc(order.get("total_expected"))}</span></td>'
            f'{cell}<span class="num">{_esc(order.get("total_actual"))}</span></td>'
            f'{cell}<span class="num" style="color:{dev_color}; font-weight:700;">'
            f'{_esc(order.get("total_deviation"))}</span></td>'
            "</tr>"
        )
        # Material sub-rows for this order (indented nested table).
        lines = lines_by_order.get(order.get("id")) or lines_by_order.get(str(order.get("id"))) or []
        if lines:
            sub_head = "".join(
                f'<th style="background:{_GREEN_TINT}; color:{_GREEN_DARK}; font-weight:700; '
                f'padding:3px 5px; border:1px solid {_RULE};">{label}</th>'
                for label in ("الكود", "المادة الخام", "الوحدة", "المتوقع", "الفعلي", "الانحراف")
            )
            sub_rows = []
            for line in lines:
                lc = _dev_color(line.get("deviation_sign"))
                c = f'<td style="border:1px solid {_RULE}; padding:3px 5px; text-align:center;">'
                sub_rows.append(
                    "<tr>"
                    f'{c}{_esc(line.get("item_code"))}</td>'
                    f'<td style="border:1px solid {_RULE}; padding:3px 6px; text-align:right;">'
                    f'{_esc(line.get("item_name"))}</td>'
                    f'{c}{_esc(line.get("unit"))}</td>'
                    f'{c}<span class="num">{_esc(line.get("expected_quantity"))}</span></td>'
                    f'{c}<span class="num">{_esc(line.get("actual_quantity"))}</span></td>'
                    f'{c}<span class="num" style="color:{lc};">{_esc(line.get("deviation"))}</span></td>'
                    "</tr>"
                )
            body.append(
                f'<tr><td colspan="8" style="padding:0 22px 8px 22px; background:{zebra.strip() or "#fff"};">'
                '<table style="width:100%; border-collapse:collapse; font-size:9.5px;">'
                f'<thead><tr>{sub_head}</tr></thead><tbody>{"".join(sub_rows)}</tbody></table>'
                "</td></tr>"
            )
    return (
        '<table style="font-size:10.5px;"><thead><tr>'
        f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def build_report_html(data: dict[str, Any]) -> str:
    """The single production-orders report sheet (A4 landscape)."""
    summary = data.get("summary") or {}
    body = (
        f"{_letterhead(data.get('company'))}"
        '<div style="text-align:center; font-size:20px; font-weight:700; '
        f'color:{_GREEN};">{_esc(data.get("title") or "تقرير أوامر الإنتاج")}</div>'
        '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; '
        f'margin:10px 0; font-size:10.5px;">{_chips(data)}</div>'
        f"{_kpi_strip(summary)}"
        f"{_orders_table(data)}"
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
  .sheet {{ width: 1123px; margin: 0 auto; padding: 18px 20px; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  thead {{ display: table-header-group; }}
  tr {{ page-break-inside: avoid; }}
  td, th {{ overflow-wrap: anywhere; }}
  .num {{ direction: ltr; unicode-bidi: embed; }}
  @media print {{ .sheet {{ width: auto; padding: 0; }} }}
</style>
</head>
<body><div class="sheet">{body}</div></body>
</html>"""


def report_page_layout() -> QPageLayout:
    """A4 landscape (the report is wide — eight columns + nested materials)."""
    return QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Landscape,
        QMarginsF(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM, _MARGIN_MM),
        QPageLayout.Millimeter,
    )


def _default_pdf_name(data: dict[str, Any]) -> str:
    return "تقرير أوامر الإنتاج.pdf"


# ---------------------------------------------------------------------------
# Preview dialog (معاينة + طباعة + تصدير PDF)
# ---------------------------------------------------------------------------
class ProductionReportPreviewDialog(QDialog):
    """On-screen preview of the printable report, with export/print/close."""

    def __init__(self, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self.setWindowTitle("معاينة تقرير أوامر الإنتاج")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1120, 800)

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
            self, "حفظ تقرير أوامر الإنتاج PDF", _default_pdf_name(self._data), "PDF (*.pdf)"
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
        parent, "حفظ تقرير أوامر الإنتاج PDF", _default_pdf_name(data), "PDF (*.pdf)"
    )
    if not path:
        return

    from PySide6.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage(parent)
    holder = getattr(parent, "_po_report_pdf_pages", None)
    if holder is None:
        holder = []
        parent._po_report_pdf_pages = holder  # type: ignore[attr-defined]
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
    "ProductionReportPreviewDialog",
    "export_report_to_pdf",
]
