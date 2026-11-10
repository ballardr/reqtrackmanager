"""Organisation branding is a partial update: the Organisation details and Branding & defaults pages each send only their own
fields, so neither overwrites the other, and the audit event names the fields without their values."""

from uuid import UUID

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.services.email_branding import resolve_email_branding
from tests.conftest import auth_headers

#: Every clearable field of the endpoint with a value that is valid for it.
CLEARABLE = {
    "accent_color_hex": "#112233",
    "logo_band_color_hex": "#102030",
    "logo_band_text_color_hex": "#f0e0d0",
    "report_accent_color_hex": "#445566",
    "header_title": "Acme Requirements",
    "email_footer_company_name": "Acme Ltd",
    "email_footer_website": "https://acme.example",
    "email_footer_address": "1 Example Street",
}


def _put(client, token, org_id, body):
    return client.put(f"/api/v1/orgs/{org_id}/branding", json=body, headers=auth_headers(token))


@pytest.fixture
def seeded(client, admin_token, org_id):
    """Sets every field, then restores the organisation to the unset state afterwards."""
    resp = _put(client, admin_token, org_id, {**CLEARABLE, "report_include_logo": False})
    assert resp.status_code == 200, resp.text
    yield org_id
    _put(client, admin_token, org_id, {**{name: None for name in CLEARABLE}, "report_include_logo": True})


@pytest.mark.parametrize("field", sorted(CLEARABLE))
def test_saving_one_field_leaves_every_other_field_as_it_was(client, admin_token, seeded, field):
    other = next(name for name in sorted(CLEARABLE) if name != field)
    new_value = "#778899" if field.endswith("hex") else "Changed"
    saved = _put(client, admin_token, seeded, {field: new_value}).json()
    assert saved[field] == new_value
    for name, value in CLEARABLE.items():
        if name != field:
            assert saved[name] == value, f"{name} was altered by a save of {field}"
    assert saved["report_include_logo"] is False
    assert saved[other] == CLEARABLE[other]


@pytest.mark.parametrize("field", sorted(CLEARABLE))
def test_null_still_clears_the_field_it_names_and_only_that_field(client, admin_token, seeded, field):
    saved = _put(client, admin_token, seeded, {field: None}).json()
    assert saved[field] is None
    for name, value in CLEARABLE.items():
        if name != field:
            assert saved[name] == value


def test_a_blank_string_clears_a_text_field(client, admin_token, seeded):
    saved = _put(client, admin_token, seeded, {"email_footer_address": "   "}).json()
    assert saved["email_footer_address"] is None
    assert saved["email_footer_company_name"] == "Acme Ltd"


def test_an_empty_request_changes_nothing(client, admin_token, seeded):
    saved = _put(client, admin_token, seeded, {}).json()
    assert {name: saved[name] for name in CLEARABLE} == CLEARABLE
    assert saved["report_include_logo"] is False


def test_the_report_colour_scheme_and_logo_switch_are_left_alone_when_not_sent(client, admin_token, seeded):
    scheme = [{"name": "brand", "colour": "#123456"}]
    first = _put(client, admin_token, seeded, {"report_colour_scheme": scheme})
    assert first.status_code == 200, first.text
    saved = _put(client, admin_token, seeded, {"header_title": "Other"}).json()
    assert saved["report_colour_scheme"] == first.json()["report_colour_scheme"]
    assert saved["report_include_logo"] is False
    assert _put(client, admin_token, seeded, {"report_colour_scheme": []}).json()["report_colour_scheme"] is None


def test_the_email_footer_resolves_from_the_saved_details_and_falls_back_when_emptied(client, admin_token, seeded):
    def resolved():
        with SessionLocal() as db:
            return resolve_email_branding(db, organization_id=UUID(seeded))

    assert resolved().footer_company_name == "Acme Ltd"
    # Saving the appearance fields alone must not disturb the footer.
    assert _put(client, admin_token, seeded, {"accent_color_hex": "#abcdef", "header_title": None}).status_code == 200
    assert resolved().footer_company_name == "Acme Ltd"
    assert _put(client, admin_token, seeded, {"email_footer_company_name": None}).status_code == 200
    assert resolved().footer_company_name != "Acme Ltd"


def test_the_audit_event_lists_the_fields_changed_but_not_their_values(client, admin_token, seeded):
    _put(client, admin_token, seeded, {"email_footer_address": "9 Secret Street", "header_title": None})
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "branding_updated", AuditEvent.entity_type == "organization")
            .order_by(AuditEvent.created_at.desc())
        ).first()
        assert event is not None
        assert event.detail == {"fields": ["email_footer_address", "header_title"]}
        assert "Secret" not in str(event.detail)
