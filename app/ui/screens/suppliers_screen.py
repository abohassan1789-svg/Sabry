"""Suppliers module screen (إدارة الموردين).

The "Model 1" horizontal code-band layout lives in :class:`CodeBandCrudScreen`;
this screen only binds it to the ``suppliers`` spec. The code is a plain number
starting at 1001 (no prefix), so no ``_display_value`` override is needed.
"""

from __future__ import annotations

from app.ui.screens.code_band_crud_screen import CodeBandCrudScreen


class SuppliersScreen(CodeBandCrudScreen):
    SPEC_KEY = "suppliers"
