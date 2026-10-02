"""Supplier Statement report screen (كشف حساب المورد).

Pure UI: it builds the RTL layout, gathers the filter values and renders the data
returned by ``SupplierStatementReportService``. It never touches SQL — every
value comes from the service, which in turn calls the repository. The report is
strictly read-only: nothing here inserts, updates or deletes any record.

Filters are «المورد» (only «عدد»-type suppliers are listed) and a date range.
معاينة / طباعة / تصدير PDF render through
:mod:`app.ui.screens.supplier_statement_print` (the single «Dashboard» template
the user picked); Excel export goes through the shared ``ExcelExporter``.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.repositories.supplier_statement_report_repository import ACCOUNT_TYPE_COUNT
from app.reports.excel_exporter import ExcelExporter
from app.services.supplier_statement_report_service import (
    EMPTY_MESSAGE,
    SupplierStatementReportService,
    SupplierStatementRequest,
    SupplierStatementValidationError,
)
from app.ui.common.theme import BORDER, GREEN, GREEN_DARK, TEXT, _button_style

CARD_BG = "#FFFFFF"
TEXT_MUTED = "#64748B"


class SupplierStatementReportScreen(QWidget):
    """RTL read-only supplier statement (purchase invoices + payment vouchers).

    The «عدد» variant is the concrete class; the «وزن» screen subclasses it and
    overrides the three class attributes below — everything else (layout, table,
    exports, printing) is shared.
    """

    # --- per-account-type configuration (overridden by subclasses) ----------
    REPORT_TITLE = "كشف حساب المورد"
    SUBTITLE = "كشف حساب تفصيلي بفواتير المشتريات وسندات الصرف للموردين (نوع الحساب: عدد)"
    ACCOUNT_TYPE = ACCOUNT_TYPE_COUNT
    # Bottom totals bar: (caption, summary key). Subclasses with a different
    # summary (e.g. the item-level ledger) override this.
    TOTALS_SPEC: tuple[tuple[str, str], ...] = (
        ("إجمالي المدين", "total_debit_label"),
        ("إجمالي الدائن", "total_credit_label"),
        ("الرصيد المستحق للمورد", "balance_label"),
    )

    def __init__(
        self,
        service: SupplierStatementReportService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or self._default_service()
        self.supplier_options = self._load_supplier_options()
        self.current_result = None
        self.setWindowTitle(self.REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1350, 840)
        self._build_ui()

    # --- overridable hooks (per report variant) -----------------------------
    def _default_service(self):
        """The service this screen drives; the «وزن» subclass inherits it, the
        item-level ledger screen overrides it with its own service."""
        return SupplierStatementReportService(account_type=self.ACCOUNT_TYPE)

    def _open_preview(self, data: dict[str, Any]) -> None:
        from app.ui.screens.supplier_statement_print import SupplierStatementPreviewDialog

        SupplierStatementPreviewDialog(data, parent=self).exec()

    def _export_pdf_file(self, data: dict[str, Any]) -> None:
        from app.ui.screens.supplier_statement_print import export_statement_to_pdf

        export_statement_to_pdf(self, data)

    def _print_document(self, data: dict[str, Any]) -> None:
        from app.ui.screens.supplier_statement_print import print_statement

        print_statement(self, data)

    # --- layout -------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self._build_header())
        layout.addWidget(self._build_filters())
        layout.addWidget(self._build_actions())
        layout.addWidget(self._build_table(), 1)
        layout.addWidget(self._build_totals())
        scroll.setWidget(content)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background:{GREEN}; border-radius:8px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        layout = QVBoxLayout(header)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(2)
        title = QLabel(self.REPORT_TITLE)
        title.setStyleSheet("font-size:24px; font-weight:900;")
        subtitle = QLabel(self.SUBTITLE)
        subtitle.setStyleSheet("font-size:13px; font-weight:700; color:#E8FBEF;")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _build_filters(self) -> QGroupBox:
        box = QGroupBox("الفلاتر")
        box.setStyleSheet(self._group_style())
        grid = QGridLayout(box)
        grid.setContentsMargins(14, 18, 14, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.supplier_combo = self._searchable_combo(self.supplier_options)
        self.from_date = self._date_edit()
        self.to_date = self._date_edit()

        fields = [
            ("المورد", self.supplier_combo),
            ("من تاريخ", self.from_date),
            ("إلى تاريخ", self.to_date),
        ]
        for index, (label, widget) in enumerate(fields):
            grid.addWidget(self._field(label, widget), 0, index)
            grid.setColumnStretch(index, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        search_button = QPushButton("بحث / عرض")
        reset_button = QPushButton("مسح الفلاتر")
        search_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
        reset_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        for button in (search_button, reset_button):
            button.setMinimumHeight(36)
            button.setCursor(Qt.PointingHandCursor)
        search_button.clicked.connect(self.apply_filters)
        reset_button.clicked.connect(self.reset_filters)
        buttons.addWidget(search_button)
        buttons.addWidget(reset_button)
        buttons.addStretch(1)
        grid.addLayout(buttons, 1, 0, 1, len(fields) + 1)
        return box

    def _build_actions(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background:{CARD_BG}; border:1px solid {BORDER}; border-radius:8px; }}")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color:{TEXT}; font-weight:800; border:none;")
        actions = [
            ("معاينة", self.print_preview),
            ("طباعة", self.print_report),
            ("PDF", self.export_pdf),
            ("Excel", self.export_excel),
            ("إغلاق", self.close_report),
        ]
        for text, callback in actions:
            button = QPushButton(text)
            button.setMinimumHeight(36)
            button.setCursor(Qt.PointingHandCursor)
            style = _button_style("#6B7280", "#4B5563") if text == "إغلاق" else _button_style(GREEN, GREEN_DARK)
            button.setStyleSheet(style)
            button.clicked.connect(lambda _checked=False, cb=callback: cb())
            layout.addWidget(button)
        layout.addStretch(1)
        layout.addWidget(self.count_label)
        return frame

    def _build_table(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setStyleSheet(f"QFrame {{ background:{CARD_BG}; border:1px solid {BORDER}; border-radius:10px; }}")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(10, 10, 10, 10)
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.service.columns))
        self.table.setHorizontalHeaderLabels([column.label for column in self.service.columns])
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(420)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; border:none; "
            "gridline-color:#E5E7EB; font-size:13px; }"
            f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; border:none; padding:10px 8px; }}"
        )
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        self.empty_label = QLabel(EMPTY_MESSAGE)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{TEXT_MUTED}; font-size:15px; font-weight:800; padding:18px; border:none;"
        )
        self.empty_label.setVisible(False)
        layout.addWidget(self.table)
        layout.addWidget(self.empty_label)
        return wrapper

    def _build_totals(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background:#EAF6EF; border:1px solid #BFE6CF; border-radius:8px; }}"
            "QLabel { border:none; background:transparent; }"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(26)
        self._total_labels = []
        for caption, key in self.TOTALS_SPEC:
            label = self._total_label(caption)
            label.setProperty("summary_key", key)
            self._total_labels.append(label)
        # RTL: add in reverse so the first spec item sits on the right.
        for label in reversed(self._total_labels):
            layout.addWidget(label)
        layout.addStretch(1)
        return frame

    def _total_label(self, caption: str) -> QLabel:
        label = QLabel(f"{caption}: —")
        label.setProperty("caption", caption)
        label.setStyleSheet(f"color:{TEXT}; font-size:14px; font-weight:900;")
        return label

    # --- field helpers ------------------------------------------------------
    def _field(self, label: str, widget: QWidget) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        text = QLabel(label)
        text.setAlignment(Qt.AlignRight)
        text.setStyleSheet(f"color:{TEXT_MUTED}; font-size:12px; font-weight:800;")
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(text)
        layout.addWidget(widget)
        return box

    def _date_edit(self) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setSpecialValueText("")
        edit.setMinimumDate(_dt.date(1900, 1, 1))
        edit.setDate(edit.minimumDate())
        edit.setMinimumHeight(36)
        edit.setStyleSheet("background:#F8FAFC; border:1px solid #CBD5E1; border-radius:7px; padding:5px;")
        return edit

    def _searchable_combo(self, options: list[dict[str, Any]]) -> QComboBox:
        """Searchable selector whose first item ('الكل', data None) means no
        filter — so a search with nothing selected returns every «عدد» supplier."""
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumHeight(36)
        combo.setStyleSheet("background:#F8FAFC; border:1px solid #CBD5E1; border-radius:7px; padding:5px;")
        combo.addItem("الكل", None)
        for option in options:
            combo.addItem(str(option.get("label") or ""), option.get("id"))
        completer = combo.completer()
        if completer is not None:
            completer.setCompletionMode(QCompleter.PopupCompletion)
            completer.setFilterMode(Qt.MatchContains)
        return combo

    # --- data flow ----------------------------------------------------------
    def _build_request(self) -> SupplierStatementRequest:
        return SupplierStatementRequest(
            supplier_id=self.supplier_combo.currentData(),
            date_from=self._date_value(self.from_date),
            date_to=self._date_value(self.to_date),
        )

    def apply_filters(self) -> None:
        try:
            result = self.service.fetch_report(self._build_request())
        except SupplierStatementValidationError as exc:
            QMessageBox.warning(self, "تحقق من الفلاتر", exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذر تحميل التقرير", str(exc))
            return
        self.current_result = result
        self._fill_table(result)
        self._fill_totals(result)
        self.count_label.setText(f"عدد الحركات: {len(result.export_rows):,}")

    def reset_filters(self) -> None:
        self.supplier_combo.setCurrentIndex(0)
        self.from_date.setDate(self.from_date.minimumDate())
        self.to_date.setDate(self.to_date.minimumDate())
        self.current_result = None
        self.table.setRowCount(0)
        self.table.setVisible(True)
        self.empty_label.setVisible(False)
        for label in self._total_labels:
            label.setText(f"{label.property('caption')}: —")
        self.count_label.setText("")

    def _fill_table(self, result) -> None:
        columns = result.columns
        rows = result.export_rows
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                value = row.get(column.key)
                item = QTableWidgetItem("" if value is None else str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column_index, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.empty_label.setVisible(result.is_empty)
        self.table.setVisible(not result.is_empty)

    def _fill_totals(self, result) -> None:
        summary = result.summary
        for label in self._total_labels:
            caption = label.property("caption")
            key = label.property("summary_key")
            label.setText(f"{caption}: {summary.get(key, '—')}")

    # --- exports ------------------------------------------------------------
    def _applied_filter_lines(self) -> list[str]:
        lines: list[str] = []
        lines.append(f"المورد: {self._combo_label(self.supplier_combo)}")
        date_from = self._date_value(self.from_date)
        date_to = self._date_value(self.to_date)
        lines.append(f"الفترة: من {date_from or 'البداية'} إلى {date_to or 'النهاية'}")
        lines.append(f"تاريخ الإصدار: {_dt.datetime.now():%Y-%m-%d %H:%M}")
        return lines

    def _summary_lines(self) -> list[str]:
        if self.current_result is None:
            return []
        summary = self.current_result.summary
        lines = [f"{caption}: {summary.get(key, '')}" for caption, key in self.TOTALS_SPEC]
        if self.current_result.is_empty:
            lines.insert(0, EMPTY_MESSAGE)
        return lines

    def _export_rows(self) -> list[dict[str, Any]]:
        return self.current_result.export_rows if self.current_result else []

    def export_excel(self) -> None:
        if not self._ensure_ran():
            return
        output = self._save_path("Excel Files (*.xlsx)", "xlsx")
        if output:
            ExcelExporter().export_with_summary(
                output, self.REPORT_TITLE, self._applied_filter_lines(),
                self.current_result.columns, self._export_rows(), self._summary_lines(),
            )
            QMessageBox.information(self, "تم التصدير", f"تم حفظ الملف:\n{output}")

    # --- printing (single «Dashboard» template) -----------------------------
    def _statement_print_data(self) -> dict[str, Any]:
        """Reshape the current result into what the print template consumes.

        The numeric ``rows`` (Decimal debit/credit/balance + ``kind``) are passed,
        not ``export_rows``: the template formats the money and colours the البيان
        badge by kind, so nothing must arrive pre-stringified.
        """
        result = self.current_result
        return {
            "title": self.REPORT_TITLE,
            "company_name": "",
            "supplier_label": self._combo_label(self.supplier_combo),
            "date_from_label": self._date_value(self.from_date) or "البداية",
            "date_to_label": self._date_value(self.to_date) or "النهاية",
            "rows": result.rows if result else [],
            "summary": result.summary if result else {},
            "is_empty": result.is_empty if result else True,
            "empty_message": EMPTY_MESSAGE,
        }

    def export_pdf(self) -> None:
        if not self._ensure_ran():
            return
        self._export_pdf_file(self._statement_print_data())

    def print_preview(self) -> None:
        if not self._ensure_ran():
            return
        self._open_preview(self._statement_print_data())

    def print_report(self) -> None:
        if not self._ensure_ran():
            return
        self._print_document(self._statement_print_data())

    def close_report(self) -> None:
        window = self.window()
        if window is not None:
            window.close()

    # --- small helpers ------------------------------------------------------
    def _ensure_ran(self) -> bool:
        if self.current_result is None:
            QMessageBox.warning(self, "لا توجد بيانات", "الرجاء تنفيذ البحث أولاً.")
            return False
        return True

    @staticmethod
    def _combo_label(combo: QComboBox) -> str:
        return "الكل" if combo.currentData() is None else combo.currentText()

    def _load_supplier_options(self) -> list[dict[str, Any]]:
        try:
            return self.service.load_supplier_options()
        except Exception:  # noqa: BLE001
            return []

    def _save_path(self, file_filter: str, suffix: str) -> Path | None:
        path, _selected = QFileDialog.getSaveFileName(
            self, "حفظ التقرير", f"{self.REPORT_TITLE}.{suffix}", file_filter
        )
        if not path:
            return None
        output = Path(path)
        if output.suffix.lower() != f".{suffix}":
            output = output.with_suffix(f".{suffix}")
        return output

    @staticmethod
    def _date_value(editor: QDateEdit) -> str | None:
        if editor.date() == editor.minimumDate():
            return None
        return editor.date().toString("yyyy-MM-dd")

    @staticmethod
    def _group_style() -> str:
        return (
            "QGroupBox { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; margin-top:14px; }"
            f"QGroupBox::title {{ subcontrol-origin:margin; subcontrol-position:top right; right:16px; "
            f"padding:0 12px; color:{GREEN}; font-weight:900; }}"
            f"QLabel {{ color:{TEXT}; font-weight:800; }}"
        )
