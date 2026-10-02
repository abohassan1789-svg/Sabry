"""Purchase report (تقرير المشتريات) — permission target descriptor.

Like :mod:`app.reports.sales_report`, this module only exposes the report's
``PERMISSION_TARGET`` so the dynamic permissions registry
(``app/services/permission_registry.py``) discovers it automatically. The actual
data lives in ``app/repositories/purchase_report_repository.py`` +
``app/services/purchase_report_service.py`` and the screen in
``app/ui/screens/purchase_report_screen.py``.
"""


class PurchaseReport:
    report_code = 21
    access_report_name = "RepPurchases1"

    # Discovered automatically by the dynamic permissions registry.
    PERMISSION_TARGET = {
        "module_code": "reports",
        "module_name_ar": "التقارير",
        "module_name_en": "Reports",
        "target_code": "purchase_report",
        "target_name_ar": "تقرير المشتريات",
        "target_name_en": "Purchase Report",
    }
