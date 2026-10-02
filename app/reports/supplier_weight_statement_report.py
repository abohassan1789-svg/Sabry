"""Supplier Statement (weight) report metadata (كشف حساب المورد - وزن).

Discovered automatically by ``permission_registry._discover_report_targets`` via
its ``PERMISSION_TARGET`` dict, so the report joins the permissions matrix on the
next sync. Metadata only — no logic here.
"""


class SupplierWeightStatementReport:
    PERMISSION_TARGET = {
        "module_code": "reports",
        "module_name_ar": "التقارير",
        "module_name_en": "Reports",
        "target_code": "supplier_weight_statement",
        "target_name_ar": "كشف حساب المورد (وزن)",
        "target_name_en": "Supplier Statement (Weight)",
    }
