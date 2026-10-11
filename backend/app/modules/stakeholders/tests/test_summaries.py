"""Tests for Stakeholders' `ArtefactSummaryProvider`s
(`modules.stakeholders.summaries`), which the core link graph uses to label and
visibility-check Personas, Stakeholders and Needs: own-project and org-owned
records are visible, another project's are not, an org record hidden from the
project is not, and the graph endpoint shows them end to end.
"""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.modules.registry import get_artefact_summaries_in_project, list_artefact_summaries
from app.modules.stakeholders.tests.test_need_api import _create_need, _create_requirement
from app.modules.stakeholders.tests.test_persona_api import (
    _create_org_persona,
    _create_project_persona,
    _setup,
)
from app.modules.stakeholders.tests.test_persona_visibility import _hide
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from app.services import relationships
from tests.conftest import auth_headers, create_project


def _summaries(project_id, artefact_type, ids):
    db = SessionLocal()
    try:
        return get_artefact_summaries_in_project(db, uuid.UUID(project_id), artefact_type, [uuid.UUID(i) for i in ids])
    finally:
        db.close()


def test_own_org_and_foreign_personas(client, admin_token):
    org, project, token = _setup(client, admin_token, "Sh Summaries Persona Co")
    other = create_project(client, token, org["id"], "Other")
    mine = _create_project_persona(client, token, project["id"], name="Mine")
    theirs = _create_project_persona(client, token, other["id"], name="Theirs")
    shared = _create_org_persona(client, token, org["id"], name="Shared")

    found = _summaries(project["id"], "persona", [mine["id"], theirs["id"], shared["id"]])

    assert {s.label for s in found.values()} == {"Mine", "Shared"}
    org_summary = found[uuid.UUID(shared["id"])]
    assert org_summary.project_id is None and org_summary.organization_id == uuid.UUID(org["id"])
    assert org_summary.status == "draft"


def test_hidden_org_persona_is_not_visible_but_un_hide_restores_it(client, admin_token):
    org, project, token = _setup(client, admin_token, "Sh Summaries Hidden Persona Co")
    shared = _create_org_persona(client, token, org["id"], name="Shared")
    assert _hide(client, token, project["id"], shared["id"]).status_code == 200, "hide failed"

    assert _summaries(project["id"], "persona", [shared["id"]]) == {}
    db = SessionLocal()
    try:
        assert list_artefact_summaries(db, uuid.UUID(project["id"]), "persona") == []
    finally:
        db.close()

    assert _hide(client, token, project["id"], shared["id"], hidden=False).status_code == 200
    assert len(_summaries(project["id"], "persona", [shared["id"]])) == 1


def test_stakeholders_and_needs(client, admin_token):
    org, project, token = _setup(client, admin_token, "Sh Summaries Stakeholder Co")
    other = create_project(client, token, org["id"], "Other")
    own = _create_project_stakeholder(client, token, project["id"])
    org_owned = _create_org_stakeholder(client, token, org["id"])
    foreign = _create_project_stakeholder(client, token, other["id"])
    need = _create_need(client, token, project["id"])
    foreign_need = _create_need(client, token, other["id"])

    stakeholders = _summaries(project["id"], "stakeholder", [own["id"], org_owned["id"], foreign["id"]])
    needs = _summaries(project["id"], "stakeholder_need", [need["id"], foreign_need["id"]])

    assert set(stakeholders) == {uuid.UUID(own["id"]), uuid.UUID(org_owned["id"])}
    assert set(needs) == {uuid.UUID(need["id"])}
    assert next(iter(needs.values())).label == need["name"]


def test_link_graph_shows_a_need_linked_to_a_requirement(client, admin_token):
    _, project, token = _setup(client, admin_token, "Sh Summaries Graph Co")
    need = _create_need(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"])
    user_id = uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"])
    db = SessionLocal()
    try:
        relationships.create_link(
            db, source_type="stakeholder_need", source_id=uuid.UUID(need["id"]), target_type="requirement",
            target_id=uuid.UUID(requirement["id"]), link_type_id=None, created_by=user_id,
        )
        db.commit()
    finally:
        db.close()

    graph = client.get(
        f"/api/v1/projects/{project['id']}/artefacts/requirement/{requirement['id']}/link-graph",
        headers=auth_headers(token),
    ).json()

    node = next(n for n in graph["nodes"] if n["type"] == "stakeholder_need")
    assert node["label"] == need["name"] and node["type_label"] == "Stakeholder need"
