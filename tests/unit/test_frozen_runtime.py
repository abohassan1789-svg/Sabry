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


def test_main_window_title_is_product_name():
    import inspect

    from app.ui import main_window

    assert main_window.APP_TITLE == "A-H CODE"
    assert "setWindowTitle(APP_TITLE)" in inspect.getsource(main_window.ReviewMainWindow.__init__)
