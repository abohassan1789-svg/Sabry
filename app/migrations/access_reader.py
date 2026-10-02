"""Read-only reader for the legacy Access file (``review/sisko.Accdb``).

The Access database is the customer's historical record, so this reader **never
opens the original**: it copies the file to a temporary location, reads the copy,
and deletes it afterwards. Two reasons:

* The file is usually also open in Microsoft Access on the same machine. Opening
  it again from here contends for the same ``.laccdb`` lock, and an import that
  runs while someone is editing reads a moving target.
* A migration has no business writing to the source at all, and reading a
  private copy makes that impossible rather than merely unintended.

Pass ``use_copy=False`` only for a throwaway file you already own.

Requires the Microsoft Access ODBC driver (shipped with Office / the Access
Database Engine redistributable) and ``pyodbc``. Both are only needed while
migrating, so the app never imports this module at runtime.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterator

DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Where the legacy file is looked for, in order. It currently lives in a
# ``review`` folder beside the project directory rather than inside it, so both
# are checked and either layout works.
DEFAULT_ACCESS_CANDIDATES = (
    _PROJECT_ROOT / "review" / "sisko.Accdb",
    _PROJECT_ROOT.parent / "review" / "sisko.Accdb",
)


def default_access_path() -> Path:
    """First candidate that exists, else the last one (for the error message)."""
    for candidate in DEFAULT_ACCESS_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_ACCESS_CANDIDATES[-1]


class AccessReaderError(RuntimeError):
    """Raised with an actionable Arabic message when the file cannot be read."""


class AccessReader:
    """Minimal read-only cursor over an Access database."""

    def __init__(self, path: str | Path | None = None, use_copy: bool = True) -> None:
        self.source_path = Path(path) if path else default_access_path()
        self.use_copy = use_copy
        # The file actually opened — a temp copy unless use_copy is off.
        self.path = self.source_path
        self._temp_dir: tempfile.TemporaryDirectory | None = None
        self._conn: Any = None

    # -- lifecycle -------------------------------------------------------

    def __enter__(self) -> "AccessReader":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        if self._conn is not None:
            return
        if not self.source_path.exists():
            raise AccessReaderError(f"ملف الأكسس غير موجود: {self.source_path}")
        if self.use_copy:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="tawrid_access_")
            self.path = Path(self._temp_dir.name) / self.source_path.name
            shutil.copy2(self.source_path, self.path)
        try:
            import pyodbc
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise AccessReaderError(
                "الحزمة pyodbc غير مثبتة. ثبّتها أولاً: pip install pyodbc"
            ) from exc
        try:
            # readonly=True keeps the migration incapable of altering the source.
            self._conn = pyodbc.connect(
                f"DRIVER={{{DRIVER}}};DBQ={self.path};", readonly=True
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            raise AccessReaderError(
                f"تعذّر فتح ملف الأكسس ({self.path}).\n"
                "تأكد من تثبيت Microsoft Access Database Engine بنفس معمارية بايثون "
                f"(32/64 بت).\nالتفاصيل: {exc}"
            ) from exc

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
        if self._temp_dir is not None:
            # The engine may still hold the copy's lock file for a moment; the
            # copy is disposable either way, so a failure here is not an error.
            try:
                self._temp_dir.cleanup()
            except Exception:
                pass
            finally:
                self._temp_dir = None
                self.path = self.source_path

    # -- reading ---------------------------------------------------------

    def rows(self, query: str) -> Iterator[dict[str, Any]]:
        """Yield each row of *query* as a ``{column: value}`` dict."""
        if self._conn is None:
            self.open()
        cursor = self._conn.cursor()
        cursor.execute(query)
        columns = [c[0] for c in cursor.description]
        for row in cursor.fetchall():
            yield dict(zip(columns, row))

    def count(self, table: str) -> int:
        if self._conn is None:
            self.open()
        return int(self._conn.cursor().execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])
