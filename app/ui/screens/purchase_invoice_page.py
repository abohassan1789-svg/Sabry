"""Purchase-invoice screen (فاتورة المشتريات).

An Arabic-first (RTL) screen for creating and managing purchase invoices on the
``purchase_invoice*`` tables. It reuses the same visual language as the Saudi
sales-invoice screen (cards, toolbar, live clock, adaptive density) but is a
plain count/weight document: **no VAT, no ZATCA/Phase-2 data and no print /
preview / PDF pipeline** — those are the deliberate differences.

Header fields: invoice number (auto "Pur-…", editable), issue date/time, supplier
(from the suppliers master data) and payment type (نقدي / آجل). نوع الحساب is
tracked internally from the supplier but hidden from the screen. Each line carries
a code (كود الصنف), a name (اسم الصنف), a unit (الوحدة), a quantity (الكمية) and a
price (السعر); the screen derives الإجمالي (quantity × price) per line. The single
invoice total is إجمالي الفاتورة (Σ الإجمالي). Weight is no longer captured on this
screen; the underlying weight columns stay in the database (defaulting to zero) so
the purchase reports and supplier statements keep working. All figures are
recomputed server-side on save; the UI totals are display only.
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, QDateTime, QEvent, Qt, QTime, QTimer, QSize
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.purchase_invoice import (
    MAX_ITEM_NAME_LEN,
    PAYMENT_CASH,
    PAYMENT_CREDIT,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_LABELS_AR,
)
from app.security.session_context import SESSION
from app.services.purchase_invoice_service import (
    PurchaseInvoiceError,
    PurchaseInvoiceService,
)
from app.ui.common.saudi_invoice_style import (
    SI_GREEN,
    button_qss,
    si_icon,
    si_pixmap,
    style_button,
)
from app.ui.dialogs.purchase_invoice_dialogs import (
    EntityPickerDialog,
    PurchaseInvoiceSearchDialog,
)

# Column indices for the details table: كود الصنف، اسم الصنف، الوحدة، الكمية،
# السعر، الإجمالي.
(COL_CODE, COL_NAME, COL_UNIT, COL_QTY, COL_PRICE, COL_TOTAL) = range(6)
COLUMN_COUNT = 6

# The columns the user can type into (الإجمالي is derived and read-only).
_EDITABLE_COLS = (COL_CODE, COL_NAME, COL_UNIT, COL_QTY, COL_PRICE)

# First row of the supplier combo; carries None as its data.
COMBO_PLACEHOLDER = "— اختر —"

PURCHASE_INVOICE_QSS = """
QWidget#purchaseInvoicePage { background: #F5F7FA; }
QScrollArea#purchaseScroll { background: #F5F7FA; border: none; }
QWidget#purchaseScrollBody { background: #F5F7FA; }

QFrame#card { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px; }
QFrame#headerCard { background: transparent; border: none; }
QFrame#headerLine { background: #E5E7EB; border: none; min-height: 1px; max-height: 1px; }

QLabel#titleLabel { color: #1F2D3D; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 22px; font-weight: 800; background: transparent; }
QLabel#subtitleLabel { color: #6B7280; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 700; background: transparent; }
QLabel#metaLabel { color: #6B7280; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 700; background: transparent; }
QLabel#sectionTitle { color: #00843D; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 15px; font-weight: 800; background: transparent; }
QLabel { color: #1F2937; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 13px; font-weight: 700; background: transparent; }
QLabel#fieldLabel { min-height: 16px; max-height: 16px; color: #111827; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 700; background: transparent; }

QLineEdit, QComboBox, QDateTimeEdit {
    min-height: 26px; max-height: 28px;
    border: 1px solid #D7DEE7; border-radius: 6px; background: #FFFFFF;
    padding: 1px 8px; color: #111827; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 700;
}
QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus { border: 1px solid #00843D; }
QLineEdit:read-only { background: #F4F6F9; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    border: 1px solid #D7DEE7; background: #FFFFFF;
    selection-background-color: #00843D; selection-color: #FFFFFF; outline: none;
}
QDateTimeEdit::drop-down { border: none; width: 22px; }

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

QFrame#netBox { background: #E8F5EC; border: 1px solid #BFE6CF; border-radius: 10px; }
QLabel#netLabel { color: #00843D; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 12px; font-weight: 800; background: transparent; }

QLineEdit#invoice_total_value {
    background: transparent; border: none; color: #00843D;
    font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 14px; font-weight: 800; min-height: 40px; padding: 0 2px;
}

QTextEdit {
    border: 1px solid #D7DEE7; border-radius: 10px; background: #FFFFFF;
    color: #111827; font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-size: 13px; font-weight: 700; padding: 6px;
}
QTextEdit:focus { border: 1px solid #00843D; }

QPushButton#lookupButton {
    background: #00843D; color: #FFFFFF; border: none; border-radius: 6px;
    font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-weight: 800;
}
QPushButton#lookupButton:hover { background: #046A31; }
QPushButton#searchButton {
    background: #00843D; color: #FFFFFF; border: none; border-radius: 8px;
    font-family: 'Cairo', 'Segoe UI', 'Tahoma', 'Arial'; font-weight: 800;
}
QPushButton#searchButton:hover { background: #046A31; }
"""

# Density (mirrors the sales screen: a maximised window on a 768px screen leaves
# the page ~680px, so compact has to start at 760).
COMPACT_BELOW_HEIGHT = 760
ROW_HEIGHT, COMPACT_ROW_HEIGHT = 44, 32
TABLE_HEADER, COMPACT_TABLE_HEADER = 50, 40
CARD_MARGINS, COMPACT_CARD_MARGINS = (18, 12, 18, 14), (12, 6, 12, 8)
CARD_SPACING, COMPACT_CARD_SPACING = 8, 4

# Icon (15) + gap (6) + padding (7 each side) + border (1 each side).
_BTN_CHROME = 15 + 6 + 2 * 7 + 2
_TOOLBAR_FONT: QFont | None = None


def _toolbar_metrics() -> QFontMetrics:
    """Metrics for the exact font the toolbar stylesheet paints with."""
    global _TOOLBAR_FONT
    if _TOOLBAR_FONT is None:
        font = QFont()
        font.setFamilies(["Cairo", "Segoe UI", "Tahoma", "Arial"])
        font.setPixelSize(12)
        font.setWeight(QFont.Bold)
        _TOOLBAR_FONT = font
    return QFontMetrics(_TOOLBAR_FONT)


class PurchaseInvoicePage(QWidget):
    """The purchase-invoice screen. Modes: ``view`` | ``new`` | ``edit``."""

    def __init__(
        self,
        service: PurchaseInvoiceService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or PurchaseInvoiceService(permission_check=SESSION.can)
        self._mode = "view"
        self._current: dict[str, Any] | None = None  # loaded invoice dict
        self._current_status = STATUS_DRAFT
        self._dirty = False
        self._post_save = False
        self._suspend_cell_signal = False
        self._compact: bool | None = None
        self._cards: list[QVBoxLayout] = []

        self.setObjectName("purchaseInvoicePage")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(PURCHASE_INVOICE_QSS)
        self.setMinimumSize(1212, 560)

        self._build_ui()
        self._load_master_combos()
        self._start_clock()
        self.enter_ready_mode()

    # ======================================================================
    # Small builders / helpers
    # ======================================================================
    def _make_card(self, title: str | None = None, icon_name: str | None = None):
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(14)
        shadow.setColor(QColor(15, 23, 42, 22))
        shadow.setOffset(0, 2)
        card.setGraphicsEffect(shadow)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(*CARD_MARGINS)
        layout.setSpacing(CARD_SPACING)
        self._cards.append(layout)
        if title:
            header = QHBoxLayout()
            header.setSpacing(8)
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            header.addWidget(label)
            if icon_name:
                icon_label = QLabel()
                icon_label.setPixmap(si_pixmap(icon_name, color=SI_GREEN, size=18))
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

    def _lookup_field(self, label_text: str, combo: QComboBox, on_search) -> QWidget:
        """A combo + small green search button, wrapped under a field label."""
        combo.setLayoutDirection(Qt.RightToLeft)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(4)
        hbox.addWidget(combo, 1)
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
        button.setCursor(Qt.PointingHandCursor)
        button.setIconSize(QSize(15, 15))
        button.setIcon(si_icon(icon_name, color="#FFFFFF" if kind != "white" else "#374151"))
        button.setStyleSheet(button_qss(kind) + "QPushButton { padding:3px 7px; }")
        width = _toolbar_metrics().horizontalAdvance(str(text)) + _BTN_CHROME
        button.setMinimumWidth(max(58, width))
        return button

    # ======================================================================
    # UI assembly
    # ======================================================================
    def _build_ui(self) -> None:
        self._lookup_buttons: list[QPushButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("purchaseScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer.addWidget(scroll)

        body = QWidget()
        body.setObjectName("purchaseScrollBody")
        scroll.setWidget(body)

        self.main_layout = QVBoxLayout(body)
        self.main_layout.setContentsMargins(12, 6, 12, 8)
        self.main_layout.setSpacing(6)

        self._build_header()
        self._build_invoice_card()
        self._build_details_row()
        self._build_quick_entry_card()
        self._build_notes_field()  # hidden — notes still round-trip

    def _build_header(self) -> None:
        container = QFrame()
        container.setObjectName("headerCard")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(4, 0, 4, 0)
        vbox.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(12)

        title_box = QWidget()
        title_v = QVBoxLayout(title_box)
        title_v.setContentsMargins(0, 0, 0, 0)
        title_v.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(si_pixmap("fa5s.file-invoice", color=SI_GREEN, size=26))
        self.title_label = QLabel("فاتورة المشتريات")
        self.title_label.setObjectName("titleLabel")
        title_row.addWidget(icon)
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        self.subtitle_label = QLabel("إنشاء وإدارة فواتير المشتريات")
        self.subtitle_label.setObjectName("subtitleLabel")
        title_v.addLayout(title_row)
        title_v.addWidget(self.subtitle_label)
        top.addWidget(title_box)
        top.addStretch(1)

        meta_box = QWidget()
        self.meta_grid = QGridLayout(meta_box)
        self.meta_grid.setContentsMargins(0, 0, 0, 0)
        self.meta_grid.setSpacing(2)
        self.user_label = QLabel("")
        self.date_label = QLabel("")
        self.time_label = QLabel("")
        for label in (self.user_label, self.date_label, self.time_label):
            label.setObjectName("metaLabel")
            label.setMinimumWidth(150)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter | Qt.AlignAbsolute)
        self._lay_out_meta(stacked=True)
        top.addWidget(meta_box)
        vbox.addLayout(top)

        # -- toolbar strip: all actions on ONE row (RTL: first added sits right) --
        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)
        self.search_button = QPushButton()
        self.search_button.setObjectName("searchButton")
        self.search_button.setIcon(si_icon("fa5s.search", color="#FFFFFF"))
        self.search_button.setIconSize(QSize(16, 16))
        self.search_button.setFixedSize(38, 38)
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.setToolTip("بحث عن فاتورة (F1)")
        self.new_button = self._make_toolbar_button("جديد", "new_button", "fa5s.plus", "green")
        self.duplicate_button = self._make_toolbar_button(
            "تكرار الفاتورة", "duplicate_button", "fa5s.copy", "green"
        )
        self.save_button = self._make_toolbar_button("حفظ", "save_button", "fa5s.save", "green")
        self.edit_button = self._make_toolbar_button("تعديل", "edit_button", "fa5s.pen", "blue")
        self.update_button = self._make_toolbar_button("تحديث", "update_button", "fa5s.sync", "blue")
        self.approve_button = self._make_toolbar_button("اعتماد الفاتورة", "approve_button", "fa5s.check-double", "blue")
        self.delete_button = self._make_toolbar_button("حذف", "delete_button", "fa5s.trash", "red")
        self.delete_all_button = self._make_toolbar_button("حذف الكل", "delete_all_button", "fa5s.trash-alt", "red")
        self.cancel_button = self._make_toolbar_button("إلغاء", "cancel_button", "fa5s.times", "white")
        self.back_button = self._make_toolbar_button("خروج", "back_button", "fa5s.sign-out-alt", "gray")
        for button in (self.search_button,
                       self.new_button, self.duplicate_button, self.save_button,
                       self.edit_button, self.update_button, self.approve_button,
                       self.delete_button, self.delete_all_button,
                       self.cancel_button, self.back_button):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        vbox.addLayout(toolbar)

        line = QFrame()
        line.setObjectName("headerLine")
        vbox.addWidget(line)

        self.main_layout.addWidget(container)
        self._wire_actions()

    def _build_invoice_card(self) -> None:
        card = QFrame()
        card.setObjectName("headerCard")
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(4, 2, 4, 2)
        vbox.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        label = QLabel("بيانات الفاتورة")
        label.setObjectName("sectionTitle")
        icon = QLabel()
        icon.setPixmap(si_pixmap("fa5s.calendar-alt", color=SI_GREEN, size=16))
        title_row.addWidget(label)
        title_row.addWidget(icon)
        title_row.addStretch(1)
        vbox.addLayout(title_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)

        # RTL: column 0 is rightmost.
        self.invoice_number_input = QLineEdit()
        self.invoice_number_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        self.invoice_number_input.textEdited.connect(self._mark_dirty)

        self.issue_datetime_input = QDateTimeEdit()
        self.issue_datetime_input.setCalendarPopup(True)
        self.issue_datetime_input.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.issue_datetime_input.setDateTime(QDateTime.currentDateTime())
        self.issue_datetime_input.dateTimeChanged.connect(self._mark_dirty)

        self.supplier_combo = QComboBox()
        self.supplier_combo.currentIndexChanged.connect(self._on_supplier_changed)

        # نوع الحساب: still tracked internally from the chosen supplier (عدد / وزن)
        # so the value round-trips, but the field is HIDDEN from the screen. The
        # widget is never added to a layout, so it renders nowhere.
        self.supplier_account_type_display = QLineEdit()
        self.supplier_account_type_display.setReadOnly(True)
        self.supplier_account_type_display.setVisible(False)

        self.payment_combo = QComboBox()
        self.payment_combo.setLayoutDirection(Qt.RightToLeft)
        self.payment_combo.addItem("نقدي", PAYMENT_CASH)
        self.payment_combo.addItem("آجل", PAYMENT_CREDIT)
        self.payment_combo.currentIndexChanged.connect(self._mark_dirty)

        grid.addWidget(self._labeled("رقم الفاتورة", self.invoice_number_input), 0, 0)
        grid.addWidget(self._labeled("التاريخ والوقت", self.issue_datetime_input), 0, 1)
        grid.addWidget(self._lookup_field("اسم المورد", self.supplier_combo, self._search_supplier), 0, 2)
        grid.addWidget(self._labeled("نوع الدفع", self.payment_combo), 0, 3)

        for col in range(4):
            grid.setColumnStretch(col, 1)
            grid.setColumnMinimumWidth(col, 200)
        vbox.addLayout(grid)
        self.main_layout.addWidget(card)

    def _build_details_row(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(16)

        details_card, details_layout = self._make_card("تفاصيل الفاتورة", "fa5s.list-ul")
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
        self.lines_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.lines_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.lines_table.setMinimumHeight(TABLE_HEADER + 3 * ROW_HEIGHT)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.cellChanged.connect(self._on_cell_changed)
        details_layout.addWidget(self.lines_table, 1)

        # Totals panel (fixed 340px, on the right under RTL) — a single total:
        # إجمالي الفاتورة (Σ الإجمالي per line).
        totals_card, totals_layout = self._make_card("الإجماليات", "fa5s.chart-pie")
        totals_card.setFixedWidth(340)
        totals_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        net_box = QFrame()
        net_box.setObjectName("netBox")
        net_box.setFixedHeight(56)
        net_h = QHBoxLayout(net_box)
        net_h.setContentsMargins(14, 8, 14, 8)
        net_label = QLabel("إجمالي الفاتورة")
        net_label.setObjectName("netLabel")
        self.invoice_total_value = QLineEdit("0.00")
        self.invoice_total_value.setObjectName("invoice_total_value")
        self.invoice_total_value.setReadOnly(True)
        self.invoice_total_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        net_h.addWidget(net_label)
        net_h.addWidget(self.invoice_total_value, 1)
        totals_layout.addWidget(net_box)
        totals_layout.addStretch(1)
        # RTL: add the totals card FIRST so it sits on the right.
        row.addWidget(totals_card)
        row.addWidget(details_card, 1)

        self.main_layout.addLayout(row, 3)

    def _build_quick_entry_card(self) -> None:
        card, layout = self._make_card("إضافة صنف", "fa5s.tag")
        card.setMaximumHeight(136)
        self.quick_entry_card = card
        row = QHBoxLayout()
        row.setSpacing(10)

        self.item_name_input = QLineEdit()
        self.item_name_input.setMinimumWidth(280)
        self.item_name_input.setPlaceholderText("اكتب اسم الصنف أو ابحث…")
        self.item_name_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        # اسم الصنف + a green search button that opens the multi-select أصناف popup.
        name_row = QWidget()
        name_hbox = QHBoxLayout(name_row)
        name_hbox.setContentsMargins(0, 0, 0, 0)
        name_hbox.setSpacing(4)
        name_hbox.addWidget(self.item_name_input, 1)
        item_search_button = QPushButton()
        item_search_button.setObjectName("lookupButton")
        item_search_button.setIcon(si_icon("fa5s.search", color="#FFFFFF"))
        item_search_button.setFixedSize(28, 28)
        item_search_button.setCursor(Qt.PointingHandCursor)
        item_search_button.setToolTip("بحث عن صنف (اختيار متعدد)")
        item_search_button.clicked.connect(self._search_item)
        self._lookup_buttons.append(item_search_button)
        name_hbox.addWidget(item_search_button)
        name_field = self._labeled("اسم الصنف", name_row)
        name_field.setMinimumWidth(320)

        self.unit_input = QLineEdit("")
        self.unit_input.setMinimumWidth(100)
        self.unit_input.setPlaceholderText("الوحدة")
        self.unit_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        self.count_input = QLineEdit("1")
        self.count_input.setMinimumWidth(100)
        self.count_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        self.price_input = QLineEdit("0")
        self.price_input.setMinimumWidth(110)
        self.price_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)

        self.add_line_button = QPushButton("إضافة إلى الفاتورة")
        self.add_line_button.setIcon(si_icon("fa5s.plus", color="#FFFFFF"))
        self.add_line_button.setIconSize(QSize(18, 18))
        self.add_line_button.setFixedHeight(36)
        self.add_line_button.setMinimumWidth(170)
        self.add_line_button.setCursor(Qt.PointingHandCursor)
        style_button(self.add_line_button, "green")
        self.add_line_button.clicked.connect(self._on_add_line)

        self.new_line_button = QPushButton("سطر جديد")
        self.new_line_button.setIcon(si_icon("fa5s.pen", color="#374151"))
        self.new_line_button.setIconSize(QSize(16, 16))
        self.new_line_button.setFixedHeight(36)
        self.new_line_button.setMinimumWidth(120)
        self.new_line_button.setCursor(Qt.PointingHandCursor)
        self.new_line_button.setToolTip("إضافة سطر فارغ تكتب فيه الصنف مباشرةً")
        style_button(self.new_line_button, "white")
        self.new_line_button.clicked.connect(self._on_new_free_line)

        self.remove_line_button = QPushButton("حذف الصنف")
        self.remove_line_button.setIcon(si_icon("fa5s.trash", color="#DC2626"))
        self.remove_line_button.setFixedHeight(36)
        self.remove_line_button.setMinimumWidth(130)
        self.remove_line_button.setCursor(Qt.PointingHandCursor)
        style_button(self.remove_line_button, "white")
        self.remove_line_button.clicked.connect(self._on_remove_line)

        row.addWidget(name_field, 1)
        row.addWidget(self._labeled("الوحدة", self.unit_input))
        row.addWidget(self._labeled("الكمية", self.count_input))
        row.addWidget(self._labeled("السعر", self.price_input))
        row.addWidget(self.add_line_button)
        row.addWidget(self.new_line_button)
        row.addWidget(self.remove_line_button)
        layout.addLayout(row)
        self.main_layout.addWidget(card)

    def _build_notes_field(self) -> None:
        # Hidden, but notes are a real column — keep the widget so save/load
        # round-trip the value.
        self.notes_input = QTextEdit()
        self.notes_input.setLayoutDirection(Qt.RightToLeft)
        self.notes_input.setVisible(False)
        self.notes_input.textChanged.connect(self._mark_dirty)

    # ======================================================================
    # Wiring / clock
    # ======================================================================
    def _wire_actions(self) -> None:
        self.search_button.clicked.connect(self.open_search)
        self.new_button.clicked.connect(self.on_new)
        self.duplicate_button.clicked.connect(self.on_duplicate)
        self.save_button.clicked.connect(self.on_save)
        self.edit_button.clicked.connect(self.on_edit)
        self.update_button.clicked.connect(self.on_update)
        self.approve_button.clicked.connect(self.on_approve)
        self.delete_button.clicked.connect(self.on_delete)
        self.delete_all_button.clicked.connect(self.on_delete_all)
        self.cancel_button.clicked.connect(self.on_cancel)
        self.back_button.clicked.connect(self.on_back)

    def _start_clock(self) -> None:
        user = SESSION.user or {}
        name = user.get("full_name") or user.get("username") or "مستخدم النظام"
        self.user_label.setText(f"المستخدم: {name}")
        self._tick_clock()
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start()

    def _tick_clock(self) -> None:
        now = datetime.datetime.now()
        self.date_label.setText(f"التاريخ: {now:%Y-%m-%d}")
        self.time_label.setText(f"الوقت: {now:%H:%M:%S}")

    # ======================================================================
    # Supplier combo
    # ======================================================================
    @staticmethod
    def _supplier_label(row: dict) -> str:
        return (row.get("supplier_name") or "") + f"  ({row.get('supplier_id')})"

    def _load_master_combos(self) -> None:
        self._fill_combo(self.supplier_combo, self._safe(self.service.list_suppliers),
                         "supplier_id", self._supplier_label)

    def refresh_master_data(self) -> None:
        """Re-read suppliers into the combo, preserving the current pick."""
        self._refill_preserving(self.supplier_combo, self._safe(self.service.list_suppliers),
                                "supplier_id", self._supplier_label)

    def _refill_preserving(self, combo: QComboBox, rows, id_key, label_fn) -> None:
        previous = combo.currentData()
        self._fill_combo(combo, rows, id_key, label_fn)
        if isinstance(previous, dict):
            self._ensure_combo_record(combo, previous, label_fn(previous), id_key)

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:
            return []

    def _fill_combo(self, combo: QComboBox, rows, id_key, label_fn) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(COMBO_PLACEHOLDER, None)
        for row in rows:
            combo.addItem(label_fn(row), row)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _ensure_combo_record(
        self, combo: QComboBox, record: dict, label: str, id_key: str
    ) -> None:
        """Select the combo row whose ``id_key`` matches ``record``'s (append if absent)."""
        target_id = record.get(id_key)
        combo.blockSignals(True)
        found = -1
        if target_id is not None:
            for i in range(combo.count()):
                data = combo.itemData(i)
                if isinstance(data, dict) and data.get(id_key) == target_id:
                    found = i
                    break
        if found < 0:
            combo.addItem(label, record)
            found = combo.count() - 1
        combo.setCurrentIndex(found)
        combo.blockSignals(False)

    def _search_supplier(self) -> None:
        dialog = EntityPickerDialog(
            "بحث عن المورد",
            [("supplier_id", "الكود"), ("supplier_name", "الاسم"), ("mobile", "الجوال")],
            self.service.search_suppliers, "supplier_id", parent=self,
        )
        if dialog.exec() and dialog.selected:
            rec = dialog.selected
            self._ensure_combo_record(
                self.supplier_combo, rec, self._supplier_label(rec), "supplier_id"
            )
            self._on_supplier_changed()

    def _search_item(self) -> None:
        """Open the multi-select أصناف popup; every ticked product becomes a line."""
        dialog = EntityPickerDialog(
            "بحث عن الصنف",
            [("item_code", "رقم الصنف"), ("item_name", "الاسم"), ("price", "السعر")],
            self.service.search_products, "id", parent=self, multi_select=True,
        )
        if not (dialog.exec() and dialog.selected_rows):
            return
        # Each picked product is added with quantity 1 and its list price, carrying
        # the product's كود الصنف and الوحدة; the user then edits quantity/price in
        # the lines table.
        for rec in dialog.selected_rows:
            try:
                price = Decimal(str(rec["price"])) if rec.get("price") is not None else Decimal("0")
            except (InvalidOperation, TypeError, ValueError):
                price = Decimal("0")
            self._append_line(
                name=str(rec.get("item_name") or ""),
                count=Decimal("1"), price=price,
                item_code=rec.get("item_code"),
                unit=str(rec.get("unit") or ""),
            )
        self.item_name_input.clear()
        self._mark_dirty()

    def _update_supplier_account_type(self) -> None:
        """Show the selected supplier's account type (نوع الحساب) automatically."""
        data = self.supplier_combo.currentData()
        account_type = data.get("account_type") if isinstance(data, dict) else None
        self.supplier_account_type_display.setText(account_type or "")

    def _on_supplier_changed(self, *_a) -> None:
        self._update_supplier_account_type()
        self._mark_dirty()

    # ======================================================================
    # Table lines
    # ======================================================================
    def _on_new_free_line(self) -> None:
        """Append an empty row and start typing the item straight into it."""
        if self._mode not in ("new", "edit"):
            return
        self._append_line(name="", count=Decimal("1"), price=Decimal("0"))
        row = self.lines_table.rowCount() - 1
        self.lines_table.setCurrentCell(row, COL_NAME)
        self.lines_table.editItem(self.lines_table.item(row, COL_NAME))
        self._mark_dirty()

    def _on_add_line(self) -> None:
        name = self.item_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "تنبيه", "اكتب اسم الصنف أولًا.")
            return
        if len(name) > MAX_ITEM_NAME_LEN:
            QMessageBox.warning(
                self, "قيمة غير صالحة",
                f"اسم الصنف يجب ألا يزيد عن {MAX_ITEM_NAME_LEN} حرفًا.",
            )
            return
        try:
            count = self._parse(self.count_input.text(), "الكمية")
            price = self._parse(self.price_input.text(), "السعر")
        except ValueError as exc:
            QMessageBox.warning(self, "قيمة غير صالحة", str(exc))
            return
        if count <= 0:
            QMessageBox.warning(self, "تنبيه", "الكمية يجب أن تكون أكبر من صفر.")
            return
        if price < 0:
            QMessageBox.warning(self, "تنبيه", "السعر لا يمكن أن يكون سالبًا.")
            return
        self._append_line(
            name=name, count=count, price=price, unit=self.unit_input.text().strip()
        )
        self.item_name_input.clear()
        self.unit_input.clear()
        self.count_input.setText("1")
        self.price_input.setText("0")
        self.item_name_input.setFocus()
        self._mark_dirty()

    def _append_line(self, *, name, count, price, item_code=None, unit="") -> None:
        meta = {
            "item_code": self._fmt_code(item_code), "item_name": name,
            "unit": unit or "", "count": count, "price": price,
            "line_id": None,
        }
        r = self.lines_table.rowCount()
        self.lines_table.insertRow(r)
        for c in range(COLUMN_COUNT):
            self.lines_table.setItem(r, c, QTableWidgetItem(""))
        self._write_row(r, meta)
        self._refresh_totals()

    def _write_row(self, r: int, meta: dict) -> None:
        # الوزن is not captured on this screen; lines are computed with zero weight
        # so الإجمالي == الكمية × السعر (count_price_total).
        amounts = self.service.compute_line_amounts(meta["count"], Decimal("0"), meta["price"])
        meta["total"] = amounts["count_price_total"]
        editable = self._mode in ("new", "edit")
        self._suspend_cell_signal = True
        try:
            cells = {
                COL_CODE: meta.get("item_code", ""),
                COL_NAME: meta["item_name"],
                COL_UNIT: meta.get("unit", ""),
                COL_QTY: self._fmt_qty(meta["count"]),
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
        name_item = self.lines_table.item(row, COL_NAME)
        value_item = self.lines_table.item(row, col)
        if name_item is None or value_item is None:
            return
        meta = name_item.data(Qt.UserRole)
        if not meta:
            return
        text = value_item.text()
        if col == COL_NAME:
            self._edit_name(row, meta, text)
            return
        if col == COL_CODE:
            meta["item_code"] = self._fmt_code(text)
            self._write_row(row, meta)
            self._mark_dirty()
            return
        if col == COL_UNIT:
            meta["unit"] = (text or "").strip()[:50]
            self._write_row(row, meta)
            self._mark_dirty()
            return
        try:
            value = self._parse(text, "القيمة")
            if col == COL_QTY and value <= 0:
                raise ValueError("الكمية يجب أن تكون أكبر من صفر.")
            if col == COL_PRICE and value < 0:
                raise ValueError("السعر لا يمكن أن يكون سالبًا.")
        except ValueError as exc:
            QMessageBox.warning(self, "قيمة غير صالحة", str(exc))
            self._write_row(row, meta)  # revert to previous good value
            return
        key = {COL_QTY: "count", COL_PRICE: "price"}[col]
        meta[key] = value
        self._write_row(row, meta)
        self._refresh_totals()
        self._mark_dirty()

    def _edit_name(self, row: int, meta: dict, text: str) -> None:
        value = (text or "").strip()
        if len(value) > MAX_ITEM_NAME_LEN:
            QMessageBox.warning(
                self, "قيمة غير صالحة",
                f"اسم الصنف يجب ألا يزيد عن {MAX_ITEM_NAME_LEN} حرفًا.",
            )
            self._write_row(row, meta)  # revert
            return
        meta["item_name"] = value
        self._write_row(row, meta)
        self._mark_dirty()

    def _on_remove_line(self) -> None:
        row = self.lines_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "تنبيه", "اختر سطرًا لحذفه.")
            return
        self.lines_table.removeRow(row)
        self._refresh_totals()
        self._mark_dirty()

    def _refresh_totals(self) -> None:
        lines = []
        for r in range(self.lines_table.rowCount()):
            meta = self.lines_table.item(r, COL_NAME).data(Qt.UserRole)
            if meta:
                lines.append({
                    "count_price_total": meta["total"],
                    "weight_price_total": Decimal("0"),
                })
        totals = self.service.compute_totals(lines)
        self.invoice_total_value.setText(f"{totals['total_count_price']:,.2f}")

    def _collect_lines(self) -> list[dict[str, Any]]:
        lines = []
        for r in range(self.lines_table.rowCount()):
            meta = self.lines_table.item(r, COL_NAME).data(Qt.UserRole)
            if meta:
                lines.append({
                    "item_code": meta.get("item_code") or None,
                    "item_name": meta["item_name"],
                    "unit": meta.get("unit", ""),
                    "item_count": meta["count"],
                    "unit_price": meta["price"],
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
        """Render an item code cell: a clean integer string, or "" when unset."""
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
        self.invoice_number_input.setReadOnly(not editable)
        self.issue_datetime_input.setEnabled(editable)
        self.supplier_combo.setEnabled(editable)
        self.payment_combo.setEnabled(editable)
        self.notes_input.setReadOnly(not editable)
        for button in self._lookup_buttons:
            button.setEnabled(editable)
        self.item_name_input.setReadOnly(not editable)
        self.unit_input.setReadOnly(not editable)
        self.count_input.setReadOnly(not editable)
        self.price_input.setReadOnly(not editable)
        self.add_line_button.setEnabled(editable)
        self.new_line_button.setEnabled(editable)
        self.remove_line_button.setEnabled(editable)
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

        self._set_form_editable(editable)

        has_current = self._current is not None
        has_draft = has_current and self._current_status == STATUS_DRAFT
        at_rest = is_view and (not has_current or self._post_save)
        self.new_button.setEnabled(at_rest)
        self.duplicate_button.setEnabled(is_view)
        save_enabled = editable or (is_view and has_current and not self._post_save)
        self.save_button.setEnabled(save_enabled)
        self.edit_button.setEnabled(is_view and has_draft and not self._post_save)
        self.update_button.setEnabled(is_edit)
        # Delete is available for any saved invoice on view — draft or approved.
        self.delete_button.setEnabled(is_view and has_current)
        self.delete_all_button.setEnabled(is_view)
        self.cancel_button.setEnabled(True)
        self.back_button.setEnabled(True)

        approve_ok = self.service.is_approval_available() and is_view and has_draft
        self.approve_button.setEnabled(approve_ok)
        self.approve_button.setToolTip(
            "" if approve_ok else "الاعتماد متاح للمسودة المحفوظة فقط."
        )

        # Re-apply editable flags to existing rows.
        self._suspend_cell_signal = True
        try:
            for r in range(self.lines_table.rowCount()):
                meta = self.lines_table.item(r, COL_NAME).data(Qt.UserRole)
                if meta:
                    self._write_row(r, meta)
        finally:
            self._suspend_cell_signal = False

    def _clear_form(self) -> None:
        self.invoice_number_input.clear()
        self.issue_datetime_input.setDateTime(QDateTime.currentDateTime())
        self.supplier_combo.setCurrentIndex(0)
        self.supplier_account_type_display.clear()
        self.payment_combo.setCurrentIndex(0)
        self.notes_input.clear()
        self._suspend_cell_signal = True
        self.lines_table.setRowCount(0)
        self._suspend_cell_signal = False
        self._refresh_totals()
        self._dirty = False

    def _populate_reserved_invoice_number(self) -> None:
        """Fill the next automatic number while preserving manual editability."""
        self.invoice_number_input.clear()
        try:
            number = self.service.reserve_invoice_number()
        except Exception:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "تعذّر إنشاء رقم الفاتورة",
                "تعذّر إنشاء رقم فاتورة تلقائيًا. يمكنك إدخال الرقم يدويًا.",
            )
            return
        self.invoice_number_input.setText(str(number))

    def enter_ready_mode(self) -> None:
        """Idle, fully-locked state: nothing loaded, only "New" is actionable."""
        self._current = None
        self._current_status = STATUS_DRAFT
        self._post_save = False
        self._clear_form()
        self._set_mode("view")
        self._dirty = False

    def enter_new_mode(self) -> None:
        self._current = None
        self._current_status = STATUS_DRAFT
        self._post_save = False
        self._clear_form()
        self._populate_reserved_invoice_number()
        self._set_mode("new")
        self._dirty = False

    def enter_view_mode(self) -> None:
        self._set_mode("view")

    def enter_edit_mode(self) -> None:
        if self._current is None or self._current_status != STATUS_DRAFT:
            return
        self._post_save = False
        self._set_mode("edit")

    # ======================================================================
    # Load an existing invoice
    # ======================================================================
    def load_invoice(self, invoice_id: int, *, post_save: bool = False) -> None:
        loaded = self._safe(lambda: self.service.load(invoice_id))
        if not loaded:
            QMessageBox.warning(self, "غير موجودة", "تعذّر تحميل الفاتورة.")
            return
        self._post_save = post_save
        self._current = loaded
        header = loaded["header"]
        self._current_status = header["document_status"]

        self.invoice_number_input.setText(header["invoice_number"] or "")
        issued = header["issue_datetime"]
        if issued is not None:
            self.issue_datetime_input.setDateTime(
                QDateTime(QDate(issued.year, issued.month, issued.day),
                          QTime(issued.hour, issued.minute, issued.second))
            )
        supplier = {"supplier_id": header["supplier_id"],
                    "supplier_name": header["supplier_name_snapshot"]}
        self._ensure_combo_record(
            self.supplier_combo, supplier, self._supplier_label(supplier), "supplier_id"
        )
        # _ensure_combo_record blocks signals, so refresh نوع الحساب explicitly from
        # the now-selected supplier (matched against the master list, which carries
        # account_type).
        self._update_supplier_account_type()
        payment_index = self.payment_combo.findData(header["payment_type"])
        if payment_index >= 0:
            self.payment_combo.setCurrentIndex(payment_index)
        self.notes_input.setPlainText(header["notes"] or "")

        # Lines.
        self._suspend_cell_signal = True
        self.lines_table.setRowCount(0)
        self._suspend_cell_signal = False
        for line in loaded["lines"]:
            meta = {
                "item_code": self._fmt_code(line.get("item_code_snapshot")),
                "item_name": line["item_name_snapshot"],
                "unit": line.get("unit_snapshot") or "",
                "count": Decimal(str(line["item_count"])),
                "price": Decimal(str(line["unit_price"])),
                "line_id": line["id"],
            }
            r = self.lines_table.rowCount()
            self.lines_table.insertRow(r)
            for c in range(COLUMN_COUNT):
                self.lines_table.setItem(r, c, QTableWidgetItem(""))
            self._write_row(r, meta)
        self._refresh_totals()

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
        supplier = self.supplier_combo.currentData()
        issued = self.issue_datetime_input.dateTime().toPython()
        if isinstance(issued, datetime.datetime) and issued.tzinfo is None:
            issued = issued.astimezone()  # attach local tz -> tz-aware storage
        return {
            "invoice_number": self.invoice_number_input.text(),
            "issue_datetime": issued,
            "supplier_id": supplier.get("supplier_id") if isinstance(supplier, dict) else None,
            "payment_type": self.payment_combo.currentData(),
            "notes": self.notes_input.toPlainText(),
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

    def _invoice_to_copy(self) -> Any:
        """The invoice "تكرار" copies: the one on screen, else the newest saved."""
        header = self._current.get("header") if isinstance(self._current, dict) else None
        if isinstance(header, dict) and header.get("id") is not None:
            return header["id"]
        rows = self._safe(lambda: self.service.search_invoices("", None, 1))
        first = rows[0] if rows else None
        return first.get("id") if isinstance(first, dict) else None

    def on_duplicate(self) -> None:
        """Open a new draft pre-filled from the previous invoice.

        Everything is copied except the invoice number (unique, typed by hand)
        and the timestamp (a new invoice is issued now).
        """
        if self._dirty and not self._confirm_discard():
            return
        source_id = self._invoice_to_copy()
        if source_id is None:
            QMessageBox.information(self, "تكرار الفاتورة", "لا توجد فاتورة سابقة لتكرارها.")
            return
        self.load_invoice(source_id)
        if self._current is None:
            return  # load_invoice already reported why
        self._detach_as_new_draft()

    def _detach_as_new_draft(self) -> None:
        """Turn the loaded invoice on screen into an unsaved copy of itself."""
        self._current = None  # nothing loaded -> Save creates, not updates
        self._current_status = STATUS_DRAFT
        self._post_save = False
        self._populate_reserved_invoice_number()
        self.issue_datetime_input.setDateTime(QDateTime.currentDateTime())
        # The rows still carry the source's line ids; they belong to that invoice.
        self._suspend_cell_signal = True
        try:
            for r in range(self.lines_table.rowCount()):
                item = self.lines_table.item(r, COL_NAME)
                meta = item.data(Qt.UserRole) if item else None
                if meta:
                    meta["line_id"] = None
                    item.setData(Qt.UserRole, meta)
        finally:
            self._suspend_cell_signal = False
        self._set_mode("new")
        self._dirty = True
        self.invoice_number_input.setFocus()

    def on_save(self) -> None:
        if self._current is None:
            self._save_new()
        else:
            self._save_existing()

    def _stay_on_saved(self, invoice_id: Any) -> None:
        """Keep the just-saved invoice on screen (re-read to refresh row_version)."""
        if invoice_id is None:
            self.enter_ready_mode()
            return
        self.load_invoice(invoice_id, post_save=True)

    @staticmethod
    def _saved_invoice_id(saved: Any) -> Any:
        header = (saved or {}).get("header") if isinstance(saved, dict) else None
        return header.get("id") if isinstance(header, dict) else None

    def _do_save(self) -> "tuple[bool, Any]":
        """Persist the invoice and return ``(ok, invoice_id)``."""
        if self._current is None:
            try:
                saved = self.service.create_draft(self._collect_form(), user_id=self._current_user_id())
            except PurchaseInvoiceError as exc:
                QMessageBox.warning(self, "تعذّر الحفظ", exc.message)
                return False, None
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "خطأ", str(exc))
                return False, None
            return True, self._saved_invoice_id(saved)

        row_version = self._current["header"]["row_version"]
        invoice_id = self._current["header"]["id"]
        try:
            self.service.update_draft(invoice_id, row_version, self._collect_form(),
                                      user_id=self._current_user_id())
        except PurchaseInvoiceError as exc:
            QMessageBox.warning(self, "تعذّر التحديث", exc.message)
            return False, None
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطأ", str(exc))
            return False, None
        return True, invoice_id

    def _save_new(self) -> None:
        ok, invoice_id = self._do_save()
        if not ok:
            return
        QMessageBox.information(self, "تم", "تم حفظ الفاتورة كمسودة.")
        self._stay_on_saved(invoice_id)

    def _save_existing(self) -> None:
        ok, invoice_id = self._do_save()
        if not ok:
            return
        QMessageBox.information(self, "تم", "تم تحديث الفاتورة.")
        self._stay_on_saved(invoice_id)

    def on_update(self) -> None:
        if self._current is None:
            return
        row_version = self._current["header"]["row_version"]
        invoice_id = self._current["header"]["id"]
        try:
            self.service.update_draft(invoice_id, row_version, self._collect_form(),
                                      user_id=self._current_user_id())
        except PurchaseInvoiceError as exc:
            QMessageBox.warning(self, "تعذّر التحديث", exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطأ", str(exc))
            return
        QMessageBox.information(self, "تم", "تم تحديث الفاتورة.")
        self._stay_on_saved(invoice_id)

    def on_approve(self) -> None:
        if self._current is None:
            return
        header = self._current["header"]
        if header["document_status"] != STATUS_DRAFT:
            QMessageBox.information(self, "الاعتماد", "الفاتورة معتمدة بالفعل.")
            return
        confirm = QMessageBox.question(
            self, "اعتماد الفاتورة",
            "هل تريد اعتماد هذه الفاتورة؟\nلا يمكن تعديلها أو حذفها بعد الاعتماد.",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.service.approve(header["id"], header["row_version"], user_id=self._current_user_id())
        except PurchaseInvoiceError as exc:
            QMessageBox.warning(self, "تعذّر الاعتماد", exc.message)
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطأ", str(exc))
            return
        QMessageBox.information(self, "تم", "تم اعتماد الفاتورة.")
        self._stay_on_saved(header["id"])

    def on_delete(self) -> None:
        if self._current is None:
            return
        if QMessageBox.question(self, "تأكيد الحذف", "هل تريد حذف هذه الفاتورة؟") != QMessageBox.Yes:
            return
        try:
            self.service.delete_draft(self._current["header"]["id"], user_id=self._current_user_id())
        except PurchaseInvoiceError as exc:
            QMessageBox.warning(self, "تعذّر الحذف", exc.message)
            return
        QMessageBox.information(self, "تم", "تم حذف الفاتورة.")
        self.enter_ready_mode()

    def on_delete_all(self) -> None:
        confirm = QMessageBox.question(
            self, "تأكيد حذف الكل",
            "سيتم حذف جميع الفواتير بما فيها الفواتير المعتمدة. هل تريد المتابعة؟",
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            result = self.service.delete_all_drafts(user_id=self._current_user_id())
        except PurchaseInvoiceError as exc:
            QMessageBox.warning(self, "تعذّر الحذف", exc.message)
            return
        QMessageBox.information(self, "تم", f"تم حذف {result['deleted']} فاتورة.")
        self.enter_ready_mode()

    def on_cancel(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        if self._mode == "edit" and self._current is not None:
            self.load_invoice(self._current["header"]["id"])
        else:
            self.enter_ready_mode()

    def on_back(self) -> None:
        window = self.window()
        if window is not None:
            window.close()

    def closeEvent(self, event) -> None:  # noqa: ANN001 - Qt close event
        if self._dirty and not self._confirm_discard():
            event.ignore()
            return
        super().closeEvent(event)
        self.enter_ready_mode()

    # ======================================================================
    # Search
    # ======================================================================
    def open_search(self) -> None:
        dialog = PurchaseInvoiceSearchDialog(self.service, parent=self)
        if dialog.exec() and dialog.selected_id is not None:
            self.load_invoice(dialog.selected_id)

    def _confirm_discard(self) -> bool:
        return QMessageBox.question(
            self, "تجاهل التغييرات", "هناك تغييرات غير محفوظة. هل تريد تجاهلها؟"
        ) == QMessageBox.Yes

    # ======================================================================
    # Fitting the screen it is actually shown on
    # ======================================================================
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._apply_density()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.refresh_master_data()

    def _lay_out_meta(self, *, stacked: bool) -> None:
        for label in (self.user_label, self.date_label, self.time_label):
            self.meta_grid.removeWidget(label)
        for i, label in enumerate((self.user_label, self.date_label, self.time_label)):
            self.meta_grid.addWidget(label, i, 0) if stacked else \
                self.meta_grid.addWidget(label, 0, i)

    def _apply_density(self) -> None:
        compact = self.height() < COMPACT_BELOW_HEIGHT
        if compact == self._compact:
            return
        self._compact = compact

        row_height = COMPACT_ROW_HEIGHT if compact else ROW_HEIGHT
        header = self.lines_table.horizontalHeader()
        header.setFixedHeight(COMPACT_TABLE_HEADER if compact else TABLE_HEADER)
        self.lines_table.verticalHeader().setDefaultSectionSize(row_height)
        self.lines_table.setMinimumHeight(header.height() + 3 * row_height)

        self.subtitle_label.setVisible(not compact)
        self._lay_out_meta(stacked=not compact)
        self.quick_entry_card.setMaximumHeight(116 if compact else 136)
        for layout in self._cards:
            layout.setContentsMargins(*(COMPACT_CARD_MARGINS if compact else CARD_MARGINS))
            layout.setSpacing(COMPACT_CARD_SPACING if compact else CARD_SPACING)
        self.main_layout.setSpacing(3 if compact else 6)
        self.main_layout.setContentsMargins(12, 3, 12, 4) if compact else \
            self.main_layout.setContentsMargins(12, 6, 12, 8)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key_F1:
            self.open_search()
            return
        super().keyPressEvent(event)


__all__ = ["PurchaseInvoicePage"]
