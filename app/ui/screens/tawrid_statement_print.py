"""طباعة/معاينة/PDF لكشف حساب عميل — قسم التوريدات.

القالب **النموذج الثاني (كشف بنكي)** الذي اختاره المستخدم: مدين/دائن ملوّنان،
مجاميع ككروت، صف ختامي داكن بالرصيد المستحق — مع عمود الرصيد الجاري وسطر «رصيد
سابق» في أوله. مبني على نفس فكرة :mod:`app.ui.screens.customer_statement_print`:
HTML واحد يُعاين ويُطبع ويُصدَّر PDF عبر Chromium (``QWebEngineView``)، يقسّم الصفحات
تلقائياً ويكرّر رأس الجدول.

خاصيتان طلبهما المستخدم:

* **اختيار الأعمدة التي تظهر في الطباعة** — الطباعة تشمل كل الأعمدة الاثني عشر
  افتراضياً، مع إمكانية إخفاء أيٍّ منها من لوحة الخيارات.
* **ملخص البونات يُلحَق أسفل الكشف** بعد انتهاء التفاصيل (وليس بجانبه) عند تفعيل
  الشيك بوكس «إرفاق ملخص البونات».

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
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.reports.report_branding import logo_img_html
from app.ui.common.theme import GREEN, GREEN_DARK, _button_style

# -- design tokens (النموذج الثاني — bank style) --------------------------------
_GREEN = "#137A38"
_HEAD_GREEN = "#0F6B30"
_INK = "#0F172A"
_DEBIT = "#A32D2D"
_CREDIT = "#0F6E56"
_AMBER = "#B45309"
_MUTED = "#94A3B8"
_RULE = "#E2E8F0"
_ZEBRA = "#F8FAFC"
_GREEN_TINT = "#E7F3EC"
_FONTS = 'Tahoma, Arial, "Segoe UI", "Helvetica Neue", sans-serif'
_MARGIN_MM = 12.0

# The full ledger columns, in print order (right-to-left). ``align`` and default
# ``width`` are the print layout; ``money`` marks a coloured numeric column.
PRINT_COLUMNS: tuple[dict[str, str], ...] = (
    {"key": "serial", "label": "م", "align": "center", "width": "3%"},
    {"key": "date", "label": "التاريخ", "align": "center", "width": "9%"},
    {"key": "kind", "label": "نوع الإذن", "align": "center", "width": "9%"},
    {"key": "description", "label": "الخامة / البيان", "align": "right", "width": "auto"},
    {"key": "price", "label": "السعر", "align": "center", "width": "7%"},
    {"key": "volume", "label": "التكعيب", "align": "center", "width": "6%"},
    {"key": "bon_no", "label": "رقم البون", "align": "center", "width": "7%"},
    {"key": "eissal", "label": "رقم الإيصال", "align": "center", "width": "8%"},
    {"key": "trailer", "label": "رقم المقطورة", "align": "center", "width": "7%"},
    {"key": "head", "label": "رقم الوش", "align": "center", "width": "7%"},
    {"key": "debit", "label": "مدين", "align": "center", "width": "10%"},
    {"key": "credit", "label": "دائن", "align": "center", "width": "10%"},
    {"key": "running", "label": "رصيد جارٍ", "align": "center", "width": "10%"},
)
ALL_COLUMN_KEYS: tuple[str, ...] = tuple(c["key"] for c in PRINT_COLUMNS)
# رقم الوش is opt-in — only the customer statement asks for it (by passing its own
# column keys as ``allowed_keys`` / the ``columns`` selection). It is left out of
# the defaults so the crusher and tractor statements print exactly as before.
DEFAULT_COLUMN_KEYS: tuple[str, ...] = tuple(k for k in ALL_COLUMN_KEYS if k != "head")


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _document(body: str) -> str:
    """Wrap the body in the shared A4-landscape print document (flows + repeats
    the table header on every page)."""
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{ font-family:{_FONTS}; color:#111; background:#fff;
         -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  .sheet {{ width:1123px; margin:0 auto; padding:18px 20px; }}
  table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
  thead {{ display:table-header-group; }}
  tr {{ page-break-inside:avoid; }}
  td, th {{ overflow-wrap:anywhere; }}
  .num {{ direction:ltr; }}
  .bon-block {{ page-break-inside:avoid; }}
  @media print {{ .sheet {{ width:auto; padding:0; }} }}
</style></head><body><div class="sheet">{body}</div></body></html>"""


def _card(label: str, value: str, *, bg: str, label_color: str, value_color: str) -> str:
    return (
        f'<div style="background:{bg}; padding:7px 14px; border-radius:6px; '
        f'text-align:center; min-width:118px;">'
        f'<div style="font-size:9.5px; color:{label_color};">{label}</div>'
        f'<div class="num" style="font-size:15px; font-weight:700; color:{value_color};">'
        f"{value}</div></div>"
    )


def _ledger_table(data: dict[str, Any], columns: list[dict[str, str]]) -> str:
    head = "".join(
        f'<th style="padding:7px 4px; font-weight:700; width:{c["width"]}; '
        f'text-align:{c["align"]}; color:{_head_color(c["key"])};">{_esc(c["label"])}</th>'
        for c in columns
    )
    body = []
    for index, row in enumerate(data.get("rows") or []):
        opening = bool(row.get("is_opening"))
        zebra = f" background:{_ZEBRA};" if (index % 2 and not opening) else ""
        base_bg = f" background:{_GREEN_TINT};" if opening else zebra
        cells = []
        for c in columns:
            key = c["key"]
            raw = row.get(key)
            text = _cell_html(key, raw, opening)
            weight = "700" if key == "running" else "400"
            colour = _CREDIT if opening and key == "running" else "#333"
            if opening:
                colour = GREEN_DARK
            cells.append(
                f'<td style="border-bottom:1px solid {_RULE}; padding:6px 4px; '
                f'text-align:{c["align"]}; font-weight:{weight}; color:{colour};{base_bg}">{text}</td>'
            )
        body.append(f"<tr>{''.join(cells)}</tr>")
    summary = data.get("summary") or {}
    # A dark closing row spanning the leading columns, then the debit/credit totals
    # under their own columns when both are shown.
    closing = _closing_row(columns, summary) if body else ""
    if not body:
        return _empty_note(data)
    return (
        f'<table style="font-size:10px;">'
        f'<thead><tr style="border-bottom:1.5px solid {_INK};">{head}</tr></thead>'
        f'<tbody>{"".join(body)}{closing}</tbody></table>'
    )


def _head_color(key: str) -> str:
    return {"debit": _DEBIT, "credit": _CREDIT}.get(key, "#334155")


def _cell_html(key: str, raw: Any, opening: bool) -> str:
    text = _esc(raw)
    if key in ("debit", "credit"):
        if not text:  # zero side prints «—»
            return f'<span style="color:{_MUTED};">—</span>'
        colour = _DEBIT if key == "debit" else _CREDIT
        return f'<span class="num" style="color:{colour};">{text}</span>'
    if key == "running":
        return f'<span class="num">{text}</span>'
    if key in ("price", "volume") and not text:
        return ""
    return text


def _closing_row(columns: list[dict[str, str]], summary: dict[str, Any]) -> str:
    keys = [c["key"] for c in columns]
    # Everything before debit/credit is merged into one dark label cell.
    lead = len(keys)
    debit_i = keys.index("debit") if "debit" in keys else None
    credit_i = keys.index("credit") if "credit" in keys else None
    running_i = keys.index("running") if "running" in keys else None
    tail_start = min([i for i in (debit_i, credit_i, running_i) if i is not None], default=lead)
    label_span = tail_start
    # Party-neutral: the caller supplies the closing label
    # («... على العميل» / «... للكسّارة»); the customer text is the fallback.
    closing_label = summary.get("closing_label") or "الرصيد الختامي المستحق على العميل"
    cells = (
        f'<td colspan="{label_span}" style="background:{_INK}; color:#fff; '
        f'padding:8px 6px; font-weight:700;">'
        f'{_esc(closing_label)}: '
        f'<span class="num">{_esc(summary.get("closing"))}</span></td>'
    )
    for i in range(tail_start, lead):
        key = keys[i]
        val = ""
        if key == "debit":
            # The column sum (opening line included), so the printed column adds up.
            val = _esc(summary.get("col_debit") or summary.get("debit"))
        elif key == "credit":
            val = _esc(summary.get("col_credit") or summary.get("credit"))
        elif key == "running":
            val = _esc(summary.get("closing"))
        cells += (
            f'<td class="num" style="background:{_INK}; color:#fff; padding:8px 4px; '
            f'text-align:center; font-weight:700;">{val}</td>'
        )
    return f"<tr>{cells}</tr>"


def _empty_note(data: dict[str, Any]) -> str:
    msg = _esc(data.get("empty_message") or "لا توجد حركات في الفترة المحددة")
    return (
        f'<div style="text-align:center; padding:26px 10px; color:#64748B; '
        f'font-size:13px; border:1px dashed {_RULE}; margin-top:10px;">{msg}</div>'
    )


def _bon_summary_block(data: dict[str, Any]) -> str:
    """The «ملخص البونات» table, appended BELOW the statement details."""
    bon = data.get("bon") or {}
    rows = bon.get("rows") or []
    # The grouping column header is party-neutral: «الصنف» for the customer (grouped
    # by item), «اسم العميل» for the tractor (grouped by customer). Falls back to
    # «الصنف» so the customer/crusher callers need not pass it.
    item_label = bon.get("item_label") or "الصنف"
    head = "".join(
        f'<th style="background:{_AMBER}; color:#fff; font-weight:700; padding:6px 4px; '
        f'text-align:{align};">{label}</th>'
        for label, align in (
            ("م", "center"), (item_label, "right"), ("الكمية", "center"),
            ("السعر", "center"), ("التكعيب", "center"),
            ("الإجمالى", "center"), ("إجمالى الأمتار", "center"),
        )
    )
    body = []
    for i, r in enumerate(rows):
        cell = ('<td style="border-bottom:1px solid #Eee; padding:5px 4px; '
                'text-align:center;">')
        body.append(
            "<tr>"
            f"{cell}{i + 1}</td>"
            f'<td style="border-bottom:1px solid #eee; padding:5px 6px; text-align:right;">'
            f'{_esc(r.get("item"))}</td>'
            f'{cell}{_esc(r.get("count"))}</td>'
            f'{cell}<span class="num">{_esc(r.get("price"))}</span></td>'
            f'{cell}<span class="num">{_esc(r.get("volume"))}</span></td>'
            f'{cell}<span class="num">{_esc(r.get("gross"))}</span></td>'
            f'{cell}<span class="num">{_esc(r.get("meters"))}</span></td>'
            "</tr>"
        )
    foot = (
        f'<tr style="background:{_AMBER}22;">'
        f'<td colspan="2" style="padding:7px 6px; font-weight:800; color:{_AMBER};">الإجمالي</td>'
        f'<td class="num" style="padding:7px 4px; text-align:center; font-weight:800; color:{_AMBER};">'
        f'{_esc(bon.get("count"))}</td>'
        '<td colspan="2"></td>'
        f'<td class="num" style="padding:7px 4px; text-align:center; font-weight:800; color:{_AMBER};">'
        f'{_esc(bon.get("value"))}</td>'
        f'<td class="num" style="padding:7px 4px; text-align:center; font-weight:800; color:{_AMBER};">'
        f'{_esc(bon.get("meters"))}</td></tr>'
    )
    table = (
        f'<table style="font-size:9.5px; margin-top:6px;">'
        f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}{foot}</tbody></table>'
        if body
        else '<div style="color:#94A3B8; font-size:11px; padding:8px;">لا توجد بونات في الفترة.</div>'
    )
    return (
        '<div class="bon-block" style="margin-top:18px; padding-top:12px; '
        f'border-top:2px dashed {_AMBER};">'
        f'<div style="font-weight:800; color:{_AMBER}; font-size:13px; margin-bottom:2px;">'
        "ملخص البونات</div>"
        f"{table}</div>"
    )


def build_statement_html(
    data: dict[str, Any],
    columns: list[str] | None = None,
    include_bon_summary: bool = False,
) -> str:
    """Render النموذج الثاني. ``columns`` selects which ledger columns to print
    (default all); ``include_bon_summary`` appends the ملخص البونات below."""
    selected = list(columns) if columns else list(DEFAULT_COLUMN_KEYS)
    cols = [c for c in PRINT_COLUMNS if c["key"] in selected]
    if not cols:  # never print a column-less table
        cols = list(PRINT_COLUMNS)
    summary = data.get("summary") or {}
    cards = (
        _card("إجمالي مدين", _esc(summary.get("debit")),
              bg="#FCEBEB", label_color=_DEBIT, value_color="#501313")
        + _card("إجمالي دائن", _esc(summary.get("credit")),
                bg="#E1F5EE", label_color=_CREDIT, value_color="#04342C")
        + _card(_esc(summary.get("opening_label") or "رصيد أول المدة"),
                _esc(summary.get("opening")),
                bg="#F1F5F9", label_color="#475569", value_color=_INK)
        + _card("الرصيد المستحق", _esc(summary.get("closing")),
                bg=_INK, label_color=_MUTED, value_color="#ffffff")
    )
    period = f'{_esc(data.get("date_from_label"))} إلى {_esc(data.get("date_to_label"))}'
    customer = _esc(data.get("customer_label") or "")
    code = _esc(data.get("customer_code"))
    ledger = _ledger_table(data, cols)
    bon = _bon_summary_block(data) if include_bon_summary else ""
    return _document(
        '<div style="display:flex; justify-content:space-between; '
        'align-items:flex-start; gap:14px; margin-bottom:12px;">'
        '<div style="min-width:0;">'
        f'<div style="font-size:21px; font-weight:700; color:{_INK};">'
        f'{_esc(data.get("title") or "كشف حساب عميل")}</div>'
        f'<div style="font-size:11px; color:#64748B; margin-top:3px; overflow-wrap:anywhere;">'
        f'{customer}' + (f' — كود {code}' if code else "") + f' · من {period}'
        f' · عدد الحركات: {_esc(data.get("movement_count"))}</div>'
        "</div>"
        f'<div style="display:flex; gap:8px; flex:none; flex-wrap:wrap;">{cards}</div>'
        f"{logo_img_html()}"
        "</div>"
        f"{ledger}{bon}"
    )


def statement_page_layout() -> QPageLayout:
    """A4 landscape — النموذج الثاني is wide (up to twelve columns)."""
    return QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Landscape,
        QMarginsF(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM, _MARGIN_MM),
        QPageLayout.Millimeter,
    )


def _default_pdf_name(data: dict[str, Any]) -> str:
    label = str(data.get("customer_label") or "").strip()
    safe = "".join(ch for ch in label if ch.isalnum() or ch in (" ", "-", "_")).strip()
    title = str(data.get("title") or "كشف حساب").strip()
    return f"{title} - {safe}.pdf" if safe else f"{title}.pdf"


def _write_temp_html(page_html: str) -> str:
    """Write *page_html* to a UTF-8 temp ``.html`` file and return its path.

    ``QWebEnginePage.setHtml`` encodes the whole document into a data URL capped at
    ~2 MB — and Arabic percent-encodes to several bytes per character, so a long
    ledger (a busy crusher runs into thousands of rows) silently fails to load.
    Loading a local file via ``QUrl.fromLocalFile`` has no such limit. The file is
    all-inline (no external assets), so the local origin changes nothing visually.
    The caller is responsible for deleting the returned path once the load is done.
    """
    fd, path = tempfile.mkstemp(suffix=".html", prefix="tawrid_stmt_")
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


# -- the print options (column chooser + summary checkbox) ----------------------


class StatementPrintOptions(QWidget):
    """Column checkboxes (all on by default) + «إرفاق ملخص البونات».

    ``show_summary_checkbox`` is ``False`` for the crusher statement, which has no
    «ملخص البونات» at all — the checkbox is then omitted and
    :meth:`include_summary` always returns ``False``.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        on_change: Callable[[], None] | None = None,
        show_summary_checkbox: bool = True,
        allowed_keys: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_change = on_change
        self._show_summary_checkbox = show_summary_checkbox
        # Which columns this statement offers. Default drops رقم الوش (customer-only).
        allowed = set(allowed_keys) if allowed_keys is not None else set(DEFAULT_COLUMN_KEYS)
        self._checks: dict[str, QCheckBox] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        box = QGroupBox("اختيار الأعمدة التي تظهر في الطباعة")
        box.setStyleSheet(
            "QGroupBox { font-weight:800; border:1px solid #E2E8F0; border-radius:8px; "
            "margin-top:9px; padding:6px; }"
            "QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top right; "
            f"right:12px; padding:0 8px; color:{GREEN_DARK}; }}"
        )
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 12, 10, 8)
        offered = [c for c in PRINT_COLUMNS if c["key"] in allowed]
        for i, col in enumerate(offered):
            cb = QCheckBox(col["label"])
            cb.setChecked(True)
            cb.toggled.connect(self._changed)
            self._checks[col["key"]] = cb
            grid.addWidget(cb, i // 4, i % 4)
        root.addWidget(box)

        self.summary_check = QCheckBox("إرفاق ملخص البونات أسفل الكشف")
        self.summary_check.setStyleSheet(f"font-weight:800; color:{_AMBER};")
        self.summary_check.toggled.connect(self._changed)
        if show_summary_checkbox:
            root.addWidget(self.summary_check)
        else:
            self.summary_check.setVisible(False)

    def _changed(self, *_a) -> None:
        if self._on_change is not None:
            self._on_change()

    def columns(self) -> list[str]:
        return [k for k, cb in self._checks.items() if cb.isChecked()]

    def include_summary(self) -> bool:
        return self._show_summary_checkbox and self.summary_check.isChecked()


class TawridStatementPrintOptionsDialog(QDialog):
    """A quick options dialog for the direct طباعة / PDF buttons."""

    def __init__(
        self, parent: QWidget | None = None, show_summary_checkbox: bool = True,
        allowed_keys: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("خيارات الطباعة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(460, 320)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self.options = StatementPrintOptions(
            self, show_summary_checkbox=show_summary_checkbox, allowed_keys=allowed_keys
        )
        root.addWidget(self.options)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("موافق")
        buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def columns(self) -> list[str]:
        return self.options.columns()

    def include_summary(self) -> bool:
        return self.options.include_summary()


# -- preview dialog ------------------------------------------------------------


class TawridStatementPreviewDialog(QDialog):
    """Live on-screen preview with the column chooser, the ملخص البونات checkbox,
    and print / export / close."""

    def __init__(
        self, data: dict[str, Any], parent: QWidget | None = None,
        show_summary_checkbox: bool = True,
        allowed_keys: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(parent)
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._data = data
        self._show_summary_checkbox = show_summary_checkbox
        self._allowed_keys = allowed_keys
        self.setWindowTitle("معاينة كشف الحساب")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1160, 820)

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
        self.print_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
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

        self.options = StatementPrintOptions(
            self, on_change=self._render, show_summary_checkbox=self._show_summary_checkbox,
            allowed_keys=self._allowed_keys,
        )
        root.addWidget(self.options)

        self.view = QWebEngineView(self)
        self.view.setStyleSheet("background:#e9e9ea; border:1px solid #E5E7EB; border-radius:8px;")
        root.addWidget(self.view, 1)
        self._tmp_files: list[str] = []
        self.finished.connect(self._cleanup_tmp)
        self._render()

    def _render(self) -> None:
        # Load via a temp file, not setHtml — a long crusher ledger exceeds the
        # setHtml ~2 MB data-URL cap. Delete the previous temp once the new one loads.
        stale = list(self._tmp_files)
        path = _write_temp_html(
            build_statement_html(self._data, self.options.columns(), self.options.include_summary())
        )
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
            self, "حفظ كشف الحساب PDF", _default_pdf_name(self._data), "PDF (*.pdf)"
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

        def _done(_success: bool) -> None:
            try:
                self.view.printFinished.disconnect(_done)
            except (RuntimeError, TypeError):
                pass

        self.view.printFinished.connect(_done)
        self.view.print(printer)


# -- direct export / print (used by the toolbar طباعة / PDF buttons) -----------


def export_statement_to_pdf(
    parent: QWidget, data: dict[str, Any],
    columns: list[str] | None = None, include_bon_summary: bool = False,
) -> None:
    """Render straight to a PDF file (no preview window)."""
    path, _ = QFileDialog.getSaveFileName(
        parent, "حفظ كشف الحساب PDF", _default_pdf_name(data), "PDF (*.pdf)"
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

    tmp_path = _write_temp_html(build_statement_html(data, columns, include_bon_summary))

    def _cleanup() -> None:
        _remove_quietly(tmp_path)
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
            QMessageBox.warning(parent, "تعذّر التصدير", "تعذّر تجهيز المستند.")
            _cleanup()
            return
        QTimer.singleShot(150, lambda: page.printToPdf(path, statement_page_layout()))

    page.pdfPrintingFinished.connect(_on_pdf)
    page.loadFinished.connect(_on_load)
    page.setUrl(QUrl.fromLocalFile(tmp_path))


def print_statement(
    parent: QWidget, data: dict[str, Any],
    columns: list[str] | None = None, include_bon_summary: bool = False,
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

    tmp_path = _write_temp_html(build_statement_html(data, columns, include_bon_summary))

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
    view.setUrl(QUrl.fromLocalFile(tmp_path))


__all__ = [
    "PRINT_COLUMNS",
    "ALL_COLUMN_KEYS",
    "build_statement_html",
    "statement_page_layout",
    "StatementPrintOptions",
    "TawridStatementPrintOptionsDialog",
    "TawridStatementPreviewDialog",
    "export_statement_to_pdf",
    "print_statement",
]
