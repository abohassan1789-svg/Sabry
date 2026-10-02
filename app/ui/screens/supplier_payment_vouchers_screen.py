"""Supplier Payment Vouchers screen (سندات صرف الموردين) — same dashboard as المصروفات.

Layout mirrors :class:`ExpensesScreen` exactly: a 2×2 widgets grid (total card,
top-supplier card, by-supplier bar chart, by-supplier donut) beside the entry
form, with the records list kept hidden and searching done through a popup. The
only structural differences from the expenses screen are:

* رقم السند is fully automatic — a read-only field pre-filled with the next
  ``Paid - Sub-<n>`` preview; the real number is assigned by the database DEFAULT
  on save (see ``ReviewDataService.save_record``).
* اسم المورد is a dropdown of the registered suppliers; the stored value is the
  ``supplier_id`` foreign key, so the dashboard aggregates group by the actual
  supplier.

All business/database logic stays in ``ReviewDataService``.
"""

from __future__ import annotations

import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import FieldSpec, ReviewDataService, TABLE_SPECS
from app.ui.common.report_charts import DashboardBarChart, DashboardDonutChart
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.screens.base_crud_screen import BaseCrudScreen


class SupplierPaymentVouchersScreen(BaseCrudScreen):
    SPEC_KEY = "supplier_payment_vouchers"
    FORM_COLUMNS = 1
    # The charts show only the biggest N suppliers (not all, no "أخرى").
    TOP_SUPPLIERS = 5

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)

    # -- اسم المورد: searchable dropdown of registered suppliers -------------

    def _make_editor(self, field: FieldSpec):
        if field.name == "supplier_id":
            combo = self._make_combo(read_only_edit=False)  # editable → searchable
            combo.setInsertPolicy(QComboBox.NoInsert)
            if combo.completer() is not None:
                combo.completer().setCompletionMode(QCompleter.PopupCompletion)
                combo.completer().setFilterMode(Qt.MatchContains)
            self._supplier_combo = combo
            self._reload_suppliers(combo)
            return combo
        return super()._make_editor(field)

    def _reload_suppliers(self, combo: QComboBox | None = None) -> None:
        combo = combo or getattr(self, "_supplier_combo", None)
        if combo is None:
            return
        current = combo.currentData()
        try:
            suppliers = self.service.list_suppliers_for_selection()
        except Exception:
            suppliers = []
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for row in suppliers:
            name = row.get("supplier_name")
            combo.addItem("" if name in (None, "") else str(name), row.get("supplier_id"))
        combo.blockSignals(False)
        if current is not None:
            self._set_editor_value(combo, current)

    def _editor_value(self, editor: QLineEdit | QComboBox) -> Any:
        # اسم المورد stores the selected supplier_id. Resolve an exactly-typed
        # name back to its id; a blank or unmatched entry yields None (which trips
        # the required-field check, since a voucher must reference a real supplier).
        if editor is getattr(self, "_supplier_combo", None):
            text = editor.currentText().strip()
            if not text:
                return None
            index = editor.findText(text, Qt.MatchFixedString)
            if index >= 0:
                return editor.itemData(index)
            return editor.currentData()
        return super()._editor_value(editor)

    # -- Model 10 dashboard (cards + interactive charts) --------------------

    def _build_content(self):
        outer = QVBoxLayout()
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self._build_dashboard(), 2)
        top.addWidget(self._build_form_panel(), 1)
        outer.addLayout(top, 1)

        # No visible list under the form — searching happens in a popup dialog.
        # The base CRUD flow still expects self.table/search_text/count_label, so
        # the panel is built but kept hidden.
        self._hidden_list = self._build_list_panel()
        self._hidden_list.setVisible(False)
        outer.addWidget(self._hidden_list)
        return outer

    # -- search popup -------------------------------------------------------

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        self.search_button = QPushButton("بحث")
        self.search_button.setFixedHeight(38)
        self.search_button.setMinimumWidth(110)
        self.search_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.search_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
        self.search_button.clicked.connect(self.open_voucher_search)
        layout.addWidget(self.search_button)

    def open_voucher_search(self) -> None:
        """Open the voucher search popup; the chosen row loads into the form."""
        from app.ui.dialogs.supplier_voucher_search_dialog import SupplierVoucherSearchDialog

        dialog = SupplierVoucherSearchDialog(self.service, self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_id is None:
            return
        record = self.service.get_record(self.spec, dialog.selected_id)
        if not record:
            QMessageBox.information(self, "بحث السندات", "تعذر تحميل السند المحدد.")
            return
        self.current_id = dialog.selected_id
        self._fill_form(record)
        self.set_mode("view")
        self._select_row_by_id(self.current_id)

    def _build_form_panel(self):
        # Lift the base 245px cap so every stacked field shows without scrolling
        # — the panel just grows to match the dashboard height beside it.
        scroll = super()._build_form_panel()
        scroll.setMinimumHeight(260)
        scroll.setMaximumHeight(16777215)
        return scroll

    def _build_dashboard(self) -> QWidget:
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        total_card, self.kpi_total_value, _ = self._make_kpi_card("إجمالي السندات", filled=True)
        top_card, self.kpi_top_value, self.kpi_top_sub = self._make_kpi_card(
            "أعلى مورد صرفت عليه", with_sub=True
        )
        grid.addWidget(total_card, 0, 0)
        grid.addWidget(top_card, 0, 1)

        # max_bars = TOP_SUPPLIERS + 1: the shared widget shows the biggest
        # TOP_SUPPLIERS suppliers individually and rolls the rest into "أخرى".
        self.bar_chart = DashboardBarChart(
            f"أكبر {self.TOP_SUPPLIERS} موردين + أخرى", "supplier_name", GREEN,
            max_bars=self.TOP_SUPPLIERS + 1, min_height=190,
        )
        self.donut_chart = DashboardDonutChart(
            f"توزيع أكبر {self.TOP_SUPPLIERS} + أخرى", "supplier_name", GREEN,
            max_bars=self.TOP_SUPPLIERS + 1, min_height=190,
        )
        grid.addWidget(self.bar_chart, 1, 0)
        grid.addWidget(self.donut_chart, 1, 1)
        return panel

    def _make_kpi_card(self, caption: str, filled: bool = False, with_sub: bool = False):
        card = QFrame()
        if filled:
            card.setStyleSheet("QFrame { background:#166534; border-radius:12px; }")
            cap_color, val_color, sub_color = "#CFEAD9", "#FFFFFF", "#CFEAD9"
        else:
            card.setStyleSheet(f"QFrame {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:12px; }}")
            cap_color, val_color, sub_color = "#64748B", TEXT, "#3B6D11"
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)
        cap = QLabel(caption)
        cap.setStyleSheet(f"background:transparent; color:{cap_color}; font-size:12px; font-weight:900;")
        value = QLabel("—")
        value.setStyleSheet(f"background:transparent; color:{val_color}; font-size:22px; font-weight:900;")
        layout.addWidget(cap)
        layout.addWidget(value)
        sub: QLabel | None = None
        if with_sub:
            sub = QLabel("")
            sub.setStyleSheet(f"background:transparent; color:{sub_color}; font-size:12px; font-weight:900;")
            layout.addWidget(sub)
        layout.addStretch(1)
        return card, value, sub

    def _refresh_dashboard(self) -> None:
        try:
            total = self.service.supplier_vouchers_total()
        except Exception:
            total = 0
        self.kpi_total_value.setText(self._money(total))

        try:
            rows = [dict(r) for r in self.service.supplier_vouchers_by_supplier()]
        except Exception:
            rows = []
        if rows:
            top = rows[0]
            self.kpi_top_value.setText(str(top.get("supplier_name") or "—"))
            self.kpi_top_sub.setText(self._money(top.get("total")))
        else:
            self.kpi_top_value.setText("—")
            self.kpi_top_sub.setText("لا توجد سندات")

        # Pass ALL suppliers; the charts keep the biggest TOP_SUPPLIERS and roll
        # the rest into an "أخرى" bucket (via their max_bars).
        self.bar_chart.set_data(None, rows, label_key="supplier_name", value_key="total")
        self.donut_chart.set_data(None, rows, label_key="supplier_name", value_key="total")
        # The shared donut widget hardcodes an unrelated summary tail; replace it
        # with the real total across all suppliers.
        try:
            full_total = sum(int(r.get("total") or 0) for r in rows)
            self.donut_chart._summary.setText(f"الإجمالي: {full_total:,}")
        except Exception:
            pass

    @staticmethod
    def _money(value: Any) -> str:
        try:
            return f"{float(value or 0):,.2f}"
        except (TypeError, ValueError):
            return "0.00"

    # -- refresh + new-record wiring ----------------------------------------

    def refresh_table(self) -> None:
        super().refresh_table()
        if hasattr(self, "kpi_total_value"):
            self._refresh_dashboard()

    def refresh_screen(self) -> None:
        self._reload_suppliers()
        super().refresh_screen()

    def new_record(self) -> None:
        # Refresh the supplier list first so a supplier added moments ago is
        # already offered in the dropdown.
        self._reload_suppliers()
        super().new_record()
        today = datetime.date.today().strftime("%Y-%m-%d")
        self._set_editor_value(self.inputs.get("voucher_date"), today)
        # Show the next automatic voucher number as a read-only preview. The real
        # number is assigned atomically by the DB DEFAULT on save.
        try:
            preview = self.service.peek_next_supplier_voucher_number()
        except Exception:
            preview = ""
        self._set_editor_value(self.inputs.get("voucher_number"), preview)
