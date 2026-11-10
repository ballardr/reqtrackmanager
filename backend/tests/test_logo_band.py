"""The logo band colour: a validated `#rrggbb` setting at platform and organisation level, resolved by one function
(organisation, then platform, then the application top bar colour) and drawn behind the organisation logo on the login
page lookup, in outgoing email and (only when chosen) on reports, as a plate composited into the picture itself."""

import io
import re
import uuid
from pathlib import Path

import pytest
from PIL import Image as PilImage

from app.database import SessionLocal
from app.models.organization import Organization
from app.services.branding import (
    DEFAULT_LOGO_BAND_HEX,
    explicit_logo_band_hex,
    get_server_settings,
    logo_band_hex,
    logo_band_text_hex,
)
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_email
from app.services.logo_plate import plate_raster_bytes, plate_resolved
from app.services.report_document import resolve_branding
from app.services.report_images import ResolvedImage, load_org_logo
from tests.conftest import auth_headers, create_org_admin_in

PLATFORM_URL = "/api/v1/system/branding"
BAD_COLOURS = ["red", "#12345", "#12345g", "url(x)", "#1234567", "rgb(0,0,0)"]


def _white_logo() -> bytes:
    """A 40 x 20 white logo on a transparent background, as PNG."""
    image = PilImage.new("RGBA", (40, 20), (0, 0, 0, 0))
    for x in range(10, 30):
        for y in range(5, 15):
            image.putpixel((x, y), (255, 255, 255, 255))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _set_platform(client, token, value):
    resp = client.put(PLATFORM_URL, json={"logo_band_color_hex": value}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def platform_band(client, admin_token):
    """Leaves the platform band unset after the test."""
    yield lambda value: _set_platform(client, admin_token, value)
    _set_platform(client, admin_token, None)


@pytest.fixture
def own_org(client, admin_token):
    """A fresh organisation and its administrator's token."""
    org, token = create_org_admin_in(client, admin_token, f"Band Org {uuid.uuid4().hex[:6]}")
    return org["id"], token


def test_the_default_is_unset_at_both_levels(client, admin_token, own_org):
    org_id, org_token = own_org
    assert client.get(PLATFORM_URL).json()["logo_band_color_hex"] is None
    org = client.get(f"/api/v1/orgs/{org_id}", headers=auth_headers(org_token)).json()
    assert org["logo_band_color_hex"] is None


def test_the_platform_value_is_set_read_publicly_and_removed(client, admin_token, platform_band):
    assert platform_band("#112233")["logo_band_color_hex"] == "#112233"
    assert client.get(PLATFORM_URL).json()["logo_band_color_hex"] == "#112233"
    assert platform_band(None)["logo_band_color_hex"] is None


def test_saving_another_platform_field_leaves_the_band_as_it_was(client, admin_token, platform_band):
    platform_band("#112233")
    saved = client.put(PLATFORM_URL, json={"default_header_title": "Band test"}, headers=auth_headers(admin_token)).json()
    assert saved["logo_band_color_hex"] == "#112233"
    client.put(PLATFORM_URL, json={"default_header_title": None}, headers=auth_headers(admin_token))


@pytest.mark.parametrize("value", BAD_COLOURS)
def test_a_value_that_is_not_a_hex_colour_is_rejected(client, admin_token, own_org, value):
    org_id, org_token = own_org
    assert client.put(PLATFORM_URL, json={"logo_band_color_hex": value}, headers=auth_headers(admin_token)).status_code == 422
    resp = client.put(f"/api/v1/orgs/{org_id}/branding", json={"logo_band_color_hex": value}, headers=auth_headers(org_token))
    assert resp.status_code == 422


def test_an_organisation_value_is_set_and_removed_without_touching_other_fields(client, own_org):
    org_id, org_token = own_org
    url = f"/api/v1/orgs/{org_id}/branding"
    client.put(url, json={"header_title": "Acme", "logo_band_color_hex": "#abcdef"}, headers=auth_headers(org_token))
    after = client.put(url, json={"accent_color_hex": "#112233"}, headers=auth_headers(org_token)).json()
    assert after["logo_band_color_hex"] == "#abcdef" and after["header_title"] == "Acme"
    cleared = client.put(url, json={"logo_band_color_hex": None}, headers=auth_headers(org_token)).json()
    assert cleared["logo_band_color_hex"] is None and cleared["header_title"] == "Acme"


def test_resolution_is_organisation_then_platform_then_the_top_bar_colour(client, own_org, platform_band):
    org_id, org_token = own_org
    url = f"/api/v1/orgs/{org_id}/branding"
    with SessionLocal() as db:
        org = db.get(Organization, uuid.UUID(org_id))
        assert org is not None
        platform = get_server_settings(db)
        assert explicit_logo_band_hex(org, platform) is None
        assert logo_band_hex(org, platform) == DEFAULT_LOGO_BAND_HEX
    platform_band("#111111")
    with SessionLocal() as db:
        org, platform = db.get(Organization, uuid.UUID(org_id)), get_server_settings(db)
        assert org is not None
        assert logo_band_hex(org, platform) == "#111111"
        assert logo_band_hex(None, platform) == "#111111"
    client.put(url, json={"logo_band_color_hex": "#222222"}, headers=auth_headers(org_token))
    with SessionLocal() as db:
        org, platform = db.get(Organization, uuid.UUID(org_id)), get_server_settings(db)
        assert org is not None
        assert explicit_logo_band_hex(org, platform) == "#222222"


def test_the_default_equals_the_stylesheets_top_bar_colour():
    css = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "styles" / "theme.css").read_text()
    match = re.search(r"--color-header-bg:\s*(#[0-9a-fA-F]{6})", css)
    assert match is not None
    assert match.group(1).lower() == DEFAULT_LOGO_BAND_HEX.lower()


def test_the_public_login_lookup_returns_the_resolved_band_and_nothing_private(client, admin_token, own_org, platform_band):
    org_id, org_token = own_org
    slug = f"band-{uuid.uuid4().hex[:8]}"
    client.put(f"/api/v1/orgs/{org_id}/sso-config", json={"slug": slug}, headers=auth_headers(org_token))
    url = f"/api/v1/orgs/by-slug/{slug}/login-info"
    assert client.get(url).json()["logo_band_color_hex"] == DEFAULT_LOGO_BAND_HEX
    platform_band("#333333")
    assert client.get(url).json()["logo_band_color_hex"] == "#333333"
    client.put(f"/api/v1/orgs/{org_id}/branding", json={"logo_band_color_hex": "#444444"}, headers=auth_headers(org_token))
    body = client.get(url).json()
    assert body["logo_band_color_hex"] == "#444444"
    assert "oidc_client_secret" not in body


def _banner_cell(html: str) -> str:
    match = re.search(r'<td align="center" bgcolor="[^"]*" style="[^"]*">', html)
    assert match is not None
    return match.group(0)


def test_the_email_banner_uses_the_band_for_an_organisation_the_platform_and_the_default(client, own_org, platform_band):
    org_id, org_token = own_org

    def render(organization_id):
        with SessionLocal() as db:
            branding = resolve_email_branding(db, organization_id=organization_id)
        return render_email("test_email", branding=branding, source_description="a test", cta_url="https://example.com")[0]

    default = render(uuid.UUID(org_id))
    assert f'bgcolor="{DEFAULT_LOGO_BAND_HEX}"' in _banner_cell(default)
    assert f"background-color: {DEFAULT_LOGO_BAND_HEX}" in _banner_cell(default)
    platform_band("#ffffff")
    platform_only = render(None)
    assert 'bgcolor="#ffffff"' in _banner_cell(platform_only)
    # Black text on a white band: the title colour follows the contrast rule.
    assert "color: #000000; font-size: 18px" in platform_only
    client.put(f"/api/v1/orgs/{org_id}/branding", json={"logo_band_color_hex": "#102030"}, headers=auth_headers(org_token))
    assert 'bgcolor="#102030"' in _banner_cell(render(uuid.UUID(org_id)))
    assert "color: #ffffff; font-size: 18px" in render(uuid.UUID(org_id))


def test_a_raster_logo_is_centred_on_a_plate_of_the_colour():
    plated = PilImage.open(io.BytesIO(plate_raster_bytes(_white_logo(), "#14161c"))).convert("RGB")
    assert plated.size[0] > 40 and plated.size[1] > 20
    assert plated.getpixel((0, 0)) == (0x14, 0x16, 0x1C)
    assert plated.getpixel((plated.size[0] // 2, plated.size[1] // 2)) == (255, 255, 255)


@pytest.mark.parametrize("bad", ["red", "#12345", "url(x)"])
def test_an_invalid_colour_leaves_the_logo_as_it_was(bad):
    logo = _white_logo()
    assert plate_raster_bytes(logo, bad) is logo
    image = ResolvedImage(data=logo, width_px=40, height_px=20)
    assert plate_resolved(image, bad) is image


def test_an_unreadable_logo_is_returned_unchanged():
    assert plate_raster_bytes(b"not an image", "#14161c") == b"not an image"


def test_a_resolved_raster_reports_its_new_size():
    image = plate_resolved(ResolvedImage(data=_white_logo(), width_px=40, height_px=20), "#14161c")
    assert image.width_px > 40 and image.height_px > 20


def test_an_svg_logo_gets_a_rectangle_behind_it_and_a_larger_view_box():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" width="200" height="100"><circle cx="50" cy="25" r="20" fill="#fff"/></svg>'
    plated = plate_resolved(ResolvedImage(svg=svg), "#14161c").svg
    assert plated is not None
    assert 'fill="#14161c"' in plated and "<rect" in plated
    assert plated.index("<rect") < plated.index("<circle")
    assert 'viewBox="-15 -15 130 80"' in plated
    assert 'width="260"' in plated and 'height="160"' in plated


def test_an_svg_without_a_size_is_left_alone():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="5" cy="5" r="2"/></svg>'
    assert plate_resolved(ResolvedImage(svg=svg), "#14161c").svg == svg


def _upload_logo(client, token, org_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/branding-image", data={"kind": "logo"},
        files={"file": ("logo.png", _white_logo(), "image/png")}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return uuid.UUID(resp.json()["logo_file_id"])


def test_reports_draw_a_band_only_when_one_is_chosen(client, own_org, platform_band):
    org_id, org_token = own_org
    logo_id = _upload_logo(client, org_token, org_id)
    with SessionLocal() as db:
        org = db.get(Organization, uuid.UUID(org_id))
        assert org is not None
        unset = resolve_branding(db, org)
        assert unset is not None and unset.logo_bytes is not None
        assert PilImage.open(io.BytesIO(unset.logo_bytes)).size == (40, 20)  # as stored: no band
        layout_logo, _ = load_org_logo(db, logo_id, org.id, explicit_logo_band_hex(org, get_server_settings(db)))
        assert layout_logo is not None and (layout_logo.width_px, layout_logo.height_px) == (40, 20)

    client.put(f"/api/v1/orgs/{org_id}/branding", json={"logo_band_color_hex": "#102030"}, headers=auth_headers(org_token))
    with SessionLocal() as db:
        org = db.get(Organization, uuid.UUID(org_id))
        assert org is not None
        platform = get_server_settings(db)
        branding = resolve_branding(db, org)
        assert branding is not None and branding.logo_bytes is not None
        plated = PilImage.open(io.BytesIO(branding.logo_bytes)).convert("RGB")
        assert plated.getpixel((0, 0)) == (0x10, 0x20, 0x30)
        band = explicit_logo_band_hex(org, platform)
        assert band == "#102030"
        layout_logo, _ = load_org_logo(db, logo_id, org.id, band)
        assert layout_logo is not None and layout_logo.width_px > 40
        # A library picture is the author's own and is not plated: only `load_org_logo` takes a colour.
        not_plated, _ = load_org_logo(db, logo_id, org.id)
        assert not_plated is not None and not_plated.width_px == 40


def test_the_platform_band_applies_to_an_organisation_with_none_of_its_own(client, own_org, platform_band):
    org_id, org_token = own_org
    _upload_logo(client, org_token, org_id)
    platform_band("#050607")
    with SessionLocal() as db:
        org = db.get(Organization, uuid.UUID(org_id))
        assert org is not None
        branding = resolve_branding(db, org)
        assert branding is not None and branding.logo_bytes is not None
        assert PilImage.open(io.BytesIO(branding.logo_bytes)).convert("RGB").getpixel((0, 0)) == (5, 6, 7)


def test_the_band_travels_in_the_organisation_bundle(client, admin_token, own_org):
    org_id, org_token = own_org
    client.put(f"/api/v1/orgs/{org_id}/branding", json={"logo_band_color_hex": "#a1b2c3"}, headers=auth_headers(org_token))
    exported = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(org_token))
    assert exported.status_code == 200, exported.text
    imported = client.post(
        "/api/v1/orgs/import", data={"name": f"Band Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    with SessionLocal() as db:
        copy = db.get(Organization, uuid.UUID(imported.json()["organization"]["id"]))
        assert copy is not None and copy.logo_band_color_hex == "#a1b2c3"


def test_a_bundle_with_a_bad_band_colour_imports_without_it(client, admin_token, own_org):
    import json
    import zipfile

    org_id, org_token = own_org
    exported = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(org_token))
    source = zipfile.ZipFile(io.BytesIO(exported.content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "org.json":
                document = json.loads(data)
                document["logo_band_color_hex"] = "red; background:url(x)"
                data = json.dumps(document).encode()
            target.writestr(name, data)
    imported = client.post(
        "/api/v1/orgs/import", data={"name": f"Bad Band {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", out.getvalue(), "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    with SessionLocal() as db:
        copy = db.get(Organization, uuid.UUID(imported.json()["organization"]["id"]))
        assert copy is not None and copy.logo_band_color_hex is None


@pytest.mark.parametrize("fmt", ["pdf", "docx", "odt", "html"])
def test_a_plated_logo_renders_in_every_report_format(fmt):
    """The plate is part of the picture, so each renderer draws it as any other image, raster or vector."""
    from app.services.report_model import Image, ReportDocument
    from app.services.report_render import RenderInput, render

    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><circle cx="50" cy="25" r="20" fill="#ffffff"/></svg>'
    raster = plate_resolved(ResolvedImage(data=_white_logo(), width_px=40, height_px=20), "#14161c")
    vector = plate_resolved(ResolvedImage(svg=svg), "#14161c")
    document = ReportDocument(
        title="Band", blocks=[Image(raster.data, alt="", decorative=True), Image(b"", svg=vector.svg, alt="", decorative=True)],
    )
    out = render(fmt, "document", RenderInput("Band", document=document))
    assert len(out.content) > 500
    if fmt == "html":
        assert b"data:image/png" in out.content
        assert b"<svg" in out.content and b'fill="#14161c"' in out.content  # the vector logo keeps its plate


def test_the_title_colour_is_chosen_or_follows_contrast_and_is_set_removed_and_validated(client, admin_token, own_org, platform_band):
    org_id, org_token = own_org
    url = f"/api/v1/orgs/{org_id}/branding"

    def resolved():
        with SessionLocal() as db:
            org = db.get(Organization, uuid.UUID(org_id))
            assert org is not None
            return logo_band_text_hex(org, get_server_settings(db))

    assert client.get(PLATFORM_URL).json()["logo_band_text_color_hex"] is None
    assert resolved() == "#ffffff"  # the default band is dark
    client.put(url, json={"logo_band_color_hex": "#ffffff"}, headers=auth_headers(org_token))
    assert resolved() == "#000000"
    set_platform = client.put(PLATFORM_URL, json={"logo_band_text_color_hex": "#123456"}, headers=auth_headers(admin_token))
    assert set_platform.json()["logo_band_text_color_hex"] == "#123456"
    try:
        assert resolved() == "#123456"
        client.put(url, json={"logo_band_text_color_hex": "#abcdef"}, headers=auth_headers(org_token))
        assert resolved() == "#abcdef"
        after = client.put(url, json={"header_title": "T"}, headers=auth_headers(org_token)).json()
        assert after["logo_band_text_color_hex"] == "#abcdef" and after["logo_band_color_hex"] == "#ffffff"
        assert client.put(url, json={"logo_band_text_color_hex": None}, headers=auth_headers(org_token)).json()["logo_band_text_color_hex"] is None
        assert resolved() == "#123456"
        for bad in BAD_COLOURS:
            assert client.put(url, json={"logo_band_text_color_hex": bad}, headers=auth_headers(org_token)).status_code == 422
            assert client.put(PLATFORM_URL, json={"logo_band_text_color_hex": bad}, headers=auth_headers(admin_token)).status_code == 422
    finally:
        client.put(PLATFORM_URL, json={"logo_band_text_color_hex": None}, headers=auth_headers(admin_token))


def test_the_login_lookup_and_the_email_carry_the_resolved_title_colour(client, own_org):
    org_id, org_token = own_org
    slug = f"band-{uuid.uuid4().hex[:8]}"
    client.put(f"/api/v1/orgs/{org_id}/sso-config", json={"slug": slug}, headers=auth_headers(org_token))
    url = f"/api/v1/orgs/by-slug/{slug}/login-info"
    assert client.get(url).json()["logo_band_text_color_hex"] == "#ffffff"
    client.put(f"/api/v1/orgs/{org_id}/branding", json={"logo_band_text_color_hex": "#ffcc00"}, headers=auth_headers(org_token))
    assert client.get(url).json()["logo_band_text_color_hex"] == "#ffcc00"
    with SessionLocal() as db:
        branding = resolve_email_branding(db, organization_id=uuid.UUID(org_id))
    html = render_email("test_email", branding=branding, source_description="a test", cta_url="https://example.com")[0]
    assert "color: #ffcc00; font-size: 18px" in html


def test_the_title_colour_travels_in_the_bundle(client, admin_token, own_org):
    org_id, org_token = own_org
    client.put(f"/api/v1/orgs/{org_id}/branding", json={"logo_band_text_color_hex": "#a1b2c3"}, headers=auth_headers(org_token))
    exported = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(org_token))
    imported = client.post(
        "/api/v1/orgs/import", data={"name": f"Text Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    with SessionLocal() as db:
        copy = db.get(Organization, uuid.UUID(imported.json()["organization"]["id"]))
        assert copy is not None and copy.logo_band_text_color_hex == "#a1b2c3"
