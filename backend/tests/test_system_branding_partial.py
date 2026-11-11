"""Platform branding is a partial update: the Server details and Branding pages each send only their own fields, so neither
overwrites the other, and the audit event names the fields without their values."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers

URL = "/api/v1/system/branding"


def _put(client, token, body):
    return client.put(URL, json=body, headers=auth_headers(token))


def test_a_field_not_sent_is_left_unchanged(client, admin_token):
    assert _put(client, admin_token, {"default_header_title": "Acme", "email_footer_company_name": "Acme Ltd"}).status_code == 200
    changed = _put(client, admin_token, {"email_footer_website": "https://acme.example"}).json()
    assert changed["default_header_title"] == "Acme"
    assert changed["email_footer_company_name"] == "Acme Ltd"
    assert changed["email_footer_website"] == "https://acme.example"


def test_null_clears_a_text_field_and_the_accent_colour_cannot_be_cleared(client, admin_token):
    _put(client, admin_token, {"default_header_title": "Acme", "accent_color_hex": "#112233"})
    cleared = _put(client, admin_token, {"default_header_title": None}).json()
    assert cleared["default_header_title"] is None
    assert cleared["accent_color_hex"] == "#112233"
    assert _put(client, admin_token, {"accent_color_hex": None}).status_code == 422
    assert _put(client, admin_token, {"accent_color_hex": "red"}).status_code == 422


def test_the_audit_event_lists_the_fields_changed_but_not_their_values(client, admin_token):
    _put(client, admin_token, {"email_footer_address": "1 Secret Street"})
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "branding_updated").order_by(AuditEvent.created_at.desc())
        ).first()
        assert event is not None
        assert event.detail == {"fields": ["email_footer_address"]}


def test_footer_prefix_and_company_id_are_stored_cleared_and_limited(client, admin_token):
    saved = _put(client, admin_token, {"footer_prefix": "Hosted by", "company_id_label": "ABN", "company_id": "12 345 678 901"}).json()
    assert (saved["footer_prefix"], saved["company_id_label"], saved["company_id"]) == ("Hosted by", "ABN", "12 345 678 901")
    # Public read, as the signed-out footer uses it.
    assert client.get(URL).json()["company_id"] == "12 345 678 901"
    cleared = _put(client, admin_token, {"footer_prefix": None, "company_id": None}).json()
    assert cleared["footer_prefix"] is None and cleared["company_id"] is None
    assert cleared["company_id_label"] == "ABN"  # not sent, so unchanged
    assert _put(client, admin_token, {"footer_prefix": "x" * 51}).status_code == 422
    assert _put(client, admin_token, {"company_id": "x" * 101}).status_code == 422
    _put(client, admin_token, {"company_id_label": None})
