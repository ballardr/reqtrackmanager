"""`PUT /orgs/{id}/advanced-settings` is a partial update: a field the client does not send is left as it is.

The organisation settings page saves email, security and report configuration with separate Save buttons, each
sending only its own group's fields, so a Save in one group must never reset another group's values to defaults.
"""

import pytest

from app.routers.orgs import settings as orgs_settings_router
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _smtp_host_resolves_publicly(monkeypatch):
    monkeypatch.setattr(orgs_settings_router, "assert_public_host", lambda host: None)


def _put(client, token, org_id, body):
    resp = client.put(f"/api/v1/orgs/{org_id}/advanced-settings", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_saving_one_group_leaves_the_other_groups_unchanged(client, admin_token, org_id):
    _put(client, admin_token, org_id, {
        "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_username": "relay", "smtp_use_tls": False,
        "force_require_change_request_for_approved_links": True, "external_user_policy": "anyone", "auto_accept_email_domain": "Example.com",
        "pat_max_lifetime_days": 30, "report_footer_text": "Confidential", "report_include_cover_page": False,
    })

    # Email group only.
    after_email = _put(client, admin_token, org_id, {"smtp_host": "mail.example.com", "smtp_port": 25, "smtp_username": None, "smtp_use_tls": True})
    assert (after_email["smtp_host"], after_email["smtp_port"], after_email["smtp_username"], after_email["smtp_use_tls"]) == (
        "mail.example.com", 25, None, True,
    )
    assert after_email["force_require_change_request_for_approved_links"] is True
    assert after_email["external_user_policy"] == "anyone"
    assert after_email["auto_accept_email_domain"] == "example.com"
    assert after_email["pat_max_lifetime_days"] == 30
    assert after_email["report_footer_text"] == "Confidential" and after_email["report_include_cover_page"] is False

    # Security group only.
    after_security = _put(client, admin_token, org_id, {"force_require_change_request_for_approved_links": False, "pat_max_lifetime_days": None})
    assert after_security["force_require_change_request_for_approved_links"] is False and after_security["pat_max_lifetime_days"] is None
    assert after_security["smtp_host"] == "mail.example.com" and after_security["smtp_port"] == 25
    assert after_security["external_user_policy"] == "anyone"

    # An explicit null still clears a nullable field.
    cleared = _put(client, admin_token, org_id, {"report_footer_text": None, "auto_accept_email_domain": None})
    assert cleared["report_footer_text"] is None and cleared["auto_accept_email_domain"] is None
    assert cleared["smtp_host"] == "mail.example.com"


def test_an_empty_body_changes_nothing(client, admin_token, org_id):
    before = _put(client, admin_token, org_id, {"force_require_change_request_for_approved_links": True, "smtp_host": "smtp.example.com"})
    assert _put(client, admin_token, org_id, {}) == before


def test_the_audit_event_names_the_fields_sent_and_never_their_values(client, admin_token, org_id):
    from app.database import SessionLocal
    from app.models.audit import AuditEvent

    _put(client, admin_token, org_id, {"smtp_host": "smtp.example.com", "smtp_password": "top-secret"})
    db = SessionLocal()
    try:
        event = (
            db.query(AuditEvent)
            .filter(AuditEvent.action == "advanced_settings_updated", AuditEvent.entity_id == str(org_id))
            .order_by(AuditEvent.created_at.desc())
            .first()
        )
        assert event is not None
        assert event.detail == {"fields": ["smtp_host", "smtp_password"]}
        assert "top-secret" not in str(event.detail)
    finally:
        db.close()
