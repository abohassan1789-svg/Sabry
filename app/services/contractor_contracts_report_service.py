"""Data and arithmetic for تقرير عقود المقاولين (the first contracting report).

One row per contract, with the user's columns: العقد (``contract_label``: «رقم —
اسم», 2026-10-13)، تاريخ العقد، اسم الشركة، اسم المشروع، اسم المقاول، قيمة العقد، نسبة الدفعة المقدمة، إجمالي المستخلصات، إجمالي
المقدمة المستقطعة، المتبقي من قيمة العقد، المتبقي من الدفعة المقدمة.

* إجمالي المستخلصات = sum of the contract's ``works_value`` (إجمالي المستخلص).
* المقدمة المستقطعة = sum of each extract's «الدفعة المقدمة» line, computed by
  ``extract_amounts`` exactly as the extracts screen shows it.
* المتبقي من قيمة العقد = قيمة العقد − إجمالي المستخلصات.
* المصروف من الدفعات المقدمة = the approved «دفعة مقدمة» payments (شاشة الدفعات) that
  fall to the contract (user, 2026-10-13): one made on an extract goes to that
  extract's contract; a general one is split over the contractor's approved
  contracts on its project in proportion to each contract's advance
  (``allocate_advance_payments``).
* المتبقي من الدفعة المقدمة = قيمة العقد × نسبة المقدمة − المستقطعة − المصروف
  من الدفعات (the same rule as كشف حساب مقاول and شاشة الدفعات).

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
from app.services.contractor_contract_service import contract_label, to_decimal
from app.services.contractor_extract_service import extract_amounts
from app.services.contractor_payment_service import ADVANCE_PAYMENT

_CENT = Decimal("0.01")
ZERO = Decimal("0")

# Status of a contract, as shown in the «الحالة» column (نموذج 7).
STATUS_NOT_STARTED = "لم يبدأ"
STATUS_RUNNING = "جاري"
STATUS_DONE = "مكتمل"
STATUS_OVER = "تجاوز العقد"

# Keys summed by ``report_totals``.
TOTAL_KEYS = ("contract_value", "extracts_total", "advance_agreed", "advance_deducted",
              "advance_paid_out", "remaining_value", "remaining_advance")


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


def contract_agreed(contract: dict[str, Any]) -> Decimal:
    """قيمة العقد × نسبة الدفعة المقدمة, to the piaster."""
    value = _money(to_decimal(contract.get("contract_value")))
    return _money(value * to_decimal(contract.get("advance_payment_pct")) / 100)


def allocate_advance_payments(contracts: list[dict[str, Any]],
                              payments: list[dict[str, Any]]) -> dict[Any, list[dict[str, Any]]]:
    """``contract_id -> [payment + its «share»]``: which part of each دفعة مقدمة falls to which contract.

    *contracts* are every approved contract of the payments' contractors and projects.
    A payment on an extract (``contract_id`` set) goes whole to that extract's contract.
    A general one (user, 2026-10-13) is split over the contractor's contracts on its
    project in proportion to their advance (equally when none has one); the last
    contract takes the rounding rest, so the shares always add up to the payment.
    A payment that fits no contract (no project, or none there) is left out.
    """
    by_place: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for contract in contracts:
        by_place[(str(contract.get("contractor_id")), str(contract.get("project_id")))].append(contract)
    known = {str(contract.get("contract_id")) for contract in contracts}
    out: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for payment in payments:
        amount = _money(to_decimal(payment.get("amount")))
        if payment.get("contract_id") is not None and str(payment["contract_id"]) in known:
            out[payment["contract_id"]].append({**payment, "share": amount})
            continue
        targets = by_place.get((str(payment.get("contractor_id")), str(payment.get("project_id"))), [])
        if not targets:
            continue
        weights = [contract_agreed(contract) for contract in targets]
        whole = sum(weights, ZERO)
        if whole <= 0:
            weights, whole = [Decimal(1)] * len(targets), Decimal(len(targets))
        left = amount
        for index, (contract, weight) in enumerate(zip(targets, weights)):
            share = left if index == len(targets) - 1 else _money(amount * weight / whole)
            left -= share
            if share:
                out[contract["contract_id"]].append({**payment, "share": share})
    return out


def report_row(contract: dict[str, Any], extracts: list[dict[str, Any]],
               advance_payments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One report line: *contract* plus the figures of its *extracts* and its share of the
    دفعات مقدمة (*advance_payments*, from ``allocate_advance_payments``)."""
    value = _money(to_decimal(contract.get("contract_value")))
    pct = to_decimal(contract.get("advance_payment_pct"))
    works = _money(sum((to_decimal(x.get("works_value")) for x in extracts), ZERO))
    deducted = sum((extract_amounts(x)["advance_payment"] for x in extracts), ZERO)
    paid_out = sum((to_decimal(p.get("share")) for p in advance_payments or ()), ZERO)
    agreed = _money(value * pct / 100)
    return {
        **contract,
        "contract_label": contract_label(contract),
        "contract_value": value,
        "advance_payment_pct": pct,
        "extracts_count": len(extracts),
        "extracts_total": works,
        "advance_agreed": agreed,
        "advance_deducted": deducted,
        "advance_paid_out": paid_out,
        "remaining_value": value - works,
        "remaining_advance": agreed - deducted - paid_out,
        "executed_pct": _percent(works, value),
        # How much of the advance is used up: deducted by the extracts and paid out.
        "recovered_pct": _percent(deducted + paid_out, agreed),
        "status": contract_status(value, works, len(extracts)),
    }


def build_report(contracts: list[dict[str, Any]], extracts: list[dict[str, Any]],
                 advance: dict[Any, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    """Every contract's line; *extracts* are matched on ``contract_id``, *advance* is
    ``allocate_advance_payments``'s result."""
    by_contract: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for extract in extracts:
        by_contract[extract.get("contract_id")].append(extract)
    advance = advance or {}
    return [report_row(contract, by_contract.get(contract.get("contract_id"), []),
                       advance.get(contract.get("contract_id"), []))
            for contract in contracts]


def report_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {key: sum((row[key] for row in rows), ZERO) for key in TOTAL_KEYS}
    totals["count"] = len(rows)
    totals["executed_pct"] = _percent(totals["extracts_total"], totals["contract_value"])
    totals["recovered_pct"] = _percent(totals["advance_deducted"] + totals["advance_paid_out"],
                                       totals["advance_agreed"])
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
            "SELECT contractor_id, contractor_code, contractor_name, registration_no FROM contractors "
            "WHERE status = 'approved' ORDER BY contractor_code"
        )

    def contract_choices(self, company_id: Any = None, project_id: Any = None,
                         contractor_id: Any = None) -> list[dict[str, Any]]:
        """The «العقد» filter (2026-10-13): approved contracts under the other filters, with
        their ``contract_label``."""
        where, params = ["k.status = 'approved'"], []
        for clause, value in (("p.company_id = %s", company_id), ("k.project_id = %s", project_id),
                              ("k.contractor_id = %s", contractor_id)):
            if value not in (None, ""):
                where.append(clause)
                params.append(value)
        rows = self._db.fetch_all(
            "SELECT k.contract_id, k.contract_no, k.contract_name FROM contractor_contracts k "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "WHERE " + " AND ".join(where) + " ORDER BY k.contract_no",
            params,
        )
        return [{**row, "contract_label": contract_label(row)} for row in rows]

    def company_print_info(self, company_ids: list[Any]) -> list[dict[str, Any]]:
        """The print header of each company (user, 2026-10-14): name, address, السجل الضريبي
        and logo, from الشركات والمشاريع, in company-code order."""
        if not company_ids:
            return []
        return self._db.fetch_all(
            "SELECT company_id, company_code, company_name, address, tax_registration_no, logo, logo_mime "
            "FROM client_companies WHERE company_id = ANY(%s) ORDER BY company_code",
            [list(company_ids)],
        )

    # -- the report ------------------------------------------------------------

    def report(self, date_from: Any = None, date_to: Any = None, company_id: Any = None,
               project_id: Any = None, contractor_id: Any = None, contract_id: Any = None) -> list[dict[str, Any]]:
        """The report lines for the filters (``None`` = الكل), oldest contract first."""
        where, params = ["k.status = 'approved'"], []
        for clause, value in (("k.contract_date >= %s", date_from), ("k.contract_date <= %s", date_to),
                              ("p.company_id = %s", company_id), ("k.project_id = %s", project_id),
                              ("k.contractor_id = %s", contractor_id), ("k.contract_id = %s", contract_id)):
            if value not in (None, ""):
                where.append(clause)
                params.append(value)
        contracts = self._db.fetch_all(
            "SELECT k.contract_id, k.contract_no, k.contract_name, k.contract_date, k.contract_value, "
            "k.advance_payment_pct, k.contractor_id, d.contractor_name, k.project_id, p.project_name, p.company_id, c.company_name "
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
        return build_report(contracts, extracts, self.advance_allocation(contracts))

    def advance_allocation(self, contracts: list[dict[str, Any]]) -> dict[Any, list[dict[str, Any]]]:
        """The approved دفعات مقدمة of *contracts*' contractors and projects, split per contract.

        The split needs every approved contract of those contractors on those projects,
        not just the ones the filters kept (a period may hide a sibling contract)."""
        contractors = sorted({row["contractor_id"] for row in contracts})
        projects = sorted({row["project_id"] for row in contracts})
        siblings = self._db.fetch_all(
            "SELECT contract_id, contractor_id, project_id, contract_value, advance_payment_pct "
            "FROM contractor_contracts WHERE status = 'approved' "
            "AND contractor_id = ANY(%s) AND project_id = ANY(%s) ORDER BY contract_date, contract_no",
            [contractors, projects],
        )
        payments = self._db.fetch_all(
            "SELECT y.payment_id, y.payment_date, y.contractor_id, y.project_id, y.extract_id, y.amount, "
            "y.payment_method, y.reference_no, x.contract_id, x.extract_no "
            "FROM contractor_payments y LEFT JOIN contractor_extracts x ON x.extract_id = y.extract_id "
            "WHERE y.account_type = %s AND y.status = 'approved' "
            "AND y.contractor_id = ANY(%s) AND y.project_id = ANY(%s) "
            "ORDER BY y.payment_date, y.payment_id",
            [ADVANCE_PAYMENT, contractors, projects],
        )
        return allocate_advance_payments(siblings, payments)
