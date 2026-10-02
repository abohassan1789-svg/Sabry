# Contracting-Only Permissions Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** «مجموعات الصلاحيات» and «صلاحيات المستخدم» show only the contracting screens, the contracting reports and the three security screens, each with only the action columns it really uses (approve/unapprove on the five contracting data screens).

**Architecture:** The permission registry (`app/services/permission_registry.py`) gets a whitelist of the 13 targets the matrix may show and a per-target action list. `collect_targets()` filters by the whitelist and assigns each target its own actions. `build_permission_rows()` and the startup sync run on top of it, so every other permission becomes `is_active = false` and nothing is deleted. The roles page builds its columns from the rows it shows, instead of from the global 14-action list. The user-permissions page already lists active permissions only, so it needs no code change.

**Tech Stack:** Python 3.11, PySide6, PostgreSQL, pytest.

**Spec:** The in-chat design approved by the user on 2026-10-02 (bounded path, no spec file). Its content:
1. Rows (13):
   - **Contracting screens:** `contractors` (module `crm`), `company_projects`, `contractor_contracts`, `contractor_extracts`, `contractor_payments`.
   - **Contracting reports:** `contractors_dashboard`, `contractor_contracts_report`, `contractor_extracts_report`, `contractor_advance_report`, `contractor_statement_report`.
   - **Security screens:** `users`, `roles`, `user_permissions`.
2. Columns:
   - Contracting screens: view, create, edit, save, delete, approve, unapprove.
   - Dashboard and reports: view, filter, print, export.
   - Security screens: view, create, edit, save, delete.
   - import, post, unpost and preview disappear from the matrix.
3. Everything else is hidden from the matrix through the existing deactivation mechanism. Old grants are kept in the database. Non-admins are denied hidden targets, which are unreachable anyway because their sidebar sections are hidden.
4. approve/unapprove already exist and are enforced by `app/ui/screens/approval_controls.py`. Nothing new is added there.

## Global Constraints

- **Working directory:** every path and command is relative to `E:\PostGre\Moh Sabry\CRM_PYTHON_APP_STRUCTURE`.
- **No git commits.** The working tree carries ~470 uncommitted files from earlier work and the user has not asked to commit. Skip every commit step.
- **Permission codes must not change.** Keep `module_code.target_code.action_code` exactly as today: `crm.contractors.*`, `contracting.*`, `security.*`. A changed code orphans existing grants.
- **Nothing is deleted from the registry.** Hidden targets stay in `SCREEN_TARGETS` / `STATIC_REPORT_TARGETS` / discovered reports, and `HIDDEN_TARGET_CODES` stays as it is.
- **Arabic action names come from `ACTION_NAMES_AR`.** Don't hard-code new labels.
- **Run only the related tests.** The full suite takes over 10 minutes. Run `python -m pytest tests/unit/test_permission_system.py tests/unit/test_permission_ui_parity.py tests/unit/test_roles_matrix_columns.py tests/unit/test_contracting_approval.py tests/unit/test_report_navigation_registry.py -q`.
- **Baseline before this work:** 3 known failures, all fixed by Task 1:
  - `test_registry_includes_screens_reports_and_security`
  - `test_hidden_targets_are_excluded_from_the_rows_but_stay_registered`
  - `test_every_permission_target_is_reachable_in_the_ui`
- **Reply to the user in Egyptian Arabic.**

## Review Focus

1. **A database still holding the old active rows** (before the startup sync runs). The roles matrix must not show import/post/unpost columns that no row uses. Columns are derived from the rows, which covers this; the column-derivation test pins it.
2. **The «الشاشات» / «التقارير» radio filter.**
   - «الشاشات» must show 7 columns and no filter/print/export columns that no screen row uses.
   - «التقارير» must show the 4 report columns only.
   - Pinned by the scope tests in Task 2.
3. **A new report added later through `PERMISSION_TARGET` discovery.** It must stay out of the matrix until it is put on the whitelist. If it gets a sidebar entry without that, the parity test must fail loudly. Pinned by `test_every_visible_ui_screen_has_a_permission_target` in Task 1.
4. **`contractors` keeps module `crm`.** Its row must still be `crm.contractors.approve` / `crm.contractors.unapprove`, which is what `approval_controls` checks. Pinned in Task 1.
5. **Column-header click (`_toggle_column`) and «تحديد الكل».** These must only touch checkable cells. A «—» cell (an action the row doesn't have) must stay unchecked and non-checkable. This is existing behaviour that relies on `row["actions"].get(action) is None`. It is checked manually in Task 3.

---

### Task 1: Registry whitelist and per-target actions

**Files:**
- Modify: `app/services/permission_registry.py`
  - The module docstring.
  - After `HIDDEN_TARGET_CODES` (ends ~line 294), add the new constants.
  - `collect_targets()` (~lines 340-366).
- Modify: `tests/unit/test_permission_system.py`, lines 19-76 (the four registry tests).
- Modify: `tests/unit/test_permission_ui_parity.py`
  - `_ui_visible_codes()`
  - `test_hiding_is_subtractive_only`

**Interfaces:**
- Consumes: none.
- Produces (used by Task 2 only indirectly, through the DB rows):
  - `MATRIX_TARGET_CODES: frozenset[str]`
  - `CONTRACTING_SCREEN_ACTIONS: tuple[str, ...]`
  - `CONTRACTING_REPORT_ACTIONS: tuple[str, ...]`
  - `SECURITY_SCREEN_ACTIONS: tuple[str, ...]`
  - `TARGET_ACTIONS: dict[str, tuple[str, ...]]`
  - `is_target_shown(target_code: str) -> bool`
  - `collect_targets(include_hidden: bool = False)` keeps its signature. Each dict's `"actions"` is now the target's own list.

- [ ] **Step 1: Rewrite the registry tests to the new behaviour (failing)**

In `tests/unit/test_permission_system.py`, replace the import block and the four tests `test_registry_includes_screens_reports_and_security`, `test_hidden_targets_are_excluded_from_the_rows_but_stay_registered`, `test_every_screen_has_all_screen_actions` and `test_every_report_has_all_report_actions` with:

```python
"""Unit tests for the dynamic permissions system (no database needed)."""

from app.security.password_hasher import PasswordHasher
from app.services.permission_registry import (
    CONTRACTING_REPORT_ACTIONS,
    CONTRACTING_SCREEN_ACTIONS,
    MATRIX_TARGET_CODES,
    SECURITY_SCREEN_ACTIONS,
    build_permission_rows,
    collect_targets,
    make_permission_code,
)
from app.services.permission_service import resolve_effective
from app.services.permissions_sync_service import PermissionsSyncService

CONTRACTING_SCREENS = {"contractors", "company_projects", "contractor_contracts",
                       "contractor_extracts", "contractor_payments"}
CONTRACTING_REPORTS = {"contractors_dashboard", "contractor_contracts_report",
                       "contractor_extracts_report", "contractor_advance_report",
                       "contractor_statement_report"}
SECURITY_SCREENS = {"users", "roles", "user_permissions"}


def test_permission_code_format():
    assert make_permission_code("crm", "customers", "view") == "crm.customers.view"


def test_matrix_shows_only_contracting_and_security_targets():
    """User request 2026-10-02: the matrix is the contracting work + security only."""
    shown = {t["target_code"] for t in collect_targets()}
    assert shown == CONTRACTING_SCREENS | CONTRACTING_REPORTS | SECURITY_SCREENS
    assert shown == set(MATRIX_TARGET_CODES)


def test_contracting_screens_carry_approve_and_unapprove():
    codes = {row["permission_code"] for row in build_permission_rows()}
    # contractors keeps its crm module — approval_controls checks crm.contractors.*
    for base in ("crm.contractors", "contracting.company_projects",
                 "contracting.contractor_contracts", "contracting.contractor_extracts",
                 "contracting.contractor_payments"):
        assert f"{base}.approve" in codes
        assert f"{base}.unapprove" in codes
        assert f"{base}.import" not in codes
        assert f"{base}.post" not in codes


def test_each_target_gets_only_its_own_actions():
    by_code = {t["target_code"]: t for t in collect_targets()}
    for code in CONTRACTING_SCREENS:
        assert tuple(by_code[code]["actions"]) == CONTRACTING_SCREEN_ACTIONS
        assert by_code[code]["permission_type"] == "screen"
    for code in CONTRACTING_REPORTS:
        assert tuple(by_code[code]["actions"]) == CONTRACTING_REPORT_ACTIONS
        assert by_code[code]["permission_type"] == "report"
    for code in SECURITY_SCREENS:
        assert tuple(by_code[code]["actions"]) == SECURITY_SCREEN_ACTIONS
    assert CONTRACTING_SCREEN_ACTIONS == ("view", "create", "edit", "save", "delete",
                                          "approve", "unapprove")
    assert CONTRACTING_REPORT_ACTIONS == ("view", "filter", "print", "export")
    assert SECURITY_SCREEN_ACTIONS == ("view", "create", "edit", "save", "delete")


def test_hidden_targets_are_excluded_from_the_rows_but_stay_registered():
    """Hidden ≠ unregistered — the distinction the sync depends on.

    The rows drive the sync, so a hidden target must be absent from them (that
    is what flips it to is_active=false and makes it disappear from the matrix).
    Its entry must nonetheless survive in the registry, or re-enabling it later
    would mean re-typing the whole target rather than deleting one line.
    """
    codes = {row["permission_code"] for row in build_permission_rows()}
    for hidden in ("crm.customers.view", "crm.receipt_vouchers.delete",
                   "sales.saudi_sales_invoices.approve", "tawrid.tawrid_tickets.view",
                   "crm.daily_followups.delete", "reports.sales_report.preview"):
        assert hidden not in codes, f"{hidden} is hidden and must not sync as active"

    registered = {t["target_code"] for t in collect_targets(include_hidden=True)}
    assert {"customers", "receipt_vouchers", "saudi_sales_invoices", "tawrid_tickets",
            "daily_followups", "sales_report"} <= registered
```

Leave `test_resolver_role_base_then_override` and everything after it untouched.

In `tests/unit/test_permission_ui_parity.py`, replace the import block, `_ui_visible_codes()` and `test_hiding_is_subtractive_only` with:

```python
from app.services.permission_registry import (
    HIDDEN_TARGET_CODES,
    MATRIX_TARGET_CODES,
    collect_targets,
)

# Sidebar items that are always shown and have no permission row
# (main_window._can_view returns True for them).
_UNPERMISSIONED_NAV_KEYS = {"backup", "connection_settings"}


def _ui_visible_codes() -> set[str]:
    """Every target_code a user can actually reach from the sidebar.

    The sidebar is built from NAV_SECTIONS only: whole sections in
    HIDDEN_NAV_SECTIONS are skipped and items in HIDDEN_NAV_KEYS are dropped.
    """
    from app.ui.main_window import HIDDEN_NAV_KEYS, HIDDEN_NAV_SECTIONS, NAV_SECTIONS

    codes = {
        key
        for section_id, _title, _icon, items in NAV_SECTIONS
        if section_id not in HIDDEN_NAV_SECTIONS
        for key, _label, _item_icon in items
    }
    return codes - HIDDEN_NAV_KEYS - _UNPERMISSIONED_NAV_KEYS
```

```python
def test_hiding_is_subtractive_only() -> None:
    """collect_targets() must filter, never reshape. Guards the sync contract.

    PermissionsSyncService deactivates whatever is absent from collect_targets(),
    so if hiding ever changed a *kept* target's code the sync would deactivate
    the real row and add a stranger — silently orphaning live grants.
    """
    shown = collect_targets()
    every = collect_targets(include_hidden=True)
    assert shown == [t for t in every
                     if t["target_code"] in MATRIX_TARGET_CODES
                     and t["target_code"] not in HIDDEN_TARGET_CODES]


def test_matrix_whitelist_names_only_registered_targets() -> None:
    """A typo'd code in MATRIX_TARGET_CODES would silently drop a screen."""
    all_codes = {t["target_code"] for t in collect_targets(include_hidden=True)}
    assert MATRIX_TARGET_CODES <= all_codes
```

Keep the other parity tests as they are: the two direction tests, `test_hidden_codes_are_really_registered` and the parametrized `test_the_requested_targets_stay_hidden`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_permission_system.py tests/unit/test_permission_ui_parity.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'CONTRACTING_REPORT_ACTIONS'` (and `MATRIX_TARGET_CODES`).

- [ ] **Step 3: Add the whitelist and per-target actions to the registry**

In `app/services/permission_registry.py`, add this after the closing `})` of `HIDDEN_TARGET_CODES`:

```python
# --- What the matrix shows ---------------------------------------------------
# User request (2026-10-02): مجموعات الصلاحيات / صلاحيات المستخدم list ONLY the
# contracting screens and reports (the sidebar's «المقاولات» + «التقارير») and
# the three security screens. Every other target stays registered but is not
# synced as active — same effect as HIDDEN_TARGET_CODES (old grants survive,
# non-admins are denied, which is moot: their sidebar sections are hidden).
# A new screen/report needs its code here AND in TARGET_ACTIONS to appear.
CONTRACTING_SCREEN_ACTIONS: tuple[str, ...] = (
    "view", "create", "edit", "save", "delete", "approve", "unapprove",
)
CONTRACTING_REPORT_ACTIONS: tuple[str, ...] = ("view", "filter", "print", "export")
SECURITY_SCREEN_ACTIONS: tuple[str, ...] = ("view", "create", "edit", "save", "delete")

TARGET_ACTIONS: dict[str, tuple[str, ...]] = {
    # المقاولات — شاشات (contractors keeps module "crm": crm.contractors.*).
    "contractors": CONTRACTING_SCREEN_ACTIONS,
    "company_projects": CONTRACTING_SCREEN_ACTIONS,
    "contractor_contracts": CONTRACTING_SCREEN_ACTIONS,
    "contractor_extracts": CONTRACTING_SCREEN_ACTIONS,
    "contractor_payments": CONTRACTING_SCREEN_ACTIONS,
    # المقاولات — داشبورد وتقارير.
    "contractors_dashboard": CONTRACTING_REPORT_ACTIONS,
    "contractor_contracts_report": CONTRACTING_REPORT_ACTIONS,
    "contractor_extracts_report": CONTRACTING_REPORT_ACTIONS,
    "contractor_advance_report": CONTRACTING_REPORT_ACTIONS,
    "contractor_statement_report": CONTRACTING_REPORT_ACTIONS,
    # النظام والصلاحيات.
    "users": SECURITY_SCREEN_ACTIONS,
    "roles": SECURITY_SCREEN_ACTIONS,
    "user_permissions": SECURITY_SCREEN_ACTIONS,
}

MATRIX_TARGET_CODES: frozenset[str] = frozenset(TARGET_ACTIONS)


def is_target_shown(target_code: str) -> bool:
    """True when the target is synced as active and listed in the matrix."""
    return target_code in MATRIX_TARGET_CODES and target_code not in HIDDEN_TARGET_CODES
```

Replace `collect_targets()` with:

```python
def collect_targets(include_hidden: bool = False) -> list[dict[str, Any]]:
    """Return every registered target with its type, category and actions.

    Only ``MATRIX_TARGET_CODES`` (minus ``HIDDEN_TARGET_CODES``) are returned
    unless ``include_hidden`` — that flag exists for tooling that needs the
    full registry (and for the parity test); the sync and the UI both want the
    filtered view. A target's actions come from ``TARGET_ACTIONS``, falling back
    to the full screen/report action set for targets outside the matrix.
    """
    screen_actions = [code for code, _ar, _en in SCREEN_ACTIONS]
    report_actions = [code for code, _ar, _en in REPORT_ACTIONS]
    targets: list[dict[str, Any]] = []
    for screen in SCREEN_TARGETS:
        targets.append({
            **screen,
            "permission_type": "screen",
            "category_ar": CATEGORY_SCREEN_AR,
            "category_en": CATEGORY_SCREEN_EN,
            "actions": list(TARGET_ACTIONS.get(screen["target_code"], screen_actions)),
        })
    for report in report_targets():
        targets.append({
            **report,
            "permission_type": "report",
            "category_ar": CATEGORY_REPORT_AR,
            "category_en": CATEGORY_REPORT_EN,
            "actions": list(TARGET_ACTIONS.get(report["target_code"], report_actions)),
        })
    if include_hidden:
        return targets
    return [t for t in targets if is_target_shown(t["target_code"])]
```

In the module docstring, replace the paragraph starting "To HIDE a screen/report…" with:

```
The matrix shows ONLY the targets in ``MATRIX_TARGET_CODES`` (built from
``TARGET_ACTIONS``, which also fixes each target's action columns). To show a
new screen/report, add it there. ``HIDDEN_TARGET_CODES`` still hides on top of
that. Read the notes there first — anything not shown is denied to every
non-admin, so it must move in step with the sidebar.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_permission_system.py tests/unit/test_permission_ui_parity.py -q`
Expected: all pass, 0 failed. The 3 baseline failures are gone, because tawrid_tickets2 and the old report expectations are no longer in play.

If `test_every_visible_ui_screen_has_a_permission_target` fails, a visible sidebar item has no whitelisted target. Read the code it names. Only add it to `TARGET_ACTIONS` if it is one of the 13 targets in the spec; otherwise stop and report.

- [ ] **Step 5: Run the neighbouring regression tests**

Run: `python -m pytest tests/unit/test_contracting_approval.py tests/unit/test_report_navigation_registry.py -q`
Expected: PASS. If `test_report_navigation_registry` asserts a now-hidden report is in `collect_targets()`, report it to the user before changing that test.

- [ ] **Step 6: Commit** — skipped (Global Constraints: no commits).

---

### Task 2: Roles matrix columns derived from the shown rows

**Files:**
- Modify: `app/ui/screens/roles_page.py`
  - Imports (line 35).
  - `_columns_for_scope` (lines 278-288).
  - `rebuild_matrix` (lines 290-297).
- Create: `tests/unit/test_roles_matrix_columns.py`

**Interfaces:**
- Consumes: the `build_matrix(scope)` row shape from `PermissionService` (`app/services/permission_service.py:73`). Each row has `"actions": dict[action_code, permission_id]`.
- Produces: `matrix_columns(rows: list[dict[str, Any]]) -> list[str]`, a module-level pure function in `roles_page.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_roles_matrix_columns.py`:

```python
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
```

Column order follows `(*SCREEN_ACTIONS, *REPORT_ACTIONS)` de-duplicated: view, create, edit, save, delete, approve, unapprove, print, export, import, post, unpost, preview, filter. That is why `filter` comes after `export`, matching the old "all" scope order.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_roles_matrix_columns.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'matrix_columns'`.

- [ ] **Step 3: Implement `matrix_columns` and use it**

In `app/ui/screens/roles_page.py`, after `T = "security.roles"` (line 40), add:

```python
# Every action in registry order; the matrix shows only those its rows use.
_ACTION_ORDER: tuple[str, ...] = tuple(dict.fromkeys(
    code for code, _ar, _en in (*SCREEN_ACTIONS, *REPORT_ACTIONS)
))


def matrix_columns(rows: list[dict[str, Any]]) -> list[str]:
    """The action columns for *rows*: the actions any row has, in registry order."""
    used = {action for row in rows for action in row["actions"]}
    return [code for code in _ACTION_ORDER if code in used]
```

Delete the `_columns_for_scope` method (lines 278-288). In `rebuild_matrix`, replace

```python
        self.active_columns = self._columns_for_scope()
```

with

```python
        self.active_columns = matrix_columns(self.rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/unit/test_roles_matrix_columns.py tests/unit/test_permission_system.py tests/unit/test_permission_ui_parity.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** — skipped (Global Constraints: no commits).

---

### Task 3: Verify in the real app and record the decision

**Files:**
- Modify: `C:\Users\hp\.claude\projects\E--PostGre-Moh-Sabry\memory\sidebar-visibility.md`. Add a line linking the new memory.
- Create: `C:\Users\hp\.claude\projects\E--PostGre-Moh-Sabry\memory\contracting-only-permissions.md`
- Modify: `C:\Users\hp\.claude\projects\E--PostGre-Moh-Sabry\memory\MEMORY.md`. Add one index line.

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: none.

- [ ] **Step 1: Run the related suite once**

Run: `python -m pytest tests/unit/test_permission_system.py tests/unit/test_permission_ui_parity.py tests/unit/test_roles_matrix_columns.py tests/unit/test_contracting_approval.py tests/unit/test_report_navigation_registry.py -q`
Expected: all pass. Paste the summary line in the report.

- [ ] **Step 2: Launch the app, which runs the startup sync**

Use the `run` skill. The app's bootstrap (`app/ui/review_window.py:83`) calls `PermissionsSyncService.sync()` on start, so the database is reconciled without pressing «مزامنة الصلاحيات». Log in as the admin.

- [ ] **Step 3: Check «مجموعات الصلاحيات»**

- **«الكل»:** exactly 13 rows. The columns must be: عرض، إضافة، تعديل، حفظ، حذف، اعتماد، إلغاء الاعتماد، طباعة، تصدير، تصفية.
  - Contracting screen rows show «—» under طباعة/تصدير/تصفية.
  - Report rows show «—» under إضافة…إلغاء الاعتماد.
  - Security rows show «—» under اعتماد/إلغاء الاعتماد.
- **«الشاشات»:** 8 rows, 7 columns.
- **«التقارير»:** 5 rows, 4 columns (عرض، طباعة، تصدير، تصفية).
- **Header clicks:** click the «اعتماد» header twice. Only the 5 contracting screen cells toggle and «—» cells stay inert (Review Focus 5).
- **Fit:** the matrix fits ~1700×900 without horizontal scroll.

- [ ] **Step 4: Check «صلاحيات المستخدم»**

Pick a non-admin user. Only permissions of those 13 targets are listed, and there are no import/post/unpost/preview rows.

- [ ] **Step 5: Spot-check enforcement**

As a non-admin whose group has `contracting.contractor_contracts.approve` unchecked, open عقود المقاولين. «اعتماد» must be disabled. Re-check it, save the group, log in again: «اعتماد» must be enabled on a saved draft.

- [ ] **Step 6: Write the memory**

Create `contracting-only-permissions.md`:

```markdown
---
name: contracting-only-permissions
description: "Permissions matrix limited to contracting screens/reports + 3 security screens, per-target columns (2026-10-02)"
metadata:
  type: project
---

On 2026-10-02 the user asked that مجموعات الصلاحيات / صلاحيات المستخدم show only the contracting work. 13 rows: the 5 contracting screens (contractors stays crm.contractors.*), the dashboard + 4 contracting reports, and users/roles/user_permissions (user chose to keep these).

Columns per target (`TARGET_ACTIONS` in `app/services/permission_registry.py`): screens view/create/edit/save/delete/approve/unapprove; reports view/filter/print/export (print/export for phase 3); security view/create/edit/save/delete. The roles page derives its columns from the shown rows (`matrix_columns`).

Everything else is not synced as active (grants kept, non-admins denied), on top of `HIDDEN_TARGET_CODES`. The startup sync applies it.

**Why:** the app is being narrowed to the contracting work ([[sidebar-visibility]]).
**How to apply:** a new contracting screen/report must be added to `TARGET_ACTIONS`, or non-admins can't see it; the parity test fails if it has a sidebar entry without that. Related: [[contracting-draft-approval]].
```

Add this to `MEMORY.md`:

```
- [Contracting-only permissions](contracting-only-permissions.md) — matrix = 13 targets (contracting + 3 security), per-target columns via TARGET_ACTIONS (2026-10-02)
```

In `sidebar-visibility.md`, replace the "Tests that were already failing" block with:

```
The 3 pre-existing permission test failures were fixed on 2026-10-02 by [[contracting-only-permissions]].
```

- [ ] **Step 7: Report to the user in Egyptian Arabic.** Cover what changed, the test result line, what was seen in the app, and that old grants are kept, not deleted.
