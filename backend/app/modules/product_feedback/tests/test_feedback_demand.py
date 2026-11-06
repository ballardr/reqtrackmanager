"""Tests for Product Feedback demand aggregation: the "Requested by" link, the generic `demand_party_providers`
hook (Module 2's Stakeholder, Persona and Engagement providers), de-duplication, weighting, visibility and the
demand fields on the list. Every test builds its own organisation."""

from __future__ import annotations

from app.modules.product_feedback.tests._helpers import (
    add_requester,
    create_engagement,
    create_inbox_request,
    create_persona,
    create_request,
    create_stakeholder,
    get_demand,
    get_request,
    org_base,
    project_base,
    setup,
    setup_with_people,
)
from app.modules.registry import get_all_link_type_seeds, get_module, resolve_demand_parties
from tests.conftest import auth_headers


def _requesters(demand: dict) -> dict[str, dict]:
    return {r["label"]: r for r in demand["requesters"]}


def test_requested_by_is_a_seeded_link_type_that_only_a_request_can_use_toward_people_and_engagements():
    seed = get_all_link_type_seeds()["Requested by"]
    assert seed.reverse_name == "Requests"
    assert seed.allowed_source_types == ("enhancement_request",)
    assert set(seed.allowed_target_types or ()) == {"stakeholder", "persona", "engagement"}


def test_demand_sums_stakeholder_influence_and_persona_weight_and_counts_the_unweighted_as_one(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Demand Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    high = create_stakeholder(client, token, pid, "Hana High", influence="High", org_id=org["id"])
    low = create_stakeholder(client, token, pid, "Lou Low", influence="Low", org_id=org["id"])
    unrated = create_stakeholder(client, token, pid, "Una Unrated")
    heavy = create_persona(client, token, pid, "Heavy user", weight=2.5)
    for kind, record in (("stakeholder", high), ("stakeholder", low), ("stakeholder", unrated), ("persona", heavy)):
        resp = add_requester(client, token, org["id"], pid, request["id"], kind, record["id"])
        assert resp.status_code == 201, resp.text

    demand = get_demand(client, token, pid, request["id"])
    by_label = _requesters(demand)
    assert by_label["Hana High"]["weight"] == 3 and by_label["Lou Low"]["weight"] == 1
    assert by_label["Una Unrated"]["weight"] is None and by_label["Una Unrated"]["effective_weight"] == 1
    assert by_label["Heavy user"]["weight"] == 2.5
    assert [by_label[n]["weight_source"] for n in ("Hana High", "Una Unrated", "Heavy user")] == ["influence", "none", "persona"]
    assert demand["requester_count"] == 4 and demand["weighted_demand"] == 3 + 1 + 1 + 2.5
    assert [r["label"] for r in demand["requesters"]][0] == "Hana High"  # heaviest first

    shown = get_request(client, token, pid, request["id"])
    assert shown["requester_count"] == 4 and shown["weighted_demand"] == 7.5
    listed = client.get(project_base(pid) + "/requests", headers=auth_headers(token)).json()
    assert listed[0]["requester_count"] == 4 and listed[0]["weighted_demand"] == 7.5


def test_an_engagement_counts_its_participants_and_covered_personas_and_nobody_twice(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Engagement Demand Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    ann = create_stakeholder(client, token, pid, "Ann", influence="Medium", org_id=org["id"])
    bob = create_stakeholder(client, token, pid, "Bob")
    persona = create_persona(client, token, pid, "Technician", weight=4)
    workshop = create_engagement(client, token, pid, "Field workshop", stakeholder_ids=[ann["id"], bob["id"]], persona_ids=[persona["id"]])

    assert add_requester(client, token, org["id"], pid, request["id"], "engagement", workshop["id"]).status_code == 201
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", ann["id"]).status_code == 201

    demand = get_demand(client, token, pid, request["id"])
    assert sorted(_requesters(demand)) == ["Ann", "Bob", "Technician"]  # Ann reached twice, counted once
    assert demand["requester_count"] == 3 and demand["weighted_demand"] == 2 + 1 + 4
    assert _requesters(demand)["Ann"]["via_engagement"] is True
    assert [e["id"] for e in demand["engagements"]] == [workshop["id"]]
    assert demand["engagements"][0]["label"].endswith("Field workshop")


def test_an_engagement_with_nobody_in_it_adds_no_demand_but_is_listed(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Empty Engagement Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    empty = create_engagement(client, token, pid, "Empty call")
    assert add_requester(client, token, org["id"], pid, request["id"], "engagement", empty["id"]).status_code == 201
    demand = get_demand(client, token, pid, request["id"])
    assert demand["requester_count"] == 0 and demand["weighted_demand"] == 0
    assert [e["id"] for e in demand["engagements"]] == [empty["id"]]


def test_a_request_with_no_requesters_has_zero_demand_and_the_link_is_refused_toward_other_types(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback No Demand Co")
    pid = project["id"]
    request, other = create_request(client, token, pid), create_request(client, token, pid, title="Other")
    assert get_demand(client, token, pid, request["id"])["requester_count"] == 0
    refused = add_requester(client, token, org["id"], pid, request["id"], "enhancement_request", other["id"])
    assert refused.status_code in (400, 409, 422), refused.text


def test_a_stakeholder_hidden_from_the_project_is_neither_counted_nor_named(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Hidden Demand Co")
    pid, h = project["id"], auth_headers(token)
    request = create_request(client, token, pid)
    shared = client.post(
        f"/api/v1/orgs/{org['id']}/modules/stakeholders/stakeholders", json={"name": "Shared Regulator"}, headers=h,
    ).json()
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", shared["id"]).status_code == 201
    assert get_demand(client, token, pid, request["id"])["requester_count"] == 1

    hidden = client.put(
        f"{project_base(pid).replace('product_feedback', 'stakeholders')}/stakeholders/{shared['id']}/visibility",
        json={"hidden": True}, headers=h,
    )
    assert hidden.status_code == 200, hidden.text
    demand = get_demand(client, token, pid, request["id"])
    assert demand["requester_count"] == 0 and demand["requesters"] == []


def test_demand_is_empty_while_the_people_module_is_off(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback People Off Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    person = create_stakeholder(client, token, pid, "Pat")
    assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", person["id"]).status_code == 201
    assert get_demand(client, token, pid, request["id"])["requester_count"] == 1
    off = client.put(f"/api/v1/orgs/{org['id']}/modules/stakeholders", json={"enabled": False}, headers=auth_headers(token))
    assert off.status_code == 200, off.text
    assert get_demand(client, token, pid, request["id"])["requester_count"] == 0  # nothing is known about them


def test_resolve_demand_parties_is_empty_for_an_unknown_type_and_for_another_projects_records(client, admin_token):
    from app.database import SessionLocal

    org, project, token = setup_with_people(client, admin_token, "Feedback Provider Co")
    other = client.post(
        "/api/v1/projects", json={"name": "Elsewhere", "organization_id": org["id"]}, headers=auth_headers(token),
    )
    elsewhere = create_stakeholder(client, token, other.json()["id"], "Elsewhere person")
    import uuid

    with SessionLocal() as db:
        assert resolve_demand_parties(db, uuid.UUID(project["id"]), "no_such_type", [uuid.UUID(elsewhere["id"])]) == {}
        assert resolve_demand_parties(db, uuid.UUID(project["id"]), "stakeholder", [uuid.UUID(elsewhere["id"])]) == {}
        assert resolve_demand_parties(db, uuid.UUID(project["id"]), "stakeholder", []) == {}


def test_the_stakeholders_module_registers_the_three_providers():
    module = get_module("stakeholders")
    assert module is not None and set(module.demand_party_providers) == {"stakeholder", "persona", "engagement"}


def test_an_inbox_request_has_no_demand_fields_set(client, admin_token):
    org, _, token = setup(client, admin_token, "Feedback Inbox Demand Co")
    inbox = create_inbox_request(client, token, org["id"])
    shown = client.get(f"{org_base(org['id'])}/requests/{inbox['id']}", headers=auth_headers(token)).json()
    assert shown["requester_count"] == 0 and shown["weighted_demand"] == 0 and shown["merged_into"] is None


def _statements_for_list(client, token, project_id) -> int:
    """SQL statements behind one list request, after an identical warm-up request."""
    from sqlalchemy import event

    from app.database import engine

    url = project_base(project_id) + "/requests"
    assert client.get(url, headers=auth_headers(token)).status_code == 200
    seen: list[str] = []

    def count(_conn, _cursor, statement, *_args, **_kwargs) -> None:
        if "generated_reports" not in statement:  # the report job loop polls on the same engine
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert client.get(url, headers=auth_headers(token)).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(seen)


def test_the_list_reads_demand_in_a_fixed_number_of_statements(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Flat Demand Co")
    pid, base = project["id"], project_base(project["id"])
    person = create_stakeholder(client, token, pid, "Pat", influence="High", org_id=org["id"])
    persona = create_persona(client, token, pid, "Tech", weight=2)
    workshop = create_engagement(client, token, pid, stakeholder_ids=[person["id"]], persona_ids=[persona["id"]])

    def add(n: int) -> list[dict]:
        made = [create_request(client, token, pid, title=f"Request {i}") for i in range(n)]
        for request in made:
            for kind, record in (("stakeholder", person), ("persona", persona), ("engagement", workshop)):
                assert add_requester(client, token, org["id"], pid, request["id"], kind, record["id"]).status_code == 201
        return made

    def merge(duplicate: dict, canonical: dict) -> None:
        resp = client.post(
            f"{base}/requests/{duplicate['id']}/merge", json={"canonical_id": canonical["id"]}, headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text

    first = add(2)
    merge(first[1], first[0])  # a merge present at both sizes, so only its count differs
    small = _statements_for_list(client, token, pid)
    more = add(5)
    for duplicate in more[1:]:
        merge(duplicate, first[0])
    large = _statements_for_list(client, token, pid)
    assert small == large, f"list statements grew with rows: {small} -> {large}"


def test_requesters_come_a_page_at_a_time_while_the_totals_cover_every_requester(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Demand Page Co")
    pid = project["id"]
    h = auth_headers(token)
    request = create_request(client, token, pid)
    for i in range(7):
        person = create_stakeholder(client, token, pid, f"Person {i}", influence="High" if i == 5 else None, org_id=org["id"])
        assert add_requester(client, token, org["id"], pid, request["id"], "stakeholder", person["id"]).status_code == 201
    url = f"{project_base(pid)}/requests/{request['id']}/demand"

    first = client.get(url, params={"limit": 3}, headers=h).json()
    assert first["requester_count"] == 7 and first["weighted_demand"] == 3 + 6  # one High (3) and six unrated (1 each)
    assert (first["offset"], first["limit"], len(first["requesters"])) == (0, 3, 3)
    assert first["requesters"][0]["label"] == "Person 5"  # heaviest first
    second = client.get(url, params={"limit": 3, "offset": 3}, headers=h).json()
    last = client.get(url, params={"limit": 3, "offset": 6}, headers=h).json()
    pages = [r["label"] for page in (first, second, last) for r in page["requesters"]]
    assert len(pages) == 7 and len(set(pages)) == 7  # every requester exactly once across the pages
    assert second["requester_count"] == 7 and len(last["requesters"]) == 1
    assert client.get(url, params={"offset": 99}, headers=h).json()["requesters"] == []
    assert client.get(url, params={"limit": 0}, headers=h).status_code == 422
    assert client.get(url, params={"limit": 501}, headers=h).status_code == 422


def test_a_requester_or_engagement_added_by_mistake_is_removed_with_the_link_the_demand_names(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Demand Remove Co")
    pid, h = project["id"], auth_headers(token)
    request = create_request(client, token, pid)
    other = create_request(client, token, pid, title="Duplicate")
    ann = create_stakeholder(client, token, pid, "Ann", org_id=org["id"])
    bob = create_stakeholder(client, token, pid, "Bob")
    cat = create_stakeholder(client, token, pid, "Cat")
    workshop = create_engagement(client, token, pid, "Field workshop", stakeholder_ids=[bob["id"]])
    for kind, record in (("stakeholder", ann), ("engagement", workshop)):
        assert add_requester(client, token, org["id"], pid, request["id"], kind, record["id"]).status_code == 201
    assert add_requester(client, token, org["id"], pid, other["id"], "stakeholder", cat["id"]).status_code == 201
    assert client.post(
        f"{project_base(pid)}/requests/{other['id']}/merge", json={"canonical_id": request["id"]}, headers=h,
    ).status_code == 200

    demand = get_demand(client, token, pid, request["id"])
    people = _requesters(demand)
    # Only the request's own direct link can be removed: Bob is reached through the Engagement, Cat through a merge.
    assert people["Ann"]["link_id"] is not None
    assert people["Bob"]["link_id"] is None and people["Cat"]["link_id"] is None
    assert demand["engagements"][0]["link_id"] is not None

    base = f"/api/v1/projects/{pid}/artefacts/enhancement_request/{request['id']}/links"
    assert client.delete(f"{base}/{people['Ann']['link_id']}", headers=h).status_code == 204
    after = get_demand(client, token, pid, request["id"])
    assert sorted(_requesters(after)) == ["Bob", "Cat"]
    # Removing the Engagement removes the people only it reached; the merged duplicate's requester stays.
    assert client.delete(f"{base}/{after['engagements'][0]['link_id']}", headers=h).status_code == 204
    final = get_demand(client, token, pid, request["id"])
    assert sorted(_requesters(final)) == ["Cat"] and final["engagements"] == []
    assert final["requester_count"] == 1
