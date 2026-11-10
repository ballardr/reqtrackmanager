"""
Module: services.email_confirmation

Confirms that a self-signed-up account's email address is the person's own before the account can sign in
(access control Known Gap 4).

Responsibilities:
- Issue and email a single-use, expiring confirmation link (reusing the reset-token table, `issued_via="confirm"`, so
  the same hashed-secret, fragment-link and cooldown rules apply) and spend it.
- Say whether an account must still confirm (`blocks_sign_in`).

Design decisions:
- Only public self-sign-up without an invitation creates a pending account. An invitation link was already sent to the
  address, an administrator or SCIM client vouches for the accounts they create, and a verified identity-provider
  claim proves the address, so none of those are asked again.
- A link that spends a password reset also confirms (it reaches the same mailbox).
- The deployment setting `Settings.require_email_confirmation` turns the requirement off (the e2e stack does).

External dependencies: `services.credential_reset` (tokens, rate limit, email), `services.email_templates`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.credential_reset import CredentialResetToken
from app.models.user import User
from app.security import hash_pat
from app.services import credential_reset
from app.services.audit import log_event
from app.services.email import send_email
from app.services.email_templates import render_email

#: Longest a confirmation link works, in minutes (a day: a person may open the email later than a reset).
CONFIRMATION_MINUTES = 24 * 60

CONFIRMATION_REQUIRED_MESSAGE = (
    "Confirm your email address before signing in. Open the link in the email we sent when you signed up."
)


def required() -> bool:
    """Whether a public self-sign-up must be confirmed (`Settings.require_email_confirmation`)."""
    return get_settings().require_email_confirmation


def send_confirmation(db: Session, user: User) -> None:
    """Issues a confirmation link and emails it to the account's own address (the caller commits).

    Raises:
        Exception: Any delivery failure, after removing the unsent token so no live link exists that nobody received.
    """
    raw, minutes = credential_reset.issue_token(db, user, via="confirm", ttl_minutes=CONFIRMATION_MINUTES)
    try:
        branding = credential_reset.resolve_branding(db, user)
        html_body, text_body = render_email(
            "password_reset", branding=branding, heading="Confirm your email address",
            intro="Confirm that this is your email address to finish creating your account.",
            reset_url=credential_reset.reset_url(raw, "confirm-email"), expires_minutes=minutes,
            cta_label="Confirm your email address",
            closing="If you did not sign up, you can ignore this email: the account cannot be used until the address is confirmed.",
        )
        inline = {"brand_logo": (branding.logo_bytes, branding.logo_content_type)} if branding.logo_bytes else None
        send_email(user.email, f"{branding.header_title}: confirm your email address", text_body, html_body=html_body, inline_images=inline)
    except Exception:
        credential_reset.delete_unsent_token(db, raw)
        raise


def confirm(db: Session, raw_token: str) -> User | None:
    """Spends a confirmation link and clears the account's pending flag (flushed, not committed).

    Returns:
        The confirmed account, or `None` for an unknown, used or expired link (one answer for all three).
    """
    now = datetime.now(UTC)
    row = db.execute(
        update(CredentialResetToken)
        .where(
            CredentialResetToken.token_hash == hash_pat(raw_token),
            CredentialResetToken.issued_via == "confirm",
            CredentialResetToken.used_at.is_(None),
            CredentialResetToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(CredentialResetToken.user_id)
    ).first()
    if row is None:
        return None
    user = db.get(User, row.user_id)
    if user is None:
        return None
    user.email_confirmation_pending = False
    log_event(db, entity_type="user", entity_id=user.id, action="email_confirmed", actor_id=user.id)
    db.flush()
    return user


def resend(db: Session, email: str) -> None:
    """Sends a fresh link to a pending account (no answer reveals whether the address has one). Commits."""
    from sqlalchemy import select

    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.email_confirmation_pending or credential_reset.recently_issued(db, user):
        return
    try:
        send_confirmation(db, user)
        log_event(db, entity_type="user", entity_id=user.id, action="email_confirmation_resent", actor_id=None)
        db.commit()
    except Exception:  # noqa: BLE001 - a delivery problem must not become a signal about the address
        db.rollback()
