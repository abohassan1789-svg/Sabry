"""Shared 'Model 1' CRUD screen: a horizontal code-band form + name-stretch list.

Concrete master screens (suppliers, workers, ...) whose form is exactly the
"Model 1" layout subclass this and only set :attr:`SPEC_KEY`. The layout is fully
derived from the screen's :class:`TableSpec`:

* the primary-key field renders as a green **code badge** (read-only, kept in
  ``self.inputs`` so the base fill/clear/new logic still drives it),
* every other visible field renders label-above-input in one horizontal band,
* the list below stretches its first data column (the name) instead of the
  trailing column.

Override :meth:`_display_value` to format the code (e.g. zero-padded ``0001``).
Business/database logic stays in ``ReviewDataService``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import FieldSpec, ReviewDataService, TABLE_SPECS
from app.ui.common.theme import GREEN, TEXT
from app.ui.screens.base_crud_screen import BaseCrudScreen


class CodeBandCrudScreen(BaseCrudScreen):
    SPEC_KEY = ""

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)

    # -- Model 1 form body: horizontal band ---------------------------------

    def _build_form_panel(self) -> QScrollArea:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        title = QLabel(self.spec.title.replace("إدارة", "بيانات"))
        title.setStyleSheet(f"font-size:21px; font-weight:900; color:{TEXT};")
        self.summary_label = QLabel("سجل جديد")
        self.summary_label.setStyleSheet("font-size:13px; font-weight:700; color:#64748B;")
        outer.addWidget(title)
        outer.addWidget(self.summary_label)

        band = QFrame()
        band.setStyleSheet(
            "QFrame { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:10px; }"
        )
        row = QHBoxLayout(band)
        row.setContentsMargins(14, 14, 14, 14)
        row.setSpacing(12)

        row.addWidget(self._build_code_badge(), 0)
        for field in self.spec.fields:
            if field.name == self.spec.primary_key or field.hidden_on_form:
                continue
            row.addWidget(self._build_labeled_field(field), 1)

        outer.addWidget(band)
        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(container)
        scroll.setMinimumHeight(150)
        scroll.setMaximumHeight(200)
        return scroll

    def _build_code_badge(self) -> QFrame:
        pk = self.spec.primary_key
        caption_text = next((f.label for f in self.spec.fields if f.name == pk), "الكود")
        badge = QFrame()
        badge.setMinimumWidth(140)
        badge.setStyleSheet(f"QFrame {{ background:{GREEN}; border-radius:10px; }}")
        layout = QVBoxLayout(badge)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        caption = QLabel(caption_text)
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet("background:transparent; color:#FFFFFF; font-size:11px; font-weight:900;")

        editor = QLineEdit()
        editor.setReadOnly(True)
        editor.setAlignment(Qt.AlignCenter)
        editor.setStyleSheet(
            "QLineEdit { background:transparent; border:none; color:#FFFFFF; "
            "font-size:20px; font-weight:900; }"
        )
        self.inputs[pk] = editor

        layout.addWidget(caption)
        layout.addWidget(editor)
        return badge

    def _build_labeled_field(self, field: FieldSpec) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        label = QLabel(field.label)
        label.setAlignment(Qt.AlignCenter)
        label.setLayoutDirection(Qt.RightToLeft)
        label.setStyleSheet(f"font-size:14px; font-weight:900; color:{TEXT};")

        editor = self._make_editor(field)
        # Keep the field text on the right (the base leaves name-type fields
        # left-aligned, which looked inconsistent in this band).
        if isinstance(editor, QLineEdit):
            editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.inputs[field.name] = editor

        # Label fills the column width and its text is centered above the field.
        layout.addWidget(label)
        layout.addWidget(editor)
        return wrapper

    # -- wider name column --------------------------------------------------

    def refresh_table(self) -> None:
        super().refresh_table()
        # Stretch the first data column (the name) instead of the trailing one,
        # so long names are readable; keep the second column at a fixed width.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        if self.table.columnCount() > 1:
            header.setSectionResizeMode(1, QHeaderView.Interactive)
            if not getattr(self, "_cols_tuned", False):
                self.table.setColumnWidth(1, 220)
                self._cols_tuned = True

    # -- code preview + opening-balance default on New ----------------------

    def new_record(self) -> None:
        super().new_record()
        # This layout is not in LOOKUP_LAYOUT_KEYS, so the base does not preview
        # the next code — do it here, formatted through _display_value.
        try:
            next_id = self.service.next_id(self.spec)
            self._set_editor_value(
                self.inputs[self.spec.primary_key],
                self._display_value(self.spec.primary_key, next_id),
            )
        except Exception:
            pass
        editor = self.inputs.get("opening_balance")
        if editor is not None:
            editor.setText("0.00")
