"""مسودة / معتمد for the contracting records (user request, 2026-10-02).

Every record of the six contracting tables has a ``status``: «حفظ» stores it
as a draft, «اعتماد» approves it. Only approved records show outside their own
screen — in the other screens' lists, in every contracting report and on the
dashboard. A draft still shows on its own screen, marked «مسودة», so it can be
finished and approved there.

The rules, kept here so every screen applies them the same way:

* A record is approved only when what it hangs on is approved: a project's
  company; a contract's contractor and project; an extract's contract; a
  payment's contractor, project and extract. A new or edited draft may also
  only point at approved records, except a project, which is made on the same
  screen as its company.
* «إلغاء الاعتماد» puts a record back to draft only while nothing hangs on it
  (a contract with extracts, a contractor with contracts, ...). Together with
  the rule above, an approved record never hangs on a draft.
* An approved contract, extract or payment is locked: it is edited or deleted
  only after «إلغاء الاعتماد», except by a full-access (admin) user, who may do
  anything (user, 2026-10-02). An approved contractor, company or project stays
  editable for whoever may edit; deleting one is again admin-only.
* «اعتماد» and «إلغاء الاعتماد» are separate permissions (``approve`` /
  ``unapprove``) that the admin grants per user.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.db import Database

DRAFT, APPROVED = "draft", "approved"
STATUS_LABELS = {DRAFT: "مسودة", APPROVED: "معتمد"}

CONTRACTOR, COMPANY, PROJECT = "contractor", "company", "project"
CONTRACT, EXTRACT, PAYMENT = "contract", "extract", "payment"


class ApprovalError(ValueError):
    """A rule the user broke (approving under a draft, unapproving with children...): shown as-is."""


@dataclass(frozen=True)
class Kind:
    table: str
    id_col: str
    noun: str  # «المقاول», «العقد», ... as it reads in a message
    # (this table's column, the kind it points at) — what the record hangs on.
    parents: tuple[tuple[str, str], ...] = ()
    # (child table, its column pointing here, the child's noun) — what hangs on the record.
    children: tuple[tuple[str, str, str], ...] = ()
    # Approved records are locked (contracts, extracts, payments), not master data.
    locked_when_approved: bool = True


KINDS: dict[str, Kind] = {
    CONTRACTOR: Kind("contractors", "contractor_id", "المقاول",
                     children=(("contractor_contracts", "contractor_id", "عقد"),
                               ("contractor_payments", "contractor_id", "دفعة")),
                     locked_when_approved=False),
    COMPANY: Kind("client_companies", "company_id", "الشركة",
                  children=(("company_projects", "company_id", "مشروع"),),
                  locked_when_approved=False),
    PROJECT: Kind("company_projects", "project_id", "المشروع",
                  parents=(("company_id", COMPANY),),
                  children=(("contractor_contracts", "project_id", "عقد"),
                            ("contractor_payments", "project_id", "دفعة")),
                  locked_when_approved=False),
    CONTRACT: Kind("contractor_contracts", "contract_id", "العقد",
                   parents=(("contractor_id", CONTRACTOR), ("project_id", PROJECT)),
                   children=(("contractor_extracts", "contract_id", "مستخلص"),)),
    EXTRACT: Kind("contractor_extracts", "extract_id", "المستخلص",
                  parents=(("contract_id", CONTRACT),),
                  children=(("contractor_payments", "extract_id", "دفعة"),)),
    PAYMENT: Kind("contractor_payments", "payment_id", "الدفعة",
                  parents=(("contractor_id", CONTRACTOR), ("project_id", PROJECT), ("extract_id", EXTRACT))),
}


def status_label(status: Any) -> str:
    return STATUS_LABELS.get(str(status or ""), "")


def is_approved(record: dict[str, Any] | None) -> bool:
    return bool(record) and record.get("status") == APPROVED


def approved_only(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The approved rows of a screen's own list (drafts never count in its figures)."""
    return [row for row in rows if row.get("status") == APPROVED]


def get_status(db: Database, kind: str, record_id: Any) -> str | None:
    spec = KINDS[kind]
    row = db.fetch_one(f"SELECT status FROM {spec.table} WHERE {spec.id_col} = %s", [record_id])
    return row.get("status") if row else None


def check_parents(db: Database, parents: list[tuple[str, Any]]) -> None:
    """Refuse when any of *parents* — ``(kind, id)``, ``None`` ids skipped — is not approved."""
    for kind, record_id in parents:
        if record_id in (None, ""):
            continue
        if get_status(db, kind, record_id) != APPROVED:
            raise ApprovalError(f"لازم يتعمل اعتماد {KINDS[kind].noun} الأول — لسه مسودة.")


def check_unlocked(db: Database, kind: str, record_id: Any, action: str, allow_approved: bool) -> None:
    """Refuse *action* («تعديل» / «حذف») on an approved record unless *allow_approved* (admin)."""
    if allow_approved or record_id in (None, ""):
        return
    if get_status(db, kind, record_id) == APPROVED:
        raise ApprovalError(
            f"مينفعش {action} {KINDS[kind].noun} بعد الاعتماد. الغي الاعتماد الأول (بصلاحية «إلغاء الاعتماد»)."
        )


def approve(db: Database, kind: str, record_id: Any, user_id: Any = None) -> None:
    spec = KINDS[kind]
    status = get_status(db, kind, record_id)
    if status is None:
        raise ApprovalError("السجل ده مش موجود. اعمل تحديث للشاشة.")
    if status == APPROVED:
        raise ApprovalError("السجل ده معتمد بالفعل.")
    if spec.parents:
        row = db.fetch_one(
            f"SELECT {', '.join(column for column, _kind in spec.parents)} FROM {spec.table} "
            f"WHERE {spec.id_col} = %s",
            [record_id],
        ) or {}
        check_parents(db, [(parent, row.get(column)) for column, parent in spec.parents])
    db.execute(
        f"UPDATE {spec.table} SET status = %s, approved_at = now(), approved_by = %s "
        f"WHERE {spec.id_col} = %s AND status = %s",
        [APPROVED, user_id, record_id, DRAFT],
    )


def unapprove(db: Database, kind: str, record_id: Any) -> None:
    spec = KINDS[kind]
    status = get_status(db, kind, record_id)
    if status is None:
        raise ApprovalError("السجل ده مش موجود. اعمل تحديث للشاشة.")
    if status != APPROVED:
        raise ApprovalError("السجل ده مسودة أصلاً.")
    for table, column, noun in spec.children:
        row = db.fetch_one(f"SELECT count(*) AS n FROM {table} WHERE {column} = %s", [record_id])
        count = int(row["n"]) if row else 0
        if count:
            raise ApprovalError(
                f"مينفعش إلغاء اعتماد {spec.noun} لوجود {count} {noun} مرتبط. "
                "احذفهم الأول (بعد إلغاء اعتمادهم)."
            )
    db.execute(
        f"UPDATE {spec.table} SET status = %s, approved_at = NULL, approved_by = NULL "
        f"WHERE {spec.id_col} = %s AND status = %s",
        [DRAFT, record_id, APPROVED],
    )
