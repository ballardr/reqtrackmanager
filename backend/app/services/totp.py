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
import io

import pyotp
import qrcode


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
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def verify_code(secret: str, code: str) -> bool:
    """Verifies a TOTP code against a secret, allowing 1 step of clock drift."""
    return pyotp.TOTP(secret).verify(code, valid_window=1)
