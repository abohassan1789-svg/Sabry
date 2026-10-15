# A-H CODE Client Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `setup/Output/A-H_CODE_Setup.exe`, a brand-new self-contained Windows installer for the app, connecting to a user-installed PostgreSQL with database `SABCONTDB`, for local and LAN use.

**Architecture:** PyInstaller builds a one-folder app (`A-H CODE.exe` + hidden console helper `ahcode-config.exe`) plus a tiny one-file `ahcode-dbcheck.exe` used by the wizard before files are copied. A new Inno Setup 6 script collects the connection, tests it, and after copying runs the helper's sub-commands (`write`, `create-db`, `provision`, `set-backup-dir`, new `enable-lan`). All logic lives in tested Python; Pascal only gathers input and calls the tools.

**Tech Stack:** Python 3.11, PySide6, psycopg 3, PyInstaller 6.22, Inno Setup 6 (`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-ahcode-client-installer-design.md`

## Global Constraints

- Product name `A-H CODE`; output file `A-H_CODE_Setup.exe`; install dir `{autopf}\A-H CODE`.
- Wizard text in English; defaults Host `localhost`, Port `5432`, Database `SABCONTDB`, User `postgres`, Password empty.
- Machine data dir `C:\ProgramData\PHASEINV2` (existing `connection_config.BRAND_DIRNAME`); default backups `C:\ProgramData\PHASEINV2\Backups`.
- Never touch old `installer/`, `installer_final/`, `installer_new/`.
- Never put the DB password on a command line or in a log; use `--password-file` in `{tmp}`, deleted right after use.
- An existing database's data is never dropped, truncated or overwritten.
- Uninstall removes `{app}` and shortcuts only.
- Tests never touch `SABCONTDB` or the real `postgresql.conf` / `pg_hba.conf`.
- Python sources use LF; commit author `abo <abo.hassan1789@gmail.com>` via env vars.

## Review Focus

1. Password with a BOM, spaces, quotes or Arabic characters → reaches PostgreSQL unchanged (Task 1 test `test_password_file_with_bom_and_unicode`).
2. Main machine with no `SABCONTDB` yet → `Test Connection` passes ("will be created") instead of failing (Task 1 test `test_allow_missing_db_falls_back_to_server`).
3. Running `enable-lan` twice or on a server already set to `listen_addresses='*'` → no duplicate lines, no needless restart (Task 2 test `test_enable_lan_is_idempotent`).
4. `postgresql.conf` / `pg_hba.conf` with CRLF line endings → written back with CRLF (Task 2 test `test_crlf_preserved`).
5. App run by a normal (non-admin) user → never writes under `Program Files` (Task 3 test `test_prepare_routes_writable_files_to_programdata`).

---

### Task 1: CLI result file, BOM-safe password file, test-db that tolerates a missing database, tiny dbcheck CLI

**Files:**
- Create: `app/config/cli_output.py`
- Create: `app/config/dbcheck_cli.py`
- Modify: `app/services/network_service.py` (add `test_database_or_server`)
- Modify: `app/config/configure_cli.py` (`_emit`, `_resolve_password`, `test-db` flags, `--result-file`)
- Test: `tests/unit/test_installer_cli.py`

**Interfaces:**
- Produces: `cli_output.emit(obj: dict, ok: bool) -> int`, `cli_output.set_result_file(path: str | None) -> None`;
  `network_service.test_database_or_server(host, port, db_name, user, password, sslmode="prefer", maintenance_db="postgres") -> tuple[CheckResult, bool]` (bool = database missing);
  `dbcheck_cli.main(argv: list[str] | None) -> int`;
  `configure_cli` global option `--result-file PATH` (before the sub-command) and `test-db --allow-missing-db`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_installer_cli.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_installer_cli.py -q`
Expected: FAIL — `ImportError: cannot import name 'cli_output'`.

- [ ] **Step 3: Implement**

```python
# app/config/cli_output.py
"""Shared JSON output for the installer-facing command-line tools.

Every tool prints one JSON object and returns 0 (ok) / 1 (failure). When the
installer passes ``--result-file`` the same JSON is also written there as UTF-8
with a BOM, which Inno Setup's ``LoadStringsFromFile`` decodes correctly (the
console code page would garble Arabic messages).
"""

from __future__ import annotations

import json
from pathlib import Path

_result_file: str | None = None


def set_result_file(path: str | None) -> None:
    global _result_file
    _result_file = path or None


def emit(obj: dict, ok: bool) -> int:
    text = json.dumps(obj, ensure_ascii=False)
    try:
        print(text)
    except UnicodeEncodeError:
        print(json.dumps(obj, ensure_ascii=True))
    if _result_file:
        Path(_result_file).write_text(text, encoding="utf-8-sig")
    return 0 if ok else 1
```

Append to `app/services/network_service.py`:

```python
def _is_missing_database(text: str) -> bool:
    lowered = (text or "").lower()
    return "database" in lowered and "does not exist" in lowered


def test_database_or_server(
    host: str,
    port: int,
    db_name: str,
    user: str,
    password: str,
    sslmode: str = "prefer",
    maintenance_db: str = "postgres",
) -> tuple[CheckResult, bool]:
    """Test ``db_name``; if only the database is missing, test the server instead.

    Returns ``(result, db_missing)``. Used on the main machine, where the
    installer creates the database after the test, so a reachable server with
    valid credentials is a pass.
    """
    result = test_database(host, port, db_name, user, password, sslmode=sslmode)
    if result.ok or not _is_missing_database(result.detail or result.message):
        return result, False
    server = test_database(host, port, maintenance_db, user, password, sslmode=sslmode)
    if server.ok:
        return CheckResult(
            True,
            f"Server {host}:{port} reachable; database '{db_name}' will be created.",
        ), True
    return server, True
```

```python
# app/config/dbcheck_cli.py
"""Tiny connection checker the installer runs BEFORE copying the program.

Frozen into the one-file ``ahcode-dbcheck.exe``; it must import only the
standard library, psycopg and ``app.services.network_service``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import cli_output
from app.services import network_service as net


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ahcode-dbcheck")
    p.add_argument("--result-file", dest="result_file", default="")
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--user", default="postgres")
    p.add_argument("--password-file", dest="password_file", default="")
    p.add_argument("--sslmode", default="prefer")
    p.add_argument("--allow-missing-db", dest="allow_missing_db", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cli_output.set_result_file(args.result_file)
    password = ""
    if args.password_file:
        try:
            password = Path(args.password_file).read_text(encoding="utf-8-sig").rstrip("\r\n")
        except OSError:
            password = ""
    try:
        if args.allow_missing_db:
            result, missing = net.test_database_or_server(
                args.host, args.port, args.db, args.user, password, sslmode=args.sslmode)
        else:
            result, missing = net.test_database(
                args.host, args.port, args.db, args.user, password, sslmode=args.sslmode), False
        message = result.message.replace(password, "******") if password else result.message
        return cli_output.emit({"ok": result.ok, "db_missing": missing, "message": message},
                               ok=result.ok)
    except Exception as exc:  # noqa: BLE001 - never show a traceback in the wizard
        return cli_output.emit({"ok": False, "db_missing": False,
                                "message": f"{type(exc).__name__}: {exc}"}, ok=False)


if __name__ == "__main__":
    sys.exit(main())
```

In `app/config/configure_cli.py`:

1. Replace `_emit` body with `return cli_output.emit(obj, ok)` and add `from app.config import cli_output` to the imports.
2. In `_resolve_password` change `read_text(encoding="utf-8")` to `read_text(encoding="utf-8-sig")`.
3. Replace `_cmd_test_db` with:

```python
def _cmd_test_db(args) -> int:
    password = _resolve_password(args)
    if getattr(args, "allow_missing_db", False):
        result, missing = net.test_database_or_server(
            args.host, args.port, args.db, args.user, password, sslmode=args.sslmode)
    else:
        result = net.test_database(
            host=args.host, port=args.port, db_name=args.db,
            user=args.user, password=password, sslmode=args.sslmode,
        )
        missing = False
    return _emit({"ok": result.ok, "db_missing": missing,
                  "message": _scrub(result.message, password),
                  "detail": _scrub(result.detail, password)}, result.ok)
```

4. In `build_parser()`, right after creating `parser`, add
   `parser.add_argument("--result-file", dest="result_file", default="")`; on `p_db` add
   `p_db.add_argument("--allow-missing-db", dest="allow_missing_db", action="store_true")`.
5. In `main()`, after `args = build_parser().parse_args(argv)`, add `cli_output.set_result_file(args.result_file)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_installer_cli.py tests/test_connection_config.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/config/cli_output.py app/config/dbcheck_cli.py app/config/configure_cli.py app/services/network_service.py tests/unit/test_installer_cli.py
git commit -m "Installer CLI: result file, BOM-safe password file, test-db tolerates a missing DB"
```

---

### Task 2: `enable-lan` — open PostgreSQL to the local network

**Files:**
- Create: `app/config/pg_lan.py`
- Modify: `app/config/configure_cli.py` (new `enable-lan` sub-command)
- Test: `tests/unit/test_pg_lan.py`

**Interfaces:**
- Consumes: `cli_output.emit`, `configure_cli._resolve_password` (Task 1).
- Produces: `pg_lan.set_listen_addresses(text) -> tuple[str, bool]`, `pg_lan.ensure_samenet_rule(text) -> tuple[str, bool]`,
  `pg_lan.find_service(data_dir, services: dict[str, str]) -> str | None`,
  `pg_lan.enable_lan(data_dir: Path, port: int, services: dict[str, str], run: Callable[[list[str]], tuple[int, str]], stamp: str) -> dict`,
  CLI `configure_cli enable-lan --host --port --user --password-file [--data-dir]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_pg_lan.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_pg_lan.py -q`
Expected: FAIL — `ImportError: cannot import name 'pg_lan'`.

- [ ] **Step 3: Implement `app/config/pg_lan.py`**

```python
"""Open the main machine's PostgreSQL to computers on the same network.

Used only by the installer (elevated) when the administrator ticks "This is the
MAIN machine". Every step is idempotent: re-running changes nothing, writes no
new backup and restarts nothing. The original files are copied to
``<name>.ahcode-bak-<stamp>`` before the first change.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable

FIREWALL_RULE_NAME = "A-H CODE PostgreSQL"
_MARK = "\t\t# set by A-H CODE setup"
_LISTEN = re.compile(r"^\s*listen_addresses\s*=\s*'([^']*)'")
_DATA_DIR = re.compile(r'-D\s+"([^"]+)"|-D\s+(\S+)')

Runner = Callable[[list[str]], "tuple[int, str]"]


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _append(text: str, line: str) -> str:
    nl = _newline(text)
    if text and not text.endswith(("\n", "\r")):
        text += nl
    return text + line + nl


def set_listen_addresses(conf_text: str) -> tuple[str, bool]:
    lines = conf_text.splitlines(keepends=True)
    active = [i for i, line in enumerate(lines) if _LISTEN.match(line)]
    if not active:
        return _append(conf_text, "listen_addresses = '*'" + _MARK), True
    last = active[-1]  # PostgreSQL honours the last setting
    if _LISTEN.match(lines[last]).group(1).strip() == "*":
        return conf_text, False
    ending = "\r\n" if lines[last].endswith("\r\n") else ("\n" if lines[last].endswith("\n") else "")
    lines[last] = "listen_addresses = '*'" + _MARK + ending
    return "".join(lines), True


def _fields(line: str) -> list[str]:
    return line.split("#", 1)[0].split()


def _local_method(hba_text: str) -> str:
    for line in hba_text.splitlines():
        f = _fields(line)
        if len(f) >= 5 and f[0] == "host" and f[3] == "127.0.0.1/32":
            return f[4]
    return "scram-sha-256"


def ensure_samenet_rule(hba_text: str) -> tuple[str, bool]:
    for line in hba_text.splitlines():
        f = _fields(line)
        if len(f) >= 5 and f[0] in ("host", "hostssl") and f[1:4] == ["all", "all", "samenet"]:
            return hba_text, False
    nl = _newline(hba_text)
    rule = f"host    all    all    samenet    {_local_method(hba_text)}"
    text = _append(hba_text, "# A-H CODE: computers on the same network")
    return text + rule + nl, True


def parse_data_dir(image_path: str) -> str | None:
    m = _DATA_DIR.search(image_path or "")
    return (m.group(1) or m.group(2)) if m else None


def find_service(data_dir: Path, services: dict[str, str]) -> str | None:
    target = os.path.normcase(os.path.normpath(str(data_dir)))
    for name, image in services.items():
        found = parse_data_dir(image)
        if found and os.path.normcase(os.path.normpath(found)) == target:
            return name
    return None


def list_pg_services() -> dict[str, str]:
    """``{service name: ImagePath}`` for every PostgreSQL Windows service."""
    import winreg

    services: dict[str, str] = {}
    root = r"SYSTEM\CurrentControlSet\Services"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as key:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(key, index)
            except OSError:
                break
            index += 1
            if not name.lower().startswith("postgresql"):
                continue
            try:
                with winreg.OpenKey(key, name) as sub:
                    services[name] = str(winreg.QueryValueEx(sub, "ImagePath")[0])
            except OSError:
                continue
    return services


def default_runner(cmd: list[str]) -> tuple[int, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _rewrite(path: Path, edit: Callable[[str], "tuple[str, bool]"], stamp: str) -> bool:
    original = path.read_bytes().decode("utf-8", "surrogateescape")
    updated, changed = edit(original)
    if changed:
        backup = path.with_name(f"{path.name}.ahcode-bak-{stamp}")
        backup.write_bytes(original.encode("utf-8", "surrogateescape"))
        path.write_bytes(updated.encode("utf-8", "surrogateescape"))
    return changed


def enable_lan(data_dir: Path, port: int, services: dict[str, str], run: Runner,
               stamp: str) -> dict:
    data_dir = Path(data_dir)
    conf, hba = data_dir / "postgresql.conf", data_dir / "pg_hba.conf"
    if not conf.exists() or not hba.exists():
        return {"ok": False, "message": f"PostgreSQL config files not found in {data_dir}. "
                "Run this option on the MAIN machine."}
    service = find_service(data_dir, services)
    if service is None:
        return {"ok": False, "message": f"No PostgreSQL Windows service uses {data_dir}."}
    steps = []
    conf_changed = _rewrite(conf, set_listen_addresses, stamp)
    steps.append("listen_addresses set to '*'" if conf_changed else "listen_addresses already '*'")
    hba_changed = _rewrite(hba, ensure_samenet_rule, stamp)
    steps.append("samenet rule added" if hba_changed else "samenet rule already present")
    if conf_changed or hba_changed:
        code, out = run(["powershell", "-NoProfile", "-Command",
                         f"Restart-Service -Name '{service}' -Force"])
        if code != 0:
            return {"ok": False, "steps": steps,
                    "message": f"Could not restart service {service}: {out.strip()}"}
        steps.append(f"service {service} restarted")
    show = ["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE_NAME}"]
    code, _ = run(show)
    if code != 0:
        code, out = run(["netsh", "advfirewall", "firewall", "add", "rule",
                         f"name={FIREWALL_RULE_NAME}", "dir=in", "action=allow",
                         "protocol=TCP", f"localport={int(port)}"])
        if code != 0:
            return {"ok": False, "steps": steps,
                    "message": f"Could not add the firewall rule: {out.strip()}"}
        steps.append(f"firewall rule added for TCP {port}")
    else:
        steps.append("firewall rule already present")
    return {"ok": True, "steps": steps, "message": "PostgreSQL accepts network connections."}
```


- [ ] **Step 4: Add the CLI sub-command** in `app/config/configure_cli.py`:

```python
def _cmd_enable_lan(args) -> int:
    from datetime import datetime

    from app.config import pg_lan

    data_dir = args.data_dir
    if not data_dir:
        import psycopg

        password = _resolve_password(args)
        try:
            with psycopg.connect(host=args.host, port=args.port, dbname="postgres",
                                 user=args.user, password=password, connect_timeout=10) as conn:
                data_dir = conn.execute("SHOW data_directory").fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            return _emit({"ok": False, "message": _scrub(f"{type(exc).__name__}: {exc}",
                                                         password)}, ok=False)
    result = pg_lan.enable_lan(Path(data_dir), args.port, pg_lan.list_pg_services(),
                               pg_lan.default_runner, datetime.now().strftime("%Y%m%d%H%M%S"))
    return _emit(result, ok=bool(result.get("ok")))
```

Parser (inside `build_parser`):

```python
    p_lan = sub.add_parser("enable-lan", help="Let computers on the same network connect")
    p_lan.add_argument("--host", default="localhost")
    p_lan.add_argument("--port", type=int, default=cc.DEFAULT_PORT)
    p_lan.add_argument("--user", default="postgres")
    p_lan.add_argument("--password", default="")
    p_lan.add_argument("--password-file", dest="password_file", default="")
    p_lan.add_argument("--data-dir", dest="data_dir", default="")
```

and `"enable-lan": _cmd_enable_lan,` in `_COMMANDS`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/unit/test_pg_lan.py tests/unit/test_installer_cli.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/config/pg_lan.py app/config/configure_cli.py tests/unit/test_pg_lan.py
git commit -m "Installer: enable-lan opens PostgreSQL to the local network (idempotent)"
```

---

### Task 3: Frozen runtime preparation, import smoke check, window title

**Files:**
- Create: `app/config/frozen_runtime.py`
- Modify: `app/ui/main_window.py:337` (`"KSA"` → `"A-H CODE"`)
- Test: `tests/unit/test_frozen_runtime.py`

**Interfaces:**
- Produces: `frozen_runtime.prepare(environ: MutableMapping[str, str] | None = None, program_data: str | None = None, chdir: bool = True) -> Path`;
  `frozen_runtime.smoke_import(packages: Iterable[str], out_path: str) -> int` (0 = all imported).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_frozen_runtime.py
from __future__ import annotations

import os

from app.config import frozen_runtime


def test_prepare_routes_writable_files_to_programdata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env: dict[str, str] = {}
    base = frozen_runtime.prepare(env, program_data=str(tmp_path / "PD"))
    assert base == tmp_path / "PD" / "PHASEINV2"
    assert base.is_dir()
    assert env["BACKUP_SETTINGS_PATH"] == str(base / "backup_settings.json")
    assert os.getcwd() == str(base)


def test_prepare_keeps_explicit_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = {"BACKUP_SETTINGS_PATH": "X:/mine.json"}
    frozen_runtime.prepare(env, program_data=str(tmp_path), chdir=False)
    assert env["BACKUP_SETTINGS_PATH"] == "X:/mine.json"
    assert os.getcwd() == str(tmp_path)


def test_smoke_import_reports_ok(tmp_path):
    out = tmp_path / "smoke.txt"
    assert frozen_runtime.smoke_import(["app.config"], str(out)) == 0
    text = out.read_text(encoding="utf-8")
    assert "OK app.config.connection_config" in text and "FAILED" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_frozen_runtime.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# app/config/frozen_runtime.py
"""Process setup for the installed (PyInstaller) build.

Installed code lives under ``Program Files``, which normal users cannot write
to. ``prepare`` points every file the app writes next to its code at the
machine data folder ``%ProgramData%\\PHASEINV2`` instead (the installer grants
Users modify rights there). Explicit environment overrides always win.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import traceback
from pathlib import Path
from typing import Iterable, MutableMapping

from app.config.connection_config import BRAND_DIRNAME


def prepare(environ: MutableMapping[str, str] | None = None,
            program_data: str | None = None, chdir: bool = True) -> Path:
    env = os.environ if environ is None else environ
    root = program_data or env.get("ProgramData") or os.environ.get("ProgramData") \
        or str(Path.home())
    base = Path(root) / BRAND_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    env.setdefault("BACKUP_SETTINGS_PATH", str(base / "backup_settings.json"))
    if chdir:
        # Settings files opened by a relative name (e.g. the daily follow-up
        # report settings) land in the data folder, not the install folder.
        os.chdir(base)
    return base


def smoke_import(packages: Iterable[str], out_path: str) -> int:
    """Import every module of ``packages``; write one OK/FAILED line each."""
    lines: list[str] = []
    failed = 0
    for package in packages:
        names = [package]
        pkg = importlib.import_module(package)
        if hasattr(pkg, "__path__"):
            names += [m.name for m in pkgutil.walk_packages(pkg.__path__, package + ".")]
        for name in names:
            try:
                importlib.import_module(name)
                lines.append(f"OK {name}")
            except Exception:  # noqa: BLE001
                failed += 1
                lines.append(f"FAILED {name}\n{traceback.format_exc()}")
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0
```

In `app/ui/main_window.py` line 337: `self.setWindowTitle("A-H CODE")`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_frozen_runtime.py -q`
Expected: PASS. Also run `python -m pytest tests/unit/test_permission_ui_parity.py -q` (touches main window) — PASS.

- [ ] **Step 5: Commit**

```bash
git add app/config/frozen_runtime.py app/ui/main_window.py tests/unit/test_frozen_runtime.py
git commit -m "Installed build: writable files go to ProgramData; window title A-H CODE"
```

---

### Task 4: PyInstaller build (`setup/`)

**Files:**
- Create: `setup/entry_app.py`, `setup/entry_config.py`, `setup/entry_dbcheck.py`
- Create: `setup/ahcode.spec`, `setup/dbcheck.spec`
- Create: `setup/make_icon.py` → generates `setup/ahcode.ico` (committed)
- Create: `setup/build.ps1` (PyInstaller part; Inno part added in Task 5)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `frozen_runtime.prepare`, `frozen_runtime.smoke_import`, `configure_cli.main`, `dbcheck_cli.main`.
- Produces: `setup/dist/A-H CODE/A-H CODE.exe`, `setup/dist/A-H CODE/ahcode-config.exe`, `setup/dist/ahcode-dbcheck.exe`.
  `A-H CODE.exe --smoke-imports <file>` runs the import check and exits.

- [ ] **Step 1: Entry scripts**

```python
# setup/entry_app.py
"""A-H CODE.exe — the installed application."""
import sys

from app.config.frozen_runtime import prepare, smoke_import

if __name__ == "__main__":
    prepare()
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-imports":
        sys.exit(smoke_import(["app.config", "app.database", "app.models", "app.repositories",
                               "app.services", "app.reports", "app.security", "app.ui"],
                              sys.argv[2]))
    from app.main import main

    main()
```

```python
# setup/entry_config.py
"""ahcode-config.exe — the installer's configuration helper (console, run hidden)."""
import sys

from app.config.frozen_runtime import prepare

if __name__ == "__main__":
    prepare(chdir=False)
    from app.config.configure_cli import main

    sys.exit(main())
```

```python
# setup/entry_dbcheck.py
"""ahcode-dbcheck.exe — connection test run by the wizard before files are copied."""
import sys

from app.config.dbcheck_cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Icon generator** — run once, commit the `.ico`.

```python
# setup/make_icon.py
"""Build setup/ahcode.ico from assets/report_logo.jpg (white square padding)."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
logo = Image.open(ROOT / "assets" / "report_logo.jpg").convert("RGBA")
side = max(logo.size)
square = Image.new("RGBA", (side, side), (255, 255, 255, 255))
square.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2))
square.save(ROOT / "setup" / "ahcode.ico",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
```

Run: `python setup/make_icon.py` — then Read `setup/ahcode.ico` is not viewable; instead save a PNG preview to the scratchpad and look at it to confirm the logo is recognisable at 48 px.

- [ ] **Step 3: Spec files**

```python
# setup/ahcode.spec  -- one-folder app + config helper sharing _internal
# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ICON = str(Path(SPECPATH) / "ahcode.ico")

hidden = (collect_submodules("app", filter=lambda n: not n.startswith("app.migrations"))
          + collect_submodules("num2words") + ["psycopg_binary"])

datas = []
for folder, _dirs, files in os.walk(ROOT / "app"):
    if "__pycache__" in folder or ".tmp_access_export" in folder:
        continue
    for name in files:
        if name.endswith((".py", ".pyc")):
            continue
        src = Path(folder) / name
        datas.append((str(src), str(src.parent.relative_to(ROOT))))
datas.append((str(ROOT / "assets" / "report_logo.jpg"), "assets"))
datas += collect_data_files("qtawesome") + collect_data_files("arabic_reshaper")

common = dict(pathex=[str(ROOT)], hiddenimports=hidden, datas=datas,
              excludes=["pytest", "tkinter"])
a_app = Analysis([str(Path(SPECPATH) / "entry_app.py")], **common)
a_cfg = Analysis([str(Path(SPECPATH) / "entry_config.py")], **common)

exe_app = EXE(PYZ(a_app.pure), a_app.scripts, [], exclude_binaries=True,
              name="A-H CODE", console=False, icon=ICON, upx=False)
exe_cfg = EXE(PYZ(a_cfg.pure), a_cfg.scripts, [], exclude_binaries=True,
              name="ahcode-config", console=True, icon=ICON, upx=False)
coll = COLLECT(exe_app, a_app.binaries, a_app.datas,
               exe_cfg, a_cfg.binaries, a_cfg.datas,
               upx=False, name="A-H CODE")
```

```python
# setup/dbcheck.spec  -- tiny one-file checker used before installation
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).parent
a = Analysis([str(Path(SPECPATH) / "entry_dbcheck.py")], pathex=[str(ROOT)],
             hiddenimports=["psycopg_binary"],
             excludes=["PySide6", "sqlalchemy", "reportlab", "openpyxl", "PIL",
                       "cryptography", "pytest", "tkinter"])
exe = EXE(PYZ(a.pure), a.scripts, a.binaries, a.datas, [], name="ahcode-dbcheck",
          console=True, upx=False, icon=str(Path(SPECPATH) / "ahcode.ico"))
```

- [ ] **Step 4: `setup/build.ps1` (build part)**

```powershell
# Builds the A-H CODE installer from the current working tree.
#   powershell -NoProfile -ExecutionPolicy Bypass -File setup\build.ps1
$ErrorActionPreference = "Stop"
$Setup = $PSScriptRoot
$Root  = Split-Path $Setup -Parent
Set-Location $Root

function Step($name, [scriptblock]$body) {
    Write-Host "==> $name" -ForegroundColor Cyan
    & $body
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

$Venv = Join-Path $Setup ".venv"
$Py   = Join-Path $Venv "Scripts\python.exe"
Step "Create clean venv" {
    if (Test-Path $Venv) { Remove-Item $Venv -Recurse -Force }
    py -3.11 -m venv $Venv
}
Step "Install libraries" {
    $req = Get-Content (Join-Path $Root "requirements.txt") | Where-Object { $_ -notmatch '^\s*pytest' }
    $tmpReq = Join-Path $env:TEMP "ahcode-req.txt"
    Set-Content -Path $tmpReq -Value $req -Encoding ascii
    & $Py -m pip install --upgrade pip
    & $Py -m pip install -r $tmpReq "pyinstaller==6.22.2"
}
Step "PyInstaller: app" {
    & $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Setup "dist") `
        --workpath (Join-Path $Setup "build") (Join-Path $Setup "ahcode.spec")
}
Step "PyInstaller: dbcheck" {
    & $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Setup "dist") `
        --workpath (Join-Path $Setup "build") (Join-Path $Setup "dbcheck.spec")
}
$Dist = Join-Path $Setup "dist\A-H CODE"
Step "Smoke: every module imports in the frozen app" {
    $out = Join-Path $Setup "build\smoke-imports.txt"
    $env:QT_QPA_PLATFORM = "offscreen"
    $p = Start-Process -FilePath (Join-Path $Dist "A-H CODE.exe") -ArgumentList "--smoke-imports", "`"$out`"" -Wait -PassThru
    Remove-Item Env:QT_QPA_PLATFORM
    if ($p.ExitCode -ne 0) { Get-Content $out | Select-String -Context 0,8 FAILED; throw "Frozen import smoke failed" }
}
Step "Smoke: helpers start" {
    & (Join-Path $Dist "ahcode-config.exe") --help | Out-Null
    & (Join-Path $Setup "dist\ahcode-dbcheck.exe") --help | Out-Null
}
```

- [ ] **Step 5: `.gitignore`** — append:

```
setup/.venv/
setup/build/
setup/dist/
setup/Output/
!setup/ahcode.spec
!setup/dbcheck.spec
```

- [ ] **Step 6: Build and verify**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File setup\build.ps1` (background; ~10–20 min).
Expected: all steps succeed; `setup/build/smoke-imports.txt` has no `FAILED`. Then run
`setup/dist/ahcode-dbcheck.exe --host localhost --port 5432 --db AHCODE_NOPE --allow-missing-db --password-file <tmp file with the local test password>` → JSON with `"db_missing": true`. If a module fails in the frozen smoke, add the missing hidden import / data file to `ahcode.spec` and rebuild.

- [ ] **Step 7: Commit**

```bash
git add .gitignore setup/entry_app.py setup/entry_config.py setup/entry_dbcheck.py setup/make_icon.py setup/ahcode.ico setup/build.ps1
git add -f setup/ahcode.spec setup/dbcheck.spec
git commit -m "Setup: PyInstaller build for A-H CODE (app, config helper, dbcheck)"
```

---

### Task 5: Inno Setup script

**Files:**
- Create: `setup/AHCODE_Setup.iss`
- Modify: `setup/build.ps1` (append the ISCC step)

**Interfaces:**
- Consumes: `setup/dist/A-H CODE/*`, `setup/dist/ahcode-dbcheck.exe`, `setup/ahcode.ico`; CLI contracts from Tasks 1–2 (`--result-file` first, then sub-command; JSON keys `ok`, `message`, `db_missing`).
- Produces: `setup/Output/A-H_CODE_Setup.exe`. Silent-install parameters for tests: `/DBHOST= /DBPORT= /DBNAME= /DBUSER= /DBPASSFILE= /BACKUPDIR= /LAN=0|1`.

- [ ] **Step 1: Write `setup/AHCODE_Setup.iss`**

```pascal
; A-H CODE — client installer (new; independent of installer/, installer_final/, installer_new/)
#define AppName "A-H CODE"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "A-H CODE.exe"
#define CfgExe "ahcode-config.exe"

[Setup]
AppId={{B533D238-22C1-432E-B2B9-C7B6B74ED57A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=A-H_CODE_Setup
SetupIconFile=ahcode.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
WizardSizePercent=110
SetupLogging=yes
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
Name: "{commonappdata}\PHASEINV2"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\PHASEINV2\logs"; Permissions: users-modify; Flags: uninsneveruninstall

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\A-H CODE\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\ahcode-dbcheck.exe"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DbPage: TInputQueryWizardPage;
  LanPage: TInputOptionWizardPage;
  BackupPage: TInputDirWizardPage;
  TestButton: TNewButton;
  TestStatus: TNewStaticText;
  TestedKey: String;
  DbMissing: Boolean;
  LogFile: String;

procedure Log2(const Line: String);
var Lines: TArrayOfString;
begin
  SetArrayLength(Lines, 1);
  Lines[0] := GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + '  ' + Line;
  SaveStringsToUTF8File(LogFile, Lines, True);
  Log(Line);
end;

function IsLocalHost(const Host: String): Boolean;
var H: String;
begin
  H := Lowercase(Trim(Host));
  Result := (H = 'localhost') or (H = '127.0.0.1') or (H = '::1') or (H = '.');
end;

function DbHost(): String; begin Result := Trim(DbPage.Values[0]); end;
function DbPort(): String; begin Result := Trim(DbPage.Values[1]); end;
function DbName(): String; begin Result := Trim(DbPage.Values[2]); end;
function DbUser(): String; begin Result := Trim(DbPage.Values[3]); end;

function CurrentKey(): String;
begin
  Result := DbHost() + '|' + DbPort() + '|' + DbName() + '|' + DbUser() + '|' + DbPage.Values[4];
end;

function JsonString(const Json, Key: String): String;
var P, I: Integer; C: Char; Esc: Boolean;
begin
  Result := '';
  P := Pos('"' + Key + '": "', Json);
  if P = 0 then Exit;
  I := P + Length(Key) + 5;
  Esc := False;
  while I <= Length(Json) do
  begin
    C := Json[I];
    if Esc then
    begin
      if C = 'n' then Result := Result + #13#10
      else if C = 't' then Result := Result + ' '
      else Result := Result + C;
      Esc := False;
    end
    else if C = '\' then Esc := True
    else if C = '"' then Exit
    else Result := Result + C;
    I := I + 1;
  end;
end;

function WritePasswordFile(): String;
var Lines: TArrayOfString;
begin
  Result := ExpandConstant('{tmp}\dbpass.txt');
  SetArrayLength(Lines, 1);
  Lines[0] := DbPage.Values[4];
  SaveStringsToUTF8File(Result, Lines, False);
end;

function ConnArgs(const PassFile: String): String;
begin
  Result := Format('--host "%s" --port %s --user "%s" --password-file "%s"',
                   [DbHost(), DbPort(), DbUser(), PassFile]);
end;

{ Runs a tool with --result-file first; returns True on exit code 0. }
function RunTool(const Exe, Params, Title: String; var Msg, Output: String): Boolean;
var ResFile: String; Lines: TArrayOfString; Code, I: Integer;
begin
  ResFile := ExpandConstant('{tmp}\result.json');
  DeleteFile(ResFile);
  Msg := '';
  Output := '';
  if not Exec(Exe, '--result-file "' + ResFile + '" ' + Params, '', SW_HIDE,
              ewWaitUntilTerminated, Code) then
  begin
    Msg := 'Could not start ' + ExtractFileName(Exe) + ': ' + SysErrorMessage(Code);
    Log2(Title + ': ' + Msg);
    Result := False;
    Exit;
  end;
  if LoadStringsFromFile(ResFile, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      Output := Output + Lines[I];
  Msg := JsonString(Output, 'message');
  if Msg = '' then Msg := 'No details (exit code ' + IntToStr(Code) + ').';
  Result := (Code = 0);
  if Result then Log2(Title + ': OK - ' + Output) else Log2(Title + ': FAILED - ' + Output);
end;

function ValidPort(): Boolean;
var P: Integer;
begin
  P := StrToIntDef(DbPort(), 0);
  Result := (P >= 1) and (P <= 65535);
end;

function TestConnection(): Boolean;
var Msg, Output, PassFile, Extra: String;
begin
  Result := False;
  if (DbHost() = '') or (DbName() = '') or (DbUser() = '') or not ValidPort() then
  begin
    SuppressibleMsgBox('Please fill in Host, a Port between 1 and 65535, Database Name and User.',
                       mbError, MB_OK, IDOK);
    Exit;
  end;
  TestStatus.Caption := 'Testing the connection...';
  TestStatus.Font.Color := clGray;
  WizardForm.Repaint;
  ExtractTemporaryFile('ahcode-dbcheck.exe');
  PassFile := WritePasswordFile();
  Extra := '';
  if IsLocalHost(DbHost()) then Extra := ' --allow-missing-db';
  Result := RunTool(ExpandConstant('{tmp}\ahcode-dbcheck.exe'),
                    ConnArgs(PassFile) + ' --db "' + DbName() + '"' + Extra,
                    'Test connection', Msg, Output);
  DeleteFile(PassFile);
  if Result then
  begin
    TestedKey := CurrentKey();
    DbMissing := Pos('"db_missing": true', Output) > 0;
    TestStatus.Font.Color := clGreen;
    if DbMissing then
      TestStatus.Caption := 'Connected. Database "' + DbName() + '" will be created.'
    else
      TestStatus.Caption := 'Connected to "' + DbName() + '".';
  end
  else
  begin
    TestedKey := '';
    TestStatus.Font.Color := clRed;
    TestStatus.Caption := 'Connection failed.';
    SuppressibleMsgBox('Could not connect to PostgreSQL:' + #13#10#13#10 + Msg, mbError, MB_OK, IDOK);
  end;
end;

procedure TestButtonClick(Sender: TObject);
begin
  TestConnection();
end;

procedure DbFieldChange(Sender: TObject);
begin
  if CurrentKey() <> TestedKey then
  begin
    TestStatus.Caption := '';
  end;
end;

procedure InitializeWizard();
var I: Integer; PassFile: String; Lines: TArrayOfString;
begin
  LogFile := ExpandConstant('{commonappdata}\PHASEINV2\logs\install-') +
             GetDateTimeString('yyyymmdd-hhnnss', '-', '-') + '.log';
  ForceDirectories(ExtractFileDir(LogFile));

  DbPage := CreateInputQueryPage(wpSelectDir, 'Database Connection',
    'PostgreSQL connection used by the application',
    'For the MAIN machine keep Host = localhost.' + #13#10 +
    'For a NETWORK client, enter the main machine''s IP address as the Host.' + #13#10 +
    'These values are saved to C:\ProgramData\PHASEINV2\connection.json and can be edited later.');
  DbPage.Add('Server IP / Host:', False);
  DbPage.Add('Port:', False);
  DbPage.Add('Database Name:', False);
  DbPage.Add('User:', False);
  DbPage.Add('Password:', True);
  DbPage.Values[0] := GetPreviousData('DbHost', ExpandConstant('{param:DBHOST|localhost}'));
  DbPage.Values[1] := GetPreviousData('DbPort', ExpandConstant('{param:DBPORT|5432}'));
  DbPage.Values[2] := GetPreviousData('DbName', ExpandConstant('{param:DBNAME|SABCONTDB}'));
  DbPage.Values[3] := GetPreviousData('DbUser', ExpandConstant('{param:DBUSER|postgres}'));
  PassFile := ExpandConstant('{param:DBPASSFILE|}');
  if (PassFile <> '') and LoadStringsFromFile(PassFile, Lines) and (GetArrayLength(Lines) > 0) then
    DbPage.Values[4] := Lines[0];
  if WizardSilent() then
  begin
    DbPage.Values[0] := ExpandConstant('{param:DBHOST|' + DbPage.Values[0] + '}');
    DbPage.Values[1] := ExpandConstant('{param:DBPORT|' + DbPage.Values[1] + '}');
    DbPage.Values[2] := ExpandConstant('{param:DBNAME|' + DbPage.Values[2] + '}');
    DbPage.Values[3] := ExpandConstant('{param:DBUSER|' + DbPage.Values[3] + '}');
  end;
  for I := 0 to 4 do
    DbPage.Edits[I].OnChange := @DbFieldChange;

  TestButton := TNewButton.Create(DbPage);
  TestButton.Parent := DbPage.Surface;
  TestButton.Caption := 'Test Connection';
  TestButton.Width := ScaleX(130);
  TestButton.Height := ScaleY(25);
  TestButton.Left := DbPage.Edits[4].Left;
  TestButton.Top := DbPage.Edits[4].Top + DbPage.Edits[4].Height + ScaleY(10);
  TestButton.OnClick := @TestButtonClick;

  TestStatus := TNewStaticText.Create(DbPage);
  TestStatus.Parent := DbPage.Surface;
  TestStatus.Left := TestButton.Left + TestButton.Width + ScaleX(12);
  TestStatus.Top := TestButton.Top + ScaleY(5);
  TestStatus.Caption := '';

  LanPage := CreateInputOptionPage(DbPage.ID, 'Network',
    'Use this computer as the main machine for the network',
    'Tick the box if other computers will run A-H CODE against the database on this machine. ' +
    'Setup will let PostgreSQL accept connections from the same network and open port 5432 in Windows Firewall.',
    False, False);
  LanPage.Add('This is the MAIN machine - allow other computers on the network to connect');
  LanPage.Values[0] := (GetPreviousData('Lan', ExpandConstant('{param:LAN|0}')) = '1');

  BackupPage := CreateInputDirPage(LanPage.ID, 'Backup Folder',
    'Where should database backups be saved?',
    'Automatic and manual backups (.sql files) are written to this folder. ' +
    'You can choose an external drive or a network folder.', False, '');
  BackupPage.Add('');
  BackupPage.Values[0] := GetPreviousData('BackupDir',
    ExpandConstant('{param:BACKUPDIR|{commonappdata}\PHASEINV2\Backups}'));
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'DbHost', DbHost());
  SetPreviousData(PreviousDataKey, 'DbPort', DbPort());
  SetPreviousData(PreviousDataKey, 'DbName', DbName());
  SetPreviousData(PreviousDataKey, 'DbUser', DbUser());
  if LanPage.Values[0] then SetPreviousData(PreviousDataKey, 'Lan', '1')
  else SetPreviousData(PreviousDataKey, 'Lan', '0');
  SetPreviousData(PreviousDataKey, 'BackupDir', BackupPage.Values[0]);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = LanPage.ID) and not IsLocalHost(DbHost());
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = DbPage.ID) and (CurrentKey() <> TestedKey) then
    Result := TestConnection();
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var Lan: String;
begin
  if IsLocalHost(DbHost()) and LanPage.Values[0] then Lan := 'Yes' else Lan := 'No';
  Result := MemoDirInfo + NewLine + NewLine +
    'Database:' + NewLine + Space + DbUser() + '@' + DbHost() + ':' + DbPort() + ' / ' + DbName() +
    NewLine + NewLine + 'Main machine for the network:' + NewLine + Space + Lan +
    NewLine + NewLine + 'Backup folder:' + NewLine + Space + BackupPage.Values[0];
end;

function RunStep(const Title, Params: String): Boolean;
var Msg, Output, PassFile: String; Answer: Integer;
begin
  repeat
    WizardForm.StatusLabel.Caption := Title + '...';
    PassFile := WritePasswordFile();
    Result := RunTool(ExpandConstant('{app}\{#CfgExe}'),
                      StringChangeEx2(Params, '%PASS%', PassFile), Title, Msg, Output);
    DeleteFile(PassFile);
    if Result then Exit;
    Answer := SuppressibleMsgBox(Title + ' failed:' + #13#10#13#10 + Msg + #13#10#13#10 +
      'Log: ' + LogFile, mbError, MB_RETRYCANCEL, IDCANCEL);
  until Answer <> IDRETRY;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Conn, Db: String; Ok: Boolean;
begin
  if CurStep <> ssPostInstall then Exit;
  Conn := Format('--host "%s" --port %s --user "%s" --password-file "%%PASS%%"',
                 [DbHost(), DbPort(), DbUser()]);
  Db := ' --db "' + DbName() + '"';
  Ok := RunStep('Saving the connection settings',
                'write --mode lan --address "' + DbHost() + '" --port ' + DbPort() + Db +
                ' --user "' + DbUser() + '" --password-file "%PASS%"');
  if Ok and IsLocalHost(DbHost()) then
    Ok := RunStep('Creating the database (only if missing)', 'create-db ' + Conn + Db);
  if Ok then
    Ok := RunStep('Preparing the database tables and default user', 'provision ' + Conn + Db);
  ForceDirectories(BackupPage.Values[0]);
  RunStep('Saving the backup folder', 'set-backup-dir --path "' + BackupPage.Values[0] +
          '" --out "' + ExpandConstant('{commonappdata}\PHASEINV2\backup_settings.json') + '"');
  if IsLocalHost(DbHost()) and LanPage.Values[0] then
    RunStep('Allowing network computers to connect', 'enable-lan ' + Conn);
end;
```

Notes for the implementer:
- `StringChangeEx2` does not exist; implement it as a helper that copies the string, calls `StringChangeEx(S, '%PASS%', PassFile, True)` and returns `S`. Put it above `RunStep`:

```pascal
function StringChangeEx2(S: String; const FromStr, ToStr: String): String;
begin
  StringChangeEx(S, FromStr, ToStr, True);
  Result := S;
end;
```

- In `Format`, `%%PASS%%` yields the literal `%PASS%`.
- `TestStatus.Font.Color` uses Inno's `clGreen`/`clRed`/`clGray` constants.

- [ ] **Step 2: Append to `setup/build.ps1`**

```powershell
$Iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) { $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
$Version = Get-Date -Format "yyyy.MM.dd"
Step "Inno Setup" { & $Iscc "/DAppVersion=$Version" (Join-Path $Setup "AHCODE_Setup.iss") }
Write-Host "Installer: $(Join-Path $Setup 'Output\A-H_CODE_Setup.exe')" -ForegroundColor Green
```

- [ ] **Step 3: Compile only** (dist already built in Task 4):

Run: `& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=2026.10.15 setup\AHCODE_Setup.iss`
Expected: `Successful compile`, `setup/Output/A-H_CODE_Setup.exe` exists. Fix any Pascal compile errors and recompile.

- [ ] **Step 4: Visual check of the wizard pages** — start `setup/Output/A-H_CODE_Setup.exe` (no install: cancel on the Ready page), screenshot the Database Connection, Network and Backup pages with computer-use, compare with the user's screenshot (field order, defaults, `SABCONTDB`), and click `Test Connection` with a wrong password to see the red status and an English error message. Then with the real password (typed by the user, never by the agent) see the green "will be created" message for a missing DB name.

- [ ] **Step 5: Commit**

```bash
git add setup/AHCODE_Setup.iss setup/build.ps1
git commit -m "Setup: Inno Setup wizard for A-H CODE (connection test, LAN, backup folder)"
```

---

### Task 6: End-to-end silent install test, client guide, push

**Files:**
- Create: `setup/e2e_silent_test.ps1`
- Create: `setup/دليل_التثبيت_للعميل.md`

**Interfaces:**
- Consumes: `setup/Output/A-H_CODE_Setup.exe` silent parameters (Task 5).

- [ ] **Step 1: Write `setup/e2e_silent_test.ps1`**

```powershell
# Silent install -> verify -> uninstall, against a throw-away database.
# Usage (elevated): setup\e2e_silent_test.ps1 -PasswordFile <file holding the local postgres password>
param([Parameter(Mandatory)] [string]$PasswordFile)
$ErrorActionPreference = "Stop"
$Setup = $PSScriptRoot
$Exe   = Join-Path $Setup "Output\A-H_CODE_Setup.exe"
$Db    = "AHCODE_SETUP_TEST"
$Dir   = "C:\AHCODE_E2E"
$Psql  = (Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" | Sort-Object FullName -Descending | Select-Object -First 1).FullName
$env:PGPASSWORD = (Get-Content $PasswordFile -Raw).Trim()
$Profile = "C:\ProgramData\PHASEINV2\connection.json"
$Saved = "$Profile.e2e-saved"
if (Test-Path $Profile) { Copy-Item $Profile $Saved -Force }
try {
    & $Psql -U postgres -h localhost -tAc "DROP DATABASE IF EXISTS $Db"
    $p = Start-Process $Exe -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/DIR=`"$Dir`"", "/DBNAME=$Db", "/DBPASSFILE=`"$PasswordFile`"", "/LAN=0",
        "/LOG=`"$Setup\build\e2e-install.log`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Setup exit code $($p.ExitCode)" }
    if (-not (Test-Path "$Dir\A-H CODE.exe")) { throw "App not installed" }
    $exists = & $Psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='$Db'"
    if ($exists.Trim() -ne "1") { throw "Database not created" }
    $tables = & $Psql -U postgres -h localhost -d $Db -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
    $users = & $Psql -U postgres -h localhost -d $Db -tAc "SELECT count(*) FROM app_users"
    if ([int]$tables -lt 50 -or [int]$users -lt 1) { throw "Schema/admin missing ($tables tables, $users users)" }
    $json = Get-Content $Profile -Raw | ConvertFrom-Json
    if ($json.database.name -ne $Db -or $json.database.password -notlike "dpapi:*") { throw "Profile wrong" }
    if (-not (Select-String -Path "C:\ProgramData\PHASEINV2\backup_settings.json" -Pattern "Backups" -Quiet)) { throw "Backup dir not saved" }
    # Second run = upgrade: must keep data and succeed.
    & $Psql -U postgres -h localhost -d $Db -tAc "CREATE TABLE e2e_marker(x int); INSERT INTO e2e_marker VALUES (7)"
    $p = Start-Process $Exe -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/DBNAME=$Db", "/DBPASSFILE=`"$PasswordFile`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Upgrade exit code $($p.ExitCode)" }
    if ((& $Psql -U postgres -h localhost -d $Db -tAc "SELECT x FROM e2e_marker").Trim() -ne "7") { throw "Upgrade touched data" }
    # Frozen app reaches the login window (offscreen, killed after 25 s).
    $env:QT_QPA_PLATFORM = "offscreen"
    $app = Start-Process "$Dir\A-H CODE.exe" -PassThru
    Start-Sleep 25
    $alive = -not $app.HasExited
    if ($alive) { Stop-Process $app -Force }
    Remove-Item Env:QT_QPA_PLATFORM
    if (-not $alive) { throw "App exited early (code $($app.ExitCode))" }
    $u = Start-Process "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES" -Wait -PassThru
    if (Test-Path "$Dir\A-H CODE.exe") { throw "Uninstall left the app" }
    if (-not (Test-Path $Profile)) { throw "Uninstall removed the connection file" }
    Write-Host "E2E PASSED" -ForegroundColor Green
}
finally {
    & $Psql -U postgres -h localhost -tAc "DROP DATABASE IF EXISTS $Db WITH (FORCE)"
    if (Test-Path $Saved) { Move-Item $Saved $Profile -Force } else { Remove-Item $Profile -ErrorAction SilentlyContinue }
    Remove-Item Env:PGPASSWORD
}
```

The script restores the developer machine's own `connection.json` afterwards, so the dev app keeps pointing at `SABCONTDB`.

- [ ] **Step 2: Run it** (elevated, background). The password file is created by the user (or from the project's local `.env` value) in the scratchpad and deleted afterwards; never print it.
Expected: `E2E PASSED`. On failure read `setup\build\e2e-install.log` and `C:\ProgramData\PHASEINV2\logs\install-*.log`, fix, rebuild, rerun.

- [ ] **Step 3: Write the Arabic client guide `setup/دليل_التثبيت_للعميل.md`** — sections:
  المتطلب الوحيد (PostgreSQL مثبت + كلمة سر postgres)، تثبيت جهاز واحد، الجهاز الرئيسي في الشبكة (تعليم الاختيار)، أجهزة الشبكة (كتابة IP الجهاز الرئيسي)، أول تسجيل دخول (اسم المستخدم الافتراضي من `auth_service.DEFAULT_ADMIN_USERNAME` — اكتب الاسم فقط، وكلمة السر تُسلَّم شفهياً)، أماكن الملفات (البرنامج، `C:\ProgramData\PHASEINV2\connection.json`، النسخ الاحتياطي، سجل التثبيت)، التحديث (شغّل النسخة الأحدث)، إلغاء التثبيت (لا يمس القاعدة)، حل المشاكل (كلمة سر خاطئة، خدمة PostgreSQL متوقفة، الفايروول/IP غلط، رسالة "database does not exist" على جهاز شبكة = اكتب IP الجهاز الرئيسي).

- [ ] **Step 4: Regression run**

Run each separately: `python -m pytest tests/unit/test_installer_cli.py tests/unit/test_pg_lan.py tests/unit/test_frozen_runtime.py tests/test_connection_config.py tests/unit/test_schema_bootstrap.py tests/unit/test_permission_system.py tests/unit/test_permission_ui_parity.py tests/unit/test_live_lists.py -q`
Expected: PASS (only the known legacy failures listed in memory are acceptable, none of them are in this list).

- [ ] **Step 5: Commit and push**

Check staged files (no `.bat`, PDFs, backups, config, passwords; grep the diff for the two known password strings), then:

```bash
git add setup/e2e_silent_test.ps1 "setup/دليل_التثبيت_للعميل.md"
git commit -m "Setup: end-to-end silent install test and Arabic client guide"
git push origin main
```

Deliver `setup/Output/A-H_CODE_Setup.exe` to the user (SendUserFile with display "attach" is too large; give the path and open the folder with reveal_path).
