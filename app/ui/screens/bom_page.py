"""Bill of Materials screen — قائمة المواد (Model 4: رأس مقسوم / Split Header).

An Arabic-first (RTL) screen for building a simple material-cost BOM on the
``boms`` / ``bom_lines`` tables. It reuses the same visual language as the
purchase-invoice screen (cards, green toolbar, RTL grid) in the approved
*split-header* composition:

* a **right** card «بيانات المنتج» — the finished product (picked from the
  ``products`` master) and the BOM date;
* a **left** card «بيانات المستند والتكلفة» — the automatic read-only BOM number
  (``BOM-0001``) and a prominent, read-only إجمالي تكلفة الخامات;
* a **full-width** components grid beneath: كود الصنف / اسم الصنف / الوحدة /
  الكمية / السعر / الإجمالي.

Only الكمية and السعر are editable per line; the code / name / unit are filled
automatically from the chosen component and الإجمالي (الكمية × السعر) is derived.
The single total إجمالي تكلفة الخامات is Σ الإجمالي. All figures are recomputed
server-side on save — the UI values are display only. There is **no** labour /
machine / overhead / routing / production / approval workflow: material cost only.
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, Qt, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
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

from app.models.bom import MAX_ITEM_NAME_LEN
from app.schemas.product_schema import ITEM_TYPE_FINISHED, ITEM_TYPE_RAW
from app.security.session_context import SESSION
from app.services.bom_service import BomService, BomServiceError
from app.ui.common.saudi_invoice_style import (
    SI_GREEN,
    button_qss,
    si_icon,
    si_pixmap,
    style_button,
)
from app.ui.dialogs.saudi_invoice_dialogs import EntityPickerDialog

# Column indices for the components table.
(COL_CODE, COL_NAME, COL_UNIT, COL_QTY, COL_PRICE, COL_TOTAL) = range(6)
COLUMN_COUNT = 6
# Only الكمية and السعر can be typed into; the rest are auto / derived.
_EDITABLE_COLS = (COL_QTY, COL_PRICE)

# Permission codes (module "manufacturing", target "boms") — mirror BomService.
PERM_VIEW = "manufacturing.boms.view"
PERM_SAVE = "manufacturing.boms.save"
PERM_EDIT = "manufacturing.boms.edit"
PERM_DELETE = "manufacturing.boms.delete"

ROW_HEIGHT = 42
TABLE_HEADER = 48

BOM_QSS = """
QWidget#bomPage { background: #F5F7FA; }
QScrollArea#bomScroll { background: #F5F7FA; border: none; }
QWidget#bomScrollBody { background: #F5F7FA; }
QFrame#card { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px; }
QFrame#headerLine { background: #E5E7EB; border: none; min-height: 1px; max-height: 1px; }
QLabel#titleLabel { color: #1F2D3D; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 22px; font-weight: 800; background: transparent; }
QLabel#subtitleLabel { color: #6B7280; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 700; background: transparent; }
QLabel#sectionTitle { color: #00843D; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 15px; font-weight: 800; background: transparent; }
QLabel { color: #1F2937; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 13px; font-weight: 700; background: transparent; }
QLabel#fieldLabel { color: #111827; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 700; background: transparent; }
QLineEdit, QDateEdit {
    border: 1px solid #D7DEE7; border-radius: 6px; background: #FFFFFF;
    padding: 4px 10px; color: #111827; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 13px; font-weight: 700; min-height: 26px;
}
QLineEdit:focus, QDateEdit:focus { border: 1px solid #00843D; }
QLineEdit:read-only { background: #F4F6F9; }
QTableWidget {
    border: 1px solid #E5E7EB; border-radius: 8px; background: #FFFFFF;
    gridline-color: #EEF1F4; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 14px; font-weight: 700;
}
QTableWidget::item { padding: 4px; color: #374151; }
QTableWidget::item:selected { background: #E7F6EE; color: #0B3B23; }
QHeaderView::section {
    background: #00843D; color: #FFFFFF; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial';
    font-size: 12px; font-weight: 800; border: none; padding: 6px 4px;
}
QFrame#costBox { background: #E8F5EC; border: 1px solid #BFE6CF; border-radius: 10px; }
QLabel#costLabel { color: #00843D; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 13px; font-weight: 800; background: transparent; }
QLabel#costValue { color: #0B3B23; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 30px; font-weight: 900; background: transparent; }
QLabel#costUnit { color: #0B3B23; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 13px; font-weight: 800; background: transparent; }
QPushButton#lookupButton {
    background: #00843D; color: #FFFFFF; border: none; border-radius: 6px;
    font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-weight: 800;
}
QPushButton#lookupButton:hover { background: #046A31; }
QPushButton#searchButton {
    background: #00843D; color: #FFFFFF; border: none; border-radius: 8px;
}
QPushButton#searchButton:hover { background: #046A31; }
"""


class BomPage(QWidget):
    """The Bill-of-Materials screen. Modes: ``view`` | ``new`` | ``edit``."""

    def __init__(
        self,
        service: BomService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or BomService(permission_check=SESSION.can)
        self._mode = "view"
        self._current: dict[str, Any] | None = None  # loaded {"header","lines"} or None
        self._product: dict[str, Any] | None = None   # {"id","name"} finished product
        self._dirty = False
        self._suspend_cell_signal = False
        self._busy = False  # re-entrancy guard for save/delete (nested modal loops)
        self._lookup_buttons: list[QPushButton] = []

        # Permission snapshot (permissive when no session is loaded).
        self._perm_save = SESSION.can(PERM_SAVE)
        self._perm_edit = SESSION.can(PERM_EDIT)
        self._perm_delete = SESSION.can(PERM_DELETE)

        self.setObjectName("bomPage")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(BOM_QSS)
        self.setMinimumSize(1080, 560)

        self._build_ui()
        self.enter_ready_mode()

    # ======================================================================
    # Small builders
    # ======================================================================
    def _make_card(self, title: str, icon_name: str | None = None):
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(14)
        shadow.setColor(QColor(15, 23, 42, 22))
        shadow.setOffset(0, 2)
        card.setGraphicsEffect(shadow)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        header.addWidget(label)
        if icon_name:
            icon_label = QLabel()
            icon_label.setPixmap(si_pixmap(icon_name, color=SI_GREEN, size=16))
            header.addWidget(icon_label)
        header.addStretch(1)
        layout.addLayout(header)
        return card, layout

    def _labeled(self, label_text: str, widget: QWidget) -> QWidget:
        box = QWidget()
        vbox = QVBoxLayout(box)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(3)
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        vbox.addWidget(label)
        vbox.addWidget(widget)
        return box

    def _lookup_field(self, label_text: str, field: QWidget, on_search) -> QWidget:
        """A field + a small green search button, under a field label."""
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(4)
        hbox.addWidget(field, 1)
        button = QPushButton()
        button.setObjectName("lookupButton")
        button.setIcon(si_icon("fa5s.search", color="#FFFFFF"))
        button.setFixedSize(28, 28)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(on_search)
        hbox.addWidget(button)
        self._lookup_buttons.append(button)
        return self._labeled(label_text, row)

    def _make_toolbar_button(self, text, object_name, icon_name, kind) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setFixedHeight(34)
        button.setMinimumWidth(96)
        button.setCursor(Qt.PointingHandCursor)
        button.setIconSize(QSize(15, 15))
        button.setIcon(si_icon(icon_name, color="#FFFFFF" if kind != "white" else "#374151"))
        button.setStyleSheet(button_qss(kind) + "QPushButton { padding:4px 12px; }")
        return button

    # ======================================================================
    # UI assembly
    # ======================================================================
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("bomScroll")
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        body = QWidget()
        body.setObjectName("bomScrollBody")
        scroll.setWidget(body)

        self.main_layout = QVBoxLayout(body)
        self.main_layout.setContentsMargins(12, 8, 12, 10)
        self.main_layout.setSpacing(8)

        self._build_header()
        self._build_split_header()
        self._build_component_actions()
        self._build_table()

    def _build_header(self) -> None:
        container = QFrame()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(4, 0, 4, 0)
        vbox.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(si_pixmap("fa5s.cubes", color=SI_GREEN, size=26))
        title_box = QWidget()
        title_v = QVBoxLayout(title_box)
        title_v.setContentsMargins(0, 0, 0, 0)
        title_v.setSpacing(2)
        self.title_label = QLabel("قائمة المواد")
        self.title_label.setObjectName("titleLabel")
        self.subtitle_label = QLabel("حساب تكلفة خامات المنتج التام")
        self.subtitle_label.setObjectName("subtitleLabel")
        title_v.addWidget(self.title_label)
        title_v.addWidget(self.subtitle_label)
        top.addWidget(icon)
        top.addWidget(title_box)
        top.addStretch(1)
        vbox.addLayout(top)

        # -- toolbar: all actions on one row (RTL: first added sits right) --
        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)
        self.new_button = self._make_toolbar_button("جديد", "new_button", "fa5s.plus", "green")
        self.search_button = self._make_toolbar_button("بحث / فتح", "search_button2", "fa5s.search", "green")
        self.save_button = self._make_toolbar_button("حفظ", "save_button", "fa5s.save", "green")
        self.edit_button = self._make_toolbar_button("تعديل", "edit_button", "fa5s.pen", "blue")
        self.delete_button = self._make_toolbar_button("حذف", "delete_button", "fa5s.trash", "red")
        self.back_button = self._make_toolbar_button("إغلاق", "back_button", "fa5s.sign-out-alt", "gray")
        for button in (self.new_button, self.search_button, self.save_button,
                       self.edit_button, self.delete_button, self.back_button):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        vbox.addLayout(toolbar)

        line = QFrame()
        line.setObjectName("headerLine")
        vbox.addWidget(line)

        self.main_layout.addWidget(container)

        self.new_button.clicked.connect(self.on_new)
        self.search_button.clicked.connect(self.open_search)
        self.save_button.clicked.connect(self.on_save)
        self.edit_button.clicked.connect(self.on_edit)
        self.delete_button.clicked.connect(self.on_delete)
        self.back_button.clicked.connect(self.on_back)

    def _build_split_header(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)

        # Model 4 (split header). Under RTL the first widget added sits on the
        # RIGHT, so the product card is added first (right) and the cost card
        # second (left).
        product_card, product_layout = self._make_card("بيانات المنتج", "fa5s.box-open")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.product_input = QLineEdit()
        self.product_input.setReadOnly(True)
        self.product_input.setPlaceholderText("اختر المنتج التام…")
        self.product_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(QDate.currentDate())
        self.date_input.dateChanged.connect(self._mark_dirty)
        grid.addWidget(
            self._lookup_field("المنتج التام", self.product_input, self._search_product), 0, 0
        )
        grid.addWidget(self._labeled("التاريخ", self.date_input), 0, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        product_layout.addLayout(grid)
        product_layout.addStretch(1)

        cost_card, cost_layout = self._make_card("بيانات المستند والتكلفة", "fa5s.receipt")
        cost_card.setFixedWidth(360)
        cost_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.bom_number_value = QLineEdit()
        self.bom_number_value.setReadOnly(True)
        self.bom_number_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        cost_layout.addWidget(self._labeled("رقم القائمة", self.bom_number_value))

        cost_box = QFrame()
        cost_box.setObjectName("costBox")
        cost_v = QVBoxLayout(cost_box)
        cost_v.setContentsMargins(16, 12, 16, 12)
        cost_v.setSpacing(2)
        cost_label = QLabel("إجمالي تكلفة الخامات")
        cost_label.setObjectName("costLabel")
        value_row = QHBoxLayout()
        value_row.setSpacing(6)
        self.total_value = QLabel("0.00")
        self.total_value.setObjectName("costValue")
        cost_unit = QLabel("ر.س")
        cost_unit.setObjectName("costUnit")
        value_row.addWidget(self.total_value)
        value_row.addWidget(cost_unit)
        value_row.addStretch(1)
        cost_v.addWidget(cost_label)
        cost_v.addLayout(value_row)
        cost_layout.addWidget(cost_box)
        cost_layout.addStretch(1)

        row.addWidget(product_card, 1)
        row.addWidget(cost_card)
        self.main_layout.addLayout(row)

    def _build_component_actions(self) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(10)
        title = QLabel("مكوّنات الخامة")
        title.setObjectName("sectionTitle")
        self.add_component_button = QPushButton("إضافة مكوّن")
        self.add_component_button.setIcon(si_icon("fa5s.plus", color="#FFFFFF"))
        self.add_component_button.setIconSize(QSize(16, 16))
        self.add_component_button.setFixedHeight(34)
        self.add_component_button.setMinimumWidth(140)
        self.add_component_button.setCursor(Qt.PointingHandCursor)
        style_button(self.add_component_button, "green")
        self.add_component_button.clicked.connect(self._add_components)

        self.remove_component_button = QPushButton("حذف المكوّن")
        self.remove_component_button.setIcon(si_icon("fa5s.trash", color="#DC2626"))
        self.remove_component_button.setFixedHeight(34)
        self.remove_component_button.setMinimumWidth(130)
        self.remove_component_button.setCursor(Qt.PointingHandCursor)
        style_button(self.remove_component_button, "white")
        self.remove_component_button.clicked.connect(self._on_remove_component)

        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(self.add_component_button)
        bar.addWidget(self.remove_component_button)
        self.main_layout.addLayout(bar)

    def _build_table(self) -> None:
        card, layout = self._make_card("جدول المكوّنات", "fa5s.list-ul")
        self.lines_table = QTableWidget()
        self.lines_table.setColumnCount(COLUMN_COUNT)
        self.lines_table.setHorizontalHeaderLabels([
            "كود الصنف", "اسم الصنف", "الوحدة", "الكمية", "السعر", "الإجمالي",
        ])
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lines_table.setAlternatingRowColors(True)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.lines_table.horizontalHeader().setFixedHeight(TABLE_HEADER)
        self.lines_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.lines_table.setMinimumHeight(TABLE_HEADER + 5 * ROW_HEIGHT)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.lines_table, 1)
        self.main_layout.addWidget(card, 1)

    # ======================================================================
    # Product + component pickers (reuse the project's searchable picker)
    # ======================================================================
    def _finished_search(self, keyword: str, limit: int) -> list[dict[str, Any]]:
        """Products for the finished-product picker: منتج تام first, never hidden."""
        rows = self.service.search_products(keyword, limit)
        return sorted(rows, key=lambda r: 0 if r.get("item_type") == ITEM_TYPE_FINISHED else 1)

    def _component_search(self, keyword: str, limit: int) -> list[dict[str, Any]]:
        """Products for the component picker: مادة خام first, never hidden."""
        rows = self.service.search_products(keyword, limit)
        return sorted(rows, key=lambda r: 0 if r.get("item_type") == ITEM_TYPE_RAW else 1)

    def _search_product(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن المنتج التام",
            [("item_code", "رقم الصنف"), ("item_name", "الاسم"),
             ("unit", "الوحدة"), ("price", "السعر")],
            self._finished_search, "id", parent=self,
        )
        if not (dialog.exec() and dialog.selected):
            return
        rec = dialog.selected
        product_id = rec.get("id")
        # Guard: the finished product must not already be one of its components.
        if any(self._line_meta(r).get("component_product_id") == product_id
               for r in range(self.lines_table.rowCount())):
            QMessageBox.warning(
                self, "تنبيه",
                "هذا الصنف مُضاف بالفعل كأحد المكوّنات، فلا يصلح كمنتج تام لنفس القائمة.",
            )
            return
        self._product = {"id": product_id, "name": str(rec.get("item_name") or "")}
        self.product_input.setText(self._product["name"])
        self._mark_dirty()

    def _add_components(self) -> None:
        """Open the multi-select أصناف popup; every ticked product becomes a line."""
        dialog = EntityPickerDialog(
            "بحث عن الأصناف المكوّنة",
            [("item_code", "رقم الصنف"), ("item_name", "الاسم"),
             ("unit", "الوحدة"), ("price", "السعر")],
            self._component_search, "id", parent=self, multi_select=True,
        )
        if not (dialog.exec() and dialog.selected_rows):
            return
        finished_id = self._product.get("id") if self._product else None
        existing = {self._line_meta(r).get("component_product_id")
                    for r in range(self.lines_table.rowCount())}
        skipped_self = skipped_dup = 0
        for rec in dialog.selected_rows:
            pid = rec.get("id")
            if pid is not None and pid == finished_id:
                skipped_self += 1
                continue
            if pid in existing:
                skipped_dup += 1
                continue
            existing.add(pid)
            try:
                price = Decimal(str(rec["price"])) if rec.get("price") is not None else Decimal("0")
            except (InvalidOperation, TypeError, ValueError):
                price = Decimal("0")
            self._append_line(
                component_product_id=pid,
                item_code=rec.get("item_code"),
                name=str(rec.get("item_name") or ""),
                unit=str(rec.get("unit") or ""),
                quantity=Decimal("1"),
                price=price,
            )
        if skipped_self or skipped_dup:
            parts = []
            if skipped_self:
                parts.append(f"{skipped_self} لأنه هو المنتج التام نفسه")
            if skipped_dup:
                parts.append(f"{skipped_dup} لأنه مُضاف مسبقًا")
            QMessageBox.information(self, "تنبيه", "تم تجاهل: " + "، ".join(parts) + ".")
        self._mark_dirty()

    # ======================================================================
    # Table lines
    # ======================================================================
    def _line_meta(self, row: int) -> dict[str, Any]:
        item = self.lines_table.item(row, COL_NAME)
        meta = item.data(Qt.UserRole) if item is not None else None
        return meta or {}

    def _append_line(self, *, component_product_id, item_code, name, unit,
                     quantity, price) -> None:
        meta = {
            "component_product_id": component_product_id,
            "item_code": self._fmt_code(item_code),
            "item_name": name,
            "unit": unit or "",
            "quantity": quantity,
            "price": price,
            "line_id": None,
        }
        r = self.lines_table.rowCount()
        self.lines_table.insertRow(r)
        for c in range(COLUMN_COUNT):
            self.lines_table.setItem(r, c, QTableWidgetItem(""))
        self._write_row(r, meta)
        self._refresh_total()

    def _write_row(self, r: int, meta: dict) -> None:
        meta["total"] = self.service.compute_line_total(meta["quantity"], meta["price"])
        editable = self._mode in ("new", "edit")
        self._suspend_cell_signal = True
        try:
            cells = {
                COL_CODE: meta.get("item_code", ""),
                COL_NAME: meta["item_name"],
                COL_UNIT: meta.get("unit", ""),
                COL_QTY: self._fmt_qty(meta["quantity"]),
                COL_PRICE: self._fmt_qty(meta["price"]),
                COL_TOTAL: f"{meta['total']:,.2f}",
            }
            for c, text in cells.items():
                item = self.lines_table.item(r, c)
                item.setText(text)
                item.setTextAlignment(Qt.AlignCenter)
                if c in _EDITABLE_COLS and editable:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.lines_table.item(r, COL_NAME).setData(Qt.UserRole, meta)
        finally:
            self._suspend_cell_signal = False

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._suspend_cell_signal or col not in _EDITABLE_COLS:
            return
        value_item = self.lines_table.item(row, col)
        meta = self._line_meta(row)
        if value_item is None or not meta:
            return
        try:
            value = self._parse(value_item.text(), "القيمة")
            if col == COL_QTY and value <= 0:
                raise ValueError("الكمية يجب أن تكون أكبر من صفر.")
            if col == COL_PRICE and value < 0:
                raise ValueError("السعر لا يمكن أن يكون سالبًا.")
        except ValueError as exc:
            QMessageBox.warning(self, "قيمة غير صالحة", str(exc))
            self._write_row(row, meta)  # revert to the previous good value
            return
        meta["quantity" if col == COL_QTY else "price"] = value
        self._write_row(row, meta)
        self._refresh_total()
        self._mark_dirty()

    def _on_remove_component(self) -> None:
        row = self.lines_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "تنبيه", "اختر مكوّنًا لحذفه.")
            return
        self.lines_table.removeRow(row)
        self._refresh_total()
        self._mark_dirty()

    def _refresh_total(self) -> None:
        lines = []
        for r in range(self.lines_table.rowCount()):
            meta = self._line_meta(r)
            if meta:
                lines.append({"line_total": meta.get("total", Decimal("0"))})
        total = self.service.compute_total_material_cost(lines)
        self.total_value.setText(f"{total:,.2f}")

    def _collect_lines(self) -> list[dict[str, Any]]:
        lines = []
        for r in range(self.lines_table.rowCount()):
            meta = self._line_meta(r)
            if meta:
                lines.append({
                    "component_product_id": meta.get("component_product_id"),
                    "quantity": meta["quantity"],
                    "price": meta["price"],
                })
        return lines

    # ======================================================================
    # Parsing / formatting helpers
    # ======================================================================
    @staticmethod
    def _parse(text: str, field: str) -> Decimal:
        raw = (text or "").strip().replace(",", "")
        if raw == "":
            raise ValueError(f"{field} مطلوب.")
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"{field}: قيمة رقمية غير صالحة.") from exc
        if not value.is_finite():
            raise ValueError(f"{field}: قيمة رقمية غير صالحة.")
        return value

    @staticmethod
    def _fmt_qty(value: Decimal) -> str:
        return format(value.normalize(), "f")

    @staticmethod
    def _fmt_code(value: Any) -> str:
        if value in (None, ""):
            return ""
        text = str(value).strip()
        try:
            return str(int(text))
        except (TypeError, ValueError):
            return text

    def _mark_dirty(self, *_a) -> None:
        self._dirty = True

    # ======================================================================
    # Modes
    # ======================================================================
    def _set_form_editable(self, editable: bool) -> None:
        self.date_input.setEnabled(editable)
        for button in self._lookup_buttons:
            button.setEnabled(editable)
        self.add_component_button.setEnabled(editable)
        self.remove_component_button.setEnabled(editable)
        self.lines_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
            if editable else QAbstractItemView.NoEditTriggers
        )

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        is_new = mode == "new"
        is_edit = mode == "edit"
        is_view = mode == "view"
        editable = is_new or is_edit
        has_current = self._current is not None

        self._set_form_editable(editable)

        self.new_button.setEnabled(is_view and self._perm_save)
        self.search_button.setEnabled(True)
        self.save_button.setEnabled(editable and self._perm_save)
        self.edit_button.setEnabled(is_view and has_current and self._perm_edit)
        self.delete_button.setEnabled(is_view and has_current and self._perm_delete)
        self.back_button.setEnabled(True)

        # Re-apply editable flags to existing rows.
        self._suspend_cell_signal = True
        try:
            for r in range(self.lines_table.rowCount()):
                meta = self._line_meta(r)
                if meta:
                    self._write_row(r, meta)
        finally:
            self._suspend_cell_signal = False

    def _clear_form(self) -> None:
        self._product = None
        self.product_input.clear()
        self.bom_number_value.clear()
        self.date_input.setDate(QDate.currentDate())
        self._suspend_cell_signal = True
        self.lines_table.setRowCount(0)
        self._suspend_cell_signal = False
        self._refresh_total()
        self._dirty = False

    def _populate_reserved_number(self) -> None:
        try:
            number = self.service.reserve_bom_number()
        except Exception:  # noqa: BLE001
            QMessageBox.warning(
                self, "تعذّر إنشاء الرقم",
                "تعذّر إنشاء رقم قائمة مواد تلقائيًا. حاول مرة أخرى.",
            )
            number = ""
        self.bom_number_value.setText(str(number))

    def enter_ready_mode(self) -> None:
        """Idle, locked state: nothing loaded, only «جديد» / «بحث» are actionable."""
        self._current = None
        self._clear_form()
        self._set_mode("view")
        self._dirty = False

    def enter_new_mode(self) -> None:
        self._current = None
        self._clear_form()
        self._populate_reserved_number()
        self._set_mode("new")
        self._dirty = False

    def enter_view_mode(self) -> None:
        self._set_mode("view")

    def enter_edit_mode(self) -> None:
        if self._current is None:
            return
        self._set_mode("edit")

    # ======================================================================
    # Load an existing BOM
    # ======================================================================
    def load_bom(self, bom_id: int) -> None:
        loaded = None
        try:
            loaded = self.service.load(bom_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطأ", str(exc))
            return
        if not loaded:
            QMessageBox.warning(self, "غير موجودة", "تعذّر تحميل قائمة المواد.")
            return
        self._current = loaded
        header = loaded["header"]

        self.bom_number_value.setText(header["bom_number"] or "")
        bom_date = header["bom_date"]
        if bom_date is not None:
            self.date_input.setDate(QDate(bom_date.year, bom_date.month, bom_date.day))
        self._product = {
            "id": header["product_id"],
            "name": header["product_name_snapshot"],
        }
        self.product_input.setText(header["product_name_snapshot"] or "")

        self._suspend_cell_signal = True
        self.lines_table.setRowCount(0)
        self._suspend_cell_signal = False
        for line in loaded["lines"]:
            meta = {
                "component_product_id": line["component_product_id"],
                "item_code": self._fmt_code(line.get("item_code_snapshot")),
                "item_name": line["item_name_snapshot"],
                "unit": line.get("unit_snapshot") or "",
                "quantity": Decimal(str(line["quantity"])),
                "price": Decimal(str(line["price"])),
                "line_id": line["id"],
            }
            r = self.lines_table.rowCount()
            self.lines_table.insertRow(r)
            for c in range(COLUMN_COUNT):
                self.lines_table.setItem(r, c, QTableWidgetItem(""))
            self._write_row(r, meta)
        self._refresh_total()

        self.enter_view_mode()
        self._dirty = False

    # ======================================================================
    # Actions
    # ======================================================================
    def _current_user_id(self) -> int | None:
        user = SESSION.user or {}
        try:
            return int(user["id"]) if user.get("id") is not None else None
        except (KeyError, TypeError, ValueError):
            return None

    def _collect_form(self) -> dict[str, Any]:
        return {
            "bom_number": self.bom_number_value.text(),
            "bom_date": self.date_input.date().toPython(),
            "product_id": self._product.get("id") if self._product else None,
            "lines": self._collect_lines(),
        }

    def on_new(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        self.enter_new_mode()

    def on_edit(self) -> None:
        if self._current is None:
            return
        self.enter_edit_mode()

    def on_save(self) -> None:
        # Re-entrancy guard: the success dialog below spins a nested event loop;
        # without this a queued second Save could create a duplicate document.
        if self._busy:
            return
        self._busy = True
        try:
            form = self._collect_form()
            try:
                if self._current is None:
                    saved = self.service.create_bom(form, user_id=self._current_user_id())
                else:
                    saved = self.service.update_bom(
                        self._current["header"]["id"], form, user_id=self._current_user_id()
                    )
            except BomServiceError as exc:
                QMessageBox.warning(self, "تعذّر الحفظ", exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "خطأ", str(exc))
                return
            # Reload (→ view mode, Save disabled) BEFORE announcing success, so the
            # message's nested loop can never re-trigger a save.
            self.load_bom(saved["header"]["id"])
            QMessageBox.information(self, "تم", "تم حفظ قائمة المواد.")
        finally:
            self._busy = False

    def on_delete(self) -> None:
        if self._current is None or self._busy:
            return
        if QMessageBox.question(
            self, "تأكيد الحذف", "هل تريد حذف قائمة المواد هذه؟"
        ) != QMessageBox.Yes:
            return
        self._busy = True
        try:
            try:
                self.service.delete_bom(
                    self._current["header"]["id"], user_id=self._current_user_id()
                )
            except BomServiceError as exc:
                QMessageBox.warning(self, "تعذّر الحذف", exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "خطأ", str(exc))
                return
            # Reset to a clean state BEFORE announcing success (see on_save).
            self.enter_ready_mode()
            QMessageBox.information(self, "تم", "تم حذف قائمة المواد.")
        finally:
            self._busy = False

    def on_back(self) -> None:
        window = self.window()
        if window is not None:
            window.close()

    def closeEvent(self, event) -> None:  # noqa: ANN001 - Qt close event
        if self._dirty and not self._confirm_discard():
            event.ignore()
            return
        super().closeEvent(event)

    # ======================================================================
    # Search / open existing (reuses the generic searchable picker)
    # ======================================================================
    def open_search(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        dialog = EntityPickerDialog(
            "بحث عن قائمة مواد",
            [("bom_number", "رقم القائمة"), ("bom_date", "التاريخ"),
             ("product_name_snapshot", "المنتج"), ("total_material_cost", "الإجمالي")],
            self.service.search_boms, "id", parent=self,
        )
        if dialog.exec() and dialog.selected:
            self.load_bom(int(dialog.selected["id"]))

    def _confirm_discard(self) -> bool:
        return QMessageBox.question(
            self, "تجاهل التغييرات", "هناك تغييرات غير محفوظة. هل تريد تجاهلها؟"
        ) == QMessageBox.Yes


__all__ = ["BomPage"]
