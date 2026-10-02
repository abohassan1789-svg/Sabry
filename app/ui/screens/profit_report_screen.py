"""Profit Report screen — تقرير الأرباح («النموذج السادس»: البطاقات الملوّنة).

Pure UI: it builds the RTL layout, gathers the filter values and renders what
``ProfitReportService`` returns. It never touches SQL — every value comes from
the service, which calls the read-only repository.

Design (chosen by the user from ten print mock-ups, 2026-08-19): Model 6 —
three big gradient KPI cards (المبيعات أخضر · المشتريات أحمر · صافي الربح أزرق),
a sales-vs-purchases **donut**, then a flat detail table (one row per invoice):
التاريخ · نوع الحركة · البيان · المبيعات · المشتريات, with a totals row.

Rows come from two header tables merged by date: sales invoices carry their total
in ``total_including_vat``; purchase invoices in ``total_count_price +
total_weight_price``. صافي الربح = إجمالي المبيعات − إجمالي المشتريات.

The company **letterhead** belongs to the printed sheet only and printing is a
later stage — this screen shows no letterhead and has no print/PDF controls yet.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
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

from app.services.profit_report_service import (
    EMPTY_MESSAGE,
    ProfitReportRequest,
    ProfitReportResult,
    ProfitReportService,
    ProfitReportValidationError,
    TYPE_ALL,
    TYPE_PURCHASE,
    TYPE_SALE,
)
from app.ui.common.theme import GREEN, GREEN_DARK, _button_style
from app.ui.screens.profit_report_print import (
    ProfitReportPreviewDialog,
    export_report_to_pdf,
)

REPORT_TITLE = "تقرير الأرباح"

_TYPE_LABELS = {TYPE_ALL: "كل الحركات", TYPE_SALE: "المبيعات فقط", TYPE_PURCHASE: "المشتريات فقط"}

_TEXT = "#0F1C14"
_MUTED = "#6B7A6F"
_LINE = "#E1E9E1"
_POS = "#047857"
_NEG = "#B91C1C"
_BLUE = "#1D4ED8"
_DATE_BLUE = "#1D4ED8"
_ROW_ALT = "#F3F8F4"

# Detail table columns.
COL_DATE, COL_TYPE, COL_STATEMENT, COL_SALES, COL_PURCHASES = range(5)

_CALENDAR_QSS = (
    "QCalendarWidget QWidget { background:#FFFFFF; color:#1D4ED8; }"
    "QCalendarWidget QAbstractItemView:enabled { background:#FFFFFF; color:#1D4ED8; "
    "selection-background-color:#1D4ED8; selection-color:#FFFFFF; }"
    "QCalendarWidget QAbstractItemView:disabled { color:#9CA3AF; }"
    "QCalendarWidget #qt_calendar_navigationbar { background:#E7F3EA; }"
    "QCalendarWidget QToolButton { color:#0F1C14; background:transparent; font-weight:800; padding:4px 10px; }"
    "QCalendarWidget QToolButton:hover { background:#D6EBDD; }"
    "QCalendarWidget QToolButton::menu-indicator { image:none; }"
    "QCalendarWidget QSpinBox, QCalendarWidget QMenu { background:#FFFFFF; color:#0F1C14; }"
)


def _style_calendar(edit: QDateEdit) -> None:
    calendar = edit.calendarWidget()
    if calendar is None:
        return
    calendar.setStyleSheet(_CALENDAR_QSS)
    blue = QTextCharFormat()
    blue.setForeground(QColor(_DATE_BLUE))
    for day in (Qt.Monday, Qt.Tuesday, Qt.Wednesday, Qt.Thursday,
                Qt.Friday, Qt.Saturday, Qt.Sunday):
        calendar.setWeekdayTextFormat(day, blue)


def _date_edit(value: str | None = None) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    edit.setMinimumHeight(34)
    edit.setStyleSheet(
        f"QDateEdit {{ background:#FFFFFF; border:1px solid #CBD5C9; border-radius:7px; "
        f"padding:5px 9px; color:{_DATE_BLUE}; font-weight:800; }}"
        f"QDateEdit:focus {{ border:1px solid {GREEN}; }}"
    )
    _style_calendar(edit)
    if value:
        edit.setDate(QDate.fromString(value, "yyyy-MM-dd"))
    return edit


def _labeled(label: str, widget: QWidget) -> QWidget:
    box = QWidget()
    box.setStyleSheet("background:transparent;")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    text = QLabel(label)
    text.setAlignment(Qt.AlignRight)
    text.setStyleSheet(f"color:{_MUTED}; font-size:12px; font-weight:800; border:none;")
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    layout.addWidget(text)
    layout.addWidget(widget)
    return box


# ---------------------------------------------------------------------------
# Donut widget — المبيعات (أخضر) مقابل المشتريات (أحمر), net profit at centre
# ---------------------------------------------------------------------------
class ProfitDonut(QWidget):
    """A two-segment donut painted from the service's ``pie`` rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._center_top = "صافي الربح"
        self._center_value = ""
        self.setMinimumSize(168, 168)
        self.setMaximumSize(210, 210)

    def set_data(self, rows: list[dict[str, Any]], center_value: str) -> None:
        self._rows = rows or []
        self._center_value = center_value or ""
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001 - Qt event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        margin = 20
        rect = QRectF(
            (self.width() - side) / 2 + margin,
            (self.height() - side) / 2 + margin,
            side - 2 * margin,
            side - 2 * margin,
        )
        total = sum(int(row.get("count", 0)) for row in self._rows)
        if total <= 0:
            painter.setPen(QPen(QColor("#D6E3DA"), 22))
            painter.drawEllipse(rect)
        else:
            start = 90 * 16
            for row in self._rows:
                span = int(-360 * 16 * int(row.get("count", 0)) / total)
                painter.setPen(QPen(QColor(str(row.get("color", GREEN))), 22, Qt.SolidLine, Qt.FlatCap))
                painter.drawArc(rect, start, span)
                start += span
        # centre caption + value
        painter.setPen(QColor(_MUTED))
        cap_font = QFont(self.font())
        cap_font.setPointSizeF(max(7.0, self.font().pointSizeF() - 1))
        painter.setFont(cap_font)
        top_rect = QRectF(rect.left(), rect.center().y() - 18, rect.width(), 16)
        painter.drawText(top_rect, Qt.AlignCenter, self._center_top)
        painter.setPen(QColor(GREEN_DARK))
        val_font = QFont(self.font())
        val_font.setBold(True)
        val_font.setPointSizeF(self.font().pointSizeF() + 2)
        painter.setFont(val_font)
        val_rect = QRectF(rect.left(), rect.center().y() - 2, rect.width(), 22)
        painter.drawText(val_rect, Qt.AlignCenter, self._center_value)


# ---------------------------------------------------------------------------
# Filter dialog — date range + movement type
# ---------------------------------------------------------------------------
class ProfitReportFilterDialog(QDialog):
    """Popup with the report filters: date range + movement-type toggle."""

    def __init__(self, state: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._movement_type = state.get("movement_type") or TYPE_ALL
        self.setWindowTitle("الفلترة والبحث — تقرير الأرباح")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(540)
        self.setStyleSheet("QDialog { background:#F6F8F5; }")
        self._build_ui(state)

    def _build_ui(self, state: dict[str, Any]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        heading = QLabel("🔎 الفلترة والبحث")
        heading.setStyleSheet(f"color:{GREEN_DARK}; font-size:16px; font-weight:900;")
        root.addWidget(heading)

        self.from_date = _date_edit(state.get("date_from"))
        self.to_date = _date_edit(state.get("date_to"))
        dates = QHBoxLayout()
        dates.setSpacing(12)
        dates.addWidget(_labeled("من تاريخ", self.from_date), 1)
        dates.addWidget(_labeled("إلى تاريخ", self.to_date), 1)
        root.addLayout(dates)

        self.all_button = self._toggle_button("الكل", TYPE_ALL)
        self.sale_button = self._toggle_button("مبيعات", TYPE_SALE)
        self.purchase_button = self._toggle_button("مشتريات", TYPE_PURCHASE)
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(0)
        toggle_row.addWidget(self.all_button)
        toggle_row.addWidget(self.sale_button)
        toggle_row.addWidget(self.purchase_button)
        toggle_row.addStretch(1)
        root.addWidget(_labeled("نوع الحركة", self._wrap(toggle_row)))
        self._sync_toggle()

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        show_button = QPushButton("عرض التقرير")
        show_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
        show_button.setMinimumHeight(38)
        show_button.setCursor(Qt.PointingHandCursor)
        show_button.clicked.connect(self.accept)
        clear_button = QPushButton("مسح الفلاتر")
        clear_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        clear_button.setMinimumHeight(38)
        clear_button.setCursor(Qt.PointingHandCursor)
        clear_button.clicked.connect(self._clear)
        cancel_button = QPushButton("إلغاء")
        cancel_button.setStyleSheet(_button_style("#94A3B8", "#64748B"))
        cancel_button.setMinimumHeight(38)
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(show_button)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

    def _wrap(self, layout) -> QWidget:
        box = QWidget()
        box.setStyleSheet("background:transparent;")
        box.setLayout(layout)
        return box

    def _toggle_button(self, text: str, value: str) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setMinimumHeight(34)
        button.setMinimumWidth(96)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _c=False, v=value: self._set_type(v))
        return button

    def _set_type(self, value: str) -> None:
        self._movement_type = value
        self._sync_toggle()

    def _sync_toggle(self) -> None:
        on = (
            f"QPushButton {{ background:{GREEN}; color:#FFFFFF; border:1px solid {GREEN}; "
            "font-weight:900; }"
        )
        off = (
            "QPushButton { background:#FFFFFF; color:#4B5563; border:1px solid #CBD5C9; "
            "font-weight:800; }"
        )
        for button, value in (
            (self.all_button, TYPE_ALL),
            (self.sale_button, TYPE_SALE),
            (self.purchase_button, TYPE_PURCHASE),
        ):
            active = self._movement_type == value
            button.setChecked(active)
            button.setStyleSheet(on if active else off)

    def _clear(self) -> None:
        self._movement_type = TYPE_ALL
        self._sync_toggle()

    def result_state(self) -> dict[str, Any]:
        return {
            "date_from": self.from_date.date().toString("yyyy-MM-dd"),
            "date_to": self.to_date.date().toString("yyyy-MM-dd"),
            "movement_type": self._movement_type,
        }


class ProfitReportScreen(QWidget):
    """RTL read-only profit report (colored KPI cards + donut + detail table)."""

    def __init__(
        self, service: ProfitReportService | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service or ProfitReportService()
        today = QDate.currentDate()
        self._date_from = QDate(today.year(), today.month(), 1).toString("yyyy-MM-dd")
        self._date_to = today.toString("yyyy-MM-dd")
        self._movement_type = TYPE_ALL
        self.current_result: ProfitReportResult | None = None
        # The letterhead is print/PDF only — fetched here, rendered only on the sheet.
        self._company = self.service.company_letterhead()
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1280, 840)
        self._build_ui()
        self.apply_filters()

    # --- layout -------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background:#F6F8F5; border:none; }")
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background:#F6F8F5;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_cards())
        layout.addWidget(self._build_charts_row())
        layout.addWidget(self._section_title("تفاصيل الحركات (فواتير المبيعات والمشتريات)"))
        layout.addWidget(self._build_table(), 1)
        scroll.setWidget(content)

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background:#FFFFFF; border:1px solid {_LINE}; border-radius:14px; }}")
        return frame

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"color:{_TEXT}; font-size:13px; font-weight:900; border:none; "
            f"border-right:5px solid {GREEN}; padding:0 10px;"
        )
        return label

    # --- top toolbar --------------------------------------------------------
    def _build_toolbar(self) -> QFrame:
        bar = self._card()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)

        filter_button = QPushButton("🔎 الفلترة والبحث")
        filter_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
        filter_button.setMinimumHeight(36)
        filter_button.setMinimumWidth(160)
        filter_button.setCursor(Qt.PointingHandCursor)
        filter_button.clicked.connect(self.open_filters)

        reset_button = QPushButton("مسح")
        reset_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        reset_button.setMinimumHeight(36)
        reset_button.setCursor(Qt.PointingHandCursor)
        reset_button.clicked.connect(self.reset_filters)

        preview_button = QPushButton("🖨️ معاينة / طباعة")
        preview_button.setStyleSheet(_button_style("#1D4ED8", "#1E40AF"))
        preview_button.setMinimumHeight(36)
        preview_button.setCursor(Qt.PointingHandCursor)
        preview_button.clicked.connect(self.open_preview)

        pdf_button = QPushButton("⬇️ تصدير PDF")
        pdf_button.setStyleSheet(_button_style("#B91C1C", "#991B1B"))
        pdf_button.setMinimumHeight(36)
        pdf_button.setCursor(Qt.PointingHandCursor)
        pdf_button.clicked.connect(self.export_pdf)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(f"color:{_MUTED}; font-size:12.5px; font-weight:700; border:none;")
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color:{_TEXT}; font-weight:900; border:none;")

        layout.addWidget(filter_button)
        layout.addWidget(reset_button)
        layout.addWidget(preview_button)
        layout.addWidget(pdf_button)
        layout.addSpacing(8)
        layout.addWidget(self.summary_label)
        layout.addStretch(1)
        layout.addWidget(self.count_label)
        self._update_summary()
        return bar

    # --- big gradient KPI cards --------------------------------------------
    def _build_cards(self) -> QWidget:
        section = QWidget()
        section.setStyleSheet("background:transparent;")
        row = QHBoxLayout(section)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._sales_card = self._gradient_card("💰 إجمالي المبيعات", "#047857", "#065F46")
        self._purchases_card = self._gradient_card("🛒 إجمالي المشتريات", "#B91C1C", "#991B1B")
        self._profit_card = self._gradient_card("📈 صافي الربح", "#1D4ED8", "#1E40AF")
        row.addWidget(self._sales_card["frame"], 1)
        row.addWidget(self._purchases_card["frame"], 1)
        row.addWidget(self._profit_card["frame"], 1)
        return section

    def _gradient_card(self, title: str, c1: str, c2: str) -> dict[str, Any]:
        frame = QFrame()
        frame.setMinimumHeight(104)
        frame.setStyleSheet(
            f"QFrame {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c1}, stop:1 {c2}); "
            "border-radius:14px; }"
            "QLabel { background:transparent; color:#FFFFFF; border:none; }"
        )
        box = QVBoxLayout(frame)
        box.setContentsMargins(16, 13, 16, 13)
        box.setSpacing(4)
        caption = QLabel(title)
        caption.setStyleSheet("font-size:12.5px; font-weight:800; color:#E6F4EA;")
        value = QLabel("—")
        value.setStyleSheet("font-size:26px; font-weight:900;")
        sub = QLabel("")
        sub.setStyleSheet("font-size:11px; font-weight:800; color:#DCEAF7;")
        box.addWidget(caption)
        box.addWidget(value)
        box.addWidget(sub)
        return {"frame": frame, "value": value, "sub": sub}

    # --- donut row ----------------------------------------------------------
    def _build_charts_row(self) -> QWidget:
        panel = self._card()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        title_box = QVBoxLayout()
        title_box.setSpacing(6)
        title = QLabel("توزيع المبيعات مقابل المشتريات")
        title.setStyleSheet(f"color:{_TEXT}; font-size:15px; font-weight:900; border:none;")
        title_box.addWidget(title)
        self._legend = QVBoxLayout()
        self._legend.setSpacing(6)
        title_box.addLayout(self._legend)
        title_box.addStretch(1)

        self.donut = ProfitDonut()
        layout.addWidget(self.donut, 0, Qt.AlignVCenter)
        layout.addLayout(title_box, 1)
        return panel

    def _rebuild_legend(self, pie: list[dict[str, Any]]) -> None:
        while self._legend.count():
            item = self._legend.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not pie:
            empty = QLabel("لا توجد بيانات كافية لعرض الرسم البياني")
            empty.setStyleSheet(f"color:{_MUTED}; font-size:12.5px; font-weight:700; border:none;")
            self._legend.addWidget(empty)
            return
        for row in pie:
            line = QLabel(
                f"■ {row['label']}    {row['value_label']}    ({row['share']:.1f}%)"
            )
            line.setStyleSheet(
                f"color:{row['color']}; font-size:13px; font-weight:900; border:none;"
            )
            self._legend.addWidget(line)

    # --- detail table -------------------------------------------------------
    def _build_table(self) -> QFrame:
        wrapper = self._card()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(12, 12, 12, 12)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["التاريخ", "نوع الحركة", "البيان", "المبيعات", "المشتريات"]
        )
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(True)
        self.table.setMinimumHeight(440)
        self.table.setStyleSheet(
            f"QTableWidget {{ background:#FFFFFF; alternate-background-color:{_ROW_ALT}; "
            f"border:2px solid {GREEN}; border-radius:10px; font-size:13px; gridline-color:#E1E9E1; }}"
            f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; "
            "border:none; padding:9px 6px; font-size:13px; }"
            "QTableWidget::item { padding:6px 4px; color:#111111; }"
        )
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_DATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_STATEMENT, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_SALES, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_PURCHASES, QHeaderView.ResizeToContents)
        header.setMinimumSectionSize(120)

        self.empty_label = QLabel(EMPTY_MESSAGE)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{_MUTED}; font-size:15px; font-weight:800; padding:18px; border:none;"
        )
        self.empty_label.setVisible(False)
        layout.addWidget(self.table)
        layout.addWidget(self.empty_label)
        return wrapper

    # --- filters ------------------------------------------------------------
    def open_filters(self) -> None:
        dialog = ProfitReportFilterDialog(self._filter_state(), parent=self)
        if dialog.exec():
            state = dialog.result_state()
            self._date_from = state["date_from"]
            self._date_to = state["date_to"]
            self._movement_type = state["movement_type"]
            self.apply_filters()

    def _filter_state(self) -> dict[str, Any]:
        return {
            "date_from": self._date_from,
            "date_to": self._date_to,
            "movement_type": self._movement_type,
        }

    def reset_filters(self) -> None:
        today = QDate.currentDate()
        self._date_from = QDate(today.year(), today.month(), 1).toString("yyyy-MM-dd")
        self._date_to = today.toString("yyyy-MM-dd")
        self._movement_type = TYPE_ALL
        self.apply_filters()

    # --- data flow ----------------------------------------------------------
    def _build_request(self) -> ProfitReportRequest:
        return ProfitReportRequest(
            date_from=self._date_from,
            date_to=self._date_to,
            movement_type=self._movement_type,
        )

    def apply_filters(self) -> None:
        try:
            result = self.service.fetch_report(self._build_request())
        except ProfitReportValidationError as exc:
            QMessageBox.warning(self, "تحقق من الفلاتر", exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذر تحميل التقرير", str(exc))
            return
        self.current_result = result
        self._fill_cards(result)
        self._fill_table(result)
        self._update_summary()
        self.count_label.setText(f"عدد الحركات: {result.summary['movement_count_label']}")

    def _fill_cards(self, result: ProfitReportResult) -> None:
        s = result.summary
        self._sales_card["value"].setText(s["total_sales_label"])
        self._sales_card["sub"].setText(f"{s['sales_count_label']} فاتورة بيع")
        self._purchases_card["value"].setText(s["total_purchases_label"])
        self._purchases_card["sub"].setText(f"{s['purchase_count_label']} فاتورة شراء")
        self._profit_card["value"].setText(s["net_profit_label"])
        self._profit_card["sub"].setText(f"هامش الربح {s['margin_label']}")
        self.donut.set_data(result.pie, s["net_profit_label"])
        self._rebuild_legend(result.pie)

    def _fill_table(self, result: ProfitReportResult) -> None:
        rows = result.export_rows
        self.table.setRowCount(0)
        self.empty_label.setVisible(result.is_empty)
        self.table.setVisible(not result.is_empty)
        if result.is_empty:
            return

        bold = QFont(self.table.font())
        bold.setBold(True)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._set_cell(r, COL_DATE, row["date"], Qt.AlignCenter)
            type_color = _POS if row["type_code"] == TYPE_SALE else _NEG
            self._set_cell(r, COL_TYPE, row["type_label"], Qt.AlignCenter, color=type_color, bold=True)
            self._set_cell(r, COL_STATEMENT, row["statement"], Qt.AlignCenter)
            self._set_cell(r, COL_SALES, row["sales_amount"] or "—",
                           Qt.AlignCenter, color=_POS if row["sales_amount"] else "#9CA3AF",
                           bold=bool(row["sales_amount"]))
            self._set_cell(r, COL_PURCHASES, row["purchase_amount"] or "—",
                           Qt.AlignCenter, color=_NEG if row["purchase_amount"] else "#9CA3AF",
                           bold=bool(row["purchase_amount"]))

        # Totals row.
        s = result.summary
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._set_cell(r, COL_DATE, "", Qt.AlignCenter, bg="#E7F3EA")
        self._set_cell(r, COL_TYPE, "", Qt.AlignCenter, bg="#E7F3EA")
        self._set_cell(r, COL_STATEMENT, "الإجمالي", Qt.AlignCenter, color=GREEN_DARK, bold=True, bg="#E7F3EA")
        self._set_cell(r, COL_SALES, s["total_sales_label"], Qt.AlignCenter, color=_POS, bold=True, bg="#E7F3EA")
        self._set_cell(r, COL_PURCHASES, s["total_purchases_label"], Qt.AlignCenter, color=_NEG, bold=True, bg="#E7F3EA")

    def _set_cell(
        self,
        row: int,
        col: int,
        text: str,
        alignment,
        *,
        color: str | None = None,
        bold: bool = False,
        bg: str | None = None,
    ) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(alignment)
        if color is not None:
            item.setForeground(QColor(color))
        if bg is not None:
            item.setBackground(QColor(bg))
        if bold:
            font = QFont(self.table.font())
            font.setBold(True)
            item.setFont(font)
        self.table.setItem(row, col, item)

    def _update_summary(self) -> None:
        parts = [
            f"الفترة: {self._date_from} — {self._date_to}",
            _TYPE_LABELS.get(self._movement_type, "كل الحركات"),
        ]
        self.summary_label.setText("  •  ".join(parts))

    # --- print / preview / PDF ---------------------------------------------
    def _print_data(self) -> dict[str, Any] | None:
        if self.current_result is None:
            return None
        result = self.current_result
        return {
            "company": self._company,
            "title": REPORT_TITLE,
            "date_from_label": self._date_from,
            "date_to_label": self._date_to,
            "movement_type_label": _TYPE_LABELS.get(self._movement_type, "كل الحركات"),
            "summary": result.summary,
            "export_rows": result.export_rows,
            "pie": result.pie,
            "is_empty": result.is_empty,
            "empty_message": EMPTY_MESSAGE,
        }

    def open_preview(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل الطباعة.")
            return
        ProfitReportPreviewDialog(data, parent=self).exec()

    def export_pdf(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل التصدير.")
            return
        export_report_to_pdf(self, data)


__all__ = [
    "ProfitReportScreen",
    "ProfitReportFilterDialog",
    "ProfitDonut",
    "REPORT_TITLE",
]
