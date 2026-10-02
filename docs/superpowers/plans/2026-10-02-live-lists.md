# Live Lists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A contractor (or company, project, contract, extract or payment) that is saved, approved, unapproved or deleted in one screen appears right away in every other contracting screen's lists, reports and dashboard, with no app restart.

**Architecture:**
- **The cause.** `MainWindow.open_screen` builds each screen once and keeps it in `open_windows`. A screen fills its lists in `__init__`, and reopening it only calls `refresh_dashboard`, which the contracting screens don't have. So the lists stay as they were first loaded.
- **The bus.** A small app-wide bus, `DATA_EVENTS.changed`, in `app/ui/common/live_lists.py`. Each data screen emits it after a successful save/delete, and `ApprovalControls` emits it after a successful approve/unapprove.
- **The manager.** A `LiveLists` manager owned by the main window marks every other open screen "stale". A stale screen calls its own `reload_lists()` as soon as the user comes to it (the window is activated, or opened from the sidebar). A screen in the middle of «جديد»/«تعديل» is never reloaded under the user's hands; it reloads as soon as the edit is saved or cancelled.
- **Other PCs.** Opening a screen from the sidebar always reloads it, so changes made on another PC show up too.

**Tech Stack:** Python 3.11, PySide6 (QObject signals, event filter, QTimer), pytest.

**Spec:** The user's request of 2026-10-02:
- «لما بدخل مقاول جديد، اعتمد وراح أعمله عقد … لازم أقفل البرنامج عشان يسمع فيها الجديد … في جميع الشاشات كدة كل القوائم».
- Scope: every contracting screen in the sidebar:
  - **Data screens:** المقاولين، الشركات والمشاريع، العقود، المستخلصات، الدفعات.
  - **Reports:** the 4 reports and داشبورد المقاولين.

  These are the only visible screens (see the memory notes `sidebar-visibility` and `contracting-only-permissions`).

## Global Constraints

- **Working directory:** paths and commands are relative to `E:\PostGre\Moh Sabry\CRM_PYTHON_APP_STRUCTURE`, on branch `main`.
- **Commit and push at the end.** Standing user instruction: after the task, commit on `main` and push to `origin main` (https://github.com/abohassan1789-svg/Sabry). Commit once, after the whole plan passes; this plan's per-task commit steps are folded into Task 4.
  - **Never stage:** `.env.example` and `app/database/migrations/002_migrate_access_core_data.ps1` (skip-worktree, hold the DB password), backups, config, `.bat`, PDFs.
  - **Before pushing,** grep the staged diff for the DB password and the default user password (their values are in the local, never-pushed `run_*.bat` files).
  - **Author:** `abo <abo.hassan1789@gmail.com>`, set through `GIT_AUTHOR_*` / `GIT_COMMITTER_*` env vars, because there is no global git identity.
- **No reload while the user edits.** Never reload a screen whose `mode` is `"new"` or `"edit"`: it would drop their typing, and extracts/payments `refresh_all` pops «احفظ التعديلات أو ألغِها الأول».
- **A reload keeps the user's place.** It keeps what is selected (the open contract, extract or payment, and the picked combo items) and never changes the maths.
- **Run only the related tests.** The full suite takes over 10 minutes. The related set is the files named in each task.
- **Known pre-existing failures:** none in these files (checked 2026-10-02).
- **Reply to the user in Egyptian Arabic.**

## Review Focus

1. **Two screens side by side.** The contractors window is active when it approves, so the contracts window is not active. It must reload when the user clicks into it, not before and not never. Pinned by `test_a_stale_window_reloads_once_when_activated` (Task 1).
2. **The sender's own child widgets.** `ApprovalControls.screen` is the screen itself, but a future emitter might pass a child widget. The sender's window must not be marked stale by its own change. Pinned by `test_a_change_from_a_child_widget_counts_as_its_window` (Task 1).
3. **A screen left in «جديد» when the change happens.** It must reload once the user saves or cancels, even though no new activation follows. Pinned by `test_an_editing_window_reloads_after_the_edit_ends` (Task 1).
4. **A refused save or delete must not broadcast.** For example, a duplicate code, or a company that still has projects. Pinned by `test_a_refused_delete_does_not_announce_a_change` (Task 2).
5. **A window closed while stale.** Its C++ object is gone. The next broadcast must not touch it. Pinned by `test_a_closed_window_is_forgotten` (Task 1).

---

### Task 1: The bus and the `LiveLists` manager

**Files:**
- Create: `app/ui/common/live_lists.py`
- Create: `tests/unit/conftest.py`. It doesn't exist yet; it holds one shared fixture.
- Create: `tests/unit/test_live_lists.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DATA_EVENTS: _DataEvents`, a `QObject` with `changed = Signal(object)`.
  - `notify_data_changed(sender: QWidget | None) -> None`
  - `is_editing(window: QWidget) -> bool`, true when `getattr(window, "mode", "view") in {"new", "edit"}`.
  - `class LiveLists(QObject)` with:
    - `register(window: QWidget) -> None`. It ignores windows without a callable `reload_lists`.
    - `opened(window: QWidget) -> None`. Marks the window stale and refreshes it now (or once its edit ends).
    - `is_stale(window: QWidget) -> bool`
    - `retry() -> None`. The timer slot; public so tests can call it.
  - Test fixture `data_changes` in `tests/unit/conftest.py`: a list that collects every `DATA_EVENTS.changed` sender while the test runs.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/conftest.py`:

```python
"""Shared fixtures for the unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def data_changes():
    """Every sender announced on DATA_EVENTS.changed while the test runs."""
    from app.ui.common.live_lists import DATA_EVENTS

    seen: list = []

    def collect(sender) -> None:
        seen.append(sender)

    DATA_EVENTS.changed.connect(collect)
    yield seen
    DATA_EVENTS.changed.disconnect(collect)
```

Create `tests/unit/test_live_lists.py`:

```python
"""القوايم بتتحدث في كل الشاشات المفتوحة من غير ما نقفل البرنامج (user request 2026-10-02)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from app.ui.common.live_lists import LiveLists, is_editing, notify_data_changed


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.mode = "view"
        self.reloads = 0

    def reload_lists(self):
        self.reloads += 1


def _activate(window):
    QApplication.sendEvent(window, QEvent(QEvent.WindowActivate))


@pytest.fixture
def live(qt_app):
    manager = LiveLists()
    yield manager
    manager.deleteLater()


def test_a_stale_window_reloads_once_when_activated(live):
    contractors, contracts = FakeWindow(), FakeWindow()
    live.register(contractors)
    live.register(contracts)
    notify_data_changed(contractors)
    assert live.is_stale(contracts) and contracts.reloads == 0
    _activate(contracts)
    assert contracts.reloads == 1 and not live.is_stale(contracts)
    _activate(contracts)  # nothing changed since: no second reload
    assert contracts.reloads == 1


def test_the_sender_is_not_marked_stale(live):
    contractors = FakeWindow()
    live.register(contractors)
    notify_data_changed(contractors)
    assert not live.is_stale(contractors)
    _activate(contractors)
    assert contractors.reloads == 0


def test_a_change_from_a_child_widget_counts_as_its_window(live):
    contractors, contracts = FakeWindow(), FakeWindow()
    button = QPushButton(contractors)
    live.register(contractors)
    live.register(contracts)
    notify_data_changed(button)
    assert not live.is_stale(contractors) and live.is_stale(contracts)


def test_an_editing_window_reloads_after_the_edit_ends(live):
    contractors, payments = FakeWindow(), FakeWindow()
    live.register(contractors)
    live.register(payments)
    payments.mode = "new"
    notify_data_changed(contractors)
    _activate(payments)
    assert payments.reloads == 0 and live.is_stale(payments)  # never under the user's hands
    live.retry()
    assert payments.reloads == 0  # still typing
    payments.mode = "view"  # saved or cancelled
    live.retry()
    assert payments.reloads == 1 and not live.is_stale(payments)


def test_opening_from_the_sidebar_always_reloads(live):
    """Picks up changes made on another PC, which no signal here announces."""
    report = FakeWindow()
    live.register(report)
    live.opened(report)
    assert report.reloads == 1


def test_opening_a_screen_mid_edit_waits_for_the_edit(live):
    screen = FakeWindow()
    screen.mode = "edit"
    live.register(screen)
    live.opened(screen)
    assert screen.reloads == 0
    screen.mode = "view"
    live.retry()
    assert screen.reloads == 1


def test_windows_without_reload_lists_are_ignored(live):
    plain, contracts = QWidget(), FakeWindow()
    live.register(plain)
    live.register(contracts)
    notify_data_changed(contracts)
    assert not live.is_stale(plain)


def test_a_closed_window_is_forgotten(live, qt_app):
    contractors, contracts = FakeWindow(), FakeWindow()
    live.register(contractors)
    live.register(contracts)
    contracts.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    notify_data_changed(contractors)  # must not touch the deleted window
    assert contractors.reloads == 0


def test_is_editing_reads_the_mode():
    class Screen:
        mode = "edit"

    assert is_editing(Screen())
    Screen.mode = "view"
    assert not is_editing(Screen())
    assert not is_editing(object())  # no mode at all = a report


def test_data_changes_fixture_sees_announcements(qt_app, data_changes):
    sender = FakeWindow()
    notify_data_changed(sender)
    assert data_changes == [sender]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/unit/test_live_lists.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'app.ui.common.live_lists'`.

- [ ] **Step 3: Write the module**

Create `app/ui/common/live_lists.py`:

```python
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
            self._refresh(obj)
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_live_lists.py -q`
Expected: 10 passed.

If `test_a_closed_window_is_forgotten` errors with "Internal C++ object already deleted", the `destroyed` lambda didn't fire before the broadcast. Check that `sendPostedEvents(None, QEvent.DeferredDelete)` ran. Do not paper over it with a try/except in `_on_changed`.

---

### Task 2: Announce every successful save, delete, approve and unapprove

**Files:**
- Modify: `app/ui/screens/approval_controls.py`, `_run` (~line 135).
- Modify: `app/ui/screens/base_crud_screen.py`, `save_record` (~898) and `delete_record` (~928). This covers المقاولين.
- Modify: `app/ui/screens/contractor_contracts_screen.py`, `save_record` (~1002) and `delete_record` (~1027).
- Modify: `app/ui/screens/contractor_extracts_screen.py`, `save_record` (~1168) and `delete_record` (~1192).
- Modify: `app/ui/screens/contractor_payments_screen.py`, `save_record` (~1177) and `delete_record` (~1214).
- Modify: `app/ui/screens/company_projects_screen.py`, `save_record` (~639) and `delete_record` (~676).
- Test: add to `tests/unit/test_contractor_contracts_screen.py`, `tests/unit/test_contractor_extracts_screen.py`, `tests/unit/test_contractor_payments_screen.py`, `tests/unit/test_company_projects_screen.py` and `tests/unit/test_contractors_screen.py`.

**Interfaces:**
- Consumes: `notify_data_changed` and the `data_changes` fixture (Task 1).
- Produces: every successful save/delete/approve/unapprove in the 5 data screens emits `DATA_EVENTS.changed(screen)`. A refused or cancelled action emits nothing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_contractor_contracts_screen.py`:

```python
# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_announces_a_change(screen, data_changes):
    screen.load_contract(101)
    screen.edit_record()
    screen.save_record()
    assert data_changes == [screen]


def test_cancel_announces_nothing(screen, data_changes):
    screen.load_contract(101)
    screen.edit_record()
    screen.cancel_edit()
    assert data_changes == []


def test_delete_and_approve_announce_a_change(screen, data_changes):
    screen.load_contract(101)
    screen.approve_record()
    screen.load_contract(102)
    screen.delete_record()
    assert data_changes == [screen, screen]
```

Append to `tests/unit/test_contractor_extracts_screen.py`:

```python
# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_and_deleting_announce_a_change(draft_screen, data_changes):
    screen = draft_screen
    screen.edit_record()
    screen.save_record()
    screen.delete_record()
    assert data_changes == [screen, screen]
```

Append to `tests/unit/test_contractor_payments_screen.py`:

```python
# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_and_deleting_announce_a_change(admin_screen, data_changes):
    screen = admin_screen
    screen.edit_record()
    screen.save_record()
    screen.delete_record()
    assert data_changes == [screen, screen]
```

Append to `tests/unit/test_company_projects_screen.py`:

```python
# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_and_deleting_a_project_announce_a_change(screen, data_changes):
    screen.select_company(1)
    screen.new_project()
    screen.project_name.setText("مدرسة النور")
    screen.save_record()
    screen.select_project(11)
    screen.delete_record()
    assert data_changes == [screen, screen]


def test_a_refused_delete_does_not_announce_a_change(screen, data_changes):
    screen.select_company(1)  # still has projects
    screen.delete_record()
    assert data_changes == []
```

Append to `tests/unit/test_contractors_screen.py`:

```python
# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_and_approving_a_contractor_announce_a_change(screen, data_changes):
    screen.new_record()
    screen.inputs["contractor_name"].setText("مقاول جديد")
    screen.save_record()
    _open(screen, 2)
    screen.approve_record()
    assert data_changes == [screen, screen]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/unit/test_contractor_contracts_screen.py tests/unit/test_contractor_extracts_screen.py tests/unit/test_contractor_payments_screen.py tests/unit/test_company_projects_screen.py tests/unit/test_contractors_screen.py -q -k "announce"`
Expected: the 7 "announce" tests that assert a non-empty list FAIL with `assert [] == [...]`. `test_cancel_announces_nothing` and `test_a_refused_delete_does_not_announce_a_change` pass already; they are guards.

- [ ] **Step 3: Emit on success**

`app/ui/screens/approval_controls.py`:
- Add `from app.ui.common.live_lists import notify_data_changed` to the imports.
- In `_run`, replace the final `return True` with:

```python
        notify_data_changed(self.screen)
        return True
```

`app/ui/screens/base_crud_screen.py`:
- Add the same import.
- In `save_record`, insert `notify_data_changed(self)` between `self._select_row_by_id(saved_id)` and `QMessageBox.information(self, "تم الحفظ", self._saved_message())`.
- In `delete_record`, insert `notify_data_changed(self)` after `self.set_mode("view")` inside the `try`.

`app/ui/screens/contractor_contracts_screen.py`:
- Add the import.
- In `save_record`, insert `notify_data_changed(self)` right before `QMessageBox.information(self, "تم الحفظ", …)`.
- In `delete_record`, append `notify_data_changed(self)` after the final `self.refresh_views()`.

`app/ui/screens/contractor_extracts_screen.py`:
- Add the import.
- In `save_record`, insert `notify_data_changed(self)` right before `QMessageBox.information(self, "تم الحفظ", …)`.
- In `delete_record`, append `notify_data_changed(self)` after the final `self.set_contract(self.contract_id)`.

`app/ui/screens/contractor_payments_screen.py`:
- Add the import.
- In `save_record`, insert `notify_data_changed(self)` right before `QMessageBox.information(self, "تم الحفظ", …)`.
- In `delete_record`, append `notify_data_changed(self)` after the final `self.select(...)` call.

`app/ui/screens/company_projects_screen.py`:
- Add the import.
- In `save_record`, insert `notify_data_changed(self)` right before `QMessageBox.information(self, "تم الحفظ", …)`.
- In `delete_record`, append `notify_data_changed(self)` after the final `self.refresh_tree()`.

Every insertion sits on the success path only, after the early `return`s of the `except` blocks.

- [ ] **Step 4: Run the five screen test files**

Run: `python -m pytest tests/unit/test_contractor_contracts_screen.py tests/unit/test_contractor_extracts_screen.py tests/unit/test_contractor_payments_screen.py tests/unit/test_company_projects_screen.py tests/unit/test_contractors_screen.py tests/unit/test_live_lists.py -q`
Expected: all pass. That is the new tests plus every existing screen test.

---

### Task 3: `reload_lists()` on every contracting screen, wired into the main window

**Files:**
- Modify: `app/ui/screens/contracting_report_base.py`. Add `reload_lists` after `refresh_all` (~line 430); it covers the 4 reports and the dashboard.
- Modify: `app/ui/screens/contractor_contracts_screen.py`. Add `reload_lists` after `refresh_all` (~905).
- Modify: `app/ui/screens/contractor_extracts_screen.py`. Add `reload_lists` after `refresh_all` (~911).
- Modify: `app/ui/screens/contractor_payments_screen.py`. Add `reload_lists` after `refresh_all` (~744).
- Modify: `app/ui/screens/company_projects_screen.py`. Add `reload_lists` after `refresh_tree` (~356).
- Modify: `app/ui/screens/contractors_screen.py`. Add `reload_lists` after `refresh_table` (~522).
- Modify: `app/ui/main_window.py`:
  - `__init__`: create the manager next to the services (~line 321).
  - `_build_window`: register the window (~768).
  - `open_screen`: reload an existing window (~789).
- Test: `tests/unit/test_live_lists.py` (an integration test with real screens), plus one reload test each in `tests/unit/test_contractor_contracts_screen.py`, `tests/unit/test_contractor_extracts_screen.py`, `tests/unit/test_contractor_payments_screen.py` and `tests/unit/test_contractor_extracts_report.py`.

**Interfaces:**
- Consumes: `LiveLists`, `DATA_EVENTS` and `is_editing` (Task 1), and the emits (Task 2).
- Produces: `reload_lists(self) -> None` on `ContractingReportBase`, `ContractorContractsScreen`, `ContractorExtractsScreen`, `ContractorPaymentsScreen`, `CompanyProjectsScreen` and `ContractorsScreen`, plus `MainWindow.live_lists: LiveLists`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_contractor_contracts_screen.py`:

```python
def test_reload_lists_shows_a_contractor_approved_elsewhere(screen, monkeypatch):
    screen.load_contract(101)
    extra = {"contractor_id": 9, "contractor_code": "A-H/CD-1009", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.reload_lists()
    assert screen.tree_form.contractor.findData(9) >= 0
    assert screen.current_id == 101  # the open contract stays open
```

Append to `tests/unit/test_contractor_extracts_screen.py`:

```python
def test_reload_lists_refreshes_the_pickers_but_never_mid_edit(screen, monkeypatch):
    extra = {"contractor_id": 9, "contractor_code": "A-H/CD-1009", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.new_extract()
    screen.reload_lists()  # «جديد»: untouched, and no «احفظ التعديلات» popup
    assert screen.mode == "new" and screen.contractor_picker.findData(9) < 0
    screen.cancel_edit()
    screen.reload_lists()
    assert screen.contractor_picker.findData(9) >= 0
```

Append to `tests/unit/test_contractor_payments_screen.py`:

```python
def test_reload_lists_refreshes_the_contractor_list(screen, monkeypatch):
    extra = {"contractor_id": 9, "contractor_code": "A-H/CD-1009", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.reload_lists()
    assert screen.board_contractor.findData(9) >= 0
```

Append to `tests/unit/test_contractor_extracts_report.py`:

```python
def test_reload_lists_refreshes_the_filters_and_keeps_the_pick(screen, monkeypatch):
    screen.contractor_combo.setCurrentIndex(screen.contractor_combo.findData(1))
    extra = {"contractor_id": 9, "contractor_code": "D9", "contractor_name": "مقاول جديد"}
    choices = screen.service.contractor_choices
    monkeypatch.setattr(screen.service, "contractor_choices", lambda: [*choices(), extra])
    screen.reload_lists()
    assert screen.contractor_combo.findData(9) >= 0
    assert screen.contractor_combo.currentData() == 1
```

Append to `tests/unit/test_live_lists.py`, the user's own scenario end to end with the real screens:

```python
def test_a_contractor_approved_in_its_screen_reaches_the_open_contracts_screen(live, monkeypatch):
    from tests.unit import test_contractor_contracts_screen as contracts_tests
    from tests.unit import test_contractors_screen as contractors_tests
    from app.ui.screens import contractor_contracts_screen, contractors_screen
    from app.ui.screens import base_crud_screen

    for module in (contractor_contracts_screen, contractors_screen, base_crud_screen):
        for name in ("information", "warning", "critical"):
            monkeypatch.setattr(module.QMessageBox, name, lambda *a, **k: None)
        monkeypatch.setattr(module.QMessageBox, "question", lambda *a, **k: module.QMessageBox.Yes)
    backend = contractors_tests.FakeBackend()
    monkeypatch.setattr(contractors_screen.ContractorsScreen, "_backend", lambda self: backend)

    contractors = contractors_screen.ContractorsScreen(contractors_tests.FakeService())
    contract_service = contracts_tests.FakeService()
    contracts = contractor_contracts_screen.ContractorContractsScreen(contract_service)
    live.register(contractors)
    live.register(contracts)

    # The new contractor only becomes a choice once approved (approved-only lists).
    extra = {"contractor_id": 9, "contractor_code": "A-H/CD-1009", "contractor_name": "مقاول معتمد"}
    choices = contract_service.contractor_choices
    monkeypatch.setattr(contract_service, "contractor_choices",
                        lambda: [*choices(), extra] if backend.approved else choices())
    contractors._load_contractor(2)
    contractors.approve_record()
    assert live.is_stale(contracts)
    _activate(contracts)
    assert contracts.tree_form.contractor.findData(9) >= 0
```

Ids: contractor 2 is a draft in `test_contractors_screen.FakeBackend` (statuses {1: approved, 2: draft}); the contracts fake already has contractors 1 and 2, so the newly approved one is mirrored there as id 9. Both fakes and `tests/unit/__init__.py` exist, so the imports work.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/unit/test_live_lists.py tests/unit/test_contractor_contracts_screen.py tests/unit/test_contractor_extracts_screen.py tests/unit/test_contractor_payments_screen.py tests/unit/test_contractor_extracts_report.py -q -k "reload_lists or reaches"`
Expected:
- The 4 `reload_lists` tests FAIL with `AttributeError: … has no attribute 'reload_lists'`.
- The integration test FAILS because `register` ignores a screen without `reload_lists`, so `assert live.is_stale(contracts)` fails.

- [ ] **Step 3: Add `reload_lists` to the six classes**

`app/ui/screens/contracting_report_base.py`, after `refresh_all`:

```python
    def reload_lists(self) -> None:
        """Data changed in another screen: refill the filters (keeping the picks) and rerun."""
        self.refresh_all()
```

`app/ui/screens/contractor_contracts_screen.py`, after `refresh_all`:

```python
    def reload_lists(self) -> None:
        """Data changed in another screen: refill the lists, keeping the open contract."""
        if self.mode in {"new", "edit"}:
            return
        self.refresh_all()
```

`app/ui/screens/contractor_extracts_screen.py` and `app/ui/screens/contractor_payments_screen.py`, after `refresh_all`. The text is the same in both; the `mode` check matters here because `refresh_all` → `_busy()` would pop «احفظ التعديلات أو ألغِها الأول»:

```python
    def reload_lists(self) -> None:
        """Data changed in another screen: refill the lists, keeping the selection.

        Never mid-edit: refresh_all would stop on «احفظ التعديلات أو ألغِها الأول».
        """
        if self.mode in {"new", "edit"}:
            return
        self.refresh_all()
```

`app/ui/screens/company_projects_screen.py`, after `refresh_tree`:

```python
    def reload_lists(self) -> None:
        """Data changed in another screen (or on another PC): rebuild the tree."""
        if self.mode in {"new", "edit"}:
            return
        self.refresh_tree()
```

`app/ui/screens/contractors_screen.py`, after `refresh_table`:

```python
    def reload_lists(self) -> None:
        """Data changed on another PC: reload the list, keeping the open contractor."""
        if self.mode in {"new", "edit"}:
            return
        current = self.current_id
        self.refresh_table()
        if current is not None:
            self._select_row_by_id(current)
```

- [ ] **Step 4: Wire the manager into the main window**

In `app/ui/main_window.py`, add `from app.ui.common.live_lists import LiveLists` to the imports.

In `__init__`, right after `self.sync_service = PermissionsSyncService(self.security_repo)`:

```python
        # Refreshes the other open screens' lists after a save/approve (user request 2026-10-02).
        self.live_lists = LiveLists(self)
```

In `_build_window`, before `return window`:

```python
        self.live_lists.register(window)
```

In `open_screen`, inside `if is_existing_window:` after the `refresh_dashboard` lines:

```python
            # Reopened from the sidebar: reload its lists (also catches other PCs' changes).
            self.live_lists.opened(window)
```

- [ ] **Step 5: Run the related tests**

Run: `python -m pytest tests/unit/test_live_lists.py tests/unit/test_contractor_contracts_screen.py tests/unit/test_contractor_extracts_screen.py tests/unit/test_contractor_payments_screen.py tests/unit/test_company_projects_screen.py tests/unit/test_contractors_screen.py tests/unit/test_contractor_extracts_report.py tests/unit/test_contractor_contracts_report.py tests/unit/test_contractor_advance_report.py tests/unit/test_contractor_statement_report.py tests/unit/test_contractors_dashboard.py -q`
Expected: all pass.

- [ ] **Step 6: Check that the main window still imports**

Run: `python -c "import app.ui.main_window as m; print(hasattr(m, 'LiveLists'))"`
Expected: `True`.

---

### Task 4: Verify, commit and push

**Files:**
- Modify: memory `C:\Users\hp\.claude\projects\E--PostGre-Moh-Sabry\memory\live-lists.md` (new) and `MEMORY.md` (one line).

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: the commit on `origin/main`.

- [ ] **Step 1: Run the related set once more and save the summary line**

Run: the Task 3 Step 5 command.
Expected: all pass.

- [ ] **Step 2: Write the memory**

`live-lists.md`:

```markdown
---
name: live-lists
description: "Open screens refresh their lists after a save/approve elsewhere (2026-10-02): DATA_EVENTS bus + LiveLists in app/ui/common/live_lists.py"
metadata:
  type: project
---

User complaint (2026-10-02): a contractor added and approved didn't appear in عقود المقاولين until the app was restarted, because screens are built once and kept open.

**What was built:**
- Data screens call `notify_data_changed(self)` after a successful save/delete. `ApprovalControls._run` does the same after approve/unapprove.
- `MainWindow.live_lists` marks the other open screens stale. A stale screen runs its `reload_lists()` when its window is activated.
- Reopening a screen from the sidebar always reloads it, which also catches other PCs' changes.
- Never mid-edit: a screen in «جديد»/«تعديل» waits and reloads after the edit ends.

**How to apply:** a new contracting screen needs a `reload_lists()` (silent, keeps the selection, returns while `mode` is new/edit). A new data screen must call `notify_data_changed(self)` on its success paths only. Related: [[contracting-draft-approval]], [[user-ui-preferences]].
```

Add this line to `MEMORY.md`:

```
- [Live lists](live-lists.md) — open screens refresh after a save/approve elsewhere; new screens need reload_lists() + notify_data_changed (2026-10-02)
```

- [ ] **Step 3: Stage only this plan's files and check them**

```bash
git add app/ui/common/live_lists.py app/ui/screens/approval_controls.py app/ui/screens/base_crud_screen.py app/ui/screens/contractor_contracts_screen.py app/ui/screens/contractor_extracts_screen.py app/ui/screens/contractor_payments_screen.py app/ui/screens/company_projects_screen.py app/ui/screens/contracting_report_base.py app/ui/screens/contractors_screen.py app/ui/main_window.py tests/unit/conftest.py tests/unit/test_live_lists.py tests/unit/test_contractor_contracts_screen.py tests/unit/test_contractor_extracts_screen.py tests/unit/test_contractor_payments_screen.py tests/unit/test_company_projects_screen.py tests/unit/test_contractors_screen.py tests/unit/test_contractor_extracts_report.py docs/superpowers/plans/2026-10-02-live-lists.md
git diff --cached --name-only
git diff --cached | grep -c -F -e "$DB_PASSWORD" -e "$CRM_DEFAULT_PASSWORD"   # both read from a local run_*.bat first
```

Expected:
- The name list is exactly those 19 files.
- The grep count is `0`.

- [ ] **Step 4: Commit and push**

```bash
GIT_AUTHOR_NAME=abo GIT_AUTHOR_EMAIL=abo.hassan1789@gmail.com GIT_COMMITTER_NAME=abo GIT_COMMITTER_EMAIL=abo.hassan1789@gmail.com git commit -m "Refresh open screens' lists after a save or approval elsewhere" -m "A contractor approved in its screen did not appear in the contracts screen until the app was restarted: screens are built once and kept open. Data screens now announce saves, deletes and approvals; the main window marks the other open screens stale and each reloads its lists when the user comes back to it, never mid-edit." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin main
```

Expected: `main -> main`.
