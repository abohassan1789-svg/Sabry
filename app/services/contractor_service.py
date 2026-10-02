"""Data helpers for شاشة المقاولين beyond the shared CRUD path.

The CRUD itself goes through ``ReviewDataService`` + ``TABLE_SPECS['contractors']``;
this only answers what that generic path cannot: the next suggested code, the
counts, and «اعتماد» / «إلغاء الاعتماد» (``contracting_approval``).
"""

from __future__ import annotations

import re
from typing import Any

from app.database.db import Database
from app.services import contracting_approval as approval

CODE_PREFIX = "A-H/CD-"
FIRST_CODE_NUMBER = 1001

# «A-H/CD-1001» — the prefix is matched case-insensitively and ignoring spaces
# around it, so a code the user retyped as «a-h/cd-1002» still counts.
_CODE_PATTERN = re.compile(r"^\s*A-H/CD-(\d+)\s*$", re.IGNORECASE)


def format_code(number: int) -> str:
    return f"{CODE_PREFIX}{number}"


def next_code_from(codes: list[Any]) -> str:
    """The code after the highest «A-H/CD-<n>» in *codes*, never below 1001.

    Codes the user typed in another shape are ignored rather than guessed at —
    they cannot collide with the suggestion, and the UNIQUE index catches the
    rest.
    """
    highest = FIRST_CODE_NUMBER - 1
    for code in codes:
        match = _CODE_PATTERN.match(str(code or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return format_code(highest + 1)


class ContractorService:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or Database()

    def next_code(self) -> str:
        """A display-only suggestion for a new contractor; editable on the form."""
        rows = self._db.fetch_all("SELECT contractor_code FROM contractors")
        return next_code_from([row["contractor_code"] for row in rows])

    def type_counts(self) -> dict[str, int]:
        """How many contractors of each نوع, plus ``""`` for the grand total."""
        rows = self._db.fetch_all(
            "SELECT contractor_type, count(*) AS n FROM contractors GROUP BY contractor_type"
        )
        counts = {row["contractor_type"]: int(row["n"]) for row in rows}
        counts[""] = sum(counts.values())
        return counts

    def list_rows(self, contractor_type: str | None = None) -> list[dict[str, Any]]:
        """The rows behind a count card: every contractor, or one نوع only."""
        query = (
            "SELECT contractor_id, contractor_code, contractor_name, contractor_type, "
            "registration_no, phone, current_balance FROM contractors"
        )
        params: list[Any] = []
        if contractor_type:
            query += " WHERE contractor_type = %s"
            params.append(contractor_type)
        query += " ORDER BY contractor_code"
        return self._db.fetch_all(query, params)

    def code_taken(self, code: str, except_id: Any = None) -> bool:
        """True if another contractor already uses *code* (trimmed, any case)."""
        row = self._db.fetch_one(
            "SELECT contractor_id FROM contractors "
            "WHERE upper(btrim(contractor_code)) = upper(btrim(%s)) "
            "AND (%s::integer IS NULL OR contractor_id <> %s::integer) LIMIT 1",
            [code, except_id, except_id],
        )
        return row is not None

    # -- مسودة / معتمد -------------------------------------------------------

    def status(self, contractor_id: Any) -> str | None:
        return approval.get_status(self._db, approval.CONTRACTOR, contractor_id)

    def approve(self, contractor_id: Any, user_id: Any = None) -> None:
        approval.approve(self._db, approval.CONTRACTOR, contractor_id, user_id)

    def unapprove(self, contractor_id: Any) -> None:
        approval.unapprove(self._db, approval.CONTRACTOR, contractor_id)
