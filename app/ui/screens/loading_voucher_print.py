"""Printable loading voucher (سند تحميل) — preview + print + PDF export.

Renders the approved **Model 1** print design (الكلاسيكي المؤطّر): an A4 sheet
with a double frame, a bilingual letterhead (Arabic factory block on the right,
English factory name on the left — no logo), a boxed «سند تحميل» title, a
key/value data table, and two captioned signature slots at the bottom
(«توقيع السائق» / «توقيع المشغل»). The whole sheet is set in **Arial** at the
user's request.

Like every other printout in the app, the most faithful reproduction is to
render HTML/CSS in a ``QWebEngineView`` and let Chromium print it to PDF. This
module mirrors :mod:`app.ui.screens.saudi_receipt_voucher_print`:

* :func:`build_loading_voucher_html` — the template, populated from a live
  ``data`` dict collected from the screen (works before or after save);
* :class:`LoadingVoucherPreviewDialog` — the on-screen preview with its own
  «تصدير PDF» / «طباعة» / «إغلاق» buttons;
* :func:`export_loading_voucher_to_pdf` — a direct "save as PDF" helper.

It is presentation only: it never touches the database.
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

# Design tokens (Model 1 — classic framed, green accent matching the app).
_GREEN = "#00843D"
_GREEN_DEEP = "#046A31"
_GREEN_INK = "#0b3d24"
_KEY_FILL = "#f3f8f5"
_BORDER = "#cdd8d1"
_INNER = "#b9c7bf"
_MUTED = "#4a5952"


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else "")).strip()


def build_loading_voucher_html(data: dict[str, Any]) -> str:
    """Build the full printable loading-voucher HTML from a live ``data`` dict.

    Expected keys (all optional — empty cells print blank): ``number``,
    ``date``, ``time``, ``customer_name``, ``driver_name``, ``vehicle_number``,
    ``item_name``, ``quantity_tons``, ``weight_before``, ``weight_after``,
    ``notes``, and a ``company`` mapping for the letterhead (``name_ar`` /
    ``name_en`` / ``phone`` / ``address_ar`` / ``logo`` / ``logo_mime``).
    """
    number = _esc(data.get("number"))
    date = _esc(data.get("date"))
    time = _esc(data.get("time"))
    customer = _esc(data.get("customer_name"))
    driver = _esc(data.get("driver_name"))
    vehicle = _esc(data.get("vehicle_number"))
    item = _esc(data.get("item_name"))
    qty = _esc(data.get("quantity_tons"))
    weight_before = _esc(data.get("weight_before"))
    weight_after = _esc(data.get("weight_after"))
    notes = _esc(data.get("notes"))

    # -- letterhead (from the first registered company) ---------------------
    company = data.get("company") or {}
    name_ar = _esc(company.get("name_ar"))
    name_en = _esc(company.get("name_en"))
    phone = _esc(company.get("phone"))
    address_ar = _esc(company.get("address_ar"))
    address_en = _esc(company.get("address_en"))

    # Arabic block (right): name, then phone, then address — each line only when
    # it carries a value.
    ar_lines = [f'<div class="fn">{name_ar}</div>'] if name_ar else []
    if phone:
        ar_lines.append(f'<div class="cn">جوال: {phone}</div>')
    if address_ar:
        ar_lines.append(f'<div class="cn">{address_ar}</div>')
    ar_block = f'<div class="ar">{"".join(ar_lines)}</div>' if ar_lines else "<div></div>"

    # English block (left) — mirrors the Arabic block: name, then the phone
    # (same number, shown verbatim — never translated), then the English address.
    en_lines = (
        [f'<div class="fn">{name_en.replace(chr(10), "<br>")}</div>'] if name_en else []
    )
    if phone:
        en_lines.append(f'<div class="cn">Mob: {phone}</div>')
    if address_en:
        en_lines.append(f'<div class="cn">{address_en}</div>')
    en_block = f'<div class="en">{"".join(en_lines)}</div>' if en_lines else "<div></div>"

    # Logo (centre) — embedded straight from the company bytes; hidden entirely
    # when the company has no logo, per the approved design.
    logo_uri = company_logo_data_uri(company)
    logo_block = (
        f'<div class="logo"><img src="{logo_uri}" alt="logo"></div>'
        if logo_uri else ""
    )

    # A flowing (non-absolute) A4 sheet — the content is short, so it prints on a
    # single page. Arial throughout per the user's request; Latin/number runs
    # inherit Arial too so nothing needs a webfont (no network dependency).
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body {{ margin: 0; padding: 0; background: #e9eaec;
    -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  * {{ box-sizing: border-box; }}
  .sheet {{
    width: 794px; margin: 0 auto; background: #ffffff; color: #14201b;
    font-family: Arial, 'Tahoma', sans-serif; padding: 40px 44px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.12);
  }}
  @page {{ size: A4; margin: 0; }}
  @media print {{
    html, body {{ background: #ffffff; }}
    .sheet {{ box-shadow: none; page-break-inside: avoid; break-inside: avoid; }}
  }}
  .frame {{ border: 2.5px solid {_GREEN_DEEP}; padding: 22px; border-radius: 2px; }}
  .inner {{ border: 1px solid {_INNER}; padding: 22px 24px; border-radius: 2px; }}
  .lh {{ display: flex; justify-content: space-between; align-items: center;
    gap: 18px; border-bottom: 2px solid {_GREEN_DEEP}; padding-bottom: 15px; }}
  .lh .ar {{ font-weight: 800; color: {_GREEN_INK}; line-height: 1.4; }}
  .lh .ar .fn {{ font-size: 20px; }}
  .lh .ar .cn {{ font-size: 13px; font-weight: 700; color: {_MUTED}; margin-top: 5px; }}
  .lh .en {{ text-align: left; direction: ltr; }}
  .lh .en .fn {{ font-weight: 800; color: {_GREEN_DEEP}; font-size: 15px;
    line-height: 1.3; letter-spacing: .3px; }}
  .lh .en .cn {{ font-size: 12px; font-weight: 700; color: {_MUTED};
    margin-top: 4px; line-height: 1.4; }}
  .lh .logo {{ flex: none; }}
  .lh .logo img {{ max-height: 72px; max-width: 160px; width: auto; height: auto;
    display: block; object-fit: contain; }}
  .doc-title {{ text-align: center; font-weight: 800; color: {_GREEN_INK};
    margin: 20px 0; font-size: 23px; letter-spacing: 1px; border: 1.5px solid {_GREEN_DEEP};
    border-radius: 999px; padding: 8px 0; background: #fbfdfb; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ border: 1px solid {_BORDER}; padding: 11px 14px; font-size: 14.5px; }}
  td.k {{ background: {_KEY_FILL}; font-weight: 800; color: {_GREEN_INK};
    width: 22%; white-space: nowrap; }}
  td.v {{ font-weight: 700; }}
  .sign {{ display: flex; gap: 48px; margin-top: 34px; }}
  .sign .slot {{ flex: 1; text-align: center; }}
  .sign .line {{ border-top: 1.5px dashed #9fb0a7; margin-bottom: 9px; height: 46px; }}
  .sign .cap {{ font-size: 14px; font-weight: 800; color: #33413a; }}
</style>
</head>
<body>
  <div class="sheet">
    <div class="frame"><div class="inner">
      <div class="lh">
        {ar_block}
        {logo_block}
        {en_block}
      </div>

      <div class="doc-title">سند تحميل</div>

      <table>
        <tr><td class="k">رقم السند</td><td class="v">{number}</td>
            <td class="k">التاريخ</td><td class="v">{date}</td></tr>
        <tr><td class="k">الوقت</td><td class="v">{time}</td>
            <td class="k">اسم العميل</td><td class="v">{customer}</td></tr>
        <tr><td class="k">اسم السائق</td><td class="v">{driver}</td>
            <td class="k">رقم السيارة</td><td class="v">{vehicle}</td></tr>
        <tr><td class="k">اسم الصنف</td><td class="v">{item}</td>
            <td class="k">الكمية بالطن</td><td class="v">{qty}</td></tr>
        <tr><td class="k">وزن قبل التحميل</td><td class="v">{weight_before}</td>
            <td class="k">وزن بعد التحميل</td><td class="v">{weight_after}</td></tr>
        <tr><td class="k">ملاحظات</td><td class="v" colspan="3">{notes}</td></tr>
      </table>

      <div class="sign">
        <div class="slot"><div class="line"></div><div class="cap">توقيع السائق</div></div>
        <div class="slot"><div class="line"></div><div class="cap">توقيع المشغل</div></div>
      </div>
    </div></div>
  </div>
</body>
</html>"""


# ======================================================================
# PDF page layout
# ======================================================================
def _page_layout() -> QPageLayout:
    """A4 portrait with zero margins — matches the 794px design sheet."""
    return QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Portrait,
        QMarginsF(0, 0, 0, 0),
    )


def _default_pdf_name(data: dict[str, Any]) -> str:
    number = str(data.get("number") or "").strip() or "loading"
    safe = "".join(ch for ch in number if ch.isalnum() or ch in ("-", "_")) or "loading"
    return f"سند_تحميل_{safe}.pdf"


# ======================================================================
# Preview dialog
# ======================================================================
class LoadingVoucherPreviewDialog(QDialog):
    """On-screen preview of the printable loading voucher, with export/print/close."""

    def __init__(
        self,
        data: dict[str, Any],
        parent: QWidget | None = None,
        html_builder: Callable[[dict[str, Any]], str] = build_loading_voucher_html,
    ) -> None:
        super().__init__(parent)
        self._data = data
        self._html_builder = html_builder
        self.setWindowTitle("معاينة سند التحميل")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 940)

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
        self.view.setStyleSheet(
            "background:#e9eaec; border:1px solid #E5E7EB; border-radius:8px;"
        )
        self.view.setHtml(html_builder(data))
        root.addWidget(self.view, 1)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ سند التحميل PDF", _default_pdf_name(self._data), "PDF (*.pdf)"
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
                QMessageBox.information(self, "تم", f"تم تصدير السند إلى:\n{file_path}")
            else:
                QMessageBox.warning(self, "تعذّر التصدير", "حدث خطأ أثناء إنشاء ملف PDF.")

        self.view.page().pdfPrintingFinished.connect(_finished)
        self.view.page().printToPdf(path, _page_layout())

    def _on_print(self) -> None:
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, "الطباعة", "خدمة الطباعة غير متاحة.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.Accepted:
            return
        self._printer = printer  # keep a reference during async print

        def _done(success: bool) -> None:  # noqa: ARG001
            try:
                self.view.printFinished.disconnect(_done)
            except (RuntimeError, TypeError):
                pass

        self.view.printFinished.connect(_done)
        self.view.print(printer)


# ======================================================================
# Direct PDF export (no preview window)
# ======================================================================
def export_loading_voucher_to_pdf(
    parent: QWidget,
    data: dict[str, Any],
    html_builder: Callable[[dict[str, Any]], str] = build_loading_voucher_html,
) -> None:
    """Ask for a path and render the voucher straight to a PDF file.

    Renders the markup off-screen in a ``QWebEnginePage`` and prints it once
    loading settles. The page is parented and held so it lives until the async
    PDF write completes.
    """
    path, _ = QFileDialog.getSaveFileName(
        parent, "حفظ سند التحميل PDF", _default_pdf_name(data), "PDF (*.pdf)"
    )
    if not path:
        return

    from PySide6.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage(parent)
    holder = getattr(parent, "_lv_pdf_export_pages", None)
    if holder is None:
        holder = []
        parent._lv_pdf_export_pages = holder  # type: ignore[attr-defined]
    holder.append(page)

    def _cleanup() -> None:
        try:
            holder.remove(page)
        except ValueError:
            pass
        page.deleteLater()

    def _on_pdf(file_path: str, success: bool) -> None:
        if success:
            QMessageBox.information(parent, "تم", f"تم تصدير السند إلى:\n{file_path}")
        else:
            QMessageBox.warning(parent, "تعذّر التصدير", "حدث خطأ أثناء إنشاء ملف PDF.")
        _cleanup()

    def _on_load(ok: bool) -> None:
        if not ok:
            QMessageBox.warning(parent, "تعذّر التصدير", "تعذّر تجهيز مستند السند.")
            _cleanup()
            return
        QTimer.singleShot(150, lambda: page.printToPdf(path, _page_layout()))

    page.pdfPrintingFinished.connect(_on_pdf)
    page.loadFinished.connect(_on_load)
    page.setHtml(html_builder(data))


__all__ = [
    "build_loading_voucher_html",
    "LoadingVoucherPreviewDialog",
    "export_loading_voucher_to_pdf",
]
