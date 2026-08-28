"""Tests for the OIDC client: the SSRF guard
(`services/oidc_client._assert_safe_external_url`, E-U-01 hardening) and
`verify_id_token`'s signature/claims verification. No network calls: the
SSRF-guard tests exercise the guard directly against literal-IP hostnames,
which resolve locally without DNS, and the `verify_id_token` tests sign
their own tokens with a locally-generated RSA key rather than calling a
real IdP."""

import time

import pytest
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import RSAKey

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


# --- verify_id_token: signature/claims verification -------------------------
#
# These pin the joserfc-based rewrite (migrated off the now-deprecated
# `authlib.jose`, see services/oidc_client.py's import comment) against
# regression, and were added because the pre-existing test suite only ever
# exercised this function via `monkeypatch.setattr("app.services.oidc_client
# .verify_id_token", ...)` in the OIDC provisioning tests — meaning its
# actual cryptographic logic had zero direct coverage before this file.

_ISSUER = "https://idp.example.com"
_JWKS_URI = "https://idp.example.com/jwks"
_CLIENT_ID = "reqtrack-client"


@pytest.fixture
def _rsa_key():
    return RSAKey.generate_key(2048, auto_kid=True)


def _discovery():
    return {"issuer": _ISSUER, "jwks_uri": _JWKS_URI}


def _sign(key, claims, *, alg="RS256"):
    header = {"alg": alg}
    if key.kid:
        header["kid"] = key.kid
    return joserfc_jwt.encode(header, claims, key)


def _default_claims(**overrides):
    now = int(time.time())
    claims = {"iss": _ISSUER, "aud": _CLIENT_ID, "sub": "user-1", "iat": now, "exp": now + 300}
    claims.update(overrides)
    return claims


def _mock_jwks(monkeypatch, rsa_key):
    # Only `verify_id_token`'s signature/claims logic is under test in this
    # section, not the SSRF guard (covered above) — `_JWKS_URI` is never
    # actually resolved (httpx.get is replaced below), so the guard's
    # real-DNS resolution step would otherwise fail every test here for an
    # unrelated reason.
    monkeypatch.setenv("OIDC_ALLOW_PRIVATE_NETWORK_TARGETS", "true")
    get_settings.cache_clear()
    jwks = {"keys": [rsa_key.as_dict(private=False)]}
    response = type("_FakeResponse", (), {"raise_for_status": lambda self: None, "json": lambda self: jwks})()
    monkeypatch.setattr("httpx.get", lambda *a, **k: response)


def test_verify_id_token_accepts_a_validly_signed_token(monkeypatch, _rsa_key):
    token = _sign(_rsa_key, _default_claims(email="user@example.com"))
    _mock_jwks(monkeypatch, _rsa_key)
    claims = oidc_client.verify_id_token(_discovery(), token, client_id=_CLIENT_ID, issuer_url=_ISSUER)
    assert claims["sub"] == "user-1"
    assert claims["email"] == "user@example.com"


def test_verify_id_token_rejects_a_token_signed_by_an_unknown_key(monkeypatch, _rsa_key):
    other_key = RSAKey.generate_key(2048, auto_kid=True)
    token = _sign(other_key, _default_claims())  # signed by a key not in the published JWKS
    _mock_jwks(monkeypatch, _rsa_key)
    with pytest.raises(ValueError, match="Invalid OIDC id_token"):
        oidc_client.verify_id_token(_discovery(), token, client_id=_CLIENT_ID, issuer_url=_ISSUER)


def test_verify_id_token_rejects_an_expired_token(monkeypatch, _rsa_key):
    expired = int(time.time()) - 3600
    token = _sign(_rsa_key, _default_claims(iat=expired - 300, exp=expired))
    _mock_jwks(monkeypatch, _rsa_key)
    with pytest.raises(ValueError, match="Invalid OIDC id_token"):
        oidc_client.verify_id_token(_discovery(), token, client_id=_CLIENT_ID, issuer_url=_ISSUER)


def test_verify_id_token_rejects_wrong_issuer(monkeypatch, _rsa_key):
    token = _sign(_rsa_key, _default_claims(iss="https://not-the-configured-issuer.example.com"))
    _mock_jwks(monkeypatch, _rsa_key)
    with pytest.raises(ValueError, match="issuer does not match"):
        oidc_client.verify_id_token(_discovery(), token, client_id=_CLIENT_ID, issuer_url=_ISSUER)


def test_verify_id_token_rejects_wrong_audience(monkeypatch, _rsa_key):
    token = _sign(_rsa_key, _default_claims(aud="some-other-client"))
    _mock_jwks(monkeypatch, _rsa_key)
    with pytest.raises(ValueError, match="audience does not match"):
        oidc_client.verify_id_token(_discovery(), token, client_id=_CLIENT_ID, issuer_url=_ISSUER)


def test_verify_id_token_rejects_a_token_missing_exp(monkeypatch, _rsa_key):
    claims = _default_claims()
    del claims["exp"]
    token = _sign(_rsa_key, claims)
    _mock_jwks(monkeypatch, _rsa_key)
    with pytest.raises(ValueError, match="Invalid OIDC id_token"):
        oidc_client.verify_id_token(_discovery(), token, client_id=_CLIENT_ID, issuer_url=_ISSUER)


def test_verify_id_token_rejects_hs256_algorithm_confusion(monkeypatch, _rsa_key):
    """A malicious token signed with HS256, using the IdP's own published RSA
    public modulus as the HMAC secret, must not verify — the classic JWT
    "algorithm confusion" attack `_ALLOWED_ID_TOKEN_ALGORITHMS` (see that
    constant's comment in services/oidc_client.py) exists to close."""
    from joserfc.jwk import OctKey

    forged_secret = _rsa_key.as_dict(private=False)["n"]
    hmac_key = OctKey.import_key(forged_secret)
    token = _sign(hmac_key, _default_claims(), alg="HS256")
    _mock_jwks(monkeypatch, _rsa_key)
    with pytest.raises(ValueError, match="Invalid OIDC id_token"):
        oidc_client.verify_id_token(_discovery(), token, client_id=_CLIENT_ID, issuer_url=_ISSUER)
