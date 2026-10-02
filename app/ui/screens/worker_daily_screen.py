"""Worker Daily screen (يومية العمال) — expenses-style dashboard for workers.

A daily wage sheet: one row per worker per day. The layout follows the expenses
/ supplier-voucher family — a KPI card row plus by-worker charts beside the entry
form, with the records list hidden and searching done through a popup. What is
specific to this screen:

* Three KPI cards instead of two: إجمالي الراتب اليومي / إجمالي النقديات /
  إجمالي الرصيد.
* Two **live** read-only formula fields, updated as the user types (same idea as
  the الإجمالي preview on the products screen). The authoritative values are the
  database generated columns:
    - الراتب اليومي = عدد الأيام × أجر اليوم
    - الرصيد        = الراتب اليومي − النقديات
* اسم العامل is a searchable dropdown of the registered workers; the stored value
  is the worker_id foreign key, so the top-workers chart groups by the real worker.
* رقم الحركة is an automatic read-only number (the sequence-assigned id), shown
  with a preview on a new record.

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


class WorkerDailyScreen(BaseCrudScreen):
    SPEC_KEY = "worker_daily"
    FORM_COLUMNS = 1
    # The chart shows only the biggest N workers (not all, no "أخرى").
    TOP_WORKERS = 5

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)
        # Keep the two formula previews in sync as the inputs change.
        for name in ("number_of_days", "daily_wage", "cash"):
            editor = self.inputs.get(name)
            if isinstance(editor, QLineEdit):
                editor.textChanged.connect(self._recompute_formulas)
        self._recompute_formulas()

    # -- اسم العامل: searchable dropdown of registered workers --------------

    def _make_editor(self, field: FieldSpec):
        if field.name == "worker_id":
            combo = self._make_combo(read_only_edit=False)  # editable → searchable
            combo.setInsertPolicy(QComboBox.NoInsert)
            if combo.completer() is not None:
                combo.completer().setCompletionMode(QCompleter.PopupCompletion)
                combo.completer().setFilterMode(Qt.MatchContains)
            self._worker_combo = combo
            self._reload_workers(combo)
            return combo
        return super()._make_editor(field)

    def _reload_workers(self, combo: QComboBox | None = None) -> None:
        combo = combo or getattr(self, "_worker_combo", None)
        if combo is None:
            return
        current = combo.currentData()
        try:
            workers = self.service.list_workers_for_selection()
        except Exception:
            workers = []
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for row in workers:
            name = row.get("worker_name")
            combo.addItem("" if name in (None, "") else str(name), row.get("worker_id"))
        combo.blockSignals(False)
        if current is not None:
            self._set_editor_value(combo, current)

    def _editor_value(self, editor: QLineEdit | QComboBox) -> Any:
        # اسم العامل stores the selected worker_id. Resolve an exactly-typed name
        # back to its id; a blank or unmatched entry yields None (trips the
        # required-field check — an entry must reference a real worker).
        if editor is getattr(self, "_worker_combo", None):
            text = editor.currentText().strip()
            if not text:
                return None
            index = editor.findText(text, Qt.MatchFixedString)
            if index >= 0:
                return editor.itemData(index)
            return editor.currentData()
        return super()._editor_value(editor)

    # -- live formula previews (الراتب اليومي / الرصيد) ---------------------

    @staticmethod
    def _to_number(text: str) -> float | None:
        text = (text or "").strip()
        if text == "":
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _recompute_formulas(self) -> None:
        days = self._to_number(self.inputs["number_of_days"].text()) if "number_of_days" in self.inputs else None
        wage = self._to_number(self.inputs["daily_wage"].text()) if "daily_wage" in self.inputs else None
        cash = self._to_number(self.inputs["cash"].text()) if "cash" in self.inputs else None

        salary_editor = self.inputs.get("daily_salary")
        balance_editor = self.inputs.get("balance")
        # الراتب اليومي = عدد الأيام × أجر اليوم (blank until both are numbers).
        salary: float | None = None
        if days is not None and wage is not None:
            salary = days * wage
        if isinstance(salary_editor, QLineEdit):
            salary_editor.setText("" if salary is None else f"{salary:.2f}")
        # الرصيد = الراتب اليومي − النقديات (treat a blank cash as 0 once a salary
        # exists, so the balance still shows the full salary before any نقديات).
        if isinstance(balance_editor, QLineEdit):
            if salary is None:
                balance_editor.setText("")
            else:
                balance_editor.setText(f"{salary - (cash or 0):.2f}")

    def _fill_form(self, record: dict) -> None:  # type: ignore[override]
        super()._fill_form(record)
        # daily_salary / balance are virtual (not returned by get_record); refresh
        # the previews from the loaded days / wage / cash.
        self._recompute_formulas()

    # -- dashboard (3 cards + by-worker charts) -----------------------------

    def _build_content(self):
        outer = QVBoxLayout()
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self._build_dashboard(), 2)
        top.addWidget(self._build_form_panel(), 1)
        outer.addLayout(top, 1)

        self._hidden_list = self._build_list_panel()
        self._hidden_list.setVisible(False)
        outer.addWidget(self._hidden_list)
        return outer

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        self.search_button = QPushButton("بحث")
        self.search_button.setFixedHeight(38)
        self.search_button.setMinimumWidth(110)
        self.search_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.search_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
        self.search_button.clicked.connect(self.open_worker_daily_search)
        layout.addWidget(self.search_button)

    def open_worker_daily_search(self) -> None:
        """Open the worker-daily search popup; the chosen row loads into the form."""
        from app.ui.dialogs.worker_daily_search_dialog import WorkerDailySearchDialog

        dialog = WorkerDailySearchDialog(self.service, self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_id is None:
            return
        record = self.service.get_record(self.spec, dialog.selected_id)
        if not record:
            QMessageBox.information(self, "بحث يومية العمال", "تعذر تحميل الحركة المحددة.")
            return
        self.current_id = dialog.selected_id
        self._fill_form(record)
        self.set_mode("view")
        self._select_row_by_id(self.current_id)

    def _build_form_panel(self):
        # Lift the base 245px cap so all nine stacked fields show without a
        # scrollbar — the panel grows to match the dashboard height beside it.
        scroll = super()._build_form_panel()
        scroll.setMinimumHeight(300)
        scroll.setMaximumHeight(16777215)
        return scroll

    def _build_dashboard(self) -> QWidget:
        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        salary_card, self.kpi_salary_value, _ = self._make_kpi_card("إجمالي الراتب اليومي", filled=True)
        cash_card, self.kpi_cash_value, _ = self._make_kpi_card("إجمالي النقديات")
        balance_card, self.kpi_balance_value, _ = self._make_kpi_card("إجمالي الرصيد")
        cards.addWidget(salary_card)
        cards.addWidget(cash_card)
        cards.addWidget(balance_card)
        outer.addLayout(cards)

        charts = QHBoxLayout()
        charts.setSpacing(10)
        # max_bars = TOP_WORKERS + 1: the shared widget shows the biggest
        # TOP_WORKERS workers individually and rolls the rest into "أخرى".
        self.bar_chart = DashboardBarChart(
            f"أعلى {self.TOP_WORKERS} عمال (رواتب)", "worker_name", GREEN,
            max_bars=self.TOP_WORKERS + 1, min_height=200,
        )
        self.donut_chart = DashboardDonutChart(
            f"توزيع أعلى {self.TOP_WORKERS} + أخرى", "worker_name", GREEN,
            max_bars=self.TOP_WORKERS + 1, min_height=200,
        )
        charts.addWidget(self.bar_chart)
        charts.addWidget(self.donut_chart)
        outer.addLayout(charts, 1)
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
        for method, label_widget in (
            ("worker_daily_total_salary", "kpi_salary_value"),
            ("worker_daily_total_cash", "kpi_cash_value"),
            ("worker_daily_total_balance", "kpi_balance_value"),
        ):
            try:
                total = getattr(self.service, method)()
            except Exception:
                total = 0
            getattr(self, label_widget).setText(self._money(total))

        try:
            rows = [dict(r) for r in self.service.worker_daily_by_worker()]
        except Exception:
            rows = []
        self.bar_chart.set_data(None, rows, label_key="worker_name", value_key="total")
        self.donut_chart.set_data(None, rows, label_key="worker_name", value_key="total")
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
        if hasattr(self, "kpi_salary_value"):
            self._refresh_dashboard()

    def refresh_screen(self) -> None:
        self._reload_workers()
        super().refresh_screen()

    def new_record(self) -> None:
        self._reload_workers()
        super().new_record()
        today = datetime.date.today().strftime("%Y-%m-%d")
        self._set_editor_value(self.inputs.get("movement_date"), today)
        # Preview the upcoming رقم الحركة (the real id is assigned atomically on
        # save via the sequence RETURNING; this is display-only).
        try:
            next_id = self.service.next_id(self.spec)
            self._set_editor_value(self.inputs.get("id"), next_id)
        except Exception:
            pass
        self._recompute_formulas()

    # -- validation before save ---------------------------------------------

    def save_record(self) -> None:  # type: ignore[override]
        # number_of_days / daily_wage / cash are NOT NULL (default 0): a blank
        # editor would be sent as NULL and rejected. Default a blank to "0" so an
        # entry with only some values still saves (same idea as the products screen).
        for name in ("number_of_days", "daily_wage", "cash"):
            editor = self.inputs.get(name)
            if isinstance(editor, QLineEdit) and editor.text().strip() == "":
                editor.setText("0")
        super().save_record()
