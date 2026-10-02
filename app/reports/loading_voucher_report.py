"""Loading Vouchers report (تقرير سندات التحميل) — permission target descriptor.

Like :mod:`app.reports.purchase_report`, this module only exposes the report's
``PERMISSION_TARGET`` so the dynamic permissions registry
(``app/services/permission_registry.py``) discovers it automatically. The actual
data lives in ``app/repositories/loading_voucher_report_repository.py`` +
``app/services/loading_voucher_report_service.py`` and the screen in
``app/ui/screens/loading_voucher_report_screen.py``.
"""


class LoadingVoucherReport:
    report_code = 22
    access_report_name = "RepLoadingVouchers1"

    # Discovered automatically by the dynamic permissions registry.
    PERMISSION_TARGET = {
        "module_code": "reports",
        "module_name_ar": "التقارير",
        "module_name_en": "Reports",
        "target_code": "loading_voucher_report",
        "target_name_ar": "تقرير سندات التحميل",
        "target_name_en": "Loading Vouchers Report",
    }
