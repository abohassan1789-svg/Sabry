"""Guard against the recurring Qt stylesheet typo across the whole UI.

A `{{`/`}}` inside an **f-string** is the escape for a single brace and is
correct for embedded CSS/QSS/HTML. Inside a **plain** string literal, though,
`{{`/`}}` are two literal braces — never valid CSS — so Qt logs
"Could not parse stylesheet of object ..." and silently drops every rule after
the doubled brace. This test walks the UI tree and fails on any such literal,
which is exactly the class of bug that produced those console warnings.
"""

from __future__ import annotations

import ast
import pathlib

import app.ui as ui_pkg

UI_DIR = pathlib.Path(ui_pkg.__file__).parent


def _offending_literals() -> list[str]:
    offenders: list[str] = []
    for path in UI_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # A bare Constant str node is a plain (non-f) string literal; the
            # pieces of an f-string live under JoinedStr and never surface here.
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "{{" in node.value or "}}" in node.value:
                    rel = path.relative_to(UI_DIR)
                    offenders.append(f"{rel}:{node.lineno}: {node.value[:80]!r}")
    return offenders


def test_no_plain_string_double_brace_in_ui() -> None:
    offenders = _offending_literals()
    assert not offenders, (
        "Plain-string '{{'/'}}' in a stylesheet (should be a single brace; "
        "use an f-string only if you meant to embed a brace):\n  "
        + "\n  ".join(offenders)
    )
