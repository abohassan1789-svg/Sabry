"""Keep every open screen's lists current without restarting the app.

User request (2026-10-02): «لما بدخل مقاول جديد واعتمده وأروح أعمله عقد، مش
بيظهر … لازم أقفل البرنامج». Screens are built once and kept open, and each
fills its lists (combos, trees, reports) when built — so a contractor approved
in one screen never reached the others.

Now every data screen announces a successful save / delete — and
``ApprovalControls`` an approve / unapprove — on ``DATA_EVENTS.changed``. The
main window's ``LiveLists`` marks every OTHER open screen stale, and a stale
screen calls its own ``reload_lists()`` when the user comes to it (window
activated, or opened from the sidebar). A screen in «جديد» / «تعديل» is never
reloaded under the user's hands: it waits, and reloads once the edit ends.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QWidget

EDITING_MODES = frozenset({"new", "edit"})


class _DataEvents(QObject):
    # The widget whose save / approve / delete changed the data.
    changed = Signal(object)


DATA_EVENTS = _DataEvents()


def notify_data_changed(sender: QWidget | None) -> None:
    """Tell every other open screen that its lists may be out of date."""
    DATA_EVENTS.changed.emit(sender)


def is_editing(window: Any) -> bool:
    return getattr(window, "mode", "view") in EDITING_MODES


class LiveLists(QObject):
    """Owns the stale flags of the open screens and reloads them at the right time."""

    RETRY_MS = 700
    # A click into an inactive window activates it first; reloading a moment later
    # lets that click land on the rows the user saw, not on a rebuilt tree.
    ACTIVATE_DELAY_MS = 150

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._windows: list[QWidget] = []
        self._stale: list[QWidget] = []
        self._waiting: list[QWidget] = []  # stale, but mid-edit
        self._timer = QTimer(self)
        self._timer.setInterval(self.RETRY_MS)
        self._timer.timeout.connect(self.retry)
        DATA_EVENTS.changed.connect(self._on_changed)

    def register(self, window: QWidget) -> None:
        if not callable(getattr(window, "reload_lists", None)) or self._has(self._windows, window):
            return
        self._windows.append(window)
        window.installEventFilter(self)
        window.destroyed.connect(lambda *_a, w=window: self._forget(w))

    def opened(self, window: QWidget) -> None:
        """The user opened *window* from the sidebar: reload it (changes from other PCs too)."""
        if self._has(self._windows, window):
            self._mark(window)
            self._refresh(window)

    def is_stale(self, window: QWidget) -> bool:
        return self._has(self._stale, window)

    def retry(self) -> None:
        for window in list(self._waiting):
            if not is_editing(window):
                self._refresh(window)
        if not self._waiting:
            self._timer.stop()

    # -- internals -------------------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt naming)
        if event.type() == QEvent.WindowActivate and self._has(self._stale, obj):
            QTimer.singleShot(self.ACTIVATE_DELAY_MS, self, lambda w=obj: self._refresh(w))
        return False

    def _on_changed(self, sender: Any) -> None:
        for window in list(self._windows):
            if isinstance(sender, QWidget) and (window is sender or window.isAncestorOf(sender)):
                continue
            self._mark(window)
            if window.isActiveWindow():
                self._refresh(window)

    def _mark(self, window: QWidget) -> None:
        if not self._has(self._stale, window):
            self._stale.append(window)

    def _refresh(self, window: QWidget) -> None:
        if not self._has(self._stale, window):
            return
        if is_editing(window):
            if not self._has(self._waiting, window):
                self._waiting.append(window)
            self._timer.start()
            return
        self._drop(self._stale, window)
        self._drop(self._waiting, window)
        window.reload_lists()

    def _forget(self, window: QWidget) -> None:
        for bucket in (self._windows, self._stale, self._waiting):
            self._drop(bucket, window)

    @staticmethod
    def _has(bucket: list[QWidget], window: Any) -> bool:
        return any(item is window for item in bucket)

    @staticmethod
    def _drop(bucket: list[QWidget], window: Any) -> None:
        bucket[:] = [item for item in bucket if item is not window]
