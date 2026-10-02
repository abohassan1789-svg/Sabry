"""Central registry of CRM screens, reports and their permission actions.

This is the single source of truth the dynamic permissions system scans. A
permission code is always ``module_code.target_code.action_code``.

To expose a NEW screen in the permissions system: add an entry to
``SCREEN_TARGETS`` (and wire its widget in the navigation/main window).

To expose a NEW report: give its report class a ``PERMISSION_TARGET`` dict in
``app/reports`` — it is discovered automatically — or add it to
``STATIC_REPORT_TARGETS`` below. Either way it is registered, but it only
appears in the matrix (and syncs as active) once it has a ``TARGET_ACTIONS``
entry — see below.

The matrix shows ONLY the targets in ``MATRIX_TARGET_CODES`` (built from
``TARGET_ACTIONS``, which also fixes each target's action columns). To show a
new screen/report, add it there. ``HIDDEN_TARGET_CODES`` still hides on top of
that. Read the notes there first — anything not shown is denied to every
non-admin, so it must move in step with the sidebar.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

# (action_code, name_ar, name_en) — order is the matrix column order.
SCREEN_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("view", "عرض", "View"),
    ("create", "إضافة", "Create"),
    ("edit", "تعديل", "Edit"),
    ("save", "حفظ", "Save"),
    ("delete", "حذف", "Delete"),
    ("approve", "اعتماد", "Approve"),
    # Puts an approved record back to draft (the contracting screens, 2026-10-02).
    ("unapprove", "إلغاء الاعتماد", "Unapprove"),
    ("print", "طباعة", "Print"),
    ("export", "تصدير", "Export"),
    ("import", "استيراد", "Import"),
    ("post", "ترحيل", "Post"),
    ("unpost", "إلغاء الترحيل", "Unpost"),
)

REPORT_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("view", "عرض", "View"),
    ("preview", "معاينة", "Preview"),
    ("filter", "تصفية", "Filter"),
    ("print", "طباعة", "Print"),
    ("export", "تصدير", "Export"),
)

ACTION_NAMES_AR = {code: ar for code, ar, _en in (*SCREEN_ACTIONS, *REPORT_ACTIONS)}
ACTION_NAMES_EN = {code: en for code, _ar, en in (*SCREEN_ACTIONS, *REPORT_ACTIONS)}

CATEGORY_SCREEN_AR, CATEGORY_SCREEN_EN = "الشاشات", "Screens"
CATEGORY_REPORT_AR, CATEGORY_REPORT_EN = "التقارير", "Reports"

# --- Screens -----------------------------------------------------------------
# target_code MUST match the screen's runtime key so enforcement lines up
# (CRUD screens use their TableSpec.key; security pages use these codes).
SCREEN_TARGETS: list[dict[str, str]] = [
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "customers", "target_name_ar": "العملاء", "target_name_en": "Customers"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "suppliers", "target_name_ar": "الموردين", "target_name_en": "Suppliers"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_tractors", "target_name_ar": "الجرارات", "target_name_en": "Tractors"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_customers", "target_name_ar": "العملاء (التوريدات)",
     "target_name_en": "Tawrid Customers"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_suppliers", "target_name_ar": "الكسارات (الموردين)",
     "target_name_en": "Tawrid Suppliers"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_tickets", "target_name_ar": "البون", "target_name_en": "Tawrid Tickets"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_tickets2", "target_name_ar": "بون 2", "target_name_en": "Tawrid Tickets (Alt)"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_crusher_cubing", "target_name_ar": "تكعيب الكسّارات",
     "target_name_en": "Crusher Cubing"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_customer_receipts", "target_name_ar": "سندات قبض العملاء",
     "target_name_en": "Customer Receipts"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_supplier_payments", "target_name_ar": "سندات صرف الكسّارات",
     "target_name_en": "Supplier Payments"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_tractor_payments", "target_name_ar": "سندات صرف الجرارات",
     "target_name_en": "Tractor Payments"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_customer_statement", "target_name_ar": "كشف حساب عميل",
     "target_name_en": "Customer Statement"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_supplier_statement", "target_name_ar": "كشف حساب الكسارات",
     "target_name_en": "Supplier Statement"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_tractor_statement", "target_name_ar": "كشف حساب الجرارات",
     "target_name_en": "Tractor Statement"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_comprehensive_report", "target_name_ar": "التقرير الشامل",
     "target_name_en": "Comprehensive Report"},
    {"module_code": "tawrid", "module_name_ar": "قسم التوريدات", "module_name_en": "Tawrid",
     "target_code": "tawrid_treasury_statement", "target_name_ar": "كشف حساب الخزينة",
     "target_name_en": "Treasury Statement"},
    # الشركات والمشاريع is its own screen (two tables), checked as
    # ``contracting.company_projects.<action>`` by the screen and the sidebar.
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "company_projects", "target_name_ar": "الشركات والمشاريع",
     "target_name_en": "Companies & Projects"},
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "contractor_contracts", "target_name_ar": "عقود المقاولين",
     "target_name_en": "Contractor Contracts"},
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "contractor_extracts", "target_name_ar": "مستخلصات المقاولين",
     "target_name_en": "Contractor Extracts"},
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "contractor_payments", "target_name_ar": "دفعات المقاولين",
     "target_name_en": "Contractor Payments"},
    # module_code "crm": BaseCrudScreen and the sidebar check ``crm.<key>.<action>``.
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "contractors", "target_name_ar": "المقاولين", "target_name_en": "Contractors"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "workers", "target_name_ar": "العمال", "target_name_en": "Workers"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "expenses", "target_name_ar": "المصروفات", "target_name_en": "Expenses"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "treasury_deposits", "target_name_ar": "إضافة أموال للخزينة", "target_name_en": "Treasury Deposits"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "products", "target_name_ar": "الأصناف", "target_name_en": "Products"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "companies", "target_name_ar": "الشركات", "target_name_en": "Companies"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "receipt_vouchers", "target_name_ar": "سندات القبض", "target_name_en": "Receipt Vouchers"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "supplier_payment_vouchers", "target_name_ar": "سندات صرف الموردين", "target_name_en": "Supplier Payment Vouchers"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "worker_payment_vouchers", "target_name_ar": "سندات صرف العمال", "target_name_en": "Worker Payment Vouchers"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "worker_daily", "target_name_ar": "يومية العمال", "target_name_en": "Worker Daily"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "employees", "target_name_ar": "الموظفين", "target_name_en": "Employees"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "daily_followups", "target_name_ar": "المتابعة اليومية", "target_name_en": "Daily Follow-ups"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "places", "target_name_ar": "المناطق", "target_name_en": "Places"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "case_statuses", "target_name_ar": "الحالات", "target_name_en": "Case Statuses"},
    {"module_code": "crm", "module_name_ar": "إدارة بيانات CRM", "module_name_en": "CRM Data",
     "target_code": "attachments", "target_name_ar": "المرفقات", "target_name_en": "Attachments"},
    # Saudi Phase-2 sales invoice (module: sales) — target_code matches the
    # navigation runtime key so view enforcement lines up.
    {"module_code": "sales", "module_name_ar": "فواتير المبيعات", "module_name_en": "Sales Invoices",
     "target_code": "saudi_sales_invoices", "target_name_ar": "فاتورة المبيعات السعودية",
     "target_name_en": "Saudi Sales Invoice"},
    # Experimental Cashier / POS (module: sales) — target_code matches the
    # navigation runtime key ("cashier") and the service's PERM_TARGET.
    {"module_code": "sales", "module_name_ar": "فواتير المبيعات", "module_name_en": "Sales Invoices",
     "target_code": "cashier", "target_name_ar": "الكاشير / نقطة البيع",
     "target_name_en": "Cashier / POS"},
    # Purchase invoice (module: purchases) — target_code matches the navigation
    # runtime key ("purchase_invoices") and the service's PERM_TARGET.
    {"module_code": "purchases", "module_name_ar": "فواتير المشتريات", "module_name_en": "Purchase Invoices",
     "target_code": "purchase_invoices", "target_name_ar": "فاتورة المشتريات",
     "target_name_en": "Purchase Invoice"},
    # Bill of Materials (module: manufacturing) — target_code matches the
    # navigation runtime key ("boms") and the service's PERM_TARGET.
    {"module_code": "manufacturing", "module_name_ar": "التصنيع", "module_name_en": "Manufacturing",
     "target_code": "boms", "target_name_ar": "قائمة المواد",
     "target_name_en": "Bill of Materials"},
    # Production Order (module: manufacturing) — target_code matches the
    # navigation runtime key ("production_orders") and the service's PERM_TARGET.
    {"module_code": "manufacturing", "module_name_ar": "التصنيع", "module_name_en": "Manufacturing",
     "target_code": "production_orders", "target_name_ar": "أوامر الإنتاج",
     "target_name_en": "Production Orders"},
    # Loading Voucher (module: logistics) — target_code matches the navigation
    # runtime key ("loading_vouchers") and the service's PERM_TARGET.
    {"module_code": "logistics", "module_name_ar": "الشحن والنقل", "module_name_en": "Logistics",
     "target_code": "loading_vouchers", "target_name_ar": "سندات التحميل",
     "target_name_en": "Loading Vouchers"},
    # Security screens (module: security)
    {"module_code": "security", "module_name_ar": "المستخدمين والصلاحيات", "module_name_en": "Users & Permissions",
     "target_code": "users", "target_name_ar": "المستخدمين", "target_name_en": "Users Management"},
    {"module_code": "security", "module_name_ar": "المستخدمين والصلاحيات", "module_name_en": "Users & Permissions",
     "target_code": "roles", "target_name_ar": "مجموعات الصلاحيات", "target_name_en": "Roles / Permission Groups"},
    {"module_code": "security", "module_name_ar": "المستخدمين والصلاحيات", "module_name_en": "Users & Permissions",
     "target_code": "user_permissions", "target_name_ar": "صلاحيات المستخدم", "target_name_en": "User Permissions"},
]

# --- Reports -----------------------------------------------------------------
# Fallback list used if dynamic discovery from app/reports finds nothing.
STATIC_REPORT_TARGETS: list[dict[str, str]] = [
    # تقرير عقود المقاولين — checked as ``contracting.contractor_contracts_report.<action>``.
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "contractor_contracts_report", "target_name_ar": "تقرير عقود المقاولين",
     "target_name_en": "Contractor Contracts Report"},
    # تقرير مستخلصات المقاولين — checked as ``contracting.contractor_extracts_report.<action>``.
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "contractor_extracts_report", "target_name_ar": "تقرير مستخلصات المقاولين",
     "target_name_en": "Contractor Extracts Report"},
    # تقرير كشف حساب الدفعة المقدمة — checked as ``contracting.contractor_advance_report.<action>``.
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "contractor_advance_report", "target_name_ar": "تقرير كشف حساب الدفعة المقدمة",
     "target_name_en": "Advance Payment Statement Report"},
    # داشبورد المقاولين — checked as ``contracting.contractors_dashboard.<action>``.
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "contractors_dashboard", "target_name_ar": "داشبورد المقاولين",
     "target_name_en": "Contractors Dashboard"},
    # تقرير كشف حساب مقاول — checked as ``contracting.contractor_statement_report.<action>``.
    {"module_code": "contracting", "module_name_ar": "المقاولات", "module_name_en": "Contracting",
     "target_code": "contractor_statement_report", "target_name_ar": "تقرير كشف حساب مقاول",
     "target_name_en": "Contractor Statement Report"},
    {"module_code": "reports", "module_name_ar": "التقارير", "module_name_en": "Reports",
     "target_code": "daily_followup_report", "target_name_ar": "تقرير المتابعة اليومية",
     "target_name_en": "Daily Follow-up Report"},
    {"module_code": "reports", "module_name_ar": "التقارير", "module_name_en": "Reports",
     "target_code": "sales_report", "target_name_ar": "تقرير المبيعات", "target_name_en": "Sales Report"},
    {"module_code": "reports", "module_name_ar": "التقارير", "module_name_en": "Reports",
     "target_code": "production_order_report", "target_name_ar": "تقرير أوامر الإنتاج",
     "target_name_en": "Production Orders Report"},
    {"module_code": "reports", "module_name_ar": "التقارير", "module_name_en": "Reports",
     "target_code": "profit_report", "target_name_ar": "تقرير الأرباح",
     "target_name_en": "Profit Report"},
    {"module_code": "reports", "module_name_ar": "التقارير", "module_name_en": "Reports",
     "target_code": "status_summary_report", "target_name_ar": "تقرير ملخص الحالات",
     "target_name_en": "Status Summary Report"},
    {"module_code": "reports", "module_name_ar": "التقارير", "module_name_en": "Reports",
     "target_code": "raw_material_balance", "target_name_ar": "مخزن مواد الخام",
     "target_name_en": "Raw Material Warehouse"},
    {"module_code": "reports", "module_name_ar": "التقارير", "module_name_en": "Reports",
     "target_code": "finished_goods_balance", "target_name_ar": "مخزن الإنتاج التام",
     "target_name_en": "Finished Goods Warehouse"},
]


# --- Hidden targets ----------------------------------------------------------
# Targets that stay fully registered above but are kept OUT of the permissions
# matrix, because the user cannot reach them in the UI (per user request,
# 2026-07-15). The rule the user asked for: **what the sidebar shows is exactly
# what the permissions screen controls** — a permission for a screen nobody can
# open is noise that invites granting access that does nothing.
#
# These are NOT deleted: `PermissionsSyncService` flips them to `is_active=false`
# on the next sync, so every existing role/user grant survives untouched and
# re-listing a code here brings the row (and its grants) straight back.
#
# ⚠️ Un-hiding rule. `can()` resolves against ACTIVE permissions only, so a code
# that is not shown is denied to every non-admin. Since 2026-10-02 the matrix is
# a whitelist (`TARGET_ACTIONS` below), so un-hiding a screen means ALL of:
#   1. give it a `TARGET_ACTIONS` entry (which also sets its columns),
#   2. remove it from this set if it is listed here,
#   3. remove it from `main_window.HIDDEN_NAV_KEYS` / its HIDDEN_NAV_SECTIONS
#      section so the sidebar shows it.
# Forgetting 1 or 2 puts a nav button on screen that silently stays invisible to
# everyone but Admin. `tests/unit/test_permission_ui_parity.py` fails on it.
HIDDEN_TARGET_CODES: frozenset[str] = frozenset({
    # Screens — mirror of main_window.HIDDEN_NAV_KEYS.
    "employees",           # الموظفين
    "daily_followups",     # المتابعة اليومية
    "places",              # المناطق
    "case_statuses",       # الحالات
    "attachments",         # المرفقات
    # Screens/reports hidden per Book1.xlsx request (2026-08-19). Kept fully
    # registered (code not deleted) but out of the sidebar AND the permissions
    # matrix — the two-way rule above. Mirror of the same keys in
    # main_window.HIDDEN_NAV_KEYS. سندات القبض (receipt_vouchers) stays visible.
    "workers",                     # العمال
    "expenses",                    # المصروفات
    "treasury_deposits",           # إضافة أموال للخزينة
    "supplier_payment_vouchers",   # سندات صرف الموردين
    "worker_payment_vouchers",     # سندات صرف العمال
    "worker_daily",                # يومية العمال
    "cashier",                     # الكاشير
    "supplier_statement",          # كشف حساب مورد
    "supplier_weight_statement",   # كشف حساب مورد وزن
    # Reports — none of these has a live entry in main_window.REPORTS
    # (daily_followup_smart_report / status_analysis_report are commented out
    # there).
    "daily_followup_report",        # تقرير المتابعة اليومية
    "daily_followup_smart_report",  # تقرير المتابعة اليومية الذكي
    "status_summary_report",        # تقرير ملخص الحالات
    "status_analysis_report",       # تقرير تحليل الحالات
    # قسم التقارير مقصور على كشوف التوريدات — تُخفى تقارير الموديول القديم من
    # القايمة ومن مصفوفة الصلاحيات (مرآة main_window.HIDDEN_NAV_KEYS).
    "production_order_report",      # تقرير أوامر الإنتاج
    "loading_voucher_report",       # تقرير سندات التحميل
    "customer_statement",           # كشف حساب العميل (القديم)
    "sales_report",                 # تقرير المبيعات
    "purchase_report",              # تقرير المشتريات
    "profit_report",                # تقرير الأرباح
    "raw_material_balance",         # مخزن مواد الخام
    "finished_goods_balance",       # مخزن الإنتاج التام
    # كشوف التوريدات — hidden from «التقارير» per user request (2026-09-26);
    # mirror of the same keys in main_window.HIDDEN_NAV_KEYS.
    "tawrid_customer_statement",    # كشف حساب عميل
    "tawrid_supplier_statement",    # كشف حساب الكسارات
    "tawrid_tractor_statement",     # كشف حساب الجرارات
    "tawrid_comprehensive_report",  # تقرير شامل
    "tawrid_treasury_statement",    # كشف حساب الخزينة
})


# --- What the matrix shows ---------------------------------------------------
# User request (2026-10-02): مجموعات الصلاحيات / صلاحيات المستخدم list ONLY the
# contracting screens and reports (the sidebar's «المقاولات» + «التقارير») and
# the three security screens. Every other target stays registered but is not
# synced as active — same effect as HIDDEN_TARGET_CODES (old grants survive,
# non-admins are denied, which is moot: their sidebar sections are hidden).
# A new screen/report appears only with a TARGET_ACTIONS entry (which also
# sets its columns); MATRIX_TARGET_CODES is built from it.
CONTRACTING_SCREEN_ACTIONS: tuple[str, ...] = (
    "view", "create", "edit", "save", "delete", "approve", "unapprove",
)
CONTRACTING_REPORT_ACTIONS: tuple[str, ...] = ("view", "filter", "print", "export")
SECURITY_SCREEN_ACTIONS: tuple[str, ...] = ("view", "create", "edit", "save", "delete")

TARGET_ACTIONS: dict[str, tuple[str, ...]] = {
    # المقاولات — شاشات (contractors keeps module "crm": crm.contractors.*).
    "contractors": CONTRACTING_SCREEN_ACTIONS,
    "company_projects": CONTRACTING_SCREEN_ACTIONS,
    "contractor_contracts": CONTRACTING_SCREEN_ACTIONS,
    "contractor_extracts": CONTRACTING_SCREEN_ACTIONS,
    "contractor_payments": CONTRACTING_SCREEN_ACTIONS,
    # المقاولات — داشبورد وتقارير.
    "contractors_dashboard": CONTRACTING_REPORT_ACTIONS,
    "contractor_contracts_report": CONTRACTING_REPORT_ACTIONS,
    "contractor_extracts_report": CONTRACTING_REPORT_ACTIONS,
    "contractor_advance_report": CONTRACTING_REPORT_ACTIONS,
    "contractor_statement_report": CONTRACTING_REPORT_ACTIONS,
    # النظام والصلاحيات.
    "users": SECURITY_SCREEN_ACTIONS,
    "roles": SECURITY_SCREEN_ACTIONS,
    "user_permissions": SECURITY_SCREEN_ACTIONS,
}

MATRIX_TARGET_CODES: frozenset[str] = frozenset(TARGET_ACTIONS)


def is_target_shown(target_code: str) -> bool:
    """True when the target is synced as active and listed in the matrix."""
    return target_code in MATRIX_TARGET_CODES and target_code not in HIDDEN_TARGET_CODES


def make_permission_code(module_code: str, target_code: str, action_code: str) -> str:
    return f"{module_code}.{target_code}.{action_code}"


def _discover_report_targets() -> list[dict[str, str]]:
    """Scan app/reports for classes exposing a ``PERMISSION_TARGET`` dict.

    Import failures (e.g. optional reportlab/openpyxl deps) are ignored so the
    scan never breaks the app.
    """
    found: dict[str, dict[str, str]] = {}
    try:
        import app.reports as reports_pkg
    except Exception:
        return []
    for mod_info in pkgutil.iter_modules(reports_pkg.__path__):
        try:
            module = importlib.import_module(f"app.reports.{mod_info.name}")
        except Exception:
            continue
        for attr in vars(module).values():
            target = getattr(attr, "PERMISSION_TARGET", None)
            if isinstance(target, dict) and target.get("target_code"):
                entry = {
                    "module_code": target.get("module_code", "reports"),
                    "module_name_ar": target.get("module_name_ar", "التقارير"),
                    "module_name_en": target.get("module_name_en", "Reports"),
                    "target_code": target["target_code"],
                    "target_name_ar": target.get("target_name_ar", target["target_code"]),
                    "target_name_en": target.get("target_name_en", target["target_code"]),
                }
                found[entry["target_code"]] = entry
    return list(found.values())


def report_targets() -> list[dict[str, str]]:
    discovered = _discover_report_targets()
    merged: dict[str, dict[str, str]] = {t["target_code"]: t for t in STATIC_REPORT_TARGETS}
    for entry in discovered:
        merged[entry["target_code"]] = entry  # discovered overrides static
    return list(merged.values())


def collect_targets(include_hidden: bool = False) -> list[dict[str, Any]]:
    """Return every registered target with its type, category and actions.

    Only ``MATRIX_TARGET_CODES`` (minus ``HIDDEN_TARGET_CODES``) are returned
    unless ``include_hidden`` — that flag exists for tooling that needs the
    full registry (and for the parity test); the sync and the UI both want the
    filtered view. A target's actions come from ``TARGET_ACTIONS``, falling back
    to the full screen/report action set for targets outside the matrix.
    """
    screen_actions = [code for code, _ar, _en in SCREEN_ACTIONS]
    report_actions = [code for code, _ar, _en in REPORT_ACTIONS]
    targets: list[dict[str, Any]] = []
    for screen in SCREEN_TARGETS:
        targets.append({
            **screen,
            "permission_type": "screen",
            "category_ar": CATEGORY_SCREEN_AR,
            "category_en": CATEGORY_SCREEN_EN,
            "actions": list(TARGET_ACTIONS.get(screen["target_code"], screen_actions)),
        })
    for report in report_targets():
        targets.append({
            **report,
            "permission_type": "report",
            "category_ar": CATEGORY_REPORT_AR,
            "category_en": CATEGORY_REPORT_EN,
            "actions": list(TARGET_ACTIONS.get(report["target_code"], report_actions)),
        })
    if include_hidden:
        return targets
    return [t for t in targets if is_target_shown(t["target_code"])]


def build_permission_rows() -> list[dict[str, Any]]:
    """Flatten all targets × actions into permission row dicts for sync/upsert."""
    rows: list[dict[str, Any]] = []
    for target in collect_targets():
        for action_code in target["actions"]:
            rows.append({
                "permission_code": make_permission_code(
                    target["module_code"], target["target_code"], action_code
                ),
                "permission_type": target["permission_type"],
                "module_code": target["module_code"],
                "module_name_ar": target["module_name_ar"],
                "module_name_en": target["module_name_en"],
                "category_ar": target["category_ar"],
                "category_en": target["category_en"],
                "target_code": target["target_code"],
                "target_name_ar": target["target_name_ar"],
                "target_name_en": target["target_name_en"],
                "action_code": action_code,
                "action_name_ar": ACTION_NAMES_AR.get(action_code, action_code),
                "action_name_en": ACTION_NAMES_EN.get(action_code, action_code),
            })
    return rows
