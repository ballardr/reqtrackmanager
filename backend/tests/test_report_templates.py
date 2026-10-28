"""Tests for Massif (v3) selectable report templates (R-G-05)."""

from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project


def test_org_admin_can_create_list_update_delete_template(client, admin_token, org_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/report-templates",
        json={"name": "Branded", "accent_color_hex": "#ff0000"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    template = resp.json()

    resp = client.get(f"/api/v1/orgs/{org_id}/report-templates", headers=auth_headers(admin_token))
    assert any(t["id"] == template["id"] for t in resp.json())

    resp = client.put(
        f"/api/v1/orgs/{org_id}/report-templates/{template['id']}",
        json={"name": "Branded v2", "accent_color_hex": "#00ff00"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Branded v2"

    resp = client.delete(f"/api/v1/orgs/{org_id}/report-templates/{template['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 204


def test_non_admin_org_cannot_create_a_template_for_another_org(client, admin_token, org_id):
    _, other_admin_token = create_org_admin_in(client, admin_token, "Org For Report Template Check")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/report-templates",
        json={"name": "Sneaky"}, headers=auth_headers(other_admin_token),
    )
    assert resp.status_code == 403


def test_generating_a_pdf_report_with_a_template_selected_succeeds(client, admin_token, org_id):
    template = client.post(
        f"/api/v1/orgs/{org_id}/report-templates",
        json={"name": "PDF Branding", "include_cover_page": True, "footer_text": "Confidential"},
        headers=auth_headers(admin_token),
    ).json()
    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports",
        json={"format": "pdf", "report_template_id": template["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_a_template_is_branding_only(client, admin_token, org_id):
    """A template has no introduction, chapters or appendices: a `content` field is ignored and never returned."""
    resp = client.post(
        f"/api/v1/orgs/{org_id}/report-templates",
        json={"name": "Branding Only", "content": [{"report_key": "requirements", "intro": "Ignored"}]},
        headers=auth_headers(admin_token),
    )

    assert resp.status_code == 201, resp.text
    assert "content" not in resp.json()
    listed = client.get(f"/api/v1/orgs/{org_id}/report-templates", headers=auth_headers(admin_token)).json()
    assert all("content" not in t for t in listed)


def test_generating_a_report_with_a_foreign_orgs_template_id_is_rejected(client, admin_token, org_id):
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Org For Report Template Isolation")
    foreign_template = client.post(
        f"/api/v1/orgs/{other_org['id']}/report-templates",
        json={"name": "Foreign"}, headers=auth_headers(other_admin_token),
    ).json()

    project = create_project(client, admin_token, org_id)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports",
        json={"format": "pdf", "report_template_id": foreign_template["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_report_template_chapters_per_component_round_trips(client, admin_token, org_id):
    """Defaults to True (chaptered) on creation; explicit False is
    respected and survives an update."""
    resp = client.post(
        f"/api/v1/orgs/{org_id}/report-templates", json={"name": "Default Layout"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["chapters_per_component"] is True

    resp = client.post(
        f"/api/v1/orgs/{org_id}/report-templates",
        json={"name": "Continuous Layout", "chapters_per_component": False}, headers=auth_headers(admin_token),
    )
    template = resp.json()
    assert template["chapters_per_component"] is False

    resp = client.put(
        f"/api/v1/orgs/{org_id}/report-templates/{template['id']}",
        json={"name": "Continuous Layout", "chapters_per_component": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["chapters_per_component"] is True


def test_a_project_has_no_default_report_template(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)

    assert "default_report_template_id" not in client.get(
        f"/api/v1/projects/{project['id']}", headers=auth_headers(admin_token),
    ).json()
    assert client.put(
        f"/api/v1/projects/{project['id']}/report-config", json={}, headers=auth_headers(admin_token),
    ).status_code in (404, 405)
