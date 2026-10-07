"""تقرير ضرائب الخصم — نموذج 7 «شريط ملخص داكن» (picked 2026-10-07).

* A dark band on top: the title, then the figures — إجمالي المستخلص، صافي الأعمال،
  رصيد أول المدة + ضرائب الخصم على المستخلصات = صافي ضرائب الخصم.
* The usual filter bar (كل الفترات، من/إلى، الشركة، المشروع، المقاول).
* «تحديد أعمدة الجدول» and «التفاف النص» over the table; both are kept per user.
  With التفاف النص on, the visible columns share the width equally and a long
  name wraps onto more lines instead of widening its column.
* One row per approved extract, then a dark totals row.

Every figure comes from ``contractor_withholding_report_service``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.contractor_withholding_report_service import (
    ContractorWithholdingReportService,
    empty_report,
)
from app.ui.common.theme import GREEN
from app.ui.screens.contracting_report_base import (
    ColumnChooser,
    ColumnFitter,
    ContractingReportBase,
    column_button,
    date_text,
    load_columns,
    load_flag,
    report_settings,
    save_columns,
    save_flag,
    share_widths,
    table_item,
)
from app.ui.screens.contractor_contracts_screen import _money, _rate_text

PERMISSION_BASE = "contracting.contractor_withholding_report"
COLUMNS_KEY = "contractor_withholding_report/columns"
WRAP_KEY = "contractor_withholding_report/wrap"

TEXT_COL, RATE_COL, AMOUNT_COL = "text", "rate", "amount"
# The user's 9 columns in their order: (row key, header, kind).
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("extract_date", "التاريخ", TEXT_COL),
    ("contractor_name", "اسم المقاول", TEXT_COL),
    ("project_name", "اسم المشروع", TEXT_COL),
    ("company_name", "اسم الشركة", TEXT_COL),
    ("works_value", "إجمالي\nالمستخلص", AMOUNT_COL),
    ("vat_pct", "نسبة\nالضريبة", RATE_COL),
    ("before_tax", "صافي\nالأعمال", AMOUNT_COL),
    ("withholding_tax_pct", "نسبة ضرائب\nالخصم", RATE_COL),
    ("withholding_tax", "قيمة ضرائب\nالخصم", AMOUNT_COL),
)
COLUMN_KEYS = tuple(key for key, _header, _kind in COLUMNS)
KIND = {key: kind for key, _header, kind in COLUMNS}
HEADER = {key: header.replace("\n", " ") for key, header, _kind in COLUMNS}
DEFAULT_COLUMNS = COLUMN_KEYS
COLUMN_GROUPS = (
    ("بيانات المستخلص", COLUMN_KEYS[:4]),
    ("المبالغ", COLUMN_KEYS[4:7]),
    ("ضرائب الخصم", COLUMN_KEYS[7:]),
)

# The band's figures, right to left: (key, caption, the sign before it).
FIGURES = (
    ("works_value", "إجمالي المستخلص", ""),
    ("before_tax", "صافي الأعمال", ""),
    ("opening", "رصيد أول المدة", ""),
    ("withholding_tax", "ضرائب الخصم على المستخلصات", "+"),
    ("net", "صافي ضرائب الخصم", "="),
)

BAND = "#14532D"
BAND_CAPTION = "#BBF7D0"
BAND_HINT = "#86EFAC"
NET_TEXT = "#881337"
WITHHOLDING_TEXT = "#9F1239"
TOTAL_TEXT_ROSE = "#FECDD3"
ROW_HEIGHT, TOTAL_HEIGHT = 32, 36

TABLE_QSS = (
    "QTableWidget { border:1px solid #E5EAF0; font-size:13px; font-weight:700; gridline-color:#E5E7EB; "
    "background:#FFFFFF; }"
    f"QHeaderView::section {{ background:#F8FAFC; color:{BAND}; font-weight:900; padding:6px; border:none; "
    f"border-bottom:2px solid {GREEN}; border-left:1px solid #E5EAF0; }}"
    "QTableWidget::item:selected { background:#FEF3C7; color:#111827; }"
)


def cell_text(row: dict[str, Any], key: str) -> str:
    kind = KIND[key]
    if key == "extract_date":
        return date_text(row.get(key))
    if kind == RATE_COL:
        return f"{_rate_text(row.get(key))}%"
    if kind == AMOUNT_COL:
        return _money(row.get(key))
    return str(row.get(key) or "")


class WrapFitter(ColumnFitter):
    """``ColumnFitter``, plus «التفاف النص»: when *wrap* is on the visible columns share the
    width by their headers alone (a long name wraps instead of widening its column) and
    every row grows to its text."""

    wrap = False

    def fit(self) -> None:
        table, header = self.table, self.table.horizontalHeader()
        if self.wrap:
            columns = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
            needs = [header.sectionSizeHint(c) + self.PADDING for c in columns]
            for column, width in zip(columns, share_widths(needs, table.viewport().width())):
                header.resizeSection(column, width)
            table.resizeRowsToContents()
        else:
            super().fit()
        last = table.rowCount() - 1
        for row in range(table.rowCount()):
            floor = TOTAL_HEIGHT if row == last else ROW_HEIGHT
            if not self.wrap or table.rowHeight(row) < floor:
                table.setRowHeight(row, floor)


class ContractorWithholdingReportScreen(ContractingReportBase):
    TITLE = "تقرير ضرائب الخصم"
    ICON = "🧾"
    PERMISSION_BASE = PERMISSION_BASE

    def __init__(self, service: ContractorWithholdingReportService | None = None,
                 parent: QWidget | None = None, settings: QSettings | None = None) -> None:
        self.settings = settings or report_settings()
        self.data: dict[str, Any] = empty_report()
        self.visible_columns = load_columns(self.settings, COLUMNS_KEY, COLUMN_KEYS, DEFAULT_COLUMNS)
        self.wrap = load_flag(self.settings, WRAP_KEY)
        super().__init__(service or ContractorWithholdingReportService(), parent)

    # -- the dark band -------------------------------------------------------------------

    def _build_header(self) -> QFrame:
        top = super()._build_header()  # icon, title, user and clock
        top.setStyleSheet("QFrame { background:transparent; } QLabel { background:transparent; color:#FFFFFF; }")
        top.layout().setContentsMargins(0, 0, 0, 0)
        band = QFrame()
        band.setObjectName("withholding_band")
        band.setStyleSheet(f"QFrame#withholding_band {{ background:{BAND}; border-radius:8px; }}"
                           "QLabel { background:transparent; }")
        layout = QVBoxLayout(band)
        layout.setContentsMargins(18, 10, 18, 12)
        layout.setSpacing(10)
        layout.addWidget(top)
        layout.addLayout(self._build_figures())
        return band

    def _build_figures(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(0)
        self.figure_values: dict[str, QLabel] = {}
        self.figure_hints: dict[str, QLabel] = {}
        for index, (key, caption, sign) in enumerate(FIGURES):
            if sign:
                mark = QLabel(sign)
                mark.setStyleSheet(f"color:{BAND_HINT}; font-size:24px; font-weight:900; padding:0 10px;")
                layout.addWidget(mark)
            net = key == "net"
            box = QFrame()
            box.setObjectName(f"figure_{key}")
            # A thin line between the first figures; the sum's terms stand on their own.
            line = "border-left:1px solid rgba(255,255,255,0.18);" if index < 2 else ""
            box.setStyleSheet(f"QFrame#figure_{key} {{ background:#FFFFFF; border-radius:8px; }}" if net
                              else f"QFrame#figure_{key} {{ background:transparent; {line} }}")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(16, 4, 16, 4)
            inner.setSpacing(0)
            name = QLabel(caption)
            name.setStyleSheet(f"font-size:12px; font-weight:800; color:{WITHHOLDING_TEXT if net else BAND_CAPTION};")
            value = QLabel("0.00")
            value.setAlignment(Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)
            value.setStyleSheet(f"font-size:22px; font-weight:900; color:{NET_TEXT if net else '#FFFFFF'};")
            hint = QLabel("")
            hint.setStyleSheet(f"font-size:11px; font-weight:700; color:{WITHHOLDING_TEXT if net else BAND_HINT};")
            for label in (name, value, hint):
                inner.addWidget(label)
            layout.addWidget(box, 1)
            self.figure_values[key] = value
            self.figure_hints[key] = hint
        return layout

    # -- the table ---------------------------------------------------------------------

    def _build_body(self, root: QVBoxLayout) -> None:
        root.addLayout(self._build_toolbar())
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("withholding_table")
        self.table.setHorizontalHeaderLabels([header for _key, header, _kind in COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(TABLE_QSS)
        header = self.table.horizontalHeader()
        header.setMinimumHeight(46)
        header.setDefaultAlignment(Qt.AlignCenter)
        self.fitter = WrapFitter(self.table)
        root.addWidget(self.table, 1)
        self._apply_wrap()
        self._apply_columns()

    def _build_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        self.chooser = ColumnChooser(COLUMN_GROUPS, HEADER, DEFAULT_COLUMNS, self.set_visible_columns)
        self.columns_button, self.columns_menu = column_button(self.chooser)
        self.wrap_button = QPushButton()
        self.wrap_button.setCheckable(True)
        self.wrap_button.setFixedHeight(36)
        self.wrap_button.setStyleSheet(
            f"QPushButton {{ background:#FFFFFF; color:{GREEN}; border:1px solid {GREEN}; border-radius:7px; "
            "padding:0 14px; font-size:13px; font-weight:900; }"
            "QPushButton:hover { background:#F0FDF4; }"
            f"QPushButton:checked {{ background:#DCFCE7; color:{BAND}; border:2px solid {GREEN}; }}"
        )
        self.wrap_button.toggled.connect(self.set_wrap)
        self.columns_count = self._caption("")
        self.count_label = self._caption("")
        layout.addWidget(self.columns_button)
        layout.addWidget(self.wrap_button)
        layout.addWidget(self.columns_count)
        layout.addStretch(1)
        layout.addWidget(self.count_label)
        return layout

    # -- columns and wrapping -------------------------------------------------------------

    def set_visible_columns(self, keys: tuple[str, ...] | list[str]) -> None:
        chosen = set(keys)
        self.visible_columns = tuple(key for key in COLUMN_KEYS if key in chosen)
        save_columns(self.settings, COLUMNS_KEY, self.visible_columns)
        self._apply_columns()
        self._fill_table()  # the totals label sits on the first visible column

    def _apply_columns(self) -> None:
        shown = set(self.visible_columns)
        for column, key in enumerate(COLUMN_KEYS):
            self.table.setColumnHidden(column, key not in shown)
        self.chooser.sync(self.visible_columns)
        self.columns_count.setText(f"{len(self.visible_columns)} من {len(COLUMN_KEYS)} أعمدة")
        self.fitter.fit()

    def set_wrap(self, on: bool) -> None:
        self.wrap = bool(on)
        save_flag(self.settings, WRAP_KEY, self.wrap)
        self._apply_wrap()

    def _apply_wrap(self) -> None:
        self.wrap_button.blockSignals(True)
        self.wrap_button.setChecked(self.wrap)
        self.wrap_button.blockSignals(False)
        self.wrap_button.setText(f"  التفاف النص: {'مفعّل' if self.wrap else 'متوقف'}  ")
        self.table.setWordWrap(self.wrap)
        self.table.setTextElideMode(Qt.ElideNone if self.wrap else Qt.ElideRight)
        self.fitter.wrap = self.wrap
        self.fitter.fit()

    # -- running -----------------------------------------------------------------------

    def run_report(self) -> None:
        filters = self.filters()
        self.data = self.service.withholding_report(**filters)
        totals = self.data["totals"]
        values = {"works_value": totals["works_value"], "before_tax": totals["before_tax"],
                  "opening": self.data["opening"], "withholding_tax": totals["withholding_tax"],
                  "net": self.data["net"]}
        for key, value in values.items():
            self.figure_values[key].setText(_money(value))
        cards = "بطاقات كل المقاولين" if filters["contractor_id"] is None else "بطاقة المقاول"
        date_from = filters["date_from"]
        self.figure_hints["works_value"].setText(f"{totals['count']} مستخلصات")
        self.figure_hints["before_tax"].setText("قبل ضريبة القيمة المضافة")
        self.figure_hints["opening"].setText(
            f"{cards} + مستخلصات قبل {date_text(date_from)}" if date_from else f"من {cards}")
        self.figure_hints["withholding_tax"].setText(
            f"من {date_text(date_from)} إلى {date_text(filters['date_to'])}" if date_from else "كل الفترات")
        self.figure_hints["net"].setText("رصيد أول المدة + ضرائب الخصم على المستخلصات")
        who = "كل المقاولين — " if filters["contractor_id"] is None else ""
        self.count_label.setText(f"{who}{totals['count']} مستخلصات")
        self._fill_table()

    def _fill_table(self) -> None:
        table = self.table
        rows = self.data["rows"]
        table.setRowCount(0)  # no stale cell from a longer run survives
        table.setRowCount(len(rows) + 1)
        for index, row in enumerate(rows):
            for column, key in enumerate(COLUMN_KEYS):
                withholding = key == "withholding_tax"
                item = table_item(cell_text(row, key), bold=withholding)
                if withholding:
                    item.setForeground(QBrush(QColor(WITHHOLDING_TEXT)))
                table.setItem(index, column, item)
        totals = self.data["totals"]
        first = next((key for key in COLUMN_KEYS if key in self.visible_columns and KIND[key] != AMOUNT_COL), None)
        for column, key in enumerate(COLUMN_KEYS):
            if KIND[key] == AMOUNT_COL:
                text = _money(totals[key])
            else:
                text = f"الإجمالي — {totals['count']} مستخلصات" if key == first else ""
            item = table_item(text, bold=True)
            item.setBackground(QBrush(QColor(BAND)))
            item.setForeground(QBrush(QColor(TOTAL_TEXT_ROSE if key == "withholding_tax" else "#FFFFFF")))
            table.setItem(len(rows), column, item)
        self.fitter.fit()
