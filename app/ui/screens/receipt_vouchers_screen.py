"""Receipt Vouchers screen (سندات قبض العملاء) — same dashboard as المصروفات.

Money RECEIVED from a customer. The screen deliberately mirrors
:class:`SupplierPaymentVouchersScreen` exactly — a 2×2 widgets grid (total card,
top-customer card, by-customer bar chart, by-customer donut) beside a five-field
entry form (رقم السند / التاريخ / اسم العميل / المبلغ / البيان), with the records
list hidden and searching done through a popup. The one extra it keeps over the
supplier screen is the **طباعة سند** (print voucher) button.

Notes:

* ``رقم السند`` is fully automatic — a read-only field pre-filled with the next
  ``PA-<n>`` preview; the real number is assigned by the database DEFAULT on save
  (see ``ReviewDataService.save_record``).
* ``اسم العميل`` is a searchable dropdown of the registered customers; the stored
  value is the ``customer_id`` foreign key, so the dashboard aggregates group by
  the actual customer.
* ``الشركة`` / ``نوع الدفع`` are no longer collected on this screen (their columns
  stay in the table as optional, so old data and the printout are unaffected).

All business/database logic stays in ``ReviewDataService``.
"""

from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
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

from app.services.receipt_voucher_numbering_service import ReceiptVoucherNumberingService
from app.services.review_data_service import FieldSpec, ReviewDataService, TABLE_SPECS
from app.ui.common.report_charts import DashboardBarChart, DashboardDonutChart
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.screens.base_crud_screen import BaseCrudScreen


class ReceiptVouchersScreen(BaseCrudScreen):
    SPEC_KEY = "receipt_vouchers"
    FORM_COLUMNS = 1
    # The charts show only the biggest N customers (not all, no "أخرى").
    TOP_CUSTOMERS = 5

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)

    # -- اسم العميل: searchable dropdown of registered customers ------------

    def _make_editor(self, field: FieldSpec):
        if field.name == "customer_id":
            combo = self._make_combo(read_only_edit=False)  # editable → searchable
            combo.setInsertPolicy(QComboBox.NoInsert)
            if combo.completer() is not None:
                combo.completer().setCompletionMode(QCompleter.PopupCompletion)
                combo.completer().setFilterMode(Qt.MatchContains)
            # Kept under the historical name too, so the print helper can read it.
            self._customer_combo = combo
            self.voucher_customer_combo = combo
            self._reload_customers(combo)
            return combo
        return super()._make_editor(field)

    def _reload_customers(self, combo: QComboBox | None = None) -> None:
        combo = combo or getattr(self, "_customer_combo", None)
        if combo is None:
            return
        current = combo.currentData()
        try:
            customers = self.service.list_customers_for_selection()
        except Exception:
            customers = []
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for row in customers:
            name = row.get("customer_name")
            combo.addItem("" if name in (None, "") else str(name), row.get("customer_id"))
        combo.blockSignals(False)
        if current is not None:
            self._set_editor_value(combo, current)

    def _editor_value(self, editor: QLineEdit | QComboBox) -> Any:
        # اسم العميل stores the selected customer_id. Resolve an exactly-typed name
        # back to its id; a blank or unmatched entry yields None (trips the
        # required-field check — a voucher must reference a real customer).
        if editor is getattr(self, "_customer_combo", None):
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

    # -- toolbar extras: search popup + print voucher -----------------------

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        self.search_button = QPushButton("بحث")
        self.search_button.setFixedHeight(38)
        self.search_button.setMinimumWidth(110)
        self.search_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.search_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
        self.search_button.clicked.connect(self.open_voucher_search)
        layout.addWidget(self.search_button)

        # Kept from the previous design: preview / print the current voucher using
        # the same flow as the sales-invoice receipt-voucher printout.
        self.print_voucher_button = QPushButton("طباعة سند")
        self.print_voucher_button.setFixedHeight(38)
        self.print_voucher_button.setStyleSheet(_button_style("#4338CA", "#3730A3"))
        self.print_voucher_button.clicked.connect(self.print_voucher)
        layout.addWidget(self.print_voucher_button)

    def open_voucher_search(self) -> None:
        """Open the receipt-voucher search popup; the chosen row loads into the form."""
        from app.ui.dialogs.receipt_voucher_search_dialog import ReceiptVoucherSearchDialog

        dialog = ReceiptVoucherSearchDialog(self.service, self)
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

    # -- print voucher (طباعة سند) ------------------------------------------

    def print_voucher(self) -> None:
        data = self._collect_voucher_print_data()
        if data is None:
            QMessageBox.information(
                self, "طباعة سند", "اختر سنداً من القائمة أو أدخل بياناته أولاً."
            )
            return
        from app.ui.screens.saudi_receipt_voucher_print import (
            SaudiReceiptVoucherPreviewDialog,
            choose_voucher_builder,
        )

        builder = choose_voucher_builder(self)
        if builder is None:
            return
        dialog = SaudiReceiptVoucherPreviewDialog(data, parent=self, html_builder=builder)
        dialog.exec()

    def _collect_voucher_print_data(self) -> dict[str, Any] | None:
        """Reshape the on-screen voucher into the receipt-voucher print template.

        Reads the currently displayed voucher straight from the form editors so a
        selected (saved) voucher prints exactly as shown. The company (seller)
        header and نوع الدفع are no longer captured on this screen, so they print
        empty — the number / date / customer / amount / purpose are what remain.
        """
        def _text(name: str) -> str:
            editor = self.inputs.get(name)
            return editor.text().strip() if editor is not None and hasattr(editor, "text") else ""

        number = _text("voucher_number")
        date_text = _text("voucher_date")
        purpose = _text("description")
        amount_text = _text("amount")

        customer_combo = getattr(self, "voucher_customer_combo", None)
        received_from = customer_combo.currentText().strip() if customer_combo is not None else ""

        # Fresh, empty screen with nothing selected — nothing to print.
        if self.current_id is None and not (received_from or amount_text):
            return None

        # No company/payment inputs on this screen anymore: seller header is blank.
        seller = {"name": "", "name_en": "", "cr": "", "vat": "", "address": "", "address_en": ""}

        # The date editor holds YYYY-MM-DD text; hand the template a real date so
        # it renders dd-mm-yyyy (falls back to the raw text if not parseable).
        issue_date: Any = date_text
        try:
            issue_date = datetime.datetime.strptime(date_text, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass

        try:
            amount: Any = Decimal(amount_text)
        except (InvalidOperation, ValueError, TypeError):
            amount = Decimal("0")

        return {
            "number": number,
            "issue_date": issue_date,
            "amount": amount,
            "received_from": received_from,
            "purpose": purpose,
            "payment_type": "",
            "seller": seller,
        }

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
            "أعلى عميل قبضت منه", with_sub=True
        )
        grid.addWidget(total_card, 0, 0)
        grid.addWidget(top_card, 0, 1)

        # max_bars = TOP_CUSTOMERS + 1: the shared widget shows the biggest
        # TOP_CUSTOMERS customers individually and rolls the rest into "أخرى".
        self.bar_chart = DashboardBarChart(
            f"أكبر {self.TOP_CUSTOMERS} عملاء + أخرى", "customer_name", GREEN,
            max_bars=self.TOP_CUSTOMERS + 1, min_height=190,
        )
        self.donut_chart = DashboardDonutChart(
            f"توزيع أكبر {self.TOP_CUSTOMERS} + أخرى", "customer_name", GREEN,
            max_bars=self.TOP_CUSTOMERS + 1, min_height=190,
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
            total = self.service.receipt_vouchers_total()
        except Exception:
            total = 0
        self.kpi_total_value.setText(self._money(total))

        try:
            rows = [dict(r) for r in self.service.receipt_vouchers_by_customer()]
        except Exception:
            rows = []
        if rows:
            top = rows[0]
            self.kpi_top_value.setText(str(top.get("customer_name") or "—"))
            self.kpi_top_sub.setText(self._money(top.get("total")))
        else:
            self.kpi_top_value.setText("—")
            self.kpi_top_sub.setText("لا توجد سندات")

        # Pass ALL customers; the charts keep the biggest TOP_CUSTOMERS and roll
        # the rest into an "أخرى" bucket (via their max_bars).
        self.bar_chart.set_data(None, rows, label_key="customer_name", value_key="total")
        self.donut_chart.set_data(None, rows, label_key="customer_name", value_key="total")
        # The shared donut widget hardcodes an unrelated summary tail; replace it
        # with the real total across all customers.
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
        self._reload_customers()
        super().refresh_screen()

    def new_record(self) -> None:
        # Refresh the customer list first so a customer added moments ago is
        # already offered in the dropdown.
        self._reload_customers()
        super().new_record()
        today = datetime.date.today().strftime("%Y-%m-%d")
        self._set_editor_value(self.inputs.get("voucher_date"), today)
        # Show the next automatic voucher number as a read-only preview. The real
        # number is assigned atomically by the DB DEFAULT on save.
        try:
            preview = ReceiptVoucherNumberingService().peek_next_number()
        except Exception:
            preview = ""
        self._set_editor_value(self.inputs.get("voucher_number"), preview)
