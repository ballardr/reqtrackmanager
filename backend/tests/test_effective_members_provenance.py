"""Tests for the follow-up UX batch's Phase D (2026-08-31, docs/decisions.md):
splitting `GET /{project_id}/effective-members`'s collapsed `kind: "direct"`
provenance bucket into five finer-grained kinds (`direct_role`,
`direct_group`, `direct_org_group`, `direct_project_ref`, `direct_org_wide`
— see `services.rbac._direct_effective_project_roles_by_kind`'s docstring),
and the endpoint's new application-level `search`/`limit`/`offset` support.

The kind split is the highest-risk change in this phase: the new frontend
Members table only offers `DELETE /{project_id}/roles/{user_id}/{role}` as a
way to toggle a role off when its *only* source is `direct_role` — every
other kind must never be presented as freely revocable that way, since that
endpoint only ever deletes `UserProjectRole` rows and would otherwise 204 as
a silent no-op while a group/org-wide-derived role stays in effect. The
tests below pin that (a) all five kinds are distinguishable when a user
holds the same role via every source at once, (b) different roles via
different sources aren't cross-contaminated, (c) revoking a `direct_role`
actually removes it, and (d) attempting to revoke a role whose only source
is *not* `direct_role` correctly leaves it untouched (no `UserProjectRole`
row exists to delete, so the endpoint 204s but nothing changes) — the
backend-side half of "this must not silently no-op"; the frontend's own
disabled+title treatment on the non-`direct_role` options is what actually
prevents a caller from trying in the first place.
"""

from tests.conftest import auth_headers, create_org_user, create_project


def _kinds_for_role(sources: list[dict], role: str) -> set[str]:
    return {s["kind"] for s in sources if s["role"] == role}


def test_all_five_direct_kinds_distinguished_for_one_user_one_role(client, admin_token, org_id):
    """A user holding the *same* role (`member`) simultaneously via every
    one of the five direct sources must show all five kinds separately in
    `sources`, not collapsed — the core regression this split guards
    against."""
    project = create_project(client, admin_token, org_id, "Kind Split Project")
    source_project = create_project(client, admin_token, org_id, "Kind Split Source Project")
    user_id = create_org_user(client, admin_token, org_id, "kind-split-user@example.com", role="member")

    # direct_role: a plain UserProjectRole row.
    assert client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(admin_token),
    ).status_code == 204

    # direct_group: same-project ProjectGroup membership.
    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Members Group", "role": "member"},
        headers=auth_headers(admin_token),
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    ).status_code == 204

    # direct_org_group: an org group nested into a (different) project group.
    org_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Kind Split Org Group"}, headers=auth_headers(admin_token)
    ).json()
    assert client.post(
        f"/api/v1/orgs/{org_id}/groups/{org_group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    ).status_code == 204
    org_group_project_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Org Group Nest", "role": "member"},
        headers=auth_headers(admin_token),
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/groups/{org_group_project_group['id']}/members",
        json={"org_group_id": org_group["id"]}, headers=auth_headers(admin_token),
    ).status_code == 204

    # direct_project_ref: a group whose members = source_project's own
    # direct members (any direct role there is enough to count).
    assert client.post(
        f"/api/v1/projects/{source_project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).status_code == 204
    ref_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Project Ref", "role": "member"},
        headers=auth_headers(admin_token),
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/groups/{ref_group['id']}/members",
        json={"source_project_id": source_project["id"]}, headers=auth_headers(admin_token),
    ).status_code == 204

    # direct_org_wide: ProjectVisibility.ORG_WIDE's baseline MEMBER grant —
    # the user already holds an org role by virtue of create_org_user, so no
    # further setup is needed once visibility is flipped.
    assert client.patch(
        f"/api/v1/projects/{project['id']}", json={"visibility": "org_wide"}, headers=auth_headers(admin_token)
    ).status_code == 200

    resp = client.get(f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    members = {m["user_id"]: m for m in resp.json()}
    assert user_id in members
    kinds = _kinds_for_role(members[user_id]["sources"], "member")
    assert kinds == {"direct_role", "direct_group", "direct_org_group", "direct_project_ref", "direct_org_wide"}


def test_different_roles_via_different_sources_not_cross_contaminated(client, admin_token, org_id):
    """A user holding *different* roles via *different* sources — a direct
    `project_manager` grant and a `stakeholder` grant via a group — must
    show each kind against only its own role, never the other."""
    project = create_project(client, admin_token, org_id, "Kind Split Cross Project")
    user_id = create_org_user(client, admin_token, org_id, "kind-split-cross@example.com", role="member")

    assert client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "project_manager"},
        headers=auth_headers(admin_token),
    ).status_code == 204

    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Stakeholders", "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    ).status_code == 204

    resp = client.get(f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    sources = next(m for m in resp.json() if m["user_id"] == user_id)["sources"]

    assert _kinds_for_role(sources, "project_manager") == {"direct_role"}
    assert _kinds_for_role(sources, "stakeholder") == {"direct_group"}
    # Neither role picked up the other source's kind.
    assert "direct_group" not in _kinds_for_role(sources, "project_manager")
    assert "direct_role" not in _kinds_for_role(sources, "stakeholder")


def test_revoking_a_direct_role_kind_role_actually_removes_it(client, admin_token, org_id):
    """`DELETE /{project_id}/roles/{user_id}/{role}` only ever deletes
    `UserProjectRole` rows — confirming it actually works for a role whose
    source genuinely is one (`direct_role`) is the positive case the
    disabled/negative case below is contrasted against."""
    project = create_project(client, admin_token, org_id, "Direct Role Revoke Project")
    user_id = create_org_user(client, admin_token, org_id, "direct-role-revoke@example.com", role="member")
    assert client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).status_code == 204

    before = next(
        m for m in client.get(
            f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token)
        ).json()
        if m["user_id"] == user_id
    )
    assert _kinds_for_role(before["sources"], "stakeholder") == {"direct_role"}

    assert client.delete(
        f"/api/v1/projects/{project['id']}/roles/{user_id}/stakeholder", headers=auth_headers(admin_token)
    ).status_code == 204

    after = client.get(f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token)).json()
    assert not any(m["user_id"] == user_id for m in after), "no source remains, so the user must drop out entirely"


def test_revoking_a_group_sourced_role_leaves_it_untouched(client, admin_token, org_id):
    """A role whose only source is `direct_group` (not `direct_role`) has no
    `UserProjectRole` row to delete — a caller that nonetheless calls
    `DELETE /{project_id}/roles/{user_id}/{role}` for it gets a 204 (nothing
    to violate — the delete statement's WHERE clause simply matches zero
    rows) but the role must still be in effect afterward via the group. This
    is the backend-side half of "must not silently no-op": the frontend's
    own disabled+title treatment on a non-`direct_role` option is what
    actually stops a caller from trying in the first place; this test
    confirms the backend itself doesn't compound that by actually removing
    access it was never asked to remove."""
    project = create_project(client, admin_token, org_id, "Group Revoke No-op Project")
    user_id = create_org_user(client, admin_token, org_id, "group-revoke-noop@example.com", role="member")
    group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Group Only", "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).json()
    assert client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    ).status_code == 204

    before = next(
        m for m in client.get(
            f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token)
        ).json()
        if m["user_id"] == user_id
    )
    assert _kinds_for_role(before["sources"], "stakeholder") == {"direct_group"}

    # No UserProjectRole row exists for this (user, role) — this must not
    # error, and must not remove the group-derived access either.
    assert client.delete(
        f"/api/v1/projects/{project['id']}/roles/{user_id}/stakeholder", headers=auth_headers(admin_token)
    ).status_code == 204

    after = next(
        m for m in client.get(
            f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token)
        ).json()
        if m["user_id"] == user_id
    )
    assert _kinds_for_role(after["sources"], "stakeholder") == {"direct_group"}, (
        "the group-derived stakeholder role must still be in effect — DELETE /roles has nothing to delete for it"
    )


def test_effective_members_search_narrows_results(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Search Narrow Project")
    alice = create_org_user(client, admin_token, org_id, "alice-searchtest@example.com", role="member")
    bob = create_org_user(client, admin_token, org_id, "bob-searchtest@example.com", role="member")
    for user_id in (alice, bob):
        assert client.post(
            f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
            headers=auth_headers(admin_token),
        ).status_code == 204

    resp = client.get(
        f"/api/v1/projects/{project['id']}/effective-members?search=alice-searchtest", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200, resp.text
    ids = {m["user_id"] for m in resp.json()}
    assert alice in ids
    assert bob not in ids
    assert resp.headers["x-total-count"] == "1"


def test_effective_members_limit_offset_paginate_deterministically(client, admin_token, org_id):
    """A deterministic (display_name) sort underlies `limit`/`offset` —
    the same three-user set sliced two different ways must partition
    cleanly with no overlap and no gaps, and `X-Total-Count` must reflect
    the full (post-search, pre-slice) count throughout."""
    project = create_project(client, admin_token, org_id, "Pagination Project")
    user_ids = []
    for name in ("aaron", "brianna", "carlos"):
        uid = create_org_user(client, admin_token, org_id, f"{name}-paginate@example.com", role="member")
        assert client.post(
            f"/api/v1/projects/{project['id']}/roles", json={"user_id": uid, "role": "member"},
            headers=auth_headers(admin_token),
        ).status_code == 204
        user_ids.append(uid)

    # The project creator (admin_token's own user) also holds a direct
    # PROJECT_MANAGER grant (C-U-10) and will appear too — total is 4, not 3.
    unpaginated = client.get(
        f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(admin_token)
    ).json()
    all_ids = {m["user_id"] for m in unpaginated}
    assert set(user_ids) <= all_ids
    assert len(all_ids) == 4

    first_page = client.get(
        f"/api/v1/projects/{project['id']}/effective-members?limit=2&offset=0", headers=auth_headers(admin_token)
    )
    assert first_page.status_code == 200, first_page.text
    assert first_page.headers["x-total-count"] == "4"
    first_ids = [m["user_id"] for m in first_page.json()]
    assert len(first_ids) == 2

    second_page = client.get(
        f"/api/v1/projects/{project['id']}/effective-members?limit=2&offset=2", headers=auth_headers(admin_token)
    )
    assert second_page.status_code == 200, second_page.text
    assert second_page.headers["x-total-count"] == "4"
    second_ids = [m["user_id"] for m in second_page.json()]
    assert len(second_ids) == 2

    assert set(first_ids).isdisjoint(second_ids), "the two pages must not overlap"
    assert set(first_ids) | set(second_ids) == all_ids, "the two pages together must reconstruct the full set"
