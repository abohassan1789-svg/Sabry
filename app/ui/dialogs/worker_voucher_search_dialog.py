"""Worker payment voucher search popup (بحث سندات صرف العمال).

A modal RTL dialog that lists worker payment vouchers with an optional filter by
a date range and by worker (a dropdown of the registered workers). With no date
filter it shows only the latest 500 rows; ticking "تصفية بالتاريخ" filters
between the two dates and shows every match. Selecting a row (double-click,
Enter, or the Select button) returns its ``selected_id`` so the caller can load
it into the form. The dialog is pure UI — all SQL lives in
:meth:`ReviewDataService.search_worker_vouchers`. Mirrors SupplierVoucherSearchDialog.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService
from app.ui.common.theme import GREEN, _button_style

_COLUMNS: tuple[tuple[str, str], ...] = (
    ("voucher_number", "رقم السند"),
    ("voucher_date", "التاريخ"),
    ("worker_name", "اسم العامل"),
    ("amount", "المبلغ"),
    ("description", "البيان"),
)
DEFAULT_LIMIT = 500


class WorkerVoucherSearchDialog(QDialog):
    """Searchable, RTL worker-voucher picker (filter by date range + worker)."""

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.selected_id: Any | None = None
        self._columns_sized = False
        self._row_records: list[dict[str, Any]] = []

        self.setWindowTitle("بحث سندات صرف العمال")
        self.resize(1000, 600)
        self.setMinimumSize(700, 420)
        self.setLayoutDirection(Qt.RightToLeft)

        self._build_ui()
        self.refresh_table()

    # -- UI -----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        filters = QHBoxLayout()
        filters.setSpacing(8)

        self.enable_dates = QCheckBox("تصفية بالتاريخ")
        self.enable_dates.setStyleSheet("font-weight:900;")
        self.enable_dates.toggled.connect(self._on_enable_dates)

        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for edit in (self.date_from, self.date_to):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setEnabled(False)
            edit.setFixedHeight(36)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_to.setDate(QDate.currentDate())

        self.worker_combo = QComboBox()
        self.worker_combo.setFixedHeight(36)
        self.worker_combo.setMinimumWidth(180)
        self._reload_workers()

        search_button = QPushButton("بحث")
        search_button.setFixedHeight(36)
        search_button.setStyleSheet(_button_style(GREEN, "#166534"))
        search_button.clicked.connect(self.refresh_table)

        filters.addWidget(self.enable_dates)
        filters.addWidget(QLabel("من"))
        filters.addWidget(self.date_from)
        filters.addWidget(QLabel("إلى"))
        filters.addWidget(self.date_to)
        filters.addWidget(QLabel("العامل"))
        filters.addWidget(self.worker_combo)
        filters.addWidget(search_button)
        filters.addStretch(1)
        root.addLayout(filters)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _c, label in _COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; "
            "border:1px solid #E2E8F0; gridline-color:#E5E7EB; font-size:13px; }"
            f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:9px 8px; }"
            "QTableWidget::item:selected { background:#DDF3E6; color:#111827; }"
        )
        self.table.cellDoubleClicked.connect(self._accept_row)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#64748B; font-weight:700;")
        select_button = QPushButton("اختيار")
        select_button.setFixedHeight(36)
        select_button.setStyleSheet(_button_style(GREEN, "#166534"))
        select_button.clicked.connect(self.accept_selected)
        close_button = QPushButton("إغلاق")
        close_button.setFixedHeight(36)
        close_button.setStyleSheet(_button_style("#374151", "#1F2937"))
        close_button.clicked.connect(self.reject)
        bottom.addWidget(close_button)
        bottom.addWidget(select_button)
        bottom.addStretch(1)
        bottom.addWidget(self.count_label)
        root.addLayout(bottom)

    def _reload_workers(self) -> None:
        self.worker_combo.clear()
        self.worker_combo.addItem("الكل", None)
        try:
            for row in self.service.list_workers_for_selection():
                name = row.get("worker_name")
                self.worker_combo.addItem(
                    "" if name in (None, "") else str(name), row.get("worker_id")
                )
        except Exception:
            pass

    def _on_enable_dates(self, enabled: bool) -> None:
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)

    # -- data ---------------------------------------------------------------

    def refresh_table(self) -> None:
        use_dates = self.enable_dates.isChecked()
        date_from = self.date_from.date().toString("yyyy-MM-dd") if use_dates else None
        date_to = self.date_to.date().toString("yyyy-MM-dd") if use_dates else None
        worker_id = self.worker_combo.currentData()
        # No date filter -> only the latest 500. With a date range -> show all.
        limit = None if use_dates else DEFAULT_LIMIT
        try:
            rows = self.service.search_worker_vouchers(
                date_from=date_from, date_to=date_to, worker_id=worker_id, limit=limit
            )
        except Exception:
            rows = []
        self._row_records = [dict(row) for row in rows]

        self.table.setUpdatesEnabled(False)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self._row_records))
            for row_index, record in enumerate(self._row_records):
                for col_index, (key, _label) in enumerate(_COLUMNS):
                    value = record.get(key)
                    if key == "amount":
                        try:
                            text = f"{float(value or 0):,.2f}"
                        except (TypeError, ValueError):
                            text = "0.00"
                    else:
                        text = "" if value is None else str(value)
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setData(Qt.UserRole, record.get("id"))
                    if key == "voucher_number":
                        item.setBackground(QColor("#ECFDF3"))
                    self.table.setItem(row_index, col_index, item)
        finally:
            self.table.setUpdatesEnabled(True)

        if not self._columns_sized and self._row_records:
            self.table.resizeColumnsToContents()
            self._columns_sized = True
        if self._row_records:
            self.table.selectRow(0)
        hint = "" if not use_dates else " (ضمن المدة)"
        self.count_label.setText(
            "لا توجد سندات" if not rows else f"عدد السندات المعروضة: {len(rows)}{hint}"
        )

    # -- selection ----------------------------------------------------------

    def _accept_row(self, row: int, _column: int = 0) -> None:
        self.table.selectRow(row)
        self.accept_selected()

    def accept_selected(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0:
            if self.table.rowCount() == 0:
                return
            row = 0
        item = self.table.item(row, 0)
        if item is None:
            return
        voucher_id = item.data(Qt.UserRole)
        if voucher_id is None:
            return
        self.selected_id = voucher_id
        self.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept_selected()
            return
        super().keyPressEvent(event)
