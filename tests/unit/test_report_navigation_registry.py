from app.ui.main_window import REPORT_SCREEN_BY_KEY, REPORTS
from app.ui.screens.customer_statement_report_screen import CustomerStatementReportScreen
from app.ui.screens.production_order_report_screen import ProductionOrderReportScreen
from app.ui.screens.sales_report_screen import SalesReportScreen
from app.ui.screens.purchase_report_screen import PurchaseReportScreen
from app.ui.screens.loading_voucher_report_screen import LoadingVoucherReportScreen
from app.ui.screens.profit_report_screen import ProfitReportScreen
from app.ui.screens.raw_material_balance_screen import RawMaterialBalanceScreen
from app.ui.screens.finished_goods_balance_screen import FinishedGoodsBalanceScreen


def test_only_live_reports_are_registered_for_navigation():
    # Per product decision, the Follow-up Smart Report and the Status Analysis
    # report are hidden from the Reports menu; the production-orders report
    # (تقرير أوامر الإنتاج), the customer/supplier statements, the sales report
    # (تقرير المبيعات), the purchase report (تقرير المشتريات), the profit report
    # (تقرير الأرباح), the raw-material warehouse (مخزن مواد الخام) and the
    # finished-goods warehouse (مخزن الإنتاج التام) are navigable.
    keys = [key for key, _label, _cls in REPORTS]

    assert keys == [
        "production_order_report", "loading_voucher_report",
        "customer_statement", "supplier_statement", "supplier_weight_statement",
        "sales_report", "purchase_report", "profit_report", "raw_material_balance",
        "finished_goods_balance",
    ]
    assert REPORT_SCREEN_BY_KEY["production_order_report"] is ProductionOrderReportScreen
    assert REPORT_SCREEN_BY_KEY["loading_voucher_report"] is LoadingVoucherReportScreen
    assert REPORT_SCREEN_BY_KEY["customer_statement"] is CustomerStatementReportScreen
    assert REPORT_SCREEN_BY_KEY["sales_report"] is SalesReportScreen
    assert REPORT_SCREEN_BY_KEY["purchase_report"] is PurchaseReportScreen
    assert REPORT_SCREEN_BY_KEY["profit_report"] is ProfitReportScreen
    assert REPORT_SCREEN_BY_KEY["raw_material_balance"] is RawMaterialBalanceScreen
    assert REPORT_SCREEN_BY_KEY["finished_goods_balance"] is FinishedGoodsBalanceScreen
    assert "daily_followup_smart_report" not in keys
    assert "status_analysis_report" not in keys
