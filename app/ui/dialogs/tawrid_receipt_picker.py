"""نافذة «بحث عن سند» — قسم التوريدات، المرحلة السادسة (سندات قبض العملاء).

The receipt screen carries no voucher list on the form (Model 9): finding an
earlier سند is done through this dialog behind the «بحث عن سند» button, and
walking them one by one is done with الأول/السابق/التالي/الأخير — the same shape
as the البون and تكعيب الكسّارات screens.

Search is **live** against the database (there can be thousands of receipts), so
the caller passes a ``search_fn(keyword) -> rows`` — usually
``TawridCustomerReceiptService.search_receipts`` — and the dialog stays pure UI:
it reads :attr:`selected_id` back. An empty box shows the most recent receipts.
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
    ("receipt_no", "رقم السند", False),
    ("receipt_date", "التاريخ", False),
    ("customer_name", "العميل", False),
    ("amount", "المبلغ", True),
    ("statement", "البيان", False),
)


def _money(value: Any) -> str:
    try:
        amount = Decimal(str(value or 0))
    except Exception:  # noqa: BLE001 - a malformed row must not break the dialog
        return "0.00"
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


class TawridReceiptPickerDialog(QDialog):
    """Find one receipt. ``selected_id`` is its ``receipt_id``, or None.

    ``search_fn`` is called with the current keyword and must return a list of
    row dicts carrying at least the keys in :data:`COLUMNS` plus ``receipt_id``.
    """

    def __init__(
        self,
        search_fn: Callable[[str], list[dict[str, Any]]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._search_fn = search_fn
        self.visible_rows: list[dict[str, Any]] = []
        self.selected_id: Any | None = None

        self.setWindowTitle("بحث عن سند")
        self.resize(820, 540)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self._run_search()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("ابحث برقم السند أو اسم العميل أو البيان")
        self.search_text.setFixedHeight(40)
        self.search_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
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
        header.setSectionResizeMode(2, QHeaderView.Stretch)
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
        self.choose_button = QPushButton("فتح السند")
        self.choose_button.setFixedHeight(38)
        self.choose_button.setMinimumWidth(120)
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

    def _cell_text(self, row: dict[str, Any], key: str, money: bool) -> str:
        value = row.get(key)
        if money:
            return _money(value)
        if key == "receipt_date" and value is not None:
            return str(value)[:10]
        return "" if value in (None, "") else str(value)

    def _run_search(self) -> None:
        try:
            self.visible_rows = list(self._search_fn(self.search_text.text()))
        except Exception:  # noqa: BLE001 - a failed search must not crash the dialog
            self.visible_rows = []
        self.table.setRowCount(len(self.visible_rows))
        for row_index, row in enumerate(self.visible_rows):
            for col_index, (key, _label, money) in enumerate(COLUMNS):
                item = QTableWidgetItem(self._cell_text(row, key, money))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, col_index, item)
        if self.visible_rows:
            self.table.selectRow(0)
            self.table.setCurrentCell(0, 0)
        self.choose_button.setEnabled(bool(self.visible_rows))
        self.count_label.setText(f"عدد السندات: {len(self.visible_rows)}")

    def accept_selected(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_rows):
            return
        self.selected_id = self.visible_rows[row].get("receipt_id")
        self.accept()

    def _accept_if_unambiguous(self) -> None:
        # A typing pause may still be pending; run the search now so Enter acts on
        # what is on screen.
        self._timer.stop()
        self._run_search()
        if len(self.visible_rows) == 1:
            self.table.setCurrentCell(0, 0)
            self.accept_selected()
        elif self.visible_rows:
            self.table.setFocus()
