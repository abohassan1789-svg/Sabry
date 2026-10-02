"""Data access and arithmetic for شاشة مستخلصات المقاولين.

An extract (مستخلص) is one progress claim on one contract
(``contractor_extracts.contract_id``). Only the inputs are stored; the amounts
come from ``extract_amounts`` so the screen, the cards and any report agree:

* صافي الأعمال = إجمالي المستخلص ÷ (1 + نسبة الضريبة) — the works value
  includes the tax (default 14%).
* الدفعة المقدمة / تأمين الأعمال / التأمينات الاجتماعية = إجمالي المستخلص × النسبة.
* ضريبة الخصم = صافي الأعمال × النسبة.
* صافي المستخلص = إجمالي المستخلص − المقدمة − ضريبة الخصم − تأمين الأعمال −
  التأمينات − خصومات أخرى.

The contract's own rates are shown on the screen for reference only; they seed
the advance-payment rate (and the two list rates when they are valid choices)
of a NEW extract and never touch a saved one.

Numbers: «<contract no>/EX-01», «/EX-02», ... per contract — suggested,
editable, only kept unique (trimmed, any case).

مسودة / معتمد (``contracting_approval``): «حفظ» keeps an extract as a draft;
only approved contractors and contracts are offered; an approved extract is
edited or deleted only after «إلغاء الاعتماد» (or by an admin). The screen
lists a contract's drafts too, but its figures (the KPI strip, the advance
balance) count approved extracts only.
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.database.db import Database
from app.services import contracting_approval as approval
from app.services.contractor_contract_service import to_decimal

EXTRACT_SEPARATOR = "/EX-"
DEFAULT_VAT_PCT = Decimal("14")
DEFAULT_WORKS_INSURANCE_PCT = Decimal("5")
# The usual choices of the two list rates; any other rate 0–100 may be typed (2026-10-02).
WITHHOLDING_OPTIONS: tuple[Decimal, ...] = (Decimal("0"), Decimal("1"), Decimal("3"), Decimal("5"))
SOCIAL_OPTIONS: tuple[Decimal, ...] = (Decimal("0"), Decimal("0.365"), Decimal("2.8"), Decimal("3.6"))

# (key, label) of the deduction lines, in screen order.
DEDUCTION_LINES: tuple[tuple[str, str], ...] = (
    ("advance_payment", "الدفعة المقدمة"),
    ("withholding_tax", "ضريبة الخصم"),
    ("works_insurance", "تأمين الأعمال"),
    ("social_insurance", "التأمينات الاجتماعية"),
)

_CENT = Decimal("0.01")

_EXTRACT_SELECT = (
    "SELECT x.extract_id, x.extract_no, x.extract_date, x.contract_id, x.works_value, x.vat_pct, "
    "x.advance_payment_pct, x.withholding_tax_pct, x.works_insurance_pct, x.social_insurance_pct, "
    "x.other_deductions, x.status, k.contract_no, k.contractor_id, d.contractor_name "
    "FROM contractor_extracts x "
    "JOIN contractor_contracts k ON k.contract_id = x.contract_id "
    "JOIN contractors d ON d.contractor_id = k.contractor_id "
)


class ExtractError(ValueError):
    """A rule the user broke (duplicate number, no contract, ...): shown as-is."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, ROUND_HALF_UP)


def extract_amounts(record: dict[str, Any]) -> dict[str, Decimal]:
    """Every computed amount of one extract, rounded to piasters.

    *record* holds the inputs under their column names (``works_value``,
    ``vat_pct``, ``advance_payment_pct``, ...); text such as «1,250.00» is fine.
    """
    works = to_decimal(record.get("works_value"))
    vat = to_decimal(record.get("vat_pct"))
    before_tax = _money(works / (Decimal(1) + vat / Decimal(100)))
    lines = {
        "advance_payment": _money(works * to_decimal(record.get("advance_payment_pct")) / 100),
        "withholding_tax": _money(before_tax * to_decimal(record.get("withholding_tax_pct")) / 100),
        "works_insurance": _money(works * to_decimal(record.get("works_insurance_pct")) / 100),
        "social_insurance": _money(works * to_decimal(record.get("social_insurance_pct")) / 100),
    }
    other = _money(to_decimal(record.get("other_deductions")))
    deductions = sum(lines.values(), Decimal("0")) + other
    return {
        "works_value": _money(works),
        "before_tax": before_tax,
        "vat_amount": _money(works) - before_tax,
        **lines,
        "other_deductions": other,
        "deductions": deductions,
        "net": _money(works) - deductions,
    }


def next_extract_no_from(contract_no: str, codes: list[Any]) -> str:
    """«<contract no>/EX-<nn>» after the highest one already on that contract."""
    base = str(contract_no or "").strip()
    pattern = re.compile(rf"^\s*{re.escape(base)}{re.escape(EXTRACT_SEPARATOR)}(\d+)\s*$", re.IGNORECASE)
    highest = 0
    for code in codes:
        match = pattern.match(str(code or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{base}{EXTRACT_SEPARATOR}{highest + 1:02d}"


def contract_progress(contract_value: Any, extracts: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals of a contract's extracts against its value (the KPI strip)."""
    value = to_decimal(contract_value)
    works = sum((to_decimal(x.get("works_value")) for x in extracts), Decimal("0"))
    net = sum((extract_amounts(x)["net"] for x in extracts), Decimal("0"))
    return {
        "contract_value": value,
        "works_total": works,
        "remaining": value - works,
        "net_total": net,
        "count": len(extracts),
        "percent": (works / value * 100) if value > 0 else Decimal("0"),
    }


def _order_key(record: dict[str, Any]) -> tuple[str, str]:
    """Extracts count in date order, then by number (EX-02 after EX-01 on the same day)."""
    return str(record.get("extract_date") or "")[:10], str(record.get("extract_no") or "").strip().upper()


def advance_balance(contract: dict[str, Any] | None, extracts: list[dict[str, Any]],
                    current: dict[str, Any]) -> dict[str, Decimal]:
    """Where the contract's advance payment stands after *current*.

    ``agreed`` = قيمة العقد × نسبة الدفعة المقدمة في العقد; ``previous`` = what the
    contract's earlier extracts (by date, then number) already deducted;
    ``this`` = *current*'s own deduction; ``remaining`` = agreed − previous − this
    (negative when the extracts deducted more than was advanced).
    *current* is the extract on screen, saved or not; its own row in *extracts*
    (same ``extract_id``) is never counted twice.
    """
    contract = contract or {}
    agreed = _money(to_decimal(contract.get("contract_value")) * to_decimal(contract.get("advance_payment_pct")) / 100)
    key = _order_key(current)
    current_id = current.get("extract_id")
    previous = sum(
        (extract_amounts(x)["advance_payment"] for x in extracts
         if (current_id is None or str(x.get("extract_id")) != str(current_id)) and _order_key(x) < key),
        Decimal("0"),
    )
    this = extract_amounts(current)["advance_payment"]
    return {"agreed": agreed, "previous": previous, "this": this, "remaining": agreed - previous - this}


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


class ContractorExtractService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- choices -----------------------------------------------------------

    def contractor_choices(self) -> list[dict[str, Any]]:
        return self._db.fetch_all(
            "SELECT contractor_id, contractor_code, contractor_name, contractor_type "
            "FROM contractors WHERE status = 'approved' ORDER BY contractor_code"
        )

    def contract_choices(self, contractor_id: Any = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT k.contract_id, k.contract_no, k.contractor_id, d.contractor_name, p.project_name "
            "FROM contractor_contracts k "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "WHERE k.status = 'approved' "
        )
        if contractor_id not in (None, ""):
            return self._db.fetch_all(sql + "AND k.contractor_id = %s ORDER BY k.contract_no", [contractor_id])
        return self._db.fetch_all(sql + "ORDER BY k.contract_no")

    def get_contract(self, contract_id: Any) -> dict[str, Any] | None:
        """The contract with its contractor / project / company — shown for reference."""
        return self._db.fetch_one(
            "SELECT k.contract_id, k.contract_no, k.contract_date, k.contractor_id, k.project_id, "
            "k.contract_value, k.advance_payment_pct, k.works_insurance_pct, k.tax_discount_pct, "
            "k.social_insurance_pct, d.contractor_code, d.contractor_name, d.contractor_type, "
            "p.project_name, c.company_name "
            "FROM contractor_contracts k "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "JOIN client_companies c ON c.company_id = p.company_id "
            "WHERE k.contract_id = %s",
            [contract_id],
        )

    # -- reading -----------------------------------------------------------

    def extracts(self, contract_id: Any) -> list[dict[str, Any]]:
        """The contract's extracts, oldest number first."""
        return self._db.fetch_all(
            _EXTRACT_SELECT + "WHERE x.contract_id = %s ORDER BY x.extract_date, x.extract_no", [contract_id]
        )

    def search_extracts(self, keyword: str = "", limit: int = 500) -> list[dict[str, Any]]:
        """«بحث» (F1): every extract with its contract, contractor, project and company.

        *keyword* matches any of the names/numbers, or an amount typed with or
        without thousands separators («50,000» finds 50000.00). Newest first; each
        row also carries ``net_works`` (صافي الأعمال) computed like the screen.
        """
        where, params = "", []
        needle = _clean(keyword)
        if needle:
            where = (
                "WHERE concat_ws(' ', d.contractor_name, x.extract_no, k.contract_no, p.project_name, "
                "c.company_name) ILIKE %s "
                "OR concat_ws(' ', x.works_value::text, "
                "round(x.works_value / (1 + x.vat_pct / 100), 2)::text) ILIKE %s "
            )
            params = [f"%{needle}%", f"%{needle.replace(',', '')}%"]
        rows = self._db.fetch_all(
            "SELECT x.extract_id, x.extract_no, x.extract_date, x.contract_id, x.works_value, x.vat_pct, "
            "x.status, k.contract_no, d.contractor_name, p.project_name, c.company_name "
            "FROM contractor_extracts x "
            "JOIN contractor_contracts k ON k.contract_id = x.contract_id "
            "JOIN contractors d ON d.contractor_id = k.contractor_id "
            "JOIN company_projects p ON p.project_id = k.project_id "
            "JOIN client_companies c ON c.company_id = p.company_id "
            + where + "ORDER BY x.extract_date DESC, x.extract_no DESC LIMIT %s",
            params + [limit],
        )
        return [dict(row, net_works=extract_amounts(row)["before_tax"]) for row in rows]

    def get_extract(self, extract_id: Any) -> dict[str, Any] | None:
        return self._db.fetch_one(_EXTRACT_SELECT + "WHERE x.extract_id = %s", [extract_id])

    # -- numbers -----------------------------------------------------------

    def next_extract_no(self, contract_id: Any) -> str:
        contract = self._db.fetch_one(
            "SELECT contract_no FROM contractor_contracts WHERE contract_id = %s", [contract_id]
        )
        if not contract:
            return ""
        rows = self._db.fetch_all(
            "SELECT extract_no FROM contractor_extracts WHERE contract_id = %s", [contract_id]
        )
        return next_extract_no_from(contract["contract_no"], [row["extract_no"] for row in rows])

    def _no_taken(self, extract_no: str, except_id: Any) -> bool:
        row = self._db.fetch_one(
            "SELECT extract_id FROM contractor_extracts WHERE upper(btrim(extract_no)) = upper(btrim(%s)) "
            "AND (%s::integer IS NULL OR extract_id <> %s::integer) LIMIT 1",
            [extract_no, except_id, except_id],
        )
        return row is not None

    # -- writing -----------------------------------------------------------

    def save_extract(self, data: dict[str, Any], extract_id: Any = None, allow_approved: bool = False) -> int:
        """Insert (as a draft) or update an extract; *allow_approved* lets an admin edit an approved one."""
        approval.check_unlocked(self._db, approval.EXTRACT, extract_id, "تعديل", allow_approved)
        extract_no = _clean(data.get("extract_no"))
        if not extract_no:
            raise ExtractError("رقم المستخلص مطلوب.")
        if data.get("contract_id") in (None, ""):
            raise ExtractError("اختار رقم العقد.")
        if not data.get("extract_date"):
            raise ExtractError("تاريخ المستخلص مطلوب.")
        works = to_decimal(data.get("works_value"))
        if works <= 0:
            raise ExtractError("اكتب إجمالي المستخلص.")
        other = to_decimal(data.get("other_deductions"))
        if other < 0:
            raise ExtractError("الخصومات الأخرى لا تكون بالسالب.")
        rates = {}
        # ضرائب الخصم / التأمينات: the lists are the usual choices, any rate may be typed (2026-10-02).
        for key, label in (("vat_pct", "نسبة الضريبة"), ("advance_payment_pct", "نسبة الدفعة المقدمة"),
                           ("withholding_tax_pct", "نسبة ضرائب الخصم"), ("works_insurance_pct", "نسبة تأمين الأعمال"),
                           ("social_insurance_pct", "نسبة التأمينات الاجتماعية")):
            rate = to_decimal(data.get(key))
            if rate < 0 or rate > 100:
                raise ExtractError(f"{label} لازم تكون بين 0 و 100.")
            rates[key] = rate
        if self._no_taken(extract_no, extract_id):
            raise ExtractError(f"رقم المستخلص «{extract_no}» مستخدم قبل كده. غيّر الرقم قبل الحفظ.")
        approval.check_parents(self._db, [(approval.CONTRACT, data["contract_id"])])

        params = [extract_no, data["extract_date"], data["contract_id"], works, rates["vat_pct"],
                  rates["advance_payment_pct"], rates["withholding_tax_pct"], rates["works_insurance_pct"],
                  rates["social_insurance_pct"], other]
        if extract_id is None:
            row = self._db.fetch_one(
                "INSERT INTO contractor_extracts (extract_no, extract_date, contract_id, works_value, vat_pct, "
                "advance_payment_pct, withholding_tax_pct, works_insurance_pct, social_insurance_pct, "
                "other_deductions) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING extract_id",
                params,
            )
            return int(row["extract_id"])
        self._db.execute(
            "UPDATE contractor_extracts SET extract_no = %s, extract_date = %s, contract_id = %s, works_value = %s, "
            "vat_pct = %s, advance_payment_pct = %s, withholding_tax_pct = %s, works_insurance_pct = %s, "
            "social_insurance_pct = %s, other_deductions = %s WHERE extract_id = %s",
            params + [extract_id],
        )
        return int(extract_id)

    def delete_extract(self, extract_id: Any, allow_approved: bool = False) -> None:
        approval.check_unlocked(self._db, approval.EXTRACT, extract_id, "حذف", allow_approved)
        count = self._db.fetch_one(
            "SELECT count(*) AS n FROM contractor_payments WHERE extract_id = %s", [extract_id]
        )
        if count and int(count["n"]):
            raise ExtractError(f"المستخلص ده عليه {int(count['n'])} دفعة. احذف الدفعات الأول من شاشة «دفعات المقاولين».")
        self._db.execute("DELETE FROM contractor_extracts WHERE extract_id = %s", [extract_id])

    # -- مسودة / معتمد -------------------------------------------------------

    def approve(self, extract_id: Any, user_id: Any = None) -> None:
        approval.approve(self._db, approval.EXTRACT, extract_id, user_id)

    def unapprove(self, extract_id: Any) -> None:
        approval.unapprove(self._db, approval.EXTRACT, extract_id)
