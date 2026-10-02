"""Data and arithmetic for داشبورد المقاولين (نموذجا 9 و 8, 2026-10-02).

One figure set per screen of «المقاولات», as the user listed them:

* المقاولين: the count, الرصيد الجاري (رصيد أول المدة) and the four typed
  amounts: ضرائب الخصم والإضافة، التأمينات الاجتماعية، تأمين الأعمال، الخصومات الأخرى.
* الشركات والمشاريع: the companies and how many projects each one has.
* العقود: the count, أكبر عقد (its contractor and value), and value × each of the
  contract's four rates (``contract_amounts``).
* المستخلصات: every amount of ``extract_amounts``, summed.
* الدفعات: the total paid and the contractor paid the most.

Added in the mockups and kept: «المتبقي للمقاولين» = صافي المستخلصات − الدفعات,
and the payments per طريقة الدفع.

The filters: the period narrows each record by its own date (تاريخ العقد، تاريخ
المستخلص، تاريخ الدفعة). Contractors have no date, so their figures ignore it. The
company / project / contractor filters narrow everything; a company or project
filter keeps only the contractors with a contract there.

Approved records only (مسودة / معتمد, 2026-10-02): no draft contractor,
company, project, contract, extract or payment counts anywhere.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.contractor_contract_service import contract_amounts, to_decimal
from app.services.contractor_contracts_report_service import ZERO, ContractorContractsReportService, _money
from app.services.contractor_extract_service import extract_amounts

CONTRACTOR_TYPES = ("مقاول", "مورد", "استشاري", "دعاية وإعلان")
PAYMENT_METHODS = ("نقدي", "شيك", "تحويل")

# contractors column → dashboard key
CONTRACTOR_AMOUNTS = (
    ("current_balance", "balance"),
    ("withholding_tax_amount", "withholding_tax"),
    ("social_insurance_amount", "social_insurance"),
    ("works_insurance_amount", "works_insurance"),
    ("other_deductions_amount", "other_deductions"),
)
CONTRACT_RATE_KEYS = ("advance_payment_pct", "works_insurance_pct", "tax_discount_pct", "social_insurance_pct")
EXTRACT_KEYS = ("works_value", "before_tax", "advance_payment", "withholding_tax", "works_insurance",
                "social_insurance", "other_deductions", "deductions", "net")


def _sum(rows: list[dict[str, Any]], key: str) -> Any:
    return sum((row[key] for row in rows), ZERO)


def contractors_figures(contractors: list[dict[str, Any]]) -> dict[str, Any]:
    figures: dict[str, Any] = {
        key: sum((_money(to_decimal(c.get(column))) for c in contractors), ZERO)
        for column, key in CONTRACTOR_AMOUNTS
    }
    figures["count"] = len(contractors)
    figures["deductions"] = (figures["withholding_tax"] + figures["social_insurance"]
                             + figures["works_insurance"] + figures["other_deductions"])
    types = {name: 0 for name in CONTRACTOR_TYPES}
    for contractor in contractors:
        kind = str(contractor.get("contractor_type") or "")
        types[kind] = types.get(kind, 0) + 1
    figures["types"] = types
    return figures


def companies_figures(companies: list[dict[str, Any]], projects: list[dict[str, Any]]) -> dict[str, Any]:
    per_company: dict[Any, int] = defaultdict(int)
    for project in projects:
        per_company[project.get("company_id")] += 1
    return {
        "count": len(companies),
        "projects": len(projects),
        "per_company": [(c.get("company_name"), per_company.get(c.get("company_id"), 0)) for c in companies],
    }


def contracts_figures(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    lines = []
    for contract in contracts:
        value = _money(to_decimal(contract.get("contract_value")))
        amounts = contract_amounts(value, {key: contract.get(key) for key in CONTRACT_RATE_KEYS})
        lines.append({**contract, "contract_value": value, **{key: amounts[key] for key in CONTRACT_RATE_KEYS}})
    ranking = sorted(lines, key=lambda line: (-line["contract_value"], str(line.get("contract_no") or "")))
    return {
        "count": len(lines),
        "value": _sum(lines, "contract_value"),
        "advance": _sum(lines, "advance_payment_pct"),
        "works_insurance": _sum(lines, "works_insurance_pct"),
        "tax": _sum(lines, "tax_discount_pct"),
        "social": _sum(lines, "social_insurance_pct"),
        "biggest": ranking[0] if ranking else None,
        "ranking": ranking,
    }


def extracts_figures(extracts: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [{**x, **extract_amounts(x)} for x in extracts]
    figures: dict[str, Any] = {key: _sum(lines, key) for key in EXTRACT_KEYS}
    figures["count"] = len(lines)
    by_contractor: dict[str, Any] = defaultdict(lambda: ZERO)
    for line in lines:
        by_contractor[str(line.get("contractor_name") or "")] += line["net"]
    figures["ranking"] = sorted(by_contractor.items(), key=lambda item: (-item[1], item[0]))
    return figures


def payments_figures(payments: list[dict[str, Any]]) -> dict[str, Any]:
    total, counts = defaultdict(lambda: ZERO), defaultdict(int)
    methods = {method: [ZERO, 0] for method in PAYMENT_METHODS}
    for payment in payments:
        amount = _money(to_decimal(payment.get("amount")))
        name = str(payment.get("contractor_name") or "")
        total[name] += amount
        counts[name] += 1
        method = methods.setdefault(str(payment.get("payment_method") or ""), [ZERO, 0])
        method[0] += amount
        method[1] += 1
    ranking = sorted(((name, amount, counts[name]) for name, amount in total.items()),
                     key=lambda item: (-item[1], item[0]))
    return {
        "count": len(payments),
        "total": sum(total.values(), ZERO),
        "methods": {name: tuple(value) for name, value in methods.items()},
        "top": ranking[0] if ranking else None,
        "ranking": ranking,
    }


def build_dashboard(contractors: list[dict[str, Any]], companies: list[dict[str, Any]],
                    projects: list[dict[str, Any]], contracts: list[dict[str, Any]],
                    extracts: list[dict[str, Any]], payments: list[dict[str, Any]]) -> dict[str, Any]:
    dashboard = {
        "contractors": contractors_figures(contractors),
        "companies": companies_figures(companies, projects),
        "contracts": contracts_figures(contracts),
        "extracts": extracts_figures(extracts),
        "payments": payments_figures(payments),
    }
    dashboard["payments"]["remaining"] = dashboard["extracts"]["net"] - dashboard["payments"]["total"]
    return dashboard


def empty_dashboard() -> dict[str, Any]:
    return build_dashboard([], [], [], [], [], [])


class ContractorsDashboardService(ContractorContractsReportService):
    """The filter choices are the contracts report's."""

    def dashboard(self, date_from: Any = None, date_to: Any = None, company_id: Any = None,
                  project_id: Any = None, contractor_id: Any = None) -> dict[str, Any]:
        def where(date_column: str | None, company: str, project: str, contractor: str | None,
                  approved: tuple[str, ...] = ()):
            """The filters as a WHERE clause; each alias in *approved* must be an approved row."""
            clauses, params = [f"{alias}.status = 'approved'" for alias in approved], []
            pairs = [(company, company_id), (project, project_id)]
            if contractor:
                pairs.append((contractor, contractor_id))
            if date_column:
                pairs += [(f"{date_column} >= %s", date_from), (f"{date_column} <= %s", date_to)]
            for clause, value in pairs:
                if value not in (None, ""):
                    clauses.append(clause if "%s" in clause else f"{clause} = %s")
                    params.append(value)
            return ("WHERE " + " AND ".join(clauses) + " " if clauses else ""), params

        sql, params = where(None, "p.company_id", "k.project_id", None, ("k",))
        scoped = company_id not in (None, "") or project_id not in (None, "")
        contractor_sql = ("SELECT d.contractor_id, d.contractor_name, d.contractor_type, d.current_balance, "
                          "d.withholding_tax_amount, d.social_insurance_amount, d.works_insurance_amount, "
                          "d.other_deductions_amount FROM contractors d ")
        clauses, contractor_params = ["d.status = 'approved'"], []
        if contractor_id not in (None, ""):
            clauses.append("d.contractor_id = %s")
            contractor_params.append(contractor_id)
        if scoped:
            clauses.append("d.contractor_id IN (SELECT k.contractor_id FROM contractor_contracts k "
                           "JOIN company_projects p ON p.project_id = k.project_id " + sql + ")")
            contractor_params += params
        contractors = self._db.fetch_all(
            contractor_sql + "WHERE " + " AND ".join(clauses) + " ORDER BY d.contractor_code",
            contractor_params,
        )

        company_where, company_params = where(None, "c.company_id", "p.project_id", None, ("p", "c"))
        projects = self._db.fetch_all(
            "SELECT p.project_id, p.company_id FROM company_projects p "
            "JOIN client_companies c ON c.company_id = p.company_id " + company_where,
            company_params,
        )
        if project_id not in (None, ""):
            company_ids = {p["company_id"] for p in projects}
            companies = [c for c in self.company_choices() if c["company_id"] in company_ids]
        elif company_id not in (None, ""):
            companies = [c for c in self.company_choices() if c["company_id"] == company_id]
        else:
            companies = self.company_choices()

        sql, params = where("k.contract_date", "p.company_id", "k.project_id", "k.contractor_id", ("k",))
        contracts = self._db.fetch_all(
            "SELECT k.contract_id, k.contract_no, k.contract_date, k.contract_value, k.advance_payment_pct, "
            "k.works_insurance_pct, k.tax_discount_pct, k.social_insurance_pct, d.contractor_name, p.project_name "
            "FROM contractor_contracts k "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id " + sql,
            params,
        )
        sql, params = where("x.extract_date", "p.company_id", "k.project_id", "k.contractor_id", ("x", "k"))
        extracts = self._db.fetch_all(
            "SELECT x.extract_id, x.works_value, x.vat_pct, x.advance_payment_pct, x.withholding_tax_pct, "
            "x.works_insurance_pct, x.social_insurance_pct, x.other_deductions, d.contractor_name "
            "FROM contractor_extracts x "
            "JOIN contractor_contracts k ON k.contract_id = x.contract_id "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id " + sql,
            params,
        )
        sql, params = where("y.payment_date", "p.company_id", "y.project_id", "y.contractor_id", ("y",))
        payments = self._db.fetch_all(
            "SELECT y.payment_id, y.amount, y.payment_method, d.contractor_name "
            "FROM contractor_payments y "
            "JOIN contractors d ON d.contractor_id = y.contractor_id "
            "JOIN company_projects p ON p.project_id = y.project_id " + sql,
            params,
        )
        return build_dashboard(contractors, companies, projects, contracts, extracts, payments)
