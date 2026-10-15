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
    """Password method for network computers: always a real password check.

    Keeps ``md5`` when the local rule uses it (md5 rules also accept SCRAM
    passwords); anything else, above all ``trust``, becomes ``scram-sha-256`` so
    the network never gets in without a password.
    """
    for line in hba_text.splitlines():
        f = _fields(line)
        if len(f) >= 5 and f[0] == "host" and f[3] == "127.0.0.1/32" and f[4] == "md5":
            return "md5"
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
               stamp: str, live_listen: str | None = None) -> dict:
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
    # live_listen is the server's current listen_addresses: when an earlier
    # attempt edited the files but its restart failed, the files look done yet
    # the server is still local-only, so restart anyway.
    not_live = live_listen is not None and live_listen.strip() != "*"
    if conf_changed or hba_changed or not_live:
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
