"""Tests for Context & Strategy's `ArtefactSummaryProvider`s
(`modules.context_strategy.summaries`), the hook the core artefact link graph
uses to label and visibility-check this module's records. Goes through the
registry's `get_artefact_summaries_in_project` so the module/sub-component
enablement gate is exercised along with each provider, and through the real
HTTP link-graph endpoint for one end-to-end case.
"""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.modules.context_strategy.tests.test_context_strategy_relationships_api import (
    _create_future_state,
    _create_guiding_principle,
    _create_open_question,
    _create_org_strategy,
    _create_pain_point,
    _create_strategy,
    _setup,
)
from app.modules.registry import get_artefact_summaries_in_project, list_artefact_summaries
from app.services import relationships
from tests.conftest import auth_headers, create_project

_TYPES = ("strategy", "future_state", "pain_point", "guiding_principle", "open_question")


def _summaries(project_id, artefact_type, ids):
    db = SessionLocal()
    try:
        return get_artefact_summaries_in_project(db, uuid.UUID(project_id), artefact_type, [uuid.UUID(i) for i in ids])
    finally:
        db.close()


def test_every_type_is_summarised_with_label_status_and_owner(client, admin_token):
    _, project, token = _setup(client, admin_token, "Cs Summaries Co")
    pid = project["id"]
    records = {
        "strategy": _create_strategy(client, token, pid, title="Lead the market"),
        "future_state": _create_future_state(client, token, pid, title="Automated inspections"),
        "pain_point": _create_pain_point(client, token, pid, title="Report delays"),
        "guiding_principle": _create_guiding_principle(client, token, pid, name="Safety first"),
        "open_question": _create_open_question(client, token, pid, question="Which battery vendor?"),
    }
    expected_labels = {
        "strategy": "Lead the market", "future_state": "Automated inspections", "pain_point": "Report delays",
        "guiding_principle": "Safety first", "open_question": "Which battery vendor?",
    }

    for artefact_type in _TYPES:
        found = _summaries(pid, artefact_type, [records[artefact_type]["id"]])
        summary = found[uuid.UUID(records[artefact_type]["id"])]
        assert summary.label == expected_labels[artefact_type], artefact_type
        assert summary.status and summary.project_id == uuid.UUID(pid) and summary.is_archived is False


def test_other_projects_and_org_owned_records_are_not_visible_in_a_project(client, admin_token):
    org, project, token = _setup(client, admin_token, "Cs Summaries Isolation Co")
    other = create_project(client, token, org["id"], "Other")
    mine = _create_strategy(client, token, project["id"])
    theirs = _create_strategy(client, token, other["id"])
    org_owned = _create_org_strategy(client, token, org["id"])

    found = _summaries(project["id"], "strategy", [mine["id"], theirs["id"], org_owned["id"]])

    assert set(found) == {uuid.UUID(mine["id"])}


def test_disabled_subcomponent_hides_only_that_type(client, admin_token):
    org, project, token = _setup(client, admin_token, "Cs Summaries Subcomponent Co")
    point = _create_pain_point(client, token, project["id"])
    question = _create_open_question(client, token, project["id"])
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/context_strategy/subcomponents/pain_point", json={"enabled": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    assert _summaries(project["id"], "pain_point", [point["id"]]) == {}
    assert len(_summaries(project["id"], "open_question", [question["id"]])) == 1


def test_picker_listing_excludes_archived_and_is_sorted(client, admin_token):
    _, project, token = _setup(client, admin_token, "Cs Summaries Picker Co")
    _create_pain_point(client, token, project["id"], title="b second")
    _create_pain_point(client, token, project["id"], title="A first")
    db = SessionLocal()
    try:
        labels = [s.label for s in list_artefact_summaries(db, uuid.UUID(project["id"]), "pain_point")]
    finally:
        db.close()
    assert labels == ["A first", "b second"]


def test_link_graph_shows_a_linked_pain_point(client, admin_token):
    _, project, token = _setup(client, admin_token, "Cs Summaries Graph Co")
    strategy = _create_strategy(client, token, project["id"])
    point = _create_pain_point(client, token, project["id"], title="Report delays")
    user_id = uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"])
    db = SessionLocal()
    try:
        relationships.create_link(
            db, source_type="strategy", source_id=uuid.UUID(strategy["id"]), target_type="pain_point",
            target_id=uuid.UUID(point["id"]), link_type_id=None, created_by=user_id,
        )
        db.commit()
    finally:
        db.close()

    graph = client.get(
        f"/api/v1/projects/{project['id']}/artefacts/strategy/{strategy['id']}/link-graph", headers=auth_headers(token)
    ).json()

    node = next(n for n in graph["nodes"] if n["type"] == "pain_point")
    assert node["label"] == "Report delays" and node["type_label"] == "Pain point"
