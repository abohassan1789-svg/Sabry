"""Treasury Deposits screen (إضافة أموال للخزينة) — expenses-style dashboard.

Money added INTO the treasury/cashbox. The layout follows the expenses family
exactly — a KPI card row plus charts beside the entry form, with the records list
hidden and searching done through a popup. What is specific to this screen:

* رقم الحركة is an automatic read-only number (the sequence-assigned id, starting
  at 3001), shown with a preview on a new record.
* The dashboard groups by **month**, not by type:
    - إجمالي المبلغ           — SUM of every deposit.
    - أعلى تاريخ دخل فيه مبلغ  — the single date whose deposits sum highest.
    - أعلى ٥ شهور             — the biggest months by total (bar + donut charts).

All business/database logic stays in ``ReviewDataService``.
"""

from __future__ import annotations

import datetime
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.ui.common.report_charts import DashboardBarChart, DashboardDonutChart
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.screens.base_crud_screen import BaseCrudScreen


class TreasuryDepositsScreen(BaseCrudScreen):
    SPEC_KEY = "treasury_deposits"
    FORM_COLUMNS = 1
    # The charts show only the biggest N months (the rest roll into "أخرى").
    TOP_MONTHS = 5

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)

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
        self.search_button.clicked.connect(self.open_treasury_search)
        layout.addWidget(self.search_button)

    def open_treasury_search(self) -> None:
        """Open the treasury search popup; the chosen row loads into the form."""
        from app.ui.dialogs.treasury_search_dialog import TreasurySearchDialog

        dialog = TreasurySearchDialog(self.service, self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_id is None:
            return
        record = self.service.get_record(self.spec, dialog.selected_id)
        if not record:
            QMessageBox.information(self, "بحث الحركات", "تعذر تحميل الحركة المحددة.")
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

        total_card, self.kpi_total_value, _ = self._make_kpi_card("إجمالي المبلغ", filled=True)
        top_card, self.kpi_top_value, self.kpi_top_sub = self._make_kpi_card(
            "أعلى تاريخ دخل فيه مبلغ", with_sub=True
        )
        grid.addWidget(total_card, 0, 0)
        grid.addWidget(top_card, 0, 1)

        # max_bars = TOP_MONTHS + 1: the shared widget shows the biggest TOP_MONTHS
        # months individually and rolls everything else into an "أخرى" bucket.
        self.bar_chart = DashboardBarChart(
            f"أعلى {self.TOP_MONTHS} شهور + أخرى", "month", GREEN,
            max_bars=self.TOP_MONTHS + 1, min_height=190,
        )
        self.donut_chart = DashboardDonutChart(
            f"توزيع أعلى {self.TOP_MONTHS} شهور + أخرى", "month", GREEN,
            max_bars=self.TOP_MONTHS + 1, min_height=190,
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
            total = self.service.treasury_total()
        except Exception:
            total = 0
        self.kpi_total_value.setText(self._money(total))

        try:
            top = self.service.treasury_top_date()
        except Exception:
            top = None
        if top:
            self.kpi_top_value.setText(str(top.get("movement_date") or "—"))
            self.kpi_top_sub.setText(self._money(top.get("total")))
        else:
            self.kpi_top_value.setText("—")
            self.kpi_top_sub.setText("لا توجد حركات")

        try:
            rows = [dict(r) for r in self.service.treasury_by_month()]
        except Exception:
            rows = []
        # Pass ALL months; the charts keep the biggest TOP_MONTHS and roll the rest
        # into an "أخرى" bucket (via their max_bars).
        self.bar_chart.set_data(None, rows, label_key="month", value_key="total")
        self.donut_chart.set_data(None, rows, label_key="month", value_key="total")
        # The shared donut widget hardcodes an unrelated summary tail; replace it
        # with the real total across all months.
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

    def new_record(self) -> None:
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
