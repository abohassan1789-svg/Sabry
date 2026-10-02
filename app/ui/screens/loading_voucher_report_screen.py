"""Loading Vouchers report screen (تقرير سندات التحميل).

Pure UI: it builds the RTL layout, gathers the filter values and renders what
``LoadingVoucherReportService`` returns. It never touches SQL — every value comes
from the service, which calls the repository. The report is strictly read-only.

Layout (design approved 2026-08-21):
* a filter card — من تاريخ · إلى تاريخ, then three **drop-down** selectors
  (العميل · الصنف · رقم السيارة), each defaulting to «الكل» (no restriction);
* three summary cards — عدد سندات التحميل · إجمالي الوزن قبل التحميل ·
  إجمالي الوزن بعد التحميل;
* a details table with the ten required columns (رقم السند · التاريخ · الوقت ·
  اسم العميل · اسم الصنف · اسم السائق · رقم السيارة · الوزن قبل/بعد · ملاحظات).

Printing / PDF / Excel are a later phase and are deliberately not wired here yet.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDateEdit,
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

from app.services.loading_voucher_report_service import (
    EMPTY_MESSAGE,
    LoadingVoucherReportRequest,
    LoadingVoucherReportService,
    LoadingVoucherReportValidationError,
)
from app.ui.common.theme import BORDER, GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.screens.loading_voucher_report_print import (
    LoadingVoucherReportPreviewDialog,
    export_report_to_pdf,
)

REPORT_TITLE = "تقرير سندات التحميل"

CARD_BG = "#FFFFFF"
TEXT_MUTED = "#64748B"

# Columns rendered right-aligned (free text); the rest are centred.
_RIGHT_ALIGN = frozenset({"customer_name", "item_name", "driver_name", "notes"})

# The three summary cards: (key into summary, caption).
_CARDS = (
    ("voucher_count_label", "عدد سندات التحميل"),
    ("total_weight_before_label", "إجمالي الوزن قبل التحميل"),
    ("total_weight_after_label", "إجمالي الوزن بعد التحميل"),
)


class LoadingVoucherReportScreen(QWidget):
    """RTL read-only loading-vouchers report (filter · cards · detail table)."""

    def __init__(
        self,
        service: LoadingVoucherReportService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or LoadingVoucherReportService()
        self.customer_options = self.service.load_customer_options()
        self.item_options = self.service.load_item_options()
        self.vehicle_options = self.service.load_vehicle_options()
        self.current_result = None
        self._card_values: dict[str, QLabel] = {}
        # Letterhead is print/PDF only — fetched here, rendered only on the sheet.
        # Guarded so a test double without the selector can't break the screen.
        try:
            self._company = self.service.company_letterhead()
        except Exception:  # noqa: BLE001
            self._company = None
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1350, 840)
        self._build_ui()

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
        layout.addWidget(self._build_cards())
        layout.addWidget(self._build_table(), 1)
        layout.addWidget(self._build_actions())
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
        title = QLabel(REPORT_TITLE)
        title.setStyleSheet("font-size:24px; font-weight:900;")
        subtitle = QLabel("تقرير تفصيلي بسندات تحميل السيارات وأوزانها قبل وبعد التحميل")
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

        self.from_date = self._date_edit()
        self.to_date = self._date_edit()
        self.customer_combo = self._searchable_combo(self.customer_options)
        self.item_combo = self._searchable_combo(self.item_options)
        self.vehicle_combo = self._searchable_combo(self.vehicle_options)

        fields = [
            ("من تاريخ", self.from_date),
            ("إلى تاريخ", self.to_date),
            ("اسم العميل", self.customer_combo),
            ("اسم الصنف", self.item_combo),
            ("رقم السيارة", self.vehicle_combo),
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
        preview_button = QPushButton("🖨️ معاينة / طباعة")
        pdf_button = QPushButton("⬇️ PDF")
        preview_button.setStyleSheet(_button_style("#1D4ED8", "#1E40AF"))
        pdf_button.setStyleSheet(_button_style("#B91C1C", "#991B1B"))
        for button in (preview_button, pdf_button):
            button.setMinimumHeight(36)
            button.setCursor(Qt.PointingHandCursor)
        preview_button.clicked.connect(self.open_preview)
        pdf_button.clicked.connect(self.export_pdf)

        search_button.clicked.connect(self.apply_filters)
        reset_button.clicked.connect(self.reset_filters)
        buttons.addWidget(search_button)
        buttons.addWidget(reset_button)
        buttons.addWidget(preview_button)
        buttons.addWidget(pdf_button)
        buttons.addStretch(1)
        grid.addLayout(buttons, 1, 0, 1, len(fields))
        return box

    def _build_cards(self) -> QWidget:
        section = QWidget()
        row = QHBoxLayout(section)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for key, caption in _CARDS:
            card, value = self._stat_card(caption)
            self._card_values[key] = value
            row.addWidget(card, 1)
        return section

    def _stat_card(self, caption: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setMinimumHeight(92)
        card.setStyleSheet(
            f"QFrame {{ background:{CARD_BG}; border:1px solid {BORDER}; "
            f"border-right:5px solid {GREEN}; border-radius:12px; }}"
            "QLabel { border:none; background:transparent; }"
        )
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)
        label = QLabel(caption)
        label.setStyleSheet(f"color:{TEXT_MUTED}; font-size:13px; font-weight:800;")
        value = QLabel("—")
        value.setStyleSheet(f"color:{GREEN_DARK}; font-size:26px; font-weight:900;")
        box.addWidget(label)
        box.addWidget(value)
        return card, value

    def _build_table(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setStyleSheet(
            f"QFrame {{ background:{CARD_BG}; border:1px solid {BORDER}; border-radius:10px; }}"
        )
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(10, 10, 10, 10)
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.service.columns))
        self.table.setHorizontalHeaderLabels([c.label for c in self.service.columns])
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(420)
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; alternate-background-color:#F8FAFC; border:none; "
            "gridline-color:#E5E7EB; font-size:13px; }"
            f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:10px 8px; }}"
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.empty_label = QLabel(EMPTY_MESSAGE)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{TEXT_MUTED}; font-size:15px; font-weight:800; padding:18px; border:none;"
        )
        self.empty_label.setVisible(False)
        layout.addWidget(self.table)
        layout.addWidget(self.empty_label)
        return wrapper

    def _build_actions(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background:{CARD_BG}; border:1px solid {BORDER}; border-radius:8px; }}"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color:{TEXT}; font-weight:800; border:none;")
        close_button = QPushButton("إغلاق")
        close_button.setMinimumHeight(36)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        close_button.clicked.connect(self.close_report)
        layout.addWidget(close_button)
        layout.addStretch(1)
        layout.addWidget(self.count_label)
        return frame

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
        edit.setStyleSheet(
            "background:#F8FAFC; border:1px solid #CBD5E1; border-radius:7px; padding:5px;"
        )
        return edit

    def _searchable_combo(self, options: list[dict[str, Any]]) -> QComboBox:
        """Drop-down whose first item ('الكل', data None) means no filter — so a
        search with nothing selected returns the full view."""
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMinimumHeight(36)
        combo.setStyleSheet(
            "background:#F8FAFC; border:1px solid #CBD5E1; border-radius:7px; padding:5px;"
        )
        combo.addItem("الكل", None)
        for option in options:
            combo.addItem(str(option.get("label") or ""), option.get("id"))
        completer = combo.completer()
        if completer is not None:
            completer.setCompletionMode(QCompleter.PopupCompletion)
            completer.setFilterMode(Qt.MatchContains)
        return combo

    # --- data flow ----------------------------------------------------------
    def _build_request(self) -> LoadingVoucherReportRequest:
        return LoadingVoucherReportRequest(
            date_from=self._date_value(self.from_date),
            date_to=self._date_value(self.to_date),
            customer_id=self.customer_combo.currentData(),
            product_id=self.item_combo.currentData(),
            vehicle_number=self.vehicle_combo.currentData(),
        )

    def refresh_dashboard(self) -> None:
        """Reload the filter drop-downs so vouchers added since the screen was last
        shown appear without restarting the app.

        ``main_window.open_screen`` calls this on every re-open of an already-built
        report window (the screen is cached and reused). The three combos are
        DISTINCT-over-the-vouchers lists, so a newly-saved سند تحميل introduces its
        customer / item / vehicle here the next time the report is opened.
        """
        self._reload_filter_options()

    def _reload_filter_options(self) -> None:
        """Re-query the three drop-downs, preserving the current selection."""
        self.customer_options = self.service.load_customer_options()
        self.item_options = self.service.load_item_options()
        self.vehicle_options = self.service.load_vehicle_options()
        self._repopulate_combo(self.customer_combo, self.customer_options)
        self._repopulate_combo(self.item_combo, self.item_options)
        self._repopulate_combo(self.vehicle_combo, self.vehicle_options)

    @staticmethod
    def _repopulate_combo(combo: QComboBox, options: list[dict[str, Any]]) -> None:
        """Rebuild a combo's items, keeping «الكل» first and restoring the previous
        selection when it still exists (else falling back to «الكل»)."""
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("الكل", None)
        for option in options:
            combo.addItem(str(option.get("label") or ""), option.get("id"))
        index = combo.findData(previous) if previous is not None else 0
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def apply_filters(self) -> None:
        # Refresh the drop-downs first, so a voucher added while this (cached)
        # window stayed open is searchable without re-opening it.
        self._reload_filter_options()
        try:
            result = self.service.fetch_report(self._build_request())
        except LoadingVoucherReportValidationError as exc:
            QMessageBox.warning(self, "تحقق من الفلاتر", exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذر تحميل التقرير", str(exc))
            return
        self.current_result = result
        self._fill_table(result)
        self._fill_cards(result)
        self.count_label.setText(f"عدد السندات: {len(result.rows):,}")

    def reset_filters(self) -> None:
        self.from_date.setDate(self.from_date.minimumDate())
        self.to_date.setDate(self.to_date.minimumDate())
        for combo in (self.customer_combo, self.item_combo, self.vehicle_combo):
            combo.setCurrentIndex(0)
        self.current_result = None
        self.table.setRowCount(0)
        self.table.setVisible(True)
        self.empty_label.setVisible(False)
        for value in self._card_values.values():
            value.setText("—")
        self.count_label.setText("")

    def _fill_table(self, result) -> None:
        columns = result.columns
        rows = result.rows
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                value = row.get(column.key)
                item = QTableWidgetItem("" if value is None else str(value))
                if column.key in _RIGHT_ALIGN:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column_index, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.empty_label.setVisible(result.is_empty)
        self.table.setVisible(not result.is_empty)

    def _fill_cards(self, result) -> None:
        summary = result.summary
        for key, value in self._card_values.items():
            value.setText(str(summary.get(key, "—")))

    # --- print / preview / PDF (same path as تقرير المشتريات) --------------
    def _print_data(self) -> dict[str, Any] | None:
        """Reshape the current result + filter labels into what the print sheet
        consumes. ``None`` when no search has run yet."""
        if self.current_result is None:
            return None
        result = self.current_result
        return {
            "company": self._company,
            "title": REPORT_TITLE,
            "date_from_label": self._date_value(self.from_date) or "البداية",
            "date_to_label": self._date_value(self.to_date) or "النهاية",
            "customer_label": self._combo_label(self.customer_combo),
            "item_label": self._combo_label(self.item_combo),
            "vehicle_label": self._combo_label(self.vehicle_combo),
            "summary": result.summary,
            "rows": result.rows,
            "is_empty": result.is_empty,
            "empty_message": EMPTY_MESSAGE,
        }

    def open_preview(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل الطباعة.")
            return
        LoadingVoucherReportPreviewDialog(data, parent=self).exec()

    def export_pdf(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل التصدير.")
            return
        export_report_to_pdf(self, data)

    @staticmethod
    def _combo_label(combo: QComboBox) -> str:
        """The selected label, or 'الكل' when nothing specific is chosen."""
        return "الكل" if combo.currentData() is None else combo.currentText()

    # --- small helpers ------------------------------------------------------
    def close_report(self) -> None:
        window = self.window()
        if window is not None:
            window.close()

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


__all__ = ["LoadingVoucherReportScreen", "REPORT_TITLE"]
