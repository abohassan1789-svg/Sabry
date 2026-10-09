"""Data access and arithmetic for شاشة دفعات المقاولين.

A payment (دفعة) is money paid to a contractor on one project
(``contractor_payments.contractor_id`` / ``project_id``; the company is the
project's). The screen asks for the contractor, then the company, then the
project, and only then lists the extracts that match all three. رقم المستخلص
is optional (user request): left empty, the payment is a general one
(دفعة عامة) on all the contractor's extracts on that project.

The cascade works on one *catalog*: every extract with its contractor, company,
project, صافي المستخلص (``net``, from ``extract_amounts``) and what its saved
payments already total (``paid``). The pure helpers below filter it, so the tree
and the combo boxes always agree.

* المتبقي على المستخلص = صافي المستخلص − دفعاته (the general ones are not split
  between the extracts).
* المتبقي على المشروع = صافي مستخلصاته − دفعاتها − الدفعات العامة.

The lists also offer a project where the contractor has an approved contract but no
extract yet (2026-10-09): a دفعة مقدمة is usually paid before the first extract.

Paying more than is left is shown as a warning, not refused (as with the
advance balance on extracts).

طريقة الدفع (user request, 2026-09-26): نقدي / شيك / تحويل. A cheque or a transfer
also needs «رقم الشيك / الحوالة» and «تاريخ الشيك»; a cash payment stores neither.

مسودة / معتمد (``contracting_approval``): «حفظ» keeps a payment as a draft. The
catalog holds approved extracts only, and every balance (``paid``, the general
payments) counts approved payments only; the screen still lists the drafts. An
approved payment is edited or deleted only after «إلغاء الاعتماد» (or by an admin).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.database.db import Database
from app.services import contracting_approval as approval
from app.services.contractor_contract_service import to_decimal
from app.services.contractor_extract_service import extract_amounts

NOTES_MAX = 500
REFERENCE_MAX = 50
CASH, CHEQUE, TRANSFER = "نقدي", "شيك", "تحويل"
PAYMENT_METHODS: tuple[str, ...] = (CASH, CHEQUE, TRANSFER)  # the list's order; the table CHECKs the same set
# نوع الحساب (user request, 2026-10-07): which balance the payment comes out of; required.
CURRENT_BALANCE, WORKS_INSURANCE, SOCIAL_INSURANCE = "رصيد جاري", "تأمين أعمال", "تأمينات اجتماعية"
# دفعة مقدمة (user, 2026-10-09): paid out of the contracts' advance (قيمة العقد × نسبة المقدمة) on the
# project, with or without an extract. It has no رصيد أول المدة on the contractor's card.
ADVANCE_PAYMENT = "دفعة مقدمة"
ACCOUNT_TYPES: tuple[str, ...] = (CURRENT_BALANCE, WORKS_INSURANCE, SOCIAL_INSURANCE,
                                  ADVANCE_PAYMENT)  # the table CHECKs the same set
# The types that come out of what the extracts hold (each has a statement tab in كشف حساب مقاول).
EXTRACT_ACCOUNT_TYPES: tuple[str, ...] = (CURRENT_BALANCE, WORKS_INSURANCE, SOCIAL_INSURANCE)
# Each type pays out of its own balance (user, 2026-10-07): رصيد جاري out of صافي المستخلص, each
# insurance out of what the extracts held back for it. Catalog fields: (held, paid by that type).
ACCOUNT_FIELDS: dict[str, tuple[str, str]] = {
    CURRENT_BALANCE: ("net", "paid"),
    WORKS_INSURANCE: ("works_insurance", "paid_works_insurance"),
    SOCIAL_INSURANCE: ("social_insurance", "paid_social_insurance"),
}
# Each type's رصيد أول المدة: its field on the contractor's card (شاشة المقاولين).
ACCOUNT_OPENING: dict[str, str] = {CURRENT_BALANCE: "current_balance", WORKS_INSURANCE: "works_insurance_amount",
                                   SOCIAL_INSURANCE: "social_insurance_amount"}
GENERAL_LABEL = "دفعة عامة"  # what «رقم المستخلص» shows for a payment without one

_CATALOG_SQL = (
    "SELECT x.extract_id, x.extract_no, x.extract_date, x.works_value, x.vat_pct, x.advance_payment_pct, "
    "x.withholding_tax_pct, x.works_insurance_pct, x.social_insurance_pct, x.other_deductions, "
    "k.contract_id, k.contract_no, d.contractor_id, d.contractor_code, d.contractor_name, "
    "c.company_id, c.company_code, c.company_name, p.project_id, p.project_code, p.project_name, "
    "COALESCE(y.paid, 0) AS paid, COALESCE(y.paid_works_insurance, 0) AS paid_works_insurance, "
    "COALESCE(y.paid_social_insurance, 0) AS paid_social_insurance "
    "FROM contractor_extracts x "
    "JOIN contractor_contracts k ON k.contract_id = x.contract_id "
    "JOIN contractors d ON d.contractor_id = k.contractor_id "
    "JOIN company_projects p ON p.project_id = k.project_id "
    "JOIN client_companies c ON c.company_id = p.company_id "
    "LEFT JOIN (SELECT extract_id, "
    f"sum(amount) FILTER (WHERE account_type = '{CURRENT_BALANCE}') AS paid, "
    f"sum(amount) FILTER (WHERE account_type = '{WORKS_INSURANCE}') AS paid_works_insurance, "
    f"sum(amount) FILTER (WHERE account_type = '{SOCIAL_INSURANCE}') AS paid_social_insurance "
    "FROM contractor_payments "
    "WHERE extract_id IS NOT NULL AND status = 'approved' GROUP BY extract_id) y "
    "ON y.extract_id = x.extract_id "
    "WHERE x.status = 'approved' "
    "ORDER BY d.contractor_code, c.company_code, p.project_code, x.extract_date, x.extract_no"
)

_PAYMENT_SELECT = (
    "SELECT y.payment_id, y.payment_date, y.extract_id, y.amount, y.notes, "
    "y.payment_method, y.reference_no, y.cheque_date, y.account_type, y.status, "
    f"COALESCE(x.extract_no, '{GENERAL_LABEL}') AS extract_no, "
    "d.contractor_id, d.contractor_name, c.company_id, c.company_name, p.project_id, p.project_name "
    "FROM contractor_payments y "
    "JOIN contractors d ON d.contractor_id = y.contractor_id "
    "JOIN company_projects p ON p.project_id = y.project_id "
    "JOIN client_companies c ON c.company_id = p.company_id "
    "LEFT JOIN contractor_extracts x ON x.extract_id = y.extract_id "
)
_PAYMENT_ORDER = "ORDER BY y.payment_date, y.payment_id"


class PaymentError(ValueError):
    """A rule the user broke (no extract, no amount, ...): shown as-is."""


def needs_reference(method: Any) -> bool:
    """شيك and تحويل carry a number and a date; نقدي does not."""
    return method in (CHEQUE, TRANSFER)


def method_text(record: dict[str, Any]) -> str:
    """How a payment's method reads in a table: «نقدي», «شيك 123456»."""
    method = record.get("payment_method") or CASH
    reference = str(record.get("reference_no") or "").strip()
    return f"{method} {reference}" if needs_reference(method) and reference else method


def _same(a: Any, b: Any) -> bool:
    return a is not None and b is not None and str(a) == str(b)


# -- the cascade ------------------------------------------------------------------------

def with_net(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Catalog rows plus ``net`` (صافي المستخلص), ``remaining`` (net − its رصيد جاري payments)
    and what it held back for each insurance (``works_insurance``, ``social_insurance``)."""
    out = []
    for row in rows:
        amounts = extract_amounts(row)
        net = amounts["net"]
        paid = to_decimal(row.get("paid"))
        out.append(dict(row, net=net, paid=paid, remaining=net - paid,
                        works_insurance=amounts["works_insurance"], social_insurance=amounts["social_insurance"],
                        paid_works_insurance=to_decimal(row.get("paid_works_insurance")),
                        paid_social_insurance=to_decimal(row.get("paid_social_insurance"))))
    return out


def extract_account(row: dict[str, Any], account_type: Any = CURRENT_BALANCE) -> tuple[Decimal, Decimal]:
    """(held, paid) of one catalog extract for one نوع الحساب: صافي المستخلص and its رصيد جاري
    payments, or the insurance it held back and that insurance's payments."""
    held_key, paid_key = ACCOUNT_FIELDS.get(account_type, ACCOUNT_FIELDS[CURRENT_BALANCE])
    return to_decimal(row.get(held_key)), to_decimal(row.get(paid_key))


def _unique(rows: list[dict[str, Any]], key: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for row in rows:
        if row[key] not in seen:
            seen.add(row[key])
            out.append({name: row[name] for name in (key, *fields)})
    return out


def companies_of(catalog: list[dict[str, Any]], contractor_id: Any,
                 contracts: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """The companies the contractor has extracts with — or an approved contract (*contracts*)."""
    rows = [r for r in [*catalog, *contracts] if _same(r["contractor_id"], contractor_id)]
    return _unique(rows, "company_id", ("company_code", "company_name"))


def projects_of(catalog: list[dict[str, Any]], contractor_id: Any, company_id: Any,
                contracts: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """That company's projects the contractor has extracts — or an approved contract — on."""
    rows = [r for r in [*catalog, *contracts]
            if _same(r["contractor_id"], contractor_id) and _same(r["company_id"], company_id)]
    return _unique(rows, "project_id", ("project_code", "project_name"))


def extracts_of(catalog: list[dict[str, Any]], contractor_id: Any, company_id: Any,
                project_id: Any) -> list[dict[str, Any]]:
    """رقم المستخلص's list: the extracts matching the contractor, company AND project."""
    return [r for r in catalog if _same(r["contractor_id"], contractor_id)
            and _same(r["company_id"], company_id) and _same(r["project_id"], project_id)]


# -- the arithmetic ------------------------------------------------------------------------

def payment_balance(net: Any, paid_total: Any, own_saved: Any, amount: Any, opening: Any = 0) -> dict[str, Decimal]:
    """Where one extract (or project) stands with the payment on screen.

    ``paid_total`` is what the SAVED payments total; ``own_saved`` is the saved
    amount of the payment being edited when it is counted there (0 for a new one),
    so it is not counted twice. ``opening`` = رصيد أول المدة from the contractor's
    card (a general payment's). ``previous`` = the other payments, ``remaining`` =
    opening + net − previous − this (negative = overpaid).
    """
    opening = to_decimal(opening)
    net = to_decimal(net)
    previous = to_decimal(paid_total) - to_decimal(own_saved)
    this = to_decimal(amount)
    return {"opening": opening, "net": net, "previous": previous, "this": this,
            "remaining": opening + net - previous - this}


def general_paid(general: dict[tuple, Any], contractor_id: Any, project_id: Any = None,
                 account_type: Any = CURRENT_BALANCE) -> Decimal:
    """The general payments (no extract) of one نوع الحساب by the contractor — on one project,
    or on all when None.

    *general* maps ``(contractor_id, project_id, account_type)`` to their total
    (``ContractorPaymentService.general_totals``); a key without the type is رصيد جاري.
    """
    total = Decimal("0")
    for key, amount in general.items():
        contractor, project, *kind = key
        if (_same(contractor, contractor_id) and (project_id is None or _same(project, project_id))
                and (kind[0] if kind else CURRENT_BALANCE) == account_type):
            total += to_decimal(amount)
    return total


def project_balance(catalog: list[dict[str, Any]], general: dict[tuple, Any], contractor_id: Any,
                    company_id: Any, project_id: Any, account_type: Any = CURRENT_BALANCE) -> dict[str, Decimal]:
    """One نوع الحساب on the contractor's extracts of a project: what they hold (صافي المستخلصات,
    or the insurance held back) and everything paid out of it, general payments included."""
    rows = extracts_of(catalog, contractor_id, company_id, project_id)
    held, paid = Decimal("0"), general_paid(general, contractor_id, project_id, account_type)
    for row in rows:
        row_held, row_paid = extract_account(row, account_type)
        held += row_held
        paid += row_paid
    return {"net": held, "paid": paid, "remaining": held - paid}


def advance_balance_of(contracts: list[dict[str, Any]], advance_paid: dict[tuple, Any], contractor_id: Any,
                       project_id: Any) -> dict[str, Decimal]:
    """دفعة مقدمة on a project: the contractor's approved contracts there grant
    قيمة العقد × نسبة المقدمة (``net``); ``paid`` = the approved دفعات مقدمة on the project,
    with or without an extract (*advance_paid* maps ``(contractor_id, project_id)`` to their total)."""
    agreed = Decimal("0")
    for contract in contracts:
        if _same(contract["contractor_id"], contractor_id) and _same(contract["project_id"], project_id):
            agreed += to_decimal(contract.get("advance_agreed"))
    paid = sum((to_decimal(amount) for (contractor, project), amount in advance_paid.items()
                if _same(contractor, contractor_id) and _same(project, project_id)), Decimal("0"))
    return {"net": agreed, "paid": paid, "remaining": agreed - paid}


def contractor_summary(catalog: list[dict[str, Any]], contractor_id: Any,
                       general: dict[tuple, Any] | None = None) -> dict[str, Decimal]:
    """The contractor's KPI tiles: صافي مستخلصاته، المدفوع (general payments included)، المتبقي."""
    rows = [r for r in catalog if _same(r["contractor_id"], contractor_id)]
    net = sum((to_decimal(r["net"]) for r in rows), Decimal("0"))
    paid = sum((to_decimal(r["paid"]) for r in rows), Decimal("0")) + general_paid(general or {}, contractor_id)
    return {"net": net, "paid": paid, "remaining": net - paid, "extracts": Decimal(len(rows))}


class ContractorPaymentService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- choices -----------------------------------------------------------

    def contractor_choices(self) -> list[dict[str, Any]]:
        return self._db.fetch_all(
            "SELECT contractor_id, contractor_code, contractor_name, contractor_type, "
            "current_balance, works_insurance_amount, social_insurance_amount "
            "FROM contractors WHERE status = 'approved' ORDER BY contractor_code"
        )

    def extract_catalog(self) -> list[dict[str, Any]]:
        """Every extract with its contractor / company / project, net, paid and remaining."""
        return with_net(self._db.fetch_all(_CATALOG_SQL))

    def contract_catalog(self) -> list[dict[str, Any]]:
        """Every approved contract with its contractor / company / project and its advance
        (قيمة العقد × نسبة المقدمة, ``advance_agreed``)."""
        rows = self._db.fetch_all(
            "SELECT k.contract_id, k.contract_no, k.contract_value, k.advance_payment_pct, "
            "d.contractor_id, d.contractor_code, d.contractor_name, "
            "c.company_id, c.company_code, c.company_name, p.project_id, p.project_code, p.project_name "
            "FROM contractor_contracts k "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "JOIN client_companies c ON c.company_id = p.company_id "
            "WHERE k.status = 'approved' AND d.status = 'approved' "
            "ORDER BY d.contractor_code, c.company_code, p.project_code, k.contract_no"
        )
        cent = Decimal("0.01")
        return [dict(row, advance_agreed=(to_decimal(row.get("contract_value")).quantize(cent)
                                          * to_decimal(row.get("advance_payment_pct")) / 100).quantize(cent))
                for row in rows]

    def advance_totals(self) -> dict[tuple, Decimal]:
        """``(contractor_id, project_id) -> total`` of the approved دفعات مقدمة, with or without an extract."""
        rows = self._db.fetch_all(
            "SELECT contractor_id, project_id, sum(amount) AS total FROM contractor_payments "
            f"WHERE account_type = '{ADVANCE_PAYMENT}' AND status = 'approved' GROUP BY contractor_id, project_id"
        )
        return {(row["contractor_id"], row["project_id"]): to_decimal(row["total"]) for row in rows}

    def general_totals(self) -> dict[tuple, Decimal]:
        """``(contractor_id, project_id, account_type) -> total`` of the approved general payments
        (no extract)."""
        rows = self._db.fetch_all(
            "SELECT contractor_id, project_id, account_type, sum(amount) AS total FROM contractor_payments "
            "WHERE extract_id IS NULL AND status = 'approved' GROUP BY contractor_id, project_id, account_type"
        )
        return {(row["contractor_id"], row["project_id"], row["account_type"]): to_decimal(row["total"])
                for row in rows}

    # -- reading -----------------------------------------------------------

    def payments(self, contractor_id: Any = None, extract_id: Any = None,
                 project_id: Any = None) -> list[dict[str, Any]]:
        """Payments, oldest first: of one extract; the GENERAL ones of a contractor on a
        project (``contractor_id`` + ``project_id``); all of one contractor; or all."""
        if extract_id not in (None, ""):
            return self._db.fetch_all(_PAYMENT_SELECT + "WHERE y.extract_id = %s " + _PAYMENT_ORDER, [extract_id])
        if contractor_id not in (None, "") and project_id not in (None, ""):
            return self._db.fetch_all(
                _PAYMENT_SELECT + "WHERE y.contractor_id = %s AND y.project_id = %s AND y.extract_id IS NULL "
                + _PAYMENT_ORDER, [contractor_id, project_id])
        if contractor_id not in (None, ""):
            return self._db.fetch_all(_PAYMENT_SELECT + "WHERE d.contractor_id = %s " + _PAYMENT_ORDER, [contractor_id])
        return self._db.fetch_all(_PAYMENT_SELECT + _PAYMENT_ORDER)

    def get_payment(self, payment_id: Any) -> dict[str, Any] | None:
        return self._db.fetch_one(_PAYMENT_SELECT + "WHERE y.payment_id = %s", [payment_id])

    def search_payments(self, keyword: str = "", limit: int = 500) -> list[dict[str, Any]]:
        """«بحث» (F1): names, extract number, notes, date, or the amount with or without commas."""
        where, params = "", []
        needle = str(keyword or "").strip()
        if needle:
            where = (
                "WHERE concat_ws(' ', d.contractor_name, c.company_name, p.project_name, "
                f"COALESCE(x.extract_no, '{GENERAL_LABEL}'), "
                "y.notes, y.payment_date::text, y.payment_method, y.reference_no, y.account_type) ILIKE %s OR y.amount::text ILIKE %s "
            )
            params = [f"%{needle}%", f"%{needle.replace(',', '')}%"]
        return self._db.fetch_all(
            _PAYMENT_SELECT + where + "ORDER BY y.payment_date DESC, y.payment_id DESC LIMIT %s", params + [limit]
        )

    # -- writing -----------------------------------------------------------

    def save_payment(self, data: dict[str, Any], payment_id: Any = None, allow_approved: bool = False) -> int:
        """Insert (as a draft) or update a payment; *allow_approved* lets an admin edit an approved one."""
        approval.check_unlocked(self._db, approval.PAYMENT, payment_id, "تعديل", allow_approved)
        if data.get("contractor_id") in (None, ""):
            raise PaymentError("اختار اسم المقاول.")
        if data.get("project_id") in (None, ""):
            raise PaymentError("اختار اسم الشركة واسم المشروع.")
        if not data.get("payment_date"):
            raise PaymentError("تاريخ الدفعة مطلوب.")
        amount = to_decimal(data.get("amount"))
        if amount <= 0:
            raise PaymentError("اكتب مبلغ الدفعة.")
        # نوع الحساب may wait while the payment is a draft; اعتماد needs it (user, 2026-10-07).
        account_type = data.get("account_type") or None
        if account_type is not None and account_type not in ACCOUNT_TYPES:
            raise PaymentError("نوع الحساب لازم يكون رصيد جاري أو تأمين أعمال أو تأمينات اجتماعية أو دفعة مقدمة.")
        notes = str(data.get("notes") or "").strip()
        if len(notes) > NOTES_MAX:
            raise PaymentError(f"الملاحظات أطول من {NOTES_MAX} حرف.")
        method = data.get("payment_method") or CASH
        if method not in PAYMENT_METHODS:
            raise PaymentError("طريقة الدفع لازم تكون نقدي أو شيك أو تحويل.")
        reference, cheque_date = None, None
        if needs_reference(method):
            reference = str(data.get("reference_no") or "").strip()
            if not reference:
                raise PaymentError("اكتب رقم الشيك / الحوالة.")
            if len(reference) > REFERENCE_MAX:
                raise PaymentError(f"رقم الشيك / الحوالة أطول من {REFERENCE_MAX} حرف.")
            cheque_date = data.get("cheque_date") or None
            if not cheque_date:
                raise PaymentError("تاريخ الشيك مطلوب.")
        extract_id = data.get("extract_id")
        if extract_id == "":
            extract_id = None
        if extract_id is not None:
            owner = self._db.fetch_one(
                "SELECT k.contractor_id, k.project_id FROM contractor_extracts x "
                "JOIN contractor_contracts k ON k.contract_id = x.contract_id WHERE x.extract_id = %s",
                [extract_id],
            )
            if not owner or not (_same(owner["contractor_id"], data["contractor_id"])
                                 and _same(owner["project_id"], data["project_id"])):
                raise PaymentError("المستخلص ده مش تبع المقاول والمشروع المختارين.")
        approval.check_parents(self._db, [(approval.CONTRACTOR, data["contractor_id"]),
                                          (approval.PROJECT, data["project_id"]), (approval.EXTRACT, extract_id)])
        params = [data["payment_date"], data["contractor_id"], data["project_id"], extract_id, amount, notes or None,
                  method, reference, cheque_date, account_type]
        if payment_id is None:
            row = self._db.fetch_one(
                "INSERT INTO contractor_payments (payment_date, contractor_id, project_id, extract_id, amount, notes, "
                "payment_method, reference_no, cheque_date, account_type) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING payment_id",
                params,
            )
            return int(row["payment_id"])
        self._db.execute(
            "UPDATE contractor_payments SET payment_date = %s, contractor_id = %s, project_id = %s, "
            "extract_id = %s, amount = %s, notes = %s, payment_method = %s, reference_no = %s, cheque_date = %s, "
            "account_type = %s WHERE payment_id = %s",
            params + [payment_id],
        )
        return int(payment_id)

    def delete_payment(self, payment_id: Any, allow_approved: bool = False) -> None:
        approval.check_unlocked(self._db, approval.PAYMENT, payment_id, "حذف", allow_approved)
        self._db.execute("DELETE FROM contractor_payments WHERE payment_id = %s", [payment_id])

    # -- مسودة / معتمد -------------------------------------------------------

    def approve(self, payment_id: Any, user_id: Any = None) -> None:
        row = self._db.fetch_one("SELECT account_type FROM contractor_payments WHERE payment_id = %s", [payment_id])
        if row is not None and not row.get("account_type"):
            raise approval.ApprovalError("اختار نوع الحساب قبل الاعتماد (عدّل الدفعة واختاره).")
        approval.approve(self._db, approval.PAYMENT, payment_id, user_id)

    def unapprove(self, payment_id: Any) -> None:
        approval.unapprove(self._db, approval.PAYMENT, payment_id)
