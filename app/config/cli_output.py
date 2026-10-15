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
