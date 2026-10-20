"""Tests for the Stakeholders & Personas contribution to the global search: organisation-owned
personas found through a project (and not through one that hides them), personal-data columns that
are never matched, and a research finding that opens its engagement."""

from __future__ import annotations

from app.modules.stakeholders.tests.test_engagement_api import _create, _engagements
from app.modules.stakeholders.tests.test_persona_api import _create_org_persona, _create_project_persona, _setup
from app.modules.stakeholders.tests.test_persona_visibility import _hide
from app.modules.stakeholders.tests.test_research_extras_api import _research_setup
from app.modules.stakeholders.tests.test_stakeholder_api import _create_project_stakeholder
from tests.conftest import auth_headers, create_project


def _search(client, token, body):
    resp = client.post("/api/v1/search", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_an_organisation_persona_is_found_through_a_project_that_shows_it_and_not_one_that_hides_it(client, admin_token):
    org, project, token = _setup(client, admin_token, "Search Persona Org Co")
    other = create_project(client, token, org["id"], "Search Persona Other")
    shared = _create_org_persona(client, token, org["id"], name="Shared Zorbian Technician")

    both = _search(client, token, {"q": "zorbian", "scope": "all"})
    hit = both["hits"][0]
    assert [h["id"] for h in both["hits"]] == [shared["id"]] and hit["type"] == "persona"
    assert hit["project_id"] is None and hit["organization_id"] == org["id"] and hit["organization_code"]
    assert hit["open_project_id"] in {project["id"], other["id"]}

    assert _hide(client, token, project["id"], shared["id"]).status_code == 200
    only_other = _search(client, token, {"q": "zorbian", "scope": "project", "project_id": project["id"]})
    assert only_other["hits"] == [] and only_other["type_counts"] == []
    elsewhere = _search(client, token, {"q": "zorbian", "scope": "project", "project_id": other["id"]})
    assert [h["id"] for h in elsewhere["hits"]] == [shared["id"]] and elsewhere["hits"][0]["open_project_id"] == other["id"]
    # Hidden from one project but shown by the other: still found, and counted once.
    both_again = _search(client, token, {"q": "zorbian", "scope": "all"})
    assert [c["count"] for c in both_again["type_counts"]] == [1]


def test_a_persona_hidden_from_every_project_is_not_found_or_counted(client, admin_token):
    org, project, token = _setup(client, admin_token, "Search Persona Hidden Co")
    shared = _create_org_persona(client, token, org["id"], name="Quietly Hidden Persona")
    assert _hide(client, token, project["id"], shared["id"]).status_code == 200
    result = _search(client, token, {"q": "quietly hidden", "scope": "all"})
    assert result["hits"] == [] and result["total"] == 0 and result["type_counts"] == []


def test_contact_details_are_never_matched_even_with_every_field_selected(client, admin_token):
    _, project, token = _setup(client, admin_token, "Search Stakeholder Pii Co")
    stakeholder = _create_project_stakeholder(
        client, token, project["id"], name="Ada Lovelace", contact_info="phone 555-0100 secret-contact-token",
        availability_constraints="never-on-fridays-token",
    )
    fields = _search(client, token, {"q": "ada", "scope": "project", "project_id": project["id"]})
    assert [h["id"] for h in fields["hits"]] == [stakeholder["id"]]
    every = [f["key"] for f in client.get("/api/v1/search/fields", headers=auth_headers(token)).json()]
    for needle in ("secret-contact-token", "never-on-fridays-token"):
        found = _search(client, token, {"q": needle, "scope": "all", "fields": every})
        assert found["hits"] == []


def test_a_finding_opens_its_engagement(client, admin_token):
    org, project, token = _research_setup(client, admin_token, "Search Finding Co")
    engagement = _create(client, token, project["id"], title="Discovery workshop")
    resp = client.post(
        f"{_engagements(project['id'])}/{engagement['id']}/findings", json={"title": "Onboarding is confusing"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    finding = resp.json()

    hits = _search(client, token, {"q": "onboarding", "scope": "project", "project_id": project["id"]})["hits"]
    assert [h["id"] for h in hits] == [finding["id"]]
    assert hits[0]["type"] == "research_finding" and hits[0]["code"] == finding["unique_code"]
    assert (hits[0]["open_type"], hits[0]["open_id"]) == ("engagement", engagement["id"])
    assert hits[0]["open_project_id"] == project["id"]


def test_project_personas_are_found_in_their_project(client, admin_token):
    _, project, token = _setup(client, admin_token, "Search Project Persona Co")
    persona = _create_project_persona(client, token, project["id"], name="Wandering Auditor")
    found = _search(client, token, {"q": "wandering", "scope": "project", "project_id": project["id"]})
    assert [h["id"] for h in found["hits"]] == [persona["id"]]
    assert found["hits"][0]["project_id"] == project["id"] and found["hits"][0]["status_label"] == "Draft"
