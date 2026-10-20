"""Tests for Context & Strategy's contribution to the global search: each of its five types is found by
title, and by a declared text field only when that field is searched; organisation-owned Strategies,
Future States and Guiding Principles have no project surface and are not returned."""

from __future__ import annotations

import pytest

from app.modules.context_strategy.tests.test_context_strategy_open_question_api import _create_open_question
from app.modules.context_strategy.tests.test_context_strategy_relationships_api import (
    _create_future_state,
    _create_guiding_principle,
    _create_org_strategy,
    _create_pain_point,
    _create_strategy,
    _setup,
)
from tests.conftest import auth_headers

# (artefact type, creator, title field of the create payload, a declared field key and its payload name)
CASES = [
    ("strategy", _create_strategy, "title", "objective", "objective"),
    ("future_state", _create_future_state, "title", "desired_state", "desired_state"),
    ("guiding_principle", _create_guiding_principle, "name", "principle_statement", "principle_statement"),
    ("pain_point", _create_pain_point, "title", "impact", "impact"),
    ("open_question", _create_open_question, "question", "context", "context"),
]


def _search(client, token, body):
    resp = client.post("/api/v1/search", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize(("artefact_type", "create", "title_field", "field_key", "field_name"), CASES)
def test_each_type_is_found_by_title_and_by_a_declared_field_only_when_it_is_searched(
    client, admin_token, artefact_type, create, title_field, field_key, field_name
):
    _, project, token = _setup(client, admin_token, f"Search CS {artefact_type} Co")
    title_word, field_word = f"titlezq{artefact_type.replace('_', '')}", f"fieldzq{artefact_type.replace('_', '')}"
    record = create(client, token, project["id"], **{title_field: f"About {title_word}", field_name: f"mentions {field_word} here"})
    scope = {"scope": "project", "project_id": project["id"]}

    by_title = _search(client, token, {"q": title_word, **scope})
    assert [(h["type"], h["id"]) for h in by_title["hits"]] == [(artefact_type, record["id"])]
    assert by_title["hits"][0]["code"] and by_title["hits"][0]["project_id"] == project["id"]

    assert _search(client, token, {"q": field_word, **scope})["hits"] == []  # not a default field
    by_field = _search(client, token, {"q": field_word, "fields": ["id", "title", field_key], **scope})
    assert [h["id"] for h in by_field["hits"]] == [record["id"]]
    assert by_field["hits"][0]["snippet"]["field_key"] == field_key


def test_organisation_records_are_found_in_the_all_projects_scope_by_members_and_open_at_their_organisation_page(client, admin_token):
    org, project, token = _setup(client, admin_token, "Search CS Org Strategy Co")
    strategy = _create_org_strategy(client, token, org["id"], title="Shared orgzq strategy")
    own = _create_strategy(client, token, project["id"], title="Project orgzq strategy")

    everywhere = _search(client, token, {"q": "orgzq", "scope": "all"})
    by_id = {h["id"]: h for h in everywhere["hits"]}
    assert set(by_id) == {strategy["id"], own["id"]}
    shared = by_id[strategy["id"]]
    assert shared["project_id"] is None and shared["open_project_id"] is None
    assert shared["organization_id"] == org["id"] and shared["organization_code"]
    assert {c["type"]: c["count"] for c in everywhere["type_counts"]} == {"strategy": 2}
    # A project search covers its organisation's records too, unless asked not to.
    scope = {"scope": "project", "project_id": project["id"]}
    assert {h["id"] for h in _search(client, token, {"q": "orgzq", **scope})["hits"]} == {strategy["id"], own["id"]}
    only_own = _search(client, token, {"q": "orgzq", "include_organization_records": False, **scope})
    assert [h["id"] for h in only_own["hits"]] == [own["id"]]
    # The all-projects scope always includes them, whatever the flag says.
    assert len(_search(client, token, {"q": "orgzq", "scope": "all", "include_organization_records": False})["hits"]) == 2


def test_the_preference_sets_whether_a_project_search_covers_organisation_records_and_a_request_overrides_it(client, admin_token):
    org, project, token = _setup(client, admin_token, "Search CS Org Pref Co")
    strategy = _create_org_strategy(client, token, org["id"], title="Preference prefzq strategy")
    scope = {"scope": "project", "project_id": project["id"]}
    headers = auth_headers(token)

    def save(value):
        return client.patch("/api/v1/auth/me/preferences", json={"ui_preferences": {"search_include_org_records": value}}, headers=headers)

    assert [h["id"] for h in _search(client, token, {"q": "prefzq", **scope})["hits"]] == [strategy["id"]]  # on by default
    assert save(False).status_code == 200
    assert _search(client, token, {"q": "prefzq", **scope})["hits"] == []
    assert [h["id"] for h in _search(client, token, {"q": "prefzq", "include_organization_records": True, **scope})["hits"]] == [strategy["id"]]
    assert save("yes").status_code == 422
    assert save(True).status_code == 200
    assert len(_search(client, token, {"q": "prefzq", **scope})["hits"]) == 1


def test_a_project_that_has_the_feature_off_does_not_show_organisation_records(client, admin_token):
    org, project, token = _setup(client, admin_token, "Search CS Org Off Co")
    _create_org_strategy(client, token, org["id"], title="Switched offzq strategy")
    scope = {"scope": "project", "project_id": project["id"]}
    assert len(_search(client, token, {"q": "offzq", **scope})["hits"]) == 1
    off = client.put(
        f"/api/v1/projects/{project['id']}/modules/context_strategy/subcomponents/strategy", json={"enabled": False},
        headers=auth_headers(token),
    )
    assert off.status_code == 200, off.text
    assert _search(client, token, {"q": "offzq", **scope})["hits"] == []
    # Still found everywhere else in the organisation.
    assert len(_search(client, token, {"q": "offzq", "scope": "all"})["hits"]) == 1


def test_organisation_records_follow_the_organisation_level_gates(client, admin_token):
    org, _project, token = _setup(client, admin_token, "Search CS Org Gates Co")
    _create_org_strategy(client, token, org["id"], title="Gated gatezq strategy")
    # Another organisation's member never sees it.
    _, _, other_token = _setup(client, admin_token, "Search CS Org Gates Other Co")
    assert _search(client, other_token, {"q": "gatezq", "scope": "all"})["hits"] == []
    # The organisation's sub-component switch removes it.
    off = client.put(
        f"/api/v1/orgs/{org['id']}/modules/context_strategy/subcomponents/strategy", json={"enabled": False},
        headers=auth_headers(token),
    )
    assert off.status_code == 200, off.text
    assert _search(client, token, {"q": "gatezq", "scope": "all"})["hits"] == []
