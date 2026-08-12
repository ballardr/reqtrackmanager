"""
Module: services.email

Outgoing email delivery (C-N-03) via SMTP. In development and the bundled
Docker Compose stack this points at MailHog, a local SMTP catcher with a web
UI, so sent mail is genuinely visible during verification rather than only
logged; in production it should point at a real SMTP relay.

`send_email`/`send_email_async` always use the deployment-wide `Settings.
smtp_*` (`config.py`) unless called with an explicit `SmtpOverride` — the
one exception being the organisation-scoped "send test email" action
(`routers/orgs.py`), which exercises an org's own `Organization.smtp_*`
override on demand. Everything else (notifications, digests, disk-space
alerts) always goes through the deployment-wide relay.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

settings = get_settings()


@dataclass
class SmtpOverride:
    """A per-call SMTP connection override, used only by the organisation-
    scoped "send test email" action (`routers/orgs.py::send_org_test_email`)
    to exercise an org's own configured relay (`Organization.smtp_*`)
    instead of the deployment-wide one. `port`/`username`/`password` may be
    `None` (an unset org field) — `aiosmtplib.send` already applies sensible
    per-field defaults (e.g. picking 587/465/25 for `port` based on
    `use_tls`) the same way it does for the deployment-wide config below, so
    no further fallback is needed here.

    Deliberately all-or-nothing rather than merged field-by-field with the
    deployment-wide `Settings`: mixing, say, an org's own host with the
    deployment's mailhog port would silently produce a nonsensical
    connection target.
    """

    host: str
    port: int | None = None
    username: str | None = None
    password: str | None = None
    use_tls: bool = True


async def send_email_async(to: str, subject: str, body: str, *, smtp_override: SmtpOverride | None = None) -> None:
    """Sends a plain-text email over SMTP.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
        smtp_override: When given, connects using these settings instead of
            the deployment-wide `Settings.smtp_*` — see `SmtpOverride`.
            Ordinary notification email (`services/notifications.py`) never
            passes this, and so always uses the deployment-wide SMTP_HOST;
            see docs/decisions.md's "SMTP/SSO organisation settings are a
            storage-only seam" entry for why.
    """
    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=smtp_override.host if smtp_override else settings.smtp_host,
        port=smtp_override.port if smtp_override else settings.smtp_port,
        username=smtp_override.username if smtp_override else settings.smtp_username,
        password=smtp_override.password if smtp_override else settings.smtp_password,
        start_tls=smtp_override.use_tls if smtp_override else settings.smtp_use_tls,
    )


def send_email(to: str, subject: str, body: str, *, smtp_override: SmtpOverride | None = None) -> None:
    """Synchronous wrapper around `send_email_async` for use in sync route/service code.

    Safe to call from a FastAPI sync route handler, which FastAPI runs in a
    worker thread with no event loop of its own, so starting a fresh one
    here via `asyncio.run` cannot collide with the app's main event loop.
    """
    asyncio.run(send_email_async(to, subject, body, smtp_override=smtp_override))
