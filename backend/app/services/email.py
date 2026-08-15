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

Every send is a `multipart/alternative` message (plain text first, HTML
second) built with stdlib `email.message.EmailMessage` — `set_content` for
the text part, `add_alternative` for the HTML part, and `add_related` to
embed an inline branding logo (if any) as a `multipart/related` `cid:`
attachment under the HTML part, so outgoing mail never depends on loading
an externally-hosted image (see `services/email_templates.py` for how the
HTML/text bodies themselves are rendered).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

settings = get_settings()

InlineImages = dict[str, tuple[bytes, str]]
"""Maps a `cid:` name (e.g. `"brand_logo"`, referenced in HTML as
`src="cid:brand_logo"`) to `(raw_bytes, content_type)`."""


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


async def send_email_async(
    to: str,
    subject: str,
    body: str,
    *,
    html_body: str | None = None,
    inline_images: InlineImages | None = None,
    smtp_override: SmtpOverride | None = None,
) -> None:
    """Sends an email over SMTP — plain text only, or `multipart/
    alternative` text+HTML when `html_body` is given.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body (always sent; the fallback for clients
            that can't or won't render HTML).
        html_body: Optional HTML email body (`services/email_templates.py`).
            When given, sent as the `multipart/alternative` HTML part.
        inline_images: Optional `cid:`-referenced images to embed under the
            HTML part (see `InlineImages`) — ignored if `html_body` is
            `None`, since a plain-text body has nothing to embed them into.
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

    if html_body is not None:
        message.add_alternative(html_body, subtype="html")
        html_part = message.get_payload()[1]
        for cid, (data, content_type) in (inline_images or {}).items():
            maintype, _, subtype = content_type.partition("/")
            html_part.add_related(data, maintype=maintype or "application", subtype=subtype or "octet-stream", cid=f"<{cid}>")

    await aiosmtplib.send(
        message,
        hostname=smtp_override.host if smtp_override else settings.smtp_host,
        port=smtp_override.port if smtp_override else settings.smtp_port,
        username=smtp_override.username if smtp_override else settings.smtp_username,
        password=smtp_override.password if smtp_override else settings.smtp_password,
        start_tls=smtp_override.use_tls if smtp_override else settings.smtp_use_tls,
    )


def send_email(
    to: str,
    subject: str,
    body: str,
    *,
    html_body: str | None = None,
    inline_images: InlineImages | None = None,
    smtp_override: SmtpOverride | None = None,
) -> None:
    """Synchronous wrapper around `send_email_async` for use in sync route/service code.

    Safe to call from a FastAPI sync route handler, which FastAPI runs in a
    worker thread with no event loop of its own, so starting a fresh one
    here via `asyncio.run` cannot collide with the app's main event loop.
    """
    asyncio.run(
        send_email_async(
            to, subject, body, html_body=html_body, inline_images=inline_images, smtp_override=smtp_override
        )
    )
