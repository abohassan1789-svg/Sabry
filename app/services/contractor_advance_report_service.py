"""Data for تقرير كشف حساب الدفعة المقدمة (نموذجان 7 و6, 2026-09-26).

One line per contract, with the user's columns: تاريخ العقد، اسم الشركة، اسم
المشروع، اسم المقاول، قيمة العقد، نسبة الدفعة المقدمة، قيمة الدفعة المقدمة من
العقد، إجمالي المسدد من الدفعة المقدمة (من المستخلصات)، المصروف من الدفعات
المقدمة (شاشة الدفعات, 2026-10-13)، المتبقي.

The lines and their figures are the contracts report's (``advance_agreed``,
``advance_deducted``, ``remaining_advance``); the period filters on تاريخ العقد
(user confirmed 2026-09-26). A click on a line lists the contract's extracts
with the advance each one took back (``extract_lines``) and, since 2026-10-13,
the دفعات مقدمة that fall to it (``payment_lines``), oldest first.
"""

from __future__ import annotations

from typing import Any

from app.services.contractor_contract_service import to_decimal
from app.services.contractor_contracts_report_service import ZERO, ContractorContractsReportService
from app.services.contractor_extract_service import extract_amounts


def extract_lines(contract: dict[str, Any], extracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The popup's lines: each extract of *contract*, oldest first (date, then number).

    Each line carries the contract's names, «إجمالي المستخلص», the extract's own
    advance rate and «قيمة الدفعة المقدمة» exactly as the extracts screen shows it.
    """
    lines = []
    for extract in sorted(extracts, key=lambda x: (x.get("extract_date") is None, x.get("extract_date"),
                                                  str(x.get("extract_no") or ""))):
        amounts = extract_amounts(extract)
        lines.append({
            "extract_id": extract.get("extract_id"),
            "extract_date": extract.get("extract_date"),
            "extract_no": extract.get("extract_no"),
            "contractor_name": contract.get("contractor_name"),
            "project_name": contract.get("project_name"),
            "company_name": contract.get("company_name"),
            "works_value": amounts["works_value"],
            "advance_payment_pct": to_decimal(extract.get("advance_payment_pct")),
            "advance_payment": amounts["advance_payment"],
        })
    return lines


PAYMENT_LINE = "payment"
PAYMENT_LABEL = "دفعة مقدمة"


def payment_lines(contract: dict[str, Any], payments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The popup's lines for the دفعات مقدمة of *contract* (``allocate_advance_payments``'s shares).

    They sit in the same columns as the extracts: the date, «دفعة مقدمة» (and the extract it
    was paid on) in place of the number, and the contract's part of the payment as the amount;
    a general payment split over several contracts says so."""
    lines = []
    for payment in payments:
        label = PAYMENT_LABEL
        if payment.get("extract_no"):
            label += f" — {str(payment['extract_no']).rsplit('/', 1)[-1]}"
        share, amount = to_decimal(payment.get("share")), to_decimal(payment.get("amount"))
        if share != amount:
            label += f" (جزء من {amount:,.2f})"
        lines.append({
            "kind": PAYMENT_LINE,
            "payment_id": payment.get("payment_id"),
            "extract_date": payment.get("payment_date"),
            "extract_no": label,
            "contractor_name": contract.get("contractor_name"),
            "project_name": contract.get("project_name"),
            "company_name": contract.get("company_name"),
            "works_value": None,
            "advance_payment_pct": None,
            "advance_payment": share,
        })
    return lines


def by_date(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extracts and payments together, oldest first (an extract before a payment on the same day)."""
    return sorted(lines, key=lambda line: (line.get("extract_date") is None, line.get("extract_date"),
                                           line.get("kind") == PAYMENT_LINE))


def lines_totals(lines: list[dict[str, Any]]) -> dict[str, Any]:
    extracts = [line for line in lines if line.get("kind") != PAYMENT_LINE]
    return {
        "count": len(extracts),
        "payments": len(lines) - len(extracts),
        "works_value": sum((to_decimal(line["works_value"]) for line in extracts), ZERO),
        "advance_payment": sum((to_decimal(line["advance_payment"]) for line in lines), ZERO),
    }


class ContractorAdvanceReportService(ContractorContractsReportService):
    """``report`` (the lines and filters) is the contracts report's; this adds the popup."""

    def contract_extracts(self, contract: dict[str, Any]) -> list[dict[str, Any]]:
        extracts = self._db.fetch_all(
            "SELECT extract_id, extract_no, extract_date, contract_id, works_value, vat_pct, advance_payment_pct, "
            "withholding_tax_pct, works_insurance_pct, social_insurance_pct, other_deductions "
            "FROM contractor_extracts WHERE contract_id = %s AND status = 'approved' "
            "ORDER BY extract_date, extract_no",
            [contract["contract_id"]],
        )
        payments = self.advance_allocation([contract]).get(contract["contract_id"], [])
        return by_date(extract_lines(contract, extracts) + payment_lines(contract, payments))
