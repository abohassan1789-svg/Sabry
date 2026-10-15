"""Passwords with spaces, symbols or Arabic text reach PostgreSQL unchanged.

No server is needed: every place that builds a connection string is parsed back
with libpq's own rules (``conninfo_to_dict``) or its kwargs are captured.
"""

from __future__ import annotations

import pytest
from psycopg.conninfo import conninfo_to_dict

from app.config import configure_cli
from app.config.connection_config import ConnectionProfile
from app.config.database import build_database_url
from app.config.settings import Settings
from app.services import network_service as net

PASSWORDS = ["plain", "a b", "p@ss#1/%", "'q", "a\\b", "كلمة سر", "50%off", "x+y", 'q"uote']


def _parsed(url: str) -> dict:
    return conninfo_to_dict(url.replace("postgresql+psycopg://", "postgresql://"))


@pytest.mark.parametrize("password", PASSWORDS)
def test_runtime_url_keeps_password(password):
    url = build_database_url(Settings(db_name="SABCONTDB", db_user="postgres",
                                      db_password=password, db_host="localhost", db_port=5432))
    parsed = _parsed(url)
    assert parsed["password"] == password
    assert parsed["host"] == "localhost" and parsed["dbname"] == "SABCONTDB"


@pytest.mark.parametrize("password", PASSWORDS)
def test_profile_url_keeps_password(password):
    profile = ConnectionProfile(server_address="192.168.1.10", db_name="SABCONTDB",
                                db_user="postgres", db_password=password)
    parsed = _parsed(profile.database_url())
    assert parsed["password"] == password and parsed["host"] == "192.168.1.10"


@pytest.mark.parametrize("password", PASSWORDS)
def test_provision_url_keeps_password(password):
    url = configure_cli.db_url("localhost", 5432, "SABCONTDB", "postgres", password, "prefer")
    assert _parsed(url)["password"] == password


@pytest.mark.parametrize("password", PASSWORDS)
def test_connection_test_passes_password_unchanged(password, monkeypatch):
    import psycopg

    seen = {}

    def fake_connect(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        raise psycopg.OperationalError("stop here")

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    result = net.test_database("localhost", 5432, "SABCONTDB", "postgres", password)
    assert not result.ok
    assert seen["args"] == () and seen["kwargs"]["password"] == password
    assert password not in result.message or password == "plain"
