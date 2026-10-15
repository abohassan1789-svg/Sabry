"""Installer-facing CLI behaviour: result files, password files, missing DB."""

from __future__ import annotations

import json

from app.config import cli_output, configure_cli, dbcheck_cli
from app.services import network_service as net
from app.services.network_service import CheckResult


def _fake_db(existing: set[str], seen: list):
    def fake(host, port, db_name, user, password, sslmode="prefer", timeout=5.0):
        seen.append((db_name, password))
        if db_name in existing:
            return CheckResult(True, f"Connected to database '{db_name}'.")
        msg = f'connection failed: FATAL:  database "{db_name}" does not exist'
        return CheckResult(False, f"Database connection failed: {msg}", detail=msg)
    return fake


def test_allow_missing_db_falls_back_to_server(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(net, "test_database", _fake_db({"postgres"}, seen))
    result, missing = net.test_database_or_server("localhost", 5432, "SABCONTDB", "postgres", "pw")
    assert result.ok and missing
    assert [db for db, _ in seen] == ["SABCONTDB", "postgres"]


def test_wrong_password_is_not_treated_as_missing_db(monkeypatch):
    def fake(*a, **k):
        msg = 'FATAL:  password authentication failed for user "postgres"'
        return CheckResult(False, f"Database connection failed: {msg}", detail=msg)
    monkeypatch.setattr(net, "test_database", fake)
    result, missing = net.test_database_or_server("localhost", 5432, "SABCONTDB", "postgres", "bad")
    assert not result.ok and not missing


def test_result_file_is_utf8_with_bom(tmp_path):
    out = tmp_path / "r.json"
    cli_output.set_result_file(str(out))
    try:
        code = cli_output.emit({"ok": False, "message": "تعذّر الاتصال"}, ok=False)
    finally:
        cli_output.set_result_file(None)
    assert code == 1
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8-sig"))["message"] == "تعذّر الاتصال"


def test_password_file_with_bom_and_unicode(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(net, "test_database", _fake_db({"SABCONTDB"}, seen))
    pw = tmp_path / "pw.txt"
    pw.write_bytes("\ufeffكلمة سر 'x\"\r\n".encode("utf-8"))
    out = tmp_path / "r.json"
    code = configure_cli.main(["--result-file", str(out), "test-db", "--host", "localhost",
                               "--port", "5432", "--db", "SABCONTDB",
                               "--password-file", str(pw)])
    assert code == 0
    assert seen[0][1] == "كلمة سر 'x\""
    assert json.loads(out.read_text(encoding="utf-8-sig"))["db_missing"] is False


def test_configure_cli_test_db_allow_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "test_database", _fake_db({"postgres"}, []))
    out = tmp_path / "r.json"
    code = configure_cli.main(["--result-file", str(out), "test-db", "--host", "localhost",
                               "--port", "5432", "--db", "SABCONTDB", "--allow-missing-db"])
    data = json.loads(out.read_text(encoding="utf-8-sig"))
    assert code == 0 and data["ok"] and data["db_missing"]


def test_dbcheck_cli_matches_configure_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "test_database", _fake_db({"postgres"}, []))
    out = tmp_path / "r.json"
    code = dbcheck_cli.main(["--result-file", str(out), "--host", "localhost", "--port", "5432",
                             "--db", "SABCONTDB", "--user", "postgres", "--allow-missing-db"])
    data = json.loads(out.read_text(encoding="utf-8-sig"))
    assert code == 0 and data["db_missing"] is True
    code = dbcheck_cli.main(["--host", "localhost", "--port", "5432", "--db", "SABCONTDB"])
    assert code == 1
