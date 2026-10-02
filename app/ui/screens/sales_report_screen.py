"""Sales report screen (تقرير المبيعات) — the "النموذج ٤" design (compact).

Pure UI: it builds the RTL layout, gathers the filter values and renders what
``SalesReportService`` returns. It never touches SQL — every value comes from the
service, which calls the repository. The report is strictly read-only.

Design (chosen by the user from ten mock-ups, 2026-08-15; refined 2026-08-15):
* a slim top toolbar whose **الفلترة والبحث** button opens a popup dialog holding
  all the filters (date range + item + customer, each with a بحث picker),
* a compact dark-green **hero** header carrying the three dashboard cards,
* a compact **donut** chart of the top-5 customers under the hero,
* a details table (raised up) with the ten required columns — including
  الإجمالي (before VAT), الضريبة and الإجمالي شامل الضريبة — and **green cell
  borders**.

Printing / preview / export are a later phase and are intentionally absent here.
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
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.sales_report_service import (
    EMPTY_MESSAGE,
    SalesReportRequest,
    SalesReportService,
    SalesReportValidationError,
)
from app.ui.common.theme import GREEN, GREEN_DARK, _button_style
from app.ui.dialogs.saudi_invoice_dialogs import EntityPickerDialog
from app.ui.screens.sales_report_print import (
    SalesReportPreviewDialog,
    export_report_to_pdf,
)

REPORT_TITLE = "تقرير المبيعات"

# Five green shades (darkest = biggest slice) shared by the donut and its legend.
DONUT_GREENS = ("#0B5326", "#0F6B30", "#137A38", "#2E9E57", "#62C888")

_PICKER_LIMIT = 500
_TEXT = "#0F1C14"
_MUTED = "#6B7A6F"
_LINE = "#E1E9E1"
# Details-table body: black bold text, centered, on two alternating row colors
# (white + light green) — user choice 2026-08-15.
_CELL_TEXT = "#000000"
_ROW_ALT = "#E6F4EA"
# Date fields + calendar popup: white background, blue text (user request).
_DATE_BLUE = "#1D4ED8"
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
    """White calendar popup with blue day/date text (incl. weekends)."""
    calendar = edit.calendarWidget()
    if calendar is None:
        return
    calendar.setStyleSheet(_CALENDAR_QSS)
    blue = QTextCharFormat()
    blue.setForeground(QColor(_DATE_BLUE))
    for day in (Qt.Monday, Qt.Tuesday, Qt.Wednesday, Qt.Thursday,
                Qt.Friday, Qt.Saturday, Qt.Sunday):
        calendar.setWeekdayTextFormat(day, blue)


def _picker_field(placeholder: str, on_click) -> tuple[QLineEdit, QWidget]:
    """A read-only text field showing the chosen name + a بحث button."""
    wrap = QWidget()
    wrap.setStyleSheet("background:transparent;")
    layout = QHBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    field = QLineEdit()
    field.setReadOnly(True)
    field.setPlaceholderText(placeholder)
    field.setMinimumHeight(34)
    field.setStyleSheet(
        "QLineEdit { background:#FFFFFF; border:1px solid #CBD5C9; border-left:none; "
        "border-top-left-radius:0; border-bottom-left-radius:0; "
        "border-top-right-radius:7px; border-bottom-right-radius:7px; padding:5px 9px; color:#0F1C14; }"
    )
    button = QPushButton("🔍 بحث")
    button.setMinimumHeight(34)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton {{ background:{GREEN}; color:#FFFFFF; border:none; "
        "border-top-left-radius:7px; border-bottom-left-radius:7px; font-weight:800; padding:0 12px; }"
        f"QPushButton:hover {{ background:{GREEN_DARK}; }}"
    )
    button.clicked.connect(on_click)
    layout.addWidget(button)
    layout.addWidget(field, 1)
    return field, wrap


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


class SalesReportFilterDialog(QDialog):
    """Popup holding the sales-report filters (date range + item + customer).

    Opens the same searchable pickers (newest 500, searchable beyond) the rest of
    the app uses. Pre-filled from the screen's current state so reopening keeps
    the previous selection; ``result_state()`` returns the chosen values.
    """

    def __init__(self, service: Any, state: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._customer_id = state.get("customer_id")
        self._customer_name = state.get("customer_name") or ""
        self._product_id = state.get("product_id")
        self._product_name = state.get("product_name") or ""

        self.setWindowTitle("الفلترة والبحث — تقرير المبيعات")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(560)
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
        self.customer_field, customer_widget = _picker_field("اختر عميلًا…", self._pick_customer)
        self.product_field, product_widget = _picker_field("اختر صنفًا…", self._pick_product)
        self.customer_field.setText(self._customer_name)
        self.product_field.setText(self._product_name)

        dates = QHBoxLayout()
        dates.setSpacing(12)
        dates.addWidget(_labeled("من تاريخ", self.from_date), 1)
        dates.addWidget(_labeled("إلى تاريخ", self.to_date), 1)
        root.addLayout(dates)

        root.addWidget(_labeled("اسم الصنف", product_widget))
        root.addWidget(_labeled("اسم العميل", customer_widget))

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

    def _pick_customer(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن عميل",
            (("customer_id", "الكود"), ("customer_name", "اسم العميل"), ("phone_number", "الهاتف")),
            self.service.search_customers,
            "customer_id",
            parent=self,
            limit=_PICKER_LIMIT,
        )
        if dialog.exec() and dialog.selected is not None:
            self._customer_id = _as_int(dialog.selected.get("customer_id"))
            self._customer_name = str(dialog.selected.get("customer_name") or "")
            self.customer_field.setText(self._customer_name)

    def _pick_product(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن صنف",
            (("item_code", "الكود"), ("item_name", "اسم الصنف"), ("price", "السعر")),
            self.service.search_products,
            "id",
            parent=self,
            limit=_PICKER_LIMIT,
        )
        if dialog.exec() and dialog.selected is not None:
            self._product_id = _as_int(dialog.selected.get("id"))
            self._product_name = str(dialog.selected.get("item_name") or "")
            self.product_field.setText(self._product_name)

    def _clear(self) -> None:
        self._customer_id = None
        self._customer_name = ""
        self._product_id = None
        self._product_name = ""
        self.customer_field.clear()
        self.product_field.clear()

    def result_state(self) -> dict[str, Any]:
        return {
            "date_from": self.from_date.date().toString("yyyy-MM-dd"),
            "date_to": self.to_date.date().toString("yyyy-MM-dd"),
            "customer_id": self._customer_id,
            "customer_name": self._customer_name,
            "product_id": self._product_id,
            "product_name": self._product_name,
        }


class _ReportTable(QTableWidget):
    """Details table whose columns fill the width proportionally.

    Fixed per-column weights keep the layout balanced (the two name columns get
    the most room; the numeric columns stay compact) and always fill the viewport
    — no single stretched column leaving a big empty gap. Recomputed on resize.
    Weights map to the 10 columns: date, customer, invoice#, item, unit,
    quantity, price, total (net), VAT, total including VAT.
    """

    _WEIGHTS = (1.25, 1.85, 1.0, 1.95, 0.7, 0.8, 1.0, 1.1, 0.9, 1.35)

    def resizeEvent(self, event: Any) -> None:  # noqa: ANN401 - Qt event
        super().resizeEvent(event)
        self.apply_widths()

    def apply_widths(self) -> None:
        count = self.columnCount()
        if count == 0:
            return
        weights = list(self._WEIGHTS[:count])
        if len(weights) < count:
            weights += [1.0] * (count - len(weights))
        total = sum(weights) or 1.0
        width = self.viewport().width()
        if width <= 0:
            return
        used = 0
        for index in range(count):
            if index == count - 1:
                col = max(60, width - used)
            else:
                col = max(60, int(width * weights[index] / total))
            self.setColumnWidth(index, col)
            used += col


class TopCustomersDonut(QWidget):
    """A compact donut of the top-5 customers, drawn with five green shades."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slices: list[tuple[float, str]] = []
        self._center_value = ""
        self._center_caption = ""
        self.setMinimumSize(132, 132)
        self.setMaximumSize(150, 150)

    def set_data(
        self, top_customers: list[dict[str, Any]], center_value: str, center_caption: str
    ) -> None:
        self._slices = [
            (float(item.get("value") or 0), DONUT_GREENS[index % len(DONUT_GREENS)])
            for index, item in enumerate(top_customers)
        ]
        self._center_value = center_value
        self._center_caption = center_caption
        self.update()

    def paintEvent(self, _event: Any) -> None:  # noqa: ANN401 - Qt event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height())
        left = (self.width() - size) / 2 + 5
        top = (self.height() - size) / 2 + 5
        rect = QRectF(left, top, size - 10, size - 10)

        total = sum(value for value, _color in self._slices)
        if total <= 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#E9EFE9"))
            painter.drawEllipse(rect)
        else:
            start = 90 * 16
            for value, color in self._slices:
                span = int(round(-360 * 16 * value / total))
                painter.setPen(QPen(QColor("#FFFFFF"), 2))
                painter.setBrush(QColor(color))
                painter.drawPie(rect, start, span)
                start += span

        # Punch the hole.
        hole_r = rect.width() * 0.32
        center = rect.center()
        hole = QRectF(center.x() - hole_r, center.y() - hole_r, hole_r * 2, hole_r * 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(hole)

        # Center text: value (bold) above a small caption.
        painter.setPen(QColor(GREEN_DARK))
        value_font = self.font()
        value_font.setPointSize(11)
        value_font.setBold(True)
        painter.setFont(value_font)
        value_rect = QRectF(hole.left(), hole.top() + hole.height() * 0.18, hole.width(), hole.height() * 0.46)
        painter.drawText(value_rect, Qt.AlignCenter, self._center_value)
        painter.setPen(QColor(_MUTED))
        caption_font = self.font()
        caption_font.setPointSize(7)
        caption_font.setBold(True)
        painter.setFont(caption_font)
        caption_rect = QRectF(hole.left(), hole.top() + hole.height() * 0.55, hole.width(), hole.height() * 0.30)
        painter.drawText(caption_rect, Qt.AlignCenter, self._center_caption)


class SalesReportScreen(QWidget):
    """RTL read-only sales report (approved-invoice lines + dashboard KPIs)."""

    def __init__(
        self, service: SalesReportService | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service or SalesReportService()
        # Filter state lives on the screen; the popup edits a copy and returns it.
        today = QDate.currentDate()
        self._date_from = QDate(today.year(), today.month(), 1).toString("yyyy-MM-dd")
        self._date_to = today.toString("yyyy-MM-dd")
        self._customer_id: int | None = None
        self._customer_name = ""
        self._product_id: int | None = None
        self._product_name = ""
        self.current_result = None
        # Letterhead is print/PDF only — fetched here, rendered only on the sheet.
        # Guarded so a test double without the selector can't break the screen.
        try:
            self._company = self.service.company_letterhead()
        except Exception:  # noqa: BLE001
            self._company = None
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1280, 820)
        self._build_ui()

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
        layout.setSpacing(9)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_chart())
        layout.addWidget(self._section_title("تفاصيل الفواتير"))
        layout.addWidget(self._build_table(), 1)
        scroll.setWidget(content)

    # --- top toolbar (filter button + summary + count) ----------------------
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

        pdf_button = QPushButton("⬇️ PDF")
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

    # --- hero + KPI cards (compact) -----------------------------------------
    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("hero")
        hero.setStyleSheet(
            "QFrame#hero { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #0F6B30, stop:1 #0A4D22); border-radius:14px; }"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        box = QVBoxLayout(hero)
        box.setContentsMargins(14, 11, 14, 13)
        box.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel(f"📊 {REPORT_TITLE}")
        title.setStyleSheet("font-size:17px; font-weight:900;")
        top.addWidget(title)
        top.addStretch(1)
        self.period_label = QLabel("")
        self.period_label.setStyleSheet("font-size:11.5px; font-weight:700; color:#BFE3CB;")
        top.addWidget(self.period_label)
        box.addLayout(top)

        cards = QHBoxLayout()
        cards.setSpacing(11)
        self.kpi_total = self._kpi_card("💰 إجمالي المبيعات")
        self.kpi_customer = self._kpi_card("👑 أعلى عميل")
        self.kpi_item = self._kpi_card("🥇 أعلى صنف مبيعًا")
        for card in (self.kpi_total, self.kpi_customer, self.kpi_item):
            cards.addWidget(card["frame"], 1)
        box.addLayout(cards)
        self._update_period_label()
        return hero

    def _kpi_card(self, title: str) -> dict[str, Any]:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.22); "
            "border-radius:11px; }"
            "QLabel { background:transparent; color:#FFFFFF; border:none; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(13, 10, 13, 10)
        layout.setSpacing(4)
        caption = QLabel(title)
        caption.setStyleSheet("font-size:11.5px; font-weight:800; color:#CDE9D6;")
        value = QLabel("—")
        value.setStyleSheet("font-size:19px; font-weight:900;")
        value.setWordWrap(True)
        sub = QLabel("")
        sub.setStyleSheet("font-size:11.5px; font-weight:800; color:#BFE3CB;")
        layout.addWidget(caption)
        layout.addWidget(value)
        layout.addWidget(sub)
        return {"frame": frame, "value": value, "sub": sub}

    # --- donut chart + legend (compact) -------------------------------------
    def _build_chart(self) -> QFrame:
        card = self._card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(6)
        title = QLabel("أكبر ٥ عملاء من حيث المبيعات")
        title.setStyleSheet(f"color:{_TEXT}; font-size:13px; font-weight:900; border:none;")
        outer.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        self.donut = TopCustomersDonut()
        row.addWidget(self.donut, 0, Qt.AlignVCenter)

        legend_wrap = QVBoxLayout()
        legend_wrap.setSpacing(4)
        self.legend_box = QVBoxLayout()
        self.legend_box.setSpacing(0)
        legend_wrap.addLayout(self.legend_box)
        legend_wrap.addStretch(1)
        row.addLayout(legend_wrap, 1)
        outer.addLayout(row)
        self._render_legend([])
        return card

    def _render_legend(self, top_customers: list[dict[str, Any]]) -> None:
        while self.legend_box.count():
            item = self.legend_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not top_customers:
            empty = QLabel("لا توجد بيانات لعرضها")
            empty.setStyleSheet(f"color:{_MUTED}; font-size:12px; font-weight:700; border:none; padding:4px 0;")
            self.legend_box.addWidget(empty)
            return
        for index, item in enumerate(top_customers):
            color = DONUT_GREENS[index % len(DONUT_GREENS)]
            self.legend_box.addWidget(self._legend_row(color, item))

    def _legend_row(self, color: str, item: dict[str, Any]) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)
        swatch = QLabel()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet(f"background:{color}; border-radius:3px;")
        name = QLabel(str(item.get("label") or ""))
        name.setStyleSheet(f"color:{_TEXT}; font-size:12px; font-weight:800; border:none;")
        name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        percent = QLabel(f"{item.get('share', 0):g}%")
        percent.setStyleSheet(f"color:{_MUTED}; font-size:11px; font-weight:800; border:none;")
        percent.setFixedWidth(50)
        percent.setAlignment(Qt.AlignCenter)
        value = QLabel(str(item.get("value_label") or ""))
        value.setStyleSheet(f"color:{GREEN_DARK}; font-size:12px; font-weight:900; border:none;")
        value.setFixedWidth(92)
        value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(swatch)
        layout.addWidget(name, 1)
        layout.addWidget(percent)
        layout.addWidget(value)
        return row

    # --- table --------------------------------------------------------------
    def _build_table(self) -> QFrame:
        wrapper = self._card()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(12, 12, 12, 12)
        self.table = _ReportTable()
        self.table.setColumnCount(len(self.service.columns))
        self.table.setHorizontalHeaderLabels([column.label for column in self.service.columns])
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(380)
        # Clean table: green header + outer frame; NO per-cell borders. Rows
        # alternate between two colors (white + light green) and the body text is
        # black, bold and centered (user choices 2026-08-15).
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ background:#FFFFFF; alternate-background-color:{_ROW_ALT}; "
            f"border:2px solid {GREEN}; border-radius:10px; font-size:14px; outline:0; }}"
            f"QHeaderView::section {{ background:#E7F3EA; color:{GREEN_DARK}; font-weight:900; "
            f"border:none; border-bottom:2px solid {GREEN}; padding:9px 8px; font-size:14px; }}"
            f"QTableWidget::item {{ border:none; padding:9px 8px; color:{_CELL_TEXT}; }}"
            "QTableWidget::item:selected { background:#CFE9D7; color:#0B3B23; }"
        )
        # Bold 14 cell font, inheriting the app's font family.
        self._cell_font = QFont(self.table.font())
        self._cell_font.setPointSize(14)
        self._cell_font.setBold(True)
        # Balanced widths: columns fill the viewport by fixed weights (see
        # _ReportTable), so nothing is cramped and no column leaves a big gap.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        for index in range(self.table.columnCount()):
            header.setSectionResizeMode(index, QHeaderView.Interactive)
        self.table.apply_widths()
        self.empty_label = QLabel(EMPTY_MESSAGE)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{_MUTED}; font-size:15px; font-weight:800; padding:18px; border:none;"
        )
        self.empty_label.setVisible(False)
        layout.addWidget(self.table)
        layout.addWidget(self.empty_label)
        return wrapper

    # --- filters popup ------------------------------------------------------
    def open_filters(self) -> None:
        dialog = SalesReportFilterDialog(self.service, self._filter_state(), parent=self)
        if dialog.exec():
            state = dialog.result_state()
            self._date_from = state["date_from"]
            self._date_to = state["date_to"]
            self._customer_id = state["customer_id"]
            self._customer_name = state["customer_name"]
            self._product_id = state["product_id"]
            self._product_name = state["product_name"]
            self.apply_filters()

    def _filter_state(self) -> dict[str, Any]:
        return {
            "date_from": self._date_from,
            "date_to": self._date_to,
            "customer_id": self._customer_id,
            "customer_name": self._customer_name,
            "product_id": self._product_id,
            "product_name": self._product_name,
        }

    # --- data flow ----------------------------------------------------------
    def _build_request(self) -> SalesReportRequest:
        return SalesReportRequest(
            customer_id=self._customer_id,
            product_id=self._product_id,
            date_from=self._date_from,
            date_to=self._date_to,
        )

    def apply_filters(self) -> None:
        try:
            result = self.service.fetch_report(self._build_request())
        except SalesReportValidationError as exc:
            QMessageBox.warning(self, "تحقق من الفلاتر", exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذر تحميل التقرير", str(exc))
            return
        self.current_result = result
        self._fill_table(result)
        self._fill_dashboard(result)
        self._update_period_label()
        self._update_summary()
        self.count_label.setText(f"عدد السطور: {len(result.export_rows):,}")

    def reset_filters(self) -> None:
        today = QDate.currentDate()
        self._date_from = QDate(today.year(), today.month(), 1).toString("yyyy-MM-dd")
        self._date_to = today.toString("yyyy-MM-dd")
        self._customer_id = None
        self._customer_name = ""
        self._product_id = None
        self._product_name = ""
        self.current_result = None
        self.table.setRowCount(0)
        self.table.setVisible(True)
        self.empty_label.setVisible(False)
        self._reset_dashboard()
        self._update_period_label()
        self._update_summary()
        self.count_label.setText("")

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
            "customer_label": self._customer_name or "الكل",
            "product_label": self._product_name or "الكل",
            "summary": result.summary,
            "export_rows": result.export_rows,
            "is_empty": result.is_empty,
            "empty_message": EMPTY_MESSAGE,
        }

    def open_preview(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل الطباعة.")
            return
        SalesReportPreviewDialog(data, parent=self).exec()

    def export_pdf(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل التصدير.")
            return
        export_report_to_pdf(self, data)

    def _fill_table(self, result) -> None:
        columns = result.columns
        rows = result.export_rows
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                value = row.get(column.key)
                item = QTableWidgetItem("" if value is None else str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFont(self._cell_font)
                self.table.setItem(row_index, column_index, item)
        self.table.apply_widths()
        self.empty_label.setVisible(result.is_empty)
        self.table.setVisible(not result.is_empty)

    def _fill_dashboard(self, result) -> None:
        summary = result.summary
        self.kpi_total["value"].setText(summary["total_sales_label"])
        self.kpi_total["sub"].setText("")
        self.kpi_customer["value"].setText(summary["top_customer_name"])
        self.kpi_customer["sub"].setText(
            summary["top_customer_value_label"]
            if summary["top_customer_name"] != "—" else ""
        )
        self.kpi_item["value"].setText(summary["top_item_name"])
        self.kpi_item["sub"].setText(
            f"{summary['top_item_quantity_label']} (الكمية)"
            if summary["top_item_name"] != "—" else ""
        )
        top = result.top_customers
        center_total = sum((item["value"] for item in top), start=_decimal_zero())
        self.donut.set_data(top, f"{center_total:,.0f}" if top else "0", "إجمالي أكبر ٥")
        self._render_legend(top)

    def _reset_dashboard(self) -> None:
        for card in (self.kpi_total, self.kpi_customer, self.kpi_item):
            card["value"].setText("—")
            card["sub"].setText("")
        self.donut.set_data([], "0", "إجمالي أكبر ٥")
        self._render_legend([])

    def _update_period_label(self) -> None:
        self.period_label.setText(f"الفترة: من {self._date_from} إلى {self._date_to}")

    def _update_summary(self) -> None:
        parts = [f"الفترة: {self._date_from} — {self._date_to}"]
        parts.append(f"العميل: {self._customer_name}" if self._customer_name else "كل العملاء")
        parts.append(f"الصنف: {self._product_name}" if self._product_name else "كل الأصناف")
        self.summary_label.setText("  •  ".join(parts))

    # --- small helpers ------------------------------------------------------
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


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal_zero():
    from decimal import Decimal

    return Decimal("0")


__all__ = [
    "SalesReportScreen",
    "SalesReportFilterDialog",
    "TopCustomersDonut",
    "REPORT_TITLE",
]
