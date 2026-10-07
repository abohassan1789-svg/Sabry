"""Data and arithmetic for تقرير ضرائب الخصم (نموذج 7 «شريط ملخص داكن», 2026-10-07).

One row per approved extract, with the user's columns: التاريخ، اسم المقاول، اسم
المشروع، اسم الشركة، إجمالي المستخلص، نسبة الضريبة، صافي الأعمال، نسبة ضرائب
الخصم، قيمة ضرائب الخصم. Every amount comes from ``extract_amounts`` (via the
extracts report's ``report_row``), so it matches the extracts screen.

The totals (user, 2026-10-07):

* رصيد أول المدة = «ضرائب الخصم والإضافة» on the contractors' cards + the
  ضريبة الخصم of the extracts dated before «من» (with «كل الفترات», the cards alone).
* صافي ضرائب الخصم = رصيد أول المدة + ضرائب الخصم على مستخلصات الفترة.

Whose cards: the chosen contractor's; with «الكل», every approved contractor's,
narrowed to those with an approved contract in the chosen company / project —
the same rule as the إجمالي ضرائب الخصم card of كشف حساب مقاول.
"""

from __future__ import annotations

from typing import Any

from app.services.contractor_contract_service import to_decimal
from app.services.contractor_contracts_report_service import ZERO, _money
from app.services.contractor_extracts_report_service import ContractorExtractsReportService

# The amounts summed for the totals row and the figures.
AMOUNT_KEYS = ("works_value", "before_tax", "withholding_tax")


def build_report(card_amount: Any, rows: list[dict[str, Any]], date_from: Any = None) -> dict[str, Any]:
    """The report for *rows* (report lines up to «إلى», any start) and the cards' *card_amount*.

    Lines before *date_from* are not listed: their ضريبة الخصم joins رصيد أول المدة.
    """
    listed, earlier = [], ZERO
    for row in rows:
        day = row.get("extract_date")
        if date_from is not None and day is not None and day < date_from:
            earlier += row["withholding_tax"]
        else:
            listed.append(row)
    totals: dict[str, Any] = {key: sum((row[key] for row in listed), ZERO) for key in AMOUNT_KEYS}
    totals["count"] = len(listed)
    card = _money(to_decimal(card_amount))
    opening = card + earlier
    return {"rows": listed, "totals": totals, "card_opening": card, "earlier_extracts": earlier,
            "opening": opening, "net": opening + totals["withholding_tax"]}


def empty_report() -> dict[str, Any]:
    return build_report(0, [])


class ContractorWithholdingReportService(ContractorExtractsReportService):
    """The filter choices are the contracts report's; the lines are the extracts report's."""

    def withholding_report(self, date_from: Any = None, date_to: Any = None, company_id: Any = None,
                           project_id: Any = None, contractor_id: Any = None) -> dict[str, Any]:
        # Every line up to «إلى»: the ones before «من» feed رصيد أول المدة.
        rows = self.report(None, date_to, company_id, project_id, contractor_id)
        return build_report(self.card_withholding(company_id, project_id, contractor_id), rows, date_from)

    def card_withholding(self, company_id: Any = None, project_id: Any = None, contractor_id: Any = None) -> Any:
        """«ضرائب الخصم والإضافة» summed over the approved contractors' cards the filters cover."""
        if contractor_id not in (None, ""):
            row = self._db.fetch_one(
                "SELECT COALESCE(sum(withholding_tax_amount), 0) AS amount FROM contractors "
                "WHERE contractor_id = %s AND status = 'approved'", [contractor_id])
            return row["amount"] if row else ZERO
        where, params = [], []
        for clause, value in (("p.company_id = %s", company_id), ("k.project_id = %s", project_id)):
            if value not in (None, ""):
                where.append(clause)
                params.append(value)
        row = self._db.fetch_one(
            "SELECT COALESCE(sum(d.withholding_tax_amount), 0) AS amount FROM contractors d "
            "WHERE d.status = 'approved'"
            + (" AND d.contractor_id IN (SELECT k.contractor_id FROM contractor_contracts k "
               "JOIN company_projects p ON p.project_id = k.project_id "
               "WHERE k.status = 'approved' AND " + " AND ".join(where) + ")" if where else ""),
            params,
        )
        return row["amount"] if row else ZERO
