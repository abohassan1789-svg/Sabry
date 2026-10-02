"""شاشة تكعيب الكسّارات — قسم التوريدات (Tawrid module, phase 5).

A **master→detail document**: one header (a crusher + a date + a sheet number)
owns many lines (a tractor + its cubic volume). It replaces the Access objects
``sallesHead`` / ``Sallesdata`` / ``SallesInvoice`` — which, despite their
*sales-invoice* names, carry **no price at all**, only the تكعيب (volume) of each
tractor from each crusher (audited 2026-09-04).

Layout is "Model 9" from the mockup set the user picked: a header band, then each
line as a **small card** (اسم السائق · رقم الوش · التكعيب), a totals footer, and —
like the البون — **no sheet list on the screen**: finding an earlier كشف is done
through the «بحث عن كشف» dialog and الأول/السابق/التالي/الأخير navigation.

The header's own INSERT/UPDATE/DELETE is the shared path (``ReviewDataService`` +
``TABLE_SPECS['tawrid_crusher_cubing']``). The lines are persisted immediately,
one statement at a time, through :class:`TawridCubingService` — the same pattern
as the customers-screen price grid, so a line can only be added once the header
exists. What is deliberately different from Access, each tied to a measured fact:

* **The crusher and the tractor are real foreign keys, chosen from pickers.**
  Access had none: 3 sheets had no crusher, 1 pointed at deleted crusher 22, and
  45 of 125 lines pointed at deleted tractors.
* **Deleting a sheet deletes its lines** (ON DELETE CASCADE); Access left them
  orphaned.
* **رقم الوش / اسم السائق are read live from the tractor card,** not re-typed on
  the line (``Sallesdata`` stored its own drifting copy).
* **The dead ``inv_id`` (text) and ``t1`` (bool) columns are gone.**
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.services.tawrid_cubing_service import CubingLine, CubingTotals, TawridCubingService
from app.ui.common.theme import GREEN, _button_style
from app.ui.dialogs.tawrid_cubing_picker import TawridCubingPickerDialog
from app.ui.dialogs.tawrid_supplier_picker import TawridSupplierPickerDialog
from app.ui.dialogs.tawrid_tractor_picker import TawridTractorPickerDialog
from app.ui.screens.base_crud_screen import BaseCrudScreen

# The crusher card colour (amber), matching the crusher's colour across the
# module; the totals footer uses the module green.
RES = ("#B45309", "#FBF0E2")
# Cards per row in the line grid.
_CARDS_PER_ROW = 3


def _num(value: Decimal | float | int | None) -> str:
    """Thousands-separated volume, up to three decimals, trailing zeros trimmed."""
    amount = Decimal(str(value or 0))
    text = f"{amount:,.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _parse_volume(text: Any) -> Decimal | None:
    """Read a volume box. Blank means zero; anything unparseable is None."""
    cleaned = str(text or "").replace(",", "").strip()
    if cleaned == "":
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


class TawridCubingScreen(BaseCrudScreen):
    SPEC_KEY = "tawrid_crusher_cubing"
    SEARCH_PLACEHOLDER = "ابحث برقم الكشف أو اسم الكسّارة"

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        # Populated before super().__init__ because the base constructor builds
        # the UI, which calls back into the widgets built here.
        self._backend_service: TawridCubingService | None = None
        self._crusher_label: QLabel | None = None
        self._stat_values: dict[str, QLabel] = {}
        self._lines: list[CubingLine] = []
        self._line_editors: dict[Any, QLineEdit] = {}
        self._filling = False
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)
        self._refresh_lines()

    # -- backend ---------------------------------------------------------

    def _backend(self) -> TawridCubingService:
        if self._backend_service is None:
            self._backend_service = TawridCubingService()
        return self._backend_service

    # -- toolbar ---------------------------------------------------------

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        """«بحث عن كشف» + the record navigation that stands in for the list."""
        self.find_button = QPushButton("بحث عن كشف")
        self.find_button.setFixedHeight(38)
        self.find_button.setStyleSheet(_button_style("#0EA5E9", "#0284C7"))
        self.find_button.clicked.connect(self.open_lookup)
        layout.addWidget(self.find_button)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, caption in (
            ("first", "الاول"),
            ("prev", "السابق"),
            ("next", "التالي"),
            ("last", "الاخير"),
        ):
            button = QPushButton(caption)
            button.setFixedHeight(38)
            button.setStyleSheet(
                "QPushButton { background:#F1F5F9; color:#475569; border:1px solid #E2E8F0; "
                "border-radius:6px; font-weight:800; padding:7px 10px; }"
                "QPushButton:hover { background:#E2E8F0; }"
                "QPushButton:disabled { color:#CBD5E1; }"
            )
            button.clicked.connect(lambda _c=False, k=key: self._navigate(k))
            self.nav_buttons[key] = button
            layout.addWidget(button)

    # -- layout ----------------------------------------------------------

    def _build_content(self):
        content = QVBoxLayout()
        content.setSpacing(10)

        # The base class writes to ``summary_label`` on every load/new/clear;
        # build it here (the base only builds it inside its form panel, which this
        # screen replaces) so those writes land, as a thin caption line.
        self.summary_label = QLabel("كشف جديد")
        self.summary_label.setStyleSheet("font-size:13px; font-weight:800; color:#64748B;")
        content.addWidget(self.summary_label, 0)

        content.addWidget(self._build_header_card(), 0)
        content.addWidget(self._build_lines_panel(), 1)
        content.addWidget(self._build_totals_footer(), 0)

        # The list panel stays built (the base class drives selection and the
        # record count through ``self.table``) but hidden — Model 9 has no sheet
        # list; navigation and «بحث عن كشف» use it instead.
        self.list_panel = self._build_list_panel()
        self.list_panel.hide()
        content.addWidget(self.list_panel, 0)
        return content

    def _editor(self, name: str) -> QLineEdit:
        by_name = {field.name: field for field in self.spec.fields}
        editor = self._make_editor(by_name[name])
        self.inputs[name] = editor
        return editor

    def _hidden_id(self, name: str) -> QLineEdit:
        editor = QLineEdit()
        editor.setReadOnly(True)
        editor.hide()
        self.inputs[name] = editor
        return editor

    def _labelled(self, caption: str, widget: QWidget) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        lab = QLabel(caption)
        lab.setStyleSheet("font-size:11.5px; font-weight:700; color:#64748B;")
        col.addWidget(lab)
        col.addWidget(widget)
        return box

    def _card(self, title: str, role: str, accent: tuple[str, str]) -> tuple[QFrame, QGridLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setStyleSheet(
            "QFrame#card { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:9px; }"
        )
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        strip = QFrame()
        strip.setStyleSheet(
            f"background:{accent[0]}; border-top-left-radius:8px; border-top-right-radius:8px;"
        )
        srow = QHBoxLayout(strip)
        srow.setContentsMargins(13, 7, 13, 7)
        head = QLabel(title)
        head.setStyleSheet("color:#FFFFFF; font-size:14px; font-weight:900; background:transparent;")
        role_lab = QLabel(role)
        role_lab.setStyleSheet(
            "color:rgba(255,255,255,0.9); font-size:11px; font-weight:700; background:transparent;"
        )
        srow.addWidget(head)
        srow.addStretch(1)
        srow.addWidget(role_lab)
        outer.addWidget(strip)

        body = QGridLayout()
        body.setContentsMargins(13, 11, 13, 12)
        body.setHorizontalSpacing(12)
        body.setVerticalSpacing(8)
        holder = QWidget()
        holder.setLayout(body)
        outer.addWidget(holder)
        return frame, body

    def _build_header_card(self) -> QFrame:
        frame, grid = self._card("بيانات الكشف", "الكسّارة والتاريخ", RES)
        self._hidden_id("crusher_id")

        # Crusher pick row (name label + «اختيار كسّارة» button).
        pick = QWidget()
        prow = QHBoxLayout(pick)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(8)
        self._crusher_label = QLabel("— لم تُختَر —")
        self._crusher_label.setStyleSheet(
            "font-size:14px; font-weight:900; color:#111827; background:#F8FAFC; "
            "border:1px solid #E2E8F0; border-radius:7px; padding:7px 10px;"
        )
        self._crusher_label.setMinimumHeight(38)
        self.crusher_pick_button = QPushButton("اختيار كسّارة")
        self.crusher_pick_button.setFixedHeight(38)
        self.crusher_pick_button.setStyleSheet(_button_style(RES[0], "#92400E"))
        self.crusher_pick_button.clicked.connect(self.pick_crusher)
        prow.addWidget(self._crusher_label, 1)
        prow.addWidget(self.crusher_pick_button, 0)

        grid.addWidget(self._labelled("الكسّارة", pick), 0, 0, 1, 3)
        grid.addWidget(self._labelled("رقم الكشف", self._editor("sheet_no")), 1, 0)
        grid.addWidget(self._labelled("التاريخ", self._editor("sheet_date")), 1, 1)
        grid.addWidget(self._labelled("ملاحظات", self._editor("notes")), 1, 2)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        return frame

    def _build_lines_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame#lines { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:9px; }"
        )
        frame.setObjectName("lines")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header strip: title + count + «إضافة جرّار».
        strip = QFrame()
        strip.setStyleSheet(
            "background:#1D4ED8; border-top-left-radius:8px; border-top-right-radius:8px;"
        )
        srow = QHBoxLayout(strip)
        srow.setContentsMargins(13, 7, 13, 7)
        title = QLabel("الجرّارات والتكعيب")
        title.setStyleSheet("color:#FFFFFF; font-size:14px; font-weight:900; background:transparent;")
        self._lines_count_label = QLabel("")
        self._lines_count_label.setStyleSheet(
            "color:rgba(255,255,255,0.92); font-size:12px; font-weight:800; background:transparent;"
        )
        self.add_line_button = QPushButton("＋ إضافة جرّار")
        self.add_line_button.setFixedHeight(30)
        self.add_line_button.setStyleSheet(
            "QPushButton { background:rgba(255,255,255,0.16); color:#FFFFFF; "
            "border:1px solid rgba(255,255,255,0.4); border-radius:6px; font-weight:800; padding:4px 12px; }"
            "QPushButton:hover { background:rgba(255,255,255,0.28); }"
            "QPushButton:disabled { color:rgba(255,255,255,0.45); border-color:rgba(255,255,255,0.2); }"
        )
        self.add_line_button.clicked.connect(self.add_line)
        srow.addWidget(title)
        srow.addSpacing(10)
        srow.addWidget(self._lines_count_label)
        srow.addStretch(1)
        srow.addWidget(self.add_line_button)
        outer.addWidget(strip)

        # A hint shown when lines cannot yet be added (no saved header / view mode).
        self._lines_hint = QLabel("")
        self._lines_hint.setStyleSheet(
            "font-size:12px; font-weight:700; color:#94A3B8; padding:6px 13px 0 13px;"
        )
        outer.addWidget(self._lines_hint)

        # Scrollable grid of line cards.
        self._cards_host = QWidget()
        self._cards_grid = QGridLayout(self._cards_host)
        self._cards_grid.setContentsMargins(13, 10, 13, 12)
        self._cards_grid.setHorizontalSpacing(10)
        self._cards_grid.setVerticalSpacing(10)
        self._cards_grid.setAlignment(Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._cards_host)
        outer.addWidget(scroll, 1)
        return frame

    def _build_totals_footer(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet("QFrame { background:transparent; }")
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        for key, caption, accent in (
            ("total", "إجمالي التكعيب", GREEN),
            ("count", "عدد الجرّارات", "#1D4ED8"),
            ("average", "متوسط الحمولة", "#0EA5E9"),
            ("max", "أعلى حمولة", "#7C3AED"),
            ("deleted", "جرّارات محذوفة", "#DC2626"),
        ):
            row.addWidget(self._stat_tile(key, caption, accent), 1)
        return panel

    def _stat_tile(self, key: str, caption: str, accent: str) -> QFrame:
        tile = QFrame()
        tile.setStyleSheet(
            "QFrame { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; }"
        )
        box = QVBoxLayout(tile)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(0)
        value = QLabel("0")
        value.setStyleSheet(
            f"font-size:20px; font-weight:900; color:{accent}; background:transparent; border:none;"
        )
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setLayoutDirection(Qt.LeftToRight)
        label = QLabel(caption)
        label.setStyleSheet("font-size:11.5px; font-weight:700; color:#64748B; background:transparent; border:none;")
        box.addWidget(value)
        box.addWidget(label)
        self._stat_values[key] = value
        return tile

    # -- the line cards --------------------------------------------------

    def _refresh_lines(self) -> None:
        """Reload the sheet's lines + totals and repaint the cards."""
        lines: list[CubingLine] = []
        if self.current_id is not None:
            try:
                lines = self._backend().lines(self.current_id)
            except Exception:
                lines = []
        self._lines = lines
        self._rebuild_cards()
        self._refresh_totals()
        self._update_lines_state()

    def _rebuild_cards(self) -> None:
        self._filling = True
        try:
            self._line_editors = {}
            self._clear_layout(self._cards_grid)
            editing = self._can_edit_lines()
            for index, line in enumerate(self._lines):
                card = self._make_line_card(line, editing)
                self._cards_grid.addWidget(card, index // _CARDS_PER_ROW, index % _CARDS_PER_ROW)
            # A trailing "add" card, only while the lines are editable.
            if editing:
                pos = len(self._lines)
                self._cards_grid.addWidget(
                    self._make_add_card(), pos // _CARDS_PER_ROW, pos % _CARDS_PER_ROW
                )
            for col in range(_CARDS_PER_ROW):
                self._cards_grid.setColumnStretch(col, 1)
        finally:
            self._filling = False

    @staticmethod
    def _clear_layout(layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_line_card(self, line: CubingLine, editing: bool) -> QFrame:
        card = QFrame()
        border = "#FCA5A5" if line.is_deleted else "#E2E8F0"
        card.setStyleSheet(
            f"QFrame#lc {{ background:#FFFFFF; border:1px solid {border}; border-radius:9px; }}"
        )
        card.setObjectName("lc")
        col = QVBoxLayout(card)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        name = QLabel(line.driver_name or "—")
        name.setStyleSheet("font-size:14px; font-weight:900; color:#111827;")
        top.addWidget(name, 1)
        if line.is_deleted:
            flag = QLabel("محذوف")
            flag.setStyleSheet(
                "font-size:10.5px; font-weight:800; color:#B91C1C; background:#FEE2E2; "
                "border-radius:8px; padding:1px 7px;"
            )
            top.addWidget(flag, 0)
        delete_button = QPushButton("✕")
        delete_button.setFixedSize(24, 24)
        delete_button.setStyleSheet(
            "QPushButton { background:#FFFFFF; color:#B91C1C; border:1px solid #FCA5A5; "
            "border-radius:6px; font-weight:900; }"
            "QPushButton:hover { background:#FEE2E2; }"
            "QPushButton:disabled { color:#E2E8F0; border-color:#F1F5F9; }"
        )
        delete_button.setEnabled(editing and self._perm_delete)
        delete_button.clicked.connect(lambda _c=False, lid=line.line_id: self.delete_line(lid))
        top.addWidget(delete_button, 0)
        col.addLayout(top)

        vol_row = QHBoxLayout()
        vol_row.setSpacing(6)
        vol_caption = QLabel("التكعيب")
        vol_caption.setStyleSheet("font-size:11.5px; font-weight:700; color:#64748B;")
        editor = QLineEdit(_num(line.volume))
        editor.setMinimumHeight(34)
        editor.setLayoutDirection(Qt.LeftToRight)
        editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        editor.setReadOnly(not editing)
        editor.setStyleSheet(
            f"QLineEdit {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:7px; "
            "padding:4px 8px; font-size:15px; font-weight:900; color:#B45309; }"
            "QLineEdit:read-only { background:#F8FAFC; color:#B45309; }"
        )
        editor.editingFinished.connect(lambda lid=line.line_id, e=editor: self._commit_volume(lid, e))
        self._line_editors[line.line_id] = editor
        vol_row.addWidget(vol_caption, 0)
        vol_row.addWidget(editor, 1)
        col.addLayout(vol_row)

        meta = QLabel(self._line_meta(line))
        meta.setStyleSheet("font-size:11px; font-weight:700; color:#94A3B8;")
        col.addWidget(meta)
        return card

    @staticmethod
    def _line_meta(line: CubingLine) -> str:
        parts = []
        if line.trailer_no:
            parts.append(f"وش {line.trailer_no}")
        if line.tractor_id not in (None, ""):
            parts.append(f"جرّار {line.tractor_id}")
        return " · ".join(parts) if parts else "—"

    def _make_add_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("addc")
        card.setStyleSheet(
            "QFrame#addc { background:#F8FAFC; border:1px dashed #93C5FD; border-radius:9px; }"
        )
        col = QVBoxLayout(card)
        col.setContentsMargins(12, 10, 12, 10)
        button = QPushButton("＋ إضافة جرّار")
        button.setMinimumHeight(56)
        button.setStyleSheet(
            "QPushButton { background:transparent; color:#1D4ED8; border:none; font-weight:900; font-size:14px; }"
            "QPushButton:hover { color:#1E40AF; }"
        )
        button.clicked.connect(self.add_line)
        col.addWidget(button)
        return card

    def _refresh_totals(self) -> None:
        totals: CubingTotals
        if self.current_id is not None:
            try:
                totals = self._backend().totals(self.current_id)
            except Exception:
                totals = CubingTotals()
        else:
            totals = CubingTotals()
        self._stat_values["total"].setText(_num(totals.total_volume))
        self._stat_values["count"].setText(str(totals.line_count))
        self._stat_values["average"].setText(_num(totals.average_volume.quantize(Decimal("0.01"))))
        self._stat_values["max"].setText(_num(totals.max_volume))
        self._stat_values["deleted"].setText(str(totals.deleted_count))
        self._lines_count_label.setText(f"({totals.line_count} جرّار)")

    # -- line editing ----------------------------------------------------

    def _can_edit_lines(self) -> bool:
        """Lines are editable only on a saved header while in new/edit mode."""
        return self.mode in {"new", "edit"} and self.current_id is not None

    def _update_lines_state(self) -> None:
        usable = self._can_edit_lines()
        if hasattr(self, "add_line_button"):
            self.add_line_button.setEnabled(usable and self._perm_save)
        if hasattr(self, "_lines_hint"):
            if self.current_id is None:
                self._lines_hint.setText("احفظ رأس الكشف (الكسّارة والتاريخ) أولاً، بعدها تقدر تضيف جرّارات.")
                self._lines_hint.show()
            elif not self._can_edit_lines():
                self._lines_hint.setText("اضغط «تعديل» لإضافة أو تغيير الجرّارات.")
                self._lines_hint.show()
            else:
                self._lines_hint.hide()

    def add_line(self) -> None:
        if not self._can_edit_lines():
            return
        try:
            rows = self._backend().tractor_picker_rows()
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة الجرارات", exc)
            return
        if not rows:
            QMessageBox.information(self, "لا توجد جرارات", "أضِف جرارًا من شاشة الجرارات أولًا.")
            return
        dialog = TawridTractorPickerDialog(rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        try:
            self._backend().add_line(
                self.current_id,
                chosen.get("tractor_id"),
                0,
                driver_name_snapshot=str(chosen.get("driver_name") or ""),
                trailer_no_snapshot=str(chosen.get("head_no") or chosen.get("trailer_no") or ""),
            )
        except Exception as exc:
            self._show_error("تعذّر إضافة الجرّار", exc)
            return
        self._refresh_lines()
        # Focus the new line's volume box so the user types the تكعيب immediately.
        if self._lines:
            editor = self._line_editors.get(self._lines[-1].line_id)
            if editor is not None:
                editor.setFocus()
                editor.selectAll()

    def _commit_volume(self, line_id: Any, editor: QLineEdit) -> None:
        if self._filling or not self._can_edit_lines():
            return
        value = _parse_volume(editor.text())
        if value is None or value < 0:
            QMessageBox.warning(self, "قيمة غير صحيحة", "التكعيب لازم يكون رقمًا موجبًا أو صفرًا.")
            self._refresh_lines()
            return
        try:
            self._backend().update_line_volume(line_id, value)
        except Exception as exc:
            self._show_error("تعذّر حفظ التكعيب", exc)
        # Repaint the total/average without a full rebuild that would steal focus.
        self._reload_line_values()
        self._refresh_totals()

    def _reload_line_values(self) -> None:
        """Refresh the in-memory line list (volumes) without rebuilding widgets."""
        if self.current_id is None:
            return
        try:
            self._lines = self._backend().lines(self.current_id)
        except Exception:
            pass

    def delete_line(self, line_id: Any) -> None:
        if not self._can_edit_lines():
            return
        line = next((l for l in self._lines if str(l.line_id) == str(line_id)), None)
        name = line.driver_name if line else ""
        answer = QMessageBox.question(
            self,
            "تأكيد الحذف",
            f"حذف الجرّار «{name}» من هذا الكشف؟" if name else "حذف هذا السطر من الكشف؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._backend().delete_line(line_id)
        except Exception as exc:
            self._show_error("تعذّر حذف السطر", exc)
            return
        self._refresh_lines()

    # -- crusher picker --------------------------------------------------

    def pick_crusher(self) -> None:
        try:
            rows = self._backend().supplier_picker_rows()
        except Exception as exc:
            self._show_error("تعذّر تحميل قائمة الكسّارات", exc)
            return
        if not rows:
            QMessageBox.information(self, "لا توجد كسّارات", "أضِف كسّارة من شاشة الكسّارات أولًا.")
            return
        dialog = TawridSupplierPickerDialog(rows, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected:
            return
        chosen = dialog.selected
        self._set_editor_value(self.inputs.get("crusher_id"), chosen.get("supplier_id"))
        if self._crusher_label is not None:
            self._crusher_label.setText(str(chosen.get("supplier_name") or ""))

    def _id(self, name: str) -> Any:
        editor = self.inputs.get(name)
        if editor is None:
            return None
        value = self._editor_value(editor)
        return value if value not in (None, "") else None

    def _val(self, name: str) -> Any:
        editor = self.inputs.get(name)
        return self._editor_value(editor) if editor is not None else ""

    # -- navigation + search ---------------------------------------------

    def open_lookup(self) -> None:
        """«بحث عن كشف»: live search dialog, then load the chosen sheet."""
        if self.mode in {"new", "edit"}:
            QMessageBox.information(self, "جاري التعديل", "احفظ الكشف أو ألغِه قبل فتح كشف تاني.")
            return
        dialog = TawridCubingPickerDialog(self._backend().search_cubing, self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_id is None:
            return
        self._load_cubing(dialog.selected_id)

    def _load_cubing(self, cubing_id: Any) -> None:
        try:
            record = self.service.get_record(self.spec, cubing_id)
        except Exception as exc:
            self._show_error("فشل تحميل الكشف", exc)
            return
        if not record:
            return
        self.current_id = cubing_id
        self._fill_form(record)
        self.set_mode("view")
        self._select_row_by_id(cubing_id)

    def _navigate(self, where: str) -> None:
        if self.mode in {"new", "edit"}:
            return
        total = self.table.rowCount()
        if total == 0:
            return
        current = self.table.currentRow()
        if current < 0:
            current = 0
        target = {
            "first": 0,
            "last": total - 1,
            "prev": max(0, current - 1),
            "next": min(total - 1, current + 1),
        }[where]
        if target != current:
            # setCurrentCell, not selectRow: Qt makes selectRow a no-op on a view
            # whose parent is hidden, and this list is hidden by design.
            self.table.setCurrentCell(target, 0)
        self._update_nav_state()

    def _update_nav_state(self) -> None:
        if not hasattr(self, "nav_buttons") or not hasattr(self, "table"):
            return
        browsing = self.mode not in {"new", "edit"}
        total = self.table.rowCount()
        current = self.table.currentRow()
        self.nav_buttons["first"].setEnabled(browsing and current > 0)
        self.nav_buttons["prev"].setEnabled(browsing and current > 0)
        self.nav_buttons["next"].setEnabled(browsing and 0 <= current < total - 1)
        self.nav_buttons["last"].setEnabled(browsing and 0 <= current < total - 1)
        if hasattr(self, "find_button"):
            self.find_button.setEnabled(browsing)

    # -- hooks fired by BaseCrudScreen -----------------------------------

    def set_mode(self, mode: str) -> None:
        super().set_mode(mode)
        editing = mode in {"new", "edit"}
        if hasattr(self, "crusher_pick_button"):
            self.crusher_pick_button.setEnabled(editing)
        # The line cards' editability follows the mode; rebuild so the add-card
        # and the delete/volume controls appear or disappear with it.
        if hasattr(self, "_cards_grid"):
            self._rebuild_cards()
            self._update_lines_state()
        self._update_nav_state()

    def refresh_table(self) -> None:
        super().refresh_table()
        if self.current_id is None and self.table.rowCount():
            self.table.setCurrentCell(0, 0)
        self._update_nav_state()

    def _select_row_by_id(self, record_id: Any) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.data(Qt.UserRole)) == str(record_id):
                self.table.setCurrentCell(row, 0)
                return

    def _fill_form(self, record: dict[str, Any]) -> None:
        self._filling = True
        try:
            for name in ("sheet_no", "sheet_date", "crusher_id", "notes"):
                self._set_editor_value(self.inputs.get(name), record.get(name))

            display = None
            cubing_id = record.get(self.spec.primary_key) or self.current_id
            if cubing_id is not None:
                try:
                    display = self._backend().for_cubing(cubing_id)
                except Exception:
                    display = None
            display = display or record
            if self._crusher_label is not None:
                self._crusher_label.setText(str(display.get("supplier_name") or "— لم تُختَر —"))

            crusher = str(display.get("supplier_name") or "").strip()
            no = record.get("sheet_no")
            self.summary_label.setText(
                f"كشف رقم {no}" + (f" — {crusher}" if crusher else "")
            )
        finally:
            self._filling = False
        self._refresh_lines()

    def _clear_form(self) -> None:
        self._filling = True
        try:
            super()._clear_form()
            if self._crusher_label is not None:
                self._crusher_label.setText("— لم تُختَر —")
        finally:
            self._filling = False
        self._refresh_lines()

    def new_record(self) -> None:
        super().new_record()
        try:
            self._set_editor_value(self.inputs.get("sheet_no"), self._backend().next_sheet_no())
        except Exception:
            pass
        self._set_editor_value(
            self.inputs.get("sheet_date"), datetime.date.today().strftime("%Y-%m-%d")
        )
        self.summary_label.setText("كشف جديد")

    def save_record(self) -> None:
        """Validate the crusher and the sheet number, then save the header."""
        if self._id("crusher_id") is None:
            QMessageBox.warning(self, "ناقص", "اختر الكسّارة قبل حفظ الكشف.")
            return
        sheet_no = str(self._val("sheet_no") or "").strip()
        if not sheet_no:
            QMessageBox.warning(self, "ناقص", "اكتب رقم الكشف.")
            return
        try:
            if self._backend().sheet_no_exists(int(sheet_no), self.current_id):
                QMessageBox.warning(self, "رقم مكرر", f"رقم الكشف {sheet_no} مستخدم في كشف تاني.")
                return
        except (ValueError, TypeError):
            QMessageBox.warning(self, "غير صحيح", "رقم الكشف لازم يكون رقمًا صحيحًا.")
            return
        super().save_record()
        # A brand-new sheet only becomes a valid line parent once saved.
        self._refresh_lines()

    def _cascade_warning(self) -> str | None:
        """Name the lines that go with the sheet, so the delete is informed."""
        if self.current_id is None:
            return None
        try:
            count = self._backend().line_count(self.current_id)
        except Exception:
            return None
        if not count:
            return None
        return f"تنبيه: سيتم أيضًا حذف {count} سطر جرّار في هذا الكشف."
