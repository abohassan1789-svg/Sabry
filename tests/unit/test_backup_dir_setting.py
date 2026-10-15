"""The backup folder chosen in the installer (backup_settings.json) is honoured."""

from __future__ import annotations

import json

from app.services import backup_service
from app.services.backup_service import BackupService


def _settings(tmp_path, **data):
    path = tmp_path / "backup_settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_backup_dir_comes_from_settings_file(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    path = _settings(tmp_path, backup_dir=str(tmp_path / "Chosen"))
    svc = BackupService(repository=object(), settings_path=path)
    assert svc.backup_dir == str(tmp_path / "Chosen")


def test_env_backup_dir_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "Env"))
    path = _settings(tmp_path, backup_dir=str(tmp_path / "Chosen"))
    svc = BackupService(repository=object(), settings_path=path)
    assert svc.backup_dir == str(tmp_path / "Env")


def test_installed_default_is_next_to_settings_not_program_files(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    path = _settings(tmp_path, backup_on_startup=True)
    monkeypatch.setenv("BACKUP_SETTINGS_PATH", str(path))
    svc = BackupService(repository=object())
    assert svc.backup_dir == str(tmp_path / "Backups")


def test_dev_default_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.delenv("BACKUP_SETTINGS_PATH", raising=False)
    path = _settings(tmp_path, backup_on_startup=True)
    svc = BackupService(repository=object(), settings_path=path)
    assert svc.backup_dir == str(backup_service._APP_ROOT / "Backups")
