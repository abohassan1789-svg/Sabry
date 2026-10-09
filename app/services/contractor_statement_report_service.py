"""Data and arithmetic for تقرير كشف حساب مقاول (نموذج 10, 2026-10-02).

One contractor's account over a period, from three screens: المقاولين (the
typed «الرصيد الجاري»)، المستخلصات and دفعات المقاولين.

* The first line is رصيد أول المدة = الرصيد الجاري + صافي المستخلصات − الدفعات
  dated before «من» (with «كل الفترات» it is the الرصيد الجاري alone).
* Then the period's extracts and payments by date (an extract before a payment on
  the same day). An extract line carries every amount of ``extract_amounts``; a
  payment line only «التحصيلات / الدفعات».
* الرصيد التراكمي = الرصيد السابق + صافي المستخلص − التحصيلات (user, 2026-10-02).
* «الضرائب الخاصة» is the extract's نسبة الضريبة (VAT) and its amount, إجمالي
  المستخلص − صافي الأعمال; it is not deducted from الصافي.

The contract figures (user, 2026-10-02): the contractor's contracts' value, the
advance they grant (value × نسبة المقدمة), the advance taken back on their
extracts up to «إلى», and what is left of it. Since 2026-10-09 also «المصروف فعلاً»:
the approved payments of نوع «دفعة مقدمة» up to «إلى». They are in none of the three
statements below (the user chose this card for them).

The company / project filters narrow the contracts, extracts and payments; the
typed الرصيد الجاري is the contractor's and always counts.

Approved records only (مسودة / معتمد, 2026-10-02): a draft contractor has no
statement, and draft contracts, extracts and payments are left out.

One statement per نوع الحساب (user, 2026-10-07), each with its own رصيد أول المدة،
مستخلصات، دفعات، متبقي and الرصيد التراكمي:

* رصيد جاري: opens on the card's «الرصيد الجاري»; an extract adds its صافي المستخلص.
* تأمين أعمال / تأمينات اجتماعية: open on the card's «تأمين الأعمال» / «التأمينات
  الاجتماعية»; an extract adds the insurance it held back.
* A payment comes off its own type only (a payment without a type counts as رصيد جاري).
* The extract lines are the same in the three (their «نوع الحساب» reads «كل الحسابات»).

«الكل» in اسم المقاول (user, 2026-10-07): every approved contractor in one statement —
the openings are their cards added up (with a company / project chosen, the cards of
the contractors with a contract there), then all their movements by date.

إجمالي ضرائب الخصم (user, 2026-10-07): a card of its own, shown only — it is not in
any balance. It starts on the card's «ضرائب الخصم والإضافة» and adds the extracts'
ضريبة الخصم (card 36,000 + extracts 4,000 = 40,000). Extracts before «من» go into
its رصيد أول المدة, those after «إلى» are left out.
"""

from __future__ import annotations

import datetime
from typing import Any

from app.services.contractor_contract_service import to_decimal
from app.services.contractor_payment_service import (
    ACCOUNT_OPENING,
    ADVANCE_PAYMENT,
    EXTRACT_ACCOUNT_TYPES,
    CURRENT_BALANCE,
    SOCIAL_INSURANCE,
    WORKS_INSURANCE,
)
from app.services.contractor_contracts_report_service import ZERO, ContractorContractsReportService, _money
from app.services.contractor_extract_service import extract_amounts

KIND_EXTRACT, KIND_PAYMENT = "extract", "payment"

RATE_KEYS = ("withholding_tax_pct", "advance_payment_pct", "vat_pct", "works_insurance_pct", "social_insurance_pct")
# Amounts on an extract line (``extract_amounts`` keys), all summed in the totals.
EXTRACT_AMOUNT_KEYS = ("works_value", "withholding_tax", "before_tax", "advance_payment", "vat_amount",
                       "works_insurance", "social_insurance", "other_deductions", "net")
AMOUNT_KEYS = EXTRACT_AMOUNT_KEYS + ("paid",)
ALL_ACCOUNTS = "كل الحسابات"  # «نوع الحساب» on an extract line: it feeds the three
# What an extract adds to each نوع الحساب (an ``extract_amounts`` key), and the card's opening field.
ACCOUNT_HELD = {CURRENT_BALANCE: "net", WORKS_INSURANCE: "works_insurance", SOCIAL_INSURANCE: "social_insurance"}


def _day(value: Any) -> datetime.date | None:
    if isinstance(value, datetime.datetime):
        return value.date()
    return value if isinstance(value, datetime.date) else None


def extract_line(extract: dict[str, Any]) -> dict[str, Any]:
    amounts = extract_amounts(extract)
    line = {**extract, "kind": KIND_EXTRACT, "date": _day(extract.get("extract_date")), "paid": ZERO,
            "account_type": ALL_ACCOUNTS}
    line.update({key: to_decimal(extract.get(key)) for key in RATE_KEYS})
    line.update({key: amounts[key] for key in EXTRACT_AMOUNT_KEYS})
    return line


def payment_line(payment: dict[str, Any]) -> dict[str, Any]:
    line = {**payment, "kind": KIND_PAYMENT, "date": _day(payment.get("payment_date")),
            "paid": _money(to_decimal(payment.get("amount"))),
            "account_type": payment.get("account_type") or CURRENT_BALANCE}
    line.update({key: ZERO for key in EXTRACT_AMOUNT_KEYS})
    return line


def _sort_key(line: dict[str, Any]) -> tuple:
    date = line["date"] or datetime.date.min
    if line["kind"] == KIND_EXTRACT:
        return date, 0, str(line.get("extract_no") or ""), line.get("extract_id") or 0
    return date, 1, "", line.get("payment_id") or 0


def build_statement(opening_balance: Any, extracts: list[dict[str, Any]], payments: list[dict[str, Any]],
                    date_from: Any = None, date_to: Any = None,
                    account_type: str = CURRENT_BALANCE) -> dict[str, Any]:
    """``{opening, lines, totals}`` of one نوع الحساب for one contractor.

    An extract adds what it holds for *account_type* (``ACCOUNT_HELD``); only the
    payments of that type come off. *extracts* / *payments* may hold any dates:
    those before *date_from* go into the opening balance, those after *date_to*
    are left out. ``totals["held"]`` = what the period's extracts added.
    """
    held_key = ACCOUNT_HELD[account_type]
    opening = _money(to_decimal(opening_balance))
    lines = []
    for line in [extract_line(x) for x in extracts] + [payment_line(p) for p in payments]:
        if line["kind"] == KIND_PAYMENT and line["account_type"] != account_type:
            continue
        line["held"] = line[held_key]
        day = line["date"]
        if date_to is not None and day is not None and day > date_to:
            continue
        if date_from is not None and day is not None and day < date_from:
            opening += line["held"] - line["paid"]
            continue
        lines.append(line)
    lines.sort(key=_sort_key)
    balance = opening
    for line in lines:
        balance += line["held"] - line["paid"]
        line["balance"] = balance
    totals: dict[str, Any] = {key: sum((line[key] for line in lines), ZERO) for key in AMOUNT_KEYS + ("held",)}
    totals.update(opening=opening, balance=balance,
                  extracts_count=sum(1 for line in lines if line["kind"] == KIND_EXTRACT),
                  payments_count=sum(1 for line in lines if line["kind"] == KIND_PAYMENT))
    return {"opening": opening, "lines": lines, "totals": totals, "account_type": account_type}


def build_accounts(card: dict[str, Any], extracts: list[dict[str, Any]], payments: list[dict[str, Any]],
                   date_from: Any = None, date_to: Any = None) -> dict[str, dict[str, Any]]:
    """The three statements, keyed by نوع الحساب; each opens on its field of the contractor's *card*."""
    return {account: build_statement(card.get(ACCOUNT_OPENING[account]), extracts, payments, date_from, date_to,
                                     account)
            for account in EXTRACT_ACCOUNT_TYPES}


def account_timeline(accounts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """For the chart: the period's movements of all types by date, each with the three running
    balances after it (``balances``); the first point is the openings."""
    current = accounts[CURRENT_BALANCE]
    payments = [line for account in EXTRACT_ACCOUNT_TYPES for line in accounts[account]["lines"]
                if line["kind"] == KIND_PAYMENT]
    extracts = [line for line in current["lines"] if line["kind"] == KIND_EXTRACT]
    balances = {account: accounts[account]["opening"] for account in EXTRACT_ACCOUNT_TYPES}
    points = [{"kind": "opening", "balances": dict(balances)}]
    for line in sorted(extracts + payments, key=_sort_key):
        if line["kind"] == KIND_EXTRACT:
            for account in EXTRACT_ACCOUNT_TYPES:
                balances[account] += line[ACCOUNT_HELD[account]]
        else:
            balances[line["account_type"]] -= line["paid"]
        points.append({"kind": line["kind"], "balances": dict(balances)})
    return points


def withholding_total(card_amount: Any, extracts: list[dict[str, Any]],
                      date_from: Any = None, date_to: Any = None) -> dict[str, Any]:
    """إجمالي ضرائب الخصم: ``{opening, held, total, extracts_count}`` — shown, never deducted."""
    opening, held, count = _money(to_decimal(card_amount)), ZERO, 0
    for extract in extracts:
        day = _day(extract.get("extract_date"))
        if date_to is not None and day is not None and day > date_to:
            continue
        amount = extract_amounts(extract)["withholding_tax"]
        if date_from is not None and day is not None and day < date_from:
            opening += amount
            continue
        held += amount
        count += 1
    return {"opening": opening, "held": held, "total": opening + held, "extracts_count": count}


def contract_advance(contracts: list[dict[str, Any]], extracts: list[dict[str, Any]],
                     date_to: Any = None, payments: list[dict[str, Any]] = ()) -> dict[str, Any]:
    """The contracts' value and advance, how much of it was paid out (*payments* of نوع
    دفعة مقدمة) and how much the extracts took back — both up to *date_to*."""
    value = sum((_money(to_decimal(c.get("contract_value"))) for c in contracts), ZERO)
    agreed = sum((_money(_money(to_decimal(c.get("contract_value"))) * to_decimal(c.get("advance_payment_pct")) / 100)
                  for c in contracts), ZERO)
    taken = [x for x in extracts if date_to is None or (_day(x.get("extract_date")) or date_to) <= date_to]
    deducted = sum((extract_amounts(x)["advance_payment"] for x in taken), ZERO)
    paid = sum((_money(to_decimal(p.get("amount"))) for p in payments
                if p.get("account_type") == ADVANCE_PAYMENT
                and (date_to is None or (_day(p.get("payment_date")) or date_to) <= date_to)), ZERO)
    return {
        "count": len(contracts),
        "contract_value": value,
        "advance_agreed": agreed,
        # The overall rate: the advance over the contracts' value.
        "advance_pct": agreed / value * 100 if value > 0 else ZERO,
        "advance_paid": paid,
        "advance_deducted": deducted,
        "remaining_advance": agreed - deducted,
    }


def _with_accounts(accounts: dict[str, dict[str, Any]], contracts: dict[str, Any],
                   withholding: dict[str, Any]) -> dict[str, Any]:
    """The رصيد جاري statement at the top (``opening``/``lines``/``totals``), plus every type's."""
    statement = dict(accounts[CURRENT_BALANCE])
    statement.update(accounts=accounts, timeline=account_timeline(accounts), contracts=contracts,
                     withholding=withholding)
    return statement


def empty_statement() -> dict[str, Any]:
    return _with_accounts(build_accounts({}, [], []), contract_advance([], []), withholding_total(0, []))


class ContractorStatementReportService(ContractorContractsReportService):
    """The filter choices are the contracts report's; no contractor (``None``) = «الكل»."""

    def statement(self, date_from: Any = None, date_to: Any = None, company_id: Any = None,
                  project_id: Any = None, contractor_id: Any = None) -> dict[str, Any]:
        everyone = contractor_id in (None, "")
        where, params = ["TRUE"], []
        if not everyone:
            where, params = ["k.contractor_id = %s"], [contractor_id]
        for clause, value in (("p.company_id = %s", company_id), ("k.project_id = %s", project_id)):
            if value not in (None, ""):
                where.append(clause)
                params.append(value)
        if everyone:
            # Every approved contractor's card; with a company / project chosen, those with a contract there.
            narrowed = len(where) > 1
            row = self._db.fetch_one(
                "SELECT COALESCE(sum(d.current_balance), 0) AS current_balance, "
                "COALESCE(sum(d.works_insurance_amount), 0) AS works_insurance_amount, "
                "COALESCE(sum(d.social_insurance_amount), 0) AS social_insurance_amount, "
                "COALESCE(sum(d.withholding_tax_amount), 0) AS withholding_tax_amount "
                "FROM contractors d WHERE d.status = 'approved'"
                + (" AND d.contractor_id IN (SELECT k.contractor_id FROM contractor_contracts k "
                   "JOIN company_projects p ON p.project_id = k.project_id "
                   "WHERE k.status = 'approved' AND " + " AND ".join(where) + ")" if narrowed else ""),
                params if narrowed else [],
            )
        else:
            row = self._db.fetch_one(
                "SELECT current_balance, works_insurance_amount, social_insurance_amount, withholding_tax_amount "
                "FROM contractors "
                "WHERE contractor_id = %s AND status = 'approved'", [contractor_id]
            )
            if row is None:
                return empty_statement()
        contracts = self._db.fetch_all(
            "SELECT k.contract_id, k.contract_value, k.advance_payment_pct FROM contractor_contracts k "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "WHERE k.status = 'approved' AND " + " AND ".join(where),
            params,
        )
        extracts = self._db.fetch_all(
            "SELECT x.extract_id, x.extract_no, x.extract_date, x.contract_id, x.works_value, x.vat_pct, "
            "x.advance_payment_pct, x.withholding_tax_pct, x.works_insurance_pct, x.social_insurance_pct, "
            "x.other_deductions, d.contractor_name "
            "FROM contractor_extracts x "
            "JOIN contractor_contracts k ON k.contract_id = x.contract_id "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "WHERE x.status = 'approved' AND k.status = 'approved' AND d.status = 'approved' AND "
            + " AND ".join(where),
            params,
        )
        payment_where = [w.replace("k.contractor_id", "y.contractor_id").replace("k.project_id", "y.project_id")
                         for w in where]
        payments = self._db.fetch_all(
            "SELECT y.payment_id, y.payment_date, y.amount, y.payment_method, y.reference_no, y.extract_id, "
            "y.account_type, "
            "x.extract_no, d.contractor_name "
            "FROM contractor_payments y "
            "JOIN contractors d ON d.contractor_id = y.contractor_id "
            "LEFT JOIN company_projects p ON p.project_id = y.project_id "  # a payment may have no project
            "LEFT JOIN contractor_extracts x ON x.extract_id = y.extract_id "
            "WHERE y.status = 'approved' AND d.status = 'approved' AND " + " AND ".join(payment_where),
            params,
        )
        accounts = build_accounts(row, extracts, payments, date_from, date_to)
        return _with_accounts(accounts, contract_advance(contracts, extracts, date_to, payments),
                              withholding_total(row.get("withholding_tax_amount"), extracts, date_from, date_to))
