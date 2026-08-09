"""Tests for Massif (v3) selectable report templates (R-G-05)."""

from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.services.reports import resolve_report_config_with_template
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
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"report_template_id": template["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_org_admin_can_set_intro_and_chapters_on_a_template(client, admin_token, org_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/report-templates",
        json={
            "name": "Content Template", "intro": "Template intro text",
            "chapters": [{"title": "Ch1", "body": "Chapter body"}],
            "appendices": [{"title": "App1", "body": "Appendix body"}],
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    template = resp.json()
    assert template["intro"] == "Template intro text"
    assert template["chapters"] == [{"title": "Ch1", "body": "Chapter body"}]
    assert template["appendices"] == [{"title": "App1", "body": "Appendix body"}]

    resp = client.put(
        f"/api/v1/orgs/{org_id}/report-templates/{template['id']}",
        json={"name": "Content Template", "intro": "Updated intro", "chapters": [], "appendices": []},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["intro"] == "Updated intro"
    assert resp.json()["chapters"] == []


def test_resolve_report_config_with_template_prefers_template_content_per_field(admin_token, org_id):
    """Pure unit test of the precedence logic (template > project > org
    default, per field independently) — no PDF parsing needed to verify
    this without going through report generation end-to-end."""
    org = Organization(default_report_intro="org default intro", default_report_chapters=None, default_report_appendices=None)
    project = Project(report_intro="project intro", report_chapters=[{"title": "Project Ch", "body": "x"}], report_appendices=[])

    # No template: same as resolve_report_config directly.
    resolved = resolve_report_config_with_template(project, org, None)
    assert resolved.intro == "project intro"
    assert resolved.appendices == []  # falls through to org default, which is also empty

    # Template overrides intro only, leaves chapters/appendices to fall through.
    template = ReportTemplate(intro="template intro", chapters=[], appendices=[])
    resolved = resolve_report_config_with_template(project, org, template)
    assert resolved.intro == "template intro"
    assert resolved.chapters[0].title == "Project Ch"  # template didn't set chapters -> falls through to project's

    # Template overrides chapters too.
    template = ReportTemplate(intro="", chapters=[{"title": "Template Ch", "body": "y"}], appendices=[])
    resolved = resolve_report_config_with_template(project, org, template)
    assert resolved.intro == "project intro"  # template didn't set intro -> falls through to project's
    assert resolved.chapters[0].title == "Template Ch"


def test_generating_a_report_with_a_foreign_orgs_template_id_is_rejected(client, admin_token, org_id):
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Org For Report Template Isolation")
    foreign_template = client.post(
        f"/api/v1/orgs/{other_org['id']}/report-templates",
        json={"name": "Foreign"}, headers=auth_headers(other_admin_token),
    ).json()

    project = create_project(client, admin_token, org_id)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"report_template_id": foreign_template["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400
