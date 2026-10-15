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
    # Never run from the users-writable data folder: a planted pg_dump.exe or
    # .env there must not be picked up (cwd is searched first on Windows).
    assert os.getcwd() == str(tmp_path)
    assert env["NoDefaultCurrentDirectoryInExePath"] == "1"


def test_frozen_build_ignores_dotenv_in_cwd(tmp_path, monkeypatch):
    import sys

    from app.config import settings as settings_mod

    (tmp_path / ".env").write_text("DB_NAME=PLANTED\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DB_NAME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(settings_mod, "_load_profile", lambda: None)
    assert settings_mod.get_settings().db_name == "crm"
    assert "DB_NAME" not in os.environ


def test_prepare_keeps_explicit_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = {"BACKUP_SETTINGS_PATH": "X:/mine.json"}
    frozen_runtime.prepare(env, program_data=str(tmp_path))
    assert env["BACKUP_SETTINGS_PATH"] == "X:/mine.json"
    assert os.getcwd() == str(tmp_path)


def test_smoke_import_reports_ok(tmp_path):
    out = tmp_path / "smoke.txt"
    assert frozen_runtime.smoke_import(["app.config"], str(out)) == 0
    text = out.read_text(encoding="utf-8")
    assert "OK app.config.connection_config" in text and "FAILED" not in text


def test_main_window_title_is_product_name():
    import inspect

    from app.ui import main_window

    assert main_window.APP_TITLE == "A-H CODE"
    assert "setWindowTitle(APP_TITLE)" in inspect.getsource(main_window.ReviewMainWindow.__init__)
