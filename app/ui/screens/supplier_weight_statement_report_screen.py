"""Item-level Supplier Ledger screen — «وزن» variant (كشف حساب المورد وزن - تفصيلي).

Same detailed ledger as the «عدد» screen, differing only in نوع الحساب: it lists
«وزن» suppliers and its service adds the weight columns (الوزن / إجمالي الوزن) with
القيمة = إجمالي سعر الوزن. Everything else (layout, totals, print) is inherited.
"""

from __future__ import annotations

from app.repositories.supplier_statement_report_repository import ACCOUNT_TYPE_WEIGHT
from app.services.supplier_ledger_report_service import SupplierLedgerReportService
from app.ui.screens.supplier_ledger_report_screen import SupplierLedgerReportScreen


class SupplierWeightStatementReportScreen(SupplierLedgerReportScreen):
    REPORT_TITLE = "كشف حساب المورد (وزن)"
    SUBTITLE = "كشف حساب تفصيلي بالأصناف والأوزان والتحصيلات للموردين (نوع الحساب: وزن)"
    ACCOUNT_TYPE = ACCOUNT_TYPE_WEIGHT

    def _default_service(self):
        return SupplierLedgerReportService(account_type=self.ACCOUNT_TYPE)
