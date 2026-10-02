"""Item-level Supplier Ledger screen for «عدد» accounts (كشف حساب المورد - تفصيلي).

Reuses the whole layout of :class:`SupplierStatementReportScreen` (filters, table,
actions, exports) and overrides only what differs for the detailed ledger: the
service (item-level), the bottom totals (رصيد أول المدة / مشتريات / تحصيلات / المتبقي)
and the print module (the eight-column dashboard). The table columns come from the
service, so no column wiring is needed here.
"""

from __future__ import annotations

from typing import Any

from app.repositories.supplier_statement_report_repository import ACCOUNT_TYPE_COUNT
from app.services.supplier_ledger_report_service import SupplierLedgerReportService
from app.ui.screens.supplier_statement_report_screen import SupplierStatementReportScreen


class SupplierLedgerReportScreen(SupplierStatementReportScreen):
    REPORT_TITLE = "كشف حساب المورد"
    SUBTITLE = "كشف حساب تفصيلي بالأصناف والتحصيلات للموردين (نوع الحساب: عدد)"
    ACCOUNT_TYPE = ACCOUNT_TYPE_COUNT
    TOTALS_SPEC = (
        ("رصيد أول المدة", "total_opening_label"),
        ("إجمالي المشتريات", "total_purchases_label"),
        ("إجمالي التحصيلات", "total_collections_label"),
        ("الرصيد المتبقي", "remaining_label"),
    )

    def _default_service(self):
        return SupplierLedgerReportService(account_type=self.ACCOUNT_TYPE)

    # The ledger print template consumes the formatted export rows (they also carry
    # the ``kind`` used to colour the نوع العملية badge), not the numeric rows.
    def _statement_print_data(self) -> dict[str, Any]:
        data = super()._statement_print_data()
        result = self.current_result
        data["rows"] = result.export_rows if result else []
        data["columns"] = [(c.key, c.label) for c in self.service.columns]
        return data

    def _open_preview(self, data: dict[str, Any]) -> None:
        from app.ui.screens.supplier_ledger_print import SupplierLedgerPreviewDialog

        SupplierLedgerPreviewDialog(data, parent=self).exec()

    def _export_pdf_file(self, data: dict[str, Any]) -> None:
        from app.ui.screens.supplier_ledger_print import export_statement_to_pdf

        export_statement_to_pdf(self, data)

    def _print_document(self, data: dict[str, Any]) -> None:
        from app.ui.screens.supplier_ledger_print import print_statement

        print_statement(self, data)
