"""Data access for شاشة الشركات والمشاريع — a company owns many projects.

Two tables, ``client_companies`` and ``company_projects`` (a two-level tree), so
this screen does not ride the single-table ``ReviewDataService`` path.

Codes: a company is «A-H/CO-1001», «A-H/CO-1002», ...; a project starts with its
company's code: «A-H/CO-1001/PR-01», «A-H/CO-1001/PR-02», ... The screen
suggests the next of each, the user may edit them, and only uniqueness
(trimmed, any case) is enforced — here with a clear message, and by the UNIQUE
indexes underneath.

Both have a ``status`` (مسودة / معتمد, ``contracting_approval``). This screen
shows drafts too; every other screen and report sees approved ones only. An
approved company or project stays editable; only an admin deletes one.
"""

from __future__ import annotations

import re
from typing import Any

from app.database.db import Database
from app.services import contracting_approval as approval

COMPANY_PREFIX = "A-H/CO-"
FIRST_COMPANY_NUMBER = 1001
PROJECT_SEPARATOR = "/PR-"

_COMPANY_PATTERN = re.compile(r"^\s*A-H/CO-(\d+)\s*$", re.IGNORECASE)


class CompanyProjectError(ValueError):
    """A rule the user broke (duplicate code, blank name, ...): shown as-is."""


def next_company_code_from(codes: list[Any]) -> str:
    """The code after the highest «A-H/CO-<n>» in *codes*, never below 1001."""
    highest = FIRST_COMPANY_NUMBER - 1
    for code in codes:
        match = _COMPANY_PATTERN.match(str(code or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{COMPANY_PREFIX}{highest + 1}"


def next_project_code_from(company_code: str, codes: list[Any]) -> str:
    """«<company code>/PR-<nn>» after the highest one already under that company.

    Only codes that start with this company's own code count, so a project
    whose code was typed by hand in another shape never shifts the numbering.
    """
    base = str(company_code or "").strip()
    pattern = re.compile(rf"^\s*{re.escape(base)}{re.escape(PROJECT_SEPARATOR)}(\d+)\s*$", re.IGNORECASE)
    highest = 0
    for code in codes:
        match = pattern.match(str(code or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{base}{PROJECT_SEPARATOR}{highest + 1:02d}"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


class CompanyProjectService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    # -- reading -----------------------------------------------------------

    def tree(self, keyword: str = "") -> list[dict[str, Any]]:
        """Every company with its ``projects`` list, in code order.

        With a *keyword*, a company stays when its own code/name/address matches
        (with all its projects) or when any of its projects matches (with only
        those projects) — so a search never hides the branch a hit sits on.
        """
        companies = self._db.fetch_all(
            "SELECT company_id, company_code, company_name, address, status FROM client_companies "
            "ORDER BY company_code"
        )
        projects = self._db.fetch_all(
            "SELECT project_id, company_id, project_code, project_name, address, status FROM company_projects "
            "ORDER BY project_code"
        )
        by_company: dict[Any, list[dict[str, Any]]] = {}
        for project in projects:
            by_company.setdefault(project["company_id"], []).append(dict(project))

        needle = _clean(keyword).casefold()

        def hit(row: dict[str, Any], keys: tuple[str, ...]) -> bool:
            return needle in " ".join(_clean(row.get(k)) for k in keys).casefold()

        result = []
        for company in companies:
            company = dict(company)
            kids = by_company.get(company["company_id"], [])
            if needle and not hit(company, ("company_code", "company_name", "address")):
                kids = [p for p in kids if hit(p, ("project_code", "project_name", "address"))]
                if not kids:
                    continue
            company["projects"] = kids
            result.append(company)
        return result

    def get_company(self, company_id: Any) -> dict[str, Any] | None:
        return self._db.fetch_one(
            "SELECT c.company_id, c.company_code, c.company_name, c.address, c.status, "
            "(SELECT count(*) FROM company_projects p WHERE p.company_id = c.company_id) AS project_count "
            "FROM client_companies c WHERE c.company_id = %s",
            [company_id],
        )

    def get_project(self, project_id: Any) -> dict[str, Any] | None:
        return self._db.fetch_one(
            "SELECT p.project_id, p.company_id, p.project_code, p.project_name, p.address, p.status, "
            "c.company_code, c.company_name "
            "FROM company_projects p JOIN client_companies c ON c.company_id = p.company_id "
            "WHERE p.project_id = %s",
            [project_id],
        )

    def company_choices(self) -> list[dict[str, Any]]:
        return self._db.fetch_all(
            "SELECT company_id, company_code, company_name FROM client_companies ORDER BY company_code"
        )

    # -- codes -------------------------------------------------------------

    def next_company_code(self) -> str:
        rows = self._db.fetch_all("SELECT company_code FROM client_companies")
        return next_company_code_from([row["company_code"] for row in rows])

    def next_project_code(self, company_id: Any) -> str:
        company = self._db.fetch_one(
            "SELECT company_code FROM client_companies WHERE company_id = %s", [company_id]
        )
        if not company:
            return ""
        rows = self._db.fetch_all(
            "SELECT project_code FROM company_projects WHERE company_id = %s", [company_id]
        )
        return next_project_code_from(company["company_code"], [row["project_code"] for row in rows])

    def _code_taken(self, table: str, id_col: str, code_col: str, code: str, except_id: Any) -> bool:
        row = self._db.fetch_one(
            f"SELECT {id_col} FROM {table} WHERE upper(btrim({code_col})) = upper(btrim(%s)) "
            f"AND (%s::integer IS NULL OR {id_col} <> %s::integer) LIMIT 1",
            [code, except_id, except_id],
        )
        return row is not None

    # -- writing -----------------------------------------------------------

    def save_company(self, data: dict[str, Any], company_id: Any = None) -> int:
        code, name, address = _clean(data.get("company_code")), _clean(data.get("company_name")), _clean(data.get("address"))
        if not code:
            raise CompanyProjectError("كود الشركة مطلوب.")
        if not name:
            raise CompanyProjectError("اسم الشركة مطلوب.")
        if self._code_taken("client_companies", "company_id", "company_code", code, company_id):
            raise CompanyProjectError(f"الكود «{code}» مستخدم لشركة تانية. غيّر الكود قبل الحفظ.")
        params = [code, name, address or None]
        if company_id is None:
            row = self._db.fetch_one(
                "INSERT INTO client_companies (company_code, company_name, address) "
                "VALUES (%s, %s, %s) RETURNING company_id",
                params,
            )
            return int(row["company_id"])
        self._db.execute(
            "UPDATE client_companies SET company_code = %s, company_name = %s, address = %s "
            "WHERE company_id = %s",
            params + [company_id],
        )
        return int(company_id)

    def save_project(self, data: dict[str, Any], project_id: Any = None) -> int:
        company_id = data.get("company_id")
        code, name, address = _clean(data.get("project_code")), _clean(data.get("project_name")), _clean(data.get("address"))
        if company_id in (None, ""):
            raise CompanyProjectError("اختار الشركة اللي المشروع تابع لها.")
        if not code:
            raise CompanyProjectError("كود المشروع مطلوب.")
        if not name:
            raise CompanyProjectError("اسم المشروع مطلوب.")
        if self._code_taken("company_projects", "project_id", "project_code", code, project_id):
            raise CompanyProjectError(f"الكود «{code}» مستخدم لمشروع تاني. غيّر الكود قبل الحفظ.")
        params = [company_id, code, name, address or None]
        if project_id is None:
            row = self._db.fetch_one(
                "INSERT INTO company_projects (company_id, project_code, project_name, address) "
                "VALUES (%s, %s, %s, %s) RETURNING project_id",
                params,
            )
            return int(row["project_id"])
        self._db.execute(
            "UPDATE company_projects SET company_id = %s, project_code = %s, project_name = %s, address = %s "
            "WHERE project_id = %s",
            params + [project_id],
        )
        return int(project_id)

    def delete_company(self, company_id: Any, allow_approved: bool = False) -> None:
        approval.check_unlocked(self._db, approval.COMPANY, company_id, "حذف", allow_approved)
        count = self._db.fetch_one(
            "SELECT count(*) AS n FROM company_projects WHERE company_id = %s", [company_id]
        )
        if count and int(count["n"]):
            raise CompanyProjectError(
                f"الشركة دي تحتها {int(count['n'])} مشروع. احذف المشاريع الأول أو انقلها لشركة تانية."
            )
        self._db.execute("DELETE FROM client_companies WHERE company_id = %s", [company_id])

    def delete_project(self, project_id: Any, allow_approved: bool = False) -> None:
        approval.check_unlocked(self._db, approval.PROJECT, project_id, "حذف", allow_approved)
        count = self._db.fetch_one(
            "SELECT count(*) AS n FROM contractor_contracts WHERE project_id = %s", [project_id]
        )
        if count and int(count["n"]):
            raise CompanyProjectError(
                f"المشروع ده عليه {int(count['n'])} عقد مقاول. احذف العقود الأول أو انقلها لمشروع تاني."
            )
        count = self._db.fetch_one(
            "SELECT count(*) AS n FROM contractor_payments WHERE project_id = %s", [project_id]
        )
        if count and int(count["n"]):
            raise CompanyProjectError(
                f"المشروع ده عليه {int(count['n'])} دفعة مقاول. احذف الدفعات الأول من شاشة «دفعات المقاولين»."
            )
        self._db.execute("DELETE FROM company_projects WHERE project_id = %s", [project_id])

    # -- مسودة / معتمد -------------------------------------------------------

    def approve(self, kind: str, record_id: Any, user_id: Any = None) -> None:
        """*kind* is ``approval.COMPANY`` or ``approval.PROJECT``."""
        approval.approve(self._db, kind, record_id, user_id)

    def unapprove(self, kind: str, record_id: Any) -> None:
        approval.unapprove(self._db, kind, record_id)
