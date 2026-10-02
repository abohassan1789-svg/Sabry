"""شاشة المقاولين — النموذج 4 «بطاقة هوية المقاول» (picked 2026-09-24).

Layout: an identity banner on top (code, type, name, registration/phone/address
and the current balance in large figures), then three cards side by side —
البيانات الأساسية، الاتصال والحساب، الضرائب والتأمينات والخصومات. There is no
list panel: the record list sits behind «بحث عن مقاول» (and F1), with
الاول/السابق/التالي/الاخير to walk the cards, the same as شاشة الكسّارات.

What the user asked for, and where it lives:

* **كود المقاول** is «A-H/CD-1001», «A-H/CD-1002», ... «جديد» fills in the next
  one, and it stays an ordinary editable box — the user may change it. Only
  uniqueness is enforced (a clear message here, the UNIQUE index underneath).
* **نوع المقاول** is one of مقاول / مورد / استشاري / دعاية وإعلان.
* **الضرائب والتأمينات والخصومات** are amounts, not percentages, plus the new
  **الخصومات الأخرى**.
* **Count cards** under the form: إجمالي السجلات، الموردين، المقاولين،
  الاستشاريين، الدعاية والإعلان. Clicking one lists who is behind the number;
  picking a row opens that contractor here.

* **مسودة / معتمد** (2026-10-02): «حفظ» keeps a new contractor as a draft;
  «اعتماد» / «إلغاء الاعتماد» (``ApprovalControls``) move it. Only approved
  contractors reach the other screens and the reports. An approved contractor
  is still edited; only an admin deletes one.

Everything below is presentation. The CRUD path is the shared one
(``ReviewDataService`` + ``TABLE_SPECS['contractors']``); the next code and the
approval come from :class:`ContractorService`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.contracting_approval import DRAFT
from app.services.contractor_service import ContractorService
from app.services.review_data_service import CONTRACTOR_TYPES, TABLE_SPECS, ReviewDataService
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.dialogs.contractor_list_dialog import ContractorListDialog
from app.ui.screens.approval_controls import ApprovalControls
from app.ui.screens.base_crud_screen import BaseCrudScreen

DEFAULT_TYPE = CONTRACTOR_TYPES[0]  # مقاول

# The three cards, in reading order (right to left).
CARD_GROUPS = ("البيانات الأساسية", "الاتصال والحساب", "الضرائب والتأمينات والخصومات")

DEDUCTION_FIELDS = (
    "vat_amount",
    "withholding_tax_amount",
    "social_insurance_amount",
    "works_insurance_amount",
    "other_deductions_amount",
)

# The count cards: (نوع filter — "" means all, caption, list title, accent).
STAT_CARDS = (
    ("", "إجمالي السجلات", "كل السجلات", "#334155"),
    ("مورد", "الموردين", "الموردين", "#0369A1"),
    ("مقاول", "المقاولين", "المقاولين", GREEN),
    ("استشاري", "الاستشاريين", "الاستشاريين", "#7C3AED"),
    ("دعاية وإعلان", "الدعاية والإعلان", "الدعاية والإعلان", "#C2410C"),
)

# Money boxes that are NOT NULL DEFAULT 0, so a blank one means zero.
_ZERO_IF_BLANK = ("current_balance", *DEDUCTION_FIELDS)

# The banner shows these, and follows them live while the user types.
_BANNER_FIELDS = ("contractor_code", "contractor_name", "contractor_type",
                  "registration_no", "phone", "address", "current_balance")


def _to_decimal(value: Any) -> Decimal:
    text = str(value if value is not None else "").replace(",", "").strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _money(value: Any) -> str:
    """Thousands-separated, two decimals; a negative shows as ``1,234.00-``.

    Trailing sign, as on شاشة الكسّارات: in an RTL layout a leading minus lands
    on the wrong end of the number.
    """
    amount = _to_decimal(value)
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


class ContractorsScreen(BaseCrudScreen):
    SPEC_KEY = "contractors"
    SEARCH_PLACEHOLDER = "ابحث بالكود أو الاسم أو رقم التسجيل أو التلفون"
    FORM_COLUMNS = 1

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        # Set before super().__init__: the base constructor builds the UI, which
        # calls back into the widgets these hold.
        self._backend_service: ContractorService | None = None
        self._banner: dict[str, QLabel] = {}
        self._stat_values: dict[str, QLabel] = {}
        self.approval: ApprovalControls | None = None  # built with the toolbar
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)
        # The status badge sits beside the mode badge, at the toolbar's far end.
        bar = self.mode_badge.parentWidget().layout()
        bar.insertWidget(bar.indexOf(self.mode_badge), self.approval.badge)
        self._update_banner()

    # -- editors -----------------------------------------------------------

    def _make_editor(self, field: Any):
        """نوع المقاول never offers a blank choice; money boxes read right-aligned."""
        editor = super()._make_editor(field)
        if field.name == "contractor_type":
            blank = editor.findText("")
            if blank >= 0:
                editor.removeItem(blank)
            editor.setCurrentIndex(max(0, editor.findText(DEFAULT_TYPE)))
            editor.currentIndexChanged.connect(lambda _i: self._update_banner())
        elif isinstance(editor, QLineEdit):
            if field.name in _BANNER_FIELDS:
                editor.textChanged.connect(lambda _t: self._update_banner())
        return editor

    # -- toolbar -----------------------------------------------------------

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        """«اعتماد» / «إلغاء الاعتماد», then the search button and the record navigation."""
        # BaseCrudScreen checks ``crm.<key>.<action>``.
        self.approval = ApprovalControls(self, f"crm.{self.SPEC_KEY}", locked_when_approved=False)
        self.approval.add_buttons(layout)
        self.approval.approve_button.clicked.connect(self.approve_record)
        self.approval.unapprove_button.clicked.connect(self.unapprove_record)

        self.find_button = QPushButton("بحث عن مقاول")
        self.find_button.setFixedHeight(38)
        self.find_button.setStyleSheet(_button_style("#0EA5E9", "#0284C7"))
        self.find_button.clicked.connect(self.open_lookup)
        layout.addWidget(self.find_button)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, caption in (
            ("first", "الاول"),
            ("prev", "السابق"),
            ("next", "التالي"),
            ("last", "الاخير"),
        ):
            button = QPushButton(caption)
            button.setFixedHeight(38)
            button.setStyleSheet(
                "QPushButton { background:#F1F5F9; color:#475569; border:1px solid #E2E8F0; "
                "border-radius:6px; font-weight:800; padding:7px 10px; }"
                "QPushButton:hover { background:#E2E8F0; }"
                "QPushButton:disabled { color:#CBD5E1; }"
            )
            button.clicked.connect(lambda _checked=False, k=key: self._navigate(k))
            self.nav_buttons[key] = button
            layout.addWidget(button)

    # -- layout ------------------------------------------------------------

    def _build_content(self):
        """Banner on top, the three cards below. No list panel.

        The list panel is still **built** and then hidden: the base class drives
        selection, navigation and the record count through ``self.table`` and
        ``self.search_text``. ``summary_label`` is likewise a live but hidden
        widget, because the base class writes to it on every load.
        """
        content = QVBoxLayout()
        content.setSpacing(10)
        content.addWidget(self._build_banner(), 0)

        by_group: dict[str, list[Any]] = {}
        for field in self.spec.fields:
            by_group.setdefault(field.group, []).append(field)

        row = QHBoxLayout()
        row.setSpacing(10)
        for group in CARD_GROUPS:
            row.addWidget(self._build_card(group, by_group.get(group, [])), 1)
        content.addLayout(row, 0)
        # The spare height goes ABOVE the count cards, pinning them to the bottom
        # of the screen (user request, 2026-09-24).
        content.addStretch(1)
        content.addLayout(self._build_stats_row(), 0)

        self.summary_label = QLabel("سجل جديد")
        self.summary_label.hide()
        content.addWidget(self.summary_label)

        self.list_panel = self._build_list_panel()
        self.list_panel.hide()
        content.addWidget(self.list_panel, 0)
        return content

    def _build_banner(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("contractor_banner")
        panel.setStyleSheet(
            "QFrame#contractor_banner { background:#FFFFFF; border:1px solid #E5EAF0; "
            "border-radius:9px; }"
            "QLabel { background:transparent; border:none; }"
        )
        outer = QHBoxLayout(panel)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(18)

        avatar = QLabel("م")
        avatar.setFixedSize(72, 72)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"QLabel {{ background:{GREEN}; color:#FFFFFF; border-radius:36px; "
            "font-size:28px; font-weight:900; }"
        )
        self._banner["avatar"] = avatar
        outer.addWidget(avatar, 0)

        middle = QVBoxLayout()
        middle.setSpacing(4)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        code = QLabel("")
        code.setLayoutDirection(Qt.LeftToRight)
        code.setStyleSheet(
            f"QLabel {{ background:#EAFBF0; color:{GREEN_DARK}; border:1px solid #BBF7D0; "
            "border-radius:12px; padding:3px 12px; font-size:13px; font-weight:900; }"
        )
        kind = QLabel("")
        kind.setStyleSheet(
            "QLabel { background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE; "
            "border-radius:12px; padding:3px 12px; font-size:13px; font-weight:900; }"
        )
        chips.addWidget(code)
        chips.addWidget(kind)
        chips.addStretch(1)
        name = QLabel("")
        name.setStyleSheet(f"font-size:24px; font-weight:900; color:{TEXT};")
        details = QLabel("")
        details.setStyleSheet("font-size:13px; font-weight:700; color:#475569;")
        # Pinned to the right edge: a line holding only digits (a phone number)
        # has no Arabic letter to set its direction, and Qt would lay it out
        # left-to-right on the far side of the banner.
        for label in (name, details):
            label.setAlignment(Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)
        middle.addLayout(chips)
        middle.addWidget(name)
        middle.addWidget(details)
        outer.addLayout(middle, 1)

        balance_box = QVBoxLayout()
        balance_box.setSpacing(0)
        caption = QLabel("الرصيد الجاري")
        caption.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        caption.setStyleSheet("font-size:13px; font-weight:800; color:#475569;")
        balance = QLabel("0.00")
        balance.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        balance.setLayoutDirection(Qt.LeftToRight)
        balance.setStyleSheet(f"font-size:32px; font-weight:900; color:{GREEN};")
        balance_box.addWidget(caption)
        balance_box.addWidget(balance)
        outer.addLayout(balance_box, 0)

        self._banner.update(code=code, kind=kind, name=name, details=details, balance=balance)
        return panel

    def _build_card(self, title: str, fields: list[Any]) -> QWidget:
        """The shared field group, with its title on the card's right edge.

        The base style puts the title at «top right», which Qt mirrors to the
        LEFT under this screen's right-to-left layout; «top left» mirrors back
        to the right, where an Arabic title starts.
        """
        card = self._build_field_group(title, fields)
        card.setStyleSheet(
            card.styleSheet().replace("subcontrol-position:top right; right:16px;",
                                      "subcontrol-position:top left; left:16px;")
        )
        return card

    # -- live banner -------------------------------------------------------------

    def _text(self, name: str) -> str:
        editor = self.inputs.get(name)
        if editor is None:
            return ""
        return str(self._editor_value(editor) or "").strip()

    def _update_banner(self) -> None:
        if not self._banner:
            return
        name = self._text("contractor_name")
        self._banner["name"].setText(name or "مقاول جديد")
        self._banner["avatar"].setText(name[:1] if name else "م")
        self._banner["code"].setText(self._text("contractor_code") or "—")
        self._banner["kind"].setText(self._text("contractor_type") or DEFAULT_TYPE)
        parts = []
        if self._text("registration_no"):
            parts.append(f"رقم التسجيل {self._text('registration_no')}")
        if self._text("phone"):
            parts.append(self._text("phone"))
        if self._text("address"):
            parts.append(self._text("address"))
        self._banner["details"].setText(" · ".join(parts))
        self._banner["balance"].setText(_money(self._text("current_balance")))

    # -- count cards -----------------------------------------------------------

    def _build_stats_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        for contractor_type, caption, title, accent in STAT_CARDS:
            row.addWidget(self._build_stat_card(contractor_type, caption, title, accent), 1)
        return row

    def _build_stat_card(self, contractor_type: str, caption: str, title: str, accent: str) -> QPushButton:
        """A clickable card: the count in large figures over its caption."""
        card = QPushButton()
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(92)
        card.setToolTip(f"اضغط لعرض {title}")
        card.setStyleSheet(
            "QPushButton { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:9px; }"
            f"QPushButton:hover {{ background:#F8FAFC; border-color:{accent}; }}"
            "QPushButton:pressed { background:#F1F5F9; }"
        )
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 10, 16, 10)
        box.setSpacing(2)
        value = QLabel("0")
        value.setStyleSheet(f"font-size:28px; font-weight:900; color:{accent}; background:transparent;")
        label = QLabel(caption)
        label.setStyleSheet("font-size:14px; font-weight:800; color:#475569; background:transparent;")
        for widget in (value, label):
            widget.setAlignment(Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)
            # Let the click reach the button underneath.
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            box.addWidget(widget)
        card.clicked.connect(lambda _checked=False: self._open_type_list(contractor_type, title))
        self._stat_values[contractor_type] = value
        return card

    def _refresh_counts(self) -> None:
        """Recount the cards. A failure here must never block the form."""
        if not self._stat_values:
            return
        try:
            counts = self._backend().type_counts()
        except Exception:
            counts = {}
        for contractor_type, value in self._stat_values.items():
            value.setText(f"{counts.get(contractor_type, 0):,}")

    def _open_type_list(self, contractor_type: str, title: str) -> None:
        """List who is behind a card; picking a row opens that contractor."""
        if self.mode in {"new", "edit"}:
            QMessageBox.information(
                self,
                "جاري التعديل",
                "احفظ التعديلات أو ألغِها قبل الانتقال إلى مقاول تاني.",
            )
            return
        try:
            rows = self._backend().list_rows(contractor_type or None)
        except Exception as exc:
            self._show_error("تعذّر تحميل القائمة", exc)
            return
        if not rows:
            QMessageBox.information(self, title, f"لا يوجد {title} مسجّلين.")
            return
        dialog = ContractorListDialog(f"{title} ({len(rows)})", rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        self._load_contractor(dialog.selected.get("contractor_id"))

    def _load_contractor(self, contractor_id: Any) -> None:
        """Show one contractor, keeping the hidden list row in step for navigation."""
        if contractor_id is None:
            return
        try:
            record = self.service.get_record(self.spec, contractor_id)
        except Exception as exc:
            self._show_error("فشل تحميل السجل", exc)
            return
        if not record:
            return
        self.current_id = contractor_id
        self._fill_form(record)
        self.set_mode("view")
        self._select_row_by_id(contractor_id)

    # -- data --------------------------------------------------------------

    def _backend(self) -> ContractorService:
        if self._backend_service is None:
            self._backend_service = ContractorService()
        return self._backend_service

    # -- the search dialog and record navigation ---------------------------------

    def open_lookup(self) -> None:
        if self.mode in {"new", "edit"}:
            QMessageBox.information(
                self,
                "جاري التعديل",
                "احفظ التعديلات أو ألغِها قبل الانتقال إلى مقاول تاني.",
            )
            return
        super().open_lookup()
        self._update_nav_state()

    def _navigate(self, where: str) -> None:
        """Move to the first/previous/next/last card in the hidden list."""
        if self.mode in {"new", "edit"}:
            return
        total = self.table.rowCount()
        if total == 0:
            return
        current = max(0, self.table.currentRow())
        target = {
            "first": 0,
            "last": total - 1,
            "prev": max(0, current - 1),
            "next": min(total - 1, current + 1),
        }[where]
        if target != current:
            # setCurrentCell, not selectRow: Qt ignores selectRow on a view whose
            # parent is hidden. Selection change fires load_selected on its own.
            self.table.setCurrentCell(target, 0)
        self._update_nav_state()

    def _update_nav_state(self) -> None:
        if not hasattr(self, "nav_buttons") or not hasattr(self, "table"):
            return
        browsing = self.mode not in {"new", "edit"}
        total = self.table.rowCount()
        current = self.table.currentRow()
        self.nav_buttons["first"].setEnabled(browsing and current > 0)
        self.nav_buttons["prev"].setEnabled(browsing and current > 0)
        self.nav_buttons["next"].setEnabled(browsing and 0 <= current < total - 1)
        self.nav_buttons["last"].setEnabled(browsing and 0 <= current < total - 1)
        if hasattr(self, "find_button"):
            self.find_button.setEnabled(browsing)

    # -- hooks fired by BaseCrudScreen ------------------------------------------

    def set_mode(self, mode: str) -> None:
        super().set_mode(mode)
        self._update_approval()
        self._update_nav_state()

    # -- مسودة / معتمد ---------------------------------------------------------------

    def _status(self) -> Any:
        """The open contractor's status, read fresh (``get_record`` returns the form fields only)."""
        if self.current_id is None or self.mode == "new":
            return None
        try:
            return self._backend().status(self.current_id)
        except Exception:
            return None

    def _update_approval(self) -> None:
        if self.approval is None or not hasattr(self, "delete_button"):
            return
        editing = self.mode in {"new", "edit"}
        status = self._status()
        if not self.approval.may_delete(status):
            self.delete_button.setEnabled(False)
        self.approval.update(editing, status, None, self.delete_button)

    def _contractor_text(self) -> str:
        return f"المقاول «{self._text('contractor_name')}»"

    def approve_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_approve:
            return
        contractor_id = self.current_id
        if self.approval.approve(self._contractor_text(),
                                 lambda: self._backend().approve(contractor_id, self.approval.user_id())):
            self.set_mode("view")
            QMessageBox.information(self, "تم", "تم اعتماد المقاول.")

    def unapprove_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_unapprove:
            return
        contractor_id = self.current_id
        if self.approval.unapprove(self._contractor_text(), lambda: self._backend().unapprove(contractor_id)):
            self.set_mode("view")
            QMessageBox.information(self, "تم", "تم إلغاء اعتماد المقاول، ورجع مسودة.")

    def delete_record(self) -> None:
        """An approved contractor is deleted by an admin only."""
        if self.approval is not None and not self.approval.may_delete(self._status()):
            QMessageBox.information(self, "لا يمكن الحذف",
                                    "المقاول ده معتمد. الغي الاعتماد الأول عشان تحذفه.")
            return
        super().delete_record()

    def _saved_message(self) -> str:
        if self._status() == DRAFT:
            return ApprovalControls.saved_message(DRAFT, "المقاول")
        return super()._saved_message()

    def refresh_table(self) -> None:
        super().refresh_table()
        # The base class opens on row 0 with selectRow, a no-op on this hidden list.
        if self.current_id is None and self.table.rowCount():
            self.table.setCurrentCell(0, 0)
        self._update_nav_state()
        # Runs after every save/delete too, since both end in refresh_table.
        self._refresh_counts()

    def _select_row_by_id(self, record_id: Any) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.data(Qt.UserRole)) == str(record_id):
                self.table.setCurrentCell(row, 0)
                return

    def _fill_form(self, record: dict[str, Any]) -> None:
        super()._fill_form(record)
        # get_record returns only the spec's columns, so there is no
        # contractor_id in *record*; name the contractor instead.
        name = str(record.get("contractor_name") or "").strip()
        if name:
            self.summary_label.setText(f"السجل الحالي: {name}")
        self._update_banner()

    def _clear_form(self) -> None:
        super()._clear_form()
        self._set_editor_value(self.inputs.get("contractor_type"), DEFAULT_TYPE)
        self._update_banner()

    def new_record(self) -> None:
        """Start a new contractor with the next code already filled in."""
        super().new_record()
        try:
            self._set_editor_value(self.inputs["contractor_code"], self._backend().next_code())
        except Exception:
            # A suggestion only — never block creating a record over it.
            pass

    def save_record(self) -> None:
        """Zero the blank money boxes, trim the code and refuse a duplicate code.

        The money columns are NOT NULL DEFAULT 0: blank here plainly means zero.
        The UNIQUE index would reject a duplicate code anyway, but as a raw
        database error; this names the clash instead.
        """
        for name in _ZERO_IF_BLANK:
            editor = self.inputs.get(name)
            if editor is not None and not str(self._editor_value(editor) or "").strip():
                self._set_editor_value(editor, 0)
        code_editor = self.inputs.get("contractor_code")
        code = str(self._editor_value(code_editor) or "").strip() if code_editor else ""
        if code_editor is not None:
            self._set_editor_value(code_editor, code)
        if code:
            try:
                taken = self._backend().code_taken(
                    code, None if self.mode == "new" else self.current_id
                )
            except Exception:
                taken = False
            if taken:
                QMessageBox.warning(
                    self,
                    "كود مكرر",
                    f"الكود «{code}» مستخدم لمقاول تاني. غيّر الكود قبل الحفظ.",
                )
                return
        super().save_record()
