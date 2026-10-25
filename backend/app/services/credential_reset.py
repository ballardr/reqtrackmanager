"""
Module: services.credential_reset

The one place a native account's password is reset without knowing the old one.

Responsibilities:
- Issue and redeem single-use, expiring reset links (`issue_token`, `redeem_token`); only a hash of
  the secret is stored.
- Email a link (`send_reset_email`) for the "forgot password" flow, an administrator's "send reset
  link" action and the command line.
- Apply a forced credential reset to a group of accounts (`force_reset`): end every session, revoke
  personal access tokens, mark the password as needing replacement, optionally clear 2FA enrolment.
- Choose the accounts a forced reset or a link batch covers (`resolve_scope`).
- Remove spent and expired token rows after a week (`purge_spent_tokens`, run daily by the scheduler).

Design decisions:
- The credential epoch is `User.token_version`: every reset increments it, which already rejects any
  session issued before (`deps._resolve_user_from_token`, the WebSocket re-check).
- A reset link never signs the person in and never touches 2FA: choosing a new password proves
  control of the mailbox only, and the second factor is still asked at the next sign-in.
- An administrator sending a link never sees it. It goes to the account's own address, so an
  administrator cannot use the feature to take over an account. The command line prints a link only
  to the operator's terminal, because its authority is shell and database access to the deployment.
- Redemption is one `UPDATE ... WHERE used_at IS NULL AND expires_at > now` so two simultaneous uses
  cannot both succeed.
- Neither the raw secret, a hash nor a link is ever logged, audited or returned from an HTTP API.
- An SSO-only account has no local credential: it is listed, never silently skipped, and a forced
  reset still ends its sessions.

Dependencies: `security` (hashing), `services.email` and `email_templates`, `services.audit`,
`services.pats` (token revocation), `auth_backends.native` (the shared sso-only rule).
"""

from __future__ import annotations

import math
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.auth_backends.native import all_orgs_sso_only
from app.config import get_settings
from app.models.credential_reset import CredentialResetToken
from app.models.notification import NotificationType
from app.models.organization import Organization, UserOrgRole
from app.models.pat import PersonalAccessToken
from app.models.user import User
from app.security import hash_password, hash_pat
from app.services import notifications
from app.services.audit import log_event
from app.services.email import EmailDeliveryDisabled, send_email
from app.services.email_branding import EmailBranding, resolve_email_branding
from app.services.email_templates import render_email
from app.services.pats import revoke_matching
from app.services.rate_limit import RateLimiter

IssuedVia = Literal["forgot", "admin", "cli"]

#: Longest a command-line operator may ask a link to live, in minutes.
MAX_TTL_MINUTES = 1440

#: An account that already has a link issued this recently gets no second one from "forgot password", so
#: the form cannot be used to flood a mailbox.
_RESEND_COOLDOWN = timedelta(seconds=60)


class ResetTokenInvalid(Exception):
    """The link is unknown, expired, already used, or names an account that can no longer reset."""


def has_local_credential(user: User) -> bool:
    """Whether `user` holds a native password at all (ignores the organisation `sso_only` rule).

    Args:
        user: The account.

    Returns:
        True for a native account with a stored password hash.
    """
    return user.auth_backend == "native" and bool(user.password_hash)


def can_reset_by_link(db: Session, user: User) -> bool:
    """Whether a reset link would be useful to `user`: a live native account that can sign in natively.

    Args:
        db: Active session.
        user: The account.

    Returns:
        False for SSO and invited accounts, deactivated, archived and banned accounts, and accounts whose
        every organisation requires SSO.
    """
    return (
        has_local_credential(user)
        and user.is_active
        and not user.is_archived
        and not user.is_banned
        and not all_orgs_sso_only(db, user.id)
    )


def reset_url(raw_token: str) -> str:
    """Builds the link a person opens. The secret is in the URL fragment, which browsers never send to a server,
    so it stays out of access logs and referrers.

    Args:
        raw_token: The secret from `issue_token`.

    Returns:
        The absolute URL of the reset page.
    """
    return f"{get_settings().frontend_base_url.rstrip('/')}/reset-password#token={raw_token}"


def _ttl(ttl_minutes: int | None) -> int:
    """Clamps a requested lifetime to the configured default and `MAX_TTL_MINUTES`."""
    return max(1, min(ttl_minutes or get_settings().credential_reset_token_minutes, MAX_TTL_MINUTES))


def issue_token(
    db: Session, user: User, *, via: IssuedVia, issued_by: uuid.UUID | None = None, ttl_minutes: int | None = None
) -> tuple[str, int]:
    """Creates a reset token for `user` and returns the raw secret once.

    Args:
        db: Active session; the row is added and flushed, not committed.
        user: The account the token resets.
        via: How it is being issued (stored for the audit trail).
        issued_by: The administrator issuing it, if any.
        ttl_minutes: Lifetime override (command line); defaults to `credential_reset_token_minutes`.

    Returns:
        `(raw_secret, lifetime_minutes)`. The secret is not stored anywhere.
    """
    minutes = _ttl(ttl_minutes)
    raw = secrets.token_urlsafe(32)
    db.add(
        CredentialResetToken(
            user_id=user.id, token_hash=hash_pat(raw), issued_via=via, issued_by=issued_by,
            expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
        )
    )
    db.flush()
    return raw, minutes


def recently_issued(db: Session, user: User) -> bool:
    """Whether `user` already has a live link issued within the resend cooldown."""
    cutoff = datetime.now(UTC) - _RESEND_COOLDOWN
    return (
        db.scalar(
            select(CredentialResetToken.id).where(
                CredentialResetToken.user_id == user.id,
                CredentialResetToken.created_at > cutoff,
                CredentialResetToken.used_at.is_(None),
            ).limit(1)
        )
        is not None
    )


def redeem_token(db: Session, raw_token: str, new_password: str) -> User:
    """Spends a reset token and sets the new password.

    The token is marked used in one conditional UPDATE before anything else, so a second concurrent
    request with the same secret finds nothing to spend. Every other outstanding link for the account is
    spent too, the credential epoch advances (ending all sessions), and the must-reset marker clears.

    Args:
        db: Active session; changes are flushed, not committed.
        raw_token: The secret from the link.
        new_password: The password to set (length is checked by the request schema).

    Returns:
        The account whose password changed.

    Raises:
        ResetTokenInvalid: If the link is unknown, expired, used, or the account is gone, inactive, banned
            or not a native account.
    """
    now = datetime.now(UTC)
    row = db.execute(
        update(CredentialResetToken)
        .where(
            CredentialResetToken.token_hash == hash_pat(raw_token),
            CredentialResetToken.used_at.is_(None),
            CredentialResetToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(CredentialResetToken.user_id, CredentialResetToken.issued_via)
    ).first()
    if row is None:
        raise ResetTokenInvalid
    user = db.get(User, row.user_id)
    if user is None or not can_reset_by_link(db, user):
        raise ResetTokenInvalid
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    user.must_reset_credentials = False
    db.execute(
        update(CredentialResetToken)
        .where(CredentialResetToken.user_id == user.id, CredentialResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    notifications.notify(
        db, user, notification_type=NotificationType.PASSWORD_CHANGED,
        title="Your password was reset",
        body="If you did not do this, contact your organisation admin immediately.",
    )
    log_event(
        db, entity_type="user", entity_id=user.id, action="password_reset_completed", actor_id=None,
        detail={"via": row.issued_via},
    )
    db.flush()
    return user


def _branding_organization_id(db: Session, user: User) -> uuid.UUID | None:
    """The organisation whose branding the email uses: the user's only organisation, else the platform's."""
    org_ids = list(db.scalars(select(UserOrgRole.organization_id).where(UserOrgRole.user_id == user.id).distinct()))
    return org_ids[0] if len(org_ids) == 1 else None


_COPY: dict[str, tuple[str, str]] = {
    "forgot": ("Reset your password", "We received a request to reset the password for your account."),
    "admin": ("Reset your password", "An administrator has sent you a link to choose a new password for your account."),
    "forced": (
        "Choose a new password",
        "Your password has been reset for security reasons. Choose a new one to sign in again.",
    ),
}


def resolve_branding(db: Session, user: User) -> EmailBranding:
    """Resolves the branding for `user`'s reset email.

    Resolving it can commit (the platform settings row is created on first use), so a caller that must be
    able to roll back an unsent token resolves it *before* issuing the token.
    """
    return resolve_email_branding(db, _branding_organization_id(db, user))


def send_reset_email(
    db: Session, user: User, raw_token: str, minutes: int, *, kind: str, branding: EmailBranding | None = None
) -> None:
    """Emails a reset link to the account's own address.

    Args:
        db: Active session (for branding).
        user: The recipient.
        raw_token: The secret; goes only into the email body.
        minutes: How long the link works, shown to the reader.
        kind: `forgot`, `admin` or `forced`; picks the wording.
        branding: Pre-resolved branding (`resolve_branding`); resolved here when omitted.

    Raises:
        EmailDeliveryDisabled: If `EMAIL_DELIVERY=disabled`.
        Exception: Any SMTP failure, unchanged.
    """
    heading, intro = _COPY[kind]
    branding = branding or resolve_branding(db, user)
    html_body, text_body = render_email(
        "password_reset", branding=branding, heading=heading, intro=intro,
        reset_url=reset_url(raw_token), expires_minutes=minutes,
    )
    inline = {"brand_logo": (branding.logo_bytes, branding.logo_content_type)} if branding.logo_bytes else None
    send_email(user.email, f"{branding.header_title}: {heading.lower()}", text_body, html_body=html_body, inline_images=inline)


def delete_unsent_token(db: Session, raw_token: str) -> None:
    """Removes a token whose email could not be sent, so no live link exists that nobody received."""
    db.execute(CredentialResetToken.__table__.delete().where(CredentialResetToken.token_hash == hash_pat(raw_token)))


def send_link_for_administrator(db: Session, target: User, *, admin: User, organization_id: uuid.UUID | None) -> None:
    """Emails `target` a reset link on an organisation or server administrator's behalf, and commits.

    The administrator never sees the link: it goes to the account's own address. The authorisation (who may
    reach `target`) is the caller's.

    Args:
        db: Active session.
        target: The account to send the link to.
        admin: The administrator acting.
        organization_id: The organisation the action was taken in, for the audit record (`None` for the
            server tier).

    Raises:
        HTTPException: 400 when the account has no local password or is deactivated; 409 when email delivery
            is disabled on this deployment; 429 when the administrator is sending too fast or a link went to
            this account in the last minute; 502 when the mail server refused it.
    """
    enforce_send_rate_limit(admin.id)
    if not has_local_credential(target) or all_orgs_sso_only(db, target.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account signs in with single sign-on and has no password to reset.")
    if not can_reset_by_link(db, target):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is deactivated, archived or banned.")
    if recently_issued(db, target):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "A reset link was sent to this person less than a minute ago.")
    branding = resolve_branding(db, target)
    raw, minutes = issue_token(db, target, via="admin", issued_by=admin.id)
    log_event(
        db, entity_type="user", entity_id=target.id, action="password_reset_link_sent", actor_id=admin.id,
        organization_id=organization_id, detail={"via": "admin", "expires_minutes": minutes},
    )
    try:
        send_reset_email(db, target, raw, minutes, kind="admin", branding=branding)
    except EmailDeliveryDisabled:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email delivery is disabled on this deployment, so no link can be sent.") from None
    except Exception:  # noqa: BLE001 - the mail server's message may quote the address; report the class of failure only
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The mail server did not accept the message.") from None
    db.commit()


#: How long a spent or expired reset token row is kept before the daily purge removes it.
PURGE_AFTER = timedelta(days=7)


def purge_spent_tokens(db: Session) -> int:
    """Deletes reset tokens that were used or expired more than `PURGE_AFTER` ago, and commits.

    A token is dead the moment it is used or expires, so keeping the row only serves recent troubleshooting;
    the hash is never needed again.

    Args:
        db: Active session.

    Returns:
        How many rows were deleted.
    """
    cutoff = datetime.now(UTC) - PURGE_AFTER
    result = db.execute(
        delete(CredentialResetToken).where(
            or_(CredentialResetToken.used_at < cutoff, CredentialResetToken.expires_at < cutoff)
        )
    )
    db.commit()
    return result.rowcount


# --- rate limits ----------------------------------------------------------------------------------------

_limiters: dict[tuple[str, int, int], RateLimiter] = {}


def _enforce(kind: str, key: object, burst: int, per_minute: int, message: str) -> None:
    """Spends one token for `key` from the `kind` limiter (in-process, per worker).

    Raises:
        HTTPException: 429 with `Retry-After` when the bucket is empty.
    """
    limiter = _limiters.setdefault((kind, burst, per_minute), RateLimiter(burst, per_minute / 60))
    wait = limiter.acquire(key)
    if wait is not None:
        seconds = max(1, math.ceil(wait))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"{message} Wait {seconds} second{'s' if seconds != 1 else ''} and try again.",
            headers={"Retry-After": str(seconds)},
        )


def enforce_public_rate_limit(client_ip: str) -> None:
    """Throttles the unauthenticated forgot-password and reset-password calls per client address.

    The address is the first `X-Forwarded-For` hop, which a client can spoof when the backend is reached
    directly; the per-account cooldown (`recently_issued`) is the control that holds regardless.
    """
    cfg = get_settings()
    _enforce("public", client_ip, cfg.public_auth_rate_limit_burst, cfg.public_auth_rate_limit_per_minute, "Too many attempts.")


def enforce_send_rate_limit(admin_id: uuid.UUID) -> None:
    """Throttles an administrator sending reset links to other people."""
    cfg = get_settings()
    _enforce(
        "send", admin_id, cfg.credential_reset_send_rate_limit_burst, cfg.credential_reset_send_rate_limit_per_minute,
        "You are sending reset links too fast.",
    )


# --- forced reset ---------------------------------------------------------------------------------------


@dataclass
class ResetScope:
    """Which accounts a forced reset or link batch covers.

    Attributes:
        kind: `all` (every account), `organization` (members of `organization_id`), `user` (one account by
            `email`) or `server_admins`.
        organization_id: For `organization`.
        email: For `user` (case-insensitive).
    """

    kind: Literal["all", "organization", "user", "server_admins"]
    organization_id: uuid.UUID | None = None
    email: str | None = None


def resolve_scope(db: Session, scope: ResetScope) -> list[User]:
    """Lists the accounts in `scope`, ordered by email.

    Args:
        db: Active session.
        scope: The scope to resolve.

    Returns:
        The matching users (any state: inactive and archived accounts are included, because their
        credentials are as suspect as anyone's).

    Raises:
        LookupError: If `organization` names no organisation, or `user` names no account.
        ValueError: If the scope is missing its argument.
    """
    query = select(User).order_by(User.email)
    if scope.kind == "server_admins":
        query = query.where(User.is_server_admin.is_(True))
    elif scope.kind == "organization":
        if scope.organization_id is None:
            raise ValueError("an organisation scope needs an organisation")
        if db.get(Organization, scope.organization_id) is None:
            raise LookupError("organisation not found")
        query = query.where(User.id.in_(select(UserOrgRole.user_id).where(UserOrgRole.organization_id == scope.organization_id)))
    elif scope.kind == "user":
        if not scope.email:
            raise ValueError("a user scope needs an email")
        query = query.where(User.email == scope.email.lower())
    users = list(db.scalars(query))
    if scope.kind == "user" and not users:
        raise LookupError("user not found")
    return users


@dataclass
class ForceResetResult:
    """What a forced reset did.

    Attributes:
        accounts: Accounts in scope.
        marked: Accounts with a local password, now needing a reset before native sign-in.
        sessions_ended: Accounts whose sessions were ended (all in scope).
        tokens_revoked: Personal access tokens revoked.
        two_factor_cleared: Accounts whose 2FA enrolment was cleared.
        sso_only: Emails of accounts without a local credential (listed, never silently skipped).
        emailed: Accounts a link was emailed to.
        email_failed: Accounts a link could not be emailed to.
    """

    accounts: int = 0
    marked: int = 0
    sessions_ended: int = 0
    tokens_revoked: int = 0
    two_factor_cleared: int = 0
    sso_only: list[str] = field(default_factory=list)
    emailed: int = 0
    email_failed: int = 0


def force_reset(
    db: Session,
    users: list[User],
    *,
    scope: ResetScope,
    reset_2fa: bool,
    actor_id: uuid.UUID | None,
    actor_label: str,
    send_links: bool = False,
) -> ForceResetResult:
    """Applies a forced credential reset to `users` in one transaction.

    Effects per account: sessions end (`token_version` +1); a local password is marked as needing
    replacement (`must_reset_credentials`); personal access tokens are revoked; with `reset_2fa`, TOTP
    enrolment is cleared. Outstanding reset links are spent, so a link issued before the incident cannot
    be used after it. One audit event records the scope, the actor and counts; it names no secret.

    Args:
        db: Active session; committed by the caller.
        users: The accounts (from `resolve_scope`).
        scope: The scope used, for the audit record.
        reset_2fa: Also clear TOTP enrolment.
        actor_id: The administrator, or `None` for the command line.
        actor_label: `cli:<os user>` or `user:<id>`, recorded in the audit detail.
        send_links: Email a fresh link to each account that can use one.

    Returns:
        The counts and the list of accounts without a local credential.
    """
    now = datetime.now(UTC)
    result = ForceResetResult(accounts=len(users))
    ids = [u.id for u in users]
    if ids:
        db.execute(
            update(CredentialResetToken)
            .where(CredentialResetToken.user_id.in_(ids), CredentialResetToken.used_at.is_(None))
            .values(used_at=now)
        )
        result.tokens_revoked = revoke_matching(db, PersonalAccessToken.user_id.in_(ids))
    for user in users:
        user.token_version += 1
        result.sessions_ended += 1
        if has_local_credential(user):
            user.must_reset_credentials = True
            result.marked += 1
            if reset_2fa and (user.is_2fa_enabled or user.totp_secret):
                user.is_2fa_enabled = False
                user.totp_secret = None
                user.failed_2fa_attempts = 0
                user.failed_2fa_locked_until = None
                result.two_factor_cleared += 1
        else:
            result.sso_only.append(user.email)
    log_event(
        db,
        entity_type="credential_reset",
        entity_id=uuid.uuid4(),
        action="credentials_force_reset",
        actor_id=actor_id,
        organization_id=scope.organization_id,
        detail={
            "actor": actor_label, "scope": scope.kind, "reset_2fa": reset_2fa,
            "accounts": result.accounts, "marked": result.marked, "tokens_revoked": result.tokens_revoked,
            "two_factor_cleared": result.two_factor_cleared, "without_local_credential": len(result.sso_only),
        },
    )
    db.flush()
    if send_links:
        for user in users:
            if not can_reset_by_link(db, user):
                continue
            raw, minutes = issue_token(db, user, via="cli" if actor_id is None else "admin", issued_by=actor_id)
            try:
                send_reset_email(db, user, raw, minutes, kind="forced")
                result.emailed += 1
            except Exception:  # noqa: BLE001 - one undeliverable address must not undo the reset for everyone
                delete_unsent_token(db, raw)
                result.email_failed += 1
    return result


def issue_links(db: Session, users: list[User], *, actor_label: str, ttl_minutes: int | None = None) -> tuple[list[tuple[str, str]], list[str]]:
    """Issues a link for each account that can use one, for the command line to print to the operator.

    Args:
        db: Active session; committed by the caller.
        users: The accounts.
        actor_label: `cli:<os user>`, recorded in the audit detail.
        ttl_minutes: Lifetime override, up to `MAX_TTL_MINUTES`.

    Returns:
        `(links, skipped)`: `(email, url)` pairs, and the emails that cannot use a link (SSO, inactive).
        One audit event per account records that a link was issued (never the link).
    """
    links: list[tuple[str, str]] = []
    skipped: list[str] = []
    for user in users:
        if not can_reset_by_link(db, user):
            skipped.append(user.email)
            continue
        raw, minutes = issue_token(db, user, via="cli", ttl_minutes=ttl_minutes)
        links.append((user.email, reset_url(raw)))
        log_event(
            db, entity_type="user", entity_id=user.id, action="password_reset_link_issued", actor_id=None,
            detail={"actor": actor_label, "via": "cli", "expires_minutes": minutes},
        )
    return links, skipped
