"""Data and arithmetic for تقرير مستخلصات المقاولين (نموذج 6, 2026-09-26).

One row per extract, with the user's columns: تاريخ المستخلص، اسم الشركة، اسم
المشروع، اسم المقاول، رقم المستخلص، إجمالي المستخلص، نسبة الضريبة، صافي الأعمال،
نسبة وقيمة كل من الدفعة المقدمة وضرائب الخصم وتأمين الأعمال والتأمينات
الاجتماعية، خصومات أخرى، صافي المستخلص.

Every amount comes from ``extract_amounts`` so the report shows exactly what the
extracts screen shows. The period filters on تاريخ المستخلص. Approved extracts
only (مسودة / معتمد, 2026-10-02). Rows can be grouped
by contractor, company or project, each group with its own totals.
"""

from __future__ import annotations

from typing import Any

from app.services.contractor_contract_service import to_decimal
from app.services.contractor_contracts_report_service import ZERO, ContractorContractsReportService
from app.services.contractor_extract_service import extract_amounts

# The amount columns, summed by ``report_totals`` and shown on the cards.
AMOUNT_KEYS = ("works_value", "before_tax", "advance_payment", "withholding_tax", "works_insurance",
               "social_insurance", "other_deductions", "net")
RATE_KEYS = ("vat_pct", "advance_payment_pct", "withholding_tax_pct", "works_insurance_pct", "social_insurance_pct")

GROUP_NONE, GROUP_CONTRACTOR, GROUP_COMPANY, GROUP_PROJECT = "none", "contractor", "company", "project"
# group mode → (row key that identifies the group, row key of its name)
GROUP_KEYS = {
    GROUP_CONTRACTOR: ("contractor_id", "contractor_name"),
    GROUP_COMPANY: ("company_id", "company_name"),
    GROUP_PROJECT: ("project_id", "project_name"),
}


def report_row(extract: dict[str, Any]) -> dict[str, Any]:
    """One report line: the extract's own fields, its rates and every computed amount."""
    amounts = extract_amounts(extract)
    row = {**extract, **{key: to_decimal(extract.get(key)) for key in RATE_KEYS}}
    row.update({key: amounts[key] for key in AMOUNT_KEYS})
    return row


def report_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {key: sum((row[key] for row in rows), ZERO) for key in AMOUNT_KEYS}
    totals["count"] = len(rows)
    return totals


def group_rows(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """The groups of *rows* for *mode*, by name: ``{key, name, rows, totals}``.

    Rows keep their order inside a group. ``GROUP_NONE`` gives no groups.
    """
    if mode not in GROUP_KEYS:
        return []
    id_key, name_key = GROUP_KEYS[mode]
    groups: dict[Any, dict[str, Any]] = {}
    for row in rows:
        group = groups.setdefault(row.get(id_key), {"key": row.get(id_key), "name": str(row.get(name_key) or ""),
                                                   "rows": []})
        group["rows"].append(row)
    ordered = sorted(groups.values(), key=lambda g: g["name"])
    for group in ordered:
        group["totals"] = report_totals(group["rows"])
    return ordered


class ContractorExtractsReportService(ContractorContractsReportService):
    """The filter choices (companies, projects, contractors) are the contracts report's."""

    def report(self, date_from: Any = None, date_to: Any = None, company_id: Any = None,
               project_id: Any = None, contractor_id: Any = None) -> list[dict[str, Any]]:
        """The report lines for the filters (``None`` = الكل), oldest extract first."""
        where, params = ["x.status = 'approved'", "k.status = 'approved'"], []
        for clause, value in (("x.extract_date >= %s", date_from), ("x.extract_date <= %s", date_to),
                              ("p.company_id = %s", company_id), ("k.project_id = %s", project_id),
                              ("k.contractor_id = %s", contractor_id)):
            if value not in (None, ""):
                where.append(clause)
                params.append(value)
        extracts = self._db.fetch_all(
            "SELECT x.extract_id, x.extract_no, x.extract_date, x.contract_id, x.works_value, x.vat_pct, "
            "x.advance_payment_pct, x.withholding_tax_pct, x.works_insurance_pct, x.social_insurance_pct, "
            "x.other_deductions, k.contract_no, k.contractor_id, d.contractor_name, k.project_id, "
            "p.project_name, p.company_id, c.company_name "
            "FROM contractor_extracts x "
            "JOIN contractor_contracts k ON k.contract_id = x.contract_id "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "JOIN client_companies c ON c.company_id = p.company_id "
            + "WHERE " + " AND ".join(where) + " "
            + "ORDER BY x.extract_date, x.extract_no",
            params,
        )
        return [report_row(extract) for extract in extracts]
