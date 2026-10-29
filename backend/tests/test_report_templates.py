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


# ---- default template and a layout's own template (Reports dialog) -------------------------------------------------


import io  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402
import zipfile  # noqa: E402

import pytest  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.services.report_document import ForeignReportTemplateError, effective_report_template  # noqa: E402
from app.services.report_layout_tree import empty_tree  # noqa: E402
from tests.link_world import World  # noqa: E402


def _template(client, token, org_id, name: str, **extra) -> dict:
    resp = client.post(f"/api/v1/orgs/{org_id}/report-templates", json={"name": name, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _defaults(client, token, org_id) -> list[str]:
    listed = client.get(f"/api/v1/orgs/{org_id}/report-templates", headers=auth_headers(token)).json()
    return [t["name"] for t in listed if t["is_default"]]


def test_an_organisation_has_at_most_one_default_template(client, admin_token, org_id):
    first = _template(client, admin_token, org_id, "First", is_default=True)
    assert first["is_default"] is True
    second = _template(client, admin_token, org_id, "Second", is_default=True)
    assert second["is_default"] is True
    assert _defaults(client, admin_token, org_id) == ["Second"]

    resp = client.put(
        f"/api/v1/orgs/{org_id}/report-templates/{first['id']}",
        json={"name": "First", "is_default": True}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert _defaults(client, admin_token, org_id) == ["First"]

    resp = client.put(
        f"/api/v1/orgs/{org_id}/report-templates/{first['id']}",
        json={"name": "First", "is_default": False}, headers=auth_headers(admin_token),
    )
    assert _defaults(client, admin_token, org_id) == []


def test_the_effective_template_is_requested_then_the_layouts_then_the_default(client, admin_token, org_id):
    default = _template(client, admin_token, org_id, "Org default", is_default=True)
    layout_own = _template(client, admin_token, org_id, "Layout own")
    requested = _template(client, admin_token, org_id, "Requested")
    org = uuid.UUID(org_id)
    with SessionLocal() as db:
        assert effective_report_template(db, org, None).id == uuid.UUID(default["id"])
        assert effective_report_template(db, org, None, layout_template_id=uuid.UUID(layout_own["id"])).id == uuid.UUID(layout_own["id"])
        assert effective_report_template(
            db, org, uuid.UUID(requested["id"]), layout_template_id=uuid.UUID(layout_own["id"]),
        ).id == uuid.UUID(requested["id"])
        with pytest.raises(ForeignReportTemplateError):
            effective_report_template(db, org, uuid.uuid4())


def test_no_default_and_no_override_means_an_unbranded_report(client, admin_token, org_id):
    _template(client, admin_token, org_id, "Not default")
    with SessionLocal() as db:
        assert effective_report_template(db, uuid.UUID(org_id), None) is None


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Template Org")


def _layout(world: World, **extra) -> dict:
    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/report-layouts",
        json={
            "name": "Branded layout", "family": "document",
            "tree": {**empty_tree("document"), "nodes": [{"type": "heading", "text": "Hi"}]}, **extra,
        },
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_layout_can_set_and_clear_its_own_template(world):
    own = _template(world.client, world.token, world.org["id"], "Own")
    layout = _layout(world, report_template_id=own["id"])
    assert layout["report_template_id"] == own["id"]
    url = f"/api/v1/orgs/{world.org['id']}/report-layouts/{layout['id']}"
    h = auth_headers(world.token)

    assert world.client.patch(url, json={"description": "x"}, headers=h).json()["report_template_id"] == own["id"]  # left out: unchanged
    catalogue = world.client.get(f"/api/v1/orgs/{world.org['id']}/report-catalogue", headers=h).json()
    assert any(e["title"] == "Branded layout" and e["report_template_id"] == own["id"] for e in catalogue)

    assert world.client.patch(url, json={"report_template_id": None}, headers=h).json()["report_template_id"] is None


def test_a_layout_refuses_another_organisations_template(world, client, admin_token):
    other_org, other_token = create_org_admin_in(client, admin_token, "Foreign Template Org")
    foreign = _template(client, other_token, other_org["id"], "Foreign")
    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/report-layouts",
        json={"name": "Bad", "family": "document", "tree": empty_tree("document"), "report_template_id": foreign["id"]},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 422 and "template" in resp.text


def test_deleting_a_template_clears_the_layouts_override(world):
    own = _template(world.client, world.token, world.org["id"], "Own")
    layout = _layout(world, report_template_id=own["id"])
    world.client.delete(f"/api/v1/orgs/{world.org['id']}/report-templates/{own['id']}", headers=auth_headers(world.token))
    got = world.client.get(f"/api/v1/orgs/{world.org['id']}/report-layouts/{layout['id']}", headers=auth_headers(world.token)).json()
    assert got["report_template_id"] is None


def test_an_organisation_bundle_carries_the_default_flag_and_a_layouts_template(world):
    h = auth_headers(world.token)
    org_id = world.org["id"]
    _template(world.client, world.token, org_id, "Corporate", is_default=True)
    own = _template(world.client, world.token, org_id, "Layout only")
    _layout(world, report_template_id=own["id"])

    exported = world.client.get(f"/api/v1/orgs/{org_id}/export", headers=h)
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as zf:
        org_json = json.loads(zf.read("org.json"))
    assert {(t["name"], t["is_default"]) for t in org_json["report_templates"]} == {("Corporate", True), ("Layout only", False)}
    assert [layout["report_template"] for layout in org_json["report_layouts"]] == ["Layout only"]


def test_a_project_bundle_restores_a_layouts_template_by_name(world):
    h = auth_headers(world.token)
    org_id = world.org["id"]
    own = _template(world.client, world.token, org_id, "Project layout template")
    project = world.project("Source")
    created = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts",
        json={"name": "P layout", "family": "document", "tree": {**empty_tree("document"), "nodes": [{"type": "heading", "text": "x"}]},
              "report_template_id": own["id"]},
        headers=h,
    )
    assert created.status_code == 201, created.text
    bundle = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=h).content
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Copy"},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []
    listed = world.client.get(f"/api/v1/projects/{imported.json()['project']['id']}/report-layouts", headers=h).json()
    assert [layout["report_template_id"] for layout in listed if layout["name"] == "P layout"] == [own["id"]]


# ---- a download picks its branding itself: the layout's own template, else the organisation's default, else none -----


def _footer_text(content: bytes) -> str:
    """The text of every footer part in a Word file (a template's footer text is how a download shows its branding)."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return " ".join(archive.read(n).decode() for n in archive.namelist() if n.startswith("word/footer"))


def _download_docx(world: World, project: dict, layout: dict) -> bytes:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": "docx"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.content


def test_a_download_uses_the_layouts_template_else_the_default_else_none(world):
    """The download dialog offers no branding choice, so the server alone decides which template applies."""
    org_id, project = world.org["id"], world.project()
    layout = _layout(world)
    assert "BRAND-DEFAULT" not in _footer_text(_download_docx(world, project, layout))  # nothing set: unbranded

    _template(world.client, world.token, org_id, "Org default", is_default=True, footer_text="BRAND-DEFAULT")
    assert "BRAND-DEFAULT" in _footer_text(_download_docx(world, project, layout))  # the organisation's default

    own = _template(world.client, world.token, org_id, "Layout own", footer_text="BRAND-OWN")
    owned = _layout(world, name="Owned layout", report_template_id=own["id"])
    footer = _footer_text(_download_docx(world, project, owned))
    assert "BRAND-OWN" in footer and "BRAND-DEFAULT" not in footer  # the layout's override beats the default


def test_a_module_report_download_uses_the_organisations_default_only(world):
    """A catalogue report has no per-report template: with no `report_template_id` the default applies, else none."""
    project = world.project()
    url = f"/api/v1/projects/{project['id']}/reports"
    h = auth_headers(world.token)
    unbranded = world.client.post(url, json={"format": "docx"}, headers=h)
    assert unbranded.status_code == 200, unbranded.text
    assert "BRAND-DEFAULT" not in _footer_text(unbranded.content)

    _template(world.client, world.token, world.org["id"], "Org default", is_default=True, footer_text="BRAND-DEFAULT")
    branded = world.client.post(url, json={"format": "docx"}, headers=h)
    assert branded.status_code == 200, branded.text
    assert "BRAND-DEFAULT" in _footer_text(branded.content)
