"""Tests for `GET /api/v1/system/client-config` — the deployment's `HELP_ENABLED`
and `HELP_URL` settings, which the frontend header reads to render (or hide)
the Help link."""

from app.routers.system import config as system_config
from tests.conftest import auth_headers


def test_client_config_defaults_to_the_docs_site(client, admin_token):
    resp = client.get("/api/v1/system/client-config", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"help_enabled": True, "help_url": "https://ballardr.github.io/reqtrackmanager/"}


def test_client_config_reflects_operator_settings(client, admin_token, monkeypatch):
    monkeypatch.setattr(system_config.settings, "help_enabled", False)
    monkeypatch.setattr(system_config.settings, "help_url", "https://docs.internal.example/")
    resp = client.get("/api/v1/system/client-config", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"help_enabled": False, "help_url": "https://docs.internal.example/"}


def test_client_config_requires_authentication(client):
    assert client.get("/api/v1/system/client-config").status_code == 401
