"""Visual theme constants and small style helpers for the review UI.

These are layout/presentation concerns only (colors, button styling, the
combo dropdown alignment delegate, and per-screen layout maps). No business
or database logic lives here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyledItemDelegate


GREEN = "#137A38"
GREEN_DARK = "#0F6B30"
BORDER = "#D9E2EC"
TEXT = "#111827"

# Screens that use the side-by-side "form + search list" layout with an
# F1 lookup dialog (same design/idea as the reference customer screen).
LOOKUP_LAYOUT_KEYS = {"customers", "employees", "daily_followups", "products", "companies",
                      "tawrid_tractors", "tawrid_customers", "tawrid_suppliers",
                      "tawrid_tickets", "tawrid_crusher_cubing",
                      "tawrid_customer_receipts", "tawrid_supplier_payments",
                      "tawrid_tractor_payments", "contractors"}

# Labels for list columns that come from a JOIN (no matching FieldSpec).
EXTRA_COLUMN_LABELS = {
    "case_status_name": "الحالة",
    "employee_name": "اسم الموظف",
}

# Fields whose text should be right-aligned (numeric values), per screen.
# Everything else on the form stays left-aligned.
RIGHT_ALIGNED_FIELDS = {
    "customers": {
        "customer_id",
        "phone_number",
        "opening_balance",
        "area_number",
        "unit_number",
        "building",
        "vat_number",
        "cr",
    },
    "suppliers": {
        "supplier_id",
        "mobile",
        "opening_balance",
    },
    "tawrid_tractors": {
        "tractor_code",
        "trailer_no",
        "head_no",
        "phone",
        "price_sen",
        "price_raml",
        "opening_balance",
    },
    "tawrid_customers": {
        "customer_code",
        "phone",
        "opening_balance",
        "discount_percent",
        # The ten item prices, all money boxes.
        "price_sen1",
        "price_sen2",
        "price_sen_ataqa",
        "price_sen6_safi",
        "price_sen6_bodra",
        "price_sen_adsa",
        "price_bodra",
        "price_raml",
        "price_sen_plus",
        "price_sen_modarag",
    },
    "tawrid_suppliers": {
        "supplier_code",
        "phone",
        "opening_balance",
        # The ten item prices, all money boxes.
        "price_sen1",
        "price_sen2",
        "price_sen_ataqa",
        "price_sen6_safi",
        "price_sen6_bodra",
        "price_sen_adsa",
        "price_bodra",
        "price_raml",
        "price_sen_plus",
        "price_sen_modarag",
    },
    "tawrid_tickets": {
        # Every number on the البون sits on the visual right (RTL), like the
        # other Tawrid screens.
        "ticket_no",
        "receipt_no",
        "cus_volume",
        "price_cus",
        "discount_percent",
        "res_volume",
        "price_res",
        "price_man",
    },
    "tawrid_crusher_cubing": {
        # The sheet number and date sit on the visual right (RTL), like the
        # other Tawrid screens. The تكعيب volumes are on the line cards, not here.
        "sheet_no",
        "sheet_date",
    },
    "tawrid_customer_receipts": {
        # Every number on the receipt sits on the visual right (RTL). The amount
        # box is styled by the screen itself (large, green); this covers the
        # smaller number/date boxes.
        "receipt_no",
        "receipt_date",
        "amount",
    },
    "tawrid_supplier_payments": {
        # Every number on the payment voucher sits on the visual right (RTL). The
        # amount box is styled by the screen itself (large, amber); this covers the
        # smaller number/date boxes.
        "payment_no",
        "payment_date",
        "amount",
    },
    "tawrid_tractor_payments": {
        # Same voucher as the crusher side; the amount box is styled by the screen
        # itself (large, blue), this covers the smaller number/date boxes.
        "payment_no",
        "payment_date",
        "amount",
    },
    "contractors": {
        "registration_no",
        "phone",
        "current_balance",
        "vat_amount",
        "withholding_tax_amount",
        "social_insurance_amount",
        "works_insurance_amount",
        "other_deductions_amount",
    },
    "workers": {
        "worker_id",
        "mobile",
        "opening_balance",
    },
    "expenses": {
        "id",
        "amount",
        "expense_date",
    },
    "treasury_deposits": {
        "id",
        "amount",
        "movement_date",
    },
    "employees": {
        "employee_id",
        "phone_number",
    },
    "products": {
        "item_code",
        "quantity",
        "price",
        "total",
    },
    "companies": {
        "id",
        "commercial_registration",
        "vat_number",
    },
    "daily_followups": {
        "daily_followup_id",
        "customer_id",
        "customer_phone",
        "case_status_id",
        "employee_id",
        "contact_count",
    },
    "receipt_vouchers": {
        "id",
        "voucher_number",
        "voucher_date",
        "amount",
    },
    "supplier_payment_vouchers": {
        "id",
        "voucher_number",
        "voucher_date",
        "amount",
    },
    "worker_payment_vouchers": {
        "id",
        "voucher_number",
        "voucher_date",
        "amount",
    },
    "worker_daily": {
        "id",
        "movement_date",
        "number_of_days",
        "daily_wage",
        "daily_salary",
        "cash",
        "balance",
    },
}


class _RightAlignDelegate(QStyledItemDelegate):
    """Render combo-box dropdown items left-aligned."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignLeft | Qt.AlignVCenter


def _button_style(bg: str, hover: str, fg: str = "#FFFFFF") -> str:
    return (
        f"QPushButton {{ background:{bg}; color:{fg}; border:none; border-radius:6px; "
        "font-weight:800; padding:7px 12px; }"
        f"QPushButton:hover {{ background:{hover}; }}"
        "QPushButton:disabled { background:#CBD5E1; color:#FFFFFF; }"
    )
