"""Rules of مسودة / معتمد on the contracting records (user request, 2026-10-02) — no database.

* «اعتماد» needs what the record hangs on to be approved already.
* «إلغاء الاعتماد» is refused while anything hangs on the record.
* An approved contract / extract / payment is locked unless an admin acts.
"""

from __future__ import annotations

import re

import pytest

from app.services import contracting_approval as approval
from app.services.contracting_approval import APPROVED, DRAFT, ApprovalError


class FakeDb:
    """Rows per table: ``{table: {id: row}}``; answers the few queries the module makes."""

    def __init__(self, tables):
        self.tables = tables
        self.updates = []

    def _row(self, sql, params):
        table = re.search(r"FROM (\w+)", sql).group(1)
        return self.tables.get(table, {}).get(params[0])

    def fetch_one(self, sql, params):
        if sql.startswith("SELECT count(*)"):
            table, column = re.search(r"FROM (\w+) WHERE (\w+) =", sql).groups()
            rows = self.tables.get(table, {}).values()
            return {"n": sum(1 for row in rows if row.get(column) == params[0])}
        return self._row(sql, params)

    def execute(self, sql, params):
        self.updates.append((sql, params))
        table = re.search(r"UPDATE (\w+)", sql).group(1)
        row = self.tables[table][params[-2]]
        row["status"] = params[0]


def _db(contractor=APPROVED, project=APPROVED, contract=DRAFT, extracts=()):
    return FakeDb({
        "contractors": {1: {"status": contractor}},
        "client_companies": {5: {"status": APPROVED}},
        "company_projects": {10: {"status": project, "company_id": 5}},
        "contractor_contracts": {100: {"status": contract, "contractor_id": 1, "project_id": 10}},
        "contractor_extracts": {x: {"status": APPROVED, "contract_id": 100} for x in extracts},
        "contractor_payments": {},
    })


def test_a_contract_is_approved_when_its_contractor_and_project_are():
    db = _db()
    approval.approve(db, approval.CONTRACT, 100, user_id=2)
    assert db.tables["contractor_contracts"][100]["status"] == APPROVED
    sql, params = db.updates[-1]
    assert "approved_by" in sql and params[:2] == [APPROVED, 2]


@pytest.mark.parametrize("contractor,project", [(DRAFT, APPROVED), (APPROVED, DRAFT)])
def test_a_contract_under_a_draft_is_not_approved(contractor, project):
    db = _db(contractor=contractor, project=project)
    with pytest.raises(ApprovalError, match="مسودة"):
        approval.approve(db, approval.CONTRACT, 100)
    assert db.updates == []


def test_approving_twice_is_refused():
    with pytest.raises(ApprovalError, match="معتمد بالفعل"):
        approval.approve(_db(contract=APPROVED), approval.CONTRACT, 100)


def test_unapprove_is_refused_while_extracts_hang_on_the_contract():
    db = _db(contract=APPROVED, extracts=(500, 501))
    with pytest.raises(ApprovalError, match="2 مستخلص"):
        approval.unapprove(db, approval.CONTRACT, 100)
    assert db.tables["contractor_contracts"][100]["status"] == APPROVED


def test_unapprove_puts_a_record_back_to_draft():
    db = _db(contract=APPROVED)
    approval.unapprove(db, approval.CONTRACT, 100)
    assert db.tables["contractor_contracts"][100]["status"] == DRAFT
    with pytest.raises(ApprovalError, match="مسودة أصلاً"):
        approval.unapprove(db, approval.CONTRACT, 100)


def test_an_approved_contract_is_locked_but_not_for_an_admin():
    db = _db(contract=APPROVED)
    with pytest.raises(ApprovalError, match="تعديل"):
        approval.check_unlocked(db, approval.CONTRACT, 100, "تعديل", allow_approved=False)
    approval.check_unlocked(db, approval.CONTRACT, 100, "تعديل", allow_approved=True)
    approval.check_unlocked(_db(), approval.CONTRACT, 100, "تعديل", allow_approved=False)  # a draft
    approval.check_unlocked(db, approval.CONTRACT, None, "تعديل", allow_approved=False)  # a new one


def test_check_parents_skips_an_empty_choice():
    approval.check_parents(_db(), [(approval.CONTRACTOR, 1), (approval.EXTRACT, None)])
    with pytest.raises(ApprovalError):
        approval.check_parents(_db(contractor=DRAFT), [(approval.CONTRACTOR, 1)])


def test_only_transactions_are_locked_when_approved():
    locked = {kind for kind, spec in approval.KINDS.items() if spec.locked_when_approved}
    assert locked == {approval.CONTRACT, approval.EXTRACT, approval.PAYMENT}


def test_approved_only_and_labels():
    rows = [{"status": APPROVED}, {"status": DRAFT}, {}]
    assert approval.approved_only(rows) == [{"status": APPROVED}]
    assert approval.status_label(DRAFT) == "مسودة" and approval.status_label(None) == ""
