from __future__ import annotations

from pathlib import Path

from app.config import pg_lan

CONF = "# comment\n#listen_addresses = 'localhost'\t# what IP\nport = 5432\n"
HBA = ("# TYPE DATABASE USER ADDRESS METHOD\n"
       "host    all    all    127.0.0.1/32    scram-sha-256\n"
       "host    all    all    ::1/128         scram-sha-256\n")
SERVICES = {"postgresql-x64-18":
            '"C:\\Program Files\\PostgreSQL\\18\\bin\\pg_ctl.exe" runservice -N '
            '"postgresql-x64-18" -D "C:\\Program Files\\PostgreSQL\\18\\data" -w'}


def test_listen_addresses_appended_when_only_commented():
    text, changed = pg_lan.set_listen_addresses(CONF)
    assert changed and text.rstrip().endswith("listen_addresses = '*'\t\t# set by A-H CODE setup")


def test_listen_addresses_replaces_last_active_line():
    text, changed = pg_lan.set_listen_addresses("listen_addresses = 'localhost'\nport = 5432\n")
    assert changed and text.splitlines()[0].startswith("listen_addresses = '*'")
    again, changed2 = pg_lan.set_listen_addresses(text)
    assert not changed2 and again == text


def test_samenet_rule_uses_local_method_and_is_added_once():
    text, changed = pg_lan.ensure_samenet_rule(HBA.replace("scram-sha-256", "md5"))
    assert changed and text.splitlines()[-1].split() == ["host", "all", "all", "samenet", "md5"]
    _, changed2 = pg_lan.ensure_samenet_rule(text)
    assert not changed2


def test_crlf_preserved():
    text, _ = pg_lan.ensure_samenet_rule(HBA.replace("\n", "\r\n"))
    assert "\n" not in text.replace("\r\n", "")
    conf, _ = pg_lan.set_listen_addresses(CONF.replace("\n", "\r\n"))
    assert conf.endswith("\r\n") and "\n" not in conf.replace("\r\n", "")


def test_find_service_by_data_dir():
    assert pg_lan.find_service(Path(r"c:\program files\postgresql\18\DATA"), SERVICES) == "postgresql-x64-18"
    assert pg_lan.find_service(Path(r"D:\other"), SERVICES) is None


def _setup(tmp_path):
    (tmp_path / "postgresql.conf").write_bytes(CONF.encode())
    (tmp_path / "pg_hba.conf").write_bytes(HBA.encode())
    return {"postgresql-x64-18": f'pg_ctl.exe runservice -N "postgresql-x64-18" -D "{tmp_path}" -w'}


def test_enable_lan_changes_backs_up_restarts_and_opens_firewall(tmp_path):
    services = _setup(tmp_path)
    calls = []

    def run(cmd):
        calls.append(cmd)
        return (1, "No rules match") if "show" in cmd else (0, "")

    result = pg_lan.enable_lan(tmp_path, 5432, services, run, stamp="20261015120000")
    assert result["ok"]
    assert (tmp_path / "postgresql.conf.ahcode-bak-20261015120000").read_bytes() == CONF.encode()
    assert (tmp_path / "pg_hba.conf.ahcode-bak-20261015120000").exists()
    assert any("Restart-Service" in " ".join(c) for c in calls)
    assert any("add" in c and "localport=5432" in c for c in calls)


def test_enable_lan_is_idempotent(tmp_path):
    services = _setup(tmp_path)
    pg_lan.enable_lan(tmp_path, 5432, services, lambda c: (1, "") if "show" in c else (0, ""), stamp="1")
    calls = []

    def run(cmd):
        calls.append(cmd)
        return (0, "Rule Name: A-H CODE PostgreSQL")

    result = pg_lan.enable_lan(tmp_path, 5432, services, run, stamp="2")
    assert result["ok"]
    assert not any("Restart-Service" in " ".join(c) for c in calls)
    assert not any("add" in c for c in calls)
    assert not (tmp_path / "postgresql.conf.ahcode-bak-2").exists()


def test_enable_lan_fails_cleanly_without_service(tmp_path):
    _setup(tmp_path)
    result = pg_lan.enable_lan(tmp_path, 5432, {}, lambda c: (0, ""), stamp="1")
    assert not result["ok"] and "service" in result["message"].lower()


def test_cli_enable_lan_with_data_dir(tmp_path, monkeypatch):
    import json

    from app.config import configure_cli

    services = _setup(tmp_path)
    monkeypatch.setattr(pg_lan, "list_pg_services", lambda: services)
    monkeypatch.setattr(pg_lan, "default_runner",
                        lambda cmd: (1, "") if "show" in cmd else (0, ""))
    out = tmp_path / "r.json"
    code = configure_cli.main(["--result-file", str(out), "enable-lan",
                               "--data-dir", str(tmp_path), "--port", "5432"])
    data = json.loads(out.read_text(encoding="utf-8-sig"))
    assert code == 0 and data["ok"], data
    assert "samenet" in (tmp_path / "pg_hba.conf").read_text()
