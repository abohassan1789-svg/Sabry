"""Lookup dialogs for the purchase-invoice screen.

The supplier picker reuses the generic :class:`EntityPickerDialog` from the
sales dialogs module (a scalable search picker that filters the whole table,
not just the pre-loaded first 100 rows). This module adds only the F1 invoice
lookup, which is purchase-specific: it has a supplier filter (not a company
one), no VAT column and no PDF-export column (purchases don't print).

Pure UI: all data access is delegated to :class:`PurchaseInvoiceService`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.purchase_invoice import STATUS_APPROVED, STATUS_DRAFT, STATUS_LABELS_AR
from app.ui.common.saudi_invoice_style import SI_GREEN, style_button
from app.ui.dialogs.saudi_invoice_dialogs import EntityPickerDialog

_TABLE_QSS = (
    "QTableWidget { background:#FFFFFF; border:1px solid #D7DEE7; border-radius:8px; "
    "gridline-color:#EEF1F4; font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size:13px; }"
    f"QHeaderView::section {{ background:{SI_GREEN}; color:#FFFFFF; font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; "
    "font-weight:800; border:none; padding:8px; }"
    "QTableWidget::item { padding:6px; color:#111827; }"
    "QTableWidget::item:selected { background:#E7F6EE; color:#0B3B23; }"
)
_SEARCH_QSS = (
    "QLineEdit { background:#FFFFFF; border:1px solid #D7DEE7; border-radius:8px; "
    "padding:7px 12px; font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size:13px; }"
    f"QLineEdit:focus {{ border:1px solid {SI_GREEN}; }}"
)
_FIELD_QSS = (
    "QComboBox, QDateEdit { background:#FFFFFF; border:1px solid #D7DEE7; border-radius:8px; "
    "padding:5px 10px; font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size:13px; }"
    f"QComboBox:focus, QDateEdit:focus {{ border:1px solid {SI_GREEN}; }}"
    "QComboBox:disabled, QDateEdit:disabled { background:#F1F5F9; color:#94A3B8; }"
)
_FILTER_LABEL_QSS = (
    "color:#334155; font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; "
    "font-size:13px; font-weight:700;"
)


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


class PurchaseInvoiceSearchDialog(QDialog):
    """F1 lookup over the purchase-invoice tables with status/supplier filters."""

    _COLUMNS = (
        ("invoice_number", "رقم الفاتورة"),
        ("supplier_name_snapshot", "المورد"),
        ("issue_datetime", "التاريخ والوقت"),
        ("document_status", "الحالة"),
        ("total_count_price", "إجمالي الفاتورة"),
        ("total_weight_price", "إجمالي الوزن"),
    )

    def __init__(self, service: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.selected_id: int | None = None
        self._rows: list[dict[str, Any]] = []

        self.setWindowTitle("بحث عن فاتورة مشتريات")
        self.resize(1000, 600)
        self.setLayoutDirection(Qt.RightToLeft)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._run_search)

        self._build_ui()
        self._run_search()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        heading = QLabel("بحث عن فاتورة")
        heading.setStyleSheet(
            f"color:{SI_GREEN}; font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size:16px; font-weight:800;"
        )
        root.addWidget(heading)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("رقم الفاتورة / المورد…")
        self.search.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.search.setStyleSheet(_SEARCH_QSS)
        self.search.textChanged.connect(self._timer.start)
        filters.addWidget(self.search, 1)

        self.status_combo = QComboBox()
        self.status_combo.addItem("كل الحالات", None)
        self.status_combo.addItem(STATUS_LABELS_AR[STATUS_DRAFT], STATUS_DRAFT)
        self.status_combo.addItem(STATUS_LABELS_AR[STATUS_APPROVED], STATUS_APPROVED)
        self.status_combo.setStyleSheet(_FIELD_QSS)
        self.status_combo.setFixedHeight(34)
        self.status_combo.setMinimumWidth(150)
        self.status_combo.currentIndexChanged.connect(self._run_search)
        filters.addWidget(self.status_combo)
        root.addLayout(filters)

        # Second filter row: supplier + optional issue-date range.
        filters2 = QHBoxLayout()
        filters2.setSpacing(8)

        supplier_label = QLabel("المورد:")
        supplier_label.setStyleSheet(_FILTER_LABEL_QSS)
        filters2.addWidget(supplier_label)

        self.supplier_combo = QComboBox()
        self.supplier_combo.addItem("كل الموردين", None)
        for supplier in self._load_suppliers():
            sid = supplier.get("supplier_id")
            name = supplier.get("supplier_name") or f"#{sid}"
            self.supplier_combo.addItem(str(name), sid)
        self.supplier_combo.setStyleSheet(_FIELD_QSS)
        self.supplier_combo.setFixedHeight(34)
        self.supplier_combo.setMinimumWidth(220)
        self.supplier_combo.currentIndexChanged.connect(self._run_search)
        filters2.addWidget(self.supplier_combo)

        filters2.addSpacing(12)

        self.date_enable = QCheckBox("تحديد الفترة")
        self.date_enable.setStyleSheet(_FILTER_LABEL_QSS)
        self.date_enable.toggled.connect(self._on_date_toggle)
        filters2.addWidget(self.date_enable)

        today = QDate.currentDate()
        from_label = QLabel("من")
        from_label.setStyleSheet(_FILTER_LABEL_QSS)
        filters2.addWidget(from_label)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_from.setDate(QDate(today.year(), today.month(), 1))
        self.date_from.setStyleSheet(_FIELD_QSS)
        self.date_from.setFixedHeight(34)
        self.date_from.setMinimumWidth(130)
        self.date_from.setEnabled(False)
        self.date_from.dateChanged.connect(self._on_date_changed)
        filters2.addWidget(self.date_from)

        to_label = QLabel("إلى")
        to_label.setStyleSheet(_FILTER_LABEL_QSS)
        filters2.addWidget(to_label)
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.date_to.setDate(today)
        self.date_to.setStyleSheet(_FIELD_QSS)
        self.date_to.setFixedHeight(34)
        self.date_to.setMinimumWidth(130)
        self.date_to.setEnabled(False)
        self.date_to.dateChanged.connect(self._on_date_changed)
        filters2.addWidget(self.date_to)

        filters2.addStretch(1)
        root.addLayout(filters2)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels([h for _k, h in self._COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setStyleSheet(_TABLE_QSS)
        self.table.itemDoubleClicked.connect(lambda *_a: self._accept())
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#64748B; font-weight:700;")
        open_button = QPushButton("فتح")
        open_button.setFixedHeight(36)
        open_button.setMinimumWidth(120)
        style_button(open_button, "green")
        open_button.clicked.connect(self._accept)
        cancel_button = QPushButton("إلغاء")
        cancel_button.setFixedHeight(36)
        cancel_button.setMinimumWidth(110)
        style_button(cancel_button, "white")
        cancel_button.clicked.connect(self.reject)
        bottom.addWidget(open_button)
        bottom.addWidget(cancel_button)
        bottom.addStretch(1)
        bottom.addWidget(self.count_label)
        root.addLayout(bottom)

    def _load_suppliers(self) -> list[dict[str, Any]]:
        try:
            return self.service.list_suppliers(1000)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "فشل تحميل الموردين", str(exc))
            return []

    def _on_date_toggle(self, checked: bool) -> None:
        self.date_from.setEnabled(checked)
        self.date_to.setEnabled(checked)
        self._run_search()

    def _on_date_changed(self, *_a: Any) -> None:
        if self.date_enable.isChecked():
            self._run_search()

    def _run_search(self) -> None:
        status = self.status_combo.currentData()
        supplier_id = self.supplier_combo.currentData()
        date_from = date_to = None
        if self.date_enable.isChecked():
            date_from = self.date_from.date().toPython()
            date_to = self.date_to.date().toPython()
        try:
            self._rows = self.service.search_invoices(
                self.search.text(),
                status,
                300,
                supplier_id=supplier_id,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "فشل البحث", str(exc))
            self._rows = []
        self._fill()

    def _fill(self) -> None:
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            self.table.setRowCount(len(self._rows))
            for r, record in enumerate(self._rows):
                for c, (key, _header) in enumerate(self._COLUMNS):
                    value = record.get(key)
                    if key == "document_status":
                        text = STATUS_LABELS_AR.get(value, value or "")
                    elif key == "issue_datetime" and value is not None:
                        text = value.strftime("%Y-%m-%d %H:%M")
                    else:
                        text = _fmt(value)
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignCenter)
                    if c == 0:
                        item.setData(Qt.UserRole, record.get("id"))
                    self.table.setItem(r, c, item)
        finally:
            self.table.setUpdatesEnabled(True)
        self.count_label.setText(f"عدد الفواتير: {len(self._rows)}")

    def _accept(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        first = self.table.item(row, 0)
        invoice_id = first.data(Qt.UserRole) if first is not None else None
        if invoice_id is None:
            return
        self.selected_id = int(invoice_id)
        self.accept()


__all__ = ["EntityPickerDialog", "PurchaseInvoiceSearchDialog"]
