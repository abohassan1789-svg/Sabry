"""Finished-Goods Warehouse balance screen (مخزن الإنتاج التام) — the "النموذج ٢" design.

Pure UI: it builds the RTL layout, gathers the filter value and renders what
``FinishedGoodsBalanceService`` returns. It never touches SQL — every value comes
from the service, which calls the repository. The report is strictly read-only.

Design (Model 2, the same shape the user approved for the raw-material warehouse):
* a compact dark-green **hero** header carrying four small dashboard cards
  (عدد الأصناف · إجمالي المنتَج · إجمالي المبيعات · صافي الرصيد),
* an inline **filter bar** (بحث باسم الصنف — double-click opens a finished-goods
  picker — + a locked «منتج تام» type chip + بحث / مسح),
* a details table with the eight balance columns and a colour-coded الحالة pill.

The balance per row = رصيد أول المدة + الكميات المنتجة − المبيعات, over finished
goods only. Printing / export are a later phase and are intentionally absent.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from app.schemas.product_schema import ITEM_TYPE_FINISHED
from app.services.finished_goods_balance_service import (
    EMPTY_MESSAGE,
    STATUS_LOW,
    STATUS_MID,
    STATUS_NONE,
    STATUS_OK,
    FinishedGoodsBalanceRequest,
    FinishedGoodsBalanceService,
    FinishedGoodsBalanceValidationError,
)
from app.ui.common.theme import GREEN, GREEN_DARK, _button_style
from app.ui.dialogs.saudi_invoice_dialogs import EntityPickerDialog

REPORT_TITLE = "مخزن الإنتاج التام"

_PICKER_LIMIT = 500

_TEXT = "#0F1C14"
_MUTED = "#6B7A6F"
_LINE = "#E1E9E1"
_CELL_TEXT = "#000000"
_ROW_ALT = "#E6F4EA"

# Status → (text colour, soft background) for the الحالة pill / balance cell.
_STATUS_COLORS: dict[str, tuple[str, str]] = {
    STATUS_OK: ("#047857", "#E8F5EC"),
    STATUS_MID: ("#B45309", "#FBEFD8"),
    STATUS_LOW: ("#B91C1C", "#FCE4E4"),
    STATUS_NONE: ("#6B7280", "#EEF1EE"),
}


class _PickerLineEdit(QLineEdit):
    """Editable text field that also opens a picker on double-click.

    Typing works (used as a contains-search); double-clicking emits
    ``doubleClicked`` so the screen can pop up the finished-goods picker.
    """

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: ANN401 - Qt event
        self.doubleClicked.emit()


def _text_field(placeholder: str) -> _PickerLineEdit:
    field = _PickerLineEdit()
    field.setPlaceholderText(placeholder)
    field.setClearButtonEnabled(True)
    field.setMinimumHeight(34)
    field.setToolTip("دبل-كليك لفتح قائمة أصناف الإنتاج التام، أو اكتب للبحث")
    field.setStyleSheet(
        "QLineEdit { background:#FFFFFF; border:1px solid #CBD5C9; border-radius:7px; "
        "padding:5px 9px; color:#0F1C14; }"
        f"QLineEdit:focus {{ border:1px solid {GREEN}; }}"
    )
    return field


def _locked_type_chip() -> QLabel:
    """The نوع الصنف field, pinned to «منتج تام» and read-only (visual only)."""
    chip = QLabel(f"🔒 {ITEM_TYPE_FINISHED}")
    chip.setAlignment(Qt.AlignCenter)
    chip.setMinimumHeight(34)
    chip.setStyleSheet(
        f"QLabel {{ background:#E8F5EC; border:1px solid {GREEN}; border-radius:7px; "
        f"padding:5px 12px; color:{GREEN_DARK}; font-weight:800; }}"
    )
    chip.setToolTip("هذه الشاشة تعرض أصناف الإنتاج التام فقط")
    return chip


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
    """Details table whose columns fill the width proportionally.

    Weights map to the 8 columns: code, name, unit, opening, produced, sold,
    balance, status. The name column gets the most room; numeric columns stay
    compact and always fill the viewport. Recomputed on resize.
    """

    _WEIGHTS = (0.85, 2.1, 0.8, 1.15, 1.1, 1.15, 1.15, 1.0)

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


class FinishedGoodsBalanceScreen(QWidget):
    """RTL read-only finished-goods warehouse balance (opening + produced − sold)."""

    def __init__(
        self, service: FinishedGoodsBalanceService | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service or FinishedGoodsBalanceService()
        self.current_result = None
        self.setWindowTitle(REPORT_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1200, 800)
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
        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._section_title("تفاصيل رصيد الإنتاج التام"))
        layout.addWidget(self._build_table(), 1)
        scroll.setWidget(content)

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
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(9)

        top = QHBoxLayout()
        title = QLabel(f"🏭 {REPORT_TITLE}")
        title.setStyleSheet("font-size:16px; font-weight:900;")
        top.addWidget(title)
        top.addStretch(1)
        subtitle = QLabel("رصيد أول المدة + الكميات المنتجة − المبيعات")
        subtitle.setStyleSheet("font-size:11px; font-weight:700; color:#BFE3CB;")
        top.addWidget(subtitle)
        box.addLayout(top)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.kpi_count = self._kpi_card("🏷 عدد الأصناف")
        self.kpi_produced = self._kpi_card("🏭 إجمالي المنتَج")
        self.kpi_sold = self._kpi_card("🛒 إجمالي المبيعات")
        self.kpi_balance = self._kpi_card("📊 صافي الرصيد")
        for card in (self.kpi_count, self.kpi_produced, self.kpi_sold, self.kpi_balance):
            cards.addWidget(card["frame"], 1)
        box.addLayout(cards)
        return hero

    def _kpi_card(self, title: str) -> dict[str, Any]:
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
        value.setStyleSheet("font-size:18px; font-weight:900;")
        value.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(value)
        return {"frame": frame, "value": value}

    # --- inline filter bar --------------------------------------------------
    def _build_filter_bar(self) -> QFrame:
        bar = self._card()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        self.item_field = _text_field("كل أصناف الإنتاج التام — دبل-كليك للاختيار")
        self.item_field.doubleClicked.connect(self._pick_item)
        self.type_chip = _locked_type_chip()

        layout.addWidget(_labeled("بحث باسم الصنف", self.item_field), 4)
        layout.addWidget(_labeled("نوع الصنف", self.type_chip), 1)

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

        buttons = QVBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(0)
        buttons.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(search_button)
        row.addWidget(reset_button)
        buttons.addLayout(row)
        buttons_box = QWidget()
        buttons_box.setStyleSheet("background:transparent;")
        buttons_box.setLayout(buttons)
        layout.addWidget(buttons_box)

        self.item_field.returnPressed.connect(self.apply_filters)
        return bar

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
        self.table.setMinimumHeight(380)
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

    # --- picker (double-click on the item field) ----------------------------
    def _pick_item(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن منتج تام",
            (("item_code", "رقم الصنف"), ("item_name", "اسم الصنف"), ("unit", "الوحدة")),
            self.service.search_items,
            "item_code",
            parent=self,
            limit=_PICKER_LIMIT,
        )
        if dialog.exec() and dialog.selected is not None:
            name = str(dialog.selected.get("item_name") or "").strip()
            self.item_field.setText(name)

    # --- data flow ----------------------------------------------------------
    def _build_request(self) -> FinishedGoodsBalanceRequest:
        return FinishedGoodsBalanceRequest(
            item_name=self.item_field.text().strip() or None,
        )

    def apply_filters(self) -> None:
        try:
            result = self.service.fetch_report(self._build_request())
        except FinishedGoodsBalanceValidationError as exc:
            QMessageBox.warning(self, "تحقق من الفلاتر", exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "تعذر تحميل التقرير", str(exc))
            return
        self.current_result = result
        self._fill_table(result)
        self._fill_dashboard(result)

    def reset_filters(self) -> None:
        self.item_field.clear()
        self.current_result = None
        self.table.setRowCount(0)
        self.table.setVisible(True)
        self.empty_label.setVisible(False)
        self._reset_dashboard()

    def _fill_table(self, result) -> None:
        columns = result.columns
        rows = result.export_rows
        numeric_rows = result.rows
        self.table.setRowCount(len(rows))
        balance_col = self._column_index("balance")
        status_col = self._column_index("status")
        for row_index, row in enumerate(rows):
            status = numeric_rows[row_index]["status"] if row_index < len(numeric_rows) else ""
            text_color, _bg = _STATUS_COLORS.get(status, ("#000000", "#FFFFFF"))
            for column_index, column in enumerate(columns):
                value = row.get(column.key)
                item = QTableWidgetItem("" if value is None else str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFont(self._cell_font)
                if column_index in (balance_col, status_col):
                    item.setForeground(QColor(text_color))
                self.table.setItem(row_index, column_index, item)
        self.table.apply_widths()
        self.empty_label.setVisible(result.is_empty)
        self.table.setVisible(not result.is_empty)

    def _fill_dashboard(self, result) -> None:
        summary = result.summary
        self.kpi_count["value"].setText(summary["item_count_label"])
        self.kpi_produced["value"].setText(summary["total_produced_label"])
        self.kpi_sold["value"].setText(summary["total_sold_label"])
        self.kpi_balance["value"].setText(summary["total_balance_label"])

    def _reset_dashboard(self) -> None:
        for card in (self.kpi_count, self.kpi_produced, self.kpi_sold, self.kpi_balance):
            card["value"].setText("—")

    # --- small helpers ------------------------------------------------------
    def _column_index(self, key: str) -> int:
        for index, column in enumerate(self.service.columns):
            if column.key == key:
                return index
        return -1

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


__all__ = ["FinishedGoodsBalanceScreen", "REPORT_TITLE"]
