"""Data and arithmetic for تقرير عقود المقاولين (the first contracting report).

One row per contract, with the user's columns: تاريخ العقد، اسم الشركة، اسم
المشروع، اسم المقاول، قيمة العقد، نسبة الدفعة المقدمة، إجمالي المستخلصات، إجمالي
المقدمة المستقطعة، المتبقي من قيمة العقد، المتبقي من الدفعة المقدمة.

* إجمالي المستخلصات = sum of the contract's ``works_value`` (إجمالي المستخلص).
* المقدمة المستقطعة = sum of each extract's «الدفعة المقدمة» line, computed by
  ``extract_amounts`` exactly as the extracts screen shows it.
* المتبقي من قيمة العقد = قيمة العقد − إجمالي المستخلصات.
* المتبقي من الدفعة المقدمة = قيمة العقد × نسبة المقدمة − المستقطعة (the same
  ``agreed`` as the extracts screen's «رصيد الدفعة المقدمة» strip).

Both remainders go negative, never clamped, when the extracts passed the contract
(user confirmed 2026-09-26). The period filters on تاريخ العقد; a contract's
extracts always count in full.

Drafts never show (مسودة / معتمد, 2026-10-02): the lines, the extracts behind
them and the filter choices are approved records only — and so are those of
every report built on this service.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.database.db import Database
from app.services.contractor_contract_service import to_decimal
from app.services.contractor_extract_service import extract_amounts

_CENT = Decimal("0.01")
ZERO = Decimal("0")

# Status of a contract, as shown in the «الحالة» column (نموذج 7).
STATUS_NOT_STARTED = "لم يبدأ"
STATUS_RUNNING = "جاري"
STATUS_DONE = "مكتمل"
STATUS_OVER = "تجاوز العقد"

# Keys summed by ``report_totals``.
TOTAL_KEYS = ("contract_value", "extracts_total", "advance_agreed", "advance_deducted",
              "remaining_value", "remaining_advance")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, ROUND_HALF_UP)


def _percent(part: Decimal, whole: Decimal) -> Decimal:
    return part / whole * 100 if whole > 0 else ZERO


def contract_status(contract_value: Decimal, extracts_total: Decimal, extracts_count: int) -> str:
    if extracts_count == 0:
        return STATUS_NOT_STARTED
    if extracts_total > contract_value:
        return STATUS_OVER
    if extracts_total == contract_value:
        return STATUS_DONE
    return STATUS_RUNNING


def report_row(contract: dict[str, Any], extracts: list[dict[str, Any]]) -> dict[str, Any]:
    """One report line: *contract* plus the figures of its *extracts*."""
    value = _money(to_decimal(contract.get("contract_value")))
    pct = to_decimal(contract.get("advance_payment_pct"))
    works = _money(sum((to_decimal(x.get("works_value")) for x in extracts), ZERO))
    deducted = sum((extract_amounts(x)["advance_payment"] for x in extracts), ZERO)
    agreed = _money(value * pct / 100)
    return {
        **contract,
        "contract_value": value,
        "advance_payment_pct": pct,
        "extracts_count": len(extracts),
        "extracts_total": works,
        "advance_agreed": agreed,
        "advance_deducted": deducted,
        "remaining_value": value - works,
        "remaining_advance": agreed - deducted,
        "executed_pct": _percent(works, value),
        "recovered_pct": _percent(deducted, agreed),
        "status": contract_status(value, works, len(extracts)),
    }


def build_report(contracts: list[dict[str, Any]], extracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every contract's line; *extracts* are matched on ``contract_id``."""
    by_contract: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for extract in extracts:
        by_contract[extract.get("contract_id")].append(extract)
    return [report_row(contract, by_contract.get(contract.get("contract_id"), [])) for contract in contracts]


def report_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {key: sum((row[key] for row in rows), ZERO) for key in TOTAL_KEYS}
    totals["count"] = len(rows)
    totals["executed_pct"] = _percent(totals["extracts_total"], totals["contract_value"])
    totals["recovered_pct"] = _percent(totals["advance_deducted"], totals["advance_agreed"])
    return totals


class ContractorContractsReportService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- filter choices ------------------------------------------------------

    def company_choices(self) -> list[dict[str, Any]]:
        return self._db.fetch_all(
            "SELECT company_id, company_code, company_name FROM client_companies "
            "WHERE status = 'approved' ORDER BY company_code"
        )

    def project_choices(self, company_id: Any = None) -> list[dict[str, Any]]:
        sql = ("SELECT project_id, project_code, project_name, company_id FROM company_projects "
               "WHERE status = 'approved' ")
        if company_id not in (None, ""):
            return self._db.fetch_all(sql + "AND company_id = %s ORDER BY project_code", [company_id])
        return self._db.fetch_all(sql + "ORDER BY project_code")

    def contractor_choices(self) -> list[dict[str, Any]]:
        return self._db.fetch_all(
            "SELECT contractor_id, contractor_code, contractor_name FROM contractors "
            "WHERE status = 'approved' ORDER BY contractor_code"
        )

    # -- the report ------------------------------------------------------------

    def report(self, date_from: Any = None, date_to: Any = None, company_id: Any = None,
               project_id: Any = None, contractor_id: Any = None) -> list[dict[str, Any]]:
        """The report lines for the filters (``None`` = الكل), oldest contract first."""
        where, params = ["k.status = 'approved'"], []
        for clause, value in (("k.contract_date >= %s", date_from), ("k.contract_date <= %s", date_to),
                              ("p.company_id = %s", company_id), ("k.project_id = %s", project_id),
                              ("k.contractor_id = %s", contractor_id)):
            if value not in (None, ""):
                where.append(clause)
                params.append(value)
        contracts = self._db.fetch_all(
            "SELECT k.contract_id, k.contract_no, k.contract_date, k.contract_value, k.advance_payment_pct, "
            "k.contractor_id, d.contractor_name, k.project_id, p.project_name, p.company_id, c.company_name "
            "FROM contractor_contracts k "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "JOIN client_companies c ON c.company_id = p.company_id "
            + "WHERE " + " AND ".join(where) + " "
            + "ORDER BY k.contract_date, k.contract_no",
            params,
        )
        if not contracts:
            return []
        extracts = self._db.fetch_all(
            "SELECT contract_id, works_value, vat_pct, advance_payment_pct, withholding_tax_pct, "
            "works_insurance_pct, social_insurance_pct, other_deductions "
            "FROM contractor_extracts WHERE contract_id = ANY(%s) AND status = 'approved'",
            [[row["contract_id"] for row in contracts]],
        )
        return build_report(contracts, extracts)
