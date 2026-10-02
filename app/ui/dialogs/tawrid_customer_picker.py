"""نافذة اختيار العميل — قسم التوريدات، المرحلة الرابعة (شاشة البون).

A searchable picker over the customer cards: مسلسل, اسم العميل and الحالة, with
one search box that matches the name or the code. It is the البون screen's way of
attaching a customer to a ticket — the same shape as the crusher picker on the
suppliers screen, so the two feel identical.

Pure UI: the caller hands it the rows and reads :attr:`selected` back. No
database access here.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.common.theme import GREEN, _button_style

# (key in the row dict, column header).
COLUMNS = (
    ("customer_code", "مسلسل"),
    ("customer_name", "اسم العميل"),
    ("is_active", "الحالة"),
)

# Only these two are searched. The status is a two-value label; matching on it
# would turn a typed digit into noise.
SEARCH_KEYS = ("customer_code", "customer_name")


def filter_customers(rows: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    """Rows whose name or مسلسل contains *keyword* (case-insensitive).

    Kept as a module function so it is testable without a Qt widget.
    """
    needle = str(keyword or "").strip().casefold()
    if not needle:
        return list(rows)
    matched = []
    for row in rows:
        haystack = " ".join(str(row.get(key) or "") for key in SEARCH_KEYS).casefold()
        if needle in haystack:
            matched.append(row)
    return matched


class TawridCustomerPickerDialog(QDialog):
    """Pick one customer. ``selected`` is the chosen row dict, or None.

    A scope toggle appears when *tractor_rows* is given — «عملاء الجرار (name)»
    (the customers set up for the chosen tractor on the price grid) and «كل
    العملاء» — so the «بون 2» flow, which picks the tractor first, opens on the
    tractor's own customers with the full list one click away. Without it the
    dialog behaves exactly as before (the البون/سندات screens pass one list).
    """

    def __init__(
        self,
        customers: list[dict[str, Any]],
        parent: QWidget | None = None,
        tractor_rows: list[dict[str, Any]] | None = None,
        tractor_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._all_rows = list(customers)
        self._tractor_rows = None if tractor_rows is None else list(tractor_rows)
        self._tractor_name = str(tractor_name or "").strip()
        # Open on the tractor's customers when they were supplied — the user asked
        # for the linked list to be the starting point.
        self.customers = list(
            self._tractor_rows if self._tractor_rows is not None else self._all_rows
        )
        self.visible_rows: list[dict[str, Any]] = list(self.customers)
        self.selected: dict[str, Any] | None = None

        self.setWindowTitle("اختيار عميل")
        self.resize(720, 500)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Scope toggle, only when the chosen tractor's customers were supplied.
        # Opens on «عملاء الجرار»; «كل العملاء» widens to the full list.
        self.scope_tractor = None
        if self._tractor_rows is not None:
            scope = QHBoxLayout()
            scope.setSpacing(14)
            caption = (
                f"عملاء الجرار ({self._tractor_name})"
                if self._tractor_name else "عملاء الجرار"
            )
            self.scope_tractor = QRadioButton(caption)
            self.scope_tractor.setChecked(True)
            self.scope_all = QRadioButton("كل العملاء")
            self._scope_group = QButtonGroup(self)
            self._scope_group.addButton(self.scope_tractor)
            self._scope_group.addButton(self.scope_all)
            self.scope_tractor.toggled.connect(self._on_scope_changed)
            self.scope_all.toggled.connect(self._on_scope_changed)
            for radio in (self.scope_tractor, self.scope_all):
                radio.setStyleSheet("font-size:13px; font-weight:800; color:#334155;")
            scope.addWidget(self.scope_tractor)
            scope.addWidget(self.scope_all)
            scope.addStretch(1)
            root.addLayout(scope)

        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("ابحث باسم العميل أو المسلسل")
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
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
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
        self.choose_button = QPushButton("اختيار")
        self.choose_button.setFixedHeight(38)
        self.choose_button.setMinimumWidth(110)
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

    def _cell_text(self, customer: dict[str, Any], key: str) -> str:
        if key == "is_active":
            return "موقوف" if customer.get(key) is False else "نشط"
        value = customer.get(key)
        return "" if value in (None, "") else str(value)

    def _on_scope_changed(self, *_args) -> None:
        """Switch between the tractor's customers and all customers."""
        if self.scope_all is not None and self.scope_all.isChecked():
            self.customers = list(self._all_rows)
        else:
            self.customers = list(self._tractor_rows or [])
        self.refresh_table()

    def refresh_table(self) -> None:
        self.visible_rows = filter_customers(self.customers, self.search_text.text())
        self.table.setRowCount(len(self.visible_rows))
        for row_index, customer in enumerate(self.visible_rows):
            stopped = customer.get("is_active") is False
            for col_index, (key, _label) in enumerate(COLUMNS):
                item = QTableWidgetItem(self._cell_text(customer, key))
                item.setTextAlignment(Qt.AlignCenter)
                if stopped:
                    item.setForeground(QColor("#94A3B8"))
                self.table.setItem(row_index, col_index, item)
        if self.visible_rows:
            self.table.selectRow(0)
            self.table.setCurrentCell(0, 0)
        self.choose_button.setEnabled(bool(self.visible_rows))
        self.count_label.setText(f"عدد العملاء: {len(self.visible_rows)}")

    def accept_selected(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_rows):
            return
        self.selected = self.visible_rows[row]
        self.accept()

    def _accept_if_unambiguous(self) -> None:
        """Enter picks the row when only one match is left, else focuses the table."""
        if len(self.visible_rows) == 1:
            self.table.setCurrentCell(0, 0)
            self.accept_selected()
        elif self.visible_rows:
            self.table.setFocus()
