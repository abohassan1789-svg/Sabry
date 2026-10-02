"""شاشة الشركات والمشاريع — النموذج 9 «فروع الشركات + درج التفاصيل» (2026-09-25).

A company owns many projects. The screen draws that tree as branches: each
company is a green header with its projects hanging off a vertical line under
it, three companies per row. Clicking a company or a project opens it in the
details drawer on the left, where it is edited.

Codes: «A-H/CO-1001» for a company, and a project starts with its company's
code: «A-H/CO-1001/PR-01». «شركة جديدة» / «مشروع جديد» fill in the next one;
both stay editable, and a duplicate is refused with a message.

This is two tables (``client_companies`` / ``company_projects``), so it is its
own screen rather than a ``BaseCrudScreen``; the header, toolbar and field
styles copy that base so it looks like every other screen.

مسودة / معتمد (2026-10-02): «حفظ» keeps a company or project as a draft, and
«اعتماد» / «إلغاء الاعتماد» (``ApprovalControls``) act on the one in the drawer.
Drafts are marked on the branches; only approved ones reach the other screens.
An approved company or project is still edited; only an admin deletes one.
"""

from __future__ import annotations

import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.security.session_context import SESSION
from app.services import contracting_approval as approval
from app.services.company_project_service import CompanyProjectError, CompanyProjectService
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.screens.approval_controls import ApprovalControls, status_chip
from app.ui.common.live_lists import notify_data_changed

PERMISSION_BASE = "contracting.company_projects"
BLUE = "#0369A1"
BRANCH_LINE = "#94A3B8"
COLUMNS = 3

_EDITOR_QSS = (
    f"QLineEdit {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:7px; "
    f"padding:6px 10px; font-size:14px; font-weight:900; color:{TEXT}; }}"
    f"QLineEdit:focus {{ border:2px solid {GREEN_DARK}; }}"
    "QLineEdit:read-only { background:#F8FAFC; color:#64748B; }"
)
_COMBO_QSS = (
    f"QComboBox {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:7px; "
    f"padding:6px 10px; font-size:14px; font-weight:900; color:{TEXT}; }}"
    "QComboBox:disabled { background:#F8FAFC; color:#64748B; }"
)


def _short_project_code(code: str) -> str:
    """«A-H/CO-1001/PR-02» -> «PR-02»: the company part is already the branch."""
    text = str(code or "")
    return text.rsplit("/", 1)[-1] if "/" in text else text


class CompanyProjectsScreen(QWidget):
    def __init__(self, service: CompanyProjectService | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service or CompanyProjectService()
        self.kind: str | None = None          # "company" | "project" | None
        self.current_id: Any = None
        self.current_record: dict[str, Any] | None = None
        self.mode = "view"
        self._suggested_code = ""
        self._buttons: dict[tuple[str, Any], QPushButton] = {}
        self._tree: list[dict[str, Any]] = []

        self._perm_create = SESSION.can(f"{PERMISSION_BASE}.create")
        self._perm_edit = SESSION.can(f"{PERMISSION_BASE}.edit")
        self._perm_save = SESSION.can(f"{PERMISSION_BASE}.save")
        self._perm_delete = SESSION.can(f"{PERMISSION_BASE}.delete")

        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet("QWidget { font-family: 'Segoe UI', 'Tahoma', 'Arial'; }")
        self.approval = ApprovalControls(self, PERMISSION_BASE, locked_when_approved=False)
        self._build_ui()
        self.set_mode("view")
        self.refresh_tree()
        self._show_empty()

    # -- layout ------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())

        body = QHBoxLayout()
        body.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background:transparent; }")
        self.branches_host = QWidget()
        self.branches_grid = QGridLayout(self.branches_host)
        self.branches_grid.setContentsMargins(0, 0, 0, 0)
        self.branches_grid.setHorizontalSpacing(16)
        self.branches_grid.setVerticalSpacing(16)
        self.branches_grid.setAlignment(Qt.AlignTop)
        for column in range(COLUMNS):
            self.branches_grid.setColumnStretch(column, 1)
        scroll.setWidget(self.branches_host)
        body.addWidget(scroll, 1)
        body.addWidget(self._build_drawer(), 0)
        root.addLayout(body, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background:{GREEN}; border-radius:6px; }}"
            "QLabel { background:transparent; color:#FFFFFF; }"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)
        icon = QLabel("🏢")
        icon.setFixedSize(54, 54)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background:rgba(255,255,255,0.16); border:1px solid rgba(255,255,255,0.28); "
            "border-radius:7px; font-size:24px; font-weight:900;"
        )
        title = QLabel("إدارة الشركات والمشاريع")
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

        self.new_company_button = QPushButton("شركة جديدة")
        self.new_project_button = QPushButton("مشروع جديد")
        self.edit_button = QPushButton("تعديل")
        self.save_button = QPushButton("حفظ")
        self.delete_button = QPushButton("حذف")
        self.cancel_button = QPushButton("إلغاء")
        self.refresh_button = QPushButton("تحديث")
        self.exit_button = QPushButton("خروج")
        buttons = [
            (self.new_company_button, QStyle.SP_FileIcon, "#1A7A3C", "#166534"),
            (self.new_project_button, QStyle.SP_FileDialogNewFolder, BLUE, "#075985"),
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
        self.search_text.setPlaceholderText("ابحث عن شركة أو مشروع")
        self.search_text.setFixedHeight(38)
        self.search_text.setMinimumWidth(240)
        self.search_text.setStyleSheet(
            "QLineEdit { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:7px; padding:6px 10px; }"
            f"QLineEdit:focus {{ border:1px solid {GREEN}; }}"
        )
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_tree)
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

        self.new_company_button.clicked.connect(self.new_company)
        self.approval.approve_button.clicked.connect(self.approve_record)
        self.approval.unapprove_button.clicked.connect(self.unapprove_record)
        self.new_project_button.clicked.connect(self.new_project)
        self.edit_button.clicked.connect(self.edit_record)
        self.save_button.clicked.connect(self.save_record)
        self.delete_button.clicked.connect(self.delete_record)
        self.cancel_button.clicked.connect(self.cancel_edit)
        self.refresh_button.clicked.connect(self.refresh_tree)
        self.exit_button.clicked.connect(self.window().close)
        return bar

    # -- the details drawer ----------------------------------------------------

    def _build_drawer(self) -> QFrame:
        drawer = QFrame()
        drawer.setObjectName("details_drawer")
        drawer.setFixedWidth(390)
        drawer.setStyleSheet(
            "QFrame#details_drawer { background:#FFFFFF; border:1px solid #E5EAF0; border-radius:10px; }"
            "QLabel { background:transparent; border:none; }"
        )
        shadow = QGraphicsDropShadowEffect(drawer)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(15, 23, 42, 40))
        drawer.setGraphicsEffect(shadow)

        layout = QVBoxLayout(drawer)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        top = QHBoxLayout()
        self.drawer_title = QLabel("")
        self.drawer_title.setStyleSheet(f"font-size:16px; font-weight:900; color:{GREEN};")
        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(32, 32)
        self.close_button.setToolTip("إغلاق")
        self.close_button.setAccessibleName("إغلاق")
        self.close_button.setStyleSheet(
            "QPushButton { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; "
            "font-size:17px; color:#475569; }"
            "QPushButton:hover { background:#F1F5F9; }"
        )
        self.close_button.clicked.connect(self.close_drawer)
        top.addWidget(self.drawer_title, 1)
        top.addWidget(self.close_button, 0)
        layout.addLayout(top)

        self.breadcrumb = QLabel("")
        self.breadcrumb.setWordWrap(True)
        self.breadcrumb.setStyleSheet("font-size:13px; font-weight:800; color:#475569;")
        layout.addWidget(self.breadcrumb)

        self.stack = QStackedWidget()
        self.empty_page = QLabel("اختار شركة أو مشروع من الشجرة\nأو اضغط «شركة جديدة».")
        self.empty_page.setAlignment(Qt.AlignCenter)
        self.empty_page.setStyleSheet("font-size:14px; font-weight:700; color:#94A3B8;")
        self.stack.addWidget(self.empty_page)
        self.stack.addWidget(self._build_company_form())
        self.stack.addWidget(self._build_project_form())
        layout.addWidget(self.stack, 1)
        self.drawer = drawer
        return drawer

    def _field(self, form: QVBoxLayout, caption: str, editor: QWidget, hint: str = "") -> None:
        label = QLabel(caption)
        label.setStyleSheet(f"font-size:14px; font-weight:900; color:{TEXT};")
        form.addWidget(label)
        form.addWidget(editor)
        if hint:
            note = QLabel(hint)
            note.setStyleSheet("font-size:11px; font-weight:700; color:#64748B;")
            form.addWidget(note)

    def _line_edit(self, placeholder: str, ltr: bool = False) -> QLineEdit:
        editor = QLineEdit()
        editor.setMinimumHeight(38)
        editor.setPlaceholderText(placeholder)
        editor.setStyleSheet(_EDITOR_QSS)
        if ltr:
            editor.setLayoutDirection(Qt.LeftToRight)
            editor.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return editor

    def _build_company_form(self) -> QWidget:
        page = QWidget()
        form = QVBoxLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        self.company_code = self._line_edit("كود الشركة", ltr=True)
        self.company_name = self._line_edit("اسم الشركة")
        self.company_address = self._line_edit("العنوان")
        self._field(form, "كود الشركة", self.company_code, "يُكتب تلقائيًا · قابل للتعديل")
        self._field(form, "اسم الشركة", self.company_name)
        self._field(form, "العنوان", self.company_address)
        self.company_projects_label = QLabel("")
        self.company_projects_label.setStyleSheet(f"font-size:13px; font-weight:900; color:{BLUE}; padding-top:6px;")
        form.addWidget(self.company_projects_label)
        form.addStretch(1)
        return page

    def _build_project_form(self) -> QWidget:
        page = QWidget()
        form = QVBoxLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        self.project_code = self._line_edit("كود المشروع", ltr=True)
        self.project_name = self._line_edit("اسم المشروع")
        self.project_company = QComboBox()
        self.project_company.setMinimumHeight(38)
        self.project_company.setStyleSheet(_COMBO_QSS)
        self.project_company.currentIndexChanged.connect(self._on_project_company_changed)
        self.project_address = self._line_edit("العنوان")
        self._field(form, "كود المشروع", self.project_code, "يبدأ بكود الشركة · قابل للتعديل")
        self._field(form, "اسم المشروع", self.project_name)
        self._field(form, "الشركة", self.project_company)
        self._field(form, "العنوان", self.project_address)
        form.addStretch(1)
        return page

    # -- the branches ------------------------------------------------------------

    def refresh_tree(self) -> None:
        if hasattr(self, "search_timer"):
            self.search_timer.stop()
        try:
            self._tree = self.service.tree(self.search_text.text())
        except Exception as exc:
            self._show_error("تعذّر تحميل الشركات", exc)
            return
        while self.branches_grid.count():
            item = self.branches_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._buttons = {}
        if not self._tree:
            empty = QLabel("لا توجد شركات بعد — اضغط «شركة جديدة»." if not self.search_text.text().strip()
                           else "لا توجد نتائج للبحث.")
            empty.setStyleSheet("font-size:15px; font-weight:800; color:#94A3B8; padding:30px;")
            empty.setAlignment(Qt.AlignCenter)
            self.branches_grid.addWidget(empty, 0, 0, 1, COLUMNS)
        for index, company in enumerate(self._tree):
            self.branches_grid.addWidget(self._build_branch(company), index // COLUMNS, index % COLUMNS)
        self._apply_selection()

    def _build_branch(self, company: dict[str, Any]) -> QWidget:
        block = QWidget()
        block.setStyleSheet("QLabel { background:transparent; border:none; }")
        column = QVBoxLayout(block)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        head = QPushButton()
        head.setCursor(Qt.PointingHandCursor)
        head.setMinimumHeight(60)
        row = QHBoxLayout(head)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)
        icon = QLabel("🏢")
        icon.setStyleSheet("font-size:20px; color:#FFFFFF;")
        # Name over code: side by side, a long company name was cut off.
        name = QLabel(str(company["company_name"]))
        name.setWordWrap(True)
        name.setStyleSheet("font-size:15px; font-weight:900; color:#FFFFFF;")
        code = QLabel(str(company["company_code"]))
        code.setStyleSheet("font-size:12px; font-weight:800; color:#D1FAE0;")
        code.setAlignment(Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(name)
        text.addWidget(code)
        for label in (icon, name, code):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(icon, 0)
        row.addLayout(text, 1)
        if company.get("status") == approval.DRAFT:
            chip = status_chip(approval.DRAFT)
            chip.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(chip, 0)
        head.clicked.connect(lambda _c=False, cid=company["company_id"]: self.select_company(cid))
        self._buttons[("company", company["company_id"])] = head
        column.addWidget(head)

        branch = QFrame()
        branch.setObjectName("branch")
        branch.setStyleSheet(f"QFrame#branch {{ border:none; border-right:2px solid {BRANCH_LINE}; }}")
        holder = QHBoxLayout()
        holder.setContentsMargins(0, 0, 22, 0)  # the line hangs under the header's icon
        holder.addWidget(branch)
        kids = QVBoxLayout(branch)
        kids.setContentsMargins(0, 2, 0, 2)
        kids.setSpacing(8)
        if not company["projects"]:
            none = QLabel("   لا توجد مشاريع")
            none.setStyleSheet("font-size:12px; font-weight:700; color:#94A3B8;")
            kids.addWidget(none)
        for project in company["projects"]:
            kids.addLayout(self._build_project_row(project))
        column.addLayout(holder)
        # Keep the branch at its own height when a taller company sits beside it.
        column.addStretch(1)
        return block

    def _build_project_row(self, project: dict[str, Any]) -> QHBoxLayout:
        line = QHBoxLayout()
        line.setSpacing(0)
        connector = QFrame()
        connector.setFixedSize(28, 2)
        connector.setStyleSheet(f"background:{BRANCH_LINE}; border:none;")
        line.addWidget(connector, 0, Qt.AlignVCenter)

        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(42)
        row = QHBoxLayout(button)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(10)
        icon = QLabel("📁")
        name = QLabel(str(project["project_name"]))
        name.setStyleSheet(f"font-size:13px; font-weight:800; color:{TEXT};")
        chip = QLabel(_short_project_code(project["project_code"]))
        chip.setToolTip(str(project["project_code"]))
        chip.setStyleSheet(
            f"font-size:11px; font-weight:800; color:{BLUE}; background:#E0F2FE; "
            "border-radius:6px; padding:2px 7px;"
        )
        widgets = [(icon, 0), (name, 1), (chip, 0)]
        if project.get("status") == approval.DRAFT:
            widgets.append((status_chip(approval.DRAFT), 0))
        for widget, stretch in widgets:
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(widget, stretch)
        button.clicked.connect(lambda _c=False, pid=project["project_id"]: self.select_project(pid))
        self._buttons[("project", project["project_id"])] = button
        line.addWidget(button, 1)
        return line

    def _apply_selection(self) -> None:
        for (kind, record_id), button in self._buttons.items():
            selected = kind == self.kind and str(record_id) == str(self.current_id)
            if kind == "company":
                button.setStyleSheet(
                    f"QPushButton {{ background:{GREEN_DARK if selected else GREEN}; border-radius:10px; "
                    f"border:{'3px solid #BBF7D0' if selected else 'none'}; }}"
                    f"QPushButton:hover {{ background:{GREEN_DARK}; }}"
                )
            else:
                button.setStyleSheet(
                    f"QPushButton {{ background:{'#F0F9FF' if selected else '#FFFFFF'}; border-radius:10px; "
                    f"border:{'2px solid ' + BLUE if selected else '1px solid #E2E8F0'}; }}"
                    "QPushButton:hover { background:#F8FAFC; }"
                )

    # -- selecting -----------------------------------------------------------------

    def _busy(self) -> bool:
        if self.mode in {"new", "edit"}:
            QMessageBox.information(self, "جاري التعديل", "احفظ التعديلات أو ألغِها الأول.")
            return True
        return False

    def select_company(self, company_id: Any) -> None:
        if self._busy():
            return
        self._load("company", company_id)

    def select_project(self, project_id: Any) -> None:
        if self._busy():
            return
        self._load("project", project_id)

    def reload_lists(self) -> None:
        """Data changed in another screen (or on another PC): rebuild the tree."""
        if self.mode in {"new", "edit"}:
            return
        self.refresh_tree()

    def _load(self, kind: str, record_id: Any) -> None:
        try:
            record = (self.service.get_company if kind == "company" else self.service.get_project)(record_id)
        except Exception as exc:
            self._show_error("فشل تحميل السجل", exc)
            return
        if not record:
            self._show_empty()
            return
        self.kind, self.current_id, self.current_record = kind, record_id, dict(record)
        if kind == "company":
            self._fill_company(record)
        else:
            self._fill_project(record)
        self.drawer.show()
        self.set_mode("view")
        self._apply_selection()

    def _fill_company(self, record: dict[str, Any]) -> None:
        self.stack.setCurrentIndex(1)
        self.drawer_title.setText("تفاصيل الشركة")
        self.breadcrumb.setText(f"🏢 {record.get('company_name') or ''}")
        self.company_code.setText(str(record.get("company_code") or ""))
        self.company_name.setText(str(record.get("company_name") or ""))
        self.company_address.setText(str(record.get("address") or ""))
        count = int(record.get("project_count") or 0)
        self.company_projects_label.setText(f"📁 عدد المشاريع: {count}")

    def _fill_project(self, record: dict[str, Any]) -> None:
        self.stack.setCurrentIndex(2)
        self.drawer_title.setText("تفاصيل المشروع")
        self.breadcrumb.setText(f"🏢 {record.get('company_name') or ''}  ›  📁 {record.get('project_name') or ''}")
        self._fill_company_choices(record.get("company_id"))
        self.project_code.setText(str(record.get("project_code") or ""))
        self.project_name.setText(str(record.get("project_name") or ""))
        self.project_address.setText(str(record.get("address") or ""))

    def _fill_company_choices(self, selected_id: Any) -> None:
        self.project_company.blockSignals(True)
        self.project_company.clear()
        try:
            choices = self.service.company_choices()
        except Exception:
            choices = []
        for company in choices:
            self.project_company.addItem(
                f"{company['company_code']} — {company['company_name']}", company["company_id"]
            )
        index = self.project_company.findData(selected_id)
        self.project_company.setCurrentIndex(max(0, index))
        self.project_company.blockSignals(False)

    def _show_empty(self) -> None:
        self.kind, self.current_id, self.current_record = None, None, None
        self.stack.setCurrentIndex(0)
        self.drawer_title.setText("التفاصيل")
        self.breadcrumb.setText("")
        self.set_mode("view")
        self._apply_selection()

    def close_drawer(self) -> None:
        if self._busy():
            return
        self._show_empty()

    # -- new / edit / save / delete ------------------------------------------------

    def _company_of_selection(self) -> Any:
        if self.kind == "company":
            return self.current_id
        if self.kind == "project":
            return self.project_company.currentData()
        return None

    def new_company(self) -> None:
        if self._busy():
            return
        self.kind, self.current_id, self.current_record = "company", None, None
        self.stack.setCurrentIndex(1)
        self.drawer_title.setText("شركة جديدة")
        self.breadcrumb.setText("")
        for editor in (self.company_code, self.company_name, self.company_address):
            editor.clear()
        self.company_projects_label.setText("")
        try:
            self.company_code.setText(self.service.next_company_code())
        except Exception:
            pass  # a suggestion only
        self.drawer.show()
        self.set_mode("new")
        self._apply_selection()
        self.company_name.setFocus()

    def new_project(self) -> None:
        if self._busy():
            return
        company_id = self._company_of_selection()
        self._fill_company_choices(company_id)
        if self.project_company.count() == 0:
            QMessageBox.information(self, "لا توجد شركات", "أضف شركة الأول، وبعدين أضف مشاريعها.")
            return
        self.kind, self.current_id, self.current_record = "project", None, None
        self.stack.setCurrentIndex(2)
        self.drawer_title.setText("مشروع جديد")
        self.breadcrumb.setText("")
        for editor in (self.project_code, self.project_name, self.project_address):
            editor.clear()
        self._suggested_code = ""
        self.drawer.show()
        self.set_mode("new")
        self._suggest_project_code()
        self._apply_selection()
        self.project_name.setFocus()

    def _suggest_project_code(self) -> None:
        """Fill the next code for the chosen company, unless the user typed one."""
        typed = self.project_code.text().strip()
        if typed and typed != self._suggested_code:
            return
        try:
            code = self.service.next_project_code(self.project_company.currentData())
        except Exception:
            return
        self._suggested_code = code
        self.project_code.setText(code)

    def _on_project_company_changed(self, _index: int) -> None:
        if self.mode == "new" and self.kind == "project":
            self._suggest_project_code()

    def edit_record(self) -> None:
        if self.current_id is not None and self.mode == "view":
            self.set_mode("edit")

    def save_record(self) -> None:
        if self.mode not in {"new", "edit"} or self.kind is None:
            return
        record_id = None if self.mode == "new" else self.current_id
        try:
            if self.kind == "company":
                saved = self.service.save_company(
                    {"company_code": self.company_code.text(), "company_name": self.company_name.text(),
                     "address": self.company_address.text()},
                    record_id,
                )
            else:
                saved = self.service.save_project(
                    {"company_id": self.project_company.currentData(), "project_code": self.project_code.text(),
                     "project_name": self.project_name.text(), "address": self.project_address.text()},
                    record_id,
                )
        except CompanyProjectError as exc:
            QMessageBox.warning(self, "لا يمكن الحفظ", str(exc))
            return
        except Exception as exc:
            self._show_error("فشل حفظ البيانات", exc)
            return
        kind = self.kind
        self.mode = "view"
        self.refresh_tree()
        self._load(kind, saved)
        notify_data_changed(self)
        QMessageBox.information(self, "تم الحفظ", self.approval.saved_message(
            self._status(), "الشركة" if kind == "company" else "المشروع"))

    def cancel_edit(self) -> None:
        if self.mode == "edit" and self.current_id is not None:
            self.mode = "view"
            self._load(self.kind, self.current_id)
        else:
            self._show_empty()

    def delete_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.may_delete(self._status()):
            return
        what = "الشركة" if self.kind == "company" else "المشروع"
        answer = QMessageBox.question(
            self, "تأكيد الحذف", f"هل تريد حذف {what} المحدد؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            if self.kind == "company":
                self.service.delete_company(self.current_id, allow_approved=self.approval.is_admin)
            else:
                self.service.delete_project(self.current_id, allow_approved=self.approval.is_admin)
        except (CompanyProjectError, approval.ApprovalError) as exc:
            QMessageBox.warning(self, "لا يمكن الحذف", str(exc))
            return
        except Exception as exc:
            self._show_error("لا يمكن حذف السجل", exc)
            return
        self._show_empty()
        self.refresh_tree()
        notify_data_changed(self)

    # -- اعتماد / إلغاء الاعتماد ----------------------------------------------------

    def _status(self) -> Any:
        return (self.current_record or {}).get("status") if self.current_id is not None else None

    def _approval_target(self) -> tuple[str, Any, str]:
        """(approval kind, id, «الشركة «…»») of the record in the drawer."""
        record = self.current_record or {}
        if self.kind == "company":
            return approval.COMPANY, self.current_id, f"الشركة «{record.get('company_name', '')}»"
        return approval.PROJECT, self.current_id, f"المشروع «{record.get('project_name', '')}»"

    def approve_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_approve:
            return
        kind, record_id, what = self._approval_target()
        if self.approval.approve(what, lambda: self.service.approve(kind, record_id, self.approval.user_id())):
            current = self.kind
            self.refresh_tree()
            self._load(current, record_id)
            QMessageBox.information(self, "تم", "تم الاعتماد.")

    def unapprove_record(self) -> None:
        if self.current_id is None or self.mode != "view" or not self.approval.can_unapprove:
            return
        kind, record_id, what = self._approval_target()
        if self.approval.unapprove(what, lambda: self.service.unapprove(kind, record_id)):
            current = self.kind
            self.refresh_tree()
            self._load(current, record_id)
            QMessageBox.information(self, "تم", "تم إلغاء الاعتماد، ورجع مسودة.")

    # -- modes -----------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        editing = mode in {"new", "edit"}
        for editor in (self.company_code, self.company_name, self.company_address,
                       self.project_code, self.project_name, self.project_address):
            editor.setReadOnly(not editing)
        self.project_company.setEnabled(editing)
        has_record = self.current_id is not None
        status = self._status()
        self.new_company_button.setEnabled(not editing and self._perm_create)
        self.new_project_button.setEnabled(not editing and self._perm_create)
        self.edit_button.setEnabled(not editing and has_record and self._perm_edit)
        self.delete_button.setEnabled(not editing and has_record and self._perm_delete
                                      and self.approval.may_delete(status))
        self.save_button.setEnabled(editing and self._perm_save)
        self.cancel_button.setEnabled(editing)
        self.approval.update(editing, status, self.edit_button, self.delete_button)
        self.search_text.setEnabled(not editing)
        self.mode_badge.setText({"view": "عرض", "new": "جديد", "edit": "تعديل"}.get(mode, mode))

    def _show_error(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, str(exc))
