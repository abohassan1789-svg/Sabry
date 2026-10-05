"""نافذة البحث عن شركة — F1 / «بحث عن شركة» on شاشة بيانات الشركة.

Lists the companies (name, tax registration number, address) with a search
box. Picking a row (double-click, «فتح», or Enter when one row is left) hands it
back in :attr:`selected`. Pure UI: the caller passes the rows in.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.common.theme import GREEN, _button_style

# (key in the row dict, column header).
COLUMNS = (
    ("company_name", "اسم الشركة"),
    ("tax_registration_no", "رقم السجل الضريبي"),
    ("address", "العنوان"),
)


def filter_companies(rows: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    """Rows whose name, tax number or address contains *keyword* (any case)."""
    needle = str(keyword or "").strip().casefold()
    if not needle:
        return list(rows)
    return [
        row for row in rows
        if needle in " ".join(str(row.get(key) or "") for key, _label in COLUMNS).casefold()
    ]


class CompanyInfoListDialog(QDialog):
    def __init__(self, rows: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = list(rows)
        self.visible_rows: list[dict[str, Any]] = list(self.rows)
        self.selected: dict[str, Any] | None = None

        self.setWindowTitle("بحث عن شركة")
        self.resize(860, 480)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        heading = QLabel(f"الشركات ({len(self.rows)})")
        heading.setStyleSheet(f"font-size:18px; font-weight:900; color:{GREEN};")
        root.addWidget(heading)

        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("ابحث بالاسم أو رقم السجل الضريبي أو العنوان")
        self.search_text.setFixedHeight(40)
        self.search_text.setStyleSheet(
            "QLineEdit { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:7px; "
            "padding:6px 10px; font-size:14px; }"
            f"QLineEdit:focus {{ border:1px solid {GREEN}; }}"
        )
        self.search_text.textChanged.connect(self.refresh_table)
        self.search_text.returnPressed.connect(self._accept_if_unambiguous)
        root.addWidget(self.search_text)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _key, label in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.Stretch)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; "
            "border:1px solid #E2E8F0; gridline-color:#E5E7EB; font-size:14px; }"
            "QHeaderView::section { background:#F1F5F9; padding:6px; border:none; font-weight:800; }"
        )
        self.table.doubleClicked.connect(lambda _index: self._accept_current())
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("فتح")
        self.open_button.setFixedHeight(38)
        self.open_button.setStyleSheet(_button_style("#2563EB", "#1D4ED8"))
        self.open_button.clicked.connect(self._accept_current)
        close_button = QPushButton("إغلاق")
        close_button.setFixedHeight(38)
        close_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        close_button.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.open_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    def refresh_table(self) -> None:
        self.visible_rows = filter_companies(self.rows, self.search_text.text())
        self.table.setRowCount(len(self.visible_rows))
        for row_index, row in enumerate(self.visible_rows):
            for column, (key, _label) in enumerate(COLUMNS):
                item = QTableWidgetItem(str(row.get(key) or ""))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column, item)
        if self.visible_rows:
            self.table.setCurrentCell(0, 0)

    def _accept_current(self) -> None:
        index = self.table.currentRow()
        if 0 <= index < len(self.visible_rows):
            self.selected = self.visible_rows[index]
            self.accept()

    def _accept_if_unambiguous(self) -> None:
        if len(self.visible_rows) == 1:
            self.table.setCurrentCell(0, 0)
            self._accept_current()
