"""تقرير عقود المقاولين — النموذجان 7 و5 كتبويبين (2026-09-26).

The user picked two of the ten mockups and asked for both as tabs, as with the
contracting screens, so they can choose one by using the real report:

* «مؤشرات التقدّم» (نموذج 7): the user's ten columns plus «الحالة»; the two
  remainder cells carry a bar — how much of the contract was executed, and how
  much of the advance payment the extracts already took back.
* «أعمدة مجمّعة» (نموذج 5): the columns grouped under three bands — بيانات
  العقد، القيمة والتنفيذ، الدفعة المقدمة — with «قيمة الدفعة المقدمة» added so
  the advance remainder reads as a subtraction.

Both tabs show the same filtered lines and the same totals row. Every figure
comes from ``contractor_contracts_report_service``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.contractor_contracts_report_service import (
    STATUS_DONE,
    STATUS_NOT_STARTED,
    STATUS_OVER,
    STATUS_RUNNING,
    ContractorContractsReportService,
    report_totals,
)
from app.ui.common.theme import GREEN, TEXT
from app.ui.screens.contracting_report_base import (
    MUTED,
    RED,
    TABLE_QSS as _TABLE_QSS,
    TOTAL_BG,
    ContractingReportBase,
    date_text as _date_text,
    table_item,
)
from app.ui.screens.contractor_contracts_screen import _money, _rate_text

PERMISSION_BASE = "contracting.contractor_contracts_report"
AMBER = "#B45309"
TAB_PROGRESS, TAB_BANDS = 0, 1

# نموذج 7: the user's columns in their order, then «الحالة».
PROGRESS_HEADERS = (
    "تاريخ العقد", "اسم الشركة", "اسم المشروع", "اسم المقاول", "قيمة العقد", "نسبة الدفعة\nالمقدمة",
    "إجمالي\nالمستخلصات", "إجمالي المقدمة\nالمستقطعة", "المتبقي من\nقيمة العقد", "المتبقي من\nالدفعة المقدمة",
    "الحالة",
)
P_REMAINING_VALUE, P_REMAINING_ADVANCE, P_STATUS = 8, 9, 10

# نموذج 5: (band title, band colours, its columns as (header, row key)).
BANDS: tuple[tuple[str, tuple[str, str, str], tuple[tuple[str, str], ...]], ...] = (
    ("بيانات العقد", ("#E2E8F0", "#1E293B", "#FFFFFF"), (
        ("تاريخ العقد", "contract_date"), ("اسم الشركة", "company_name"),
        ("اسم المشروع", "project_name"), ("اسم المقاول", "contractor_name"))),
    ("القيمة والتنفيذ", ("#DCFCE7", "#166534", "#F6FDF8"), (
        ("قيمة العقد", "contract_value"), ("إجمالي\nالمستخلصات", "extracts_total"),
        ("المتبقي من\nقيمة العقد", "remaining_value"))),
    ("الدفعة المقدمة", ("#FEF3C7", "#92400E", "#FFFBF0"), (
        ("نسبة الدفعة\nالمقدمة", "advance_payment_pct"), ("قيمة الدفعة\nالمقدمة", "advance_agreed"),
        ("المقدمة\nالمستقطعة", "advance_deducted"), ("المتبقي من\nالدفعة المقدمة", "remaining_advance"))),
)
BAND_KEYS = tuple(key for _title, _colors, columns in BANDS for _header, key in columns)
NAME_KEYS = ("company_name", "project_name", "contractor_name")

# «الحالة»: (text colour, background).
STATUS_COLORS = {
    STATUS_RUNNING: ("#0369A1", "#E0F2FE"),
    STATUS_DONE: ("#166534", "#DCFCE7"),
    STATUS_NOT_STARTED: ("#475569", "#F1F5F9"),
    STATUS_OVER: (RED, "#FEE2E2"),
}


def _pct_text(value: Any) -> str:
    return f"{_rate_text(value)}%"


def _whole_pct(value: Decimal) -> int:
    return int(Decimal(value).quantize(Decimal(1)))


def cell_text(row: dict[str, Any], key: str) -> str:
    """How a report value is written in a cell (money, rate or text)."""
    value = row.get(key)
    if key == "contract_date":
        return _date_text(value)
    if key == "advance_payment_pct":
        return _pct_text(value)
    if key in NAME_KEYS:
        return str(value or "")
    return _money(value)


class ProgressCell(QWidget):
    """A remainder cell of نموذج 7: caption + amount on one line, a thin bar under it."""

    def __init__(self, caption: str, amount: Decimal, percent: Decimal, color: str, bold: bool = False) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 5)
        layout.setSpacing(3)
        line = QHBoxLayout()
        line.setSpacing(6)
        self.caption = QLabel(caption)
        self.caption.setStyleSheet(f"font-size:11px; font-weight:700; color:{MUTED}; background:transparent;")
        self.value_label = QLabel(_money(amount))
        self.value_label.setStyleSheet(
            f"font-size:{14 if bold else 13}px; font-weight:900; background:transparent; "
            f"color:{RED if amount < 0 else TEXT};"
        )
        line.addWidget(self.caption)
        line.addStretch(1)
        line.addWidget(self.value_label)
        layout.addLayout(line)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(max(0, min(_whole_pct(percent), 100)))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(
            "QProgressBar { background:#E5E7EB; border:none; border-radius:3px; }"
            f"QProgressBar::chunk {{ background:{RED if percent > 100 else color}; border-radius:3px; }}"
        )
        layout.addWidget(self.bar)


class BandHeader(QWidget):
    """The band titles above نموذج 5's table, each placed exactly over its columns.

    The titles have no layout: each one is moved onto the screen span of its
    columns, so they follow resizing and right-to-left order, and this strip
    never asks for width of its own (a width it asked for used to widen the
    page, stretch the columns and push the report sideways on every run).
    """

    def __init__(self, table: QTableWidget) -> None:
        super().__init__()
        self.table = table
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.labels: list[QLabel] = []
        for title, (background, color, _tint), _columns in BANDS:
            label = QLabel(title, self)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                f"background:{background}; color:{color}; font-size:14px; font-weight:900; "
                "border-left:2px solid #FFFFFF; border-top-left-radius:6px; border-top-right-radius:6px;"
            )
            self.labels.append(label)
        header = table.horizontalHeader()
        header.sectionResized.connect(lambda *_: self.sync())
        header.geometriesChanged.connect(self.sync)
        table.horizontalScrollBar().valueChanged.connect(lambda *_: self.sync())

    def band_spans(self) -> list[tuple[int, int]]:
        """(x, width) of each band in this widget's coordinates."""
        header = self.table.horizontalHeader()
        viewport = header.viewport()
        spans, start = [], 0
        for _title, _colors, columns in BANDS:
            sections = range(start, start + len(columns))
            left = min(header.sectionViewportPosition(i) for i in sections)
            right = max(header.sectionViewportPosition(i) + header.sectionSize(i) for i in sections)
            x = self.mapFromGlobal(viewport.mapToGlobal(QPoint(left, 0))).x()
            spans.append((x, right - left))
            start += len(columns)
        return spans

    def sync(self) -> None:
        for label, (x, width) in zip(self.labels, self.band_spans()):
            label.setGeometry(x, 0, width, self.height())

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self.sync()


class ContractorContractsReportScreen(ContractingReportBase):
    TITLE = "تقرير عقود المقاولين"
    ICON = "📈"
    PERMISSION_BASE = PERMISSION_BASE

    def __init__(self, service: ContractorContractsReportService | None = None,
                 parent: QWidget | None = None) -> None:
        self.rows: list[dict[str, Any]] = []
        self.totals: dict[str, Any] = report_totals([])
        super().__init__(service or ContractorContractsReportService(), parent)

    # -- layout ------------------------------------------------------------------

    def _build_body(self, root: QVBoxLayout) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:none; }"
            "QTabBar::tab { background:#FFFFFF; color:#334155; border:1px solid #D9E2EC; border-bottom:none; "
            "border-top-left-radius:8px; border-top-right-radius:8px; padding:9px 22px; margin-left:4px; "
            "font-size:14px; font-weight:900; }"
            f"QTabBar::tab:selected {{ background:{GREEN}; color:#FFFFFF; border-color:{GREEN}; }}"
        )
        self.tabs.addTab(self._build_progress_tab(), "📊  مؤشرات التقدّم (نموذج 7)")
        self.tabs.addTab(self._build_bands_tab(), "📋  أعمدة مجمّعة (نموذج 5)")
        root.addWidget(self.tabs, 1)

    def _new_table(self, headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet(_TABLE_QSS)
        header = table.horizontalHeader()
        header.setMinimumHeight(46)
        header.setDefaultAlignment(Qt.AlignCenter)
        for column in range(len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        return table

    def _build_progress_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)
        self.progress_table = self._new_table(PROGRESS_HEADERS)
        header = self.progress_table.horizontalHeader()
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        for column in (P_REMAINING_VALUE, P_REMAINING_ADVANCE):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.progress_table.setColumnWidth(column, 200)
        layout.addWidget(self.progress_table, 1)
        self.progress_count = self._caption("")
        layout.addWidget(self.progress_count)
        return page

    def _build_bands_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)
        headers = tuple(text for _title, _colors, columns in BANDS for text, _key in columns)
        self.band_table = self._new_table(headers)
        for column, key in enumerate(BAND_KEYS):
            if key in NAME_KEYS:
                self.band_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.band_header = BandHeader(self.band_table)
        layout.addWidget(self.band_header)
        layout.addWidget(self.band_table, 1)
        layout.addSpacing(6)
        self.bands_count = self._caption("")
        layout.addWidget(self.bands_count)
        return page

    # -- running -------------------------------------------------------------------

    def run_report(self) -> None:
        self.rows = self.service.report(**self.filters())
        self.totals = report_totals(self.rows)
        self._fill_progress()
        self._fill_bands()
        text = f"عدد العقود: {self.totals['count']}"
        self.progress_count.setText(text)
        self.bands_count.setText(text)

    _item = staticmethod(table_item)

    def _total_row(self, table: QTableWidget, row: int, label_span: int) -> None:
        table.setSpan(row, 0, 1, label_span)
        table.setItem(row, 0, self._item(f"الإجمالي — {self.totals['count']} عقود", bold=True))
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is None:
                item = self._item("")
                table.setItem(row, column, item)
            item.setBackground(QBrush(QColor(TOTAL_BG)))

    def _fill_progress(self) -> None:
        table = self.progress_table
        table.clearSpans()
        table.setRowCount(0)  # drops the last run's items and bars, so no stale cell survives
        table.setRowCount(len(self.rows) + 1)
        for index, row in enumerate(self.rows):
            for column, key in enumerate(("contract_date", "company_name", "project_name", "contractor_name",
                                          "contract_value", "advance_payment_pct", "extracts_total",
                                          "advance_deducted")):
                table.setItem(index, column, self._item(cell_text(row, key), bold=key == "contractor_name"))
            self._progress_cells(index, row, bold=False)
            text_color, background = STATUS_COLORS[row["status"]]
            status = self._item(row["status"], bold=True)
            status.setForeground(QBrush(QColor(text_color)))
            status.setBackground(QBrush(QColor(background)))
            table.setItem(index, P_STATUS, status)
            table.setRowHeight(index, 46)
        last = len(self.rows)
        for column, key in ((4, "contract_value"), (6, "extracts_total"), (7, "advance_deducted")):
            table.setItem(last, column, self._item(_money(self.totals[key]), bold=True,
                                                   negative=self.totals[key] < 0))
        self._progress_cells(last, self.totals, bold=True)
        self._total_row(table, last, 4)
        table.setRowHeight(last, 48)

    def _progress_cells(self, index: int, row: dict[str, Any], bold: bool) -> None:
        for column, key, caption, percent_key, color in (
            (P_REMAINING_VALUE, "remaining_value", "نُفّذ", "executed_pct", GREEN),
            (P_REMAINING_ADVANCE, "remaining_advance", "استُرد", "recovered_pct", AMBER),
        ):
            percent = row[percent_key]
            self.progress_table.setItem(index, column, self._item(""))
            self.progress_table.setCellWidget(
                index, column, ProgressCell(f"{caption} {_whole_pct(percent)}%", row[key], percent, color, bold)
            )

    def _fill_bands(self) -> None:
        table = self.band_table
        table.clearSpans()
        table.setRowCount(0)  # drops the last run's items and bars, so no stale cell survives
        table.setRowCount(len(self.rows) + 1)
        tints = [tint for _title, (_bg, _fg, tint), columns in BANDS for _column in columns]
        for index, row in enumerate(self.rows):
            for column, key in enumerate(BAND_KEYS):
                numeric = key not in NAME_KEYS and key != "contract_date"
                value = row.get(key)
                item = self._item(cell_text(row, key), negative=numeric and isinstance(value, Decimal) and value < 0,
                                  bold=key in ("contractor_name", "remaining_value", "remaining_advance"))
                item.setBackground(QBrush(QColor(tints[column])))
                table.setItem(index, column, item)
            table.setRowHeight(index, 38)
        last = len(self.rows)
        for column, key in enumerate(BAND_KEYS):
            if key in self.totals:
                table.setItem(last, column, self._item(_money(self.totals[key]), bold=True,
                                                       negative=self.totals[key] < 0))
        self._total_row(table, last, 4)
        table.setRowHeight(last, 42)
        self.band_header.sync()
        QTimer.singleShot(0, self.band_header.sync)  # after the columns settle
