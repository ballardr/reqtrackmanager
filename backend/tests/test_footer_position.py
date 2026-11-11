"""The footer position of the signed-out pages: a validated choice at platform level (never cleared) and an organisation
override (null follows the platform), resolved by one function, returned by the public lookups and carried in the
organisation bundle. It is a public presentation value, so the update audit names the field and no value."""

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.organization import Organization
from app.services.branding import DEFAULT_FOOTER_POSITION, FOOTER_POSITIONS, footer_position, get_server_settings
from tests.conftest import auth_headers, create_org_admin_in

PLATFORM_URL = "/api/v1/system/branding"


def _set_platform(client, token, value):
    return client.put(PLATFORM_URL, json={"footer_position": value}, headers=auth_headers(token))


@pytest.fixture
def platform_position(client, admin_token):
    """Returns a setter for the platform value and puts the default back afterwards."""
    yield lambda value: _set_platform(client, admin_token, value)
    _set_platform(client, admin_token, DEFAULT_FOOTER_POSITION)


@pytest.fixture
def own_org(client, admin_token):
    """A fresh organisation and its administrator's token."""
    org, token = create_org_admin_in(client, admin_token, f"Footer Org {uuid.uuid4().hex[:6]}")
    return org["id"], token


def test_the_default_is_after_the_content_and_an_organisation_follows_the_platform(client, own_org):
    org_id, org_token = own_org
    assert client.get(PLATFORM_URL).json()["footer_position"] == "after_content"
    assert client.get(f"/api/v1/orgs/{org_id}", headers=auth_headers(org_token)).json()["footer_position"] is None


def test_the_platform_value_is_set_and_read_publicly(client, platform_position):
    assert platform_position("bottom_of_page").json()["footer_position"] == "bottom_of_page"
    assert client.get(PLATFORM_URL).json()["footer_position"] == "bottom_of_page"


def test_saving_other_platform_fields_leaves_the_position_as_it_was(client, admin_token, platform_position):
    platform_position("bottom_of_page")
    saved = client.put(PLATFORM_URL, json={"default_header_title": "Footer test"}, headers=auth_headers(admin_token)).json()
    assert saved["footer_position"] == "bottom_of_page"
    client.put(PLATFORM_URL, json={"default_header_title": None}, headers=auth_headers(admin_token))


def test_saving_the_position_leaves_other_platform_fields_as_they_were(client, admin_token, platform_position):
    client.put(PLATFORM_URL, json={"default_header_title": "Kept title"}, headers=auth_headers(admin_token))
    assert platform_position("bottom_of_page").json()["default_header_title"] == "Kept title"
    client.put(PLATFORM_URL, json={"default_header_title": None}, headers=auth_headers(admin_token))


@pytest.mark.parametrize("value", ["top", "", "BOTTOM_OF_PAGE", "fixed", None])
def test_an_unknown_or_cleared_platform_value_is_rejected(client, admin_token, platform_position, value):
    assert _set_platform(client, admin_token, value).status_code == 422
    assert client.get(PLATFORM_URL).json()["footer_position"] == "after_content"


def test_only_a_server_administrator_may_set_the_platform_value(client, own_org):
    _org_id, org_token = own_org
    assert _set_platform(client, org_token, "bottom_of_page").status_code == 403


@pytest.mark.parametrize("value", ["top", "", "fixed"])
def test_an_unknown_organisation_value_is_rejected(client, own_org, value):
    org_id, org_token = own_org
    resp = client.put(f"/api/v1/orgs/{org_id}/branding", json={"footer_position": value}, headers=auth_headers(org_token))
    assert resp.status_code == 422


def test_an_organisation_value_is_set_cleared_and_leaves_other_fields_alone(client, own_org):
    org_id, org_token = own_org
    url = f"/api/v1/orgs/{org_id}/branding"
    client.put(url, json={"header_title": "Acme"}, headers=auth_headers(org_token))
    set_ = client.put(url, json={"footer_position": "bottom_of_page"}, headers=auth_headers(org_token)).json()
    assert set_["footer_position"] == "bottom_of_page" and set_["header_title"] == "Acme"
    other = client.put(url, json={"accent_color_hex": "#112233"}, headers=auth_headers(org_token)).json()
    assert other["footer_position"] == "bottom_of_page"
    cleared = client.put(url, json={"footer_position": None}, headers=auth_headers(org_token)).json()
    assert cleared["footer_position"] is None and cleared["header_title"] == "Acme"


def test_resolution_is_organisation_then_platform(client, own_org, platform_position):
    org_id, org_token = own_org
    with SessionLocal() as db:
        org, platform = db.get(Organization, uuid.UUID(org_id)), get_server_settings(db)
        assert org is not None
        assert footer_position(org, platform) == "after_content"
    platform_position("bottom_of_page")
    with SessionLocal() as db:
        org, platform = db.get(Organization, uuid.UUID(org_id)), get_server_settings(db)
        assert footer_position(org, platform) == "bottom_of_page"
        assert footer_position(None, platform) == "bottom_of_page"
    client.put(f"/api/v1/orgs/{org_id}/branding", json={"footer_position": "after_content"}, headers=auth_headers(org_token))
    with SessionLocal() as db:
        org, platform = db.get(Organization, uuid.UUID(org_id)), get_server_settings(db)
        assert footer_position(org, platform) == "after_content"
        assert footer_position(None, platform) == "bottom_of_page"


def test_every_registered_position_is_accepted_at_both_levels(client, admin_token, own_org, platform_position):
    org_id, org_token = own_org
    for value in FOOTER_POSITIONS:
        assert _set_platform(client, admin_token, value).status_code == 200
        resp = client.put(f"/api/v1/orgs/{org_id}/branding", json={"footer_position": value}, headers=auth_headers(org_token))
        assert resp.status_code == 200


def test_the_public_login_lookup_returns_the_resolved_position(client, own_org, platform_position):
    org_id, org_token = own_org
    slug = f"foot-{uuid.uuid4().hex[:8]}"
    client.put(f"/api/v1/orgs/{org_id}/sso-config", json={"slug": slug}, headers=auth_headers(org_token))
    url = f"/api/v1/orgs/by-slug/{slug}/login-info"
    assert client.get(url).json()["footer_position"] == "after_content"
    platform_position("bottom_of_page")
    assert client.get(url).json()["footer_position"] == "bottom_of_page"
    client.put(f"/api/v1/orgs/{org_id}/branding", json={"footer_position": "after_content"}, headers=auth_headers(org_token))
    assert client.get(url).json()["footer_position"] == "after_content"


def test_the_audit_event_names_the_field_and_no_value(client, admin_token, platform_position):
    platform_position("bottom_of_page")
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "branding_updated").order_by(AuditEvent.created_at.desc())
        ).first()
        assert event is not None
        assert event.detail == {"fields": ["footer_position"]}


def test_the_position_travels_in_the_organisation_bundle(client, admin_token, own_org):
    org_id, org_token = own_org
    client.put(f"/api/v1/orgs/{org_id}/branding", json={"footer_position": "bottom_of_page"}, headers=auth_headers(org_token))
    exported = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(org_token))
    assert exported.status_code == 200, exported.text
    imported = client.post(
        "/api/v1/orgs/import", data={"name": f"Footer Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    with SessionLocal() as db:
        copy = db.get(Organization, uuid.UUID(imported.json()["organization"]["id"]))
        assert copy is not None and copy.footer_position == "bottom_of_page"


def test_a_bundle_with_an_unknown_position_imports_without_it(client, admin_token, own_org):
    org_id, org_token = own_org
    exported = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(org_token))
    source = zipfile.ZipFile(io.BytesIO(exported.content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "org.json":
                document = json.loads(data)
                document["footer_position"] = "position: fixed"
                data = json.dumps(document).encode()
            target.writestr(name, data)
    imported = client.post(
        "/api/v1/orgs/import", data={"name": f"Bad Footer {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    with SessionLocal() as db:
        copy = db.get(Organization, uuid.UUID(imported.json()["organization"]["id"]))
        assert copy is not None and copy.footer_position is None


def test_the_migration_adds_and_removes_the_columns_and_defaults_existing_rows():
    """Down to 0169 removes both columns; up to head restores them with the platform row at `after_content` and no
    organisation value. Always upgrades back to head so the shared test database matches the models."""
    from sqlalchemy import text

    from alembic import command
    from app.database import engine
    from tests.conftest import build_alembic_config

    config = build_alembic_config()

    def _columns() -> set[tuple[str, str]]:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE column_name = 'footer_position' AND table_name IN ('server_settings', 'organizations')"
            )).all()
        return {(r[0], r[1]) for r in rows}

    engine.dispose()
    command.downgrade(config, "0169")
    try:
        assert _columns() == set()
    finally:
        command.upgrade(config, "head")
        engine.dispose()
    assert _columns() == {("server_settings", "footer_position"), ("organizations", "footer_position")}
    with SessionLocal() as db:
        assert get_server_settings(db).footer_position == "after_content"
