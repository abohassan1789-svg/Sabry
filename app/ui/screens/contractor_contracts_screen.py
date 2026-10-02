"""شاشة عقود المقاولين — النموذجان 7 و8 كتبويبين (2026-09-25).

The user asked for both mockups side by side as tabs, to choose one by using it:

* «شجرة الشركات والمشاريع» (نموذج 7): a tree company → project → contracts on
  the right, the selected contract's form beside it with a table of the four
  rates and their amounts.
* «بطاقة المقاول» (نموذج 8): pick a contractor at the top to see his card
  (code, type, count, totals) and his contracts as cards; the selected
  contract's form sits on the left.

Both tabs edit the same contract; each has its own form widget
(``ContractForm``, wide or compact), and switching tabs is locked while a
contract is being edited. A contract stores the project only — the company is
the project's, so picking a company just narrows the project list.

مسودة / معتمد (2026-10-02): «حفظ» keeps a contract as a draft, «اعتماد» /
«إلغاء الاعتماد» (``ApprovalControls``) move it; drafts are marked in the tree
and on the cards. An approved contract is locked except for an admin.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.security.session_context import SESSION
from app.services.contracting_approval import ApprovalError
from app.services.contractor_contract_service import (
    RATE_FIELDS,
    ContractError,
    ContractorContractService,
    contract_amounts,
    to_decimal,
)
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.screens.approval_controls import ApprovalControls, draft_suffix, status_chip
from app.ui.common.live_lists import notify_data_changed

PERMISSION_BASE = "contracting.contractor_contracts"
BLUE = "#0369A1"
MUTED = "#475569"
CARD_COLUMNS = 2
TAB_TREE, TAB_CONTRACTOR = 0, 1

# One colour per rate, as in the mockups: المقدمة blue, التأمين purple,
# الضرائب amber, التأمينات teal.
RATE_COLORS = {
    "advance_payment_pct": ("#0369A1", "#E0F2FE"),
    "works_insurance_pct": ("#6D28D9", "#EDE9FE"),
    "tax_discount_pct": ("#B45309", "#FEF3C7"),
    "social_insurance_pct": ("#0F766E", "#CCFBF1"),
}

_EDITOR_QSS = (
    f"QLineEdit, QDateEdit {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:7px; "
    f"padding:6px 10px; font-size:14px; font-weight:900; color:{TEXT}; }}"
    f"QLineEdit:focus, QDateEdit:focus {{ border:2px solid {GREEN_DARK}; }}"
    "QLineEdit:read-only { background:#F8FAFC; color:#334155; }"
    "QDateEdit:read-only { background:#F8FAFC; color:#334155; }"
)
_COMBO_QSS = (
    f"QComboBox {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:7px; "
    f"padding:6px 10px; font-size:14px; font-weight:900; color:{TEXT}; }}"
    "QComboBox:disabled { background:#F8FAFC; color:#334155; }"
)
_CARD_QSS = "background:#FFFFFF; border:1px solid #E5EAF0; border-radius:10px;"


def _money(value: Any) -> str:
    return f"{Decimal(str(value or 0)):,.2f}"


def _rate_text(value: Any) -> str:
    """«10» for 10.00, «2.5» for 2.50 — the way the rate is spoken."""
    rate = Decimal(str(value or 0)).normalize()
    return f"{rate:f}"


def _select_data(combo: QComboBox, value: Any) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else (0 if combo.count() else -1))


def _caption(text: str, size: int = 14, color: str = TEXT) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size:{size}px; font-weight:900; color:{color}; background:transparent; border:none;")
    return label


def _card_frame(name: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName(name)
    frame.setStyleSheet(f"QFrame#{name} {{ {_CARD_QSS} }} QLabel {{ background:transparent; border:none; }}")
    return frame


class ContractForm(QWidget):
    """The contract's fields plus the live rate amounts. ``wide`` = tab 7's layout."""

    def __init__(self, service: ContractorContractService, wide: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.wide = wide
        self._loading = False

        self.contract_no = self._line_edit("رقم العقد", ltr=True)
        self.contract_date = QDateEdit()
        self.contract_date.setCalendarPopup(True)
        self.contract_date.setDisplayFormat("yyyy-MM-dd")
        self.contract_date.setDate(QDate.currentDate())
        self.contract_date.setMinimumHeight(38)
        self.contract_date.setLayoutDirection(Qt.LeftToRight)
        self.contract_date.setStyleSheet(_EDITOR_QSS)
        self.contract_value = self._line_edit("0.00", ltr=True)
        self.contract_value.textChanged.connect(self.recalc)
        self.contract_value.editingFinished.connect(self._format_value)
        self.contractor = self._combo()
        self.company = self._combo()
        self.project = self._combo()
        self.company.currentIndexChanged.connect(self._on_company_changed)

        self.rates: dict[str, QDoubleSpinBox] = {}
        self.amounts: dict[str, QLabel] = {}
        for key, _label in RATE_FIELDS:
            color = RATE_COLORS[key][0]
            spin = QDoubleSpinBox()
            spin.setRange(0, 100)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setSuffix(" %")
            spin.setMinimumHeight(36)
            spin.setFixedWidth(110)
            spin.setLayoutDirection(Qt.LeftToRight)
            spin.setAlignment(Qt.AlignCenter)
            spin.setStyleSheet(
                f"QDoubleSpinBox {{ background:#FFFFFF; border:1.5px solid {color}; border-radius:7px; "
                f"padding:4px 6px; font-size:15px; font-weight:900; color:{color}; }}"
                "QDoubleSpinBox:read-only { background:#F8FAFC; }"
            )
            spin.valueChanged.connect(self.recalc)
            self.rates[key] = spin
            amount = QLabel("0.00")
            amount.setLayoutDirection(Qt.LeftToRight)
            amount.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
            amount.setMinimumWidth(130)
            amount.setStyleSheet(
                "background:#EEF2F6; border:1px solid #CBD5E1; border-radius:7px; padding:7px 10px; "
                f"font-size:14px; font-weight:900; color:{TEXT};"
            )
            self.amounts[key] = amount
        self.breadcrumb = QLabel("")
        self.breadcrumb.setWordWrap(True)
        self.breadcrumb.setStyleSheet(f"font-size:13px; font-weight:800; color:{MUTED}; background:transparent; border:none;")

        (self._build_wide if wide else self._build_compact)()
        self.set_editing(False)

    # -- widgets -------------------------------------------------------------

    def _line_edit(self, placeholder: str, ltr: bool = False) -> QLineEdit:
        editor = QLineEdit()
        editor.setMinimumHeight(38)
        editor.setPlaceholderText(placeholder)
        editor.setStyleSheet(_EDITOR_QSS)
        if ltr:
            editor.setLayoutDirection(Qt.LeftToRight)
            editor.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return editor

    def _combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumHeight(38)
        combo.setStyleSheet(_COMBO_QSS)
        # Long «code — name» items must not widen the form past its panel.
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        return combo

    def _labelled(self, caption: str, editor: QWidget) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(5)
        column.addWidget(_caption(caption))
        column.addWidget(editor)
        return box

    def _fields(self) -> list[tuple[str, QWidget]]:
        return [("رقم العقد", self.contract_no), ("تاريخ العقد", self.contract_date),
                ("قيمة العقد (ج.م)", self.contract_value), ("اسم المقاول", self.contractor),
                ("اسم الشركة", self.company), ("اسم المشروع", self.project)]

    def _rates_grid(self, headers: bool) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        row = 0
        if headers:
            for col, text in enumerate(("البند", "النسبة", "المبلغ (ج.م)")):
                grid.addWidget(_caption(text, 13, MUTED), row, col)
            row += 1
        for key, label in RATE_FIELDS:
            color = RATE_COLORS[key][0]
            caption = QLabel(f"■  {label}")
            caption.setStyleSheet(f"font-size:14px; font-weight:900; color:{TEXT}; background:transparent; border:none;")
            caption.setText(f"<span style='color:{color}'>■</span>&nbsp;&nbsp;{label}")
            grid.addWidget(caption, row, 0)
            grid.addWidget(self.rates[key], row, 1)
            grid.addWidget(self.amounts[key], row, 2)
            row += 1
        # إجمالي الاستقطاعات / الصافي are not shown (user request, 2026-09-25).
        # Wide: keep label, rate and amount together and leave the slack after
        # them; compact: the label column takes the slack.
        grid.setColumnStretch(3 if self.wide else 0, 1)
        return grid

    def _build_wide(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        data_card = _card_frame("contract_data_card")
        data = QVBoxLayout(data_card)
        data.setContentsMargins(16, 14, 16, 16)
        data.setSpacing(10)
        data.addWidget(self.breadcrumb)
        data.addWidget(_caption("بيانات العقد", 16, GREEN))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        for index, (caption, editor) in enumerate(self._fields()):
            grid.addWidget(self._labelled(caption, editor), index // 3, index % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        data.addLayout(grid)
        root.addWidget(data_card)

        rates_card = _card_frame("contract_rates_card")
        rates = QVBoxLayout(rates_card)
        rates.setContentsMargins(16, 14, 16, 16)
        rates.setSpacing(10)
        rates.addWidget(_caption("النسب والمبالغ", 16, GREEN))
        rates.addLayout(self._rates_grid(headers=True))
        root.addWidget(rates_card)
        root.addStretch(1)

    def _build_compact(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)
        root.addWidget(_caption("تفاصيل العقد المحدد", 16, GREEN))
        root.addWidget(self.breadcrumb)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        fields = dict(self._fields())
        grid.addWidget(self._labelled("رقم العقد", fields["رقم العقد"]), 0, 0)
        grid.addWidget(self._labelled("تاريخ العقد", fields["تاريخ العقد"]), 0, 1)
        grid.addWidget(self._labelled("اسم المقاول", fields["اسم المقاول"]), 1, 0, 1, 2)
        grid.addWidget(self._labelled("اسم الشركة", fields["اسم الشركة"]), 2, 0, 1, 2)
        grid.addWidget(self._labelled("اسم المشروع", fields["اسم المشروع"]), 3, 0, 1, 2)
        grid.addWidget(self._labelled("قيمة العقد (ج.م)", fields["قيمة العقد (ج.م)"]), 4, 0, 1, 2)
        root.addLayout(grid)
        root.addSpacing(4)
        root.addLayout(self._rates_grid(headers=False))
        root.addStretch(1)

    # -- choices ---------------------------------------------------------------

    def load_choices(self) -> None:
        """Refill the contractor and company lists, keeping what is selected."""
        self._loading = True
        try:
            keep_contractor = self.contractor.currentData()
            keep_company = self.company.currentData()
            keep_project = self.project.currentData()
            try:
                contractors = self.service.contractor_choices()
                companies = self.service.company_choices()
            except Exception:
                contractors, companies = [], []
            self.contractor.clear()
            for row in contractors:
                self.contractor.addItem(f"{row['contractor_code']} — {row['contractor_name']}", row["contractor_id"])
            self.company.clear()
            for row in companies:
                self.company.addItem(f"{row['company_code']} — {row['company_name']}", row["company_id"])
            _select_data(self.contractor, keep_contractor)
            _select_data(self.company, keep_company)
            self.set_projects(self.company.currentData(), keep_project)
        finally:
            self._loading = False

    def set_projects(self, company_id: Any, select_project: Any = None) -> None:
        self.project.blockSignals(True)
        self.project.clear()
        try:
            projects = self.service.project_choices(company_id)
        except Exception:
            projects = []
        for row in projects:
            self.project.addItem(f"{row['project_code']} — {row['project_name']}", row["project_id"])
        _select_data(self.project, select_project)
        self.project.blockSignals(False)

    def _on_company_changed(self, _index: int) -> None:
        if not self._loading:
            self.set_projects(self.company.currentData())

    # -- values ------------------------------------------------------------------

    def fill(self, record: dict[str, Any]) -> None:
        self._loading = True
        try:
            self.contract_no.setText(str(record.get("contract_no") or ""))
            date = record.get("contract_date")
            if isinstance(date, (datetime.date, datetime.datetime)):
                self.contract_date.setDate(QDate(date.year, date.month, date.day))
            _select_data(self.contractor, record.get("contractor_id"))
            _select_data(self.company, record.get("company_id"))
            self.set_projects(record.get("company_id"), record.get("project_id"))
            self.contract_value.setText(_money(record.get("contract_value")))
            for key, _label in RATE_FIELDS:
                self.rates[key].setValue(float(record.get(key) or 0))
            self.breadcrumb.setText(
                f"🏢 {record.get('company_name') or ''}  ›  📁 {record.get('project_name') or ''}"
                f"  ›  📄 {record.get('contract_no') or ''}"
            )
        finally:
            self._loading = False
        self.recalc()

    def clear(self, breadcrumb: str = "") -> None:
        self._loading = True
        try:
            self.contract_no.clear()
            self.contract_date.setDate(QDate.currentDate())
            self.contract_value.clear()
            for spin in self.rates.values():
                spin.setValue(0)
            self.breadcrumb.setText(breadcrumb)
        finally:
            self._loading = False
        self.recalc()

    def start_new(self, contract_no: str, contractor_id: Any = None, company_id: Any = None,
                  project_id: Any = None) -> None:
        self.clear("عقد جديد")
        self.contract_no.setText(contract_no)
        if contractor_id is not None:
            _select_data(self.contractor, contractor_id)
        if company_id is not None:
            self._loading = True
            _select_data(self.company, company_id)
            self._loading = False
            self.set_projects(company_id, project_id)

    def data(self) -> dict[str, Any]:
        values = {
            "contract_no": self.contract_no.text(),
            "contract_date": self.contract_date.date().toString("yyyy-MM-dd"),
            "contractor_id": self.contractor.currentData(),
            "project_id": self.project.currentData(),
            "contract_value": self.contract_value.text(),
        }
        for key, spin in self.rates.items():
            values[key] = Decimal(str(round(spin.value(), 2)))
        return values

    def recalc(self) -> None:
        amounts = contract_amounts(self.contract_value.text(),
                                   {key: spin.value() for key, spin in self.rates.items()})
        for key, label in self.amounts.items():
            label.setText(_money(amounts[key]))

    def _format_value(self) -> None:
        text = self.contract_value.text().strip()
        if text and not self.contract_value.isReadOnly():
            self.contract_value.setText(_money(to_decimal(text)))

    def set_editing(self, editing: bool) -> None:
        for editor in (self.contract_no, self.contract_value):
            editor.setReadOnly(not editing)
        self.contract_date.setReadOnly(not editing)
        self.contract_date.setCalendarPopup(editing)
        for combo in (self.contractor, self.company, self.project):
            combo.setEnabled(editing)
        for spin in self.rates.values():
            spin.setReadOnly(not editing)
            spin.setButtonSymbols(QDoubleSpinBox.UpDownArrows if editing else QDoubleSpinBox.NoButtons)


class ContractorContractsScreen(QWidget):
    def __init__(self, service: ContractorContractService | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service or ContractorContractService()
        self.current_id: Any = None
        self.current_record: dict[str, Any] | None = None
        self.mode = "view"
        self._tree_items: dict[tuple[str, Any], QTreeWidgetItem] = {}
        self._cards: dict[Any, QPushButton] = {}

        self._perm_create = SESSION.can(f"{PERMISSION_BASE}.create")
        self._perm_edit = SESSION.can(f"{PERMISSION_BASE}.edit")
        self._perm_save = SESSION.can(f"{PERMISSION_BASE}.save")
        self._perm_delete = SESSION.can(f"{PERMISSION_BASE}.delete")

        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("QWidget { font-family: 'Segoe UI', 'Tahoma', 'Arial'; }")
        self.approval = ApprovalControls(self, PERMISSION_BASE, locked_when_approved=True)
        self._build_ui()
        self.refresh_all()
        self.set_mode("view")

    # -- layout ------------------------------------------------------------------

    @property
    def form(self) -> ContractForm:
        """The form of the tab in front — the one «جديد» and «تعديل» act on."""
        return self.tree_form if self.tabs.currentIndex() == TAB_TREE else self.card_form

    @property
    def forms(self) -> tuple[ContractForm, ContractForm]:
        return self.tree_form, self.card_form

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
        self.tabs.addTab(self._build_tree_tab(), "🌳  شجرة الشركات والمشاريع (نموذج 7)")
        self.tabs.addTab(self._build_contractor_tab(), "👷  بطاقة المقاول (نموذج 8)")
        self.tabs.currentChanged.connect(self._on_tab_changed)
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
        icon = QLabel("🤝")
        icon.setFixedSize(54, 54)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background:rgba(255,255,255,0.16); border:1px solid rgba(255,255,255,0.28); "
            "border-radius:7px; font-size:24px; font-weight:900;"
        )
        title = QLabel("عقود المقاولين")
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

        self.new_button = QPushButton("عقد جديد")
        self.edit_button = QPushButton("تعديل")
        self.save_button = QPushButton("حفظ")
        self.delete_button = QPushButton("حذف")
        self.cancel_button = QPushButton("إلغاء")
        self.refresh_button = QPushButton("تحديث")
        self.exit_button = QPushButton("خروج")
        buttons = [
            (self.new_button, QStyle.SP_FileIcon, "#1A7A3C", "#166534"),
            (self.edit_button, QStyle.SP_FileDialogDetailedView, "#64748B", "#475569"),
            (self.save_button, QStyle.SP_DialogSaveButton, "#2563EB", "#1D4ED8"),
            (self.delete_button, QStyle.SP_TrashIcon, "#DC2626", "#B91C1C"),
            (self.cancel_button, QStyle.SP_DialogCancelButton, "#6B7280", "#4B5563"),
            (self.refresh_button, QStyle.SP_BrowserReload, "#FFFFFF", "#F3F4F6"),
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
        self.approval.add_buttons(layout)

        self.search_text = QLineEdit()
        self.search_text.setPlaceholderText("ابحث برقم العقد أو المقاول أو المشروع")
        self.search_text.setFixedHeight(38)
        self.search_text.setMinimumWidth(270)
        self.search_text.setStyleSheet(
            "QLineEdit { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:7px; padding:6px 10px; }"
            f"QLineEdit:focus {{ border:1px solid {GREEN}; }}"
        )
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_views)
        self.search_text.textChanged.connect(self.search_timer.start)
        layout.addWidget(self.search_text)

        layout.addStretch(1)
        self.mode_badge = QLabel("عرض")
        self.mode_badge.setAlignment(Qt.AlignCenter)
        self.mode_badge.setMinimumWidth(100)
        self.mode_badge.setStyleSheet(
            "background:#ECFDF3;color:#087443;border:1px solid #B7E4C7;border-radius:7px;"
            "padding:8px 12px;font-weight:900;"
        )
        layout.addWidget(self.approval.badge)
        layout.addWidget(self.mode_badge)

        self.new_button.clicked.connect(self.new_contract)
        self.approval.approve_button.clicked.connect(self.approve_record)
        self.approval.unapprove_button.clicked.connect(self.unapprove_record)
        self.edit_button.clicked.connect(self.edit_record)
        self.save_button.clicked.connect(self.save_record)
        self.delete_button.clicked.connect(self.delete_record)
        self.cancel_button.clicked.connect(self.cancel_edit)
        self.refresh_button.clicked.connect(self.refresh_all)
        self.exit_button.clicked.connect(self.window().close)
        return bar

    # -- tab 7: the tree ----------------------------------------------------------

    def _build_tree_tab(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(10)

        tree_card = _card_frame("contracts_tree_card")
        tree_card.setFixedWidth(370)
        column = QVBoxLayout(tree_card)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(8)
        column.addWidget(_caption("الشركات والمشاريع والعقود", 15, GREEN))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(22)
        self.tree.setLayoutDirection(Qt.RightToLeft)
        self.tree.setStyleSheet(
            "QTreeWidget { border:none; background:#FFFFFF; font-size:13px; }"
            "QTreeWidget::item { padding:6px 4px; border-radius:6px; }"
            f"QTreeWidget::item:selected {{ background:{GREEN}; color:#FFFFFF; }}"
            "QTreeWidget::item:hover:!selected { background:#F1F5F9; }"
        )
        self.tree.itemClicked.connect(self._on_tree_clicked)
        column.addWidget(self.tree, 1)
        row.addWidget(tree_card, 0)

        self.tree_form = ContractForm(self.service, wide=True)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.tree_form)
        row.addWidget(scroll, 1)
        return page

    def _fill_tree(self, tree: list[dict[str, Any]]) -> None:
        self.tree.clear()
        self._tree_items = {}
        bold = self.tree.font()
        bold.setBold(True)
        for company in tree:
            company_item = QTreeWidgetItem([f"🏢  {company['company_name']}    {company['company_code']}"])
            company_item.setData(0, Qt.UserRole, ("company", company["company_id"], company["company_id"], None))
            company_item.setFont(0, bold)
            company_item.setForeground(0, Qt.darkGreen)
            self.tree.addTopLevelItem(company_item)
            self._tree_items[("company", company["company_id"])] = company_item
            for project in company["projects"]:
                count = len(project["contracts"])
                project_item = QTreeWidgetItem([f"📁  {project['project_name']}   ({count})"])
                project_item.setToolTip(0, str(project["project_code"]))
                project_item.setData(0, Qt.UserRole,
                                     ("project", project["project_id"], company["company_id"], project["project_id"]))
                project_item.setFont(0, bold)
                company_item.addChild(project_item)
                self._tree_items[("project", project["project_id"])] = project_item
                for contract in project["contracts"]:
                    item = QTreeWidgetItem([f"📄  {contract['contract_no']}  —  {contract['contractor_name']}"
                                            f"{draft_suffix(contract)}"])
                    item.setData(0, Qt.UserRole,
                                 ("contract", contract["contract_id"], company["company_id"], project["project_id"]))
                    project_item.addChild(item)
                    self._tree_items[("contract", contract["contract_id"])] = item
        self.tree.expandAll()
        if not tree:
            empty = QTreeWidgetItem(["لا توجد نتائج." if self.search_text.text().strip()
                                     else "أضف الشركات والمشاريع من شاشة «الشركات والمشاريع» أولاً."])
            empty.setFlags(Qt.NoItemFlags)
            self.tree.addTopLevelItem(empty)
        self._mark_tree_selection()

    def _mark_tree_selection(self) -> None:
        item = self._tree_items.get(("contract", self.current_id))
        self.tree.blockSignals(True)
        if item is not None:
            self.tree.setCurrentItem(item)
        else:
            self.tree.clearSelection()
        self.tree.blockSignals(False)

    def _on_tree_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        info = item.data(0, Qt.UserRole)
        if not info:
            return
        if self._busy():
            self._mark_tree_selection()
            return
        if info[0] == "contract":
            self.load_contract(info[1])

    def _tree_context(self) -> tuple[Any, Any]:
        """(company_id, project_id) of the tree's selected row, for «عقد جديد»."""
        item = self.tree.currentItem()
        info = item.data(0, Qt.UserRole) if item is not None else None
        if not info:
            return None, None
        return info[2], info[3]

    # -- tab 8: the contractor's card -----------------------------------------------

    def _build_contractor_tab(self) -> QWidget:
        # The contract panel runs the full height beside the contractor bar and
        # the cards, so every field fits without scrolling (user request).
        page = QWidget()
        page_row = QHBoxLayout(page)
        page_row.setContentsMargins(0, 8, 0, 0)
        page_row.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(10)

        bar = _card_frame("contractor_bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        avatar = QLabel("👷")
        avatar.setFixedSize(60, 60)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background:#EAFBF0; border-radius:12px; font-size:30px;")
        row.addWidget(avatar)
        picker = QVBoxLayout()
        picker.setSpacing(4)
        picker.addWidget(_caption("اسم المقاول", 12, MUTED))
        self.contractor_picker = QComboBox()
        self.contractor_picker.setMinimumHeight(40)
        self.contractor_picker.setMinimumWidth(280)
        self.contractor_picker.setStyleSheet(
            f"QComboBox {{ background:#F8FAFC; border:2px solid {GREEN}; border-radius:8px; padding:6px 10px; "
            f"font-size:15px; font-weight:900; color:{TEXT}; }}"
        )
        self.contractor_picker.currentIndexChanged.connect(self._on_contractor_picked)
        picker.addWidget(self.contractor_picker)
        row.addLayout(picker)
        self.stat_labels: dict[str, QLabel] = {}
        for key, caption in (("code", "كود المقاول"), ("type", "النوع"), ("count", "عدد العقود"),
                             ("total", "إجمالي قيمة العقود"), ("advance", "إجمالي المقدمات")):
            cell = QFrame()
            cell.setObjectName("stat_cell")
            cell.setStyleSheet("QFrame#stat_cell { border:none; border-right:1px solid #D9E2EC; }")
            cell_col = QVBoxLayout(cell)
            cell_col.setContentsMargins(12, 0, 12, 0)
            cell_col.setSpacing(3)
            cell_col.addWidget(_caption(caption, 12, MUTED))
            value = _caption("—", 17, BLUE if key == "advance" else (GREEN if key == "code" else TEXT))
            self.stat_labels[key] = value
            cell_col.addWidget(value)
            row.addWidget(cell)
        row.addStretch(1)
        column.addWidget(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background:transparent; }")
        self.cards_host = QWidget()
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setSpacing(10)
        self.cards_grid.setAlignment(Qt.AlignTop)
        for col in range(CARD_COLUMNS):
            self.cards_grid.setColumnStretch(col, 1)
        scroll.setWidget(self.cards_host)
        column.addWidget(scroll, 1)
        page_row.addLayout(column, 1)

        panel = _card_frame("contract_panel")
        panel.setFixedWidth(480)
        panel_col = QVBoxLayout(panel)
        panel_col.setContentsMargins(0, 0, 0, 0)
        self.card_form = ContractForm(self.service, wide=False)
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setWidget(self.card_form)
        panel_col.addWidget(panel_scroll)
        page_row.addWidget(panel, 0)
        return page

    def _fill_contractor_picker(self) -> None:
        keep = self.contractor_picker.currentData()
        self.contractor_picker.blockSignals(True)
        self.contractor_picker.clear()
        try:
            rows = self.service.contractor_choices()
        except Exception:
            rows = []
        for row in rows:
            self.contractor_picker.addItem(f"{row['contractor_code']} — {row['contractor_name']}", row["contractor_id"])
        _select_data(self.contractor_picker, keep)
        self.contractor_picker.blockSignals(False)

    def _on_contractor_picked(self, _index: int) -> None:
        if self.mode in {"new", "edit"}:
            return
        self._fill_contractor_view()
        # Keep the form on this contractor: his first contract, or nothing.
        contractor_id = self.contractor_picker.currentData()
        if self.current_record and self.current_record.get("contractor_id") == contractor_id:
            return
        if self._cards:
            self.load_contract(next(iter(self._cards)))
        else:
            self._show_empty()

    def _fill_contractor_view(self) -> None:
        contractor_id = self.contractor_picker.currentData()
        card = None
        contracts: list[dict[str, Any]] = []
        if contractor_id is not None:
            try:
                card = self.service.contractor_card(contractor_id)
                contracts = self.service.contracts(self.search_text.text(), contractor_id)
            except Exception as exc:
                self._show_error("تعذّر تحميل عقود المقاول", exc)
        if card:
            self.stat_labels["code"].setText(str(card["contractor_code"]))
            self.stat_labels["type"].setText(str(card.get("contractor_type") or "—"))
            self.stat_labels["count"].setText(str(int(card["contract_count"] or 0)))
            self.stat_labels["total"].setText(_money(card["total_value"]))
            self.stat_labels["advance"].setText(_money(card["total_advance"]))
        else:
            for label in self.stat_labels.values():
                label.setText("—")

        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            if item.widget() is not None:
                # Detach first: a deleteLater() card stays painted until the
                # event loop runs, overlapping the new ones.
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._cards = {}
        if contractor_id is None:
            empty = _caption("أضف المقاولين من شاشة «المقاولين» أولاً.", 15, "#94A3B8")
            empty.setAlignment(Qt.AlignCenter)
            self.cards_grid.addWidget(empty, 0, 0, 1, CARD_COLUMNS)
            return
        for index, contract in enumerate(contracts):
            self.cards_grid.addWidget(self._build_card(contract), index // CARD_COLUMNS, index % CARD_COLUMNS)
        self.new_card_button = QPushButton("＋\nعقد جديد لهذا المقاول")
        self.new_card_button.setMinimumHeight(170)
        self.new_card_button.setCursor(Qt.PointingHandCursor)
        self.new_card_button.setEnabled(self._perm_create)
        self.new_card_button.setStyleSheet(
            "QPushButton { border:2px dashed #94A3B8; border-radius:12px; background:transparent; "
            "font-size:15px; font-weight:900; color:#475569; }"
            "QPushButton:hover { background:#F1F5F9; }"
        )
        self.new_card_button.clicked.connect(self.new_contract)
        position = len(contracts)
        self.cards_grid.addWidget(self.new_card_button, position // CARD_COLUMNS, position % CARD_COLUMNS)
        self._apply_card_selection()

    def _build_card(self, contract: dict[str, Any]) -> QPushButton:
        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(170)
        column = QVBoxLayout(button)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(7)

        top = QHBoxLayout()
        number = _caption(str(contract["contract_no"]), 14, GREEN)
        date = contract.get("contract_date")
        date_label = _caption(f"📅 {date:%Y-%m-%d}" if isinstance(date, datetime.date) else "", 12, MUTED)
        top.addWidget(number)
        top.addWidget(status_chip(contract.get("status")))
        top.addStretch(1)
        top.addWidget(date_label)
        column.addLayout(top)
        project = _caption(f"📁  {contract['project_name']}", 16, TEXT)
        company = _caption(f"🏢  {contract['company_name']}", 13, MUTED)
        column.addWidget(project)
        column.addWidget(company)

        value_row = QFrame()
        value_row.setObjectName("value_row")
        value_row.setStyleSheet("QFrame#value_row { background:#F8FAFC; border-radius:8px; }")
        value_layout = QHBoxLayout(value_row)
        value_layout.setContentsMargins(10, 6, 10, 6)
        value_layout.addWidget(_caption("قيمة العقد", 12, MUTED))
        value_layout.addStretch(1)
        value_layout.addWidget(_caption(_money(contract["contract_value"]), 19, TEXT))
        column.addWidget(value_row)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for key, label in RATE_FIELDS:
            color, tint = RATE_COLORS[key]
            chip = QLabel(f"{label.replace('نسبة ', '')} {_rate_text(contract[key])}%")
            chip.setStyleSheet(
                f"font-size:11px; font-weight:800; color:{color}; background:{tint}; border-radius:6px; padding:3px 7px;"
            )
            chips.addWidget(chip)
        chips.addStretch(1)
        column.addLayout(chips)

        for label in button.findChildren(QLabel):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        value_row.setAttribute(Qt.WA_TransparentForMouseEvents)
        button.clicked.connect(lambda _c=False, cid=contract["contract_id"]: self._on_card_clicked(cid))
        self._cards[contract["contract_id"]] = button
        return button

    def _on_card_clicked(self, contract_id: Any) -> None:
        if self._busy():
            return
        self.load_contract(contract_id)

    def _apply_card_selection(self) -> None:
        for contract_id, button in self._cards.items():
            selected = str(contract_id) == str(self.current_id)
            button.setStyleSheet(
                f"QPushButton {{ background:{'#F0FDF4' if selected else '#FFFFFF'}; border-radius:12px; "
                f"border:{'2px solid ' + GREEN if selected else '1px solid #D9E2EC'}; text-align:right; }}"
                "QPushButton:hover { background:#F8FAFC; }"
            )

    # -- loading -----------------------------------------------------------------------

    def refresh_all(self) -> None:
        """Reload the choice lists and both views, keeping the open contract."""
        for form in self.forms:
            form.load_choices()
        self._fill_contractor_picker()
        self.refresh_views()
        if self.current_id is not None and self.mode == "view":
            self.load_contract(self.current_id)
        elif self.mode == "view":
            self._show_empty()

    def reload_lists(self) -> None:
        """Data changed in another screen: refill the lists, keeping the open contract.

        The tree keeps its scroll position: the rebuild would jump it to the top.
        """
        if self.mode in {"new", "edit"}:
            return
        bar = self.tree.verticalScrollBar()
        position = bar.value()
        self.refresh_all()
        bar.setValue(position)

    def refresh_views(self) -> None:
        self.search_timer.stop()
        try:
            tree = self.service.tree(self.search_text.text())
        except Exception as exc:
            self._show_error("تعذّر تحميل العقود", exc)
            tree = []
        self._fill_tree(tree)
        self._fill_contractor_view()

    def load_contract(self, contract_id: Any) -> None:
        try:
            record = self.service.get_contract(contract_id)
        except Exception as exc:
            self._show_error("فشل تحميل العقد", exc)
            return
        if not record:
            self._show_empty()
            return
        self.current_id, self.current_record = record["contract_id"], dict(record)
        for form in self.forms:
            form.fill(record)
        # Keep tab 8 on this contract's contractor.
        if self.contractor_picker.currentData() != record["contractor_id"]:
            self.contractor_picker.blockSignals(True)
            _select_data(self.contractor_picker, record["contractor_id"])
            self.contractor_picker.blockSignals(False)
            self._fill_contractor_view()
        self.set_mode("view")
        self._mark_tree_selection()
        self._apply_card_selection()

    def _show_empty(self) -> None:
        self.current_id, self.current_record = None, None
        for form in self.forms:
            form.clear("اختار عقد من الشجرة أو الكروت، أو اضغط «عقد جديد».")
        self.set_mode("view")
        self._mark_tree_selection()
        self._apply_card_selection()

    def _on_tab_changed(self, _index: int) -> None:
        self._mark_tree_selection()
        self._apply_card_selection()

    # -- new / edit / save / delete --------------------------------------------------------

    def _busy(self) -> bool:
        if self.mode in {"new", "edit"}:
            QMessageBox.information(self, "جاري التعديل", "احفظ التعديلات أو ألغِها الأول.")
            return True
        return False

    def new_contract(self) -> None:
        if self._busy() or not self._perm_create:
            return
        form = self.form
        if form.contractor.count() == 0:
            QMessageBox.information(self, "لا يوجد مقاولين", "أضف المقاول الأول من شاشة «المقاولين».")
            return
        if form.company.count() == 0:
            QMessageBox.information(self, "لا توجد شركات", "أضف الشركة والمشروع الأول من شاشة «الشركات والمشاريع».")
            return
        try:
            number = self.service.next_contract_no()
        except Exception:
            number = ""
        if self.tabs.currentIndex() == TAB_TREE:
            company_id, project_id = self._tree_context()
            contractor_id = None
        else:
            contractor_id = self.contractor_picker.currentData()
            company_id = project_id = None
        form.start_new(number, contractor_id, company_id, project_id)
        self.set_mode("new")
        self.tree.clearSelection()
        self._apply_card_selection()
        form.contract_value.setFocus()

    def _status(self) -> Any:
        return (self.current_record or {}).get("status") if self.current_id is not None else None

    def edit_record(self) -> None:
        if (self.current_id is not None and self.mode == "view" and self._perm_edit
                and self.approval.may_edit(self._status())):
            self.set_mode("edit")

    def save_record(self) -> None:
        if self.mode not in {"new", "edit"}:
            return
        record_id = None if self.mode == "new" else self.current_id
        try:
            saved = self.service.save_contract(self.form.data(), record_id, allow_approved=self.approval.is_admin)
        except (ContractError, ApprovalError) as exc:
            QMessageBox.warning(self, "لا يمكن الحفظ", str(exc))
            return
        except Exception as exc:
            self._show_error("فشل حفظ العقد", exc)
            return
        self.mode = "view"
        self.current_id = saved
        self.refresh_views()
        self.load_contract(saved)
        notify_data_changed(self)
        QMessageBox.information(self, "تم الحفظ", self.approval.saved_message(self._status(), "العقد"))

    def cancel_edit(self) -> None:
        self.mode = "view"
        if self.current_id is not None:
            self.load_contract(self.current_id)
        else:
            self._show_empty()

    def delete_record(self) -> None:
        if (self.current_id is None or self.mode != "view" or not self._perm_delete
                or not self.approval.may_delete(self._status())):
            return
        answer = QMessageBox.question(
            self, "تأكيد الحذف", f"هل تريد حذف العقد «{(self.current_record or {}).get('contract_no', '')}»؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.delete_contract(self.current_id, allow_approved=self.approval.is_admin)
        except (ContractError, ApprovalError) as exc:
            QMessageBox.warning(self, "لا يمكن الحذف", str(exc))
            return
        except Exception as exc:
            self._show_error("لا يمكن حذف العقد", exc)
            return
        self._show_empty()
        self.refresh_views()
        notify_data_changed(self)

    # -- اعتماد / إلغاء الاعتماد ------------------------------------------------------------

    def _approval_done(self, message: str) -> None:
        contract_id = self.current_id
        self.refresh_views()
        self.load_contract(contract_id)
        QMessageBox.information(self, "تم", message)

    def approve_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_approve:
            return
        contract_id, number = self.current_id, (self.current_record or {}).get("contract_no", "")
        if self.approval.approve(f"العقد «{number}»",
                                 lambda: self.service.approve(contract_id, self.approval.user_id())):
            self._approval_done("تم اعتماد العقد.")

    def unapprove_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_unapprove:
            return
        contract_id, number = self.current_id, (self.current_record or {}).get("contract_no", "")
        if self.approval.unapprove(f"العقد «{number}»", lambda: self.service.unapprove(contract_id)):
            self._approval_done("تم إلغاء اعتماد العقد، ورجع مسودة.")

    # -- modes ---------------------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        editing = mode in {"new", "edit"}
        for form in self.forms:
            form.set_editing(editing and form is self.form)
        has_record = self.current_id is not None
        status = self._status()
        self.new_button.setEnabled(not editing and self._perm_create)
        self.edit_button.setEnabled(not editing and has_record and self._perm_edit and self.approval.may_edit(status))
        self.delete_button.setEnabled(not editing and has_record and self._perm_delete
                                      and self.approval.may_delete(status))
        self.save_button.setEnabled(editing and self._perm_save)
        self.cancel_button.setEnabled(editing)
        self.approval.update(editing, status, self.edit_button, self.delete_button)
        self.search_text.setEnabled(not editing)
        self.contractor_picker.setEnabled(not editing)
        self.tabs.tabBar().setEnabled(not editing)
        self.mode_badge.setText({"view": "عرض", "new": "جديد", "edit": "تعديل"}.get(mode, mode))

    def _show_error(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, str(exc))
