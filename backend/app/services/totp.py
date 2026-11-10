"""
Module: services.totp

TOTP-based two-factor authentication (C-U-14): secret generation,
QR-code provisioning for authenticator-app enrollment, and code
verification. Only applies to the native auth backend — SSO-authenticated
users manage MFA through their identity provider, per the requirement's
"for users not using SSO" clarification.
"""

from __future__ import annotations

import base64
import hmac
import io
import time

import pyotp
import qrcode

from app.models.user import User


def generate_secret() -> str:
    """Generates a new random TOTP secret."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str, issuer: str = "ReqTrackManager") -> str:
    """Builds the `otpauth://` provisioning URI for authenticator-app enrollment."""
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def provisioning_qr_code_png_base64(secret: str, email: str, issuer: str = "ReqTrackManager") -> str:
    """Builds a base64-encoded PNG QR code for authenticator-app enrollment.

    Args:
        secret: The TOTP secret to encode.
        email: The user's email, shown as the account label in the app.
        issuer: The issuer name shown in the authenticator app.

    Returns:
        A base64-encoded PNG image string (no data: URI prefix).
    """
    image = qrcode.make(provisioning_uri(secret, email, issuer))
    buffer = io.BytesIO()
    image.save(buffer)  # both qrcode image back ends write PNG by default
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def verify_code(secret: str, code: str) -> bool:
    """Verifies a TOTP code against a secret, allowing 1 step of clock drift."""
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def _now() -> float:
    """The current time in seconds since the epoch (UTC); a seam for tests."""
    return time.time()


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The 30-second time step whose code equals `code`, allowing 1 step of clock drift, or `None`.

    Args:
        secret: The account's TOTP secret.
        code: The submitted code.
        now: Seconds since the epoch (UTC); tests pass it.
    """
    totp = pyotp.TOTP(secret)
    current = int((_now() if now is None else now) // totp.interval)
    for step in (current, current - 1, current + 1):
        if hmac.compare_digest(totp.generate_otp(step), str(code)):
            return step
    return None


def consume_code(user: User, code: str, now: float | None = None) -> bool:
    """Accepts `code` once: valid for the account's secret and for a later time step than any code already used.

    A code seen by someone watching (or typed into a phishing page) is therefore not reusable inside its
    30-second window. On success the step is recorded on `user` (the caller commits).

    Returns:
        True when accepted.
    """
    if user.totp_secret is None:
        return False
    step = matching_step(user.totp_secret, code, now)
    if step is None or (user.last_totp_step is not None and step <= user.last_totp_step):
        return False
    user.last_totp_step = step
    return True
