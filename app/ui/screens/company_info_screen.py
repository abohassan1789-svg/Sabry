"""شاشة بيانات الشركة — النموذج 8 «شريط عرض علوي + 3 كروت» (picked 2026-10-05).

The companies the app prints for. A dark strip on top shows the open company
(logo, name, tax registration number, address) and follows the boxes live
while the user types. Below it, three cards hold the editors:
الاسم والسجل، العنوان، اللوجو.

What the user asked for:

* اسم الشركة، رقم السجل الضريبي، العنوان، اللوجو.
* **More than one company** (2026-10-05). Which one a printout uses is for
  the print phase. One company shows at a time; «بحث عن شركة» (F1) and
  الاول/السابق/التالي/الاخير move between them. Two companies cannot share a
  name.
* The logo is saved **inside the database** (``company_info.logo``), not as a
  path. Picking or removing it is part of the edit: «حفظ» stores it,
  «إلغاء» puts the old one back.
* A «يظهر في الطباعة» box beside the **address only**: it decides whether the
  address prints. The other fields always print.

No مسودة / معتمد: the user didn't ask for it on this screen.
"""

from __future__ import annotations

import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.security.session_context import SESSION
from app.services.company_info_service import (
    ADDRESS_MAX,
    LOGO_FILE_FILTER,
    NAME_MAX,
    TAX_MAX,
    CompanyInfoError,
    CompanyInfoService,
    read_logo_file,
)
from app.ui.common.live_lists import notify_data_changed
from app.ui.dialogs.company_info_list_dialog import CompanyInfoListDialog
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style

PERMISSION_BASE = "contracting.company_info"
HERO = "#0E5A66"
HERO_SOFT = "#CFE3E6"
HERO_LOGO = 130
CARD_LOGO = 150

_EDITOR_QSS = (
    f"QLineEdit, QPlainTextEdit {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:7px; "
    f"padding:6px 10px; font-size:15px; font-weight:800; color:{TEXT}; }}"
    f"QLineEdit:focus, QPlainTextEdit:focus {{ border:2px solid {GREEN_DARK}; }}"
    "QLineEdit:read-only, QPlainTextEdit[readOnly=\"true\"] { background:#F8FAFC; color:#334155; }"
)


def _pixmap(data: bytes | None) -> QPixmap | None:
    if not data:
        return None
    pixmap = QPixmap()
    return pixmap if pixmap.loadFromData(data) else None


class CompanyInfoScreen(QWidget):
    def __init__(self, service: CompanyInfoService | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service or CompanyInfoService()
        self.mode = "view"
        self.rows: list[dict[str, Any]] = []      # every company, for navigation
        self.current_id: Any = None
        self.record: dict[str, Any] | None = None
        self._logo: bytes | None = None
        self._logo_mime: str | None = None

        self._perm_create = SESSION.can(f"{PERMISSION_BASE}.create")
        self._perm_edit = SESSION.can(f"{PERMISSION_BASE}.edit")
        self._perm_save = SESSION.can(f"{PERMISSION_BASE}.save")
        self._perm_delete = SESSION.can(f"{PERMISSION_BASE}.delete")

        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("QWidget { font-family: 'Segoe UI', 'Tahoma', 'Arial'; }")
        self._build_ui()
        QShortcut(QKeySequence(Qt.Key_F1), self, activated=self.open_lookup)
        self.refresh()

    # -- layout ------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_hero())
        cards = QHBoxLayout()
        cards.setSpacing(14)
        cards.addWidget(self._build_name_card(), 1)
        cards.addWidget(self._build_address_card(), 1)
        cards.addWidget(self._build_logo_card(), 1)
        # The cards take the spare height, down to the bottom of the window.
        root.addLayout(cards, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background:{GREEN}; border-radius:6px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)
        icon = QLabel("🏛")
        icon.setFixedSize(54, 54)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background:rgba(255,255,255,0.16); border:1px solid rgba(255,255,255,0.28); "
            "border-radius:7px; font-size:24px; font-weight:900;"
        )
        title = QLabel("بيانات الشركة")
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
        bar.setStyleSheet("QFrame { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:7px; }"
                          "QLabel { border:none; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(7)

        self.new_button = QPushButton("جديد")
        self.edit_button = QPushButton("تعديل")
        self.save_button = QPushButton("حفظ")
        self.delete_button = QPushButton("حذف")
        self.cancel_button = QPushButton("إلغاء")
        self.refresh_button = QPushButton("تحديث")
        self.find_button = QPushButton("بحث عن شركة")
        self.exit_button = QPushButton("خروج")
        for button, icon, bg, hover in (
            (self.new_button, QStyle.SP_FileIcon, "#1A7A3C", "#166534"),
            (self.edit_button, QStyle.SP_FileDialogDetailedView, "#64748B", "#475569"),
            (self.save_button, QStyle.SP_DialogSaveButton, "#2563EB", "#1D4ED8"),
            (self.delete_button, QStyle.SP_TrashIcon, "#DC2626", "#B91C1C"),
            (self.cancel_button, QStyle.SP_DialogCancelButton, "#6B7280", "#4B5563"),
            (self.refresh_button, QStyle.SP_BrowserReload, "#FFFFFF", "#F3F4F6"),
            (self.find_button, QStyle.SP_FileDialogContentsView, "#0EA5E9", "#0284C7"),
            (self.exit_button, QStyle.SP_ArrowBack, "#374151", "#1F2937"),
        ):
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
        self.find_button.setToolTip("F1")

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, caption in (("first", "الاول"), ("prev", "السابق"), ("next", "التالي"), ("last", "الاخير")):
            button = QPushButton(caption)
            button.setFixedHeight(38)
            button.setStyleSheet(
                "QPushButton { background:#F1F5F9; color:#475569; border:1px solid #E2E8F0; "
                "border-radius:6px; font-weight:800; padding:7px 10px; }"
                "QPushButton:hover { background:#E2E8F0; }"
                "QPushButton:disabled { color:#CBD5E1; }"
            )
            button.clicked.connect(lambda _checked=False, k=key: self.navigate(k))
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.position_label = QLabel("")
        self.position_label.setStyleSheet("color:#334155; font-size:13px; font-weight:900;")
        layout.addWidget(self.position_label)
        self.updated_label = QLabel("")
        self.updated_label.setStyleSheet("color:#64748B; font-size:12px; font-weight:700;")
        layout.addWidget(self.updated_label)
        self.mode_badge = QLabel("عرض")
        self.mode_badge.setAlignment(Qt.AlignCenter)
        self.mode_badge.setMinimumWidth(100)
        self.mode_badge.setStyleSheet(
            "background:#ECFDF3;color:#087443;border:1px solid #B7E4C7;border-radius:7px;"
            "padding:8px 12px;font-weight:900;"
        )
        layout.addWidget(self.mode_badge)

        self.new_button.clicked.connect(self.new_record)
        self.edit_button.clicked.connect(self.edit_record)
        self.save_button.clicked.connect(self.save_record)
        self.delete_button.clicked.connect(self.delete_record)
        self.cancel_button.clicked.connect(self.cancel_edit)
        self.refresh_button.clicked.connect(lambda _checked=False: self.refresh())
        self.find_button.clicked.connect(self.open_lookup)
        self.exit_button.clicked.connect(lambda _checked=False: self.window().close())
        return bar

    def _build_hero(self) -> QFrame:
        """The company as it stands: logo, name, tax number, address."""
        hero = QFrame()
        hero.setObjectName("company_hero")
        hero.setStyleSheet(
            f"QFrame#company_hero {{ background:{HERO}; border-radius:14px; }}"
            "QLabel { background:transparent; color:#FFFFFF; border:none; }"
        )
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(28)

        self.hero_logo = QLabel()
        self.hero_logo.setFixedSize(HERO_LOGO + 20, HERO_LOGO + 20)
        self.hero_logo.setAlignment(Qt.AlignCenter)
        self.hero_logo.setStyleSheet(
            "QLabel { background:#FFFFFF; border-radius:22px; color:#94A3B8; font-size:13px; font-weight:800; }"
        )
        layout.addWidget(self.hero_logo, 0, Qt.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(4)
        name_caption = self._hero_caption("اسم الشركة")
        self.hero_name = QLabel("")
        self.hero_name.setWordWrap(True)
        self.hero_name.setStyleSheet("font-size:32px; font-weight:900;")
        text.addWidget(name_caption)
        text.addWidget(self.hero_name)

        details = QHBoxLayout()
        details.setSpacing(40)
        tax_box = QVBoxLayout()
        tax_box.setSpacing(2)
        self.hero_tax = QLabel("")
        self.hero_tax.setStyleSheet("font-size:17px; font-weight:800;")
        tax_box.addWidget(self._hero_caption("رقم السجل الضريبي"))
        tax_box.addWidget(self.hero_tax)
        address_box = QVBoxLayout()
        address_box.setSpacing(2)
        self.hero_address_caption = self._hero_caption("العنوان")
        self.hero_address = QLabel("")
        self.hero_address.setWordWrap(True)
        self.hero_address.setStyleSheet("font-size:17px; font-weight:800;")
        address_box.addWidget(self.hero_address_caption)
        address_box.addWidget(self.hero_address)
        details.addLayout(tax_box, 0)
        details.addLayout(address_box, 1)
        text.addSpacing(6)
        text.addLayout(details)
        for label in (name_caption, self.hero_name, self.hero_tax, self.hero_address_caption, self.hero_address):
            # Pinned right: a line of digits alone has no Arabic letter to set its direction.
            label.setAlignment(Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)
        layout.addLayout(text, 1)
        return hero

    @staticmethod
    def _hero_caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color:{HERO_SOFT}; font-size:13px; font-weight:800;")
        return label

    def _card(self, title: str, icon: str) -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
        """A white card: (frame, body layout, title row)."""
        card = QFrame()
        card.setObjectName("company_card")
        card.setStyleSheet(
            "QFrame#company_card { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:12px; }"
            "QLabel { background:transparent; border:none; }"
        )
        body = QVBoxLayout(card)
        body.setContentsMargins(22, 18, 22, 20)
        body.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        badge = QLabel(icon)
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"QLabel {{ background:#E4EFF0; color:{HERO}; border-radius:9px; font-size:17px; }}")
        caption = QLabel(title)
        caption.setStyleSheet(f"font-size:16px; font-weight:900; color:{TEXT};")
        head.addWidget(badge)
        head.addWidget(caption)
        head.addStretch(1)
        body.addLayout(head)
        return card, body, head

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size:13.5px; font-weight:800; color:#334155;")
        return label

    def _build_name_card(self) -> QFrame:
        card, body, _head = self._card("الاسم والسجل", "🏢")
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(NAME_MAX)
        self.tax_edit = QLineEdit()
        self.tax_edit.setMaxLength(TAX_MAX)
        for editor in (self.name_edit, self.tax_edit):
            editor.setFixedHeight(42)
            editor.setStyleSheet(_EDITOR_QSS)
            editor.textChanged.connect(lambda _t: self._update_hero())
        body.addWidget(self._field_label("اسم الشركة"))
        body.addWidget(self.name_edit)
        body.addSpacing(4)
        body.addWidget(self._field_label("رقم السجل الضريبي"))
        body.addWidget(self.tax_edit)
        body.addStretch(1)
        return card

    def _build_address_card(self) -> QFrame:
        card, body, head = self._card("العنوان", "📍")
        self.show_address_check = QCheckBox("يظهر في الطباعة")
        self.show_address_check.setChecked(True)
        self.show_address_check.setStyleSheet(
            f"QCheckBox {{ color:{HERO}; font-size:13.5px; font-weight:900; spacing:8px; }}"
            "QCheckBox::indicator { width:18px; height:18px; }"
        )
        self.show_address_check.toggled.connect(lambda _on: self._update_hero())
        head.addWidget(self.show_address_check)
        self.address_edit = QPlainTextEdit()
        self.address_edit.setFixedHeight(120)
        self.address_edit.setStyleSheet(_EDITOR_QSS)
        self.address_edit.textChanged.connect(self._update_hero)
        body.addWidget(self.address_edit)
        hint = QLabel("لو شلت العلامة، العنوان مش هيظهر في رأس المطبوعات.")
        hint.setStyleSheet("color:#64748B; font-size:12px; font-weight:700;")
        body.addWidget(hint)
        body.addStretch(1)
        return card

    def _build_logo_card(self) -> QFrame:
        card, body, _head = self._card("اللوجو", "🖼")
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addStretch(1)
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(CARD_LOGO, CARD_LOGO)
        self.logo_preview.setAlignment(Qt.AlignCenter)
        self.logo_preview.setStyleSheet(
            "QLabel { background:#FAF9F6; border:2px dashed #C9C6BC; border-radius:12px; "
            "color:#94A3B8; font-weight:800; }"
        )
        row.addWidget(self.logo_preview, 0)
        buttons = QVBoxLayout()
        buttons.setSpacing(8)
        self.choose_logo_button = QPushButton("اختيار صورة…")
        self.choose_logo_button.setStyleSheet(_button_style("#0E7490", "#155E75"))
        self.remove_logo_button = QPushButton("إزالة")
        self.remove_logo_button.setStyleSheet(_button_style("#DC2626", "#B91C1C"))
        for button in (self.choose_logo_button, self.remove_logo_button):
            button.setFixedSize(160, 38)
            buttons.addWidget(button)
        buttons.addStretch(1)
        row.addLayout(buttons, 0)
        row.addStretch(1)
        body.addLayout(row)
        hint = QLabel("الصورة بتتحفظ جوه قاعدة البيانات — PNG أو JPG لحد 5 ميجا")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748B; font-size:12px; font-weight:700;")
        body.addWidget(hint)
        body.addStretch(1)
        self.choose_logo_button.clicked.connect(self.choose_logo)
        self.remove_logo_button.clicked.connect(self.remove_logo)
        return card

    # -- data --------------------------------------------------------------

    def refresh(self, open_id: Any = None) -> None:
        """Reload the company list; show *open_id*, else the open one, else the first."""
        try:
            self.rows = self.service.list_rows()
        except Exception as exc:
            self.rows = []
            self._show_error("تعذّر تحميل الشركات", exc)
        ids = [row["company_info_id"] for row in self.rows]
        for wanted in (open_id, self.current_id):
            if wanted is not None and wanted in ids:
                self.open_company(wanted)
                return
        if ids:
            self.open_company(ids[0])
        else:
            self._show_empty()

    def reload_lists(self) -> None:
        """Another screen or PC saved: show the latest, never mid-edit."""
        if self.mode in {"new", "edit"}:
            return
        self.refresh()

    def open_company(self, company_id: Any) -> None:
        try:
            record = self.service.get(company_id)
        except Exception as exc:
            self._show_error("تعذّر تحميل بيانات الشركة", exc)
            return
        if not record:
            return
        self.current_id = company_id
        self.record = record
        self._fill(record)
        self.set_mode("view")

    def _show_empty(self) -> None:
        self.current_id = None
        self.record = None
        self._fill({})
        self.set_mode("view")

    def _fill(self, record: dict[str, Any]) -> None:
        self.name_edit.setText(str(record.get("company_name") or ""))
        self.tax_edit.setText(str(record.get("tax_registration_no") or ""))
        self.address_edit.setPlainText(str(record.get("address") or ""))
        show = record.get("show_address_in_print")
        self.show_address_check.setChecked(True if show is None else bool(show))
        self._logo = record.get("logo") or None
        self._logo_mime = record.get("logo_mime") if self._logo else None
        updated = record.get("updated_at")
        if isinstance(updated, datetime.datetime):
            self.updated_label.setText(f"آخر تعديل: {updated.astimezone():%Y-%m-%d %H:%M}")
        else:
            self.updated_label.setText("")
        self._render_logo()
        self._update_hero()

    def _render_logo(self) -> None:
        pixmap = _pixmap(self._logo)
        for label, size, empty in ((self.logo_preview, CARD_LOGO - 16, "لا يوجد لوجو"),
                                   (self.hero_logo, HERO_LOGO, "بدون لوجو")):
            if pixmap is None:
                label.setPixmap(QPixmap())
                label.setText(empty if not self._logo else "تعذّر عرض الصورة")
            else:
                label.setText("")
                label.setPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _update_hero(self) -> None:
        name = self.name_edit.text().strip()
        if name:
            self.hero_name.setText(name)
        elif self.mode == "new":
            self.hero_name.setText("شركة جديدة")
        else:
            self.hero_name.setText("لسه مفيش شركات — اضغط «جديد»")
        self.hero_tax.setText(self.tax_edit.text().strip() or "—")
        self.hero_address.setText(self.address_edit.toPlainText().strip() or "—")
        hidden = "" if self.show_address_check.isChecked() else " (مش هيظهر في الطباعة)"
        self.hero_address_caption.setText(f"العنوان{hidden}")

    # -- the logo ----------------------------------------------------------

    def choose_logo(self) -> None:
        if self.mode not in {"new", "edit"}:
            return
        path, _ = QFileDialog.getOpenFileName(self, "اختيار لوجو الشركة", "", LOGO_FILE_FILTER)
        if not path:
            return
        try:
            raw, mime = read_logo_file(path)
        except CompanyInfoError as exc:
            QMessageBox.warning(self, "لا يمكن استخدام الصورة", str(exc))
            return
        if _pixmap(raw) is None:
            QMessageBox.warning(self, "صورة غير صالحة", "تعذّر قراءة الصورة المختارة.")
            return
        self._logo, self._logo_mime = raw, mime
        self._render_logo()
        self._update_logo_buttons()

    def remove_logo(self) -> None:
        if self.mode not in {"new", "edit"} or not self._logo:
            return
        self._logo, self._logo_mime = None, None
        self._render_logo()
        self._update_logo_buttons()

    def _update_logo_buttons(self) -> None:
        editing = self.mode in {"new", "edit"}
        self.choose_logo_button.setEnabled(editing)
        self.remove_logo_button.setEnabled(editing and bool(self._logo))

    # -- moving between companies --------------------------------------------

    def _index(self) -> int:
        for index, row in enumerate(self.rows):
            if row["company_info_id"] == self.current_id:
                return index
        return -1

    def navigate(self, where: str) -> None:
        if self.mode != "view" or not self.rows:
            return
        current = max(0, self._index())
        target = {
            "first": 0,
            "last": len(self.rows) - 1,
            "prev": max(0, current - 1),
            "next": min(len(self.rows) - 1, current + 1),
        }[where]
        if target != self._index():
            self.open_company(self.rows[target]["company_info_id"])

    def open_lookup(self) -> None:
        """F1: pick a company from the list."""
        if self.mode != "view":
            QMessageBox.information(self, "جاري التعديل",
                                    "احفظ التعديلات أو ألغِها قبل الانتقال لشركة تانية.")
            return
        if not self.rows:
            QMessageBox.information(self, "بحث عن شركة", "لسه مفيش شركات مسجّلة.")
            return
        dialog = CompanyInfoListDialog(self.rows, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected:
            self.open_company(dialog.selected["company_info_id"])

    # -- actions -----------------------------------------------------------

    def new_record(self) -> None:
        if self.mode != "view" or not self._perm_create:
            return
        self.set_mode("new")
        self._fill({})
        self.name_edit.setFocus()

    def edit_record(self) -> None:
        if self.mode == "view" and self.current_id is not None and self._perm_edit:
            self.set_mode("edit")
            self.name_edit.setFocus()

    def save_record(self) -> None:
        if self.mode not in {"new", "edit"} or not self._perm_save:
            return
        address = self.address_edit.toPlainText()
        if len(address.strip()) > ADDRESS_MAX:
            QMessageBox.warning(self, "لا يمكن الحفظ", f"العنوان أطول من {ADDRESS_MAX} حرف.")
            return
        data = {
            "company_name": self.name_edit.text(),
            "tax_registration_no": self.tax_edit.text(),
            "address": address,
            "show_address_in_print": self.show_address_check.isChecked(),
        }
        try:
            saved_id = self.service.save(data, self._logo, self._logo_mime,
                                         None if self.mode == "new" else self.current_id,
                                         (SESSION.user or {}).get("id"))
        except CompanyInfoError as exc:
            QMessageBox.warning(self, "لا يمكن الحفظ", str(exc))
            return
        except Exception as exc:
            self._show_error("فشل حفظ بيانات الشركة", exc)
            return
        self.mode = "view"
        self.refresh(saved_id)
        notify_data_changed(self)
        QMessageBox.information(self, "تم الحفظ", "تم حفظ بيانات الشركة.")

    def delete_record(self) -> None:
        if self.mode != "view" or self.current_id is None or not self._perm_delete:
            return
        name = self.name_edit.text().strip()
        answer = QMessageBox.question(
            self, "تأكيد الحذف", f"هل تريد حذف الشركة «{name}»؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        index = self._index()
        try:
            self.service.delete(self.current_id)
        except Exception as exc:
            self._show_error("لا يمكن حذف الشركة", exc)
            return
        # Open the company that takes its place in the list.
        left = [row for row in self.rows if row["company_info_id"] != self.current_id]
        neighbour = left[min(index, len(left) - 1)]["company_info_id"] if left else None
        self.current_id = None
        self.refresh(neighbour)
        notify_data_changed(self)

    def cancel_edit(self) -> None:
        if self.mode not in {"new", "edit"}:
            return
        self.mode = "view"
        if self.current_id is not None:
            self.open_company(self.current_id)
        else:
            self._show_empty()

    # -- modes -------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        editing = mode in {"new", "edit"}
        has_record = self.current_id is not None
        for editor in (self.name_edit, self.tax_edit, self.address_edit):
            editor.setReadOnly(not editing)
        self.address_edit.style().unpolish(self.address_edit)
        self.address_edit.style().polish(self.address_edit)
        self.show_address_check.setEnabled(editing)
        self.new_button.setEnabled(not editing and self._perm_create)
        self.edit_button.setEnabled(not editing and has_record and self._perm_edit)
        self.delete_button.setEnabled(not editing and has_record and self._perm_delete)
        self.save_button.setEnabled(editing and self._perm_save)
        self.cancel_button.setEnabled(editing)
        self.refresh_button.setEnabled(not editing)
        self.find_button.setEnabled(not editing and bool(self.rows))
        index = self._index()
        last = len(self.rows) - 1
        for key, enabled in (("first", index > 0), ("prev", index > 0),
                             ("next", 0 <= index < last), ("last", 0 <= index < last)):
            self.nav_buttons[key].setEnabled(not editing and enabled)
        if mode == "new":
            self.position_label.setText("شركة جديدة")
        elif index >= 0:
            self.position_label.setText(f"شركة {index + 1} من {len(self.rows)}")
        else:
            self.position_label.setText("")
        self._update_logo_buttons()
        self._update_hero()
        self.mode_badge.setText({"view": "عرض", "new": "جديد", "edit": "تعديل"}.get(mode, mode))

    def _show_error(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, str(exc))
