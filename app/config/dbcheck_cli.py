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
        message = result.message
        if not result.ok:
            message = net.friendly_db_message(args.host, args.port, args.db, args.user,
                                              result.detail or result.message)
        if password:
            message = message.replace(password, "******")
        return cli_output.emit({"ok": result.ok, "db_missing": missing, "message": message},
                               ok=result.ok)
    except Exception as exc:  # noqa: BLE001 - never show a traceback in the wizard
        return cli_output.emit({"ok": False, "db_missing": False,
                                "message": f"{type(exc).__name__}: {exc}"}, ok=False)


if __name__ == "__main__":
    sys.exit(main())
