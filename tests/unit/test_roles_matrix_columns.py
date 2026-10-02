"""مصفوفة مجموعات الصلاحيات: الأعمدة = الأفعال المستخدمة في الصفوف الظاهرة فقط."""

from app.ui.screens.roles_page import matrix_columns


def _row(*actions: str) -> dict:
    return {"actions": {a: i for i, a in enumerate(actions, start=1)}}


def test_columns_are_the_union_of_row_actions_in_registry_order():
    rows = [
        _row("view", "create", "edit", "save", "delete", "approve", "unapprove"),
        _row("view", "filter", "print", "export"),
        _row("view", "create", "edit", "save", "delete"),
    ]
    assert matrix_columns(rows) == ["view", "create", "edit", "save", "delete",
                                    "approve", "unapprove", "print", "export", "filter"]


def test_screens_scope_shows_no_report_only_columns():
    rows = [_row("view", "create", "edit", "save", "delete", "approve", "unapprove")]
    assert matrix_columns(rows) == ["view", "create", "edit", "save", "delete",
                                    "approve", "unapprove"]


def test_reports_scope_shows_only_report_columns():
    assert matrix_columns([_row("view", "filter", "print", "export")]) == [
        "view", "print", "export", "filter"]


def test_unused_actions_never_become_columns():
    cols = matrix_columns([_row("view", "save")])
    for unused in ("import", "post", "unpost", "preview"):
        assert unused not in cols


def test_no_rows_means_no_action_columns():
    assert matrix_columns([]) == []
