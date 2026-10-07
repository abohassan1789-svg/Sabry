"""نافذة قائمة المقاولين — opened from a count card on شاشة المقاولين.

Each card («إجمالي السجلات»، «الموردين»، «المقاولين»، «الاستشاريين»،
«الدعاية والإعلان»، «السماسرة») opens this list of the contractors behind its number. Picking
a row (double-click, «فتح», or Enter when one row is left) hands it back so the
screen can load that card.

Pure UI: the caller hands it the rows and reads :attr:`selected` back. No
database access here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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
    ("contractor_code", "الكود"),
    ("contractor_name", "اسم المقاول"),
    ("contractor_type", "النوع"),
    ("registration_no", "رقم التسجيل"),
    ("phone", "رقم التلفون"),
    ("current_balance", "الرصيد الجاري"),
)

SEARCH_KEYS = ("contractor_code", "contractor_name", "registration_no", "phone")


def filter_contractors(rows: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    """Rows whose code, name, registration number or phone contains *keyword*."""
    needle = str(keyword or "").strip().casefold()
    if not needle:
        return list(rows)
    return [
        row for row in rows
        if needle in " ".join(str(row.get(key) or "") for key in SEARCH_KEYS).casefold()
    ]


def format_money(value: Any) -> str:
    """Thousands-separated, two decimals; a negative shows as ``1,234.00-``."""
    try:
        amount = Decimal(str(value or 0))
    except Exception:  # noqa: BLE001 - a malformed row must not break the dialog
        return "0.00"
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


class ContractorListDialog(QDialog):
    """List the contractors behind one count card. ``selected`` is the picked row."""

    def __init__(self, title: str, rows: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows = list(rows)
        self.visible_rows: list[dict[str, Any]] = list(self.rows)
        self.selected: dict[str, Any] | None = None
        self.title = title

        self.setWindowTitle(title)
        self.resize(900, 520)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        heading = QLabel(self.title)
        heading.setStyleSheet(f"font-size:18px; font-weight:900; color:{GREEN};")
        root.addWidget(heading)

        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("ابحث بالكود أو الاسم أو رقم التسجيل أو التلفون")
        self.search_text.setFixedHeight(40)
        self.search_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
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
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; "
            "border:1px solid #E2E8F0; gridline-color:#E5E7EB; font-size:14px; }"
            f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:9px 12px; }"
            "QTableWidget::item:selected { background:#DDF3E6; color:#111827; }"
        )
        self.table.itemDoubleClicked.connect(self.accept_selected)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.open_button = QPushButton("فتح")
        self.open_button.setFixedHeight(38)
        self.open_button.setMinimumWidth(110)
        self.open_button.setStyleSheet(_button_style(GREEN, "#0F6B30"))
        self.open_button.clicked.connect(self.accept_selected)

        close_button = QPushButton("إغلاق")
        close_button.setFixedHeight(38)
        close_button.setStyleSheet(_button_style("#374151", "#1F2937"))
        close_button.clicked.connect(self.reject)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#64748B; font-weight:700;")

        bottom.addWidget(self.open_button)
        bottom.addWidget(close_button)
        bottom.addStretch(1)
        bottom.addWidget(self.count_label)
        root.addLayout(bottom)

    def _cell_text(self, row: dict[str, Any], key: str) -> str:
        if key == "current_balance":
            return format_money(row.get(key))
        value = row.get(key)
        return "" if value in (None, "") else str(value)

    def refresh_table(self) -> None:
        self.visible_rows = filter_contractors(self.rows, self.search_text.text())
        self.table.setRowCount(len(self.visible_rows))
        for row_index, row in enumerate(self.visible_rows):
            for col_index, (key, _label) in enumerate(COLUMNS):
                item = QTableWidgetItem(self._cell_text(row, key))
                item.setTextAlignment(Qt.AlignCenter)
                if key == "current_balance":
                    try:
                        if Decimal(str(row.get(key) or 0)) < 0:
                            item.setForeground(QColor("#B91C1C"))
                    except Exception:  # noqa: BLE001
                        pass
                self.table.setItem(row_index, col_index, item)
        if self.visible_rows:
            self.table.setCurrentCell(0, 0)
        self.open_button.setEnabled(bool(self.visible_rows))
        self.count_label.setText(f"العدد: {len(self.visible_rows)}")

    def accept_selected(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_rows):
            return
        self.selected = self.visible_rows[row]
        self.accept()

    def _accept_if_unambiguous(self) -> None:
        if len(self.visible_rows) == 1:
            self.table.setCurrentCell(0, 0)
            self.accept_selected()
        elif self.visible_rows:
            self.table.setFocus()
