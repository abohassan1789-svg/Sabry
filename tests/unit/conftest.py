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
