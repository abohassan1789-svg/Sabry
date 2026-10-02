"""Production Order screen — أمر الإنتاج (Model 1: الكلاسيكي / Classic ERP).

An Arabic-first (RTL) screen for a simple manufacturing document on the
``production_orders`` / ``production_order_lines`` tables. It reuses the same
visual language as the BOM / purchase-invoice screens (cards, green toolbar, RTL
grid) in the approved *classic* composition:

* a **top toolbar** with the document actions (New / Search-Open / Save / Edit /
  Delete / صرف المواد الخام / Close);
* a **single compact header band** holding the four header fields in one row: the
  automatic read-only order number (``PRO-001``), the date, the finished product
  (picked from the ``products`` master) and «الكمية المطلوب إنتاجها»;
* a **full-width materials grid** beneath: كود الصنف / اسم الصنف / الوحدة /
  الكمية المفروض صرفها / الكمية الفعلية / الانحراف.

Only «الكمية الفعلية» is editable per line; the code / name / unit are filled from
the BOM and «الكمية المفروض صرفها» + «الانحراف» are derived. Pressing «صرف المواد
الخام» (re)loads the selected product's BOM, computes the expected quantities and
resets the actual quantities to them — it does **not** create any stock movement.
Changing «الكمية المطلوب إنتاجها» after loading recomputes the expected quantities
and deviations while preserving the user's actual quantities. All figures are
recomputed server-side on save — the UI values are display only. There is **no**
warehouse, inventory posting, cost total or approval workflow.
"""

from __future__ import annotations

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

from app.schemas.product_schema import ITEM_TYPE_FINISHED
from app.security.session_context import SESSION
from app.services.production_order_service import (
    ProductionOrderService,
    ProductionOrderServiceError,
)
from app.ui.common.saudi_invoice_style import (
    SI_GREEN,
    button_qss,
    si_icon,
    si_pixmap,
    style_button,
)
from app.ui.dialogs.saudi_invoice_dialogs import EntityPickerDialog

# Column indices for the materials table.
(COL_CODE, COL_NAME, COL_UNIT, COL_EXPECTED, COL_ACTUAL, COL_DEV) = range(6)
COLUMN_COUNT = 6
# Only «الكمية الفعلية» can be typed into; the rest are auto / derived.
_EDITABLE_COLS = (COL_ACTUAL,)

# Permission codes (module "manufacturing", target "production_orders") — mirror
# ProductionOrderService.
PERM_VIEW = "manufacturing.production_orders.view"
PERM_SAVE = "manufacturing.production_orders.save"
PERM_EDIT = "manufacturing.production_orders.edit"
PERM_DELETE = "manufacturing.production_orders.delete"

# Deviation cell colours (subtle, professional — not dashboard-bright).
_DEV_POS = QColor("#047857")   # موجب
_DEV_NEG = QColor("#B91C1C")   # سالب
_DEV_ZERO = QColor("#6B7280")  # صفر

ROW_HEIGHT = 42
TABLE_HEADER = 48

PO_QSS = """
QWidget#poPage { background: #F5F7FA; }
QScrollArea#poScroll { background: #F5F7FA; border: none; }
QWidget#poScrollBody { background: #F5F7FA; }
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
QLineEdit#qtyInput { font-size: 15px; font-weight: 800; }
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
QPushButton#lookupButton {
    background: #00843D; color: #FFFFFF; border: none; border-radius: 6px;
    font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-weight: 800;
}
QPushButton#lookupButton:hover { background: #046A31; }
"""


class ProductionOrderPage(QWidget):
    """The Production Order screen. Modes: ``view`` | ``new`` | ``edit``."""

    def __init__(
        self,
        service: ProductionOrderService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or ProductionOrderService(permission_check=SESSION.can)
        self._mode = "view"
        self._current: dict[str, Any] | None = None  # loaded {"header","lines"} or None
        self._product: dict[str, Any] | None = None   # {"id","name"} finished product
        self._bom_id: int | None = None               # BOM chosen/used for the lines
        self._dirty = False
        self._suspend_cell_signal = False
        self._busy = False  # re-entrancy guard for save/delete (nested modal loops)
        self._lookup_buttons: list[QPushButton] = []

        # Permission snapshot (permissive when no session is loaded).
        self._perm_save = SESSION.can(PERM_SAVE)
        self._perm_edit = SESSION.can(PERM_EDIT)
        self._perm_delete = SESSION.can(PERM_DELETE)

        self.setObjectName("poPage")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(PO_QSS)
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
        if title:
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
        scroll.setObjectName("poScroll")
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        body = QWidget()
        body.setObjectName("poScrollBody")
        scroll.setWidget(body)

        self.main_layout = QVBoxLayout(body)
        self.main_layout.setContentsMargins(12, 8, 12, 10)
        self.main_layout.setSpacing(8)

        self._build_header()
        self._build_header_band()
        self._build_table()

    def _build_header(self) -> None:
        container = QFrame()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(4, 0, 4, 0)
        vbox.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(si_pixmap("fa5s.industry", color=SI_GREEN, size=26))
        title_box = QWidget()
        title_v = QVBoxLayout(title_box)
        title_v.setContentsMargins(0, 0, 0, 0)
        title_v.setSpacing(2)
        self.title_label = QLabel("أمر الإنتاج")
        self.title_label.setObjectName("titleLabel")
        self.subtitle_label = QLabel("تحميل مكونات قائمة المواد وحساب الانحراف")
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
        self.issue_button = self._make_toolbar_button(
            "صرف المواد الخام", "issue_button", "fa5s.dolly-flatbed", "green"
        )
        self.issue_button.setMinimumWidth(150)
        self.back_button = self._make_toolbar_button("إغلاق", "back_button", "fa5s.sign-out-alt", "gray")
        for button in (self.new_button, self.search_button, self.save_button,
                       self.edit_button, self.delete_button, self.issue_button,
                       self.back_button):
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
        self.issue_button.clicked.connect(self.on_issue_materials)
        self.back_button.clicked.connect(self.on_back)

    def _build_header_band(self) -> None:
        """Model 1: the four header fields in one structured band (single row)."""
        card, layout = self._make_card("بيانات أمر الإنتاج", "fa5s.clipboard-list")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        self.order_number_value = QLineEdit()
        self.order_number_value.setReadOnly(True)
        self.order_number_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(QDate.currentDate())
        self.date_input.dateChanged.connect(self._mark_dirty)

        self.product_input = QLineEdit()
        self.product_input.setReadOnly(True)
        self.product_input.setPlaceholderText("اختر المنتج التام…")
        self.product_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)

        self.qty_input = QLineEdit()
        self.qty_input.setObjectName("qtyInput")
        self.qty_input.setPlaceholderText("0")
        self.qty_input.setAlignment(Qt.AlignCenter)
        self.qty_input.textEdited.connect(self._on_quantity_edited)

        grid.addWidget(self._labeled("رقم أمر الإنتاج", self.order_number_value), 0, 0)
        grid.addWidget(self._labeled("التاريخ", self.date_input), 0, 1)
        grid.addWidget(
            self._lookup_field("المنتج التام", self.product_input, self._search_product), 0, 2
        )
        grid.addWidget(self._labeled("الكمية المطلوب إنتاجها", self.qty_input), 0, 3)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)

        self.main_layout.addWidget(card)

    def _build_table(self) -> None:
        card, layout = self._make_card("مكوّنات الخامة", "fa5s.list-ul")
        self.lines_table = QTableWidget()
        self.lines_table.setColumnCount(COLUMN_COUNT)
        self.lines_table.setHorizontalHeaderLabels([
            "كود الصنف", "اسم الصنف", "الوحدة",
            "الكمية المفروض صرفها", "الكمية الفعلية", "الانحراف",
        ])
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lines_table.setAlternatingRowColors(True)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.lines_table.horizontalHeader().setFixedHeight(TABLE_HEADER)
        self.lines_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.lines_table.setMinimumHeight(TABLE_HEADER + 6 * ROW_HEIGHT)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.lines_table, 1)

        self.hint_label = QLabel(
            "اختر المنتج وحدد الكمية ثم اضغط «صرف المواد الخام» لتحميل مكونات قائمة المواد."
        )
        self.hint_label.setObjectName("subtitleLabel")
        self.hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint_label)

        self.main_layout.addWidget(card, 1)

    # ======================================================================
    # Finished-product picker (reuse the project's searchable picker)
    # ======================================================================
    def _finished_search(self, keyword: str, limit: int) -> list[dict[str, Any]]:
        """Products for the finished-product picker: منتج تام first, never hidden."""
        rows = self.service.search_products(keyword, limit)
        return sorted(rows, key=lambda r: 0 if r.get("item_type") == ITEM_TYPE_FINISHED else 1)

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
        # Changing the finished product invalidates any loaded materials / BOM
        # choice (business rule): clear the lines and reset the BOM selection.
        if self._product is not None and self._product.get("id") != product_id \
                and self.lines_table.rowCount() > 0:
            if not self._confirm(
                "تغيير المنتج", "سيؤدي تغيير المنتج التام إلى مسح المواد المحمّلة. متابعة؟"
            ):
                return
        self._product = {"id": product_id, "name": str(rec.get("item_name") or "")}
        self.product_input.setText(self._product["name"])
        self._bom_id = None
        self._clear_lines()
        self._mark_dirty()

    # ======================================================================
    # صرف المواد الخام — load / reload materials from the selected BOM
    # ======================================================================
    def on_issue_materials(self) -> None:
        """Load/reload BOM materials, compute expected, reset actual = expected.

        This creates NO stock movement — it only populates the requirement lines.
        """
        if self._busy or self._mode not in ("new", "edit"):
            return
        if self._product is None or self._product.get("id") is None:
            QMessageBox.information(self, "تنبيه", "اختر المنتج التام أولًا.")
            return
        try:
            quantity = self._parse(self.qty_input.text(), "الكمية المطلوب إنتاجها")
            if quantity <= 0:
                raise ValueError("الكمية المطلوب إنتاجها يجب أن تكون أكبر من صفر.")
        except ValueError as exc:
            QMessageBox.warning(self, "قيمة غير صالحة", str(exc))
            return

        product_id = self._product["id"]
        # Resolve which BOM to consume: none -> message; one -> auto; many -> picker.
        try:
            boms = self.service.list_boms_for_product(product_id)
        except ProductionOrderServiceError as exc:
            QMessageBox.warning(self, "تعذّر التحميل", exc.message)
            return
        if not boms:
            QMessageBox.warning(
                self, "لا توجد قائمة مواد",
                "المنتج التام المحدد ليس له قائمة مواد (BOM). أنشئ قائمة مواد أولًا.",
            )
            return

        bom_id = self._bom_id
        if bom_id is None:
            if len(boms) == 1:
                bom_id = boms[0]["id"]
            else:
                bom_id = self._choose_bom(boms)
                if bom_id is None:
                    return

        try:
            loaded = self.service.load_materials(product_id, quantity, bom_id=bom_id)
        except ProductionOrderServiceError as exc:
            QMessageBox.warning(self, "تعذّر التحميل", exc.message)
            return

        self._bom_id = loaded["bom_id"]
        self._populate_lines(loaded["lines"])
        self._mark_dirty()

    def _choose_bom(self, boms: list[dict[str, Any]]) -> int | None:
        """Popup to pick one BOM when a product has several; returns its id or None."""
        dialog = EntityPickerDialog(
            "اختر قائمة المواد",
            [("bom_number", "رقم القائمة"), ("bom_date", "التاريخ"),
             ("total_material_cost", "إجمالي التكلفة")],
            lambda _kw, _limit, rows=boms: rows, "id", parent=self,
        )
        if dialog.exec() and dialog.selected:
            return int(dialog.selected["id"])
        return None

    # ======================================================================
    # Table lines
    # ======================================================================
    def _line_meta(self, row: int) -> dict[str, Any]:
        item = self.lines_table.item(row, COL_NAME)
        meta = item.data(Qt.UserRole) if item is not None else None
        return meta or {}

    def _populate_lines(self, lines: list[dict[str, Any]]) -> None:
        self._suspend_cell_signal = True
        self.lines_table.setRowCount(0)
        self._suspend_cell_signal = False
        for line in lines:
            meta = {
                "component_product_id": line.get("component_product_id"),
                "item_code": self._fmt_code(line.get("item_code_snapshot")),
                "item_name": line.get("item_name_snapshot") or "",
                "unit": line.get("unit_snapshot") or "",
                "bom_quantity_per_unit": Decimal(str(line.get("bom_quantity_per_unit", "0"))),
                "expected_quantity": Decimal(str(line.get("expected_quantity", "0"))),
                "actual_quantity": Decimal(str(line.get("actual_quantity", "0"))),
                "line_id": line.get("id"),
            }
            self._append_row(meta)
        self._update_hint()

    def _append_row(self, meta: dict[str, Any]) -> None:
        r = self.lines_table.rowCount()
        self.lines_table.insertRow(r)
        for c in range(COLUMN_COUNT):
            self.lines_table.setItem(r, c, QTableWidgetItem(""))
        self._write_row(r, meta)

    def _write_row(self, r: int, meta: dict) -> None:
        meta["deviation"] = meta["actual_quantity"] - meta["expected_quantity"]
        editable = self._mode in ("new", "edit")
        self._suspend_cell_signal = True
        try:
            cells = {
                COL_CODE: meta.get("item_code", ""),
                COL_NAME: meta["item_name"],
                COL_UNIT: meta.get("unit", ""),
                COL_EXPECTED: self._fmt_qty(meta["expected_quantity"]),
                COL_ACTUAL: self._fmt_qty(meta["actual_quantity"]),
                COL_DEV: self._fmt_dev(meta["deviation"]),
            }
            for c, text in cells.items():
                item = self.lines_table.item(r, c)
                item.setText(text)
                item.setTextAlignment(Qt.AlignCenter)
                if c in _EDITABLE_COLS and editable:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            # Deviation colour (subtle).
            dev = meta["deviation"]
            dev_item = self.lines_table.item(r, COL_DEV)
            dev_item.setForeground(_DEV_POS if dev > 0 else _DEV_NEG if dev < 0 else _DEV_ZERO)
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
            value = self._parse(value_item.text(), "الكمية الفعلية")
            if value < 0:
                raise ValueError("الكمية الفعلية لا يمكن أن تكون سالبة.")
        except ValueError as exc:
            QMessageBox.warning(self, "قيمة غير صالحة", str(exc))
            self._write_row(row, meta)  # revert to the previous good value
            return
        meta["actual_quantity"] = value
        self._write_row(row, meta)
        self._mark_dirty()

    def _clear_lines(self) -> None:
        self._suspend_cell_signal = True
        self.lines_table.setRowCount(0)
        self._suspend_cell_signal = False
        self._update_hint()

    def _update_hint(self) -> None:
        self.hint_label.setVisible(self.lines_table.rowCount() == 0)

    # ======================================================================
    # Production-quantity change: recompute expected, preserve actual
    # ======================================================================
    def _on_quantity_edited(self, _text: str) -> None:
        self._mark_dirty()
        if self.lines_table.rowCount() == 0:
            return
        try:
            quantity = self._parse(self.qty_input.text(), "الكمية")
            if quantity <= 0:
                return
        except ValueError:
            return  # don't nag on every keystroke; wait for a valid value
        metas = [self._line_meta(r) for r in range(self.lines_table.rowCount())]
        try:
            updated = self.service.recalculate_for_quantity(metas, quantity)
        except ProductionOrderServiceError:
            return
        for r, meta in enumerate(updated):
            self._write_row(r, meta)

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

    @classmethod
    def _fmt_dev(cls, value: Decimal) -> str:
        if value > 0:
            return "+" + cls._fmt_qty(value)
        return cls._fmt_qty(value)  # negative keeps its '-', zero shows '0'

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
        self.qty_input.setReadOnly(not editable)
        for button in self._lookup_buttons:
            button.setEnabled(editable)
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
        self.issue_button.setEnabled(editable)
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
        self._bom_id = None
        self.product_input.clear()
        self.order_number_value.clear()
        self.qty_input.clear()
        self.date_input.setDate(QDate.currentDate())
        self._clear_lines()
        self._dirty = False

    def _populate_reserved_number(self) -> None:
        try:
            number = self.service.reserve_order_number()
        except Exception:  # noqa: BLE001
            QMessageBox.warning(
                self, "تعذّر إنشاء الرقم",
                "تعذّر إنشاء رقم أمر إنتاج تلقائيًا. حاول مرة أخرى.",
            )
            number = ""
        self.order_number_value.setText(str(number))

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
    # Load an existing Production Order (from stored snapshots)
    # ======================================================================
    def load_order(self, order_id: int) -> None:
        loaded = None
        try:
            loaded = self.service.load(order_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطأ", str(exc))
            return
        if not loaded:
            QMessageBox.warning(self, "غير موجود", "تعذّر تحميل أمر الإنتاج.")
            return
        self._current = loaded
        header = loaded["header"]

        self.order_number_value.setText(header["order_number"] or "")
        order_date = header["order_date"]
        if order_date is not None:
            self.date_input.setDate(QDate(order_date.year, order_date.month, order_date.day))
        self._product = {
            "id": header["product_id"],
            "name": header["product_name_snapshot"],
        }
        self.product_input.setText(header["product_name_snapshot"] or "")
        self._bom_id = header.get("bom_id")
        self.qty_input.setText(self._fmt_qty(Decimal(str(header["production_quantity"]))))

        self._populate_lines(loaded["lines"])
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

    def _collect_lines(self) -> list[dict[str, Any]]:
        lines = []
        for r in range(self.lines_table.rowCount()):
            meta = self._line_meta(r)
            if meta:
                lines.append({
                    "component_product_id": meta.get("component_product_id"),
                    "actual_quantity": meta["actual_quantity"],
                })
        return lines

    def _collect_form(self) -> dict[str, Any]:
        return {
            "order_number": self.order_number_value.text(),
            "order_date": self.date_input.date().toPython(),
            "product_id": self._product.get("id") if self._product else None,
            "bom_id": self._bom_id,
            "production_quantity": self.qty_input.text(),
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
        # The grid is the source of truth: never persist materials the user has
        # not loaded/reviewed. Without this, an empty grid would let the service
        # silently pull a full BOM on save (materials the user never saw).
        if self.lines_table.rowCount() == 0:
            QMessageBox.information(
                self, "لا توجد مواد",
                "قم بتحميل مكوّنات قائمة المواد أولًا عبر «صرف المواد الخام».",
            )
            return
        self._busy = True
        try:
            form = self._collect_form()
            try:
                if self._current is None:
                    saved = self.service.create_order(form, user_id=self._current_user_id())
                else:
                    saved = self.service.update_order(
                        self._current["header"]["id"], form, user_id=self._current_user_id()
                    )
            except ProductionOrderServiceError as exc:
                QMessageBox.warning(self, "تعذّر الحفظ", exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "خطأ", str(exc))
                return
            # Reload (→ view mode, Save disabled) BEFORE announcing success, so the
            # message's nested loop can never re-trigger a save.
            self.load_order(saved["header"]["id"])
            QMessageBox.information(self, "تم", "تم حفظ أمر الإنتاج.")
        finally:
            self._busy = False

    def on_delete(self) -> None:
        if self._current is None or self._busy:
            return
        if QMessageBox.question(
            self, "تأكيد الحذف", "هل تريد حذف أمر الإنتاج هذا؟"
        ) != QMessageBox.Yes:
            return
        self._busy = True
        try:
            try:
                self.service.delete_order(
                    self._current["header"]["id"], user_id=self._current_user_id()
                )
            except ProductionOrderServiceError as exc:
                QMessageBox.warning(self, "تعذّر الحذف", exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "خطأ", str(exc))
                return
            # Reset to a clean state BEFORE announcing success (see on_save).
            self.enter_ready_mode()
            QMessageBox.information(self, "تم", "تم حذف أمر الإنتاج.")
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
            "بحث عن أمر إنتاج",
            [("order_number", "رقم الأمر"), ("order_date", "التاريخ"),
             ("product_name_snapshot", "المنتج"), ("production_quantity", "الكمية")],
            self.service.search_orders, "id", parent=self,
        )
        if dialog.exec() and dialog.selected:
            self.load_order(int(dialog.selected["id"]))

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

    def _confirm_discard(self) -> bool:
        return QMessageBox.question(
            self, "تجاهل التغييرات", "هناك تغييرات غير محفوظة. هل تريد تجاهلها؟"
        ) == QMessageBox.Yes


__all__ = ["ProductionOrderPage"]
