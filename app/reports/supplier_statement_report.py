"""Supplier Statement report metadata (كشف حساب المورد).

Discovered automatically by ``permission_registry._discover_report_targets`` via
its ``PERMISSION_TARGET`` dict, so the report joins the permissions matrix on the
next sync. Metadata only — no logic here.
"""


class SupplierStatementReport:
    PERMISSION_TARGET = {
        "module_code": "reports",
        "module_name_ar": "التقارير",
        "module_name_en": "Reports",
        "target_code": "supplier_statement",
        "target_name_ar": "كشف حساب المورد",
        "target_name_en": "Supplier Statement",
    }
