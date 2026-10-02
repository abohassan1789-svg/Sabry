"""طباعة/معاينة/PDF لكشف حساب الخزينة — قسم التوريدات.

نفس ماكينة طباعة «التقرير الشامل» (Chromium ``QWebEngineView``، محمّل الملف
المؤقت، منتقي الأعمدة، كروت المجاميع، تكرار رأس الجدول) — لكن أعمدة كشف الخزينة
مختلفة: التاريخ · النوع · الطرف · مقبوضات · مدفوعات · رصيد تراكمي · البيان، وثلاثة
مجاميع في التذييل (إجمالي المقبوضات/المدفوعات/الرصيد). اللون ذهبي ``#A16207``،
والصفحة A4 عمودية (ثمانية أعمدة تتّسع للعمودي).

وحدة موازية لـ :mod:`app.ui.screens.tawrid_comprehensive_report_print` عن قصد:
أعمدتها وتذييلها مختلفان، فبناء وحدة مستقلة بنفس الماكينة أقلّ زعزعة من التعميم.

عرضٌ فقط: لا وصول لقاعدة البيانات هنا. كل قيمة تأتي جاهزة من الشاشة/الخدمة.
"""

from __future__ import annotations

import html
import os
import tempfile
from typing import Any, Callable

from PySide6.QtCore import QMarginsF, Qt, QTimer, QUrl
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.reports.report_branding import logo_img_html
from app.ui.common.theme import _button_style

# -- design tokens (gold accent — الخزينة) --------------------------------------
_GOLD = "#A16207"
_GOLD_DARK = "#854D0E"
_INK = "#0F172A"
_RULE = "#E5E7EB"
_ZEBRA = "#FEFCE8"
_RECEIPT = "#047857"   # مقبوضات — green
_PAYMENT = "#B91C1C"   # مدفوعات — red
_FONTS = 'Tahoma, Arial, "Segoe UI", "Helvetica Neue", sans-serif'
_MARGIN_MM = 10.0

# Detail columns, in print order (right-to-left). Keys match the service's
# ``export_rows`` / ``REPORT_COLUMNS``. ``kind`` colours cells consistently;
# the dr/cr/balance columns carry a footer sum.
PRINT_COLUMNS: tuple[dict[str, str], ...] = (
    {"key": "serial", "label": "م", "align": "center", "width": "4%", "kind": "text"},
    {"key": "date", "label": "التاريخ", "align": "center", "width": "12%", "kind": "text"},
    {"key": "source", "label": "النوع", "align": "center", "width": "12%", "kind": "text"},
    {"key": "party", "label": "الطرف", "align": "right", "width": "auto", "kind": "text"},
    {"key": "dr", "label": "مقبوضات", "align": "center", "width": "13%", "kind": "receipt"},
    {"key": "cr", "label": "مدفوعات", "align": "center", "width": "13%", "kind": "payment"},
    {"key": "balance", "label": "رصيد تراكمي", "align": "center", "width": "14%", "kind": "balance"},
    {"key": "statement", "label": "البيان", "align": "right", "width": "auto", "kind": "text"},
)
ALL_COLUMN_KEYS: tuple[str, ...] = tuple(c["key"] for c in PRINT_COLUMNS)

# The columns that carry a footer total, and which totals key feeds each.
_TOTAL_KEYS: dict[str, str] = {
    "dr": "total_dr",
    "cr": "total_cr",
    "balance": "balance",
}
_KIND_COLOR: dict[str, str] = {
    "receipt": _RECEIPT,
    "payment": _PAYMENT,
    "balance": _INK,
}


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _document(body: str) -> str:
    """Wrap the body in the shared A4-portrait print document (flows + repeats the
    table header on every page)."""
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{ font-family:{_FONTS}; color:#111; background:#fff;
         -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  .sheet {{ width:794px; margin:0 auto; padding:16px 18px; }}
  table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
  thead {{ display:table-header-group; }}
  tr {{ page-break-inside:avoid; }}
  td, th {{ overflow-wrap:anywhere; }}
  .num {{ direction:ltr; }}
  @media print {{ .sheet {{ width:auto; padding:0; }} }}
</style></head><body><div class="sheet">{body}</div></body></html>"""


def _card(label: str, value: str, *, bg: str, label_color: str, value_color: str) -> str:
    return (
        f'<div style="background:{bg}; padding:7px 12px; border-radius:6px; '
        f'text-align:center; min-width:118px;">'
        f'<div style="font-size:9px; color:{label_color};">{label}</div>'
        f'<div class="num" style="font-size:14px; font-weight:700; color:{value_color};">'
        f"{value}</div></div>"
    )


def _head_color(kind: str) -> str:
    return _KIND_COLOR.get(kind, _GOLD_DARK)


def _cell_html(kind: str, raw: Any) -> str:
    text = _esc(raw)
    if not text:
        return ""
    color = _KIND_COLOR.get(kind)
    if color:
        return f'<span class="num" style="color:{color};">{text}</span>'
    return text


def _detail_table(data: dict[str, Any], columns: list[dict[str, str]]) -> str:
    head = "".join(
        f'<th style="padding:7px 3px; font-weight:700; width:{c["width"]}; '
        f'text-align:{c["align"]}; color:{_head_color(c["kind"])};">{_esc(c["label"])}</th>'
        for c in columns
    )
    body = []
    for index, row in enumerate(data.get("rows") or []):
        zebra = f" background:{_ZEBRA};" if index % 2 else ""
        cells = []
        for c in columns:
            text = _cell_html(c["kind"], row.get(c["key"]))
            cells.append(
                f'<td style="border-bottom:1px solid {_RULE}; padding:5px 3px; '
                f'text-align:{c["align"]}; color:#333;{zebra}">{text}</td>'
            )
        body.append(f"<tr>{''.join(cells)}</tr>")
    if not body:
        return _empty_note(data)
    totals_row = _totals_row(columns, data.get("totals") or {})
    return (
        f'<table style="font-size:10px;">'
        f'<thead><tr style="border-bottom:1.5px solid {_INK};">{head}</tr></thead>'
        f'<tbody>{"".join(body)}{totals_row}</tbody></table>'
    )


def _totals_row(columns: list[dict[str, str]], totals: dict[str, Any]) -> str:
    """A dark footer row: the leading columns merged into one label cell, then the
    dr/cr/balance totals under their own columns (only for columns shown)."""
    keys = [c["key"] for c in columns]
    totalled_indices = [i for i, k in enumerate(keys) if k in _TOTAL_KEYS]
    first = totalled_indices[0] if totalled_indices else len(keys)
    cells = (
        f'<td colspan="{first}" style="background:{_INK}; color:#fff; '
        f'padding:8px 6px; font-weight:700;">الإجماليات '
        f'· عدد الحركات: <span class="num">{_esc(totals.get("count"))}</span></td>'
    )
    for i in range(first, len(keys)):
        key = keys[i]
        val = _esc(totals.get(_TOTAL_KEYS[key])) if key in _TOTAL_KEYS else ""
        cells += (
            f'<td class="num" style="background:{_INK}; color:#fff; padding:8px 3px; '
            f'text-align:center; font-weight:700;">{val}</td>'
        )
    return f"<tr>{cells}</tr>"


def _empty_note(data: dict[str, Any]) -> str:
    msg = _esc(data.get("empty_message") or "لا توجد حركات مطابقة للفترة المحددة")
    return (
        f'<div style="text-align:center; padding:26px 10px; color:#64748B; '
        f'font-size:13px; border:1px dashed {_RULE}; margin-top:10px;">{msg}</div>'
    )


def build_report_html(data: dict[str, Any], columns: list[str] | None = None) -> str:
    """Render the treasury statement. ``columns`` selects which detail columns to
    print (default all)."""
    selected = list(columns) if columns else list(ALL_COLUMN_KEYS)
    cols = [c for c in PRINT_COLUMNS if c["key"] in selected]
    if not cols:  # never print a column-less table
        cols = list(PRINT_COLUMNS)
    totals = data.get("totals") or {}
    cards = (
        _card("إجمالي المقبوضات", _esc(totals.get("total_dr")),
              bg="#ECFDF5", label_color="#047857", value_color="#065F46")
        + _card("إجمالي المدفوعات", _esc(totals.get("total_cr")),
                bg="#FEF2F2", label_color="#B91C1C", value_color="#7F1D1D")
        + _card("الرصيد الحالي", _esc(totals.get("balance")),
                bg="#FEF9E7", label_color="#A16207", value_color="#713F12")
    )
    period = f'{_esc(data.get("date_from_label"))} إلى {_esc(data.get("date_to_label"))}'
    table = _detail_table(data, cols)
    return _document(
        '<div style="display:flex; justify-content:space-between; '
        'align-items:flex-start; gap:14px; margin-bottom:12px;">'
        '<div style="min-width:0;">'
        f'<div style="font-size:20px; font-weight:700; color:{_INK};">'
        f'{_esc(data.get("title") or "كشف حساب الخزينة")}</div>'
        f'<div style="font-size:11px; color:#64748B; margin-top:3px; overflow-wrap:anywhere;">'
        f'من {period} · عدد الحركات: {_esc(totals.get("count"))}'
        + "</div>"
        "</div>"
        f'<div style="display:flex; gap:7px; flex:none; flex-wrap:wrap;">{cards}</div>'
        f"{logo_img_html()}"
        "</div>"
        f"{table}"
    )


def report_page_layout() -> QPageLayout:
    """A4 portrait — the treasury statement is eight columns, fits portrait."""
    return QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Portrait,
        QMarginsF(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM, _MARGIN_MM),
        QPageLayout.Millimeter,
    )


def _default_pdf_name(data: dict[str, Any]) -> str:
    title = str(data.get("title") or "كشف حساب الخزينة").strip()
    return f"{title}.pdf"


def _write_temp_html(page_html: str) -> str:
    """Write *page_html* to a UTF-8 temp ``.html`` file and return its path.

    ``QWebEnginePage.setHtml`` caps its data URL at ~2 MB and Arabic
    percent-encodes to several bytes per character, so a large unfiltered report
    silently fails to load. Loading a local file has no such limit; the caller
    deletes the returned path once the load is done.
    """
    fd, path = tempfile.mkstemp(suffix=".html", prefix="tawrid_treasury_")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(page_html)
    return path


def _remove_quietly(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


# -- the print options (column chooser) ----------------------------------------


class ReportPrintOptions(QWidget):
    """Column checkboxes (all on by default) for the treasury detail table."""

    def __init__(
        self,
        parent: QWidget | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_change = on_change
        self._checks: dict[str, QCheckBox] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        box = QGroupBox("اختيار الأعمدة التي تظهر في الطباعة")
        box.setStyleSheet(
            "QGroupBox { font-weight:800; border:1px solid #E5E7EB; border-radius:8px; "
            "margin-top:9px; padding:6px; }"
            "QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top right; "
            f"right:12px; padding:0 8px; color:{_GOLD_DARK}; }}"
        )
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 12, 10, 8)
        for i, col in enumerate(PRINT_COLUMNS):
            cb = QCheckBox(col["label"])
            cb.setChecked(True)
            cb.toggled.connect(self._changed)
            self._checks[col["key"]] = cb
            grid.addWidget(cb, i // 4, i % 4)
        root.addWidget(box)

    def _changed(self, *_a) -> None:
        if self._on_change is not None:
            self._on_change()

    def columns(self) -> list[str]:
        return [k for k, cb in self._checks.items() if cb.isChecked()]


class TawridTreasuryPrintOptionsDialog(QDialog):
    """A quick options dialog for the direct طباعة / PDF buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("خيارات الطباعة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(520, 220)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self.options = ReportPrintOptions(self)
        root.addWidget(self.options)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("موافق")
        buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def columns(self) -> list[str]:
        return self.options.columns()


# -- preview dialog ------------------------------------------------------------


class TawridTreasuryPreviewDialog(QDialog):
    """Live on-screen preview with the column chooser and print / export / close."""

    def __init__(self, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._data = data
        self.setWindowTitle("معاينة كشف حساب الخزينة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1000, 840)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.pdf_button = QPushButton("تصدير PDF")
        self.pdf_button.setFixedHeight(36)
        self.pdf_button.setMinimumWidth(120)
        self.pdf_button.setStyleSheet(_button_style("#B91C1C", "#991B1B"))
        self.pdf_button.clicked.connect(self._on_export)
        self.print_button = QPushButton("طباعة")
        self.print_button.setFixedHeight(36)
        self.print_button.setMinimumWidth(100)
        self.print_button.setStyleSheet(_button_style(_GOLD, _GOLD_DARK))
        self.print_button.clicked.connect(self._on_print)
        close_button = QPushButton("إغلاق")
        close_button.setFixedHeight(36)
        close_button.setMinimumWidth(90)
        close_button.setStyleSheet(_button_style("#374151", "#1F2937"))
        close_button.clicked.connect(self.reject)
        bar.addWidget(self.pdf_button)
        bar.addWidget(self.print_button)
        bar.addStretch(1)
        bar.addWidget(close_button)
        root.addLayout(bar)

        self.options = ReportPrintOptions(self, on_change=self._render)
        root.addWidget(self.options)

        self.view = QWebEngineView(self)
        self.view.setStyleSheet("background:#e9e9ea; border:1px solid #E5E7EB; border-radius:8px;")
        root.addWidget(self.view, 1)
        self._tmp_files: list[str] = []
        self.finished.connect(self._cleanup_tmp)
        self._render()

    def _render(self) -> None:
        stale = list(self._tmp_files)
        path = _write_temp_html(build_report_html(self._data, self.options.columns()))
        self._tmp_files.append(path)

        def _loaded(_ok: bool) -> None:
            try:
                self.view.loadFinished.disconnect(_loaded)
            except (RuntimeError, TypeError):
                pass
            for old in stale:
                _remove_quietly(old)
                if old in self._tmp_files:
                    self._tmp_files.remove(old)

        self.view.loadFinished.connect(_loaded)
        self.view.setUrl(QUrl.fromLocalFile(path))

    def _cleanup_tmp(self, *_a) -> None:
        for path in self._tmp_files:
            _remove_quietly(path)
        self._tmp_files.clear()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ الكشف PDF", _default_pdf_name(self._data), "PDF (*.pdf)"
        )
        if not path:
            return
        self.pdf_button.setEnabled(False)

        def _finished(file_path: str, success: bool) -> None:
            self.pdf_button.setEnabled(True)
            try:
                self.view.page().pdfPrintingFinished.disconnect(_finished)
            except (RuntimeError, TypeError):
                pass
            if success:
                QMessageBox.information(self, "تم", f"تم تصدير الكشف إلى:\n{file_path}")
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
        self._printer = printer

        def _done(_success: bool) -> None:
            try:
                self.view.printFinished.disconnect(_done)
            except (RuntimeError, TypeError):
                pass

        self.view.printFinished.connect(_done)
        self.view.print(printer)


# -- direct export / print (used by the toolbar طباعة / PDF buttons) -----------


def export_report_to_pdf(
    parent: QWidget, data: dict[str, Any], columns: list[str] | None = None
) -> None:
    """Render straight to a PDF file (no preview window)."""
    path, _ = QFileDialog.getSaveFileName(
        parent, "حفظ الكشف PDF", _default_pdf_name(data), "PDF (*.pdf)"
    )
    if not path:
        return
    from PySide6.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage(parent)
    holder = getattr(parent, "_tawrid_pdf_pages", None)
    if holder is None:
        holder = []
        parent._tawrid_pdf_pages = holder  # type: ignore[attr-defined]
    holder.append(page)

    tmp_path = _write_temp_html(build_report_html(data, columns))

    def _cleanup() -> None:
        _remove_quietly(tmp_path)
        try:
            holder.remove(page)
        except ValueError:
            pass
        page.deleteLater()

    def _on_pdf(file_path: str, success: bool) -> None:
        if success:
            QMessageBox.information(parent, "تم", f"تم تصدير الكشف إلى:\n{file_path}")
        else:
            QMessageBox.warning(parent, "تعذّر التصدير", "حدث خطأ أثناء إنشاء ملف PDF.")
        _cleanup()

    def _on_load(ok: bool) -> None:
        if not ok:
            QMessageBox.warning(parent, "تعذّر التصدير", "تعذّر تجهيز المستند.")
            _cleanup()
            return
        QTimer.singleShot(150, lambda: page.printToPdf(path, report_page_layout()))

    page.pdfPrintingFinished.connect(_on_pdf)
    page.loadFinished.connect(_on_load)
    page.setUrl(QUrl.fromLocalFile(tmp_path))


def print_report(
    parent: QWidget, data: dict[str, Any], columns: list[str] | None = None
) -> None:
    """Send straight to a printer, without the preview window."""
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    from PySide6.QtWebEngineWidgets import QWebEngineView

    view = QWebEngineView(parent)
    view.setVisible(False)
    holder = getattr(parent, "_tawrid_print_views", None)
    if holder is None:
        holder = []
        parent._tawrid_print_views = holder  # type: ignore[attr-defined]
    holder.append(view)

    tmp_path = _write_temp_html(build_report_html(data, columns))

    def _cleanup() -> None:
        _remove_quietly(tmp_path)
        try:
            holder.remove(view)
        except ValueError:
            pass
        view.deleteLater()

    def _on_load(ok: bool) -> None:
        if not ok:
            QMessageBox.warning(parent, "الطباعة", "تعذّر تجهيز المستند.")
            _cleanup()
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageLayout(report_page_layout())
        dialog = QPrintDialog(printer, parent)
        if dialog.exec() != QPrintDialog.Accepted:
            _cleanup()
            return

        def _done(success: bool) -> None:
            if not success:
                QMessageBox.warning(parent, "الطباعة", "تعذّرت طباعة الكشف.")
            _cleanup()

        view.printFinished.connect(_done)
        view.print(printer)

    view.loadFinished.connect(_on_load)
    view.setUrl(QUrl.fromLocalFile(tmp_path))


__all__ = [
    "PRINT_COLUMNS",
    "ALL_COLUMN_KEYS",
    "build_report_html",
    "report_page_layout",
    "ReportPrintOptions",
    "TawridTreasuryPrintOptionsDialog",
    "TawridTreasuryPreviewDialog",
    "export_report_to_pdf",
    "print_report",
]
