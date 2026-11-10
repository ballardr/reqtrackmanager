"""Tests for the HTML email template system
(`services/email_branding.py::resolve_email_branding`,
`services/email_templates.py::render_email`/`render_page`): branding
resolution, dark-mode support, non-empty plain-text fallbacks, and —
because Jinja2 has a real history of autoescape-bypass/XSS CVEs (see
docs/decisions.md's "HTML email template system" entry) — a dedicated
regression test proving every org-/user-supplied value actually reaching
these templates is escaped in the rendered HTML output, not just assumed
to be.
"""

from uuid import UUID

from app.database import SessionLocal
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_email, render_page
from tests.conftest import auth_headers

XSS_HEADER_TITLE = "<script>alert('header')</script>"
XSS_COMPANY_NAME = 'Acme "Corp" <img src=x onerror=alert(1)>'
XSS_ADDRESS = "1 Fake St\n<script>alert('address')</script>"
XSS_NOTIFICATION_TITLE = "<img src=x onerror=alert('title')>"


def test_notification_email_escapes_org_and_notification_supplied_content(client, admin_token, org_id):
    # Round-trip through the real branding endpoint, so this exercises the
    # actual stored/reloaded values rather than a hand-built dataclass.
    resp = client.put(
        f"/api/v1/orgs/{org_id}/branding",
        json={
            "accent_color_hex": None, "header_title": XSS_HEADER_TITLE,
            "email_footer_company_name": XSS_COMPANY_NAME, "email_footer_website": None,
            "email_footer_address": XSS_ADDRESS,
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    try:
        branding = resolve_email_branding(db, organization_id=UUID(org_id))
    finally:
        db.close()

    html, text = render_email(
        "notification", branding=branding, unsubscribe_url="https://example.com/unsub?token=abc",
        title=XSS_NOTIFICATION_TITLE, body_text="ordinary notification body", cta_url="https://example.com/projects/1",
    )

    for payload in (XSS_HEADER_TITLE, XSS_COMPANY_NAME, XSS_ADDRESS, XSS_NOTIFICATION_TITLE):
        assert payload not in html, f"unescaped payload leaked into rendered HTML: {payload!r}"
    assert "&lt;script&gt;alert(&#39;header&#39;)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "1 Fake St<br" in html  # nl2br: newline became <br>, payload after it still escaped
    assert "&lt;script&gt;alert(&#39;address&#39;)&lt;/script&gt;" in html

    # The plain-text part has no markup to escape into — raw content is fine
    # there (a text/plain body can't execute a <script> tag in any client).
    assert "ordinary notification body" in text
    assert text.strip()


def test_base_layout_declares_dark_mode_support(client, admin_token, org_id):
    db = SessionLocal()
    try:
        branding = resolve_email_branding(db, organization_id=UUID(org_id))
    finally:
        db.close()
    html, _ = render_email("test_email", branding=branding, source_description="a test", cta_url="https://example.com")
    assert "prefers-color-scheme: dark" in html
    assert 'name="color-scheme" content="light dark"' in html
    assert 'name="supported-color-schemes" content="light dark"' in html


def test_all_email_templates_render_nonempty_html_and_text(client, admin_token, org_id):
    db = SessionLocal()
    try:
        branding = resolve_email_branding(db, organization_id=UUID(org_id))
    finally:
        db.close()

    cases = [
        ("notification", {"title": "Stage approved", "body_text": "It happened.", "cta_url": "https://example.com/x"}),
        ("digest", {"items": [{"title": "A", "body": "b"}], "cta_url": "https://example.com/notifications"}),
        ("test_email", {"source_description": "a test", "cta_url": "https://example.com"}),
        ("disk_alert", {"usage_percent": 91.2, "threshold_percent": 90, "cta_url": "https://example.com/server"}),
    ]
    for template_name, context in cases:
        html, text = render_email(template_name, branding=branding, unsubscribe_url="https://example.com/unsub", **context)
        assert html.strip(), f"{template_name}.html.jinja rendered empty"
        assert text.strip(), f"{template_name}.txt.jinja rendered empty"
        assert "<html" in html.lower()


def test_unsubscribe_confirmation_page_renders_for_success_and_failure(client, admin_token, org_id):
    db = SessionLocal()
    try:
        branding = resolve_email_branding(db, organization_id=None)
    finally:
        db.close()
    for success in (True, False):
        html = render_page("unsubscribe_confirmation", branding=branding, success=success, cta_url="https://example.com/preferences")
        assert html.strip()
        assert "<html" in html.lower()


def test_platform_branding_falls_back_to_built_in_product_name_when_unset(client, admin_token):
    db = SessionLocal()
    try:
        branding = resolve_email_branding(db, organization_id=None)
    finally:
        db.close()
    # No PUT /system/branding has set email_footer_company_name in this
    # test's fresh database, so it must fall back rather than render blank.
    assert branding.footer_company_name == "ReqTrackManager"


def _platform_footer(client, admin_token, **fields):
    resp = client.put("/api/v1/system/branding", json=fields, headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text


def test_platform_prefix_and_company_id_appear_in_the_email_footer(client, admin_token):
    _platform_footer(client, admin_token, email_footer_company_name="Host Pty Ltd", footer_prefix="Hosted by",
                     company_id_label="ABN", company_id="12 345 678 901")
    try:
        db = SessionLocal()
        try:
            branding = resolve_email_branding(db, organization_id=None)
        finally:
            db.close()
        assert branding.footer_prefix == "Hosted by"
        assert branding.footer_company_id == "ABN 12 345 678 901"
        html, text = render_email("notification", branding=branding, unsubscribe_url=None, title="t", body_text="b", cta_url=None)
        assert "Hosted by Host Pty Ltd" in html and "ABN 12 345 678 901" in html
        assert "&copy;" not in html  # the operator hosts the service; it is not the copyright holder
        assert "Hosted by Host Pty Ltd" in text and "ABN 12 345 678 901" in text
    finally:
        _platform_footer(client, admin_token, email_footer_company_name=None, footer_prefix=None, company_id_label=None, company_id=None)


def test_company_id_has_no_label_when_none_is_set_and_needs_a_value(client, admin_token):
    _platform_footer(client, admin_token, company_id="99", company_id_label=None)
    try:
        db = SessionLocal()
        try:
            assert resolve_email_branding(db, organization_id=None).footer_company_id == "99"
        finally:
            db.close()
        _platform_footer(client, admin_token, company_id=None, company_id_label="ABN")
        db = SessionLocal()
        try:
            assert resolve_email_branding(db, organization_id=None).footer_company_id is None
        finally:
            db.close()
    finally:
        _platform_footer(client, admin_token, company_id=None, company_id_label=None)


def test_an_organisation_with_its_own_company_name_does_not_carry_the_operators_prefix_or_id(client, admin_token, org_id):
    _platform_footer(client, admin_token, email_footer_company_name="Host Pty Ltd", footer_prefix="Hosted by", company_id="12")
    try:
        # No company name of its own: the platform details (and so the prefix and identifier) are shown.
        db = SessionLocal()
        try:
            shown = resolve_email_branding(db, organization_id=UUID(org_id))
        finally:
            db.close()
        assert shown.footer_prefix == "Hosted by" and shown.footer_company_id == "12"
        resp = client.put(
            f"/api/v1/orgs/{org_id}/branding", json={"email_footer_company_name": "Tenant Ltd"}, headers=auth_headers(admin_token)
        )
        assert resp.status_code == 200, resp.text
        db = SessionLocal()
        try:
            own = resolve_email_branding(db, organization_id=UUID(org_id))
        finally:
            db.close()
        assert own.footer_company_name == "Tenant Ltd"
        assert own.footer_prefix is None and own.footer_company_id is None
    finally:
        client.put(f"/api/v1/orgs/{org_id}/branding", json={"email_footer_company_name": None}, headers=auth_headers(admin_token))
        _platform_footer(client, admin_token, email_footer_company_name=None, footer_prefix=None, company_id=None)
