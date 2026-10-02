"""Loading Voucher screen — سند تحميل (Model 3: البطاقات العصرية / Modern Cards).

An Arabic-first (RTL) screen for a simple single-item logistics document on the
``loading_vouchers`` table. It reuses the same visual language as the production
order / BOM / invoice screens (green toolbar, cards, RTL) in the approved *cards*
composition the user selected (Model 3):

* a **header** with the title «سند تحميل» and the document actions on one row
  (New / Search-Open / Save / Edit / Delete / Close);
* four **grouped cards**:
    - «بيانات السند»: the automatic read-only number (``LV-001``), date, time and
      the customer (picked from the ``customers`` master via a searchable popup);
    - «بيانات النقل»: driver name, vehicle number (free text) and the vehicle
      weighbridge readings before / after loading;
    - «الصنف والكمية»: the item (picked from the ``products`` master) and the
      prominent quantity in tons;
    - «ملاحظات»: a multi-line notes area.

Every business field is optional (v1): only the auto number and the date/time are
always present. The customer name and the item code/name/unit are snapshotted
server-side at save time, so an opened voucher shows exactly what was stored — the
UI values are display only and everything is re-validated in the service. Deletes
are hard deletes; there is no posting / approval workflow.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, QSize, QTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDateEdit,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.security.session_context import SESSION
from app.services.loading_voucher_service import (
    LoadingVoucherService,
    LoadingVoucherServiceError,
)
from app.ui.common.saudi_invoice_style import (
    SI_GREEN,
    button_qss,
    si_icon,
    si_pixmap,
)
from app.ui.dialogs.saudi_invoice_dialogs import EntityPickerDialog
from app.ui.screens.loading_voucher_print import (
    LoadingVoucherPreviewDialog,
    build_loading_voucher_html,
    export_loading_voucher_to_pdf,
)

# Permission codes (module "logistics", target "loading_vouchers") — mirror
# LoadingVoucherService.
PERM_VIEW = "logistics.loading_vouchers.view"
PERM_SAVE = "logistics.loading_vouchers.save"
PERM_EDIT = "logistics.loading_vouchers.edit"
PERM_DELETE = "logistics.loading_vouchers.delete"

LV_QSS = """
QWidget#lvPage { background: #F5F7FA; }
QScrollArea#lvScroll { background: #F5F7FA; border: none; }
QWidget#lvScrollBody { background: #F5F7FA; }
QFrame#card { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px; }
QFrame#headerLine { background: #E5E7EB; border: none; min-height: 1px; max-height: 1px; }
QLabel#titleLabel { color: #1F2D3D; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 22px; font-weight: 800; background: transparent; }
QLabel#subtitleLabel { color: #6B7280; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 700; background: transparent; }
QLabel#sectionTitle { color: #00843D; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 15px; font-weight: 800; background: transparent; }
QLabel { color: #1F2937; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 13px; font-weight: 700; background: transparent; }
QLabel#fieldLabel { color: #111827; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 700; background: transparent; }
QLineEdit, QDateEdit, QTimeEdit, QTextEdit {
    border: 1px solid #D7DEE7; border-radius: 6px; background: #FFFFFF;
    padding: 4px 10px; color: #111827; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 13px; font-weight: 700; min-height: 26px;
}
QLineEdit:focus, QDateEdit:focus, QTimeEdit:focus, QTextEdit:focus { border: 1px solid #00843D; }
QLineEdit:read-only { background: #F4F6F9; color: #046A31; font-weight: 800; }
QLineEdit#qtyInput { font-size: 16px; font-weight: 800; color: #046A31; }
QPushButton#lookupButton {
    background: #00843D; color: #FFFFFF; border: none; border-radius: 6px;
    font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-weight: 800;
}
QPushButton#lookupButton:hover { background: #046A31; }
"""


class LoadingVoucherPage(QWidget):
    """The Loading Voucher screen. Modes: ``view`` | ``new`` | ``edit``."""

    def __init__(
        self,
        service: LoadingVoucherService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or LoadingVoucherService(permission_check=SESSION.can)
        self._mode = "view"
        self._current: dict[str, Any] | None = None  # loaded voucher row or None
        self._customer: dict[str, Any] | None = None  # {"id","name"} or None
        self._product: dict[str, Any] | None = None    # {"id","name"} or None
        self._dirty = False
        self._busy = False  # re-entrancy guard for save/delete (nested modal loops)
        self._lookup_buttons: list[QPushButton] = []
        # Company letterhead (name/phone/address/logo) — loaded once, lazily, and
        # reused for every print/preview/PDF of this screen session.
        self._company: dict[str, Any] | None = None
        self._company_loaded = False

        # Permission snapshot (permissive when no session is loaded).
        self._perm_save = SESSION.can(PERM_SAVE)
        self._perm_edit = SESSION.can(PERM_EDIT)
        self._perm_delete = SESSION.can(PERM_DELETE)

        self.setObjectName("lvPage")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(LV_QSS)
        self.setMinimumSize(980, 560)

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
            if icon_name:
                icon_label = QLabel()
                icon_label.setPixmap(si_pixmap(icon_name, color=SI_GREEN, size=16))
                header.addWidget(icon_label)
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            header.addWidget(label)
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
        scroll.setObjectName("lvScroll")
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        body = QWidget()
        body.setObjectName("lvScrollBody")
        scroll.setWidget(body)

        self.main_layout = QVBoxLayout(body)
        self.main_layout.setContentsMargins(12, 8, 12, 10)
        self.main_layout.setSpacing(10)

        self._build_header()
        self._build_cards()

    def _build_header(self) -> None:
        container = QFrame()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(4, 0, 4, 0)
        vbox.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(si_pixmap("fa5s.truck", color=SI_GREEN, size=26))
        title_box = QWidget()
        title_v = QVBoxLayout(title_box)
        title_v.setContentsMargins(0, 0, 0, 0)
        title_v.setSpacing(2)
        self.title_label = QLabel("سند تحميل")
        self.title_label.setObjectName("titleLabel")
        self.subtitle_label = QLabel("تسجيل تحميل صنف لعميل على مركبة")
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
        self.preview_button = self._make_toolbar_button("معاينة", "preview_button", "fa5s.eye", "blue")
        self.print_button = self._make_toolbar_button("طباعة", "print_button", "fa5s.print", "gray")
        self.pdf_button = self._make_toolbar_button("تصدير PDF", "pdf_button", "fa5s.file-pdf", "red")
        self.back_button = self._make_toolbar_button("إغلاق", "back_button", "fa5s.sign-out-alt", "gray")
        for button in (self.new_button, self.search_button, self.save_button,
                       self.edit_button, self.delete_button,
                       self.preview_button, self.print_button, self.pdf_button,
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
        self.preview_button.clicked.connect(self.on_preview)
        self.print_button.clicked.connect(self.on_print)
        self.pdf_button.clicked.connect(self.on_export_pdf)
        self.back_button.clicked.connect(self.on_back)

    def _build_cards(self) -> None:
        # -- field widgets --
        self.voucher_number_value = QLineEdit()
        self.voucher_number_value.setReadOnly(True)
        self.voucher_number_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(QDate.currentDate())
        self.date_input.dateChanged.connect(self._mark_dirty)

        self.time_input = QTimeEdit()
        self.time_input.setDisplayFormat("hh:mm")
        self.time_input.setTime(QTime.currentTime())
        self.time_input.timeChanged.connect(self._mark_dirty)

        self.customer_input = QLineEdit()
        self.customer_input.setReadOnly(True)
        self.customer_input.setPlaceholderText("اختر العميل…")
        self.customer_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)

        self.driver_input = QLineEdit()
        self.driver_input.setPlaceholderText("اسم السائق")
        self.driver_input.textEdited.connect(self._mark_dirty)

        self.vehicle_input = QLineEdit()
        self.vehicle_input.setPlaceholderText("رقم السيارة")
        self.vehicle_input.textEdited.connect(self._mark_dirty)

        self.weight_before_input = QLineEdit()
        self.weight_before_input.setPlaceholderText("0.000")
        self.weight_before_input.setAlignment(Qt.AlignCenter)
        self.weight_before_input.textEdited.connect(self._mark_dirty)

        self.weight_after_input = QLineEdit()
        self.weight_after_input.setPlaceholderText("0.000")
        self.weight_after_input.setAlignment(Qt.AlignCenter)
        self.weight_after_input.textEdited.connect(self._mark_dirty)

        self.item_input = QLineEdit()
        self.item_input.setReadOnly(True)
        self.item_input.setPlaceholderText("اختر الصنف (بحث بالكود أو الاسم)…")
        self.item_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)

        self.qty_input = QLineEdit()
        self.qty_input.setObjectName("qtyInput")
        self.qty_input.setPlaceholderText("0.000")
        self.qty_input.setAlignment(Qt.AlignCenter)
        self.qty_input.textEdited.connect(self._mark_dirty)

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("ملاحظات…")
        self.notes_input.setMinimumHeight(96)
        self.notes_input.textChanged.connect(self._mark_dirty)

        # -- cards laid out in a responsive 2-column grid --
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        # Card 1 — بيانات السند
        doc_card, doc_layout = self._make_card("بيانات السند", "fa5s.file-invoice")
        doc_grid = QGridLayout()
        doc_grid.setHorizontalSpacing(12)
        doc_grid.setVerticalSpacing(8)
        doc_grid.addWidget(self._labeled("رقم السند", self.voucher_number_value), 0, 0)
        doc_grid.addWidget(self._labeled("التاريخ", self.date_input), 0, 1)
        doc_grid.addWidget(self._labeled("الوقت", self.time_input), 1, 0)
        doc_grid.addWidget(
            self._lookup_field("اسم العميل", self.customer_input, self._search_customer), 1, 1
        )
        doc_layout.addLayout(doc_grid)

        # Card 2 — بيانات النقل
        transport_card, transport_layout = self._make_card("بيانات النقل", "fa5s.truck")
        transport_grid = QGridLayout()
        transport_grid.setHorizontalSpacing(12)
        transport_grid.setVerticalSpacing(8)
        transport_grid.addWidget(self._labeled("اسم السائق", self.driver_input), 0, 0)
        transport_grid.addWidget(self._labeled("رقم السيارة", self.vehicle_input), 0, 1)
        transport_grid.addWidget(
            self._labeled("وزن السيارة قبل التحميل", self.weight_before_input), 1, 0
        )
        transport_grid.addWidget(
            self._labeled("وزن السيارة بعد التحميل", self.weight_after_input), 1, 1
        )
        transport_layout.addLayout(transport_grid)

        # Card 3 — الصنف والكمية
        item_card, item_layout = self._make_card("الصنف والكمية", "fa5s.box")
        item_layout.addWidget(
            self._lookup_field("اسم الصنف", self.item_input, self._search_item)
        )
        item_layout.addWidget(self._labeled("الكمية بالطن", self.qty_input))

        # Card 4 — ملاحظات
        notes_card, notes_layout = self._make_card("ملاحظات", "fa5s.sticky-note")
        notes_layout.addWidget(self.notes_input)

        grid.addWidget(doc_card, 0, 0)
        grid.addWidget(transport_card, 0, 1)
        grid.addWidget(item_card, 1, 0)
        grid.addWidget(notes_card, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.main_layout.addLayout(grid)
        self.main_layout.addStretch(1)

    # ======================================================================
    # Lookups (reuse the project's searchable picker — server-side search)
    # ======================================================================
    def _search_customer(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن عميل",
            [("customer_id", "الكود"), ("customer_name", "الاسم"),
             ("phone_number", "الهاتف")],
            self.service.search_customers, "customer_id", parent=self,
        )
        if not (dialog.exec() and dialog.selected):
            return
        rec = dialog.selected
        self._customer = {
            "id": rec.get("customer_id"),
            "name": str(rec.get("customer_name") or ""),
        }
        self.customer_input.setText(self._customer["name"])
        self._mark_dirty()

    def _search_item(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن صنف",
            [("item_code", "رقم الصنف"), ("item_name", "الاسم"),
             ("unit", "الوحدة"), ("price", "السعر")],
            self.service.search_products, "id", parent=self,
        )
        if not (dialog.exec() and dialog.selected):
            return
        rec = dialog.selected
        self._product = {
            "id": rec.get("id"),
            "name": str(rec.get("item_name") or ""),
        }
        self.item_input.setText(self._product["name"])
        self._mark_dirty()

    # ======================================================================
    # Modes
    # ======================================================================
    def _set_form_editable(self, editable: bool) -> None:
        self.date_input.setEnabled(editable)
        self.time_input.setEnabled(editable)
        self.driver_input.setReadOnly(not editable)
        self.vehicle_input.setReadOnly(not editable)
        self.weight_before_input.setReadOnly(not editable)
        self.weight_after_input.setReadOnly(not editable)
        self.qty_input.setReadOnly(not editable)
        self.notes_input.setReadOnly(not editable)
        for button in self._lookup_buttons:
            button.setEnabled(editable)

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

    def _clear_form(self) -> None:
        self._customer = None
        self._product = None
        self.voucher_number_value.clear()
        self.customer_input.clear()
        self.item_input.clear()
        self.driver_input.clear()
        self.vehicle_input.clear()
        self.weight_before_input.clear()
        self.weight_after_input.clear()
        self.qty_input.clear()
        self.notes_input.clear()
        self.date_input.setDate(QDate.currentDate())
        self.time_input.setTime(QTime.currentTime())
        self._dirty = False

    def _populate_reserved_number(self) -> None:
        try:
            number = self.service.reserve_voucher_number()
        except Exception:  # noqa: BLE001
            QMessageBox.warning(
                self, "تعذّر إنشاء الرقم",
                "تعذّر إنشاء رقم سند تلقائيًا. حاول مرة أخرى.",
            )
            number = ""
        self.voucher_number_value.setText(str(number))

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
    # Load an existing voucher (from stored snapshots)
    # ======================================================================
    def load_voucher(self, voucher_id: int) -> None:
        loaded = None
        try:
            loaded = self.service.load(voucher_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطأ", str(exc))
            return
        if not loaded:
            QMessageBox.warning(self, "غير موجود", "تعذّر تحميل السند.")
            return
        self._current = loaded

        self.voucher_number_value.setText(loaded.get("voucher_number") or "")
        voucher_date = loaded.get("voucher_date")
        if voucher_date is not None:
            self.date_input.setDate(
                QDate(voucher_date.year, voucher_date.month, voucher_date.day)
            )
        voucher_time = loaded.get("voucher_time")
        if voucher_time is not None:
            self.time_input.setTime(QTime(voucher_time.hour, voucher_time.minute))

        customer_id = loaded.get("customer_id")
        customer_name = loaded.get("customer_name_snapshot") or ""
        self._customer = {"id": customer_id, "name": customer_name} if customer_id else None
        self.customer_input.setText(customer_name)

        product_id = loaded.get("product_id")
        item_name = loaded.get("item_name_snapshot") or ""
        self._product = {"id": product_id, "name": item_name} if product_id else None
        self.item_input.setText(item_name)

        self.driver_input.setText(loaded.get("driver_name") or "")
        self.vehicle_input.setText(loaded.get("vehicle_number") or "")
        # Weights are free text — show exactly what was stored.
        self.weight_before_input.setText(loaded.get("weight_before_loading") or "")
        self.weight_after_input.setText(loaded.get("weight_after_loading") or "")
        quantity = loaded.get("quantity_tons")
        self.qty_input.setText(self._fmt_qty(quantity) if quantity is not None else "")
        self.notes_input.setPlainText(loaded.get("notes") or "")

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
            "voucher_number": self.voucher_number_value.text(),
            "voucher_date": self.date_input.date().toPython(),
            "voucher_time": self.time_input.time().toPython(),
            "customer_id": self._customer.get("id") if self._customer else None,
            "driver_name": self.driver_input.text(),
            "vehicle_number": self.vehicle_input.text(),
            "weight_before_loading": self.weight_before_input.text(),
            "weight_after_loading": self.weight_after_input.text(),
            "product_id": self._product.get("id") if self._product else None,
            "quantity_tons": self.qty_input.text(),
            "notes": self.notes_input.toPlainText(),
        }

    def _company_letterhead(self) -> dict[str, Any]:
        """The first registered company's letterhead, fetched once and cached."""
        if not self._company_loaded:
            try:
                self._company = self.service.get_company_letterhead()
            except Exception:  # noqa: BLE001 - letterhead is optional
                self._company = None
            self._company_loaded = True
        return self._company or {}

    def _collect_print_data(self) -> dict[str, Any]:
        """Snapshot the current form for the printable voucher (works pre-save)."""
        return {
            "number": self.voucher_number_value.text(),
            "date": self.date_input.date().toString("yyyy-MM-dd"),
            "time": self.time_input.time().toString("hh:mm"),
            "customer_name": self.customer_input.text(),
            "driver_name": self.driver_input.text(),
            "vehicle_number": self.vehicle_input.text(),
            "item_name": self.item_input.text(),
            "quantity_tons": self.qty_input.text(),
            "weight_before": self.weight_before_input.text(),
            "weight_after": self.weight_after_input.text(),
            "notes": self.notes_input.toPlainText(),
            "company": self._company_letterhead(),
        }

    def on_preview(self) -> None:
        """Open the on-screen preview (with its own طباعة / تصدير PDF buttons)."""
        LoadingVoucherPreviewDialog(
            self._collect_print_data(), parent=self,
            html_builder=build_loading_voucher_html,
        ).exec()

    def on_print(self) -> None:
        """Print directly via the system print dialog (renders off-screen)."""
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, "الطباعة", "خدمة الطباعة غير متاحة.")
            return
        from PySide6.QtGui import QPageSize
        from PySide6.QtWebEngineWidgets import QWebEngineView

        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        if QPrintDialog(printer, self).exec() != QPrintDialog.Accepted:
            return

        view = QWebEngineView(self)
        view.setVisible(False)
        holder = getattr(self, "_lv_print_views", None)
        if holder is None:
            holder = []
            self._lv_print_views = holder
        holder.append((view, printer))

        def _on_load(ok: bool) -> None:
            if not ok:
                QMessageBox.warning(self, "الطباعة", "تعذّر تجهيز مستند السند.")
                _cleanup()
                return

            def _done(_success: bool) -> None:
                _cleanup()

            view.printFinished.connect(_done)
            view.print(printer)

        def _cleanup() -> None:
            try:
                holder.remove((view, printer))
            except ValueError:
                pass
            view.deleteLater()

        view.loadFinished.connect(_on_load)
        view.setHtml(build_loading_voucher_html(self._collect_print_data()))

    def on_export_pdf(self) -> None:
        """Export the voucher straight to a PDF file (no preview window)."""
        export_loading_voucher_to_pdf(
            self, self._collect_print_data(),
            html_builder=build_loading_voucher_html,
        )

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
                    saved = self.service.create_voucher(
                        form, user_id=self._current_user_id()
                    )
                else:
                    saved = self.service.update_voucher(
                        self._current["id"], form, user_id=self._current_user_id()
                    )
            except LoadingVoucherServiceError as exc:
                QMessageBox.warning(self, "تعذّر الحفظ", exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "خطأ", str(exc))
                return
            # Reload (→ view mode, Save disabled) BEFORE announcing success, so the
            # message's nested loop can never re-trigger a save.
            self.load_voucher(saved["id"])
            QMessageBox.information(self, "تم", "تم حفظ السند.")
        finally:
            self._busy = False

    def on_delete(self) -> None:
        if self._current is None or self._busy:
            return
        if QMessageBox.question(
            self, "تأكيد الحذف", "هل تريد حذف هذا السند؟"
        ) != QMessageBox.Yes:
            return
        self._busy = True
        try:
            try:
                self.service.delete_voucher(
                    self._current["id"], user_id=self._current_user_id()
                )
            except LoadingVoucherServiceError as exc:
                QMessageBox.warning(self, "تعذّر الحذف", exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "خطأ", str(exc))
                return
            # Reset to a clean state BEFORE announcing success (see on_save).
            self.enter_ready_mode()
            QMessageBox.information(self, "تم", "تم حذف السند.")
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
            "بحث عن سند تحميل",
            [("voucher_number", "رقم السند"), ("voucher_date", "التاريخ"),
             ("customer_name_snapshot", "العميل"), ("item_name_snapshot", "الصنف"),
             ("quantity_tons", "الكمية")],
            self.service.search_vouchers, "id", parent=self,
        )
        if dialog.exec() and dialog.selected:
            self.load_voucher(int(dialog.selected["id"]))

    # ======================================================================
    # Helpers
    # ======================================================================
    @staticmethod
    def _fmt_qty(value: Any) -> str:
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except (InvalidOperation, TypeError, ValueError):
            return str(value or "")

    def _mark_dirty(self, *_a) -> None:
        self._dirty = True

    def _confirm_discard(self) -> bool:
        return QMessageBox.question(
            self, "تجاهل التغييرات", "هناك تغييرات غير محفوظة. هل تريد تجاهلها؟"
        ) == QMessageBox.Yes


__all__ = ["LoadingVoucherPage"]
