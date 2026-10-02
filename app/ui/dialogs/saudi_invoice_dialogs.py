"""Lookup dialogs for the Saudi sales-invoice screen.

* :class:`EntityPickerDialog` — a generic, scalable search picker used for the
  seller company, the customer and the product. It calls a service *search*
  callable (``search_fn(keyword, limit)``) so typing filters the **whole**
  database, never just the pre-loaded first 100 rows.
* :class:`SaudiInvoiceSearchDialog` — the F1 invoice lookup over the new Saudi
  invoice tables only, with status filters (مسودة / معتمدة).

Pure UI: all data access is delegated to :class:`SaudiSalesInvoiceService`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Sequence

from PySide6.QtCore import QDate, Qt, QTimer, Signal
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

from app.models.sales_invoice import STATUS_APPROVED, STATUS_DRAFT, STATUS_LABELS_AR
from app.ui.common.saudi_invoice_style import SI_GREEN, SI_GREEN_DARK, style_button

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
_EXPORT_LINK_QSS = (
    f"QLabel {{ background:transparent; color:{SI_GREEN}; "
    "font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size:13px; padding:4px; }"
    f"QLabel:hover {{ color:{SI_GREEN_DARK}; }}"
)
# Sentinel column key for the per-row «تصدير» PDF hyperlink (not a data field).
_EXPORT_COL_KEY = "__export__"


class _PdfLinkLabel(QLabel):
    """A cell widget that looks and behaves like a text hyperlink.

    A plain ``QLabel`` anchor (``<a>``) loses its palette link colour once the
    widget carries a stylesheet, so the word renders invisibly. This styles the
    colour via QSS (reliable) and underlines via the font, and emits ``clicked``
    for the whole cell rather than only the glyphs."""

    clicked = Signal()

    def __init__(self, text: str = "PDF", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._pressed = False
        self.setStyleSheet(_EXPORT_LINK_QSS)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        font = self.font()
        font.setUnderline(True)
        font.setBold(True)
        self.setFont(font)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Emit on RELEASE, not press: opening a modal dialog while the press's
        # implicit mouse grab is still held freezes the app once you nest a few
        # modal loops deep (picker -> preview -> file dialog -> async PDF).
        if event.button() == Qt.LeftButton:
            self._pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        was_pressed = self._pressed
        self._pressed = False
        super().mouseReleaseEvent(event)  # lets Qt drop the mouse grab first
        if was_pressed and event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if self.rect().contains(pos):
                self.clicked.emit()


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


class EntityPickerDialog(QDialog):
    """Searchable table picker returning the selected row dict(s).

    ``columns`` is a sequence of ``(key, header)`` pairs; ``search_fn`` returns a
    list of row dicts for a keyword. The chosen row is exposed as ``self.selected``.
    With ``multi_select=True`` the table accepts Ctrl/Shift ranges and every chosen
    row is exposed, in table order, as ``self.selected_rows`` (``selected`` stays
    the first one so single-pick callers keep working).
    """

    def __init__(
        self,
        title: str,
        columns: Sequence[tuple[str, str]],
        search_fn: Callable[[str, int], list[dict[str, Any]]],
        id_key: str,
        parent: QWidget | None = None,
        limit: int = 100,
        multi_select: bool = False,
    ) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._search_fn = search_fn
        self._id_key = id_key
        self._limit = limit
        self._multi_select = multi_select
        self.selected: dict[str, Any] | None = None
        self.selected_rows: list[dict[str, Any]] = []
        self._rows: list[dict[str, Any]] = []

        self.setWindowTitle(title)
        self.resize(860, 560)
        self.setLayoutDirection(Qt.RightToLeft)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._run_search)

        self._build_ui(title)
        self._run_search()

    def _build_ui(self, title: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        heading = QLabel(title)
        heading.setStyleSheet(
            f"color:{SI_GREEN}; font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size:16px; font-weight:800;"
        )
        root.addWidget(heading)

        self.search = QLineEdit()
        self.search.setPlaceholderText("ابحث بالاسم أو الكود أو الرقم الضريبي…")
        self.search.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.search.setStyleSheet(_SEARCH_QSS)
        self.search.textChanged.connect(self._timer.start)
        root.addWidget(self.search)

        if self._multi_select:
            hint = QLabel("علّم على مربع الاختيار (✔) أمام كل صنف تريده — يمكنك اختيار أكثر من صنف.")
            hint.setStyleSheet(
                "color:#64748B; font-family:'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size:12px; font-weight:700;"
            )
            root.addWidget(hint)

        # In multi-select mode a leading checkbox column is the primary way to pick
        # rows; the data columns are shifted one to the right.
        headers = [header for _key, header in self._columns]
        if self._multi_select:
            headers = ["✔"] + headers

        self.table = QTableWidget()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.ExtendedSelection if self._multi_select else QAbstractItemView.SingleSelection
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Stretch)
        if self._multi_select:
            header_view.setSectionResizeMode(0, QHeaderView.Fixed)
            self.table.setColumnWidth(0, 46)
        self.table.setStyleSheet(_TABLE_QSS)
        self.table.itemDoubleClicked.connect(lambda *_a: self._accept())
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#64748B; font-weight:700;")
        select_button = QPushButton("اختيار")
        select_button.setFixedHeight(36)
        select_button.setMinimumWidth(120)
        style_button(select_button, "green")
        select_button.clicked.connect(self._accept)
        cancel_button = QPushButton("إلغاء")
        cancel_button.setFixedHeight(36)
        cancel_button.setMinimumWidth(110)
        style_button(cancel_button, "white")
        cancel_button.clicked.connect(self.reject)
        bottom.addWidget(select_button)
        bottom.addWidget(cancel_button)
        bottom.addStretch(1)
        bottom.addWidget(self.count_label)
        root.addLayout(bottom)

    def _run_search(self) -> None:
        try:
            self._rows = self._search_fn(self.search.text(), self._limit)
        except Exception as exc:  # noqa: BLE001 - surface to user, never crash
            QMessageBox.critical(self, "فشل البحث", str(exc))
            self._rows = []
        self._fill()

    def _fill(self) -> None:
        # In multi-select mode column 0 is the checkbox; the row's record is stored
        # on that checkbox item. In single-select mode the record lives on the first
        # (and only) data column, exactly as before. Either way it is always on the
        # item at column 0, so _accept() reads it uniformly.
        offset = 1 if self._multi_select else 0
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self._rows))
            for r, record in enumerate(self._rows):
                if self._multi_select:
                    checkbox = QTableWidgetItem()
                    checkbox.setFlags(
                        Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
                    )
                    checkbox.setCheckState(Qt.Unchecked)
                    checkbox.setTextAlignment(Qt.AlignCenter)
                    checkbox.setData(Qt.UserRole, record)
                    self.table.setItem(r, 0, checkbox)
                for c, (key, _header) in enumerate(self._columns):
                    item = QTableWidgetItem(_fmt(record.get(key)))
                    item.setTextAlignment(Qt.AlignCenter)
                    if c == 0 and not self._multi_select:
                        item.setData(Qt.UserRole, record)
                    self.table.setItem(r, c + offset, item)
        finally:
            self.table.setUpdatesEnabled(True)
        self.count_label.setText(f"عدد النتائج: {len(self._rows)}")

    def _checked_row_indexes(self) -> list[int]:
        return [
            r for r in range(self.table.rowCount())
            if (it := self.table.item(r, 0)) is not None and it.checkState() == Qt.Checked
        ]

    def _selected_row_indexes(self) -> list[int]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if rows:
            return rows
        current = self.table.currentRow()
        return [current] if current >= 0 else []

    def _accept(self) -> None:
        # Ticked checkboxes win; if the user ticked nothing we fall back to the
        # highlighted row(s) so a double-click / single highlight still selects.
        if self._multi_select:
            rows = self._checked_row_indexes() or self._selected_row_indexes()
        else:
            rows = self._selected_row_indexes()
        records = []
        for row in rows:
            first = self.table.item(row, 0)
            record = first.data(Qt.UserRole) if first is not None else None
            if record is not None:
                records.append(record)
        if not records:
            return
        self.selected_rows = records
        self.selected = records[0]
        self.accept()


class SaudiInvoiceSearchDialog(QDialog):
    """F1 lookup over the Saudi invoice tables with status filters."""

    _COLUMNS = (
        ("invoice_number", "رقم الفاتورة"),
        ("seller_name_ar_snapshot", "البائع"),
        ("customer_name_snapshot", "العميل"),
        ("issue_datetime", "التاريخ والوقت"),
        ("document_status", "الحالة"),
        ("total_including_vat", "الإجمالي شامل الضريبة"),
        (_EXPORT_COL_KEY, "تصدير"),
    )

    def __init__(
        self,
        service: Any,
        parent: QWidget | None = None,
        print_callback: "Callable[[int, QWidget], None] | None" = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.selected_id: int | None = None
        self._rows: list[dict[str, Any]] = []
        self._status: str | None = None
        # Called with (invoice_id, dialog) when a row's «PDF» link is clicked;
        # the page wires it to print_saved_invoice so listed invoices export/print
        # without being loaded onto the form. None → the link is inert.
        self._print_callback = print_callback

        self.setWindowTitle("بحث عن فاتورة مبيعات سعودية")
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
        self.search.setPlaceholderText("رقم الفاتورة / البائع / العميل…")
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

        # Second filter row: seller company + optional issue-date range.
        filters2 = QHBoxLayout()
        filters2.setSpacing(8)

        company_label = QLabel("الشركة:")
        company_label.setStyleSheet(_FILTER_LABEL_QSS)
        filters2.addWidget(company_label)

        self.company_combo = QComboBox()
        self.company_combo.addItem("كل الشركات", None)
        for company in self._load_companies():
            cid = company.get("id")
            name = company.get("name_ar") or company.get("name_en") or f"#{cid}"
            self.company_combo.addItem(str(name), cid)
        self.company_combo.setStyleSheet(_FIELD_QSS)
        self.company_combo.setFixedHeight(34)
        self.company_combo.setMinimumWidth(220)
        self.company_combo.currentIndexChanged.connect(self._run_search)
        filters2.addWidget(self.company_combo)

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
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        # The «تصدير» link column hugs its content instead of stretching.
        header.setSectionResizeMode(len(self._COLUMNS) - 1, QHeaderView.ResizeToContents)
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

    def _load_companies(self) -> list[dict[str, Any]]:
        try:
            return self.service.list_companies(1000)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "فشل تحميل الشركات", str(exc))
            return []

    def _on_date_toggle(self, checked: bool) -> None:
        self.date_from.setEnabled(checked)
        self.date_to.setEnabled(checked)
        self._run_search()

    def _on_date_changed(self, *_a: Any) -> None:
        # Only re-query while the date range is active.
        if self.date_enable.isChecked():
            self._run_search()

    def _run_search(self) -> None:
        status = self.status_combo.currentData()
        company_id = self.company_combo.currentData()
        date_from = date_to = None
        if self.date_enable.isChecked():
            date_from = self.date_from.date().toPython()
            date_to = self.date_to.date().toPython()
        try:
            self._rows = self.service.search_invoices(
                self.search.text(),
                status,
                300,
                company_id=company_id,
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
            # setRowCount(0) drops the previous rows' cell widgets (the PDF links)
            # too, so their stale row->id closures never linger.
            self.table.setRowCount(0)
            self.table.setRowCount(len(self._rows))
            for r, record in enumerate(self._rows):
                for c, (key, _header) in enumerate(self._COLUMNS):
                    if key == _EXPORT_COL_KEY:
                        self.table.setCellWidget(r, c, self._make_export_cell(record.get("id")))
                        continue
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

    def _make_export_cell(self, invoice_id: Any) -> QWidget:
        """A centered «PDF» hyperlink that exports/prints the row's invoice."""
        link = _PdfLinkLabel("PDF")
        link.setToolTip("تصدير الفاتورة PDF")
        link.clicked.connect(lambda iid=invoice_id: self._on_export_clicked(iid))
        return link

    def _on_export_clicked(self, invoice_id: Any) -> None:
        if invoice_id is None:
            return
        if self._print_callback is None:
            QMessageBox.information(self, "تصدير PDF", "خدمة التصدير غير متاحة.")
            return
        # Defer to the next event-loop tick so the current click fully unwinds
        # before the nested template-picker / QWebEngine preview loop opens.
        callback = self._print_callback
        iid = int(invoice_id)
        QTimer.singleShot(0, lambda: callback(iid, self))

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


__all__ = ["EntityPickerDialog", "SaudiInvoiceSearchDialog"]
