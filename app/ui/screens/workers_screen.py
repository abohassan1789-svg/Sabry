"""Workers module screen (إدارة العمال).

Same "Model 1" layout as the suppliers screen (via :class:`CodeBandCrudScreen`),
bound to the ``workers`` spec. The only difference is the code format: the stored
worker_id is a plain integer starting at 1, shown zero-padded to four digits
(``0001``, ``0002``, ``0003`` ...) for display only — the real id still drives
the primary key and any future links.
"""

from __future__ import annotations

from typing import Any

from app.ui.screens.code_band_crud_screen import CodeBandCrudScreen


class WorkersScreen(CodeBandCrudScreen):
    SPEC_KEY = "workers"

    def _display_value(self, field_name: str, value: Any) -> Any:
        """Show the worker code zero-padded to four digits (0001, 0002, ...)."""
        if field_name == "worker_id" and value not in (None, ""):
            try:
                return f"{int(value):04d}"
            except (TypeError, ValueError):
                return value
        return value
