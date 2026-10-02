"""القوايم بتتحدث في كل الشاشات المفتوحة من غير ما نقفل البرنامج (user request 2026-10-02)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
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
    """Activate *window* and let the (slightly delayed) reload run."""
    QApplication.sendEvent(window, QEvent(QEvent.WindowActivate))
    QTest.qWait(LiveLists.ACTIVATE_DELAY_MS + 150)


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


def test_the_activating_click_lands_before_the_reload(live):
    """Review fix: the click that activates a stale window must hit the rows the
    user saw, so the reload waits a moment instead of running inside activation."""
    contractors, contracts = FakeWindow(), FakeWindow()
    live.register(contractors)
    live.register(contracts)
    notify_data_changed(contractors)
    QApplication.sendEvent(contracts, QEvent(QEvent.WindowActivate))
    assert contracts.reloads == 0
    QTest.qWait(live.ACTIVATE_DELAY_MS + 150)
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
