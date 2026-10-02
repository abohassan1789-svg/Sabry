"""تقرير كشف حساب الدفعة المقدمة — النموذجان 7 و6 كتبويبين (2026-09-26).

The user picked two of the ten mockups and asked for both as tabs, 7 first:

* «نافذة منبثقة» (نموذج 7): a click on a contract opens a window with the
  contract's advance split over its extracts (a coloured bar) and the list of
  extracts that paid it back.
* «تفاصيل تحت الصف» (نموذج 6): a click opens the same list right under the
  contract's row; another click closes it.

Both tabs show the same lines and totals. «تحديد أعمدة الجدول» sits above the
tabs and applies to both; the choice is kept per user. Every figure comes from
``contractor_advance_report_service``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import QRectF, QSettings, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.contractor_advance_report_service import ContractorAdvanceReportService, lines_totals
from app.services.contractor_contracts_report_service import report_totals
from app.ui.common.theme import GREEN, TEXT, _button_style
from app.ui.screens.contracting_report_base import (
    MUTED,
    RED,
    TABLE_QSS,
    TOTAL_BG,
    ColumnChooser,
    ColumnFitter,
    ContractingReportBase,
    column_button,
    date_text,
    load_columns,
    report_settings,
    save_columns,
    table_item,
)
from app.ui.screens.contractor_contracts_screen import _money, _rate_text

PERMISSION_BASE = "contracting.contractor_advance_report"
SETTINGS_KEY = "contractor_advance_report/columns"
TAB_POPUP, TAB_INLINE = 0, 1

TEXT_COL, RATE_COL, AMOUNT_COL = "text", "rate", "amount"
# The user's 9 columns in their order: (row key, header, kind).
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("contract_date", "تاريخ العقد", TEXT_COL),
    ("company_name", "اسم الشركة", TEXT_COL),
    ("project_name", "اسم المشروع", TEXT_COL),
    ("contractor_name", "اسم المقاول", TEXT_COL),
    ("contract_value", "قيمة العقد", AMOUNT_COL),
    ("advance_payment_pct", "نسبة الدفعة\nالمقدمة", RATE_COL),
    ("advance_agreed", "قيمة الدفعة المقدمة\nمن العقد", AMOUNT_COL),
    ("advance_deducted", "إجمالي المسدد من\nالدفعة المقدمة", AMOUNT_COL),
    ("remaining_advance", "المتبقي", AMOUNT_COL),
)
COLUMN_KEYS = tuple(key for key, _header, _kind in COLUMNS)
KIND = {key: kind for key, _header, kind in COLUMNS}
HEADER = {key: header.replace("\n", " ") for key, header, _kind in COLUMNS}
DEFAULT_COLUMNS = COLUMN_KEYS

# The total cards over the table, with the user's titles (2026-09-26); the last one is the dark one.
CARDS = (
    ("contract_value", "إجمالي قيمة العقد"),
    ("advance_agreed", "إجمالي الدفعة المقدمة من العقد"),
    ("advance_deducted", "إجمالي المسدد من العقد"),
    ("remaining_advance", "إجمالي المتبقي"),
)
COLUMN_GROUPS = (("بيانات العقد", COLUMN_KEYS[:4]), ("الدفعة المقدمة", COLUMN_KEYS[4:]))

# The popup's columns: the user's list, with رقم المستخلص after التاريخ (user asked 2026-09-26).
LINE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("extract_date", "التاريخ", TEXT_COL),
    ("extract_no", "رقم المستخلص", TEXT_COL),
    ("contractor_name", "اسم المقاول", TEXT_COL),
    ("project_name", "اسم المشروع", TEXT_COL),
    ("company_name", "اسم الشركة", TEXT_COL),
    ("works_value", "إجمالي المستخلص", AMOUNT_COL),
    ("advance_payment_pct", "نسبة الدفعة المقدمة", RATE_COL),
    ("advance_payment", "قيمة الدفعة المقدمة", AMOUNT_COL),
)
LINE_KEYS = tuple(key for key, _header, _kind in LINE_COLUMNS)
LINE_KIND = {key: kind for key, _header, kind in LINE_COLUMNS}

# One colour per extract on the bar (cycled), and the unpaid rest.
SEGMENT_COLORS = ("#137A38", "#2F9D5A", "#6FC08D", "#A9DCBA")
REST_COLOR = "#E5E7EB"
SELECTED_BG = "#FEF3C7"

ROW_CONTRACT, ROW_DETAIL, ROW_TOTAL = "contract", "detail", "total"


def cell_text(row: dict[str, Any], key: str, kinds: dict[str, str]) -> str:
    """How a value is written in a cell (date, text, rate or money)."""
    value = row.get(key)
    if key in ("contract_date", "extract_date"):
        return date_text(value)
    kind = kinds[key]
    if kind == RATE_COL:
        return f"{_rate_text(value)}%"
    if kind == AMOUNT_COL:
        return _money(value)
    return str(value or "")


def _count_text(count: int) -> str:
    return f"{count} مستخلص" if count == 1 else f"{count} مستخلصات"


def _paid_pct(contract: dict[str, Any]) -> Decimal:
    agreed = contract.get("advance_agreed") or Decimal(0)
    return contract["advance_deducted"] / agreed * 100 if agreed > 0 else Decimal(0)


def _new_table(columns: int, headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, columns)
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(TABLE_QSS)
    header = table.horizontalHeader()
    header.setMinimumHeight(46)
    header.setDefaultAlignment(Qt.AlignCenter)
    return table


def fill_lines_table(table: QTableWidget, lines: list[dict[str, Any]]) -> None:
    """The extracts of one contract and their «إجمالي المسدد» row."""
    table.clearSpans()
    table.setRowCount(0)
    table.setRowCount(len(lines) + 1)
    for index, line in enumerate(lines):
        for column, key in enumerate(LINE_KEYS):
            table.setItem(index, column, table_item(cell_text(line, key, LINE_KIND), bold=key == "advance_payment"))
        table.setRowHeight(index, 32)
    totals = lines_totals(lines)
    last = len(lines)
    for column, key in enumerate(LINE_KEYS):
        text = _money(totals[key]) if key in ("works_value", "advance_payment") else ""
        item = table_item(text, bold=True)
        item.setBackground(QBrush(QColor(TOTAL_BG)))
        table.setItem(last, column, item)
    table.setSpan(last, 0, 1, 5)
    table.item(last, 0).setText(f"إجمالي المسدد — {_count_text(totals['count'])}")
    table.setRowHeight(last, 34)


def lines_table(lines: list[dict[str, Any]]) -> QTableWidget:
    table = _new_table(len(LINE_COLUMNS), [header for _key, header, _kind in LINE_COLUMNS])
    header = table.horizontalHeader()
    header.setMinimumHeight(36)
    for column, key in enumerate(LINE_KEYS):
        header.setSectionResizeMode(column, QHeaderView.Stretch if key in ("contractor_name", "project_name",
                                                                              "company_name")
                                    else QHeaderView.ResizeToContents)
    fill_lines_table(table, lines)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    table.setFixedHeight(fitted_height(table))
    return table


def fitted_height(table: QTableWidget) -> int:
    """The height that shows every row of *table* with no scrolling and no empty strip."""
    rows = sum(table.rowHeight(i) for i in range(table.rowCount()))
    return table.horizontalHeader().minimumHeight() + rows + 2 * table.frameWidth() + 2


class AdvanceBar(QWidget):
    """نموذج 7's bar: the contract's advance, one segment per extract that paid part of it.

    The unpaid rest is grey. When the extracts took back more than the advance,
    the bar spans what was taken and a red line marks the advance itself.
    """

    def __init__(self, agreed: Decimal, lines: list[dict[str, Any]]) -> None:
        super().__init__()
        self.agreed = Decimal(agreed or 0)
        self.parts = [Decimal(line["advance_payment"] or 0) for line in lines]
        self.setFixedHeight(26)

    def segments(self) -> list[tuple[float, float, str]]:
        """(start, width, colour) of each piece, as fractions of the bar, right to left."""
        paid = sum(self.parts, Decimal(0))
        whole = max(self.agreed, paid)
        if whole <= 0:
            return []
        pieces, start = [], 0.0
        for index, part in enumerate(self.parts):
            width = float(part / whole)
            pieces.append((start, width, SEGMENT_COLORS[index % len(SEGMENT_COLORS)]))
            start += width
        if self.agreed > paid:
            pieces.append((start, float((self.agreed - paid) / whole), REST_COLOR))
        return pieces

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(REST_COLOR))
        painter.drawRoundedRect(QRectF(0, 0, width, height), 6, 6)
        for start, size, color in self.segments():
            # Right to left: the first extract starts at the right edge.
            right = width - start * width
            painter.setBrush(QColor(color))
            painter.drawRect(QRectF(right - size * width + 1, 0, max(size * width - 2, 1), height))
        paid = sum(self.parts, Decimal(0))
        if paid > self.agreed > 0:
            x = width - float(self.agreed / paid) * width
            painter.setPen(QPen(QColor(RED), 3))
            painter.drawLine(int(x), -2, int(x), height + 2)
        painter.end()


class AdvanceStatementDialog(QDialog):
    """نموذج 7: كشف حساب الدفعة المقدمة of one contract."""

    def __init__(self, contract: dict[str, Any], lines: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.contract = contract
        self.lines = lines
        self.setWindowTitle(f"كشف حساب الدفعة المقدمة — {contract.get('contract_no') or ''}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("QDialog { background:#FFFFFF; } QLabel { background:transparent; }")
        self.setMinimumWidth(1180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title = QLabel(f"كشف حساب الدفعة المقدمة — {contract.get('contract_no') or ''}")
        title.setStyleSheet(f"font-size:20px; font-weight:900; color:{TEXT};")
        subtitle = QLabel(f"{contract.get('contractor_name') or ''}  ·  {contract.get('project_name') or ''}  ·  "
                          f"{contract.get('company_name') or ''}  ·  تاريخ العقد {date_text(contract.get('contract_date'))}")
        subtitle.setStyleSheet(f"font-size:13px; font-weight:700; color:{MUTED};")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        summary = QHBoxLayout()
        summary.setSpacing(10)
        rate = _rate_text(contract.get("advance_payment_pct"))
        self.summary_values: dict[str, QLabel] = {}
        for key, caption, background, color in (
            ("contract_value", "قيمة العقد", "#F8FAFC", TEXT),
            ("advance_agreed", f"قيمة الدفعة المقدمة من العقد ({rate}%)", "#F8FAFC", TEXT),
            ("advance_deducted", f"إجمالي المسدد ({_paid_pct(contract):.0f}%)", "#FEF3C7", "#92400E"),
            ("remaining_advance", "المتبقي", GREEN, "#FFFFFF"),
        ):
            box = QFrame()
            box.setObjectName(f"sum_{key}")
            box.setStyleSheet(f"QFrame#sum_{key} {{ background:{background}; border-radius:9px; }}")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(14, 8, 14, 8)
            inner.setSpacing(2)
            label = QLabel(caption)
            label.setStyleSheet(f"font-size:12px; font-weight:800; color:{'#D1FAE5' if color == '#FFFFFF' else MUTED};")
            value = QLabel(_money(contract.get(key)))
            if Decimal(contract.get(key) or 0) < 0:
                color = "#FECACA" if color == "#FFFFFF" else RED  # readable on the dark box too
            value.setStyleSheet(f"font-size:19px; font-weight:900; color:{color};")
            value.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
            inner.addWidget(label)
            inner.addWidget(value)
            self.summary_values[key] = value
            summary.addWidget(box, 1)
        layout.addLayout(summary)

        band = QFrame()
        band.setObjectName("band")
        band.setStyleSheet("QFrame#band { background:#F8FAFC; border-radius:9px; }")
        band_layout = QVBoxLayout(band)
        band_layout.setContentsMargins(14, 10, 14, 10)
        band_layout.setSpacing(7)
        line = QHBoxLayout()
        agreed_label = QLabel(f"الدفعة المقدمة من العقد  <b>{_money(contract.get('advance_agreed'))}</b>")
        paid_label = QLabel(f"تم سداد  <b>{_paid_pct(contract):.0f}%</b>")
        for label in (agreed_label, paid_label):
            label.setStyleSheet(f"font-size:13px; color:{TEXT};")
        line.addWidget(agreed_label)
        line.addStretch(1)
        line.addWidget(paid_label)
        band_layout.addLayout(line)
        self.bar = AdvanceBar(contract.get("advance_agreed"), lines)
        band_layout.addWidget(self.bar)
        self.legend = QLabel(self._legend_html())
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet(f"font-size:12.5px; color:{TEXT};")
        band_layout.addWidget(self.legend)
        layout.addWidget(band)

        if lines:
            self.table = lines_table(lines)
            if len(lines) > 12:  # a long list scrolls inside the window instead of growing it
                self.table.setMinimumHeight(200)
                self.table.setMaximumHeight(16777215)
                self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            layout.addWidget(self.table, 1 if len(lines) > 12 else 0)
        else:
            self.table = None
            empty = QLabel("لا توجد مستخلصات على هذا العقد حتى الآن.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"font-size:15px; font-weight:800; color:{MUTED}; padding:30px;")
            layout.addWidget(empty, 1)

        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = QPushButton("إغلاق")
        self.close_button.setFixedHeight(36)
        self.close_button.setStyleSheet(_button_style("#374151", "#1F2937"))
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.resize(1180, min(self.sizeHint().height(), 820))

    def _legend_html(self) -> str:
        parts = []
        for index, line in enumerate(self.lines):
            color = SEGMENT_COLORS[index % len(SEGMENT_COLORS)]
            number = str(line.get("extract_no") or "").rsplit("/", 1)[-1]
            parts.append(f"<span style='color:{color}'>■</span> {number} · {date_text(line.get('extract_date'))} · "
                         f"{_money(line.get('advance_payment'))}")
        remaining = Decimal(self.contract.get("remaining_advance") or 0)
        if remaining < 0:
            parts.append(f"<span style='color:{RED}'>▌ تجاوز الدفعة المقدمة بـ {_money(-remaining)}</span>")
        else:
            parts.append(f"<span style='color:#9CA3AF'>■</span> المتبقي · {_money(remaining)}")
        return "&nbsp;&nbsp;&nbsp;&nbsp;".join(parts)


class InlineDetail(QFrame):
    """نموذج 6: the extracts of one contract, opened under its row."""

    def __init__(self, contract: dict[str, Any], lines: list[dict[str, Any]]) -> None:
        super().__init__()
        self.setObjectName("inline")
        self.setStyleSheet("QFrame#inline { background:#FFFBF0; border:1px solid #F3E3B5; border-radius:8px; }"
                           "QLabel { background:transparent; border:none; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        title = QLabel(f"الدفعات المقدمة المسددة من مستخلصات العقد {contract.get('contract_no') or ''}")
        title.setStyleSheet(f"font-size:13px; font-weight:900; color:{TEXT};")
        layout.addWidget(title)
        if lines:
            self.table = lines_table(lines)
            layout.addWidget(self.table)
        else:
            self.table = None
            empty = QLabel("لا توجد مستخلصات على هذا العقد حتى الآن.")
            empty.setStyleSheet(f"font-size:13px; font-weight:800; color:{MUTED};")
            layout.addWidget(empty)

    def wanted_height(self) -> int:
        """Tall enough for the title and every extract, so the row needs no scrolling."""
        return self.sizeHint().height() + 4


class ContractorAdvanceReportScreen(ContractingReportBase):
    TITLE = "تقرير كشف حساب الدفعة المقدمة"
    ICON = "💳"
    PERMISSION_BASE = PERMISSION_BASE

    def __init__(self, service: ContractorAdvanceReportService | None = None,
                 parent: QWidget | None = None, settings: QSettings | None = None) -> None:
        self.settings = settings or report_settings()
        self.rows: list[dict[str, Any]] = []
        self.totals: dict[str, Any] = report_totals([])
        self.visible_columns = load_columns(self.settings, SETTINGS_KEY, COLUMN_KEYS, DEFAULT_COLUMNS)
        self.expanded: set[Any] = set()
        self.inline_kinds: list[tuple[str, Any]] = []
        self.dialog: AdvanceStatementDialog | None = None
        self._lines: dict[Any, list[dict[str, Any]]] = {}
        super().__init__(service or ContractorAdvanceReportService(), parent)

    # -- layout ------------------------------------------------------------------------

    def _build_body(self, root: QVBoxLayout) -> None:
        root.addLayout(self._build_cards())
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.chooser = ColumnChooser(COLUMN_GROUPS, HEADER, DEFAULT_COLUMNS, self.set_visible_columns)
        self.columns_button, self.columns_menu = column_button(self.chooser)
        self.columns_count = self._caption("")
        hint = self._caption("اضغط على أي عقد لعرض الدفعات المقدمة المسددة من مستخلصاته")
        self.count_label = self._caption("")
        toolbar.addWidget(self.columns_button)
        toolbar.addWidget(self.columns_count)
        toolbar.addSpacing(18)
        toolbar.addWidget(hint)
        toolbar.addStretch(1)
        toolbar.addWidget(self.count_label)
        root.addLayout(toolbar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:none; }"
            "QTabBar::tab { background:#FFFFFF; color:#334155; border:1px solid #D9E2EC; border-bottom:none; "
            "border-top-left-radius:8px; border-top-right-radius:8px; padding:9px 22px; margin-left:4px; "
            "font-size:14px; font-weight:900; }"
            f"QTabBar::tab:selected {{ background:{GREEN}; color:#FFFFFF; border-color:{GREEN}; }}"
        )
        headers = [header for _key, header, _kind in COLUMNS]
        self.popup_table = _new_table(len(COLUMNS), headers)
        self.inline_table = _new_table(len(COLUMNS) + 1, [""] + headers)
        self.popup_fitter = ColumnFitter(self.popup_table)
        self.inline_fitter = ColumnFitter(self.inline_table, fixed=(0,))  # the ＋/－ column
        self.inline_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.inline_table.setColumnWidth(0, 38)
        self.popup_table.cellClicked.connect(self._popup_clicked)
        self.inline_table.cellClicked.connect(self._inline_clicked)
        self.tabs.addTab(self._page(self.popup_table), "🪟  نافذة منبثقة (نموذج 7)")
        self.tabs.addTab(self._page(self.inline_table), "📂  تفاصيل تحت الصف (نموذج 6)")
        root.addWidget(self.tabs, 1)
        self._apply_columns()

    def _build_cards(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(10)
        self.card_values: dict[str, QLabel] = {}
        self._card_styles: dict[str, str] = {}
        for key, title in CARDS:
            dark = key == "remaining_advance"
            background, border, caption_color, value_color = (
                (GREEN, GREEN, "#D1FAE5", "#FFFFFF") if dark else ("#FFFFFF", "#E5EAF0", MUTED, TEXT))
            card = QFrame()
            card.setObjectName(f"card_{key}")
            card.setStyleSheet(
                f"QFrame#card_{key} {{ background:{background}; border:1px solid {border}; border-radius:9px; }}"
                "QLabel { background:transparent; border:none; }"
            )
            inner = QVBoxLayout(card)
            inner.setContentsMargins(14, 9, 14, 9)
            inner.setSpacing(2)
            caption = QLabel(title)
            caption.setStyleSheet(f"font-size:13px; font-weight:800; color:{caption_color};")
            value = QLabel("0.00")
            value.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
            self._card_styles[key] = f"font-size:21px; font-weight:900; color:{value_color};"
            value.setStyleSheet(self._card_styles[key])
            inner.addWidget(caption)
            inner.addWidget(value)
            self.card_values[key] = value
            layout.addWidget(card, 1)
        return layout

    @staticmethod
    def _page(table: QTableWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(table, 1)
        return page

    # -- columns -----------------------------------------------------------------------

    def set_visible_columns(self, keys: tuple[str, ...] | list[str]) -> None:
        chosen = set(keys)
        self.visible_columns = tuple(key for key in COLUMN_KEYS if key in chosen)
        save_columns(self.settings, SETTINGS_KEY, self.visible_columns)
        self._apply_columns()
        self._fill_popup_table()
        self._fill_inline_table()

    def _apply_columns(self) -> None:
        for column, key in enumerate(COLUMN_KEYS):
            hidden = key not in self.visible_columns
            self.popup_table.setColumnHidden(column, hidden)
            self.inline_table.setColumnHidden(column + 1, hidden)
        self.columns_count.setText(f"ظاهر {len(self.visible_columns)} من {len(COLUMNS)} أعمدة")
        self.chooser.sync(self.visible_columns)
        self.popup_fitter.fit()
        self.inline_fitter.fit()

    def _label_span(self) -> tuple[int, int]:
        """(first column, span) of the totals label: the visible text columns."""
        text_columns = [i for i, key in enumerate(COLUMN_KEYS) if KIND[key] == TEXT_COL]
        visible = [i for i in text_columns if COLUMN_KEYS[i] in self.visible_columns]
        if not visible:
            return -1, 0
        return visible[0], text_columns[-1] - visible[0] + 1

    # -- running -----------------------------------------------------------------------

    def run_report(self) -> None:
        self.rows = self.service.report(**self.filters())
        self.totals = report_totals(self.rows)
        self._lines.clear()
        known = {row.get("contract_id") for row in self.rows}
        self.expanded &= known
        self.count_label.setText(f"عدد العقود: {self.totals['count']}")
        for key, label in self.card_values.items():
            negative = self.totals[key] < 0
            label.setText(_money(self.totals[key]))
            # a negative total is red; on the dark card a light red stays readable
            red = "#FECACA" if key == "remaining_advance" else RED
            label.setStyleSheet(self._card_styles[key] + (f" color:{red};" if negative else ""))
        self._fill_popup_table()
        self._fill_inline_table()

    def lines_for(self, contract: dict[str, Any]) -> list[dict[str, Any]]:
        key = contract.get("contract_id")
        if key not in self._lines:
            self._lines[key] = self.service.contract_extracts(contract)
        return self._lines[key]

    def _contract_cells(self, table: QTableWidget, index: int, row: dict[str, Any], offset: int) -> None:
        for column, key in enumerate(COLUMN_KEYS):
            kind = KIND[key]
            value = row.get(key)
            item = table_item(cell_text(row, key, KIND), negative=kind == AMOUNT_COL and Decimal(value or 0) < 0,
                              bold=key in ("contractor_name", "remaining_advance"))
            item.setToolTip("اضغط لعرض الدفعات المقدمة المسددة")
            table.setItem(index, column + offset, item)

    def _totals_cells(self, table: QTableWidget, index: int, offset: int) -> None:
        first, span = self._label_span()
        for column, key in enumerate(COLUMN_KEYS):
            if KIND[key] == AMOUNT_COL:
                item = table_item(_money(self.totals[key]), bold=True, negative=self.totals[key] < 0)
            else:
                item = table_item(f"الإجمالي — {self.totals['count']} عقود" if column == first else "", bold=True)
            item.setBackground(QBrush(QColor(TOTAL_BG)))
            table.setItem(index, column + offset, item)
        if offset:
            item = table_item("")
            item.setBackground(QBrush(QColor(TOTAL_BG)))
            table.setItem(index, 0, item)
        if span > 1:
            table.setSpan(index, first + offset, 1, span)

    def _fill_popup_table(self) -> None:
        table = self.popup_table
        table.clearSpans()
        table.setRowCount(0)  # no stale cell from a longer run survives
        table.setRowCount(len(self.rows) + 1)
        for index, row in enumerate(self.rows):
            self._contract_cells(table, index, row, 0)
            table.setRowHeight(index, 38)
        self._totals_cells(table, len(self.rows), 0)
        table.setRowHeight(len(self.rows), 40)
        self.popup_fitter.fit()

    def _fill_inline_table(self) -> None:
        table = self.inline_table
        table.clearSpans()
        table.setRowCount(0)
        self.inline_kinds = []
        for row in self.rows:
            key = row.get("contract_id")
            opened = key in self.expanded
            index = table.rowCount()
            table.insertRow(index)
            self.inline_kinds.append((ROW_CONTRACT, key))
            toggle = table_item("－" if opened else "＋", bold=True)
            toggle.setTextAlignment(Qt.AlignCenter)
            toggle.setForeground(QBrush(QColor(GREEN)))
            table.setItem(index, 0, toggle)
            self._contract_cells(table, index, row, 1)
            table.setRowHeight(index, 38)
            if opened:
                for column in range(1, table.columnCount()):
                    table.item(index, column).setBackground(QBrush(QColor(SELECTED_BG)))
                detail_index = table.rowCount()
                table.insertRow(detail_index)
                self.inline_kinds.append((ROW_DETAIL, key))
                detail = InlineDetail(row, self.lines_for(row))
                table.setSpan(detail_index, 0, 1, table.columnCount())
                table.setCellWidget(detail_index, 0, detail)
                table.setRowHeight(detail_index, detail.wanted_height())
        index = table.rowCount()
        table.insertRow(index)
        self.inline_kinds.append((ROW_TOTAL, None))
        self._totals_cells(table, index, 1)
        table.setRowHeight(index, 40)
        self.inline_fitter.fit()

    # -- clicks ------------------------------------------------------------------------

    def _popup_clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.rows):
            self.open_statement(self.rows[row])

    def open_statement(self, contract: dict[str, Any]) -> AdvanceStatementDialog:
        if self.dialog is not None:
            self.dialog.close()
        self.dialog = AdvanceStatementDialog(contract, self.lines_for(contract), self)
        self.dialog.open()
        return self.dialog

    def _inline_clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.inline_kinds) and self.inline_kinds[row][0] == ROW_CONTRACT:
            self.toggle_contract(self.inline_kinds[row][1])

    def toggle_contract(self, contract_id: Any) -> None:
        self.expanded.symmetric_difference_update({contract_id})
        self._fill_inline_table()
