"""Application shell for the CRM app.

Thin shell: owns the right-side sidebar/main menu and opens each screen as its
own maximized top-level window. It contains no form layout, no business logic,
and no database access — screens live under ``app.ui.screens`` and all data
access stays in the services. Opening any screen is gated by the current
session's ``view`` permission, and menu items the user cannot view are hidden.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.repositories.security_repository import SecurityRepository
from app.security.session_context import SESSION
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.services.permissions_sync_service import PermissionsSyncService
from app.services.review_data_service import ReviewDataService, TABLE_SPECS
from app.ui.common.live_lists import LiveLists
from app.ui.common.theme import GREEN, GREEN_DARK
from app.ui.screens.attachments_page import AttachmentsPage
from app.ui.screens.backup_screen import BackupManagementScreen
from app.ui.screens.connection_screen import ConnectionSettingsScreen
from app.ui.screens.crm_dashboard_page import CrmDashboardPage
from app.ui.screens.executive_dashboard_page import ExecutiveDashboardPage
from app.ui.screens.customer_statement_report_screen import CustomerStatementReportScreen
from app.ui.screens.supplier_ledger_report_screen import SupplierLedgerReportScreen
from app.ui.screens.supplier_weight_statement_report_screen import SupplierWeightStatementReportScreen
from app.ui.screens.sales_report_screen import SalesReportScreen
from app.ui.screens.production_order_report_screen import ProductionOrderReportScreen
from app.ui.screens.profit_report_screen import ProfitReportScreen
from app.ui.screens.purchase_report_screen import PurchaseReportScreen
from app.ui.screens.loading_voucher_report_screen import LoadingVoucherReportScreen
from app.ui.screens.raw_material_balance_screen import RawMaterialBalanceScreen
from app.ui.screens.finished_goods_balance_screen import FinishedGoodsBalanceScreen
from app.ui.screens.dashboard_page import DashboardPage
from app.ui.screens.case_statuses_screen import CaseStatusesScreen
from app.ui.screens.companies_screen import CompaniesScreen
from app.ui.screens.customers_screen import CustomersScreen
from app.ui.screens.daily_followup_smart_report_screen import DailyFollowupSmartReportScreen
from app.ui.screens.status_analysis_report_screen import StatusAnalysisReportScreen
from app.ui.screens.daily_followups_screen import DailyFollowupsScreen
from app.ui.screens.employees_screen import EmployeesScreen
from app.ui.screens.places_screen import PlacesScreen
from app.ui.screens.products_screen import ProductsScreen
from app.ui.screens.receipt_vouchers_screen import ReceiptVouchersScreen
from app.ui.screens.supplier_payment_vouchers_screen import SupplierPaymentVouchersScreen
from app.ui.screens.worker_payment_vouchers_screen import WorkerPaymentVouchersScreen
from app.ui.screens.treasury_deposits_screen import TreasuryDepositsScreen
from app.ui.screens.suppliers_screen import SuppliersScreen
from app.ui.screens.tawrid_customers_screen import TawridCustomersScreen
from app.ui.screens.tawrid_suppliers_screen import TawridSuppliersScreen
from app.ui.screens.tawrid_tickets_screen import TawridTicketsScreen
from app.ui.screens.tawrid_tickets2_screen import TawridTickets2Screen
from app.ui.screens.tawrid_cubing_screen import TawridCubingScreen
from app.ui.screens.tawrid_customer_receipts_screen import TawridCustomerReceiptsScreen
from app.ui.screens.tawrid_supplier_payments_screen import TawridSupplierPaymentsScreen
from app.ui.screens.tawrid_tractor_payments_screen import TawridTractorPaymentsScreen
from app.ui.screens.tawrid_tractors_screen import TawridTractorsScreen
from app.ui.screens.tawrid_customer_statement_screen import TawridCustomerStatementScreen
from app.ui.screens.tawrid_supplier_statement_screen import TawridSupplierStatementScreen
from app.ui.screens.tawrid_tractor_statement_screen import TawridTractorStatementScreen
from app.ui.screens.tawrid_comprehensive_report_screen import TawridComprehensiveReportScreen
from app.ui.screens.tawrid_treasury_statement_screen import TawridTreasuryStatementScreen
from app.ui.screens.workers_screen import WorkersScreen
from app.ui.screens.contractors_screen import ContractorsScreen
from app.ui.screens.company_projects_screen import CompanyProjectsScreen
from app.ui.screens.contractor_contracts_screen import ContractorContractsScreen
from app.ui.screens.contractor_extracts_screen import ContractorExtractsScreen
from app.ui.screens.contractor_payments_screen import ContractorPaymentsScreen
from app.ui.screens.contractor_contracts_report_screen import ContractorContractsReportScreen
from app.ui.screens.contractor_extracts_report_screen import ContractorExtractsReportScreen
from app.ui.screens.contractor_advance_report_screen import ContractorAdvanceReportScreen
from app.ui.screens.contractor_statement_report_screen import ContractorStatementReportScreen
from app.ui.screens.contractors_dashboard_screen import ContractorsDashboardScreen
from app.ui.screens.worker_daily_screen import WorkerDailyScreen
from app.ui.screens.expenses_screen import ExpensesScreen
from app.ui.screens.cashier_page import CashierPage
from app.ui.screens.roles_page import RolesPage
from app.ui.screens.saudi_sales_invoice_page import SaudiSalesInvoicePage
from app.ui.screens.purchase_invoice_page import PurchaseInvoicePage
from app.ui.screens.bom_page import BomPage
from app.ui.screens.production_order_page import ProductionOrderPage
from app.ui.screens.loading_voucher_page import LoadingVoucherPage
from app.ui.screens.user_permissions_page import UserPermissionsPage
from app.ui.screens.users_page import UsersPage


# CRM data modules: (spec key, sidebar label, screen class).
MODULES = (
    ("customers", "العملاء", CustomersScreen),
    ("suppliers", "الموردين", SuppliersScreen),
    ("workers", "العمال", WorkersScreen),
    ("expenses", "المصروفات", ExpensesScreen),
    ("treasury_deposits", "إضافة أموال للخزينة", TreasuryDepositsScreen),
    ("products", "الأصناف", ProductsScreen),
    ("companies", "الشركات", CompaniesScreen),
    ("receipt_vouchers", "سندات القبض", ReceiptVouchersScreen),
    ("supplier_payment_vouchers", "سندات صرف الموردين", SupplierPaymentVouchersScreen),
    ("worker_payment_vouchers", "سندات صرف العمال", WorkerPaymentVouchersScreen),
    ("worker_daily", "يومية العمال", WorkerDailyScreen),
    ("employees", "الموظفين", EmployeesScreen),
    ("daily_followups", "المتابعة اليومية", DailyFollowupsScreen),
    ("places", "المناطق", PlacesScreen),
    ("case_statuses", "الحالات", CaseStatusesScreen),
    # قسم التوريدات — phases 1, 2, 3, 4, 5, 6 and 7.
    ("tawrid_tractors", "الجرارات", TawridTractorsScreen),
    ("tawrid_customers", "العملاء", TawridCustomersScreen),
    ("tawrid_suppliers", "الكسارات", TawridSuppliersScreen),
    ("tawrid_tickets", "البون", TawridTicketsScreen),
    ("tawrid_crusher_cubing", "تكعيب الكسّارات", TawridCubingScreen),
    ("tawrid_customer_receipts", "سندات قبض العملاء", TawridCustomerReceiptsScreen),
    ("tawrid_supplier_payments", "سندات صرف الكسّارات", TawridSupplierPaymentsScreen),
    ("tawrid_tractor_payments", "سندات صرف الجرارات", TawridTractorPaymentsScreen),
    # قسم المقاولات.
    ("contractors", "المقاولين", ContractorsScreen),
)
SCREEN_BY_KEY = {key: screen_cls for key, _label, screen_cls in MODULES}

# Screens intentionally hidden from the sidebar (per user request). The screens,
# their TableSpecs and their permissions stay fully registered and functional —
# only their navigation buttons are not shown, and they are skipped by prewarm so
# no time is spent building a screen the sidebar can't open. To re-enable a screen,
# simply remove its key from this set.
HIDDEN_NAV_KEYS: frozenset[str] = frozenset(
    {
        "employees", "daily_followups", "places", "case_statuses", "attachments",
        # Hidden per Book1.xlsx request (kept in code, not deleted):
        "workers", "expenses", "treasury_deposits",
        "supplier_payment_vouchers", "worker_payment_vouchers", "worker_daily",
        "cashier",
        "supplier_statement", "supplier_weight_statement",
        # قسم التقارير مقصور على كشوف التوريدات — تُخفى تقارير الموديول القديم
        # (تبقى الشاشات والصلاحيات مسجّلة؛ مرآتها في permission_registry.HIDDEN_TARGET_CODES).
        "production_order_report", "loading_voucher_report", "customer_statement",
        "sales_report", "purchase_report", "profit_report",
        "raw_material_balance", "finished_goods_balance",
        # كشوف التوريدات والتقرير الشامل — hidden per user request (2026-09-26);
        # the «التقارير» section itself stays (KEEP_EMPTY_NAV_SECTIONS).
        "tawrid_customer_statement", "tawrid_supplier_statement", "tawrid_tractor_statement",
        "tawrid_comprehensive_report", "tawrid_treasury_statement",
    }
)

# Whole accordion sections hidden from the sidebar (per user request). Their
# screens, TableSpecs and permissions stay fully registered — only the section
# header + its items are not shown. To re-enable one, remove its id from this set.
HIDDEN_NAV_SECTIONS: frozenset[str] = frozenset(
    {"data", "finance", "invoices", "manufacturing", "logistics",
     # التوريدات — بيانات / مالية: hidden per user request (2026-09-26).
     "tawrid", "tawrid_finance"}
)

# Sections whose header stays in the sidebar even when none of their items is
# shown (user request 2026-09-26: «سيب القسم» — التقارير kept for reports to come).
KEEP_EMPTY_NAV_SECTIONS: frozenset[str] = frozenset({"reports"})

# Reports: (report key, sidebar label, screen class).
REPORTS = (
    # Hidden from the Reports menu (kept for possible re-enable):
    # ("daily_followup_smart_report", "Daily Follow-up Smart Report", DailyFollowupSmartReportScreen),
    # ("status_analysis_report", "تقرير تحليل الحالات", StatusAnalysisReportScreen),
    ("production_order_report", "تقرير أوامر الإنتاج", ProductionOrderReportScreen),
    ("loading_voucher_report", "تقرير سندات التحميل", LoadingVoucherReportScreen),
    ("customer_statement", "كشف حساب العميل", CustomerStatementReportScreen),
    ("supplier_statement", "كشف حساب المورد", SupplierLedgerReportScreen),
    ("supplier_weight_statement", "كشف حساب المورد (وزن)", SupplierWeightStatementReportScreen),
    ("sales_report", "تقرير المبيعات", SalesReportScreen),
    ("purchase_report", "تقرير المشتريات", PurchaseReportScreen),
    ("profit_report", "تقرير الأرباح", ProfitReportScreen),
    ("raw_material_balance", "مخزن مواد الخام", RawMaterialBalanceScreen),
    ("finished_goods_balance", "مخزن الإنتاج التام", FinishedGoodsBalanceScreen),
)
REPORT_SCREEN_BY_KEY = {key: screen_cls for key, _label, screen_cls in REPORTS}

# Collapsible "Users & Permissions" group: (child key, sidebar label).
SECURITY_CHILDREN = (
    ("users", "المستخدمين"),
    ("roles", "مجموعات الصلاحيات"),
    ("user_permissions", "صلاحيات المستخدم"),
)

# Sidebar organised into collapsible sections (accordion: opening one folds the
# rest). Each section is (section_id, title, icon, items), and each item is
# (runtime key, sidebar label, icon). The key must resolve through open_screen /
# the factories map. لوحة التحكم و داشبورد stay pinned above the sections.
NAV_SECTIONS: tuple[tuple[str, str, str, tuple[tuple[str, str, str], ...]], ...] = (
    ("data", "البيانات الأساسية", "🗂", (
        ("customers", "العملاء", "👥"),
        ("suppliers", "الموردين", "🚚"),
        ("workers", "العمال", "👷"),
        ("products", "الأصناف", "📦"),
        ("companies", "الشركات", "🏢"),
    )),
    ("finance", "الحركات المالية", "💸", (
        ("expenses", "المصروفات", "🧾"),
        ("treasury_deposits", "إضافة أموال للخزينة", "💰"),
        ("receipt_vouchers", "سندات القبض", "💵"),
        ("supplier_payment_vouchers", "سندات صرف الموردين", "🧾"),
        ("worker_payment_vouchers", "سندات صرف العمال", "👷"),
        ("worker_daily", "يومية العمال", "🗓"),
    )),
    ("invoices", "المبيعات والمشتريات", "🛒", (
        ("saudi_sales_invoices", "فاتورة مبيعات ", "🧾"),
        ("cashier", "الكاشير", "🛒"),
        ("purchase_invoices", "فاتورة المشتريات", "📦"),
    )),
    ("manufacturing", "التصنيع", "🏭", (
        ("boms", "قائمة المواد", "🧱"),
        ("production_orders", "أوامر الإنتاج", "🏭"),
    )),
    ("logistics", "الشحن والنقل", "🚚", (
        ("loading_vouchers", "سندات التحميل", "🚛"),
    )),
    ("contracting", "المقاولات", "🏗", (
        ("contractors_dashboard", "داشبورد المقاولين", "📊"),
        ("contractors", "المقاولين", "👷"),
        ("company_projects", "الشركات والمشاريع", "🏢"),
        ("contractor_contracts", "عقود المقاولين", "🤝"),
        ("contractor_extracts", "مستخلصات المقاولين", "🧾"),
        ("contractor_payments", "دفعات المقاولين", "💵"),
    )),
    # قسم التوريدات مقسوم إلى بيانات ومالية (بناءً على طلب المستخدم).
    ("tawrid", "التوريدات — بيانات", "🏗", (
        ("tawrid_tractors", "الجرارات", "🚜"),
        ("tawrid_customers", "العملاء", "👥"),
        ("tawrid_suppliers", "الكسارات", "🏗"),
        ("tawrid_crusher_cubing", "تكعيب الكسّارات", "🏗️"),
    )),
    ("tawrid_finance", "التوريدات — مالية", "💰", (
        ("tawrid_tickets", "البون", "🧾"),
        ("tawrid_tickets2", "بون 2", "🧾"),
        ("tawrid_customer_receipts", "سندات قبض العملاء", "💵"),
        ("tawrid_supplier_payments", "سندات صرف الكسّارات", "🧾"),
        ("tawrid_tractor_payments", "سندات صرف الجرارات", "🚜"),
    )),
    ("reports", "التقارير", "📈", (
        # تقارير المقاولات.
        ("contractor_contracts_report", "تقرير عقود المقاولين", "🤝"),
        ("contractor_extracts_report", "تقرير مستخلصات المقاولين", "🧾"),
        ("contractor_advance_report", "تقرير كشف حساب الدفعة المقدمة", "💳"),
        ("contractor_statement_report", "تقرير كشف حساب مقاول", "📒"),
        # كشوف حسابات التوريدات والتقرير الشامل — نُقلت هنا من قسم التوريدات.
        ("tawrid_customer_statement", "كشف حساب عميل", "📄"),
        ("tawrid_supplier_statement", "كشف حساب الكسارات", "📄"),
        ("tawrid_tractor_statement", "كشف حساب الجرارات", "📄"),
        ("tawrid_comprehensive_report", "تقرير شامل", "📊"),
        ("tawrid_treasury_statement", "كشف حساب الخزينة", "💰"),
        ("production_order_report", "تقرير أوامر الإنتاج", "🏭"),
        ("loading_voucher_report", "تقرير سندات التحميل", "🚛"),
        ("customer_statement", "كشف حساب العميل", "📄"),
        ("supplier_statement", "كشف حساب المورد", "📄"),
        ("supplier_weight_statement", "كشف حساب المورد (وزن)", "⚖"),
        ("sales_report", "تقرير المبيعات", "📊"),
        ("purchase_report", "تقرير المشتريات", "🛒"),
        ("profit_report", "تقرير الأرباح", "💰"),
        ("raw_material_balance", "مخزن مواد الخام", "🧱"),
        ("finished_goods_balance", "مخزن الإنتاج التام", "🏭"),
    )),
    ("system", "النظام والصلاحيات", "⚙", (
        ("backup", "النسخ الاحتياطي", "🗄"),
        ("connection_settings", "إعدادات الاتصال", "🌐"),
        ("users", "المستخدمين", "👤"),
        ("roles", "مجموعات الصلاحيات", "🛡"),
        ("user_permissions", "صلاحيات المستخدم", "🔑"),
    )),
)

# Accordion styling — "filled pills" (النموذج 5): a folded section header is a
# faint rounded row; an open one is a filled green pill. Items are rounded pills
# that turn white when active.
_SECTION_HEADER_BASE = (
    "QPushButton { text-align:left; color:#FFFFFF; background:rgba(255,255,255,0.05); "
    "border:none; border-radius:11px; padding:11px 12px; font-size:13px; font-weight:900; }"
    "QPushButton:hover { background:rgba(255,255,255,0.12); }"
)
_SECTION_HEADER_OPEN = (
    "QPushButton { text-align:left; color:#FFFFFF; background:#137A38; "
    "border:none; border-radius:11px; padding:11px 12px; font-size:13px; font-weight:900; }"
    "QPushButton:hover { background:#137A38; }"
)
_SECTION_ITEM_BASE = (
    "QPushButton { text-align:left; color:#D6F5E0; background:transparent; border:none; "
    "border-radius:20px; padding:12px 14px 12px 30px; font-size:14px; font-weight:800; }"
    "QPushButton:hover { background:rgba(255,255,255,0.10); color:#E8FBEF; }"
)
_SECTION_ITEM_ACTIVE = (
    "QPushButton { text-align:left; color:#0F6B30; background:#FFFFFF; border:none; "
    "border-radius:20px; padding:12px 14px 12px 30px; font-size:14px; font-weight:900; }"
)


class ReviewMainWindow(QMainWindow):
    """Main shell: sidebar menu that opens each screen in its own window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KSA")
        self.resize(1500, 850)
        self.setMinimumSize(1000, 640)
        self.setLayoutDirection(Qt.RightToLeft)

        # Services (single instances shared by all screens).
        self.service = ReviewDataService()
        self.security_repo = SecurityRepository()
        self.auth_service = AuthService(self.security_repo)
        self.permission_service = PermissionService(self.security_repo)
        self.sync_service = PermissionsSyncService(self.security_repo)
        # Refreshes the other open screens' lists after a save/approve (user request 2026-10-02).
        self.live_lists = LiveLists(self)

        self.open_windows: dict[str, QWidget] = {}
        self.nav_buttons: list[QPushButton] = []
        self._nav_by_key: dict[str, QPushButton] = {}
        self._button_styles: dict[QPushButton, tuple[str, str]] = {}
        # Accordion sections: section_id -> {header, body, expanded}; and a
        # reverse map from each nav key to the section that contains it.
        self._sections: dict[str, dict] = {}
        self._section_of_key: dict[str, str] = {}
        self._factories = self._build_factories()
        self._build_ui()

    # --- factory / permissions ---------------------------------------------
    def _build_factories(self) -> dict[str, dict]:
        factories: dict[str, dict] = {}
        for key, _label, cls in MODULES:
            factories[key] = {
                "title": TABLE_SPECS[key].title,
                "view": f"crm.{key}.view",
                "make": (lambda c=cls: c(self.service)),
            }
        factories["users"] = {
            "title": "إدارة المستخدمين", "view": "security.users.view",
            "make": lambda: UsersPage(self.auth_service, self.permission_service),
        }
        factories["roles"] = {
            "title": "مجموعات الصلاحيات", "view": "security.roles.view",
            "make": lambda: RolesPage(self.permission_service, self.sync_service),
        }
        factories["user_permissions"] = {
            "title": "صلاحيات المستخدم", "view": "security.user_permissions.view",
            "make": lambda: UserPermissionsPage(self.auth_service, self.permission_service),
        }
        factories["crm_dashboard"] = {
            "title": "داشبورد",
            "view": "dashboard.crm.view",
            "make": lambda: CrmDashboardPage(),
        }
        factories["executive_dashboard"] = {
            "title": "الداشبورد التنفيذية",
            "view": "dashboard.executive.view",
            "make": lambda: ExecutiveDashboardPage(),
        }
        factories["saudi_sales_invoices"] = {
            "title": "فاتورة المبيعات السعودية",
            "view": "sales.saudi_sales_invoices.view",
            "make": lambda: SaudiSalesInvoicePage(),
        }
        factories["cashier"] = {
            "title": "الكاشير / نقطة البيع",
            "view": "sales.cashier.view",
            "make": lambda: CashierPage(),
        }
        factories["purchase_invoices"] = {
            "title": "فاتورة المشتريات",
            "view": "purchases.purchase_invoices.view",
            "make": lambda: PurchaseInvoicePage(),
        }
        factories["company_projects"] = {
            "title": "الشركات والمشاريع",
            "view": "contracting.company_projects.view",
            "make": lambda: CompanyProjectsScreen(),
        }
        factories["contractor_contracts"] = {
            "title": "عقود المقاولين",
            "view": "contracting.contractor_contracts.view",
            "make": lambda: ContractorContractsScreen(),
        }
        factories["contractor_extracts"] = {
            "title": "مستخلصات المقاولين",
            "view": "contracting.contractor_extracts.view",
            "make": lambda: ContractorExtractsScreen(),
        }
        factories["contractor_payments"] = {
            "title": "دفعات المقاولين",
            "view": "contracting.contractor_payments.view",
            "make": lambda: ContractorPaymentsScreen(),
        }
        factories["contractor_contracts_report"] = {
            "title": "تقرير عقود المقاولين",
            "view": "contracting.contractor_contracts_report.view",
            "make": lambda: ContractorContractsReportScreen(),
        }
        factories["contractor_extracts_report"] = {
            "title": "تقرير مستخلصات المقاولين",
            "view": "contracting.contractor_extracts_report.view",
            "make": lambda: ContractorExtractsReportScreen(),
        }
        factories["contractor_advance_report"] = {
            "title": "تقرير كشف حساب الدفعة المقدمة",
            "view": "contracting.contractor_advance_report.view",
            "make": lambda: ContractorAdvanceReportScreen(),
        }
        factories["contractors_dashboard"] = {
            "title": "داشبورد المقاولين",
            "view": "contracting.contractors_dashboard.view",
            "make": lambda: ContractorsDashboardScreen(),
        }
        factories["contractor_statement_report"] = {
            "title": "تقرير كشف حساب مقاول",
            "view": "contracting.contractor_statement_report.view",
            "make": lambda: ContractorStatementReportScreen(),
        }
        factories["boms"] = {
            "title": "قائمة المواد",
            "view": "manufacturing.boms.view",
            "make": lambda: BomPage(),
        }
        factories["production_orders"] = {
            "title": "أوامر الإنتاج",
            "view": "manufacturing.production_orders.view",
            "make": lambda: ProductionOrderPage(),
        }
        factories["loading_vouchers"] = {
            "title": "سندات التحميل",
            "view": "logistics.loading_vouchers.view",
            "make": lambda: LoadingVoucherPage(),
        }
        factories["attachments"] = {
            "title": "المرفقات",
            "view": "crm.attachments.view",
            "make": lambda: AttachmentsPage(),
        }
        # «بون 2» — a second look over the SAME ``tawrid_tickets`` table as البون.
        # It has no TABLE_SPECS entry of its own (it reuses tawrid_tickets'), so it
        # is registered explicitly here instead of through the MODULES loop, which
        # would look up a spec under this key.
        factories["tawrid_tickets2"] = {
            "title": "بون 2 - التوريدات",
            "view": "tawrid.tawrid_tickets2.view",
            "make": lambda: TawridTickets2Screen(self.service),
        }
        # كشف حساب عميل — a read-only Tawrid report, not a CRUD table, so it is
        # registered explicitly here (like the dashboards) instead of through the
        # MODULES loop above, which requires a TABLE_SPECS entry the statement has
        # no table for.
        factories["tawrid_customer_statement"] = {
            "title": "كشف حساب عميل",
            "view": "tawrid.tawrid_customer_statement.view",
            "make": lambda: TawridCustomerStatementScreen(),
        }
        factories["tawrid_supplier_statement"] = {
            "title": "كشف حساب الكسارات",
            "view": "tawrid.tawrid_supplier_statement.view",
            "make": lambda: TawridSupplierStatementScreen(),
        }
        factories["tawrid_tractor_statement"] = {
            "title": "كشف حساب الجرارات",
            "view": "tawrid.tawrid_tractor_statement.view",
            "make": lambda: TawridTractorStatementScreen(),
        }
        factories["tawrid_comprehensive_report"] = {
            "title": "التقرير الشامل",
            "view": "tawrid.tawrid_comprehensive_report.view",
            "make": lambda: TawridComprehensiveReportScreen(),
        }
        factories["tawrid_treasury_statement"] = {
            "title": "كشف حساب الخزينة",
            "view": "tawrid.tawrid_treasury_statement.view",
            "make": lambda: TawridTreasuryStatementScreen(),
        }
        factories["backup"] = {
            "title": "إدارة النسخ الاحتياطي",
            "view": "backup.view",
            "make": lambda: BackupManagementScreen(),
        }
        factories["connection_settings"] = {
            "title": "إعدادات الاتصال",
            "view": "connection.settings.view",
            "make": lambda: ConnectionSettingsScreen(),
        }
        for key, label, cls in REPORTS:
            factories[key] = {
                "title": label,
                "view": f"reports.{key}.view",
                "make": (lambda c=cls: c()),
            }
        return factories

    def _can_view(self, key: str) -> bool:
        # The home dashboard, backup, and connection settings are always available.
        if key in ("crm_dashboard", "executive_dashboard", "backup", "connection_settings"):
            return True
        return SESSION.can(self._factories[key]["view"])

    # --- layout -------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())  # right side under RTL
        layout.addWidget(self._build_content_area(), 1)
        self.setCentralWidget(central)
        self._highlight("dashboard")  # home dashboard is selected by default

    PREWARM_ORDER = ("daily_followups", "customers", "suppliers", "workers", "expenses", "treasury_deposits", "products", "companies", "receipt_vouchers", "supplier_payment_vouchers", "worker_payment_vouchers", "worker_daily", "employees", "places", "case_statuses")

    def prewarm_all(self, progress: Callable[[int, int, str], None] | None = None) -> None:
        """Pre-build the CRM data screens the user may view so they open fast."""
        keys = [
            k for k in self.PREWARM_ORDER
            if self._can_view(k) and k not in HIDDEN_NAV_KEYS
        ]
        total = len(keys)
        for index, key in enumerate(keys, start=1):
            if progress is not None:
                progress(index, total, TABLE_SPECS[key].title)
                QApplication.processEvents()
            if key not in self.open_windows:
                try:
                    self._build_window(key)
                except Exception:
                    pass
        if progress is not None:
            progress(total or 1, total or 1, "")
            QApplication.processEvents()

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setFixedWidth(300)
        sidebar.setStyleSheet(f"QFrame {{ background:{GREEN_DARK}; }}")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(6)

        brand = QLabel("A-H CODE")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet(
            "color:#FFFFFF; font-size:17px; font-weight:900; background:transparent; "
            "padding:6px 0 14px 0; line-height:135%;"
        )
        layout.addWidget(brand)

        # Home dashboard button (always visible — it is the central home page).
        dashboard_button = self._make_home_button("لوحة التحكم", "🏠")
        dashboard_button.clicked.connect(self.show_dashboard)
        self.nav_buttons.append(dashboard_button)
        self._nav_by_key["dashboard"] = dashboard_button
        layout.addWidget(dashboard_button)

        crm_dashboard_button = self._make_home_button("داشبورد", "📊")
        crm_dashboard_button.clicked.connect(lambda _c=False: self.open_screen("crm_dashboard"))
        self.nav_buttons.append(crm_dashboard_button)
        self._nav_by_key["crm_dashboard"] = crm_dashboard_button
        layout.addWidget(crm_dashboard_button)

        exec_dashboard_button = self._make_home_button("الداشبورد التنفيذية", "🧭")
        exec_dashboard_button.clicked.connect(lambda _c=False: self.open_screen("executive_dashboard"))
        self.nav_buttons.append(exec_dashboard_button)
        self._nav_by_key["executive_dashboard"] = exec_dashboard_button
        layout.addWidget(exec_dashboard_button)

        # Collapsible sections (accordion). Whole sections in HIDDEN_NAV_SECTIONS
        # are skipped; items the user can't view are hidden; a section with no
        # visible item is dropped entirely.
        for section_id, title, icon, items in NAV_SECTIONS:
            if section_id in HIDDEN_NAV_SECTIONS:
                continue
            self._build_section(layout, section_id, title, icon, items)

        # Open the first non-empty section by default so the menu isn't all folded.
        for section_id, _t, _i, _items in NAV_SECTIONS:
            if section_id in self._sections and section_id in self._section_of_key.values():
                self._expand_section(section_id)
                break

        layout.addStretch(1)
        version = QLabel("")
        version.setStyleSheet("color:#BBF7D0; font-size:11px; background:transparent;")
        layout.addWidget(version)
        return sidebar

    # --- accordion sections -------------------------------------------------
    def _build_section(
        self,
        layout: QVBoxLayout,
        section_id: str,
        title: str,
        icon: str,
        items: tuple[tuple[str, str, str], ...],
    ) -> None:
        visible = [
            (k, lbl, ic)
            for k, lbl, ic in items
            if self._can_view(k) and k not in HIDDEN_NAV_KEYS
        ]
        if not visible and section_id not in KEEP_EMPTY_NAV_SECTIONS:
            return

        header = self._make_section_header(icon, title)
        header.clicked.connect(lambda _c=False, sid=section_id: self._toggle_section(sid))
        layout.addWidget(header)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 0, 10)
        body_layout.setSpacing(13)
        for key, label, item_icon in visible:
            item = self._make_section_item(item_icon, label)
            item.clicked.connect(lambda _c=False, k=key: self.open_screen(k))
            body_layout.addWidget(item)
            self.nav_buttons.append(item)
            self._nav_by_key[key] = item
            self._section_of_key[key] = section_id
        body.setVisible(False)
        layout.addWidget(body)

        self._sections[section_id] = {
            "header": header,
            "body": body,
            "expanded": False,
            "label": f"{icon}   {title}",
        }

    def _toggle_section(self, section_id: str) -> None:
        """Accordion: toggling a section folds every other open one."""
        if self._sections.get(section_id, {}).get("expanded"):
            self._collapse_section(section_id)
        else:
            self._expand_section(section_id)

    def _expand_section(self, section_id: str) -> None:
        for sid, sec in self._sections.items():
            expanded = sid == section_id
            sec["expanded"] = expanded
            sec["body"].setVisible(expanded)
            self._style_section_header(sec, expanded)

    def _collapse_section(self, section_id: str) -> None:
        sec = self._sections.get(section_id)
        if not sec:
            return
        sec["expanded"] = False
        sec["body"].setVisible(False)
        self._style_section_header(sec, False)

    def _style_section_header(self, sec: dict, expanded: bool) -> None:
        header = sec["header"]
        arrow = "▾" if expanded else "▸"
        header.setText(f"{arrow}   {sec['label']}")
        header.setStyleSheet(_SECTION_HEADER_OPEN if expanded else _SECTION_HEADER_BASE)

    def _make_section_header(self, icon: str, title: str) -> QPushButton:
        """A collapsible section header — a filled green pill when open."""
        button = QPushButton(f"▸   {icon}   {title}")
        button.setLayoutDirection(Qt.LeftToRight)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(46)
        button.setStyleSheet(_SECTION_HEADER_BASE)
        return button

    def _make_section_item(self, icon: str, label: str) -> QPushButton:
        """A nav item inside a section — a rounded pill; white when active."""
        button = QPushButton(f"{icon}   {label}")
        button.setLayoutDirection(Qt.LeftToRight)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(42)
        self._register_style(button, _SECTION_ITEM_BASE, _SECTION_ITEM_ACTIVE)
        return button

    # --- button factories ---------------------------------------------------
    def _register_style(self, button: QPushButton, base: str, active: str) -> None:
        self._button_styles[button] = (base, active)
        button.setStyleSheet(base)

    def _make_home_button(self, label: str, icon: str = "🏠") -> QPushButton:
        button = QPushButton(f"{icon}   {label}")
        button.setLayoutDirection(Qt.LeftToRight)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(44)
        base = (
            "QPushButton { text-align:left; color:#E8FBEF; background:transparent; border:none; "
            "border-radius:8px; padding:8px 14px; font-size:15px; font-weight:800; }"
            "QPushButton:hover { background:rgba(255,255,255,0.10); }"
        )
        active = (
            "QPushButton { text-align:left; color:#0F6B30; background:#FFFFFF; border:none; "
            "border-radius:8px; padding:8px 14px; font-size:15px; font-weight:900; }"
        )
        self._register_style(button, base, active)
        return button

    def _build_content_area(self) -> QWidget:
        """Central content area: hosts the home dashboard by default.

        The dashboard lives embedded here (left of the sidebar under RTL); the
        CRM data screens still open in their own maximized windows, which is the
        app's existing intentional behaviour.
        """
        area = QWidget()
        area.setStyleSheet("background:#F1F5F9;")
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        try:
            self.dashboard_page = DashboardPage()
            layout.addWidget(self.dashboard_page)
        except Exception as exc:  # never block the app if the dashboard fails
            self.dashboard_page = None
            hint = QLabel(f"تعذّر تحميل لوحة التحكم:\n{exc}")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet(
                "color:#94A3B8; font-size:15px; font-weight:700; background:transparent;"
            )
            layout.addStretch(1)
            layout.addWidget(hint)
            layout.addStretch(1)
        return area

    def show_dashboard(self) -> None:
        """Bring the home dashboard to the foreground and refresh its data."""
        if getattr(self, "dashboard_page", None) is not None:
            self.dashboard_page.refresh_dashboard()
        self._highlight("dashboard")

    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if event.type() == QEvent.WindowActivate:
            dashboard = getattr(self, "dashboard_page", None)
            if dashboard is not None:
                dashboard.refresh_dashboard()
        return result

    def closeEvent(self, event) -> None:  # noqa: ANN001 - Qt close event
        """Run the shutdown backup (if enabled) before the window closes.

        Fully guarded: a backup failure — or the backup module being unavailable
        — must never prevent the application from closing.
        """
        try:
            from app.services.backup_service import BackupService

            user = SESSION.user or {}
            created_by = user.get("id")
            try:
                created_by = int(created_by) if created_by is not None else None
            except (TypeError, ValueError):
                created_by = None
            BackupService().run_shutdown_backup(created_by=created_by)
        except Exception:
            pass
        super().closeEvent(event)

    # --- open / highlight ---------------------------------------------------
    def _build_window(self, key: str) -> QWidget:
        spec = self._factories[key]
        window = spec["make"]()
        window.setWindowTitle(f"KSA - {spec['title']}")
        window.setLayoutDirection(Qt.RightToLeft)
        window.destroyed.connect(lambda *_a, k=key: self.open_windows.pop(k, None))
        self.open_windows[key] = window
        self.live_lists.register(window)
        return window

    def open_screen(self, key: str) -> None:
        if not self._can_view(key):
            QMessageBox.warning(self, "غير مسموح", "ليس لديك صلاحية لفتح هذه الشاشة.")
            return
        try:
            window = self.open_windows.get(key)
            is_existing_window = window is not None
            if window is None:
                window = self._build_window(key)
        except Exception as exc:
            QMessageBox.critical(self, "تعذر فتح الشاشة", str(exc))
            return
        if is_existing_window:
            refresh = getattr(window, "refresh_dashboard", None)
            if callable(refresh):
                refresh()
        window.showMaximized()
        window.raise_()
        window.activateWindow()
        if is_existing_window:
            # Reopened from the sidebar: reload its lists (also catches other PCs' changes).
            self.live_lists.opened(window)
        self._highlight(key)

    def _highlight(self, key: str) -> None:
        # If the active screen lives inside a folded section, open that section so
        # its highlighted row is actually visible (accordion folds the others).
        owner = self._section_of_key.get(key)
        if owner is not None and not self._sections.get(owner, {}).get("expanded"):
            self._expand_section(owner)
        for button, (base, active) in self._button_styles.items():
            button.setStyleSheet(base)
        button = self._nav_by_key.get(key)
        if button is not None and button in self._button_styles:
            button.setStyleSheet(self._button_styles[button][1])
