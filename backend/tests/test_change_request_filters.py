"""Tests for the optional `active_only` query param on
`GET /projects/{project_id}/change-requests` (2026-08 UX audit roadmap,
"Default Change Requests to an active-only status filter") — pins that
`active_only=true` narrows to the three non-terminal statuses
(draft/submitted/in_review), that omitting both `active_only` and
`cr_status` still returns every status (the existing, unchanged default),
and that an explicit `cr_status` wins over `active_only` when both are
somehow present. Also pins the list's default newest-first order and its
`search` param."""

from tests.conftest import auth_headers, create_component_and_category, create_project


def test_active_only_hides_terminal_statuses(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)

    draft = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "Still open", "reason": "because"},
        headers=auth_headers(admin_token),
    ).json()
    withdrawn = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "No longer needed", "reason": "because"},
        headers=auth_headers(admin_token),
    ).json()
    withdraw_resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{withdrawn['id']}/withdraw",
        headers=auth_headers(admin_token),
    )
    assert withdraw_resp.status_code == 200, withdraw_resp.text

    # Default (no active_only, no cr_status) is unchanged: every status,
    # draft and withdrawn both present.
    default = client.get(
        f"/api/v1/projects/{project['id']}/change-requests", headers=auth_headers(admin_token)
    )
    default_ids = {c["id"] for c in default.json()}
    assert {draft["id"], withdrawn["id"]}.issubset(default_ids)

    active_only = client.get(
        f"/api/v1/projects/{project['id']}/change-requests?active_only=true",
        headers=auth_headers(admin_token),
    )
    assert active_only.status_code == 200, active_only.text
    active_ids = {c["id"] for c in active_only.json()}
    assert draft["id"] in active_ids
    assert withdrawn["id"] not in active_ids
    assert {c["status"] for c in active_only.json()}.issubset({"draft", "submitted", "in_review"})


def test_explicit_cr_status_wins_over_active_only(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)

    withdrawn = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "No longer needed", "reason": "because"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{withdrawn['id']}/withdraw",
        headers=auth_headers(admin_token),
    )

    # A specific cr_status still surfaces a status active_only would hide —
    # active_only is only a default-view convenience, not a hard filter
    # that overrides an explicit request for one status.
    resp = client.get(
        f"/api/v1/projects/{project['id']}/change-requests?active_only=true&cr_status=withdrawn",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    ids = {c["id"] for c in resp.json()}
    assert withdrawn["id"] in ids
    assert {c["status"] for c in resp.json()} == {"withdrawn"}


def test_search_matches_proposed_name_reason_and_target_requirement(client, admin_token, org_id):
    """`search` matches what the list shows and what a user would type: the
    proposed name, the reason, and the target requirement's name/code
    (2026-10-04)."""
    project = create_project(client, admin_token, org_id)
    base = f"/api/v1/projects/{project['id']}/change-requests"
    headers = auth_headers(admin_token)
    named = client.post(base, json={"kind": "new_requirement", "proposed_name": "Telemetry Uplink", "reason": "alpha"},
                        headers=headers).json()
    by_reason = client.post(base, json={"kind": "new_requirement", "proposed_name": "Other", "reason": "Customer asked"},
                            headers=headers).json()

    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(f"/api/v1/projects/{project['id']}/requirements", json={
        "name": "Battery Monitor", "component_id": component_id, "category_id": category_id,
    }, headers=headers).json()
    assert client.post(f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve",
                       headers=headers).status_code == 200
    modify = client.post(base, json={"kind": "modify_requirement", "requirement_id": requirement["id"],
                                     "changed_fields": ["reasoning"], "proposed_reasoning": "x", "reason": "tweak"},
                         headers=headers)
    assert modify.status_code == 201, modify.text

    def ids(term):
        resp = client.get(base, params={"search": term}, headers=headers)
        assert resp.status_code == 200, resp.text
        return {cr["id"] for cr in resp.json()}

    assert ids("telemetry") == {named["id"]}
    assert ids("CUSTOMER") == {by_reason["id"]}
    assert ids("battery monitor") == {modify.json()["id"]}
    assert ids(requirement["unique_code"].lower()) == {modify.json()["id"]}
    assert ids("no such thing") == set()
    assert len(ids("")) == 3


def test_default_order_is_newest_first_and_pages_are_stable(client, admin_token, org_id):
    """Without `sort`, rows come newest first, so `limit`/`offset` pages
    neither repeat nor skip rows (they were previously in arbitrary order)."""
    project = create_project(client, admin_token, org_id)
    base = f"/api/v1/projects/{project['id']}/change-requests"
    created = [
        client.post(base, json={"kind": "new_requirement", "proposed_name": f"CR {i}", "reason": "because"},
                    headers=auth_headers(admin_token)).json()["id"]
        for i in range(5)
    ]
    newest_first = list(reversed(created))
    assert [c["id"] for c in client.get(base, headers=auth_headers(admin_token)).json()] == newest_first
    paged = []
    for offset in (0, 2, 4):
        paged += [c["id"] for c in client.get(f"{base}?limit=2&offset={offset}", headers=auth_headers(admin_token)).json()]
    assert paged == newest_first
