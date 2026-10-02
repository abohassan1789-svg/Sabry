"""«اعتماد» / «إلغاء الاعتماد» on the contracting screens (user request, 2026-10-02).

One helper per screen holds the two toolbar buttons and the status badge, and
answers what the rules in ``contracting_approval`` allow the current user:

* «اعتماد» needs the ``approve`` permission and a saved draft; «إلغاء الاعتماد»
  needs ``unapprove`` and an approved record.
* An approved contract / extract / payment (``locked_when_approved``) is
  neither edited nor deleted; an approved contractor / company / project is
  still edited but not deleted. A full-access (admin) user may do anything.

The screen keeps its own flow (reload, messages); ``approve`` / ``unapprove``
here only ask, run the service call and report a refusal.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QStyle, QWidget

from app.security.session_context import SESSION
from app.services.contracting_approval import APPROVED, DRAFT, STATUS_LABELS, ApprovalError
from app.ui.common.live_lists import notify_data_changed
from app.ui.common.theme import _button_style

DRAFT_COLOR, DRAFT_TINT = "#B45309", "#FEF3C7"
APPROVED_COLOR, APPROVED_TINT = "#047857", "#D1FAE5"

LOCKED_TIP = "السجل معتمد: الغي الاعتماد الأول عشان تعدّل أو تحذف."
DELETE_TIP = "السجل معتمد: الغي الاعتماد الأول عشان تحذف."


def status_colors(status: Any) -> tuple[str, str]:
    """(text, background) of a status chip."""
    return (APPROVED_COLOR, APPROVED_TINT) if status == APPROVED else (DRAFT_COLOR, DRAFT_TINT)


def status_chip(status: Any, size: int = 11) -> QLabel:
    """A small «مسودة» / «معتمد» chip for a card or a list row."""
    color, tint = status_colors(status)
    chip = QLabel(STATUS_LABELS.get(str(status or ""), ""))
    chip.setStyleSheet(
        f"font-size:{size}px; font-weight:900; color:{color}; background:{tint}; "
        "border-radius:6px; padding:2px 8px;"
    )
    return chip


def draft_suffix(record: dict[str, Any]) -> str:
    """«  · مسودة» after a draft's text in a tree or a list; nothing for an approved one."""
    return f"  · {STATUS_LABELS[DRAFT]}" if record.get("status") == DRAFT else ""


class ApprovalControls:
    def __init__(self, screen: QWidget, permission_base: str, locked_when_approved: bool) -> None:
        self.screen = screen
        self.locked_when_approved = locked_when_approved
        self.can_approve = SESSION.can(f"{permission_base}.approve")
        self.can_unapprove = SESSION.can(f"{permission_base}.unapprove")
        self.is_admin = SESSION.is_admin

        self.approve_button = QPushButton("اعتماد")
        self.unapprove_button = QPushButton("إلغاء الاعتماد")
        for button, icon, bg, hover in (
            (self.approve_button, QStyle.SP_DialogApplyButton, "#0F766E", "#115E59"),
            (self.unapprove_button, QStyle.SP_DialogResetButton, "#B45309", "#92400E"),
        ):
            button.setFixedHeight(38)
            button.setIcon(screen.style().standardIcon(icon))
            button.setStyleSheet(_button_style(bg, hover))
        self.approve_button.setToolTip("يعتمد السجل المحفوظ، فيظهر في باقي الشاشات والتقارير.")
        self.unapprove_button.setToolTip("يرجّع السجل مسودة، فيختفي من باقي الشاشات والتقارير.")

        self.badge = QLabel("")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setMinimumWidth(90)
        self.badge.hide()

    def add_buttons(self, layout: QHBoxLayout) -> None:
        layout.addWidget(self.approve_button)
        layout.addWidget(self.unapprove_button)

    # -- what the user may do ----------------------------------------------------

    def may_edit(self, status: Any) -> bool:
        return self.is_admin or not (self.locked_when_approved and status == APPROVED)

    def may_delete(self, status: Any) -> bool:
        return self.is_admin or status != APPROVED

    def update(self, editing: bool, status: Any, edit_button: QPushButton | None = None,
               delete_button: QPushButton | None = None) -> None:
        """Enable the two buttons and show the badge for the record on screen (*status* None = none)."""
        self.approve_button.setEnabled(not editing and status == DRAFT and self.can_approve)
        self.unapprove_button.setEnabled(not editing and status == APPROVED and self.can_unapprove)
        if status in STATUS_LABELS:
            color, tint = status_colors(status)
            self.badge.setText(STATUS_LABELS[status])
            self.badge.setStyleSheet(
                f"background:{tint}; color:{color}; border:1px solid {color}; border-radius:7px; "
                "padding:8px 12px; font-weight:900;"
            )
            self.badge.show()
        else:
            self.badge.hide()
        if edit_button is not None:
            edit_button.setToolTip("" if self.may_edit(status) else LOCKED_TIP)
        if delete_button is not None:
            delete_button.setToolTip("" if self.may_delete(status) else DELETE_TIP)

    @staticmethod
    def user_id() -> Any:
        return (SESSION.user or {}).get("id")

    # -- the two actions ---------------------------------------------------------------

    def approve(self, what: str, run: Callable[[], None]) -> bool:
        """Ask, then approve *what* («العقد «A-H/CT-1001»») through *run*; True when it was approved."""
        answer = QMessageBox.question(
            self.screen, "تأكيد الاعتماد",
            f"اعتماد {what}؟\nبعد الاعتماد هيظهر في باقي الشاشات والتقارير.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return answer == QMessageBox.Yes and self._run("لا يمكن الاعتماد", run)

    def unapprove(self, what: str, run: Callable[[], None]) -> bool:
        answer = QMessageBox.question(
            self.screen, "تأكيد إلغاء الاعتماد",
            f"إلغاء اعتماد {what}؟\nهيرجع مسودة ويختفي من باقي الشاشات والتقارير.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return answer == QMessageBox.Yes and self._run("لا يمكن إلغاء الاعتماد", run)

    def _run(self, title: str, run: Callable[[], None]) -> bool:
        try:
            run()
        except ApprovalError as exc:
            QMessageBox.warning(self.screen, title, str(exc))
            return False
        except Exception as exc:  # a database error: shown, never raised into Qt
            QMessageBox.critical(self.screen, title, str(exc))
            return False
        notify_data_changed(self.screen)
        return True

    @staticmethod
    def saved_message(status: Any, noun: str) -> str:
        """What «حفظ» reports: a draft is reminded it still needs «اعتماد»."""
        if status == APPROVED:
            return f"تم حفظ {noun} بنجاح."
        return f"تم حفظ {noun} كمسودة.\nاضغط «اعتماد» عشان يظهر في باقي الشاشات والتقارير."
