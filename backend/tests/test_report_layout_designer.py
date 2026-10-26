"""Tests for what the layout designer calls beyond storing layouts (`services.report_layout_designer`,
`routers.report_layouts`): the field catalogue (`GET .../report-layouts/fields`) and the draft preview
(`POST .../report-layouts/preview`) at the organisation and project tier.

A preview evaluates an unsaved draft for the caller and leaves nothing behind: no layout, no provenance row, no
audit event, no logged text. Each test builds its own organisation.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.generated_report import GeneratedReport
from app.models.report_layout import ReportLayout
from app.services import report_layout_designer
from app.services.report_layout_tree import empty_tree
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import REQ, World

DOCUMENT_TEXT = """\
@layout document

@heading Requirements of {{project_name}}

@each requirement sort title as req
  @heading level=2 {{req.code}} {{req.title}}
@end
"""
SECRET = "Customer-confidential-phrase-9c1d"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Designer Org")


def org_url(world: World, suffix: str) -> str:
    return f"/api/v1/orgs/{world.org['id']}/report-layouts{suffix}"


def project_url(project: dict, suffix: str) -> str:
    return f"/api/v1/projects/{project['id']}/report-layouts{suffix}"


def member_token(world: World) -> str:
    email = f"m-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    return login(world.client, email, "Password123!")


def counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.scalar(select(func.count()).select_from(AuditEvent)),
            db.scalar(select(func.count()).select_from(ReportLayout)),
            db.scalar(select(func.count()).select_from(GeneratedReport)),
        )


def sheet_tree() -> dict:
    return {
        **empty_tree("table"),
        "nodes": [{
            "type": "sheet", "name": "Reqs", "source": {"record_type": REQ, "sort": [{"field": "title"}]},
            "columns": [{"field": "code"}, {"field": "title"}],
        }],
    }


# ---- the field catalogue ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["org", "project"])
def test_the_catalogue_lists_types_with_their_fields_and_the_placeholders(world, tier):
    project = world.project()
    url = org_url(world, "/fields") if tier == "org" else project_url(project, "/fields")

    resp = world.client.get(url, headers=auth_headers(world.token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    requirement = next(t for t in body["types"] if t["type"] == REQ)
    assert requirement["label"] == "Requirement"
    keys = [f["key"] for f in requirement["fields"]]
    assert keys[:4] == ["code", "title", "status", "tags"]
    assert all(f["reserved"] for f in requirement["fields"][:4])
    assert "report_title" in body["placeholders"] and body["group_fields"] == {"value": "text", "count": "number"}
    labels = [t["label"].lower() for t in body["types"]]
    assert labels == sorted(labels)


@pytest.mark.parametrize("tier", ["org", "project"])
def test_a_type_of_a_module_that_is_off_is_not_offered(world, tier):
    project = world.project()
    url = org_url(world, "/fields") if tier == "org" else project_url(project, "/fields")
    h = auth_headers(world.token)

    before = {t["type"] for t in world.client.get(url, headers=h).json()["types"]}
    world.enable("decisions")
    project = world.project("With decisions")
    url = org_url(world, "/fields") if tier == "org" else project_url(project, "/fields")
    after = {t["type"] for t in world.client.get(url, headers=h).json()["types"]}

    assert "decision" not in before
    assert "decision" in after and REQ in after


def test_the_catalogue_needs_the_manage_permission(world):
    project = world.project()
    member = member_token(world)

    for url in (org_url(world, "/fields"), project_url(project, "/fields")):
        assert world.client.get(url, headers=auth_headers(member)).status_code in (403, 404), url
        assert world.client.get(url).status_code in (401, 403), url


# ---- the draft preview ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["org", "project"])
def test_a_document_draft_comes_back_as_a_standalone_html_page(world, tier):
    project = world.project()
    world.requirement(project, "Brake pads")
    url = org_url(world, "/preview") if tier == "org" else project_url(project, "/preview")

    resp = world.client.post(url, json={"text": DOCUMENT_TEXT, "name": "My draft"}, headers=auth_headers(world.token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["family"] == "document" and body["sheets"] == []
    assert "Brake pads" in body["html"] and f"Requirements of {project['name']}" in body["html"]
    assert "Content-Security-Policy" in body["html"] and "<script" not in body["html"].lower()
    assert body["records_read"] >= 1 and body["projects"] == 1


@pytest.mark.parametrize("tier", ["org", "project"])
def test_a_table_draft_comes_back_as_sheets(world, tier):
    project = world.project()
    world.requirement(project, "Alpha")
    world.requirement(project, "Beta")
    url = org_url(world, "/preview") if tier == "org" else project_url(project, "/preview")

    resp = world.client.post(url, json={"tree": sheet_tree()}, headers=auth_headers(world.token))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["family"] == "table" and body["html"] is None
    sheet = body["sheets"][0]
    # An organisation-wide run adds the project each row came from.
    assert sheet["name"] == "Reqs" and sheet["columns"][-2:] == ["Code", "Title"]
    assert sheet["columns"][0] == ("Project" if tier == "org" else "Code")
    assert [row[-1] for row in sheet["rows"]] == ["Alpha", "Beta"] and sheet["total_rows"] == 2


def test_a_sheet_is_capped_for_the_screen_but_reports_its_real_size(world, monkeypatch):
    project = world.project()
    for title in ("A", "B", "C"):
        world.requirement(project, title)
    monkeypatch.setattr(report_layout_designer, "PREVIEW_MAX_ROWS", 2)

    body = world.client.post(project_url(project, "/preview"), json={"tree": sheet_tree()}, headers=auth_headers(world.token)).json()

    assert len(body["sheets"][0]["rows"]) == 2 and body["sheets"][0]["total_rows"] == 3


def test_text_problems_come_back_positioned_and_nothing_runs(world):
    project = world.project()

    syntax = world.client.post(
        project_url(project, "/preview"), json={"text": "@layout document\n@each\n@end\n"}, headers=auth_headers(world.token),
    )
    meaning = world.client.post(
        project_url(project, "/preview"), json={"text": "@layout document\n\n@heading {{nope.title}}\n"}, headers=auth_headers(world.token),
    )

    for resp, line in ((syntax, 2), (meaning, 3)):
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is False and resp.json()["errors"][0]["line"] == line
        assert resp.json()["html"] is None


def test_an_invalid_tree_is_a_422_with_positioned_errors(world):
    project = world.project()

    resp = world.client.post(
        project_url(project, "/preview"), json={"tree": {"schema_version": 1, "family": "document", "nodes": [{"type": "heading"}]}},
        headers=auth_headers(world.token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["path"] == "nodes[0].text"


@pytest.mark.parametrize("body", [{}, {"text": "x", "tree": {}}])
def test_exactly_one_draft_is_required(world, body):
    project = world.project()

    assert world.client.post(project_url(project, "/preview"), json=body, headers=auth_headers(world.token)).status_code == 422


def test_the_manage_permission_is_required_to_preview(world):
    project = world.project()
    member = member_token(world)

    for url in (org_url(world, "/preview"), project_url(project, "/preview")):
        assert world.client.post(url, json={"text": DOCUMENT_TEXT}, headers=auth_headers(member)).status_code in (403, 404), url
        assert world.client.post(url, json={"text": DOCUMENT_TEXT}).status_code in (401, 403), url


def test_an_organisation_preview_can_be_narrowed_and_refuses_a_project_it_cannot_cover(world):
    first, second = world.project("First"), world.project("Second")
    world.requirement(first, "In first")
    world.requirement(second, "In second")
    h = auth_headers(world.token)

    narrowed = world.client.post(org_url(world, "/preview"), json={"tree": sheet_tree(), "project_ids": [first["id"]]}, headers=h).json()
    foreign = world.client.post(org_url(world, "/preview"), json={"tree": sheet_tree(), "project_ids": [str(uuid.uuid4())]}, headers=h)

    assert narrowed["projects"] == 1
    assert [row[-1] for row in narrowed["sheets"][0]["rows"]] == ["In first"]
    assert foreign.status_code == 404


def test_a_preview_stores_nothing_audits_nothing_and_logs_no_text(world, caplog):
    project = world.project()
    world.requirement(project, SECRET)
    before = counts()
    caplog.set_level(logging.DEBUG)

    resp = world.client.post(
        project_url(project, "/preview"), json={"text": f"@layout document\n\n{SECRET}\n"}, headers=auth_headers(world.token),
    )
    org_resp = world.client.post(org_url(world, "/preview"), json={"tree": sheet_tree()}, headers=auth_headers(world.token))

    assert resp.status_code == 200 and org_resp.status_code == 200
    assert counts() == before
    assert SECRET not in caplog.text
