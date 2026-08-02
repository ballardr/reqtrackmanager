"""Tests for the OIDC client's SSRF guard (`services/oidc_client._assert_safe_external_url`,
E-U-01 hardening). No network calls: these exercise the guard directly against
literal-IP hostnames, which resolve locally without DNS."""

import pytest

from app.config import get_settings
from app.services import oidc_client


@pytest.fixture(autouse=True)
def _reset_settings_cache(monkeypatch):
    # The real dev/test stack sets OIDC_INTERNAL_BASE_URL_OVERRIDE (see
    # tests/container/docker-compose.yml) so it can reach its own Keycloak
    # container — clear it here so "by default" below actually means the
    # guard's true default, not this environment's override.
    monkeypatch.delenv("OIDC_INTERNAL_BASE_URL_OVERRIDE", raising=False)
    monkeypatch.delenv("OIDC_ALLOW_PRIVATE_NETWORK_TARGETS", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_rejects_a_loopback_target_by_default():
    with pytest.raises(ValueError, match="non-public address"):
        oidc_client._assert_safe_external_url("http://127.0.0.1/.well-known/openid-configuration")


def test_rejects_a_private_range_target_by_default():
    with pytest.raises(ValueError, match="non-public address"):
        oidc_client._assert_safe_external_url("http://10.0.0.5/.well-known/openid-configuration")


def test_allows_a_public_looking_target_by_default():
    # 8.8.8.8 is a real, always-global address (Google Public DNS) — used
    # here purely as a stand-in "definitely public" IP literal, no request
    # is actually made by this guard.
    oidc_client._assert_safe_external_url("http://8.8.8.8/.well-known/openid-configuration")


def test_oidc_allow_private_network_targets_disables_the_guard(monkeypatch):
    monkeypatch.setenv("OIDC_ALLOW_PRIVATE_NETWORK_TARGETS", "true")
    get_settings.cache_clear()
    oidc_client._assert_safe_external_url("http://127.0.0.1/.well-known/openid-configuration")
    oidc_client._assert_safe_external_url("http://10.0.0.5/.well-known/openid-configuration")


def test_oidc_internal_base_url_override_also_disables_the_guard(monkeypatch):
    monkeypatch.setenv("OIDC_INTERNAL_BASE_URL_OVERRIDE", "http://keycloak:8080")
    get_settings.cache_clear()
    oidc_client._assert_safe_external_url("http://127.0.0.1/.well-known/openid-configuration")
