"""نافذة «بحث عن عقد» — شاشة عقود المقاولين (زر «بحث» أو F1).

The columns are the ones the user listed, in their order (2026-10-13): رقم
العقد، تاريخ العقد، اسم المقاول، اسم الشركة، اسم المشروع، اسم العقد.

Above the table each column has its own drop list: «الكل» plus every value in
that column, searchable by any part like the program's other drop lists. The
lists narrow the table together (AND). The caller passes the contracts
(``ContractorContractService.contracts()``) and reads :attr:`selected` back.
"""

from __future__ import annotations

import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.common.searchable_combos import enable_combo_search
from app.ui.common.theme import GREEN, _button_style

# (key in the row dict, column header).
COLUMNS = (
    ("contract_no", "رقم العقد"),
    ("contract_date", "تاريخ العقد"),
    ("contractor_name", "اسم المقاول"),
    ("company_name", "اسم الشركة"),
    ("project_name", "اسم المشروع"),
    ("contract_name", "اسم العقد"),
)
ALL = "الكل"


def cell_text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return f"{value:%Y-%m-%d}"
    return "" if value in (None, "") else str(value).strip()


class ContractorContractPickerDialog(QDialog):
    """Find one contract. ``selected`` is its row, or None when cancelled."""

    def __init__(self, contracts: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = list(contracts)
        self.visible_rows: list[dict[str, Any]] = []
        self.selected: dict[str, Any] | None = None
        self.filters: dict[str, QComboBox] = {}

        self.setWindowTitle("بحث عن عقد")
        self.resize(1150, 600)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        enable_combo_search(self)
        self.apply_filters()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for col, (key, label) in enumerate(COLUMNS):
            caption = QLabel(label)
            caption.setStyleSheet("font-size:13px; font-weight:900; color:#334155;")
            combo = QComboBox()
            combo.setMinimumHeight(36)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setStyleSheet(
                "QComboBox { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:7px; "
                "padding:4px 8px; font-size:13px; font-weight:700; }"
                f"QComboBox:focus {{ border:1px solid {GREEN}; }}"
            )
            combo.addItem(ALL, None)
            values = {cell_text(row, key) for row in self.rows} - {""}
            # Dates newest first; everything else alphabetically.
            for value in sorted(values, reverse=(key == "contract_date")):
                combo.addItem(value, value)
            combo.currentIndexChanged.connect(self.apply_filters)
            self.filters[key] = combo
            grid.addWidget(caption, 0, col)
            grid.addWidget(combo, 1, col)
            grid.setColumnStretch(col, 1)
        root.addLayout(grid)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _k, label in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        for col in (0, 1):  # the number and the date: never cut off
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; "
            "border:1px solid #E2E8F0; gridline-color:#E5E7EB; font-size:14px; }"
            f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:9px 8px; }"
            "QTableWidget::item:selected { background:#DDF3E6; color:#111827; }"
        )
        self.table.itemDoubleClicked.connect(self.accept_selected)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.choose_button = QPushButton("فتح العقد")
        self.choose_button.setFixedHeight(38)
        self.choose_button.setMinimumWidth(130)
        self.choose_button.setStyleSheet(_button_style(GREEN, "#0F6B30"))
        self.choose_button.clicked.connect(self.accept_selected)
        self.clear_button = QPushButton("مسح الفلاتر")
        self.clear_button.setFixedHeight(38)
        self.clear_button.setStyleSheet(_button_style("#64748B", "#475569"))
        self.clear_button.clicked.connect(self.clear_filters)
        cancel_button = QPushButton("إلغاء")
        cancel_button.setFixedHeight(38)
        cancel_button.setStyleSheet(_button_style("#374151", "#1F2937"))
        cancel_button.clicked.connect(self.reject)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#64748B; font-weight:700;")
        bottom.addWidget(self.choose_button)
        bottom.addWidget(self.clear_button)
        bottom.addWidget(cancel_button)
        bottom.addStretch(1)
        bottom.addWidget(self.count_label)
        root.addLayout(bottom)

    def apply_filters(self, *_args) -> None:
        wanted = {key: combo.currentData() for key, combo in self.filters.items() if combo.currentData() is not None}
        self.visible_rows = [row for row in self.rows
                             if all(cell_text(row, key) == value for key, value in wanted.items())]
        self.table.setRowCount(len(self.visible_rows))
        for row_index, row in enumerate(self.visible_rows):
            for col_index, (key, _label) in enumerate(COLUMNS):
                item = QTableWidgetItem(cell_text(row, key))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, col_index, item)
        if self.visible_rows:
            self.table.selectRow(0)
            self.table.setCurrentCell(0, 0)
        self.choose_button.setEnabled(bool(self.visible_rows))
        self.count_label.setText(f"عدد العقود: {len(self.visible_rows)}")

    def clear_filters(self) -> None:
        for combo in self.filters.values():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.apply_filters()

    def accept_selected(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_rows):
            return
        self.selected = self.visible_rows[row]
        self.accept()
