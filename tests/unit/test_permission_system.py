"""Unit tests for the dynamic permissions system (no database needed)."""

from app.security.password_hasher import PasswordHasher
from app.services.permission_registry import (
    CONTRACTING_REPORT_ACTIONS,
    CONTRACTING_SCREEN_ACTIONS,
    MATRIX_TARGET_CODES,
    SECURITY_SCREEN_ACTIONS,
    COMPANY_INFO_ACTIONS,
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
                       "contractor_statement_report", "contractor_withholding_report"}
SECURITY_SCREENS = {"users", "roles", "user_permissions"}
COMPANY_INFO_SCREENS = {"company_info"}


def test_permission_code_format():
    assert make_permission_code("crm", "customers", "view") == "crm.customers.view"


def test_matrix_shows_only_contracting_and_security_targets():
    """User request 2026-10-02: the matrix is the contracting work + security only."""
    shown = {t["target_code"] for t in collect_targets()}
    assert shown == CONTRACTING_SCREENS | CONTRACTING_REPORTS | SECURITY_SCREENS | COMPANY_INFO_SCREENS
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
    for code in COMPANY_INFO_SCREENS:
        assert tuple(by_code[code]["actions"]) == COMPANY_INFO_ACTIONS
        assert by_code[code]["permission_type"] == "screen"
    assert CONTRACTING_SCREEN_ACTIONS == ("view", "create", "edit", "save", "delete",
                                          "approve", "unapprove")
    assert CONTRACTING_REPORT_ACTIONS == ("view", "filter", "print", "export")
    assert SECURITY_SCREEN_ACTIONS == ("view", "create", "edit", "save", "delete")
    assert COMPANY_INFO_ACTIONS == ("view", "create", "edit", "save", "delete")


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


def test_resolver_role_base_then_override():
    perms = [
        {"id": 1, "permission_code": "a"},
        {"id": 2, "permission_code": "b"},
        {"id": 3, "permission_code": "c"},
        {"id": 4, "permission_code": "d"},
    ]
    role_map = {1: True, 2: False, 4: True}
    user_map = {2: True, 4: False}  # allow b, deny d
    resolved = resolve_effective(perms, role_map, user_map, is_full_access=False)
    assert resolved[1]["allowed"] is True and resolved[1]["source"] == "role"
    assert resolved[2]["allowed"] is True and resolved[2]["source"] == "override"
    assert resolved[3]["allowed"] is False and resolved[3]["source"] == "role"
    assert resolved[4]["allowed"] is False and resolved[4]["source"] == "override"


def test_resolver_full_access_allows_everything():
    perms = [{"id": 1, "permission_code": "a"}, {"id": 2, "permission_code": "b"}]
    resolved = resolve_effective(perms, {}, {}, is_full_access=True)
    assert all(info["allowed"] for info in resolved.values())
    assert all(info["source"] == "full_access" for info in resolved.values())


def test_password_hash_roundtrip_and_format():
    hasher = PasswordHasher(iterations=1000)
    stored = hasher.hash("secret")
    assert stored.startswith("pbkdf2_sha256$")
    assert stored.count("$") == 3
    assert hasher.verify("secret", stored) is True
    assert hasher.verify("wrong", stored) is False
    assert hasher.verify("secret", None) is False
    assert hasher.verify("secret", "garbage") is False


class _FakeSecurityRepo:
    """In-memory stand-in for SecurityRepository used by the sync test."""

    def __init__(self, existing_codes=None):
        self.perms = {}  # code -> row
        self.deactivated = []
        for code in existing_codes or []:
            self.perms[code] = {"permission_code": code, "is_active": True}

    def ensure_schema(self):
        pass

    def list_permissions(self, active_only=True):
        rows = list(self.perms.values())
        if active_only:
            rows = [r for r in rows if r.get("is_active", True)]
        return rows

    def upsert_permission(self, row):
        self.perms[row["permission_code"]] = {**row, "is_active": True}

    def deactivate_permissions_not_in(self, active_codes):
        active = set(active_codes)
        count = 0
        for code, row in self.perms.items():
            if code not in active and row.get("is_active", True):
                row["is_active"] = False
                self.deactivated.append(code)
                count += 1
        return count


def test_sync_inserts_new_keeps_existing_and_deactivates_removed():
    repo = _FakeSecurityRepo(existing_codes=["crm.contractors.view", "crm.customers.view",
                                             "crm.OLD.view"])
    summary = PermissionsSyncService(repo).sync()

    # The stale code not in the registry is deactivated, never deleted.
    assert "crm.OLD.view" in repo.deactivated
    assert "crm.OLD.view" in repo.perms
    assert repo.perms["crm.OLD.view"]["is_active"] is False

    # A registered target outside the matrix (2026-10-02) is deactivated too —
    # kept, so its old grants come back if it is ever shown again.
    assert repo.perms["crm.customers.view"]["is_active"] is False

    # Existing shown code stays; new codes were added.
    assert repo.perms["crm.contractors.view"]["is_active"] is True
    assert summary["added"] >= 1
    assert summary["total"] == len(build_permission_rows())
    assert summary["deactivated"] >= 1


class _RecordingDb:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((" ".join(query.split()), list(params or [])))


def test_reset_user_overrides_spares_overrides_on_inactive_permissions():
    """«تصفير» clears what the matrix shows, not the overrides on hidden targets.

    Hidden permissions are kept inactive so their grants come back if the
    screen is shown again (2026-10-02); wiping their overrides would break that.
    """
    from app.repositories.security_repository import SecurityRepository

    db = _RecordingDb()
    SecurityRepository(db).reset_user_overrides(7)
    (query, params), = db.calls
    assert query.startswith("DELETE FROM user_permissions WHERE user_id=%s")
    assert "permission_id IN (SELECT id FROM permissions WHERE is_active)" in query
    assert params == [7]
