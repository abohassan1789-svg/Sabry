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
