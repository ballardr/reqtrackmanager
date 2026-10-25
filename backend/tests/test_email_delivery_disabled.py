"""
Module: tests.test_email_delivery_disabled

Pins the `EMAIL_DELIVERY=disabled` kill switch (`services/email.py`): a copy of the platform that must never
reach real recipients, such as the disaster-recovery restore-test stack, sends nothing and opens no
connection whatever `SMTP_HOST` says, including for the organisation test-email action and an explicit
`SmtpOverride`, and a refused send is reported as a failure rather than as a success.
"""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import email as email_service
from app.services.email import EmailDeliveryDisabled, SmtpOverride, send_email_async
from tests.conftest import auth_headers


@pytest.fixture
def smtp_send(monkeypatch):
    """Replaces the SMTP client with a recorder, so a test can see whether a connection would have been made."""
    mock = AsyncMock()
    monkeypatch.setattr(email_service.aiosmtplib, "send", mock)
    return mock


def test_default_delivery_is_smtp():
    assert Settings().email_delivery == "smtp"


def test_unknown_delivery_mode_is_rejected():
    with pytest.raises(ValidationError):
        Settings(email_delivery="sometimes")


@pytest.mark.asyncio
async def test_smtp_mode_sends(monkeypatch, smtp_send):
    monkeypatch.setattr(email_service.settings, "email_delivery", "smtp")
    await send_email_async("someone@example.com", "subject", "body")
    smtp_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_mode_refuses_before_connecting(monkeypatch, smtp_send):
    monkeypatch.setattr(email_service.settings, "email_delivery", "disabled")
    with pytest.raises(EmailDeliveryDisabled):
        await send_email_async("someone@example.com", "subject", "body", html_body="<p>body</p>")
    smtp_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_mode_also_refuses_an_organisation_smtp_override(monkeypatch, smtp_send):
    monkeypatch.setattr(email_service.settings, "email_delivery", "disabled")
    with pytest.raises(EmailDeliveryDisabled):
        await send_email_async("someone@example.com", "subject", "body", smtp_override=SmtpOverride(host="smtp.customer.example"))
    smtp_send.assert_not_awaited()


def test_system_test_email_reports_that_delivery_is_disabled(client, admin_token, monkeypatch, smtp_send):
    monkeypatch.setattr(email_service.settings, "email_delivery", "disabled")
    resp = client.post("/api/v1/system/test-email", json={}, headers=auth_headers(admin_token))
    assert resp.status_code == 502
    assert "EMAIL_DELIVERY=disabled" in resp.json()["detail"]
    smtp_send.assert_not_awaited()
