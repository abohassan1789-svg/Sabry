"""Purchase report screen (تقرير المشتريات) — the "النموذج ١" design.

Pure UI: it builds the RTL layout, gathers the filter values and renders what
``PurchaseReportService`` returns. It never touches SQL — every value comes from
the service, which calls the repository. The report is strictly read-only.

Design (chosen by the user from ten mock-ups, 2026-08-15; data rebuilt on the
simplified purchase invoice, 2026-08-20):
* an inline **filter bar** at the top (date range + supplier-name + item-name
  text searches + a طريقة الدفع dropdown [الكل / نقدي / آجل] + بحث / مسح),
* a compact dark-green **hero** header carrying four small dashboard cards
  (إجمالي المشتريات · عدد الفواتير · عدد الأصناف · أكبر مورد),
* two **donut** charts side by side (أعلى ٥ موردين + توزيع طرق الدفع),
* a details table with the eight required columns matching the invoice.

Preview / print / PDF export are wired through ``purchase_report_print`` (the
Model-3 "green banner" sheet with the company letterhead); the letterhead and
banner are print/PDF only and never render on this screen.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import QDate, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
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

from app.services.purchase_report_service import (
    EMPTY_MESSAGE,
    PAYMENT_CASH,
    PAYMENT_CREDIT,
    PAYMENT_LABEL_CASH,
    PAYMENT_LABEL_CREDIT,
    PurchaseReportRequest,
    PurchaseReportService,
    PurchaseReportValidationError,
)
from app.ui.common.theme import GREEN, GREEN_DARK, _button_style
from app.ui.dialogs.saudi_invoice_dialogs import EntityPickerDialog
from app.ui.screens.purchase_report_print import (
    PurchaseReportPreviewDialog,
    export_report_to_pdf,
)

REPORT_TITLE = "تقرير المشتريات"

_PICKER_LIMIT = 500

# Five green shades (darkest = biggest slice) for the suppliers donut + legend.
DONUT_GREENS = ("#0B5326", "#0F6B30", "#137A38", "#2E9E57", "#62C888")
# Payment-type donut: نقدي vs آجل (+ a muted grey for غير محدد, if present).
PAYMENT_COLORS = {
    PAYMENT_LABEL_CASH: "#0F6B30",
    PAYMENT_LABEL_CREDIT: "#62C888",
}
PAYMENT_FALLBACK = "#9CB3A2"

_TEXT = "#0F1C14"
_MUTED = "#6B7A6F"
_LINE = "#E1E9E1"
_CELL_TEXT = "#000000"
_ROW_ALT = "#E6F4EA"
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


class _PickerLineEdit(QLineEdit):
    """An editable text field that also opens a picker on double-click.

    Typing still works (the value is used as a contains-search); double-clicking
    emits ``doubleClicked`` so the screen can pop up the supplier / item picker.
    """

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: ANN401 - Qt event
        self.doubleClicked.emit()


def _text_field(placeholder: str) -> _PickerLineEdit:
    field = _PickerLineEdit()
    field.setPlaceholderText(placeholder)
    field.setClearButtonEnabled(True)
    field.setMinimumHeight(34)
    field.setToolTip("دبل-كليك لفتح قائمة الاختيار، أو اكتب للبحث")
    field.setStyleSheet(
        "QLineEdit { background:#FFFFFF; border:1px solid #CBD5C9; border-radius:7px; "
        "padding:5px 9px; color:#0F1C14; }"
        f"QLineEdit:focus {{ border:1px solid {GREEN}; }}"
    )
    return field


def _payment_combo() -> QComboBox:
    combo = QComboBox()
    # userData carries the stored code; "الكل" means no restriction.
    combo.addItem("الكل", None)
    combo.addItem(PAYMENT_LABEL_CASH, PAYMENT_CASH)
    combo.addItem(PAYMENT_LABEL_CREDIT, PAYMENT_CREDIT)
    combo.setMinimumHeight(34)
    combo.setCursor(Qt.PointingHandCursor)
    combo.setStyleSheet(
        "QComboBox { background:#FFFFFF; border:1px solid #CBD5C9; border-radius:7px; "
        "padding:5px 9px; color:#0F1C14; font-weight:700; }"
        f"QComboBox:focus {{ border:1px solid {GREEN}; }}"
        "QComboBox QAbstractItemView { background:#FFFFFF; color:#0F1C14; "
        f"selection-background-color:{GREEN}; selection-color:#FFFFFF; }}"
    )
    return combo


def _labeled(label: str, widget: QWidget, stretch: int = 1) -> QWidget:
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


class _ReportTable(QTableWidget):
    """Details table whose eight columns fill the width proportionally.

    Fixed per-column weights keep the layout balanced (the two name columns get
    the most room; the numeric columns stay compact) and always fill the viewport
    — no single stretched column leaving a big empty gap. Recomputed on resize.
    Weights map to the 8 columns: date, invoice#, supplier, item, unit, quantity,
    price, total.
    """

    _WEIGHTS = (1.15, 1.15, 1.9, 2.0, 0.8, 0.9, 1.0, 1.25)

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


class DonutChart(QWidget):
    """A compact donut drawn from (value, color) slices with a center caption."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slices: list[tuple[float, str]] = []
        self._center_value = ""
        self._center_caption = ""
        self.setMinimumSize(128, 128)
        self.setMaximumSize(150, 150)

    def set_slices(
        self, slices: list[tuple[float, str]], center_value: str, center_caption: str
    ) -> None:
        self._slices = [(float(value or 0), color) for value, color in slices]
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

        hole_r = rect.width() * 0.32
        center = rect.center()
        hole = QRectF(center.x() - hole_r, center.y() - hole_r, hole_r * 2, hole_r * 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(hole)

        painter.setPen(QColor(GREEN_DARK))
        value_font = self.font()
        value_font.setPointSize(10)
        value_font.setBold(True)
        painter.setFont(value_font)
        value_rect = QRectF(hole.left(), hole.top() + hole.height() * 0.16, hole.width(), hole.height() * 0.46)
        painter.drawText(value_rect, Qt.AlignCenter, self._center_value)
        painter.setPen(QColor(_MUTED))
        caption_font = self.font()
        caption_font.setPointSize(7)
        caption_font.setBold(True)
        painter.setFont(caption_font)
        caption_rect = QRectF(hole.left(), hole.top() + hole.height() * 0.55, hole.width(), hole.height() * 0.30)
        painter.drawText(caption_rect, Qt.AlignCenter, self._center_caption)


class PurchaseReportScreen(QWidget):
    """RTL read-only purchase report (approved purchase-invoice lines + KPIs)."""

    def __init__(
        self, service: PurchaseReportService | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service or PurchaseReportService()
        today = QDate.currentDate()
        self._default_from = QDate(today.year(), today.month(), 1).toString("yyyy-MM-dd")
        self._default_to = today.toString("yyyy-MM-dd")
        self.current_result = None
        # Letterhead is print/PDF only — fetched here, rendered only on the sheet.
        # Guarded so a test double without the selector can't break the screen.
        try:
            self._company = self.service.company_letterhead()
        except Exception:  # noqa: BLE001
            self._company = None
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1300, 840)
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
        layout.setSpacing(10)
        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_charts())
        layout.addWidget(self._section_title("تفاصيل المشتريات"))
        layout.addWidget(self._build_table(), 1)
        scroll.setWidget(content)

    # --- inline filter bar --------------------------------------------------
    def _build_filter_bar(self) -> QFrame:
        bar = self._card()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        self.from_date = _date_edit(self._default_from)
        self.to_date = _date_edit(self._default_to)
        self.supplier_field = _text_field("كل الموردين — دبل-كليك للاختيار")
        self.item_field = _text_field("كل الأصناف — دبل-كليك للاختيار")
        self.payment_combo = _payment_combo()
        # Double-click either name field to open a searchable picker.
        self.supplier_field.doubleClicked.connect(self._pick_supplier)
        self.item_field.doubleClicked.connect(self._pick_item)

        layout.addWidget(_labeled("من تاريخ", self.from_date), 1)
        layout.addWidget(_labeled("إلى تاريخ", self.to_date), 1)
        layout.addWidget(_labeled("اسم المورد", self.supplier_field), 2)
        layout.addWidget(_labeled("اسم الصنف", self.item_field), 2)
        layout.addWidget(_labeled("طريقة الدفع", self.payment_combo), 1)

        search_button = QPushButton("🔎 بحث")
        search_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
        search_button.setMinimumHeight(34)
        search_button.setMinimumWidth(96)
        search_button.setCursor(Qt.PointingHandCursor)
        search_button.clicked.connect(self.apply_filters)

        reset_button = QPushButton("مسح")
        reset_button.setStyleSheet(_button_style("#6B7280", "#4B5563"))
        reset_button.setMinimumHeight(34)
        reset_button.setCursor(Qt.PointingHandCursor)
        reset_button.clicked.connect(self.reset_filters)

        preview_button = QPushButton("🖨️ معاينة / طباعة")
        preview_button.setStyleSheet(_button_style("#1D4ED8", "#1E40AF"))
        preview_button.setMinimumHeight(34)
        preview_button.setCursor(Qt.PointingHandCursor)
        preview_button.clicked.connect(self.open_preview)

        pdf_button = QPushButton("⬇️ PDF")
        pdf_button.setStyleSheet(_button_style("#B91C1C", "#991B1B"))
        pdf_button.setMinimumHeight(34)
        pdf_button.setCursor(Qt.PointingHandCursor)
        pdf_button.clicked.connect(self.export_pdf)

        # Buttons sit at the bottom so they line up with the input fields (which
        # each carry a label above them), with no empty placeholder box.
        buttons = QVBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(0)
        buttons.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(search_button)
        row.addWidget(reset_button)
        row.addWidget(preview_button)
        row.addWidget(pdf_button)
        buttons.addLayout(row)
        buttons_box = QWidget()
        buttons_box.setStyleSheet("background:transparent;")
        buttons_box.setLayout(buttons)
        layout.addWidget(buttons_box)

        # Enter in a text field triggers the search.
        self.supplier_field.returnPressed.connect(self.apply_filters)
        self.item_field.returnPressed.connect(self.apply_filters)
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
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(9)

        top = QHBoxLayout()
        title = QLabel(f"📊 {REPORT_TITLE}")
        title.setStyleSheet("font-size:16px; font-weight:900;")
        top.addWidget(title)
        top.addStretch(1)
        self.period_label = QLabel("")
        self.period_label.setStyleSheet("font-size:11px; font-weight:700; color:#BFE3CB;")
        top.addWidget(self.period_label)
        box.addLayout(top)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.kpi_total = self._kpi_card("💰 إجمالي المشتريات")
        self.kpi_invoices = self._kpi_card("🧾 عدد الفواتير")
        self.kpi_items = self._kpi_card("📦 عدد الأصناف")
        self.kpi_top_supplier = self._kpi_card("🏆 أكبر مورد")
        for card in (self.kpi_total, self.kpi_invoices,
                     self.kpi_items, self.kpi_top_supplier):
            cards.addWidget(card["frame"], 1)
        box.addLayout(cards)
        self._update_period_label(self._default_from, self._default_to)
        return hero

    def _kpi_card(self, title: str) -> dict[str, Any]:
        # Compact cards (smaller than the sales report's, per user request).
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.22); "
            "border-radius:10px; }"
            "QLabel { background:transparent; color:#FFFFFF; border:none; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(11, 8, 11, 8)
        layout.setSpacing(2)
        caption = QLabel(title)
        caption.setStyleSheet("font-size:10.5px; font-weight:800; color:#CDE9D6;")
        value = QLabel("—")
        value.setStyleSheet("font-size:16px; font-weight:900;")
        value.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(value)
        return {"frame": frame, "value": value}

    # --- two donut charts ---------------------------------------------------
    def _build_charts(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background:transparent;")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        supplier_card, self.supplier_donut, self.supplier_legend = self._chart_card(
            "أكبر ٥ موردين (حسب الإجمالي)"
        )
        payment_card, self.payment_donut, self.payment_legend = self._chart_card(
            "توزيع طرق الدفع (حسب الإجمالي)"
        )
        row.addWidget(supplier_card, 1)
        row.addWidget(payment_card, 1)
        self._render_legend(self.supplier_legend, [])
        self._render_legend(self.payment_legend, [])
        return wrap

    def _chart_card(self, title: str) -> tuple[QFrame, DonutChart, QVBoxLayout]:
        card = self._card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(6)
        heading = QLabel(title)
        heading.setStyleSheet(f"color:{_TEXT}; font-size:13px; font-weight:900; border:none;")
        outer.addWidget(heading)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        donut = DonutChart()
        row.addWidget(donut, 0, Qt.AlignVCenter)
        legend_box = QVBoxLayout()
        legend_box.setSpacing(0)
        legend_wrap = QVBoxLayout()
        legend_wrap.addLayout(legend_box)
        legend_wrap.addStretch(1)
        row.addLayout(legend_wrap, 1)
        outer.addLayout(row)
        return card, donut, legend_box

    def _render_legend(self, legend_box: QVBoxLayout, items: list[dict[str, Any]]) -> None:
        while legend_box.count():
            item = legend_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not items:
            empty = QLabel("لا توجد بيانات لعرضها")
            empty.setStyleSheet(f"color:{_MUTED}; font-size:12px; font-weight:700; border:none; padding:4px 0;")
            legend_box.addWidget(empty)
            return
        for item in items:
            legend_box.addWidget(self._legend_row(item))

    def _legend_row(self, item: dict[str, Any]) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(9)
        swatch = QLabel()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet(f"background:{item['color']}; border-radius:3px;")
        name = QLabel(str(item.get("label") or ""))
        name.setStyleSheet(f"color:{_TEXT}; font-size:12px; font-weight:800; border:none;")
        name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        percent = QLabel(f"{item.get('share', 0):g}%")
        percent.setStyleSheet(f"color:{_MUTED}; font-size:11px; font-weight:800; border:none;")
        percent.setFixedWidth(48)
        percent.setAlignment(Qt.AlignCenter)
        value = QLabel(str(item.get("value_label") or ""))
        value.setStyleSheet(f"color:{GREEN_DARK}; font-size:12px; font-weight:900; border:none;")
        value.setFixedWidth(96)
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
        self.table.setHorizontalHeaderLabels([c.label for c in self.service.columns])
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(360)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ background:#FFFFFF; alternate-background-color:{_ROW_ALT}; "
            f"border:2px solid {GREEN}; border-radius:10px; font-size:13px; outline:0; }}"
            f"QHeaderView::section {{ background:#E7F3EA; color:{GREEN_DARK}; font-weight:900; "
            f"border:none; border-bottom:2px solid {GREEN}; padding:9px 6px; font-size:13px; }}"
            f"QTableWidget::item {{ border:none; padding:8px 6px; color:{_CELL_TEXT}; }}"
            "QTableWidget::item:selected { background:#CFE9D7; color:#0B3B23; }"
        )
        self._cell_font = QFont(self.table.font())
        self._cell_font.setPointSize(13)
        self._cell_font.setBold(True)
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

    # --- pickers (double-click on the name fields) --------------------------
    def _pick_supplier(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن مورد",
            (("supplier_id", "الكود"), ("supplier_name", "اسم المورد"),
             ("account_type", "نوع الحساب"), ("mobile", "الموبايل")),
            self.service.search_suppliers,
            "supplier_id",
            parent=self,
            limit=_PICKER_LIMIT,
        )
        if dialog.exec() and dialog.selected is not None:
            name = str(dialog.selected.get("supplier_name") or "").strip()
            self.supplier_field.setText(name)

    def _pick_item(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن صنف",
            (("item_name", "اسم الصنف"), ("usage_count", "عدد مرات الاستخدام")),
            self.service.search_items,
            "item_name",
            parent=self,
            limit=_PICKER_LIMIT,
        )
        if dialog.exec() and dialog.selected is not None:
            name = str(dialog.selected.get("item_name") or "").strip()
            self.item_field.setText(name)

    # --- data flow ----------------------------------------------------------
    def _build_request(self) -> PurchaseReportRequest:
        return PurchaseReportRequest(
            date_from=self.from_date.date().toString("yyyy-MM-dd"),
            date_to=self.to_date.date().toString("yyyy-MM-dd"),
            supplier_name=self.supplier_field.text().strip() or None,
            item_name=self.item_field.text().strip() or None,
            payment_type=self.payment_combo.currentData(),
        )

    def apply_filters(self) -> None:
        try:
            result = self.service.fetch_report(self._build_request())
        except PurchaseReportValidationError as exc:
            QMessageBox.warning(self, "تحقق من الفلاتر", exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذر تحميل التقرير", str(exc))
            return
        self.current_result = result
        self._fill_table(result)
        self._fill_dashboard(result)
        self._update_period_label(
            self.from_date.date().toString("yyyy-MM-dd"),
            self.to_date.date().toString("yyyy-MM-dd"),
        )

    def reset_filters(self) -> None:
        self.from_date.setDate(QDate.fromString(self._default_from, "yyyy-MM-dd"))
        self.to_date.setDate(QDate.fromString(self._default_to, "yyyy-MM-dd"))
        self.supplier_field.clear()
        self.item_field.clear()
        self.payment_combo.setCurrentIndex(0)
        self.current_result = None
        self.table.setRowCount(0)
        self.table.setVisible(True)
        self.empty_label.setVisible(False)
        self._reset_dashboard()
        self._update_period_label(self._default_from, self._default_to)

    # --- print / preview / PDF ---------------------------------------------
    def _print_data(self) -> dict[str, Any] | None:
        if self.current_result is None:
            return None
        result = self.current_result
        return {
            "company": self._company,
            "title": REPORT_TITLE,
            "date_from_label": self.from_date.date().toString("yyyy-MM-dd"),
            "date_to_label": self.to_date.date().toString("yyyy-MM-dd"),
            "payment_type_label": self.payment_combo.currentText(),
            "summary": result.summary,
            "export_rows": result.export_rows,
            "payment_breakdown": result.payment_breakdown,
            "is_empty": result.is_empty,
            "empty_message": EMPTY_MESSAGE,
        }

    def open_preview(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل الطباعة.")
            return
        PurchaseReportPreviewDialog(data, parent=self).exec()

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
        self.kpi_total["value"].setText(summary["total_count_price_label"])
        self.kpi_invoices["value"].setText(summary["invoice_count_label"])
        self.kpi_items["value"].setText(summary["line_count_label"])
        self.kpi_top_supplier["value"].setText(
            f"{summary['top_supplier_name']}\n{summary['top_supplier_value_label']}"
        )

        suppliers = self._colorize(result.top_suppliers, self._supplier_color)
        self.supplier_donut.set_slices(
            [(item["value"], item["color"]) for item in suppliers],
            self._donut_center(result.top_suppliers), "إجمالي أكبر ٥",
        )
        self._render_legend(self.supplier_legend, suppliers)

        payments = self._colorize(result.payment_breakdown, self._payment_color)
        self.payment_donut.set_slices(
            [(item["value"], item["color"]) for item in payments],
            self._donut_center(result.payment_breakdown), "الإجمالي",
        )
        self._render_legend(self.payment_legend, payments)

    def _reset_dashboard(self) -> None:
        for card in (self.kpi_total, self.kpi_invoices,
                     self.kpi_items, self.kpi_top_supplier):
            card["value"].setText("—")
        self.supplier_donut.set_slices([], "0", "إجمالي أكبر ٥")
        self.payment_donut.set_slices([], "0", "الإجمالي")
        self._render_legend(self.supplier_legend, [])
        self._render_legend(self.payment_legend, [])

    # --- chart colouring helpers -------------------------------------------
    @staticmethod
    def _colorize(items: list[dict[str, Any]], colorer) -> list[dict[str, Any]]:
        out = []
        for index, item in enumerate(items):
            out.append({**item, "color": colorer(index, item)})
        return out

    @staticmethod
    def _supplier_color(index: int, _item: dict[str, Any]) -> str:
        return DONUT_GREENS[index % len(DONUT_GREENS)]

    @staticmethod
    def _payment_color(index: int, item: dict[str, Any]) -> str:
        return PAYMENT_COLORS.get(item.get("label"), PAYMENT_FALLBACK)

    @staticmethod
    def _donut_center(items: list[dict[str, Any]]) -> str:
        total = sum((item["value"] for item in items), start=Decimal("0"))
        return f"{total:,.0f}" if items else "0"

    # --- small helpers ------------------------------------------------------
    def _update_period_label(self, date_from: str, date_to: str) -> None:
        self.period_label.setText(f"الفترة: من {date_from} إلى {date_to}")

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


__all__ = ["PurchaseReportScreen", "DonutChart", "REPORT_TITLE"]
