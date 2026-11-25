"""
Module: services.email

Outgoing email delivery (C-N-03) via SMTP. Development and the bundled Docker Compose stack point at
MailHog, a local SMTP catcher, so sent mail is visible during verification; production points at a real relay.

Design decisions:
- `send_email`/`send_email_async` use the deployment-wide `Settings.smtp_*` (`config.py`) unless given an
  explicit `SmtpOverride`. The organisation "send test email" action (`routers/orgs.py`) is the one use of an
  organisation's own `Organization.smtp_*`; notifications, digests and disk-space alerts always use the
  deployment relay.
- Every send is `multipart/alternative` (plain text, then HTML) built with stdlib `EmailMessage`
  (`set_content`, `add_alternative`); an inline branding logo is embedded with `add_related` as a `cid:`
  attachment, so mail never depends on an externally hosted image (bodies come from
  `services/email_templates.py`).
- `Settings.email_delivery == "disabled"` is a deployment-wide kill switch for copies that must not contact
  anyone (the disaster-recovery restore-test stack): every send, including the test-email action and an
  explicit `SmtpOverride`, raises `EmailDeliveryDisabled` before any connection opens. The error is the honest
  signal: notifications are not marked as emailed and the test-email actions report why nothing was sent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

settings = get_settings()

InlineImages = Mapping[str, tuple[bytes, str | None]]  # cid -> (data, content type; None falls back to octet-stream)
"""Maps a `cid:` name (e.g. `"brand_logo"`, referenced in HTML as
`src="cid:brand_logo"`) to `(raw_bytes, content_type)`."""


class EmailDeliveryDisabled(RuntimeError):
    """Raised instead of sending when `EMAIL_DELIVERY=disabled`; nothing was sent and no connection was made."""


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

    Raises:
        EmailDeliveryDisabled: If `EMAIL_DELIVERY=disabled`; nothing was sent.
    """
    if settings.email_delivery == "disabled":
        raise EmailDeliveryDisabled("email delivery is disabled on this deployment (EMAIL_DELIVERY=disabled)")
    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    if html_body is not None:
        message.add_alternative(html_body, subtype="html")
        html_part = message.get_body(("html",))
        if html_part is None:  # `add_alternative` just added it
            raise RuntimeError("The HTML alternative is missing from the message.")
        for cid, (data, content_type) in (inline_images or {}).items():
            maintype, _, subtype = (content_type or "").partition("/")
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
    Called from code that runs on an event loop (an `async` route), `asyncio.run` would refuse
    and the message would be dropped, so the send runs on a worker thread and this waits for it.

    Raises:
        EmailDeliveryDisabled: Delivery is switched off for the deployment.
        Exception: Whatever the SMTP exchange raises, unchanged.
    """

    def deliver() -> None:
        asyncio.run(
            send_email_async(
                to, subject, body, html_body=html_body, inline_images=inline_images, smtp_override=smtp_override
            )
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        deliver()
        return
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(deliver).result()
