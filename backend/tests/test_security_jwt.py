"""Tests for the JWT helpers in `app.security` (`_encode_jwt`/`_decode_jwt`,
built on joserfc): round-trip, and rejection of every malformed, tampered,
expired, `exp`-less or wrong-algorithm token — the failure classes that
motivated replacing python-jose (CVE-2024-33663 algorithm confusion, no
patched release)."""

import base64
import json
from datetime import UTC, datetime, timedelta

from joserfc import jwt as joserfc_jwt
from joserfc.jwk import OctKey

from app.config import get_settings
from app.security import _decode_jwt, _encode_jwt, create_access_token, decode_access_token

settings = get_settings()


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _future() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=5)


def test_round_trip_preserves_claims():
    claims = _decode_jwt(_encode_jwt({"sub": "u1", "exp": _future(), "purpose": "access"}))
    assert claims is not None
    assert claims["sub"] == "u1" and claims["purpose"] == "access"


def test_access_token_round_trip():
    claims = decode_access_token(create_access_token("u1", token_version=3))
    assert claims is not None and claims["sub"] == "u1" and claims["tv"] == 3


def test_expired_token_rejected():
    assert _decode_jwt(_encode_jwt({"sub": "u1", "exp": datetime.now(UTC) - timedelta(seconds=5)})) is None


def test_token_without_exp_rejected():
    assert _decode_jwt(_encode_jwt({"sub": "u1"})) is None


def test_tampered_payload_rejected():
    header, _payload, signature = _encode_jwt({"sub": "u1", "exp": _future()}).split(".")
    forged = _b64({"sub": "admin", "exp": int(_future().timestamp())})
    assert _decode_jwt(f"{header}.{forged}.{signature}") is None


def test_wrong_secret_rejected():
    other = OctKey.import_key("x" * 48)
    token = joserfc_jwt.encode({"alg": "HS256"}, {"sub": "u1", "exp": int(_future().timestamp())}, other)
    assert _decode_jwt(token) is None


def test_alg_none_rejected():
    token = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': 'u1', 'exp': int(_future().timestamp())})}."
    assert _decode_jwt(token) is None


def test_other_hmac_algorithm_rejected():
    """Signed with the right secret but a non-configured algorithm."""
    key = OctKey.import_key(settings.jwt_secret)
    token = joserfc_jwt.encode(
        {"alg": "HS512"}, {"sub": "u1", "exp": int(_future().timestamp())}, key, algorithms=["HS512"],
    )
    assert _decode_jwt(token) is None


def test_garbage_rejected():
    for token in ("", "garbage", "a.b.c", "a.b"):
        assert _decode_jwt(token) is None
