"""Drop lists searchable by any part of an item (user, 2026-10-07).

Only the screens shown in the sidebar, phase by phase: a screen calls
``enable_combo_search(self)`` and each of its QComboBoxes (and those of the
dialogs it parents, built now or later) is hooked:

* A pick-only combo (not editable, or a read-only line edit) keeps its normal
  behaviour, but typing opens its list with a search box on top. Each letter
  hides the items that don't contain what was typed; Enter or a click picks
  the highlighted one, Backspace removes a letter, Esc clears the search.
* A free-typing combo that only accepts its own items (``NoInsert``, no
  validator) gets a contains-completer: typing shows the matching items.

Matching ignores case and the usual Arabic spelling variants (أ/إ/آ/ا, ة/ه,
ى/ي, diacritics). A combo opts out with ``combo.setProperty("noSearch", True)``.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QLineEdit,
    QListView,
    QStyle,
    QWidget,
)

_HOOKED = "_searchHooked"
_ENABLED = "comboSearchEnabled"
_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u0640]")  # tashkeel + tatweel
_LETTER_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_EDIT_QSS = (
    "QLineEdit { background:#F0FDF4; border:none; border-bottom:1px solid #15803D; "
    "padding:5px 8px; font-size:13px; font-weight:700; color:#0F172A; }"
)
_EDIT_NO_MATCH_QSS = _EDIT_QSS.replace("#F0FDF4", "#FEF2F2").replace("#15803D", "#DC2626")


def normalize_search_text(text: str) -> str:
    """Lower-case, no diacritics and one spelling for the common Arabic variants."""
    return _DIACRITICS.sub("", str(text or "")).translate(_LETTER_MAP).casefold().strip()


def matches(item_text: str, typed: str) -> bool:
    needle = normalize_search_text(typed)
    return not needle or needle in normalize_search_text(item_text)


def _is_typing_key(event: QKeyEvent) -> bool:
    if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
        return False
    text = event.text()
    return bool(text) and text.isprintable()


class _ComboSearch(QObject):
    """The search box and row filter of one pick-only combo's popup."""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self.combo = combo
        self.text = ""
        self.edit: QLineEdit | None = None
        self.view: QAbstractItemView | None = None
        self._chrome: int | None = None  # popup height that isn't the list (frame, box, arrows)
        self._list_height = 0

    # --- wiring -------------------------------------------------------------
    def _ensure_view_hooked(self) -> None:
        view = self.combo.view()
        if view is self.view:
            return
        self.view = view
        view.installEventFilter(self)

    def _ensure_edit(self) -> QLineEdit | None:
        container = self.view.parentWidget() if self.view is not None else None
        layout = container.layout() if container is not None else None
        if layout is None:
            return None
        if self.edit is None or self.edit.parentWidget() is not container:
            self.edit = QLineEdit(container)
            self.edit.setObjectName("comboSearchBox")
            self.edit.setReadOnly(True)
            self.edit.setFocusPolicy(Qt.NoFocus)
            self.edit.setPlaceholderText("اكتب جزء من الاسم للبحث…")
            self.edit.setLayoutDirection(Qt.RightToLeft)
            self.edit.setStyleSheet(_EDIT_QSS)
            layout.insertWidget(0, self.edit)
            if not self.combo.style().styleHint(QStyle.SH_ComboBox_Popup, None, self.combo):
                # A plain drop-down scrolls with its scroll bar; Qt still flashes the
                # popup-menu scroll arrows as an empty strip above or under the matches.
                # (Done by style sheet: wrapping those private widgets in PySide crashes.)
                container.setStyleSheet(
                    container.styleSheet() + "QComboBoxPrivateScroller { max-height:0px; min-height:0px; }"
                )
        return self.edit

    # --- events -------------------------------------------------------------
    def combo_key(self, event: QKeyEvent) -> bool:
        """A key on the closed combo: a letter opens the list already searching it."""
        if not _is_typing_key(event) or not self.combo.isEnabled() or self.combo.count() == 0:
            return False
        self._ensure_view_hooked()
        if self.view.isVisible():  # the list is already open: keep adding to the search
            self.set_text(self.text + event.text())
            return True
        self.combo.showPopup()
        self.set_text(event.text())
        return True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if watched is not self.view:
            return False
        kind = event.type()
        if kind == QEvent.Show:
            self._ensure_edit()
            self.text = ""
            self._apply()
        elif kind == QEvent.Hide:
            self.text = ""
            self._unhide_all()
        elif kind == QEvent.KeyPress:
            return self._view_key(event)
        return False

    def _view_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key == Qt.Key_Backspace:
            if self.text:
                self.set_text(self.text[:-1])
            return True
        if key == Qt.Key_Escape and self.text:
            self.set_text("")
            return True
        if _is_typing_key(event):
            self.set_text(self.text + event.text())
            return True
        return False

    # --- filtering ----------------------------------------------------------
    def set_text(self, text: str) -> None:
        self.text = text
        self._apply()

    def _unhide_all(self) -> None:
        if isinstance(self.view, QListView):
            for row in range(self.combo.count()):
                self.view.setRowHidden(row, False)
        if self.edit is not None:
            self.edit.clear()
            self.edit.setStyleSheet(_EDIT_QSS)

    def _apply(self) -> None:
        if not isinstance(self.view, QListView):
            return
        first_visible = -1
        current_row = self.view.currentIndex().row()
        current_visible = False
        column = self.combo.modelColumn()
        model = self.combo.model()
        root = self.combo.rootModelIndex()
        for row in range(model.rowCount(root)):
            label = str(model.index(row, column, root).data(Qt.DisplayRole) or "")
            show = matches(label, self.text) if self.text else True
            self.view.setRowHidden(row, not show)
            if show and first_visible < 0 and (label.strip() or not self.text):
                first_visible = row
            if show and row == current_row:
                current_visible = True
        if self.text and first_visible >= 0 and not (current_visible and self.view.currentIndex().data()):
            self.view.setCurrentIndex(model.index(first_visible, column, root))
        if self.edit is not None:
            self.edit.setText(self.text)
            self.edit.setStyleSheet(_EDIT_QSS if (first_visible >= 0 or not self.text) else _EDIT_NO_MATCH_QSS)
        self._fit()

    def _fit(self) -> None:
        """Size the popup to the search box plus the rows still shown, under the combo
        (above it when the screen has no room below)."""
        container = self.view.parentWidget() if self.view is not None else None
        if container is None or self.edit is None:
            return
        rows = [row for row in range(self.combo.count()) if not self.view.isRowHidden(row)]
        row_height = self.view.sizeHintForRow(rows[0]) if rows else -1
        if row_height <= 0:
            row_height = self.view.fontMetrics().height() + 8
        shown = max(1, min(len(rows), self.combo.maxVisibleItems()))
        self._list_height = shown * row_height + 2 * self.view.frameWidth()
        if self._chrome is None:  # a first guess; _settle() learns the real one
            margins = container.contentsMargins()
            self._chrome = self.edit.sizeHint().height() + margins.top() + margins.bottom()
        height = self._list_height + self._chrome
        below = self.combo.mapToGlobal(self.combo.rect().bottomLeft())
        above = self.combo.mapToGlobal(self.combo.rect().topLeft())
        width = max(container.geometry().width(), self.combo.width())
        right = self.combo.mapToGlobal(self.combo.rect().topRight()).x()
        left = right - width + 1 if self.combo.layoutDirection() == Qt.RightToLeft else below.x()
        geometry = QRect(left, below.y() + 1, width, height)
        screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if geometry.bottom() > available.bottom():
                if above.y() - height >= available.top():
                    geometry.moveBottom(above.y() - 1)
                else:
                    geometry.setBottom(available.bottom())
        container.setGeometry(geometry)
        self.view.scrollTo(self.view.currentIndex())
        QTimer.singleShot(0, self, self._settle)  # dropped if the combo is gone

    def _settle(self) -> None:
        """Once laid out, give the list what the frame, spacers and scroll arrows took from it."""
        container = self.view.parentWidget() if self.view is not None else None
        if container is None or not container.isVisible() or self._chrome is None:
            return
        short = self._list_height - self.view.height()
        if short == 0:
            return
        self._chrome += short
        geometry = QRect(container.geometry())
        above = self.combo.mapToGlobal(self.combo.rect().topLeft())
        if geometry.bottom() < above.y():  # opens upwards
            geometry.setTop(geometry.top() - short)
        else:
            geometry.setHeight(geometry.height() + short)
        container.setGeometry(geometry)
        self.view.scrollTo(self.view.currentIndex())


class SearchableCombos(QObject):
    """App-wide hook: makes each QComboBox inside an enabled screen searchable once polished."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        kind = event.type()
        if kind == QEvent.Polish:
            if isinstance(watched, QComboBox) and _in_enabled_screen(watched):
                hook_combo(watched)
        elif kind == QEvent.MouseButtonPress and isinstance(watched, QComboBox):
            search = watched.findChild(_ComboSearch, options=Qt.FindDirectChildrenOnly)
            if search is not None:
                search._ensure_view_hooked()  # setView() may have swapped the list
        elif kind == QEvent.KeyPress and isinstance(watched, (QComboBox, QLineEdit)):
            search = _search_for(watched)
            if search is not None:
                return search.combo_key(event)
        return False


def _in_enabled_screen(widget: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if parent.property(_ENABLED):
            return True
        parent = parent.parentWidget()
    return False


def _search_for(watched: QObject) -> _ComboSearch | None:
    combo = watched if isinstance(watched, QComboBox) else watched.parentWidget()
    if not isinstance(combo, QComboBox) or combo.property("noSearch"):
        return None
    if combo.isEditable() and not (combo.lineEdit() and combo.lineEdit().isReadOnly()):
        return None  # free typing: the completer does the searching
    return combo.findChild(_ComboSearch, options=Qt.FindDirectChildrenOnly)


def hook_combo(combo: QComboBox) -> None:
    """Make one combo searchable (idempotent)."""
    if combo.property(_HOOKED) or combo.property("noSearch"):
        return
    combo.setProperty(_HOOKED, True)
    _ComboSearch(combo)._ensure_view_hooked()
    _upgrade_completer(combo)


def _upgrade_completer(combo: QComboBox) -> None:
    """Free-typing combos limited to their items: suggest every item containing the text."""
    edit = combo.lineEdit()
    if edit is None or edit.isReadOnly() or edit.validator() is not None:
        return
    if combo.insertPolicy() != QComboBox.NoInsert:
        return  # free text is allowed (e.g. a server address); leave its completion alone
    completer = combo.completer()
    if completer is None or completer.completionMode() == QCompleter.UnfilteredPopupCompletion:
        return
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCompletionMode(QCompleter.PopupCompletion)


_INSTALLED: SearchableCombos | None = None


def enable_combo_search(screen: QWidget) -> None:
    """Turn the search on for every drop list in ``screen``, now and later (its dialogs too)."""
    global _INSTALLED
    app = QApplication.instance()
    if _INSTALLED is None and app is not None:
        _INSTALLED = SearchableCombos(app)
        app.installEventFilter(_INSTALLED)
    screen.setProperty(_ENABLED, True)
    for combo in screen.findChildren(QComboBox):
        hook_combo(combo)
