"""نافذة اختيار الجرار — قسم التوريدات.

A searchable picker over the tractor cards: اسم صاحب الجرار, رقم الوش and
رقم المقطورة in a table, with one search box that matches any of the three.

It replaces the plain combo the Access subform used, which offered nothing but
a list to scroll and no way to find a tractor by its plate — the number the
staff actually have in front of them when a load arrives.

Pure UI: the caller hands it the rows (already filtered to the tractors that
may be picked) and reads :attr:`selected` back. No database access here.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
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

# (key in the row dict, column header). Exactly the three things that identify a
# tractor on the yard.
COLUMNS = (
    ("driver_name", "اسم صاحب الجرار"),
    ("head_no", "رقم الوش"),
    ("trailer_no", "رقم المقطورة"),
)


def filter_tractors(rows: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    """Rows whose name or either plate contains *keyword* (case-insensitive).

    Plates are stored as text, so this matches partial numbers too: typing
    ``581`` finds مقطورة 3581. Kept as a module function so it is testable
    without a Qt widget.
    """
    needle = str(keyword or "").strip().casefold()
    if not needle:
        return list(rows)
    matched = []
    for row in rows:
        haystack = " ".join(
            str(row.get(key) or "") for key, _label in COLUMNS
        ).casefold()
        if needle in haystack:
            matched.append(row)
    return matched


class TawridTractorPickerDialog(QDialog):
    """Pick one tractor. ``selected`` is the chosen row dict, or None.

    A scope toggle appears when *customer_rows* and/or *crusher_rows* are given —
    «كل الجرارات» (the default), «جرارات العميل» (the tractors set up for the
    ticket's customer on the price grid) and «جرارات الكسّارة» (the tractors that
    hauled from the chosen crusher, from the تكعيب الكسّارات sheets) — so the البون
    can narrow the list either way. Without either the dialog behaves exactly as
    before (the customers screen still calls it with one list).
    """

    def __init__(
        self,
        tractors: list[dict[str, Any]],
        parent: QWidget | None = None,
        customer_rows: list[dict[str, Any]] | None = None,
        customer_name: str | None = None,
        crusher_rows: list[dict[str, Any]] | None = None,
        crusher_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._all_rows = list(tractors)
        self._customer_rows = None if customer_rows is None else list(customer_rows)
        self._customer_name = str(customer_name or "").strip()
        self._crusher_rows = None if crusher_rows is None else list(crusher_rows)
        self._crusher_name = str(crusher_name or "").strip()
        # The active source refresh_table filters; defaults to all tractors.
        self.tractors = list(self._all_rows)
        self.visible_rows: list[dict[str, Any]] = list(self.tractors)
        self.selected: dict[str, Any] | None = None

        self.setWindowTitle("اختيار جرار")
        self.resize(720, 480)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self.refresh_table()

    # -- layout ----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Scope toggle: shown when a customer's and/or a crusher's own tractors
        # were supplied. The default is «كل الجرارات» — the user asked for the
        # full list to be the starting point, with the narrowed lists one click
        # away. The customer and crusher radios each appear only when their list
        # was passed, so the customers screen (which passes neither) shows none.
        self.scope_customer = None
        self.scope_crusher = None
        if self._customer_rows is not None or self._crusher_rows is not None:
            scope = QHBoxLayout()
            scope.setSpacing(14)
            self.scope_all = QRadioButton("كل الجرارات")
            self.scope_all.setChecked(True)
            self._scope_group = QButtonGroup(self)
            self._scope_group.addButton(self.scope_all)
            self.scope_all.toggled.connect(self._on_scope_changed)
            scope.addWidget(self.scope_all)

            if self._customer_rows is not None:
                caption = (
                    f"جرارات العميل ({self._customer_name})"
                    if self._customer_name else "جرارات العميل"
                )
                self.scope_customer = QRadioButton(caption)
                self._scope_group.addButton(self.scope_customer)
                self.scope_customer.toggled.connect(self._on_scope_changed)
                scope.addWidget(self.scope_customer)

            if self._crusher_rows is not None:
                caption = (
                    f"جرارات الكسّارة ({self._crusher_name})"
                    if self._crusher_name else "جرارات الكسّارة"
                )
                self.scope_crusher = QRadioButton(caption)
                self._scope_group.addButton(self.scope_crusher)
                self.scope_crusher.toggled.connect(self._on_scope_changed)
                scope.addWidget(self.scope_crusher)

            for radio in (self.scope_all, self.scope_customer, self.scope_crusher):
                if radio is not None:
                    radio.setStyleSheet("font-size:13px; font-weight:800; color:#334155;")
            scope.addStretch(1)
            root.addLayout(scope)

        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText(
            "ابحث باسم صاحب الجرار أو رقم الوش أو رقم المقطورة"
        )
        self.search_text.setFixedHeight(40)
        self.search_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.search_text.setStyleSheet(
            "QLineEdit { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:7px; "
            "padding:6px 10px; font-size:14px; }"
            f"QLineEdit:focus {{ border:1px solid {GREEN}; }}"
        )
        # Filtering runs on every keystroke: the list is one row per tractor
        # (25 of them today), so there is nothing to debounce.
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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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

    # -- data ------------------------------------------------------------

    def _on_scope_changed(self, *_args) -> None:
        """Switch the active source between all tractors, the customer's, the crusher's."""
        if self.scope_customer is not None and self.scope_customer.isChecked():
            self.tractors = list(self._customer_rows or [])
        elif self.scope_crusher is not None and self.scope_crusher.isChecked():
            self.tractors = list(self._crusher_rows or [])
        else:
            self.tractors = list(self._all_rows)
        self.refresh_table()

    def refresh_table(self) -> None:
        self.visible_rows = filter_tractors(self.tractors, self.search_text.text())
        self.table.setRowCount(len(self.visible_rows))
        for row_index, tractor in enumerate(self.visible_rows):
            for col_index, (key, _label) in enumerate(COLUMNS):
                value = tractor.get(key)
                item = QTableWidgetItem("" if value in (None, "") else str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, col_index, item)
        if self.visible_rows:
            self.table.selectRow(0)
            self.table.setCurrentCell(0, 0)
        self.choose_button.setEnabled(bool(self.visible_rows))
        self.count_label.setText(f"عدد الجرارات: {len(self.visible_rows)}")

    def accept_selected(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_rows):
            return
        self.selected = self.visible_rows[row]
        self.accept()

    def _accept_if_unambiguous(self) -> None:
        """Enter in the search box picks the row when only one is left.

        Typing a plate and pressing Enter is the fast path this screen exists
        for. With more than one match it would be a guess, so it only moves the
        focus to the table instead.
        """
        if len(self.visible_rows) == 1:
            self.table.setCurrentCell(0, 0)
            self.accept_selected()
        elif self.visible_rows:
            self.table.setFocus()
