"""شاشة دفعات المقاولين — النموذجان 4 و7 كتبويبين (2026-09-26).

As with the contracts and extracts screens, the user asked for two mockups side
by side as tabs so they can pick one by using both:

* «الشجرة» (نموذج 4): a tree مقاول ← شركة ← مشروع ← مستخلص on the right; picking
  an extract fills the contractor / company / project, and the form, the
  extract's balance strip and its payments sit on the left.
* «لوحة المقاول» (نموذج 7): pick the contractor at the top (with his totals),
  then the company, project and extract in the form; his extracts on that
  project show as cards beside all his payments.

The user's fields: التاريخ، اسم المقاول، اسم الشركة، اسم المشروع، رقم المستخلص،
المبلغ، ملاحظات. رقم المستخلص lists only the extracts matching the contractor,
company AND project, and is optional: its first choice «دفعة عامة» (no extract)
pays on all the contractor's extracts on that project — the balance shown is
then the project's. The cascade and the balances come from
``contractor_payment_service``.

Both tabs show the same selection and payment; switching tabs is locked while
editing. The selection may change while creating or editing (it moves the
payment to the chosen extract); opening another payment may not.

مسودة / معتمد (2026-10-02): «حفظ» keeps a payment as a draft, «اعتماد» /
«إلغاء الاعتماد» (``ApprovalControls``) move it. Only approved extracts can be
paid, and the balances count approved payments only; the tables list the drafts
too, marked «مسودة». An approved payment is locked except for an admin.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.security.session_context import SESSION
from app.services.contracting_approval import APPROVED, ApprovalError, approved_only
from app.services.contractor_contract_service import to_decimal
from app.services.contractor_payment_service import (
    GENERAL_LABEL,
    PAYMENT_METHODS,
    REFERENCE_MAX,
    ContractorPaymentService,
    PaymentError,
    companies_of,
    contractor_summary,
    extracts_of,
    general_paid,
    method_text,
    needs_reference,
    payment_balance,
    project_balance,
    projects_of,
)
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.dialogs.contractor_payment_picker import ContractorPaymentPickerDialog
from app.ui.screens.approval_controls import ApprovalControls, draft_suffix
from app.ui.common.live_lists import notify_data_changed
from app.ui.screens.contractor_contracts_screen import (
    _COMBO_QSS,
    _EDITOR_QSS,
    _caption,
    _card_frame,
    _money,
    _select_data,
)

PERMISSION_BASE = "contracting.contractor_payments"
BLUE = "#0369A1"
MUTED = "#475569"
AMBER = "#B45309"
RED = "#B91C1C"
TAB_TREE, TAB_BOARD = 0, 1
CARD_COLUMNS = 3
# «رقم المستخلص» left empty = a general payment. The combo boxes hold GENERAL for
# it (extract ids start at 1); the screen's state holds None.
GENERAL = 0
GENERAL_TEXT = "— دفعة عامة (بدون مستخلص) —"
AUTO = object()  # select(): «pick the latest extract» (None means general)

_TABLE_QSS = (
    "QTableWidget { border:none; font-size:13px; font-weight:700; gridline-color:#E5E7EB; }"
    f"QHeaderView::section {{ background:{GREEN}; color:#FFFFFF; font-weight:900; padding:6px; border:none; }}"
    "QTableWidget::item:selected { background:#DCFCE7; color:#111827; }"
)


def _date_text(value: Any) -> str:
    return f"{value:%Y-%m-%d}" if isinstance(value, (datetime.date, datetime.datetime)) else str(value or "")


def extract_label(row: dict[str, Any]) -> str:
    """رقم المستخلص's list entry: the number and what is left to pay on it."""
    remaining = to_decimal(row.get("remaining"))
    return f"{row['extract_no']} — {'مسدد' if remaining <= 0 else 'المتبقي ' + _money(remaining)}"


def _date_edit() -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    edit.setDate(QDate.currentDate())
    edit.setMinimumHeight(38)
    edit.setLayoutDirection(Qt.LeftToRight)
    edit.setStyleSheet(_EDITOR_QSS)
    return edit


def _to_qdate(value: Any) -> QDate | None:
    if isinstance(value, (datetime.date, datetime.datetime)):
        return QDate(value.year, value.month, value.day)
    return None


class PaymentFields:
    """The typed inputs of one payment: التاريخ، المبلغ، طريقة الدفع (+ رقم الشيك / الحوالة
    وتاريخ الشيك لو شيك أو تحويل)، ملاحظات. One set per tab."""

    def __init__(self) -> None:
        self.date = _date_edit()
        self.amount = QLineEdit()
        self.amount.setMinimumHeight(38)
        self.amount.setPlaceholderText("0.00")
        self.amount.setLayoutDirection(Qt.LeftToRight)
        self.amount.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.amount.setStyleSheet(_EDITOR_QSS.replace("font-size:14px", "font-size:17px"))
        self.amount.editingFinished.connect(self._format_amount)
        self.notes = QLineEdit()
        self.notes.setMinimumHeight(38)
        self.notes.setMaxLength(500)
        self.notes.setStyleSheet(_EDITOR_QSS)
        self.method = QComboBox()
        for method in PAYMENT_METHODS:
            self.method.addItem(method, method)
        self.method.setMinimumHeight(38)
        self.method.setStyleSheet(_COMBO_QSS)
        self.reference = QLineEdit()
        self.reference.setMinimumHeight(38)
        self.reference.setMaxLength(REFERENCE_MAX)
        self.reference.setStyleSheet(_EDITOR_QSS)
        self.cheque_date = _date_edit()
        # The boxes of رقم الشيك / الحوالة and تاريخ الشيك: shown only for شيك / تحويل.
        self.reference_boxes: list[QWidget] = []
        self.method.currentIndexChanged.connect(self._method_changed)

    def watch_reference(self, *boxes: QWidget) -> None:
        self.reference_boxes.extend(boxes)
        self._sync_reference()

    def shows_reference(self) -> bool:
        return needs_reference(self.method.currentData())

    def _sync_reference(self) -> None:
        for box in self.reference_boxes:
            box.setVisible(self.shows_reference())

    def _method_changed(self) -> None:
        # A new cheque / transfer is usually dated like the payment itself.
        if self.shows_reference() and not self.reference.text().strip() and not self.reference.isReadOnly():
            self.cheque_date.setDate(self.date.date())
        self._sync_reference()

    def _format_amount(self) -> None:
        text = self.amount.text().strip()
        if text and not self.amount.isReadOnly():
            self.amount.setText(_money(to_decimal(text)))

    def values(self) -> dict[str, Any]:
        return {
            "payment_date": self.date.date().toString("yyyy-MM-dd"),
            "amount": self.amount.text(),
            "notes": self.notes.text(),
            "payment_method": self.method.currentData(),
            "reference_no": self.reference.text(),
            "cheque_date": self.cheque_date.date().toString("yyyy-MM-dd"),
        }

    def fill(self, record: dict[str, Any]) -> None:
        date = _to_qdate(record.get("payment_date"))
        if date is not None:
            self.date.setDate(date)
        self.amount.setText(_money(record.get("amount")))
        self.notes.setText(str(record.get("notes") or ""))
        self.reference.setText(str(record.get("reference_no") or ""))
        self.cheque_date.setDate(_to_qdate(record.get("cheque_date")) or self.date.date())
        _select_data(self.method, record.get("payment_method") or PAYMENT_METHODS[0])
        self._sync_reference()

    def clear(self) -> None:
        self.date.setDate(QDate.currentDate())
        self.amount.clear()
        self.notes.clear()
        self.reference.clear()
        self.cheque_date.setDate(QDate.currentDate())
        self.method.setCurrentIndex(0)
        self._sync_reference()

    def set_editing(self, editing: bool) -> None:
        self.amount.setReadOnly(not editing)
        self.notes.setReadOnly(not editing)
        self.date.setReadOnly(not editing)
        self.date.setCalendarPopup(editing)
        self.method.setEnabled(editing)
        self.reference.setReadOnly(not editing)
        self.cheque_date.setReadOnly(not editing)
        self.cheque_date.setCalendarPopup(editing)


class ContractorPaymentsScreen(QWidget):
    def __init__(self, service: ContractorPaymentService | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service or ContractorPaymentService()
        self.contractors: list[dict[str, Any]] = []
        self.catalog: list[dict[str, Any]] = []
        self.general: dict[tuple, Decimal] = {}  # (contractor, project) -> general payments
        self._captions: dict[str, QLabel] = {}
        self.contractor_id: Any = None
        self.company_id: Any = None
        self.project_id: Any = None
        self.extract_id: Any = None
        self.current_id: Any = None
        self.current_record: dict[str, Any] | None = None
        self.mode = "view"
        self._tree_items: dict[tuple, QTreeWidgetItem] = {}
        self._cards: dict[Any, QPushButton] = {}

        self._perm_create = SESSION.can(f"{PERMISSION_BASE}.create")
        self._perm_edit = SESSION.can(f"{PERMISSION_BASE}.edit")
        self._perm_save = SESSION.can(f"{PERMISSION_BASE}.save")
        self._perm_delete = SESSION.can(f"{PERMISSION_BASE}.delete")

        self.tree_fields = PaymentFields()
        self.board_fields = PaymentFields()
        for fields in self.fields_pair:
            fields.amount.textChanged.connect(self._update_balance)

        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("QWidget { font-family: 'Segoe UI', 'Tahoma', 'Arial'; }")
        self.approval = ApprovalControls(self, PERMISSION_BASE, locked_when_approved=True)
        self._build_ui()
        self.search_shortcut = QShortcut(QKeySequence("F1"), self)
        self.search_shortcut.activated.connect(self.open_search)
        self.refresh_all()

    @property
    def fields(self) -> PaymentFields:
        return self.tree_fields if self.tabs.currentIndex() == TAB_TREE else self.board_fields

    @property
    def fields_pair(self) -> tuple[PaymentFields, PaymentFields]:
        return self.tree_fields, self.board_fields

    # -- layout ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:none; }"
            "QTabBar::tab { background:#FFFFFF; color:#334155; border:1px solid #D9E2EC; border-bottom:none; "
            "border-top-left-radius:8px; border-top-right-radius:8px; padding:9px 22px; margin-left:4px; "
            "font-size:14px; font-weight:900; }"
            f"QTabBar::tab:selected {{ background:{GREEN}; color:#FFFFFF; border-color:{GREEN}; }}"
            "QTabBar::tab:disabled { color:#94A3B8; }"
        )
        self.tabs.addTab(self._build_tree_tab(), "🌳  الشجرة (نموذج 4)")
        self.tabs.addTab(self._build_board_tab(), "📊  لوحة المقاول (نموذج 7)")
        root.addWidget(self.tabs, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background:{GREEN}; border-radius:6px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)
        icon = QLabel("💵")
        icon.setFixedSize(54, 54)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background:rgba(255,255,255,0.16); border:1px solid rgba(255,255,255,0.28); "
            "border-radius:7px; font-size:24px; font-weight:900;"
        )
        title = QLabel("دفعات المقاولين")
        title.setStyleSheet("font-size:27px; font-weight:900;")
        username = (SESSION.user or {}).get("username") if SESSION.user else None
        self.header_user = QLabel(f"المستخدم: {username or '—'}")
        self.header_date = QLabel("")
        for label in (self.header_user, self.header_date):
            label.setStyleSheet(
                "background:rgba(255,255,255,0.14); border:1px solid rgba(255,255,255,0.24); "
                "border-radius:6px; padding:9px 14px; font-weight:800;"
            )
        layout.addWidget(icon)
        layout.addWidget(title, 1)
        layout.addWidget(self.header_user)
        layout.addWidget(self.header_date)
        self.header_timer = QTimer(self)
        self.header_timer.timeout.connect(self._update_datetime)
        self.header_timer.start(1000)
        self._update_datetime()
        return header

    def _update_datetime(self) -> None:
        now = datetime.datetime.now()
        self.header_date.setText(f"التاريخ: {now:%Y-%m-%d} | الوقت: {now:%H:%M:%S}")

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet("QFrame { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:7px; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(7)
        self.new_button = QPushButton("دفعة جديدة")
        self.edit_button = QPushButton("تعديل")
        self.save_button = QPushButton("حفظ")
        self.delete_button = QPushButton("حذف")
        self.cancel_button = QPushButton("إلغاء")
        self.refresh_button = QPushButton("تحديث")
        self.search_button = QPushButton("بحث (F1)")
        self.exit_button = QPushButton("خروج")
        buttons = [
            (self.new_button, QStyle.SP_FileIcon, "#1A7A3C", "#166534"),
            (self.edit_button, QStyle.SP_FileDialogDetailedView, "#64748B", "#475569"),
            (self.save_button, QStyle.SP_DialogSaveButton, "#2563EB", "#1D4ED8"),
            (self.delete_button, QStyle.SP_TrashIcon, "#DC2626", "#B91C1C"),
            (self.cancel_button, QStyle.SP_DialogCancelButton, "#6B7280", "#4B5563"),
            (self.refresh_button, QStyle.SP_BrowserReload, "#FFFFFF", "#F3F4F6"),
            (self.search_button, QStyle.SP_FileDialogContentsView, "#0369A1", "#075985"),
            (self.exit_button, QStyle.SP_ArrowBack, "#374151", "#1F2937"),
        ]
        for button, icon, bg, hover in buttons:
            button.setFixedHeight(38)
            button.setIcon(self.style().standardIcon(icon))
            if bg == "#FFFFFF":
                button.setStyleSheet(
                    "QPushButton { background:#FFFFFF;color:#374151;border:1px solid #D1D5DB;"
                    "border-radius:6px;font-weight:800;padding:7px 12px; }"
                    f"QPushButton:hover {{ background:{hover}; }}"
                )
            else:
                button.setStyleSheet(_button_style(bg, hover))
            layout.addWidget(button)
            if button is self.save_button:
                self.approval.add_buttons(layout)
        layout.addStretch(1)
        layout.addWidget(self.approval.badge)
        self.mode_badge = QLabel("عرض")
        self.mode_badge.setAlignment(Qt.AlignCenter)
        self.mode_badge.setMinimumWidth(100)
        self.mode_badge.setStyleSheet(
            "background:#ECFDF3;color:#087443;border:1px solid #B7E4C7;border-radius:7px;"
            "padding:8px 12px;font-weight:900;"
        )
        layout.addWidget(self.mode_badge)
        self.new_button.clicked.connect(self.new_payment)
        self.approval.approve_button.clicked.connect(self.approve_record)
        self.approval.unapprove_button.clicked.connect(self.unapprove_record)
        self.edit_button.clicked.connect(self.edit_record)
        self.save_button.clicked.connect(self.save_record)
        self.delete_button.clicked.connect(self.delete_record)
        self.cancel_button.clicked.connect(self.cancel_edit)
        self.refresh_button.clicked.connect(self.refresh_all)
        self.search_button.clicked.connect(self.open_search)
        self.exit_button.clicked.connect(self.window().close)
        return bar

    # -- small builders -------------------------------------------------------------------

    def _combo(self, min_width: int = 0, strong: bool = False) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumHeight(40 if strong else 38)
        if min_width:
            combo.setMinimumWidth(min_width)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        if strong:
            combo.setStyleSheet(
                f"QComboBox {{ background:#F8FAFC; border:2px solid {GREEN}; border-radius:8px; padding:6px 10px; "
                f"font-size:15px; font-weight:900; color:{TEXT}; }}"
                "QComboBox:disabled { background:#F1F5F9; color:#64748B; }"
            )
        else:
            combo.setStyleSheet(_COMBO_QSS)
        return combo

    def _read_only(self) -> QLineEdit:
        editor = QLineEdit()
        editor.setMinimumHeight(38)
        editor.setReadOnly(True)
        editor.setFocusPolicy(Qt.NoFocus)
        editor.setStyleSheet(_EDITOR_QSS)
        return editor

    def _labelled(self, caption: str, editor: QWidget, step: int | None = None, hint: str = "") -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        if step is not None:
            badge = QLabel(str(step))
            badge.setFixedSize(20, 20)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(f"background:{GREEN}; color:#FFFFFF; border-radius:10px; font-size:11px; font-weight:900;")
            head.addWidget(badge)
        head.addWidget(_caption(caption, 13))
        head.addStretch(1)
        if hint:
            head.addWidget(_caption(hint, 11, "#64748B"))
        column.addLayout(head)
        column.addWidget(editor)
        return box

    def _stat_tile(self, name: str, caption: str, color: str, size: int = 18) -> tuple[QFrame, QLabel]:
        tile = _card_frame(name)
        column = QVBoxLayout(tile)
        column.setContentsMargins(14, 8, 14, 8)
        column.setSpacing(3)
        self._captions[name] = _caption(caption, 12, MUTED)
        column.addWidget(self._captions[name])
        value = _caption("—", size, color)
        column.addWidget(value)
        return tile, value

    def _payments_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.Stretch)  # ملاحظات
        table.setStyleSheet(_TABLE_QSS)
        table.cellClicked.connect(lambda row, _col, t=table: self._on_table_clicked(t, row))
        return table

    # -- tab 4: the tree ----------------------------------------------------------------------

    def _build_tree_tab(self) -> QWidget:
        page = QWidget()
        page_row = QHBoxLayout(page)
        page_row.setContentsMargins(0, 8, 0, 0)
        page_row.setSpacing(10)

        tree_card = _card_frame("payment_tree_card")
        tree_card.setFixedWidth(430)
        tree_col = QVBoxLayout(tree_card)
        tree_col.setContentsMargins(12, 12, 12, 12)
        tree_col.setSpacing(8)
        tree_col.addWidget(_caption("المقاول ← الشركة ← المشروع ← المستخلص", 15, GREEN))
        self.tree_search = QLineEdit()
        self.tree_search.setMinimumHeight(36)
        self.tree_search.setPlaceholderText("بحث في الشجرة…")
        self.tree_search.setStyleSheet(
            "QLineEdit { background:#F8FAFC; border:1px solid #CBD5E1; border-radius:8px; padding:6px 10px; font-size:13px; }"
            f"QLineEdit:focus {{ border:1px solid {GREEN}; }}"
        )
        self.tree_search.textChanged.connect(lambda _t: self._build_tree())
        tree_col.addWidget(self.tree_search)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setStyleSheet(
            "QTreeWidget { border:none; font-size:13px; font-weight:700; }"
            "QTreeWidget::item { height:30px; }"
            f"QTreeWidget::item:selected {{ background:#DCFCE7; color:{GREEN_DARK}; }}"
        )
        self.tree.itemClicked.connect(self._on_tree_clicked)
        tree_col.addWidget(self.tree, 1)
        page_row.addWidget(tree_card, 0)

        column = QVBoxLayout()
        column.setSpacing(10)
        form_card = _card_frame("payment_tree_form")
        form_col = QVBoxLayout(form_card)
        form_col.setContentsMargins(14, 10, 14, 12)
        form_col.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(_caption("بيانات الدفعة", 16, GREEN))
        head.addStretch(1)
        head.addWidget(_caption("اختار من الشجرة — الحقول تتملى لوحدها · رقم المستخلص اختياري", 12, "#64748B"))
        form_col.addLayout(head)
        self.tree_contractor = self._read_only()
        self.tree_company = self._read_only()
        self.tree_project = self._read_only()
        self.tree_extract = self._combo()
        self.tree_extract.currentIndexChanged.connect(lambda _i: self._on_extract_combo(self.tree_extract))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        cells = (("اسم المقاول", self.tree_contractor), ("اسم الشركة", self.tree_company),
                 ("اسم المشروع", self.tree_project), ("رقم المستخلص", self.tree_extract),
                 ("التاريخ", self.tree_fields.date), ("المبلغ (ج.م)", self.tree_fields.amount))
        for index, (caption, editor) in enumerate(cells):
            grid.addWidget(self._labelled(caption, editor), index // 3, index % 3)
        tree = self.tree_fields
        reference_box = self._labelled("رقم الشيك / الحوالة", tree.reference)
        cheque_box = self._labelled("تاريخ الشيك", tree.cheque_date)
        grid.addWidget(self._labelled("طريقة الدفع", tree.method), 2, 0)
        grid.addWidget(reference_box, 2, 1)
        grid.addWidget(cheque_box, 2, 2)
        tree.watch_reference(reference_box, cheque_box)
        grid.addWidget(self._labelled("ملاحظات", tree.notes), 3, 0, 1, 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        form_col.addLayout(grid)
        column.addWidget(form_card)

        strip = QHBoxLayout()
        strip.setSpacing(10)
        self.tree_stats: dict[str, QLabel] = {}
        for key, caption, color in (("net", "صافي المستخلص", TEXT), ("previous", "المدفوع سابقاً", BLUE),
                                    ("this", "هذه الدفعة", GREEN_DARK), ("remaining", "المتبقي بعد الدفعة", AMBER)):
            tile, value = self._stat_tile(f"tree_stat_{key}", caption, color)
            self.tree_stats[key] = value
            strip.addWidget(tile, 1)
        column.addLayout(strip)
        self.tree_warning = _caption("", 12, RED)
        self.tree_warning.hide()
        column.addWidget(self.tree_warning)

        table_card = _card_frame("payment_tree_table")
        table_col = QVBoxLayout(table_card)
        table_col.setContentsMargins(12, 10, 12, 10)
        table_col.setSpacing(6)
        self.tree_table_title = _caption("دفعات المستخلص", 15, GREEN)
        table_col.addWidget(self.tree_table_title)
        self.tree_table = self._payments_table(["التاريخ", "رقم المستخلص", "المبلغ", "طريقة الدفع", "ملاحظات"])
        table_col.addWidget(self.tree_table, 1)
        column.addWidget(table_card, 1)
        page_row.addLayout(column, 1)
        return page

    # -- tab 7: the contractor board ----------------------------------------------------------

    def _build_board_tab(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(10)

        top = _card_frame("payment_board_top")
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(14, 10, 14, 10)
        top_row.setSpacing(12)
        avatar = QLabel("👷")
        avatar.setFixedSize(56, 56)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background:#EAFBF0; border-radius:12px; font-size:28px;")
        top_row.addWidget(avatar)
        self.board_contractor = self._combo(320, strong=True)
        self.board_contractor.currentIndexChanged.connect(self._on_board_contractor)
        top_row.addWidget(self._labelled("اسم المقاول", self.board_contractor, 1))
        self.board_kpis: dict[str, QLabel] = {}
        for key, caption, color in (("net", "إجمالي صافي المستخلصات", TEXT), ("paid", "إجمالي المدفوع", BLUE),
                                    ("remaining", "المتبقي للمقاول", AMBER), ("count", "عدد الدفعات", TEXT)):
            tile, value = self._stat_tile(f"board_kpi_{key}", caption, color, 19)
            self.board_kpis[key] = value
            top_row.addWidget(tile, 1)
        column.addWidget(top)

        body = QHBoxLayout()
        body.setSpacing(10)
        form_card = _card_frame("payment_board_form")
        form_card.setFixedWidth(440)
        form_col = QVBoxLayout(form_card)
        form_col.setContentsMargins(14, 10, 14, 12)
        form_col.setSpacing(7)
        form_col.addWidget(_caption("الدفعة الحالية", 16, GREEN))
        self.board_company = self._combo()
        self.board_company.currentIndexChanged.connect(self._on_board_company)
        self.board_project = self._combo()
        self.board_project.currentIndexChanged.connect(self._on_board_project)
        self.board_extract = self._combo()
        self.board_extract.currentIndexChanged.connect(lambda _i: self._on_extract_combo(self.board_extract))
        form_col.addWidget(self._labelled("التاريخ", self.board_fields.date))
        form_col.addWidget(self._labelled("اسم الشركة", self.board_company, 2))
        form_col.addWidget(self._labelled("اسم المشروع", self.board_project, 3))
        form_col.addWidget(self._labelled("رقم المستخلص", self.board_extract, 4, "اختياري — فاضي = دفعة عامة"))
        board = self.board_fields
        amount_row = QHBoxLayout()
        amount_row.setSpacing(10)
        amount_row.addWidget(self._labelled("المبلغ (ج.م)", board.amount), 3)
        amount_row.addWidget(self._labelled("طريقة الدفع", board.method), 2)
        form_col.addLayout(amount_row)
        reference_row = QWidget()
        reference_layout = QHBoxLayout(reference_row)
        reference_layout.setContentsMargins(0, 0, 0, 0)
        reference_layout.setSpacing(10)
        reference_layout.addWidget(self._labelled("رقم الشيك / الحوالة", board.reference), 3)
        reference_layout.addWidget(self._labelled("تاريخ الشيك", board.cheque_date), 2)
        form_col.addWidget(reference_row)
        board.watch_reference(reference_row)
        form_col.addWidget(self._labelled("ملاحظات", board.notes))
        remaining = QFrame()
        remaining.setObjectName("board_remaining")
        remaining.setStyleSheet(
            "QFrame#board_remaining { background:#FEF3C7; border-radius:8px; } QLabel { background:transparent; }")
        remaining_row = QHBoxLayout(remaining)
        remaining_row.setContentsMargins(10, 6, 10, 6)
        self.board_remaining_caption = _caption("المتبقي على المستخلص بعد الدفعة", 13, AMBER)
        remaining_row.addWidget(self.board_remaining_caption)
        remaining_row.addStretch(1)
        self.board_remaining = _caption("—", 15, AMBER)
        remaining_row.addWidget(self.board_remaining)
        form_col.addWidget(remaining)
        self.board_warning = _caption("", 12, RED)
        self.board_warning.setWordWrap(True)
        self.board_warning.hide()
        form_col.addWidget(self.board_warning)
        form_col.addStretch(1)
        body.addWidget(form_card, 0)

        side = _card_frame("payment_board_side")
        side_col = QVBoxLayout(side)
        side_col.setContentsMargins(12, 10, 12, 10)
        side_col.setSpacing(8)
        side_col.addWidget(_caption("مستخلصات المقاول حسب الشركة والمشروع", 15, GREEN))
        self.board_path = _caption("", 13, TEXT)
        side_col.addWidget(self.board_path)
        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setFrameShape(QFrame.NoFrame)
        cards_scroll.setMaximumHeight(250)
        cards_scroll.setStyleSheet("QScrollArea { background:transparent; }")
        self.cards_host = QWidget()
        self.cards_host.setObjectName("cards_host")
        self.cards_host.setStyleSheet("QWidget#cards_host { background:#FFFFFF; }")
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setSpacing(10)
        self.cards_grid.setAlignment(Qt.AlignTop)
        for col in range(CARD_COLUMNS):
            self.cards_grid.setColumnStretch(col, 1)
        cards_scroll.setWidget(self.cards_host)
        side_col.addWidget(cards_scroll)
        side_col.addWidget(_caption("دفعات المقاول", 14, GREEN))
        self.board_table = self._payments_table(["التاريخ", "رقم المستخلص", "اسم المشروع", "المبلغ", "طريقة الدفع", "ملاحظات"])
        side_col.addWidget(self.board_table, 1)
        body.addWidget(side, 1)
        column.addLayout(body, 1)
        return page

    def _build_extract_card(self, row: dict[str, Any]) -> QPushButton:
        net, paid = to_decimal(row["net"]), to_decimal(row["paid"])
        remaining = net - paid
        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(104)
        column = QVBoxLayout(button)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(7)
        top = QHBoxLayout()
        top.addWidget(_caption(str(row["extract_no"]), 14, GREEN if remaining > 0 else "#94A3B8"))
        top.addStretch(1)
        state = QLabel("مسدد بالكامل" if remaining <= 0 else f"متبقي {_money(remaining)}")
        state.setStyleSheet(
            "font-size:11px; font-weight:800; border-radius:6px; padding:3px 8px; "
            + ("color:#64748B; background:#F1F5F9;" if remaining <= 0 else f"color:{AMBER}; background:#FEF3C7;"))
        top.addWidget(state)
        column.addLayout(top)
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        bar.setValue(int(min(max(paid / net, Decimal(0)), Decimal(1)) * 1000) if net > 0 else 0)
        bar.setStyleSheet(
            "QProgressBar { background:#E2E8F0; border:none; border-radius:5px; }"
            f"QProgressBar::chunk {{ background:{BLUE}; border-radius:5px; }}"
        )
        column.addWidget(bar)
        bottom = QHBoxLayout()
        bottom.addWidget(_caption(f"الصافي {_money(net)}", 12, MUTED))
        bottom.addStretch(1)
        bottom.addWidget(_caption(f"المدفوع {_money(paid)}", 12, BLUE))
        column.addLayout(bottom)
        for widget in button.findChildren(QWidget):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        button.clicked.connect(lambda _c=False, xid=row["extract_id"]: self._on_card_clicked(xid))
        self._cards[row["extract_id"]] = button
        return button

    def _build_general_card(self, total: Decimal) -> QPushButton:
        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(104)
        column = QVBoxLayout(button)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(7)
        column.addWidget(_caption("💵 دفعة عامة", 14, GREEN_DARK))
        column.addWidget(_caption("بدون مستخلص — على كل مستخلصات المشروع", 11, "#64748B"))
        column.addStretch(1)
        column.addWidget(_caption(f"المدفوع {_money(total)}", 12, BLUE))
        for widget in button.findChildren(QWidget):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        button.clicked.connect(lambda _c=False: self._on_card_clicked(None))
        self._cards[GENERAL] = button
        return button

    # -- data ---------------------------------------------------------------------------------

    def _catalog_row(self, extract_id: Any) -> dict[str, Any] | None:
        return next((r for r in self.catalog if str(r["extract_id"]) == str(extract_id)), None)

    def refresh_all(self) -> None:
        if self._busy():
            return
        self._reload_data()
        self.mode = "view"
        contractor = self.contractor_id
        if contractor is None:
            contractor = self.catalog[0]["contractor_id"] if self.catalog else (
                self.contractors[0]["contractor_id"] if self.contractors else None)
        if self.current_id is not None:
            self.load_payment(self.current_id)
        else:
            self.select(contractor, self.company_id, self.project_id,
                        self.extract_id if self.project_id is not None else AUTO)

    def reload_lists(self) -> None:
        """Data changed in another screen: refill the lists, keeping the selection.

        Never mid-edit: refresh_all would stop on «احفظ التعديلات أو ألغِها الأول».
        The tree keeps its scroll position: the rebuild would jump it to the top.
        """
        if self.mode in {"new", "edit"}:
            return
        bar = self.tree.verticalScrollBar()
        position = bar.value()
        self.refresh_all()
        bar.setValue(position)

    def _reload_data(self) -> None:
        try:
            self.contractors = self.service.contractor_choices()
            self.catalog = self.service.extract_catalog()
            self.general = self.service.general_totals()
        except Exception as exc:
            self._show_error("تعذّر تحميل البيانات", exc)
            self.contractors, self.catalog, self.general = [], [], {}
        self._fill_combo(self.board_contractor, self.contractors,
                         lambda r: f"{r['contractor_code']} — {r['contractor_name']}", "contractor_id", self.contractor_id)
        self._build_tree()

    def _fill_combo(self, combo: QComboBox, rows: list[dict[str, Any]], text, key: str, keep: Any) -> None:
        combo.blockSignals(True)
        combo.clear()
        for row in rows:
            combo.addItem(text(row), row[key])
        _select_data(combo, keep)
        combo.blockSignals(False)

    # -- the selection (المقاول ← الشركة ← المشروع ← المستخلص) --------------------------------------

    def select(self, contractor_id: Any, company_id: Any = None, project_id: Any = None, extract_id: Any = AUTO) -> None:
        """Walk the cascade: a company / project that doesn't fit is replaced by the first fitting one.

        *extract_id* None = a general payment on the project; AUTO (or one that
        doesn't fit) = the project's latest extract. In «عرض» the latest payment
        of that extract (or the project's latest general payment) opens, else an
        empty form; while creating or editing, the typed values stay and move there.
        """
        companies = [c["company_id"] for c in companies_of(self.catalog, contractor_id)]
        if company_id not in companies:
            company_id = companies[0] if companies else None
        projects = [p["project_id"] for p in projects_of(self.catalog, contractor_id, company_id)]
        if project_id not in projects:
            project_id = projects[0] if projects else None
        extracts = [x["extract_id"] for x in extracts_of(self.catalog, contractor_id, company_id, project_id)]
        if project_id is None:
            extract_id = None
        elif extract_id is AUTO or (extract_id is not None and extract_id not in extracts):
            extract_id = extracts[-1] if extracts else None  # the latest extract
        self.contractor_id, self.company_id, self.project_id, self.extract_id = (
            contractor_id, company_id, project_id, extract_id)
        if self.mode != "view":
            self._sync()
            return
        try:
            payments = self._target_payments()
        except Exception as exc:
            self._show_error("تعذّر تحميل الدفعات", exc)
            payments = []
        if payments:
            self.load_payment(payments[-1]["payment_id"])
        else:
            self._show_empty()

    def _target_payments(self) -> list[dict[str, Any]]:
        """The payments of the selected extract, or the project's general ones."""
        if self.extract_id is not None:
            return self.service.payments(extract_id=self.extract_id)
        if self.project_id is not None:
            return self.service.payments(contractor_id=self.contractor_id, project_id=self.project_id)
        return []

    def _on_tree_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        if self.mode == "view" and key[0] == "x" and str(key[1]) == str(self.extract_id):
            return
        if key[0] == "x":
            row = self._catalog_row(key[1])
            if row:
                self.select(row["contractor_id"], row["company_id"], row["project_id"], row["extract_id"])
        elif key[0] == "g":
            if self.mode == "view" and self.extract_id is None and key[3] == self.project_id \
                    and key[1] == self.contractor_id:
                return
            self.select(key[1], key[2], key[3], None)
        elif key[0] == "p":
            self.select(key[1], key[2], key[3])
        elif key[0] == "co":
            self.select(key[1], key[2])
        elif key[0] == "c":
            self.select(key[1])

    def _on_board_contractor(self, _index: int) -> None:
        self.select(self.board_contractor.currentData())

    def _on_board_company(self, _index: int) -> None:
        self.select(self.contractor_id, self.board_company.currentData())

    def _on_board_project(self, _index: int) -> None:
        self.select(self.contractor_id, self.company_id, self.board_project.currentData())

    def _on_extract_combo(self, combo: QComboBox) -> None:
        data = combo.currentData()
        self.select(self.contractor_id, self.company_id, self.project_id, None if data == GENERAL else data)

    def _on_card_clicked(self, extract_id: Any) -> None:
        if self.mode == "view" and extract_id == self.extract_id:
            return
        self.select(self.contractor_id, self.company_id, self.project_id, extract_id)

    def _on_table_clicked(self, table: QTableWidget, row: int) -> None:
        item = table.item(row, 0)
        payment_id = item.data(Qt.UserRole) if item is not None else None
        if payment_id is None:
            return
        if self._busy():
            self._mark_tables()
            return
        self.load_payment(payment_id)

    # -- drawing -----------------------------------------------------------------------------------

    def _build_tree(self) -> None:
        """The tree from the catalog; the search box keeps the extracts whose path matches."""
        needle = self.tree_search.text().strip().lower()
        self.tree.blockSignals(True)
        self.tree.clear()
        self._tree_items = {}
        bold = self.tree.font()
        bold.setBold(True)
        for row in self.catalog:
            if needle:
                path = " ".join(str(row.get(k) or "") for k in (
                    "contractor_code", "contractor_name", "company_name", "project_name", "extract_no")).lower()
                if needle not in path:
                    continue
            levels = (
                (("c", row["contractor_id"]), f"👷 {row['contractor_name']}"),
                (("co", row["contractor_id"], row["company_id"]), f"🏢 {row['company_name']}"),
                (("p", row["contractor_id"], row["company_id"], row["project_id"]), f"📁 {row['project_name']}"),
            )
            parent = None
            for key, text in levels:
                if key not in self._tree_items:
                    item = QTreeWidgetItem([text, ""])
                    item.setData(0, Qt.UserRole, key)
                    if key[0] == "c":
                        item.setFont(0, bold)
                    if parent is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    self._tree_items[key] = item
                    if key[0] == "p":
                        paid = general_paid(self.general, row["contractor_id"], row["project_id"])
                        general = QTreeWidgetItem(["💵 دفعات عامة (بدون مستخلص)", f"مدفوع {_money(paid)}" if paid else ""])
                        general.setData(0, Qt.UserRole, ("g", *key[1:]))
                        general.setForeground(0, QBrush(QColor(GREEN_DARK)))
                        general.setForeground(1, QBrush(QColor(BLUE)))
                        item.addChild(general)
                        self._tree_items[("g", *key[1:])] = general
                parent = self._tree_items[key]
            remaining = to_decimal(row["remaining"])
            leaf = QTreeWidgetItem([f"🧾 {row['extract_no']}", "مسدد" if remaining <= 0 else f"متبقي {_money(remaining)}"])
            leaf.setData(0, Qt.UserRole, ("x", row["extract_id"]))
            leaf.setForeground(1, QBrush(QColor("#64748B" if remaining <= 0 else AMBER)))
            if remaining <= 0:
                leaf.setForeground(0, QBrush(QColor("#94A3B8")))
            parent.addChild(leaf)
            self._tree_items[("x", row["extract_id"])] = leaf
        if needle:
            self.tree.expandAll()
        self.tree.blockSignals(False)
        self._mark_tree()

    def _mark_tree(self) -> None:
        key = ("x", self.extract_id) if self.extract_id is not None else (
            "g", self.contractor_id, self.company_id, self.project_id)
        item = self._tree_items.get(key)
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        if item is not None:
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        self.tree.blockSignals(False)

    def _sync(self) -> None:
        """Every view of the selection, in both tabs."""
        row = self._catalog_row(self.extract_id)
        companies = companies_of(self.catalog, self.contractor_id)
        projects = projects_of(self.catalog, self.contractor_id, self.company_id)
        extracts = extracts_of(self.catalog, self.contractor_id, self.company_id, self.project_id)
        contractor = next((c for c in self.contractors if str(c["contractor_id"]) == str(self.contractor_id)), None)
        company = next((c for c in companies if c["company_id"] == self.company_id), None)
        project = next((p for p in projects if p["project_id"] == self.project_id), None)

        # tab 4
        self.tree_contractor.setText((contractor or {}).get("contractor_name") or (row or {}).get("contractor_name") or "")
        self.tree_company.setText((company or {}).get("company_name") or "")
        self.tree_project.setText((project or {}).get("project_name") or "")
        choices = ([{"extract_id": GENERAL}] + extracts) if self.project_id is not None else []
        chosen = GENERAL if self.extract_id is None else self.extract_id
        self._fill_combo(self.tree_extract, choices, self._choice_text, "extract_id", chosen)
        self._mark_tree()

        # tab 7
        self.board_contractor.blockSignals(True)
        _select_data(self.board_contractor, self.contractor_id)
        self.board_contractor.blockSignals(False)
        self._fill_combo(self.board_company, companies, lambda r: f"{r['company_code']} — {r['company_name']}",
                         "company_id", self.company_id)
        self._fill_combo(self.board_project, projects, lambda r: f"{r['project_code']} — {r['project_name']}",
                         "project_id", self.project_id)
        self._fill_combo(self.board_extract, choices, self._choice_text, "extract_id", chosen)
        on_project = project_balance(self.catalog, self.general, self.contractor_id, self.company_id, self.project_id)
        self.board_path.setText(
            f"🏢 {(company or {}).get('company_name', '—')}   /   📁 {(project or {}).get('project_name', '—')}"
            f"   ·   المتبقي على المشروع {_money(on_project['remaining'])}"
            if company else "لا توجد مستخلصات لهذا المقاول. أضف عقد ومستخلص الأول.")
        self._fill_cards(extracts)

        try:
            extract_payments = self._target_payments()
            contractor_payments = (self.service.payments(contractor_id=self.contractor_id)
                                   if self.contractor_id is not None else [])
        except Exception as exc:
            self._show_error("تعذّر تحميل الدفعات", exc)
            extract_payments, contractor_payments = [], []
        summary = contractor_summary(self.catalog, self.contractor_id, self.general)
        has = self.contractor_id is not None
        self.board_kpis["net"].setText(_money(summary["net"]) if has else "—")
        self.board_kpis["paid"].setText(_money(summary["paid"]) if has else "—")
        self.board_kpis["remaining"].setText(_money(summary["remaining"]) if has else "—")
        self.board_kpis["count"].setText(str(len(approved_only(contractor_payments))) if has else "—")
        self.tree_table_title.setText(
            f"دفعات المستخلص {row['extract_no']}" if row else
            "الدفعات العامة على المشروع (بدون مستخلص)" if self.project_id is not None else "الدفعات")
        self._fill_table(self.tree_table, extract_payments, with_project=False)
        self._fill_table(self.board_table, contractor_payments, with_project=True)
        self._update_balance()

    @staticmethod
    def _choice_text(row: dict[str, Any]) -> str:
        return GENERAL_TEXT if row["extract_id"] == GENERAL else extract_label(row)

    def _fill_cards(self, extracts: list[dict[str, Any]]) -> None:
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._cards = {}
        cards = [self._build_extract_card(row) for row in extracts]
        if self.project_id is not None:
            cards.insert(0, self._build_general_card(general_paid(self.general, self.contractor_id, self.project_id)))
        for index, card in enumerate(cards):
            self.cards_grid.addWidget(card, index // CARD_COLUMNS, index % CARD_COLUMNS)
        self._mark_cards()

    def _mark_cards(self) -> None:
        for extract_id, button in self._cards.items():
            selected = (self.extract_id is None) if extract_id == GENERAL else str(extract_id) == str(self.extract_id)
            button.setStyleSheet(
                f"QPushButton {{ background:{'#F0FDF4' if selected else '#FFFFFF'}; border-radius:10px; "
                f"border:{'2px solid ' + GREEN if selected else '1px solid #D9E2EC'}; text-align:right; }}"
                "QPushButton:hover { background:#F8FAFC; }"
            )

    def _fill_table(self, table: QTableWidget, payments: list[dict[str, Any]], with_project: bool) -> None:
        amount_col = 3 if with_project else 2
        table.setRowCount(len(payments) + (1 if payments else 0))
        # Every payment is listed; the totals row counts the approved ones only.
        approved = approved_only(payments)
        total = sum((to_decimal(record.get("amount")) for record in approved), Decimal("0"))
        for index, record in enumerate(payments):
            values = [f"{_date_text(record.get('payment_date'))}{draft_suffix(record)}", record.get("extract_no") or ""]
            if with_project:
                values.append(record.get("project_name") or "")
            values += [_money(record.get("amount")), method_text(record), record.get("notes") or ""]
            for col, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setData(Qt.UserRole, record["payment_id"])
                if col == amount_col:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(index, col, item)
        if payments:
            values = (["إجمالي المعتمد", f"{len(approved)} دفعة"] + ([""] if with_project else [])
                      + [_money(total), "", ""])
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled)
                item.setForeground(Qt.darkGreen)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                if col == amount_col:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(len(payments), col, item)
        self._mark_tables()

    def _mark_tables(self) -> None:
        for table in (self.tree_table, self.board_table):
            table.blockSignals(True)
            table.clearSelection()
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and self.current_id is not None and str(item.data(Qt.UserRole)) == str(self.current_id):
                    table.selectRow(row)
            table.blockSignals(False)

    def current_balance(self) -> dict[str, Decimal] | None:
        """Where the payment on screen leaves its extract — or, for a general payment,
        the project (all the contractor's extracts on it). None: no project chosen."""
        record = self.current_record or {}
        if self.extract_id is not None:
            row = self._catalog_row(self.extract_id)
            if row is None:
                return None
            net, paid = row["net"], row["paid"]
            mine = str(record.get("extract_id")) == str(self.extract_id)
        elif self.project_id is not None:
            on_project = project_balance(self.catalog, self.general, self.contractor_id, self.company_id,
                                         self.project_id)
            net, paid = on_project["net"], on_project["paid"]
            mine = (record.get("extract_id") is None and str(record.get("contractor_id")) == str(self.contractor_id)
                    and str(record.get("project_id")) == str(self.project_id))
        else:
            return None
        saved = to_decimal(record.get("amount")) if self.mode != "new" and mine else Decimal("0")
        # An approved payment is already inside ``paid`` (a draft is not): count it once, as «this».
        counted = saved if record.get("status") == APPROVED else Decimal("0")
        amount = self.fields.amount.text() if self.mode != "view" else saved
        return payment_balance(net, paid, counted, amount)

    def _update_balance(self, *_args) -> None:
        if not hasattr(self, "tabs"):
            return
        balance = self.current_balance()
        general = self.extract_id is None
        self._captions["tree_stat_net"].setText("صافي مستخلصات المشروع" if general else "صافي المستخلص")
        self._captions["tree_stat_remaining"].setText("المتبقي على المشروع بعد الدفعة" if general else "المتبقي بعد الدفعة")
        self.board_remaining_caption.setText(
            "المتبقي على المشروع بعد الدفعة" if general else "المتبقي على المستخلص بعد الدفعة")
        for key, label in self.tree_stats.items():
            label.setText(_money(balance[key]) if balance else "—")
        self.board_remaining.setText(_money(balance["remaining"]) if balance else "—")
        over = bool(balance) and balance["remaining"] < 0
        target = "المشروع" if general else "المستخلص"
        text = f"⚠ المبلغ أكبر من المتبقي على {target} بـ {_money(-balance['remaining'])}" if over else ""
        for warning in (self.tree_warning, self.board_warning):
            warning.setText(text)
            warning.setVisible(over)
        color = RED if over else AMBER
        self.tree_stats["remaining"].setStyleSheet(f"font-size:18px; font-weight:900; color:{color}; background:transparent;")
        self.board_remaining.setStyleSheet(f"font-size:15px; font-weight:900; color:{color}; background:transparent;")

    # -- loading -----------------------------------------------------------------------------------

    def load_payment(self, payment_id: Any) -> None:
        try:
            record = self.service.get_payment(payment_id)
        except Exception as exc:
            self._show_error("فشل تحميل الدفعة", exc)
            return
        if not record:
            self.current_id, self.current_record = None, None
            self.select(self.contractor_id, self.company_id, self.project_id,
                        self.extract_id if self.project_id is not None else AUTO)
            return
        self.current_id, self.current_record = record["payment_id"], dict(record)
        self.contractor_id, self.company_id = record["contractor_id"], record["company_id"]
        self.project_id, self.extract_id = record["project_id"], record["extract_id"]
        for fields in self.fields_pair:
            fields.fill(record)
        self.set_mode("view")
        self._sync()

    def _show_empty(self) -> None:
        self.current_id, self.current_record = None, None
        for fields in self.fields_pair:
            fields.clear()
        self.set_mode("view")
        self._sync()

    # -- «بحث» (F1) ----------------------------------------------------------------------------------

    def open_search(self) -> None:
        if self._busy():
            return
        dialog = ContractorPaymentPickerDialog(self.service.search_payments, self)
        if dialog.exec() != ContractorPaymentPickerDialog.Accepted or not dialog.selected:
            return
        self.load_payment(dialog.selected["payment_id"])

    # -- new / edit / save / delete ----------------------------------------------------------------

    def _busy(self) -> bool:
        if self.mode in {"new", "edit"}:
            QMessageBox.information(self, "جاري التعديل", "احفظ التعديلات أو ألغِها الأول.")
            return True
        return False

    def new_payment(self) -> None:
        if self._busy() or not self._perm_create:
            return
        self.fields.clear()
        self.set_mode("new")
        self._mark_tables()
        self._update_balance()
        self.fields.amount.setFocus()

    def _status(self) -> Any:
        return (self.current_record or {}).get("status") if self.current_id is not None else None

    def edit_record(self) -> None:
        if (self.current_id is not None and self.mode == "view" and self._perm_edit
                and self.approval.may_edit(self._status())):
            self.set_mode("edit")
            self.fields.amount.setFocus()

    def save_record(self) -> None:
        if self.mode not in {"new", "edit"}:
            return
        data = dict(self.fields.values(), contractor_id=self.contractor_id, project_id=self.project_id,
                    extract_id=self.extract_id)
        balance = self.current_balance()
        if balance and balance["remaining"] < 0 and to_decimal(data["amount"]) > 0:
            answer = QMessageBox.question(
                self, "المبلغ أكبر من المتبقي",
                f"المبلغ أكبر من المتبقي على {'المشروع' if self.extract_id is None else 'المستخلص'} "
                f"بـ {_money(-balance['remaining'])}.\nتحفظ الدفعة برضه؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            saved = self.service.save_payment(data, None if self.mode == "new" else self.current_id,
                                              allow_approved=self.approval.is_admin)
        except (PaymentError, ApprovalError) as exc:
            QMessageBox.warning(self, "لا يمكن الحفظ", str(exc))
            return
        except Exception as exc:
            self._show_error("فشل حفظ الدفعة", exc)
            return
        self.mode = "view"
        self._reload_data()
        self.load_payment(saved)
        notify_data_changed(self)
        QMessageBox.information(self, "تم الحفظ", self.approval.saved_message(self._status(), "الدفعة"))

    def cancel_edit(self) -> None:
        self.mode = "view"
        if self.current_id is not None:
            self.load_payment(self.current_id)
        else:
            self.select(self.contractor_id, self.company_id, self.project_id,
                        self.extract_id if self.project_id is not None else AUTO)

    def delete_record(self) -> None:
        if (self.current_id is None or self.mode != "view" or not self._perm_delete
                or not self.approval.may_delete(self._status())):
            return
        record = self.current_record or {}
        answer = QMessageBox.question(
            self, "تأكيد الحذف",
            f"هل تريد حذف دفعة {_money(record.get('amount'))} بتاريخ {_date_text(record.get('payment_date'))} "
            + ("(دفعة عامة)؟" if record.get("extract_id") is None else f"من المستخلص «{record.get('extract_no', '')}»؟"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.delete_payment(self.current_id, allow_approved=self.approval.is_admin)
        except ApprovalError as exc:
            QMessageBox.warning(self, "لا يمكن الحذف", str(exc))
            return
        except Exception as exc:
            self._show_error("لا يمكن حذف الدفعة", exc)
            return
        self.current_id, self.current_record = None, None
        self._reload_data()
        self.select(self.contractor_id, self.company_id, self.project_id,
                    self.extract_id if self.project_id is not None else AUTO)
        notify_data_changed(self)

    # -- اعتماد / إلغاء الاعتماد ---------------------------------------------------------------------

    def _payment_text(self) -> str:
        record = self.current_record or {}
        return f"دفعة {_money(record.get('amount'))} بتاريخ {_date_text(record.get('payment_date'))}"

    def approve_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_approve:
            return
        payment_id = self.current_id
        if self.approval.approve(self._payment_text(),
                                 lambda: self.service.approve(payment_id, self.approval.user_id())):
            self._reload_data()
            self.load_payment(payment_id)
            QMessageBox.information(self, "تم", "تم اعتماد الدفعة.")

    def unapprove_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_unapprove:
            return
        payment_id = self.current_id
        if self.approval.unapprove(self._payment_text(), lambda: self.service.unapprove(payment_id)):
            self._reload_data()
            self.load_payment(payment_id)
            QMessageBox.information(self, "تم", "تم إلغاء اعتماد الدفعة، ورجعت مسودة.")

    # -- modes ---------------------------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        editing = mode in {"new", "edit"}
        for fields in self.fields_pair:
            fields.set_editing(editing and fields is self.fields)
        has_record = self.current_id is not None
        status = self._status()
        self.new_button.setEnabled(not editing and self._perm_create)
        self.edit_button.setEnabled(not editing and has_record and self._perm_edit and self.approval.may_edit(status))
        self.delete_button.setEnabled(not editing and has_record and self._perm_delete
                                      and self.approval.may_delete(status))
        self.save_button.setEnabled(editing and self._perm_save)
        self.cancel_button.setEnabled(editing)
        self.approval.update(editing, status, self.edit_button, self.delete_button)
        self.search_button.setEnabled(not editing)
        self.refresh_button.setEnabled(not editing)
        self.tabs.tabBar().setEnabled(not editing)
        self.mode_badge.setText({"view": "عرض", "new": "جديد", "edit": "تعديل"}.get(mode, mode))

    def _show_error(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, str(exc))
