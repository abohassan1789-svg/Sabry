"""Production Orders Report screen — تقرير أوامر الإنتاج ("النموذج الثاني": Dashboard-first).

Pure UI: it builds the RTL layout, gathers the filter values and renders what
``ProductionOrderReportService`` returns. It never touches SQL — every value
comes from the service, which calls the read-only repository.

Design (chosen by the user from ten mock-ups, 2026-08-19): dashboard-first —
a compact dark-green **hero** carrying the KPI cards, a row of **donut** charts
(production by finished product · raw-material share · expected-vs-actual), then
an **expandable** orders table (one row per production order; expand to see its
material lines). The company **letterhead** (Arabic right · logo centre · English
left, from the first registered company) is NOT shown on-screen — it belongs to
the printed report only (معاينة / طباعة / تصدير PDF, via the shared Chromium
print path).

The «اسم الصنف» filter searches BOTH finished products and raw materials; a
segmented toggle (منتج تام / مادة خام) tells the report which side to match —
the finished product on the order header, or a raw material in its lines.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.production_order_report_service import (
    EMPTY_MESSAGE,
    ProductionReportRequest,
    ProductionReportValidationError,
    ProductionOrderReportService,
    ROLE_FINISHED,
    ROLE_RAW,
)
from app.ui.common.report_charts import DashboardDonutChart
from app.ui.common.theme import GREEN, GREEN_DARK, _button_style
from app.ui.dialogs.saudi_invoice_dialogs import EntityPickerDialog
from app.ui.screens.production_order_report_print import (
    ProductionReportPreviewDialog,
    export_report_to_pdf,
)

REPORT_TITLE = "تقرير أوامر الإنتاج"

_PICKER_LIMIT = 500
_TEXT = "#0F1C14"
_MUTED = "#6B7A6F"
_LINE = "#E1E9E1"
_ROW_ALT = "#E6F4EA"
_POS = "#047857"
_NEG = "#B91C1C"
_ZERO = "#6B7280"
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

# Order (parent) tree columns; material (child) rows map into the same columns.
COL_ORDER, COL_DATE, COL_PRODUCT, COL_PLANNED, COL_MATS, COL_EXP, COL_ACT, COL_DEV = range(8)


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


def _picker_field(placeholder: str, on_click) -> tuple[QLineEdit, QWidget]:
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


class ProductionReportFilterDialog(QDialog):
    """Popup with the report filters: date range + item (finished/raw toggle)."""

    def __init__(self, service: Any, state: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._item_id = state.get("item_id")
        self._item_name = state.get("item_name") or ""
        self._item_role = state.get("item_role") or ROLE_FINISHED

        self.setWindowTitle("الفلترة والبحث — تقرير أوامر الإنتاج")
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
        dates = QHBoxLayout()
        dates.setSpacing(12)
        dates.addWidget(_labeled("من تاريخ", self.from_date), 1)
        dates.addWidget(_labeled("إلى تاريخ", self.to_date), 1)
        root.addLayout(dates)

        # Segmented role toggle: which side does «اسم الصنف» match?
        self.finished_button = self._toggle_button("منتج تام", ROLE_FINISHED)
        self.raw_button = self._toggle_button("مادة خام", ROLE_RAW)
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(0)
        toggle_row.addWidget(self.finished_button)
        toggle_row.addWidget(self.raw_button)
        toggle_row.addStretch(1)
        root.addWidget(_labeled("نوع البحث في الصنف", self._wrap(toggle_row)))

        self.item_field, item_widget = _picker_field("اختر صنفًا…", self._pick_item)
        self.item_field.setText(self._item_name)
        root.addWidget(_labeled("اسم الصنف (منتج تام أو مادة خام)", item_widget))
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

    def _toggle_button(self, text: str, role: str) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setMinimumHeight(34)
        button.setMinimumWidth(110)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _c=False, r=role: self._set_role(r))
        return button

    def _set_role(self, role: str) -> None:
        # Switching the role invalidates the previously-picked item (it belongs to
        # the other side): clear it so the user re-picks from the right list.
        if role != self._item_role:
            self._item_role = role
            self._item_id = None
            self._item_name = ""
            self.item_field.clear()
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
        is_finished = self._item_role == ROLE_FINISHED
        self.finished_button.setChecked(is_finished)
        self.raw_button.setChecked(not is_finished)
        self.finished_button.setStyleSheet(on if is_finished else off)
        self.raw_button.setStyleSheet(on if not is_finished else off)

    def _pick_item(self) -> None:
        title = "بحث عن منتج تام" if self._item_role == ROLE_FINISHED else "بحث عن مادة خام"
        dialog = EntityPickerDialog(
            title,
            (("item_code", "الكود"), ("item_name", "اسم الصنف"),
             ("unit", "الوحدة"), ("item_type", "النوع")),
            self.service.search_products,
            "id",
            parent=self,
            limit=_PICKER_LIMIT,
        )
        if dialog.exec() and dialog.selected is not None:
            self._item_id = _as_int(dialog.selected.get("id"))
            self._item_name = str(dialog.selected.get("item_name") or "")
            self.item_field.setText(self._item_name)

    def _clear(self) -> None:
        self._item_id = None
        self._item_name = ""
        self.item_field.clear()

    def result_state(self) -> dict[str, Any]:
        return {
            "date_from": self.from_date.date().toString("yyyy-MM-dd"),
            "date_to": self.to_date.date().toString("yyyy-MM-dd"),
            "item_id": self._item_id,
            "item_name": self._item_name,
            "item_role": self._item_role,
        }


class _ReportDonut(DashboardDonutChart):
    """Donut panel with a report-appropriate summary line.

    The shared ``DashboardDonutChart`` hard-codes the caption «أحدث حالة لكل عميل»
    (it came from the status-analysis screen). Here the slices are quantities, so
    the caption is replaced with a neutral total.
    """

    summary_suffix = ""

    def build_rows(self) -> None:
        super().build_rows()
        if self._rows:
            total = sum(int(row["count"]) for row in self._rows)
            suffix = f" | {self.summary_suffix}" if self.summary_suffix else ""
            self._summary.setText(f"الإجمالي: {total:,}{suffix}")


class ExpectedActualPanel(QFrame):
    """A compact 'expected vs actual' comparison: two proportional bars + net."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartPanel")
        self.setMinimumHeight(210)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(
            f"QFrame#chartPanel {{ background:#FFFFFF; border:1px solid {_LINE}; border-radius:10px; }}"
        )
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(10)
        title = QLabel("المتوقع مقابل الفعلي (خام)")
        title.setAlignment(Qt.AlignRight)
        title.setStyleSheet(f"color:{_TEXT}; font-size:15px; font-weight:900;")
        box.addWidget(title)
        self._expected_bar, self._expected_val = self._bar_row("المتوقع", "#93C5A9")
        self._actual_bar, self._actual_val = self._bar_row("الفعلي", GREEN)
        box.addWidget(self._expected_bar)
        box.addWidget(self._actual_bar)
        self._net = QLabel("")
        self._net.setAlignment(Qt.AlignRight)
        self._net.setStyleSheet(f"color:{_MUTED}; font-size:13px; font-weight:900;")
        box.addWidget(self._net)
        box.addStretch(1)
        self._rows = {"expected": self._expected_fill, "actual": self._actual_fill}

    def _bar_row(self, name: str, color: str) -> tuple[QWidget, QLabel]:
        row = QWidget()
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        top = QHBoxLayout()
        label = QLabel(name)
        label.setStyleSheet(f"color:{_TEXT}; font-size:12.5px; font-weight:800;")
        value = QLabel("0")
        value.setStyleSheet(f"color:{GREEN_DARK}; font-size:12.5px; font-weight:900;")
        top.addWidget(label)
        top.addStretch(1)
        top.addWidget(value)
        v.addLayout(top)
        track = QFrame()
        track.setFixedHeight(16)
        track.setStyleSheet("background:#E2E8F0; border:none; border-radius:8px;")
        track_l = QHBoxLayout(track)
        track_l.setContentsMargins(0, 0, 0, 0)
        track_l.setSpacing(0)
        fill = QFrame()
        fill.setStyleSheet(f"background:{color}; border:none; border-radius:8px;")
        track_l.addWidget(fill, 0)
        track_l.addStretch(1000)
        row._fill = fill  # type: ignore[attr-defined]
        row._track_layout = track_l  # type: ignore[attr-defined]
        v.addWidget(track)
        if name == "المتوقع":
            self._expected_fill = (fill, track_l)
        else:
            self._actual_fill = (fill, track_l)
        return row, value

    def set_data(self, expected: float, actual: float, expected_label: str,
                 actual_label: str, deviation_label: str) -> None:
        peak = max(expected, actual, 1.0)
        for (fill, track_l), value in (
            (self._expected_fill, expected), (self._actual_fill, actual)
        ):
            units = max(0, min(1000, int(round(value / peak * 1000))))
            track_l.setStretch(0, units)
            track_l.setStretch(1, 1000 - units)
        self._expected_val.setText(expected_label)
        self._actual_val.setText(actual_label)
        self._net.setText(f"صافي الانحراف: {deviation_label}")

    def clear(self) -> None:
        self.set_data(0, 0, "0", "0", "0")


class ProductionOrderReportScreen(QWidget):
    """RTL read-only production-orders report (dashboard-first + expandable table)."""

    def __init__(
        self, service: ProductionOrderReportService | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service or ProductionOrderReportService()
        today = QDate.currentDate()
        self._date_from = QDate(today.year(), today.month(), 1).toString("yyyy-MM-dd")
        self._date_to = today.toString("yyyy-MM-dd")
        self._item_id: int | None = None
        self._item_name = ""
        self._item_role = ROLE_FINISHED
        self.current_result = None
        self._company = self.service.company_letterhead()
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1320, 860)
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
        layout.setSpacing(9)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_charts())
        layout.addWidget(self._section_title("تفاصيل أوامر الإنتاج (اضغط السهم لعرض المواد)"))
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

    # --- hero + KPI cards ---------------------------------------------------
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
        title = QLabel(f"🏭 {REPORT_TITLE}")
        title.setStyleSheet("font-size:17px; font-weight:900;")
        top.addWidget(title)
        top.addStretch(1)
        self.period_label = QLabel("")
        self.period_label.setStyleSheet("font-size:11.5px; font-weight:700; color:#BFE3CB;")
        top.addWidget(self.period_label)
        box.addLayout(top)

        cards = QHBoxLayout()
        cards.setSpacing(9)
        # (attr, caption)
        self._kpis = {
            "total_orders": self._kpi_card("📦 أوامر الإنتاج"),
            "total_planned": self._kpi_card("🎯 الكمية المخططة"),
            "finished_products": self._kpi_card("🏷️ المنتجات التامة"),
            "raw_materials": self._kpi_card("🧱 المواد الخام"),
            "total_expected": self._kpi_card("📐 إجمالي المتوقع"),
            "total_actual": self._kpi_card("⚙️ إجمالي الفعلي"),
            "deviation": self._kpi_card("📊 صافي الانحراف"),
        }
        for card in self._kpis.values():
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
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        caption = QLabel(title)
        caption.setStyleSheet("font-size:11px; font-weight:800; color:#CDE9D6;")
        caption.setWordWrap(True)
        value = QLabel("—")
        value.setStyleSheet("font-size:20px; font-weight:900;")
        sub = QLabel("")
        sub.setStyleSheet("font-size:11px; font-weight:800; color:#BFE3CB;")
        layout.addWidget(caption)
        layout.addWidget(value)
        layout.addWidget(sub)
        return {"frame": frame, "value": value, "sub": sub}

    # --- charts row ---------------------------------------------------------
    def _build_charts(self) -> QWidget:
        section = QWidget()
        section.setStyleSheet("background:transparent;")
        row = QHBoxLayout(section)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.product_donut = _ReportDonut(
            "توزيع الإنتاج حسب المنتج التام", "label", GREEN, max_bars=6, min_height=210
        )
        self.product_donut.summary_suffix = "إجمالي الكمية المخططة"
        self.material_donut = _ReportDonut(
            "حصة المواد الخام (الكمية الفعلية)", "label", "#2563EB", max_bars=6, min_height=210
        )
        self.material_donut.summary_suffix = "إجمالي الكمية الفعلية"
        self.expected_actual = ExpectedActualPanel()
        row.addWidget(self.product_donut, 1)
        row.addWidget(self.material_donut, 1)
        row.addWidget(self.expected_actual, 1)
        return section

    # --- expandable orders table (tree) -------------------------------------
    def _build_table(self) -> QFrame:
        wrapper = self._card()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(12, 12, 12, 12)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels([
            "رقم الأمر", "التاريخ", "المنتج التام", "الكمية المخططة",
            "عدد المواد", "إجمالي المتوقع", "إجمالي الفعلي", "الانحراف",
        ])
        self.tree.setLayoutDirection(Qt.RightToLeft)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setUniformRowHeights(False)
        self.tree.setMinimumHeight(440)
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background:#FFFFFF; alternate-background-color:{_ROW_ALT}; "
            f"border:2px solid {GREEN}; border-radius:10px; font-size:13px; outline:0; }}"
            f"QHeaderView::section {{ background:#E7F3EA; color:{GREEN_DARK}; font-weight:900; "
            f"border:none; border-bottom:2px solid {GREEN}; padding:8px 6px; font-size:13px; }}"
            "QTreeWidget::item { padding:6px 4px; color:#000000; }"
            "QTreeWidget::item:selected { background:#CFE9D7; color:#0B3B23; }"
        )
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.resizeSection(COL_ORDER, 110)
        header.resizeSection(COL_DATE, 100)
        header.resizeSection(COL_PRODUCT, 240)
        header.resizeSection(COL_PLANNED, 120)
        header.resizeSection(COL_MATS, 90)
        header.resizeSection(COL_EXP, 120)
        header.resizeSection(COL_ACT, 120)

        self._bold_font = QFont(self.tree.font())
        self._bold_font.setBold(True)

        self.empty_label = QLabel(EMPTY_MESSAGE)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{_MUTED}; font-size:15px; font-weight:800; padding:18px; border:none;"
        )
        self.empty_label.setVisible(False)
        layout.addWidget(self.tree)
        layout.addWidget(self.empty_label)
        return wrapper

    # --- filters popup ------------------------------------------------------
    def open_filters(self) -> None:
        dialog = ProductionReportFilterDialog(self.service, self._filter_state(), parent=self)
        if dialog.exec():
            state = dialog.result_state()
            self._date_from = state["date_from"]
            self._date_to = state["date_to"]
            self._item_id = state["item_id"]
            self._item_name = state["item_name"]
            self._item_role = state["item_role"]
            self.apply_filters()

    def _filter_state(self) -> dict[str, Any]:
        return {
            "date_from": self._date_from,
            "date_to": self._date_to,
            "item_id": self._item_id,
            "item_name": self._item_name,
            "item_role": self._item_role,
        }

    # --- data flow ----------------------------------------------------------
    def _build_request(self) -> ProductionReportRequest:
        return ProductionReportRequest(
            date_from=self._date_from,
            date_to=self._date_to,
            item_id=self._item_id,
            item_role=self._item_role,
        )

    def apply_filters(self) -> None:
        try:
            result = self.service.fetch_report(self._build_request())
        except ProductionReportValidationError as exc:
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
        self.count_label.setText(f"عدد الأوامر: {len(result.orders):,}")

    def reset_filters(self) -> None:
        today = QDate.currentDate()
        self._date_from = QDate(today.year(), today.month(), 1).toString("yyyy-MM-dd")
        self._date_to = today.toString("yyyy-MM-dd")
        self._item_id = None
        self._item_name = ""
        self._item_role = ROLE_FINISHED
        self.apply_filters()

    def _fill_table(self, result) -> None:
        self.tree.clear()
        for order in result.export_orders:
            parent = QTreeWidgetItem([
                order.get("order_number", ""),
                order.get("order_date", ""),
                order.get("product_name", ""),
                order.get("production_quantity", ""),
                order.get("material_count", ""),
                order.get("total_expected", ""),
                order.get("total_actual", ""),
                order.get("total_deviation", ""),
            ])
            for col in range(8):
                parent.setFont(col, self._bold_font)
                if col != COL_PRODUCT:
                    parent.setTextAlignment(col, Qt.AlignCenter)
            parent.setForeground(COL_DEV, QColor(self._sign_color(order.get("deviation_sign"))))
            # Material child rows mapped into the shared columns.
            for line in result.lines_by_order.get(order.get("id"), []):
                child = QTreeWidgetItem([
                    line.get("item_code", ""),
                    "",
                    line.get("item_name", ""),
                    line.get("unit", ""),
                    "",
                    line.get("expected_quantity", ""),
                    line.get("actual_quantity", ""),
                    line.get("deviation", ""),
                ])
                for col in range(8):
                    if col != COL_PRODUCT:
                        child.setTextAlignment(col, Qt.AlignCenter)
                child.setForeground(COL_DEV, QColor(self._sign_color(line.get("deviation_sign"))))
                child.setForeground(COL_PRODUCT, QColor("#334155"))
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
        self.empty_label.setVisible(result.is_empty)
        self.tree.setVisible(not result.is_empty)

    @staticmethod
    def _sign_color(sign: Any) -> str:
        return _POS if sign == "pos" else _NEG if sign == "neg" else _ZERO

    def _fill_dashboard(self, result) -> None:
        s = result.summary
        self._kpis["total_orders"]["value"].setText(s["total_orders_label"])
        self._kpis["total_planned"]["value"].setText(s["total_planned_label"])
        self._kpis["finished_products"]["value"].setText(s["finished_products_label"])
        self._kpis["raw_materials"]["value"].setText(s["raw_materials_label"])
        self._kpis["total_expected"]["value"].setText(s["total_expected_label"])
        self._kpis["total_actual"]["value"].setText(s["total_actual_label"])
        self._kpis["deviation"]["value"].setText(s["total_deviation_label"])
        self._kpis["deviation"]["sub"].setText(s.get("deviation_pct_label", ""))

        self.product_donut.set_data(None, result.production_by_product, "label", "count")
        self.material_donut.set_data(None, result.material_share, "label", "count")
        totals = result.totals
        self.expected_actual.set_data(
            float(totals["expected"]), float(totals["actual"]),
            totals["expected_label"], totals["actual_label"], totals["deviation_label"],
        )

    def _reset_dashboard(self) -> None:
        for card in self._kpis.values():
            card["value"].setText("—")
            card["sub"].setText("")
        self.product_donut.set_data(None, [], "label", "count")
        self.material_donut.set_data(None, [], "label", "count")
        self.expected_actual.clear()

    def _update_period_label(self) -> None:
        self.period_label.setText(f"الفترة: من {self._date_from} إلى {self._date_to}")

    def _update_summary(self) -> None:
        role = "منتج تام" if self._item_role == ROLE_FINISHED else "مادة خام"
        parts = [f"الفترة: {self._date_from} — {self._date_to}"]
        parts.append(f"{role}: {self._item_name}" if self._item_name else "كل الأصناف")
        self.summary_label.setText("  •  ".join(parts))

    # --- print / preview / PDF ---------------------------------------------
    def _print_data(self) -> dict[str, Any] | None:
        if self.current_result is None:
            return None
        result = self.current_result
        role_label = "المنتج التام" if self._item_role == ROLE_FINISHED else "المادة الخام"
        return {
            "company": self._company,
            "title": REPORT_TITLE,
            "date_from_label": self._date_from,
            "date_to_label": self._date_to,
            "item_label": self._item_name or "الكل",
            "item_role_label": role_label,
            "summary": result.summary,
            "export_orders": result.export_orders,
            "lines_by_order": result.lines_by_order,
            "is_empty": result.is_empty,
            "empty_message": EMPTY_MESSAGE,
        }

    def open_preview(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل الطباعة.")
            return
        ProductionReportPreviewDialog(data, parent=self).exec()

    def export_pdf(self) -> None:
        data = self._print_data()
        if data is None:
            QMessageBox.information(self, "لا توجد بيانات", "اعرض التقرير أولًا قبل التصدير.")
            return
        export_report_to_pdf(self, data)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ProductionOrderReportScreen",
    "ProductionReportFilterDialog",
    "REPORT_TITLE",
]
