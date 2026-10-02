"""Customers module screen (إدارة العملاء).

UI only: it reuses :class:`BaseCrudScreen` bound to the ``customers`` table
spec. Business/database logic stays in ``ReviewDataService``.

Layout is "Model 7": two KPI cards on top (عدد العملاء + أعلى عميل مبيعات),
then the single-column data form beside the search list. The customer code is
shown as ``CUS-<id>`` for display only — the stored primary key stays the plain
integer, so every existing link (daily follow-ups, invoices, ...) is untouched.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.services import whatsapp_service
from app.services.review_data_service import FieldSpec, ReviewDataService, TABLE_SPECS
from app.ui.common.theme import GREEN, GREEN_DARK, TEXT, _button_style
from app.ui.screens.base_crud_screen import BaseCrudScreen


class CustomersScreen(BaseCrudScreen):
    SPEC_KEY = "customers"
    AUTO_SEND_DELAY_MS = 25_000
    # Model 7: each of the five fields sits on its own row.
    FORM_COLUMNS = 1

    def __init__(self, service: ReviewDataService, parent: QWidget | None = None) -> None:
        super().__init__(service, TABLE_SPECS[self.SPEC_KEY], parent)

    # -- display formatting -------------------------------------------------

    def _display_value(self, field_name: str, value: Any) -> Any:
        """Show the customer code as ``CUS-1001`` (display only)."""
        if field_name == "customer_id" and value not in (None, ""):
            return f"CUS-{value}"
        return value

    # -- top KPI cards ------------------------------------------------------

    def _build_content(self):
        outer = QVBoxLayout()
        outer.setSpacing(10)
        outer.addWidget(self._build_kpi_cards())
        outer.addLayout(super()._build_content(), 1)
        return outer

    def _build_kpi_cards(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet("QFrame { background:transparent; }")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        count_card, self.kpi_count_value, _sub = self._make_kpi_card("ع", "عدد العملاء")
        top_card, self.kpi_top_value, self.kpi_top_sub = self._make_kpi_card(
            "★", "أعلى عميل مبيعات", with_sub=True
        )
        row.addWidget(count_card, 1)
        row.addWidget(top_card, 1)
        return bar

    def _make_kpi_card(
        self, icon_text: str, caption: str, with_sub: bool = False
    ) -> tuple[QFrame, QLabel, QLabel | None]:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:#FFFFFF; border:1px solid {GREEN}; border-radius:12px; }}"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        icon = QLabel(icon_text)
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background:#EAF3DE; color:#166534; border-radius:10px; "
            "font-size:20px; font-weight:900;"
        )
        layout.addWidget(icon)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        cap = QLabel(caption)
        cap.setStyleSheet("color:#64748B; font-size:12px; font-weight:900;")
        value = QLabel("—")
        value.setStyleSheet(f"color:{TEXT}; font-size:20px; font-weight:900;")
        text_box.addWidget(cap)
        text_box.addWidget(value)
        sub: QLabel | None = None
        if with_sub:
            sub = QLabel("")
            sub.setStyleSheet("color:#3B6D11; font-size:12px; font-weight:900;")
            text_box.addWidget(sub)
        layout.addLayout(text_box, 1)
        return card, value, sub

    def _refresh_kpis(self) -> None:
        try:
            count = self.service.count_customers()
        except Exception:
            count = None
        self.kpi_count_value.setText("—" if count is None else str(count))

        try:
            top = self.service.top_customer_by_sales()
        except Exception:
            top = None
        if top and top.get("customer_id") is not None:
            name = top.get("customer_name") or f"CUS-{top.get('customer_id')}"
            self.kpi_top_value.setText(str(name))
            try:
                total = float(top.get("total_sales") or 0)
            except (TypeError, ValueError):
                total = 0.0
            self.kpi_top_sub.setText(f"{total:,.2f}")
        else:
            self.kpi_top_value.setText("—")
            self.kpi_top_sub.setText("لا توجد مبيعات")

    def refresh_table(self) -> None:
        super().refresh_table()
        # The cards are built during _build_ui, so they exist by the time the
        # base constructor first calls refresh_table; guard anyway for safety.
        if hasattr(self, "kpi_count_value"):
            self._refresh_kpis()

    def new_record(self) -> None:
        super().new_record()
        editor = self.inputs.get("opening_balance")
        if editor is not None:
            editor.setText("0.00")

    # -- search button ------------------------------------------------------

    def _install_extra_toolbar_buttons(self, layout: QHBoxLayout) -> None:
        self.search_button = QPushButton("بحث")
        self.search_button.setFixedHeight(38)
        self.search_button.setMinimumWidth(110)
        self.search_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.search_button.setStyleSheet(_button_style(GREEN, GREEN_DARK))
        self.search_button.clicked.connect(self.open_customer_search)
        layout.addWidget(self.search_button)

    def open_customer_search(self) -> None:
        """Open the customer picker; the chosen customer loads into the form.

        Search any part of the name/phone, pick a customer (double-click, Enter,
        or the Select button), and it is loaded read-only into the background
        form — ready to view, then edit via the "تعديل" button.
        """
        from app.ui.dialogs.customer_lookup_dialog import CustomerLookupDialog

        dialog = CustomerLookupDialog(self.service, self)
        if dialog.exec() != QDialog.Accepted or dialog.selected_customer_id is None:
            return
        record = self.service.get_record(self.spec, dialog.selected_customer_id)
        if not record:
            QMessageBox.information(self, "بحث العملاء", "تعذر تحميل بيانات العميل المحدد.")
            return
        self.current_id = dialog.selected_customer_id
        self._fill_form(record)
        self.set_mode("view")
        self._select_row_by_id(self.current_id)

    # -- data-entry group (WhatsApp / attachments buttons) ------------------

    def _build_field_group(self, title: str, fields: list[FieldSpec]) -> QGroupBox:
        box = super()._build_field_group(title, fields)
        grid = box.layout()

        # The WhatsApp and Attachments buttons are kept (so their behaviour and
        # references stay intact) but hidden from the customer form per request.
        # Hidden widgets take no layout space, so the form stays clean.
        self.whatsapp_button = QPushButton("WhatsApp")
        self.whatsapp_button.setFixedHeight(38)
        self.whatsapp_button.setMinimumWidth(150)
        self.whatsapp_button.setStyleSheet(
            "QPushButton { background:#25D366; color:#FFFFFF; border:none; "
            "border-radius:6px; padding:7px 16px; font-weight:900; }"
            "QPushButton:hover { background:#1EBE5D; }"
        )
        self.whatsapp_button.clicked.connect(self._open_whatsapp)
        grid.addWidget(self.whatsapp_button, grid.rowCount(), 0, 1, 4, Qt.AlignRight)
        self.whatsapp_button.setVisible(False)

        self.attachments_button = QPushButton("المرفقات")
        self.attachments_button.setFixedHeight(38)
        self.attachments_button.setMinimumWidth(150)
        self.attachments_button.setStyleSheet(
            "QPushButton { background:#0891B2; color:#FFFFFF; border:none; "
            "border-radius:6px; padding:7px 16px; font-weight:900; }"
            "QPushButton:hover { background:#0E7490; }"
        )
        self.attachments_button.clicked.connect(self._open_attachments)
        grid.addWidget(self.attachments_button, grid.rowCount(), 0, 1, 4, Qt.AlignRight)
        self.attachments_button.setVisible(False)
        return box

    def _open_attachments(self) -> None:
        """Open the Attachments screen pre-filtered to the selected customer."""
        if self.current_id is None:
            QMessageBox.information(self, "المرفقات", "اختر عميلاً أولاً لعرض مرفقاته.")
            return
        try:
            from app.ui.screens.attachments_page import AttachmentsPage

            window = AttachmentsPage(entity_type="Customer", entity_id=int(self.current_id))
            window.setWindowTitle(f"KSA - مرفقات العميل {self.current_id}")
            window.setLayoutDirection(Qt.RightToLeft)
            # Keep a reference so the window is not garbage-collected.
            self._attachments_window = window
            window.showMaximized()
            window.raise_()
            window.activateWindow()
        except Exception as exc:  # never break the customer screen
            QMessageBox.critical(self, "تعذر فتح المرفقات", str(exc))

    def _open_whatsapp(self) -> None:
        phone = self.inputs["phone_number"].text()
        if not phone.strip():
            self._show_whatsapp_warning("يرجى إدخال رقم الهاتف أولاً.")
            return
        try:
            whatsapp_service.open_whatsapp_web(phone)
        except ValueError:
            self._show_whatsapp_warning("رقم الهاتف غير صالح. يرجى إدخال رقم موبايل مصري صحيح.")
        except RuntimeError:
            self._show_whatsapp_warning("تعذر فتح واتساب في المتصفح الافتراضي.")
        else:
            self.whatsapp_button.setEnabled(False)
            self.whatsapp_button.setText("جاري الإرسال...")
            QTimer.singleShot(self.AUTO_SEND_DELAY_MS, self._send_whatsapp_message)

    def _send_whatsapp_message(self) -> None:
        try:
            whatsapp_service.press_enter_key()
            QMessageBox.information(
                self,
                "تم الإرسال",
                "تم إرسال رسالة واتساب بنجاح.",
            )
        except RuntimeError:
            QMessageBox.warning(
                self,
                "تعذر إرسال رسالة واتساب",
                "تم فتح واتساب، لكن تعذر الضغط على زر الإرسال تلقائيًا.",
            )
        finally:
            self.whatsapp_button.setText("WhatsApp")
            self.whatsapp_button.setEnabled(True)

    def _show_whatsapp_warning(self, message: str) -> None:
        QMessageBox.warning(self, "تعذر فتح واتساب", message)
