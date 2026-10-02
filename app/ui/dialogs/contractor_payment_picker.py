"""نافذة «بحث عن دفعة» — شاشة دفعات المقاولين (زر «بحث» أو F1).

The columns follow the screen's fields, in the user's order: التاريخ، اسم
المقاول، اسم الشركة، اسم المشروع، رقم المستخلص، المبلغ، ملاحظات.

Search is live against the database: the caller passes
``search_fn(keyword) -> rows`` (``ContractorPaymentService.search_payments``)
and reads :attr:`selected` back — the chosen row, with its ``payment_id`` and
the ids of its contractor / company / project / extract.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
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

# (key in the row dict, column header, is it a money column).
COLUMNS = (
    ("payment_date", "التاريخ", False),
    ("contractor_name", "اسم المقاول", False),
    ("company_name", "اسم الشركة", False),
    ("project_name", "اسم المشروع", False),
    ("extract_no", "رقم المستخلص", False),
    ("amount", "المبلغ", True),
    ("notes", "ملاحظات", False),
)


def _money(value: Any) -> str:
    try:
        return f"{Decimal(str(value or 0)):,.2f}"
    except Exception:  # noqa: BLE001 - a malformed row must not break the dialog
        return "0.00"


class ContractorPaymentPickerDialog(QDialog):
    """Find one payment. ``selected`` is its row, or None when cancelled."""

    def __init__(self, search_fn: Callable[[str], list[dict[str, Any]]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._search_fn = search_fn
        self.visible_rows: list[dict[str, Any]] = []
        self.selected: dict[str, Any] | None = None

        self.setWindowTitle("بحث عن دفعة")
        self.resize(1100, 580)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self._run_search()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText(
            "ابحث باسم المقاول أو الشركة أو المشروع أو رقم المستخلص أو المبلغ أو الملاحظات أو التاريخ"
        )
        self.search_text.setFixedHeight(40)
        self.search_text.setAlignment(Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)  # starts at the right
        self.search_text.setStyleSheet(
            "QLineEdit { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:7px; "
            "padding:6px 10px; font-size:14px; }"
            f"QLineEdit:focus {{ border:1px solid {GREEN}; }}"
        )
        # Debounced: the search hits the database, so wait for a typing pause.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._run_search)
        self.search_text.textChanged.connect(self._timer.start)
        self.search_text.returnPressed.connect(self._accept_if_unambiguous)
        root.addWidget(self.search_text)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _k, label, _m in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        for col in (0, 4, 5):  # the date and numbers: never cut off
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
        self.choose_button = QPushButton("فتح الدفعة")
        self.choose_button.setFixedHeight(38)
        self.choose_button.setMinimumWidth(130)
        self.choose_button.setStyleSheet(_button_style(GREEN, "#0F6B30"))
        self.choose_button.clicked.connect(self.accept_selected)
        cancel_button = QPushButton("إلغاء")
        cancel_button.setFixedHeight(38)
        cancel_button.setStyleSheet(_button_style("#374151", "#1F2937"))
        cancel_button.clicked.connect(self.reject)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#64748B; font-weight:700;")
        bottom.addWidget(self.choose_button)
        bottom.addWidget(cancel_button)
        bottom.addStretch(1)
        bottom.addWidget(self.count_label)
        root.addLayout(bottom)

    def _run_search(self) -> None:
        try:
            self.visible_rows = list(self._search_fn(self.search_text.text()))
        except Exception:  # noqa: BLE001 - a failed search must not crash the dialog
            self.visible_rows = []
        self.table.setRowCount(len(self.visible_rows))
        for row_index, row in enumerate(self.visible_rows):
            for col_index, (key, _label, money) in enumerate(COLUMNS):
                value = row.get(key)
                text = _money(value) if money else ("" if value in (None, "") else str(value))
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, col_index, item)
        if self.visible_rows:
            self.table.selectRow(0)
            self.table.setCurrentCell(0, 0)
        self.choose_button.setEnabled(bool(self.visible_rows))
        self.count_label.setText(f"عدد الدفعات: {len(self.visible_rows)}")

    def accept_selected(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_rows):
            return
        self.selected = self.visible_rows[row]
        self.accept()

    def _accept_if_unambiguous(self) -> None:
        # A typing pause may still be pending; search now so Enter acts on what is shown.
        self._timer.stop()
        self._run_search()
        if len(self.visible_rows) == 1:
            self.table.setCurrentCell(0, 0)
            self.accept_selected()
        elif self.visible_rows:
            self.table.setFocus()
