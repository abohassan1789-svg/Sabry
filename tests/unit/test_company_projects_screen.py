"""Widget tests for شاشة الشركات والمشاريع — النموذج 9 (headless Qt, no database).

Covers what the user asked for:

* Companies are drawn as branches with their projects under them.
* Codes: a company is «A-H/CO-<n>» from 1001; a project starts with its
  company's code, «A-H/CO-1001/PR-01». Both are suggested and stay editable.
* «مشروع جديد» belongs to the company currently selected (or the selected
  project's company), and changing the company re-suggests the code — unless the
  user already typed one.
* A company with projects cannot be deleted.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from app.services.company_project_service import (
    CompanyProjectError,
    next_company_code_from,
    next_project_code_from,
)
from app.ui.screens import company_projects_screen as screen_module
from app.ui.screens.company_projects_screen import CompanyProjectsScreen, _short_project_code

COMPANIES = {
    1: {"company_id": 1, "company_code": "A-H/CO-1001", "company_name": "شركة الأهرام", "address": "القاهرة",
        "status": "draft"},
    2: {"company_id": 2, "company_code": "A-H/CO-1002", "company_name": "مجموعة النيل", "address": None,
        "status": "approved"},
}
PROJECTS = {
    10: {"project_id": 10, "company_id": 1, "project_code": "A-H/CO-1001/PR-01",
         "project_name": "برج الأهرام", "address": "التجمع", "status": "approved"},
    11: {"project_id": 11, "company_id": 1, "project_code": "A-H/CO-1001/PR-02",
         "project_name": "كمبوند الياسمين", "address": None, "status": "draft"},
}


class FakeService:
    def __init__(self):
        self.saved = []
        self.deleted = []
        self.approved = []
        self.unapproved = []

    def tree(self, keyword=""):
        out = []
        for company in COMPANIES.values():
            kids = [dict(p) for p in PROJECTS.values() if p["company_id"] == company["company_id"]]
            out.append(dict(company, projects=kids))
        return out

    def get_company(self, company_id):
        company = COMPANIES.get(int(company_id))
        if company is None:
            return None
        count = sum(1 for p in PROJECTS.values() if p["company_id"] == company["company_id"])
        return dict(company, project_count=count)

    def get_project(self, project_id):
        project = PROJECTS.get(int(project_id))
        if project is None:
            return None
        company = COMPANIES[project["company_id"]]
        return dict(project, company_code=company["company_code"], company_name=company["company_name"])

    def company_choices(self):
        return [dict(c) for c in COMPANIES.values()]

    def next_company_code(self):
        return "A-H/CO-1003"

    def next_project_code(self, company_id):
        return {1: "A-H/CO-1001/PR-03", 2: "A-H/CO-1002/PR-01"}.get(company_id, "")

    def save_company(self, data, company_id=None):
        self.saved.append(("company", dict(data), company_id))
        return company_id or 1

    def save_project(self, data, project_id=None):
        self.saved.append(("project", dict(data), project_id))
        return project_id or 10

    def delete_company(self, company_id, allow_approved=False):
        if any(p["company_id"] == int(company_id) for p in PROJECTS.values()):
            raise CompanyProjectError("الشركة دي تحتها مشاريع.")
        self.deleted.append(("company", company_id))

    def delete_project(self, project_id, allow_approved=False):
        self.deleted.append(("project", project_id))

    def approve(self, kind, record_id, user_id=None):
        self.approved.append((kind, record_id))

    def unapprove(self, kind, record_id):
        self.unapproved.append((kind, record_id))


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(qt_app, monkeypatch):
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(screen_module.QMessageBox, name, lambda *a, **k: None)
    monkeypatch.setattr(screen_module.QMessageBox, "question",
                        lambda *a, **k: screen_module.QMessageBox.Yes)
    return CompanyProjectsScreen(FakeService())


# --- codes -------------------------------------------------------------------------

@pytest.mark.parametrize("codes,expected", [
    ([], "A-H/CO-1001"),
    (["A-H/CO-1001", " a-h/co-1004 "], "A-H/CO-1005"),
    (["X", None], "A-H/CO-1001"),
])
def test_next_company_code(codes, expected):
    assert next_company_code_from(codes) == expected


@pytest.mark.parametrize("codes,expected", [
    ([], "A-H/CO-1001/PR-01"),
    (["A-H/CO-1001/PR-01", "A-H/CO-1001/PR-09"], "A-H/CO-1001/PR-10"),
    (["A-H/CO-1002/PR-05", "other"], "A-H/CO-1001/PR-01"),
])
def test_next_project_code_starts_with_the_company_code(codes, expected):
    assert next_project_code_from("A-H/CO-1001", codes) == expected


def test_short_project_code():
    assert _short_project_code("A-H/CO-1001/PR-02") == "PR-02"


# --- the branches -------------------------------------------------------------------

def test_every_company_and_project_gets_a_button(screen):
    assert set(screen._buttons) == {("company", 1), ("company", 2), ("project", 10), ("project", 11)}


def test_clicking_a_project_opens_it_in_the_drawer(screen):
    screen._buttons[("project", 11)].click()
    assert screen.kind == "project" and screen.current_id == 11
    assert screen.stack.currentIndex() == 2
    assert screen.project_name.text() == "كمبوند الياسمين"
    assert screen.project_company.currentData() == 1
    assert screen.project_name.isReadOnly()


def test_clicking_a_company_shows_its_project_count(screen):
    screen._buttons[("company", 1)].click()
    assert screen.stack.currentIndex() == 1
    assert screen.company_code.text() == "A-H/CO-1001"
    assert "2" in screen.company_projects_label.text()


# --- new ---------------------------------------------------------------------------------

def test_new_company_suggests_the_next_code_and_it_stays_editable(screen):
    screen.new_company()
    assert screen.mode == "new"
    assert screen.company_code.text() == "A-H/CO-1003"
    assert screen.company_code.isReadOnly() is False


def test_new_project_belongs_to_the_selected_company(screen):
    screen.select_company(2)
    screen.new_project()
    assert screen.project_company.currentData() == 2
    assert screen.project_code.text() == "A-H/CO-1002/PR-01"


def test_new_project_from_a_selected_project_uses_its_company(screen):
    screen.select_project(10)
    screen.new_project()
    assert screen.project_code.text() == "A-H/CO-1001/PR-03"


def test_changing_the_company_resuggests_the_code(screen):
    screen.select_company(1)
    screen.new_project()
    screen.project_company.setCurrentIndex(screen.project_company.findData(2))
    assert screen.project_code.text() == "A-H/CO-1002/PR-01"


def test_a_typed_code_is_not_overwritten(screen):
    screen.select_company(1)
    screen.new_project()
    screen.project_code.setText("MY-CODE")
    screen.project_company.setCurrentIndex(screen.project_company.findData(2))
    assert screen.project_code.text() == "MY-CODE"


def test_saving_a_new_project_sends_its_company(screen):
    screen.select_company(1)
    screen.new_project()
    screen.project_name.setText("مدرسة النور")
    screen.save_record()
    kind, data, record_id = screen.service.saved[-1]
    assert (kind, record_id) == ("project", None)
    assert data["company_id"] == 1 and data["project_code"] == "A-H/CO-1001/PR-03"
    assert screen.mode == "view"


def test_selecting_is_blocked_while_editing(screen):
    screen.new_company()
    screen.select_project(10)
    assert screen.kind == "company" and screen.mode == "new"


# --- delete --------------------------------------------------------------------------------

def test_a_company_with_projects_is_not_deleted(screen):
    screen.select_company(1)
    screen.delete_record()
    assert screen.service.deleted == []
    assert screen.current_id == 1


def test_a_project_is_deleted(screen):
    screen.select_project(11)
    screen.delete_record()
    assert screen.service.deleted == [("project", 11)]
    assert screen.current_id is None


# --- مسودة / معتمد --------------------------------------------------------------------------

def test_drafts_are_marked_on_the_branches(screen):
    def texts(key):
        return [label.text() for label in screen._buttons[key].findChildren(QLabel)]
    assert "مسودة" in texts(("project", 11))
    assert "مسودة" not in texts(("project", 10))
    assert "مسودة" in texts(("company", 1))


def test_approving_a_draft_project(screen):
    screen.select_project(11)
    assert screen.approval.badge.text() == "مسودة"
    assert screen.approval.approve_button.isEnabled() and not screen.approval.unapprove_button.isEnabled()
    screen.approve_record()
    assert screen.service.approved == [("project", 11)]


def test_an_approved_company_is_edited_but_not_deleted(screen):
    screen.select_company(2)
    assert screen.approval.badge.text() == "معتمد"
    assert screen.edit_button.isEnabled()
    assert not screen.delete_button.isEnabled()
    screen.delete_record()
    assert screen.service.deleted == []
    screen.unapprove_record()
    assert screen.service.unapproved == [("company", 2)]


def test_an_admin_deletes_an_approved_project(screen):
    screen.approval.is_admin = True
    screen.select_project(10)
    assert screen.delete_button.isEnabled()
    screen.delete_record()
    assert screen.service.deleted == [("project", 10)]


# --- القوايم في باقي الشاشات (user request 2026-10-02) ----------------------------------------

def test_saving_and_deleting_a_project_announce_a_change(screen, data_changes):
    screen.select_company(1)
    screen.new_project()
    screen.project_name.setText("مدرسة النور")
    screen.save_record()
    screen.select_project(11)
    screen.delete_record()
    assert data_changes == [screen, screen]


def test_a_refused_delete_does_not_announce_a_change(screen, data_changes):
    screen.select_company(1)  # still has projects
    screen.delete_record()
    assert data_changes == []
