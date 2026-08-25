"""Tests for the optional `active_only` query param on
`GET /projects/{project_id}/change-requests` (2026-08 UX audit roadmap,
"Default Change Requests to an active-only status filter") — pins that
`active_only=true` narrows to the three non-terminal statuses
(draft/submitted/in_review), that omitting both `active_only` and
`cr_status` still returns every status (the existing, unchanged default),
and that an explicit `cr_status` wins over `active_only` when both are
somehow present."""

from tests.conftest import auth_headers, create_project


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
