"""Data access for شاشة عقود المقاولين — one contract ties a contractor to a project.

Table ``contractor_contracts``; the company is read through the project
(``company_projects.company_id``), never stored, so the two cannot disagree.

Codes: «A-H/CT-1001», «A-H/CT-1002», ... The screen suggests the next one, the
user may edit it, and only uniqueness (trimmed, any case) is enforced.

The four rates are percentages of the contract value. ``contract_amounts``
turns them into money: الصافي = القيمة − (تأمين الأعمال + الضرائب والخصم +
التأمينات الاجتماعية); the advance payment is shown on its own, not deducted.

مسودة / معتمد (``contracting_approval``): «حفظ» keeps a contract as a draft;
only approved contractors, companies and projects are offered; an approved
contract is edited or deleted only after «إلغاء الاعتماد» (or by an admin).
The contractor bar counts approved contracts only.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.database.db import Database
from app.services import contracting_approval as approval

CONTRACT_PREFIX = "A-H/CT-"
FIRST_CONTRACT_NUMBER = 1001

# (column, label) in the order the screen shows them.
RATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("advance_payment_pct", "نسبة الدفعة المقدمة"),
    ("works_insurance_pct", "نسبة تأمين الأعمال"),
    ("tax_discount_pct", "نسبة الضرائب والخصم"),
    ("social_insurance_pct", "نسبة التأمينات الاجتماعية"),
)
# The rates subtracted from the value to reach الصافي.
DEDUCTION_FIELDS = ("works_insurance_pct", "tax_discount_pct", "social_insurance_pct")

_CONTRACT_PATTERN = re.compile(r"^\s*A-H/CT-(\d+)\s*$", re.IGNORECASE)
_CENT = Decimal("0.01")

_CONTRACT_SELECT = (
    "SELECT k.contract_id, k.contract_no, k.contract_date, k.contractor_id, k.project_id, "
    "k.contract_value, k.advance_payment_pct, k.works_insurance_pct, k.tax_discount_pct, "
    "k.social_insurance_pct, k.status, "
    "d.contractor_code, d.contractor_name, "
    "p.project_code, p.project_name, p.company_id, c.company_code, c.company_name "
    "FROM contractor_contracts k "
    "JOIN contractors d ON d.contractor_id = k.contractor_id "
    "JOIN company_projects p ON p.project_id = k.project_id "
    "JOIN client_companies c ON c.company_id = p.company_id "
)


class ContractError(ValueError):
    """A rule the user broke (duplicate number, missing project, ...): shown as-is."""


def next_contract_no_from(codes: list[Any]) -> str:
    """The number after the highest «A-H/CT-<n>» in *codes*, never below 1001."""
    highest = FIRST_CONTRACT_NUMBER - 1
    for code in codes:
        match = _CONTRACT_PATTERN.match(str(code or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{CONTRACT_PREFIX}{highest + 1}"


def to_decimal(value: Any) -> Decimal:
    """Read a typed number («2,500,000.00», «10», «»). Blank or junk is zero."""
    text = str(value if value is not None else "").replace(",", "").replace("%", "").strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def contract_amounts(value: Any, rates: dict[str, Any]) -> dict[str, Decimal]:
    """Each rate's amount, the deductions total and الصافي, rounded to piasters."""
    base = to_decimal(value)
    amounts = {
        key: (base * to_decimal(rates.get(key)) / Decimal(100)).quantize(_CENT, ROUND_HALF_UP)
        for key, _label in RATE_FIELDS
    }
    deductions = sum((amounts[key] for key in DEDUCTION_FIELDS), Decimal("0"))
    amounts["deductions"] = deductions
    amounts["net"] = base.quantize(_CENT, ROUND_HALF_UP) - deductions
    return amounts


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


class ContractorContractService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- choices -----------------------------------------------------------

    def contractor_choices(self) -> list[dict[str, Any]]:
        return self._db.fetch_all(
            "SELECT contractor_id, contractor_code, contractor_name, contractor_type "
            "FROM contractors WHERE status = 'approved' ORDER BY contractor_code"
        )

    def company_choices(self) -> list[dict[str, Any]]:
        return self._db.fetch_all(
            "SELECT company_id, company_code, company_name FROM client_companies "
            "WHERE status = 'approved' ORDER BY company_code"
        )

    def project_choices(self, company_id: Any) -> list[dict[str, Any]]:
        if company_id in (None, ""):
            return []
        return self._db.fetch_all(
            "SELECT project_id, project_code, project_name FROM company_projects "
            "WHERE company_id = %s AND status = 'approved' ORDER BY project_code",
            [company_id],
        )

    # -- reading -----------------------------------------------------------

    def contracts(self, keyword: str = "", contractor_id: Any = None) -> list[dict[str, Any]]:
        """Contracts with their contractor / project / company, newest number last.

        *keyword* matches the number, the contractor, the project or the company.
        """
        where, params = [], []
        if contractor_id not in (None, ""):
            where.append("k.contractor_id = %s")
            params.append(contractor_id)
        needle = _clean(keyword)
        if needle:
            where.append(
                "concat_ws(' ', k.contract_no, d.contractor_code, d.contractor_name, "
                "p.project_code, p.project_name, c.company_code, c.company_name) ILIKE %s"
            )
            params.append(f"%{needle}%")
        sql = _CONTRACT_SELECT + (f"WHERE {' AND '.join(where)} " if where else "") + "ORDER BY k.contract_no"
        return self._db.fetch_all(sql, params)

    def tree(self, keyword: str = "") -> list[dict[str, Any]]:
        """company → ``projects`` → ``contracts``, for the tree tab.

        Without a keyword every company and project shows, even with no
        contracts (so «عقد جديد» can start from any project). With one, only the
        branches that lead to a matching contract stay.
        """
        contracts = self.contracts(keyword)
        by_project: dict[Any, list[dict[str, Any]]] = {}
        for contract in contracts:
            by_project.setdefault(contract["project_id"], []).append(dict(contract))

        companies = self.company_choices()
        projects = self._db.fetch_all(
            "SELECT project_id, company_id, project_code, project_name FROM company_projects "
            "WHERE status = 'approved' ORDER BY project_code"
        )
        filtering = bool(_clean(keyword))
        projects_by_company: dict[Any, list[dict[str, Any]]] = {}
        for project in projects:
            kids = by_project.get(project["project_id"], [])
            if filtering and not kids:
                continue
            projects_by_company.setdefault(project["company_id"], []).append(dict(project, contracts=kids))

        result = []
        for company in companies:
            kids = projects_by_company.get(company["company_id"], [])
            if filtering and not kids:
                continue
            result.append(dict(company, projects=kids))
        return result

    def get_contract(self, contract_id: Any) -> dict[str, Any] | None:
        return self._db.fetch_one(_CONTRACT_SELECT + "WHERE k.contract_id = %s", [contract_id])

    def contractor_card(self, contractor_id: Any) -> dict[str, Any] | None:
        """The contractor plus the count and totals of his contracts (tab 8's bar)."""
        return self._db.fetch_one(
            "SELECT d.contractor_id, d.contractor_code, d.contractor_name, d.contractor_type, d.phone, "
            "count(k.contract_id) AS contract_count, "
            "COALESCE(sum(k.contract_value), 0) AS total_value, "
            "COALESCE(sum(round(k.contract_value * k.advance_payment_pct / 100, 2)), 0) AS total_advance "
            "FROM contractors d LEFT JOIN contractor_contracts k "
            "ON k.contractor_id = d.contractor_id AND k.status = 'approved' "
            "WHERE d.contractor_id = %s "
            "GROUP BY d.contractor_id, d.contractor_code, d.contractor_name, d.contractor_type, d.phone",
            [contractor_id],
        )

    # -- codes -------------------------------------------------------------

    def next_contract_no(self) -> str:
        rows = self._db.fetch_all("SELECT contract_no FROM contractor_contracts")
        return next_contract_no_from([row["contract_no"] for row in rows])

    def _no_taken(self, contract_no: str, except_id: Any) -> bool:
        row = self._db.fetch_one(
            "SELECT contract_id FROM contractor_contracts WHERE upper(btrim(contract_no)) = upper(btrim(%s)) "
            "AND (%s::integer IS NULL OR contract_id <> %s::integer) LIMIT 1",
            [contract_no, except_id, except_id],
        )
        return row is not None

    # -- writing -----------------------------------------------------------

    def save_contract(self, data: dict[str, Any], contract_id: Any = None, allow_approved: bool = False) -> int:
        """Insert (as a draft) or update a contract; *allow_approved* lets an admin edit an approved one."""
        approval.check_unlocked(self._db, approval.CONTRACT, contract_id, "تعديل", allow_approved)
        contract_no = _clean(data.get("contract_no"))
        if not contract_no:
            raise ContractError("رقم العقد مطلوب.")
        if data.get("contractor_id") in (None, ""):
            raise ContractError("اختار المقاول.")
        if data.get("project_id") in (None, ""):
            raise ContractError("اختار الشركة والمشروع.")
        if not data.get("contract_date"):
            raise ContractError("تاريخ العقد مطلوب.")
        value = to_decimal(data.get("contract_value"))
        if value <= 0:
            raise ContractError("اكتب قيمة العقد.")
        rates = []
        for key, label in RATE_FIELDS:
            rate = to_decimal(data.get(key))
            if rate < 0 or rate > 100:
                raise ContractError(f"{label} لازم تكون بين 0 و 100.")
            rates.append(rate)
        if self._no_taken(contract_no, contract_id):
            raise ContractError(f"رقم العقد «{contract_no}» مستخدم لعقد تاني. غيّر الرقم قبل الحفظ.")
        approval.check_parents(self._db, [(approval.CONTRACTOR, data["contractor_id"]),
                                          (approval.PROJECT, data["project_id"])])

        params = [contract_no, data["contract_date"], data["contractor_id"], data["project_id"], value, *rates]
        if contract_id is None:
            row = self._db.fetch_one(
                "INSERT INTO contractor_contracts (contract_no, contract_date, contractor_id, project_id, "
                "contract_value, advance_payment_pct, works_insurance_pct, tax_discount_pct, social_insurance_pct) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING contract_id",
                params,
            )
            return int(row["contract_id"])
        self._db.execute(
            "UPDATE contractor_contracts SET contract_no = %s, contract_date = %s, contractor_id = %s, "
            "project_id = %s, contract_value = %s, advance_payment_pct = %s, works_insurance_pct = %s, "
            "tax_discount_pct = %s, social_insurance_pct = %s WHERE contract_id = %s",
            params + [contract_id],
        )
        return int(contract_id)

    def delete_contract(self, contract_id: Any, allow_approved: bool = False) -> None:
        approval.check_unlocked(self._db, approval.CONTRACT, contract_id, "حذف", allow_approved)
        count = self._db.fetch_one(
            "SELECT count(*) AS n FROM contractor_extracts WHERE contract_id = %s", [contract_id]
        )
        if count and int(count["n"]):
            raise ContractError(f"العقد ده عليه {int(count['n'])} مستخلص. احذف المستخلصات الأول.")
        self._db.execute("DELETE FROM contractor_contracts WHERE contract_id = %s", [contract_id])

    # -- مسودة / معتمد -------------------------------------------------------

    def approve(self, contract_id: Any, user_id: Any = None) -> None:
        approval.approve(self._db, approval.CONTRACT, contract_id, user_id)

    def unapprove(self, contract_id: Any) -> None:
        approval.unapprove(self._db, approval.CONTRACT, contract_id)
