"""Tests for the text-view endpoints of custom report layouts (`routers.report_layouts`).

`POST .../report-layouts/text/parse` and `.../text/format` at the organisation and project tier: they
convert and report positioned errors, need the matching manage permission, store nothing, audit nothing
and never log the text. The conversion itself is covered by `test_report_layout_text.py`. Each test
builds its own organisation.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.report_layout import ReportLayout
from app.services.report_layout_text import MAX_TEXT_VIEW_CHARS
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

TEXT = """\
@layout document

@heading Report for {{project_name}}

@each requirement sort title as req
  @heading level=2 {{req.code}} {{req.title}}
@end
"""
SECRET = "Customer-confidential-phrase-7f3a"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Text Org")


def org_url(world: World, suffix: str) -> str:
    return f"/api/v1/orgs/{world.org['id']}/report-layouts{suffix}"


def project_url(project: dict, suffix: str) -> str:
    return f"/api/v1/projects/{project['id']}/report-layouts{suffix}"


def member_token(world: World) -> str:
    email = f"m-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    return login(world.client, email, "Password123!")


def counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(AuditEvent)), db.scalar(select(func.count()).select_from(ReportLayout))


@pytest.mark.parametrize("tier", ["org", "project"])
def test_text_converts_to_a_tree_and_back(world, tier):
    project = world.project()
    url = (lambda s: org_url(world, s)) if tier == "org" else (lambda s: project_url(project, s))
    h = auth_headers(world.token)

    parsed = world.client.post(url("/text/parse"), json={"text": TEXT}, headers=h)

    assert parsed.status_code == 200, parsed.text
    body = parsed.json()
    assert body["ok"] is True and body["errors"] == []
    assert body["tree"]["nodes"][0] == {"type": "heading", "text": "Report for {{project_name}}"}

    written = world.client.post(url("/text/format"), json={"tree": body["tree"]}, headers=h)

    assert written.status_code == 200, written.text
    assert written.json()["text"] == TEXT


def test_errors_come_back_positioned_and_a_syntax_error_has_no_tree(world):
    h = auth_headers(world.token)

    syntax = world.client.post(org_url(world, "/text/parse"), json={"text": "@layout document\n@each\n@end\n"}, headers=h).json()
    meaning = world.client.post(
        org_url(world, "/text/parse"), json={"text": "@layout document\n\n@heading {{nope.title}}\n"}, headers=h,
    ).json()

    assert syntax["ok"] is False and syntax["tree"] is None
    assert syntax["errors"][0]["line"] == 2 and syntax["errors"][0]["column"] is not None
    assert meaning["ok"] is False and meaning["tree"] is not None
    assert meaning["errors"][0]["line"] == 3 and meaning["errors"][0]["column"] is None


def test_formatting_an_invalid_tree_is_a_422_with_positioned_errors(world):
    resp = world.client.post(
        org_url(world, "/text/format"),
        json={"tree": {"schema_version": 1, "family": "document", "nodes": [{"type": "heading"}]}},
        headers=auth_headers(world.token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["errors"][0]["path"] == "nodes[0].text"


def test_text_over_the_size_limit_is_refused(world):
    resp = world.client.post(
        org_url(world, "/text/parse"), json={"text": "x" * (MAX_TEXT_VIEW_CHARS + 1)}, headers=auth_headers(world.token),
    )

    assert resp.status_code == 422


def test_the_manage_permission_is_required_at_both_tiers(world):
    project = world.project()
    member = member_token(world)

    urls = [org_url(world, "/text/parse"), org_url(world, "/text/format"), project_url(project, "/text/parse"), project_url(project, "/text/format")]
    for url in urls:
        body = {"text": TEXT} if url.endswith("parse") else {"tree": {"schema_version": 1, "family": "document", "nodes": []}}
        assert world.client.post(url, json=body, headers=auth_headers(member)).status_code in (403, 404), url
        assert world.client.post(url, json=body).status_code in (401, 403), url


def test_converting_stores_nothing_audits_nothing_and_logs_no_text(world, caplog):
    before = counts()
    caplog.set_level(logging.DEBUG)

    resp = world.client.post(
        org_url(world, "/text/parse"), json={"text": f"@layout document\n\n{SECRET}\n@bogus {SECRET}\n"}, headers=auth_headers(world.token),
    )

    assert resp.status_code == 200 and resp.json()["ok"] is False
    assert counts() == before
    assert SECRET not in caplog.text
