"""
Module: services.email

Outgoing email delivery (C-N-03) via SMTP. In development and the bundled
Docker Compose stack this points at MailHog, a local SMTP catcher with a web
UI, so sent mail is genuinely visible during verification rather than only
logged; in production it should point at a real SMTP relay.
"""

from __future__ import annotations

import asyncio
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

settings = get_settings()


async def send_email_async(to: str, subject: str, body: str) -> None:
    """Sends a plain-text email over SMTP.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
    """
    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=settings.smtp_use_tls,
    )


def send_email(to: str, subject: str, body: str) -> None:
    """Synchronous wrapper around `send_email_async` for use in sync route/service code.

    Safe to call from a FastAPI sync route handler, which FastAPI runs in a
    worker thread with no event loop of its own, so starting a fresh one
    here via `asyncio.run` cannot collide with the app's main event loop.
    """
    asyncio.run(send_email_async(to, subject, body))
