"""Tests for PR7 of the members/groups directory rework plan (docs/
decisions.md): a `ProjectGroup`'s role is no longer a single, required field
fixed at creation — it now holds zero, one, or several independently-
revocable roles, each its own `ProjectGroupRole` row, granted/revoked via
`POST`/`DELETE /projects/{id}/groups/{group_id}/roles[/{role}]`. This is the
group-level counterpart to `test_org_group_project_roles.py`'s
`OrgGroupProjectRole` coverage (PR4), mirroring its shape closely, plus the
migration backfill that converted every pre-existing group's old scalar
`role` into exactly one grant row.

This file used to cover `PATCH /projects/{id}/groups/{group_id}` (making a
project group's role editable after creation, Phase 5) — that endpoint no
longer exists (there is no longer a single mutable `role` field to PATCH);
its coverage is replaced by the grant/revoke tests below. The delete/
member-removal C-U-08 guard tests and the engagement-cleanup regression
tests carry over, adapted to the new group-creation shape (bare, then a
role granted separately) and to `_get_group_roles`'s new reads.

Both group-scoped mutating endpoints (create/grant/revoke/delete/member add-
remove) share `require_project_manage`'s gate tier, same as before.
"""

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import ProjectGroupRole
from tests.conftest import auth_headers, create_org_user, create_project, login


def _create_group(client, token, project_id, name: str, role: str | None = None) -> dict:
    """Creates a bare project group (PR7: `ProjectGroupCreate` no longer
    accepts a role at all), then optionally grants it one role via the new
    `POST .../groups/{group_id}/roles` endpoint — the two-call replacement
    for the old single `POST .../groups` with `role` in the payload."""
    group = client.post(
        f"/api/v1/projects/{project_id}/groups", json={"name": name}, headers=auth_headers(token)
    ).json()
    if role is not None:
        resp = client.post(
            f"/api/v1/projects/{project_id}/groups/{group['id']}/roles",
            json={"role": role}, headers=auth_headers(token),
        )
        assert resp.status_code == 204, resp.text
        group["roles"] = [role]
    return group


def _grant(client, token, project_id, group_id, role):
    return client.post(
        f"/api/v1/projects/{project_id}/groups/{group_id}/roles",
        json={"role": role}, headers=auth_headers(token),
    )


def _revoke(client, token, project_id, group_id, role):
    return client.delete(
        f"/api/v1/projects/{project_id}/groups/{group_id}/roles/{role}", headers=auth_headers(token)
    )


def _effective_sources_for(client, admin_token, project_id, user_id) -> list[dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/effective-members", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    member = next((m for m in resp.json() if m["user_id"] == user_id), None)
    return member["sources"] if member else []


def _kinds_for_role(sources: list[dict], role: str) -> set[str]:
    return {s["kind"] for s in sources if s["role"] == role}


def _make_group_the_sole_manager(client, admin_token, org_id, project_id) -> dict:
    """Creates a manager-role group with a *different* user as its only
    member, then revokes the project creator's own direct manager grant
    (C-U-10) — leaving the new group as the project's only manager source.

    `revoke_project_role`'s own C-U-08 guard only blocks removing a
    direct grant when the grantee would become the project's *sole*
    effective manager afterward (and isn't also an inherited manager) — so
    this only works cleanly because the new group's member is someone
    other than the creator: with two independent manager sources (the
    creator's direct grant, the new group), revoking the creator's direct
    grant leaves exactly one (the group), and the revoke itself is never
    blocked by the very guard this helper exists to set up a test for.
    """
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    other_id = create_org_user(client, admin_token, org_id, "sole-manager-source@example.com", role="member")
    group = _create_group(client, admin_token, project_id, "Managers", role="project_manager")
    added = client.post(
        f"/api/v1/projects/{project_id}/groups/{group['id']}/members",
        json={"user_id": other_id}, headers=auth_headers(admin_token),
    )
    assert added.status_code == 204, added.text
    revoke = client.delete(
        f"/api/v1/projects/{project_id}/roles/{me['id']}/project_manager", headers=auth_headers(admin_token)
    )
    assert revoke.status_code == 204, revoke.text
    return group


# --- Create: no role required any more ---------------------------------------


def test_create_group_has_no_role_and_starts_with_empty_roles_list(client, admin_token, org_id):
    """PR7: `POST .../groups` no longer accepts (or requires) a role — a
    freshly created group starts with zero roles, symmetric with how a
    freshly created org group already has none."""
    project = create_project(client, admin_token, org_id)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Bare Group"}, headers=auth_headers(admin_token)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["roles"] == []
    assert "role" not in body

    listed = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next(g for g in listed if g["id"] == body["id"])
    assert reloaded["roles"] == []


def test_create_group_ignores_a_stray_role_field_in_the_payload(client, admin_token, org_id):
    """Defense against a stale client (or bundle importer) still sending the
    retired `role` field: pydantic silently drops unknown fields, so this
    must not error, and must not grant anything either."""
    project = create_project(client, admin_token, org_id)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/groups",
        json={"name": "Stray Role Field", "role": "project_manager"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["roles"] == []


# --- Grant / revoke basics ---------------------------------------------------


def test_grant_gives_group_member_effective_role_with_provenance(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Direct Project Group Grant")
    user_id = create_org_user(client, admin_token, org_id, "project-group-grant-user@example.com", role="member")
    group = _create_group(client, admin_token, project["id"], "Grant Recipients")
    add_member = client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )
    assert add_member.status_code == 204, add_member.text

    assert _grant(client, admin_token, project["id"], group["id"], "stakeholder").status_code == 204

    sources = _effective_sources_for(client, admin_token, project["id"], user_id)
    entries = [s for s in sources if s["kind"] == "direct_group" and s["role"] == "stakeholder"]
    assert len(entries) == 1, sources
    assert entries[0]["via_group_id"] == group["id"]
    assert entries[0]["via_group_name"] == "Grant Recipients"

    token = login(client, "project-group-grant-user@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token)).status_code == 200


def test_revoke_removes_the_grant(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Direct Project Group Revoke")
    user_id = create_org_user(client, admin_token, org_id, "project-group-revoke-user@example.com", role="member")
    group = _create_group(client, admin_token, project["id"], "Revoke Recipients")
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )
    assert _grant(client, admin_token, project["id"], group["id"], "stakeholder").status_code == 204
    assert _kinds_for_role(_effective_sources_for(client, admin_token, project["id"], user_id), "stakeholder") == {
        "direct_group"
    }

    assert _revoke(client, admin_token, project["id"], group["id"], "stakeholder").status_code == 204

    sources = _effective_sources_for(client, admin_token, project["id"], user_id)
    assert _kinds_for_role(sources, "stakeholder") == set(), "the role must be fully gone after revoke"

    db = SessionLocal()
    try:
        remaining = db.scalars(
            select(ProjectGroupRole).where(
                ProjectGroupRole.project_group_id == group["id"], ProjectGroupRole.role == "stakeholder"
            )
        ).all()
    finally:
        db.close()
    assert remaining == []


def test_grant_is_idempotent_no_duplicate_row_or_error(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Idempotent Project Group Grant")
    group = _create_group(client, admin_token, project["id"], "Idempotent Group")

    assert _grant(client, admin_token, project["id"], group["id"], "member").status_code == 204
    assert _grant(client, admin_token, project["id"], group["id"], "member").status_code == 204

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(ProjectGroupRole).where(ProjectGroupRole.project_group_id == group["id"])
        ).all()
    finally:
        db.close()
    assert len(rows) == 1, "granting the same (group, role) twice must not create a duplicate row"


def test_revoke_of_a_nonexistent_grant_is_a_no_op_204(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Project Group Revoke Noop")
    group = _create_group(client, admin_token, project["id"], "Never Granted Group")
    assert _revoke(client, admin_token, project["id"], group["id"], "member").status_code == 204


def test_grant_and_revoke_require_project_manage(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Non Manager Project Group Grant")
    group = _create_group(client, admin_token, project["id"], "Non Manager Group")
    outsider_id = create_org_user(client, admin_token, org_id, "non-manager-pg-grant@example.com", role="member")
    outsider_token = login(client, "non-manager-pg-grant@example.com", "Password123!")

    assert _grant(client, outsider_token, project["id"], group["id"], "member").status_code == 403

    assert client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": outsider_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).status_code == 204
    stakeholder_token = login(client, "non-manager-pg-grant@example.com", "Password123!")
    assert _grant(client, stakeholder_token, project["id"], group["id"], "member").status_code == 403

    assert _grant(client, admin_token, project["id"], group["id"], "member").status_code == 204
    assert _revoke(client, stakeholder_token, project["id"], group["id"], "member").status_code == 403


def test_grant_and_revoke_are_audit_logged(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Audited Project Group Grant")
    group = _create_group(client, admin_token, project["id"], "Audited Group")

    assert _grant(client, admin_token, project["id"], group["id"], "stakeholder").status_code == 204
    assert _revoke(client, admin_token, project["id"], group["id"], "stakeholder").status_code == 204

    db = SessionLocal()
    try:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "project_group", AuditEvent.entity_id == group["id"],
                    AuditEvent.action.in_(["role_granted", "role_revoked"]),
                )
            )
        )
    finally:
        db.close()
    actions = [e.action for e in events]
    assert "role_granted" in actions
    assert "role_revoked" in actions
    granted_event = next(e for e in events if e.action == "role_granted")
    revoked_event = next(e for e in events if e.action == "role_revoked")
    assert granted_event.detail.get("role") == "stakeholder"
    assert revoked_event.detail.get("role") == "stakeholder"
    assert granted_event.project_id is not None and str(granted_event.project_id) == project["id"]


def test_idempotent_grant_no_op_does_not_create_a_second_audit_event(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Idempotent Project Group Audit")
    group = _create_group(client, admin_token, project["id"], "Idempotent Audit Group")
    assert _grant(client, admin_token, project["id"], group["id"], "member").status_code == 204
    assert _grant(client, admin_token, project["id"], group["id"], "member").status_code == 204

    db = SessionLocal()
    try:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "project_group", AuditEvent.entity_id == group["id"],
                    AuditEvent.action == "role_granted",
                )
            )
        )
    finally:
        db.close()
    assert len(events) == 1, "a no-op re-grant must not log a second audit event"


# --- Multiplicity: a group can hold more than one role at once --------------


def test_group_holding_two_roles_produces_two_provenance_entries_for_its_members(client, admin_token, org_id):
    """The core PR7 behaviour: a group is no longer limited to one role.
    Both grants must show up as two separate `direct_group` Source entries
    for the same member, not collapsed into one — the same "one line per
    source" principle PR1 established for two *different* groups granting
    the same role, applied here the other way round (one group granting two
    different roles)."""
    project = create_project(client, admin_token, org_id, "Two Roles One Group Project")
    user_id = create_org_user(client, admin_token, org_id, "two-roles-one-group@example.com", role="member")
    group = _create_group(client, admin_token, project["id"], "Dual Role Group")
    add_member = client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )
    assert add_member.status_code == 204, add_member.text

    assert _grant(client, admin_token, project["id"], group["id"], "stakeholder").status_code == 204
    assert _grant(client, admin_token, project["id"], group["id"], "member").status_code == 204

    listed = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next(g for g in listed if g["id"] == group["id"])
    assert set(reloaded["roles"]) == {"stakeholder", "member"}

    sources = _effective_sources_for(client, admin_token, project["id"], user_id)
    group_sources = [s for s in sources if s["kind"] == "direct_group"]
    assert {s["role"] for s in group_sources} == {"stakeholder", "member"}
    assert len(group_sources) == 2, "two roles granted by the same group must be two distinct Source entries"
    assert all(s["via_group_id"] == group["id"] for s in group_sources)


def test_two_different_groups_granting_the_same_role_still_produce_two_entries(client, admin_token, org_id):
    """Regression check that PR7's join-through-the-grant-table rewrite of
    the `direct_group` provenance branch didn't disturb PR1's existing
    two-*different*-groups behaviour."""
    project = create_project(client, admin_token, org_id, "Two Groups Same Role Project")
    user_id = create_org_user(client, admin_token, org_id, "two-groups-same-role@example.com", role="member")
    group_a = _create_group(client, admin_token, project["id"], "Alpha Group", role="member")
    group_b = _create_group(client, admin_token, project["id"], "Beta Group", role="member")
    for group in (group_a, group_b):
        added = client.post(
            f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
            json={"user_id": user_id}, headers=auth_headers(admin_token),
        )
        assert added.status_code == 204, added.text

    sources = _effective_sources_for(client, admin_token, project["id"], user_id)
    entries = [s for s in sources if s["kind"] == "direct_group" and s["role"] == "member"]
    assert len(entries) == 2, sources
    assert {e["via_group_id"] for e in entries} == {group_a["id"], group_b["id"]}


# --- C-U-08 "at least one manager" guard, in its new (per-role) form --------


def test_revoke_manager_role_blocked_when_sole_manager(client, admin_token, org_id):
    """C-U-08's new form: revoking a group's *sole* `project_manager` grant
    is rejected when doing so would leave the project with zero managers —
    the direct successor to the old `PATCH .../groups/{id}` "role away from
    manager" guard, now expressed as a role revocation instead of a field
    update."""
    project = create_project(client, admin_token, org_id)
    manager_group = _make_group_the_sole_manager(client, admin_token, org_id, project["id"])

    resp = _revoke(client, admin_token, project["id"], manager_group["id"], "project_manager")
    assert resp.status_code == 400, resp.text

    # Rolled back entirely: the group still holds the role.
    listed = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next(g for g in listed if g["id"] == manager_group["id"])
    assert reloaded["roles"] == ["project_manager"]


def test_revoke_manager_role_allowed_with_backup_manager(client, admin_token, org_id):
    """The same revoke succeeds once a backup manager source exists — the
    guard re-checks *actual* effective managers after the change, not just
    whether this specific group used to grant it."""
    project = create_project(client, admin_token, org_id)
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    manager_group = _make_group_the_sole_manager(client, admin_token, org_id, project["id"])

    backup_group = _create_group(client, admin_token, project["id"], "Backup Managers", role="project_manager")
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{backup_group['id']}/members",
        json={"user_id": me["id"]}, headers=auth_headers(admin_token),
    )

    resp = _revoke(client, admin_token, project["id"], manager_group["id"], "project_manager")
    assert resp.status_code == 204, resp.text

    listed = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    reloaded = next(g for g in listed if g["id"] == manager_group["id"])
    assert reloaded["roles"] == []


def test_group_response_has_no_role_field_and_delete_has_no_special_cases(client, admin_token, org_id):
    """`role` was removed from `ProjectGroupOut` entirely (replaced by
    `roles`), and `delete_project_group` still doesn't special-case any
    group — the only remaining delete guard is C-U-08, which applies
    uniformly regardless of how a group came to exist. This project's
    creator already holds a direct PROJECT_MANAGER grant (C-U-10), so a
    brand-new manager-role group here is never the project's sole manager
    source and is freely deletable."""
    project = create_project(client, admin_token, org_id)
    group = _create_group(client, admin_token, project["id"], "Extra Managers", role="project_manager")
    assert "role" not in group
    assert group["roles"] == ["project_manager"]

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text


def test_delete_custom_manager_group_blocked_when_sole_manager(client, admin_token, org_id):
    """C-U-08 on delete: a group holding a `project_manager` grant can
    normally be deleted, but not if doing so would leave the project with
    zero managers."""
    project = create_project(client, admin_token, org_id)
    custom_group = _make_group_the_sole_manager(client, admin_token, org_id, project["id"])

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{custom_group['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 400, resp.text

    listed = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    assert any(g["id"] == custom_group["id"] for g in listed)


def test_delete_custom_manager_group_allowed_with_backup_manager(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    custom_group = _create_group(client, admin_token, project["id"], "Extra Managers", role="project_manager")
    client.post(
        f"/api/v1/projects/{project['id']}/groups/{custom_group['id']}/members",
        json={"user_id": me["id"]}, headers=auth_headers(admin_token),
    )
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{custom_group['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text
    listed = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    assert not any(g["id"] == custom_group["id"] for g in listed)


def test_delete_group_holding_manager_role_alongside_others_is_still_guarded(client, admin_token, org_id):
    """A group holding `project_manager` *and* another role at once is
    still caught by the delete guard for the manager grant specifically —
    multiplicity doesn't weaken the C-U-08 check."""
    project = create_project(client, admin_token, org_id)
    group = _make_group_the_sole_manager(client, admin_token, org_id, project["id"])
    assert _grant(client, admin_token, project["id"], group["id"], "stakeholder").status_code == 204

    resp = client.delete(f"/api/v1/projects/{project['id']}/groups/{group['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 400, resp.text


def test_grant_and_revoke_gated_at_manage_tier(client, admin_token, org_id):
    """403 for a role below project-manage tier (a plain project member);
    success for an org admin of the project's own organisation who holds no
    project role at all, per `can_manage_project_settings`'s existing
    carve-out (C-U-01 clarification)."""
    project = create_project(client, admin_token, org_id)
    group = _create_group(client, admin_token, project["id"], "Gate Test")

    plain_member_id = create_org_user(client, admin_token, org_id, "pg-gate-member@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": plain_member_id, "role": "member"},
        headers=auth_headers(admin_token),
    )
    member_token = login(client, "pg-gate-member@example.com", "Password123!")
    assert _grant(client, member_token, project["id"], group["id"], "stakeholder").status_code == 403

    org_admin_id = create_org_user(client, admin_token, org_id, "pg-gate-org-admin@example.com", role="org_admin")
    assert org_admin_id
    org_admin_token = login(client, "pg-gate-org-admin@example.com", "Password123!")
    assert _grant(client, org_admin_token, project["id"], group["id"], "stakeholder").status_code == 204
    assert _revoke(client, org_admin_token, project["id"], group["id"], "stakeholder").status_code == 204


# --- Engagement cleanup regressions (unchanged mechanism, still pinned) -----


def test_removing_a_nested_org_group_member_cleans_up_its_users_favourites(client, admin_token, org_id):
    """Pre-existing regression pin (PR4, docs/decisions.md), carried over
    unchanged by PR7's group-creation shape update:
    `remove_project_group_member`'s engagement cleanup resolves a removed
    nested org group's real member set (direct + nested descendants) before
    deciding whether to clean up favourites/subscriptions."""
    project = create_project(client, admin_token, org_id)
    member_id = create_org_user(client, admin_token, org_id, "nested-group-member@example.com", role="member")
    member_token = login(client, "nested-group-member@example.com", "Password123!")

    org_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Nested Reviewers"}, headers=auth_headers(admin_token)
    ).json()
    add_org_member = client.post(
        f"/api/v1/orgs/{org_id}/groups/{org_group['id']}/members",
        json={"user_id": member_id}, headers=auth_headers(admin_token),
    )
    assert add_org_member.status_code == 204, add_org_member.text

    project_group = _create_group(client, admin_token, project["id"], "Via Org Group", role="stakeholder")
    add_nested = client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members",
        json={"org_group_id": org_group["id"]}, headers=auth_headers(admin_token),
    )
    assert add_nested.status_code == 204, add_nested.text

    favorite = client.put(f"/api/v1/projects/{project['id']}/favorite", headers=auth_headers(member_token))
    assert favorite.status_code == 204, favorite.text
    listing = client.get("/api/v1/projects", headers=auth_headers(member_token)).json()
    assert next(p for p in listing if p["id"] == project["id"])["is_favorite"] is True

    remove = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members/{org_group['id']}",
        headers=auth_headers(admin_token),
    )
    assert remove.status_code == 204, remove.text

    listing_after = client.get("/api/v1/projects", headers=auth_headers(member_token)).json()
    assert not any(p["id"] == project["id"] for p in listing_after)


def test_removing_a_project_reference_member_cleans_up_its_roster_favourites(client, admin_token, org_id):
    """Same regression as above, for the third `ProjectGroupMember` kind:
    `source_project_id` ("this group's members = that other project's
    roster")."""
    source_project = create_project(client, admin_token, org_id)
    receiving_project = create_project(client, admin_token, org_id)
    member_id = create_org_user(client, admin_token, org_id, "source-roster-member@example.com", role="member")
    member_token = login(client, "source-roster-member@example.com", "Password123!")
    grant = client.post(
        f"/api/v1/projects/{source_project['id']}/roles", json={"user_id": member_id, "role": "member"},
        headers=auth_headers(admin_token),
    )
    assert grant.status_code == 204, grant.text

    project_group = _create_group(client, admin_token, receiving_project["id"], "Via Source Project", role="member")
    add_ref = client.post(
        f"/api/v1/projects/{receiving_project['id']}/groups/{project_group['id']}/members",
        json={"source_project_id": source_project["id"]}, headers=auth_headers(admin_token),
    )
    assert add_ref.status_code == 204, add_ref.text

    favorite = client.put(f"/api/v1/projects/{receiving_project['id']}/favorite", headers=auth_headers(member_token))
    assert favorite.status_code == 204, favorite.text
    listing = client.get("/api/v1/projects", headers=auth_headers(member_token)).json()
    assert next(p for p in listing if p["id"] == receiving_project["id"])["is_favorite"] is True

    remove = client.delete(
        f"/api/v1/projects/{receiving_project['id']}/groups/{project_group['id']}/members/{source_project['id']}",
        headers=auth_headers(admin_token),
    )
    assert remove.status_code == 204, remove.text

    listing_after = client.get("/api/v1/projects", headers=auth_headers(member_token)).json()
    assert not any(p["id"] == receiving_project["id"] for p in listing_after)


def test_revoking_a_role_cleans_up_the_left_behind_members_favourites(client, admin_token, org_id):
    """New engagement-cleanup path this PR adds (`revoke_project_group_role`):
    revoking a group's role must clean up favourites/subscriptions for any
    member left with no remaining access, mirroring `revoke_group_project_
    role`'s (PR4) equivalent per-member cleanup."""
    project = create_project(client, admin_token, org_id)
    member_id = create_org_user(client, admin_token, org_id, "revoke-role-cleanup@example.com", role="member")
    member_token = login(client, "revoke-role-cleanup@example.com", "Password123!")
    group = _create_group(client, admin_token, project["id"], "Cleanup Group", role="stakeholder")
    added = client.post(
        f"/api/v1/projects/{project['id']}/groups/{group['id']}/members",
        json={"user_id": member_id}, headers=auth_headers(admin_token),
    )
    assert added.status_code == 204, added.text

    favorite = client.put(f"/api/v1/projects/{project['id']}/favorite", headers=auth_headers(member_token))
    assert favorite.status_code == 204, favorite.text

    assert _revoke(client, admin_token, project["id"], group["id"], "stakeholder").status_code == 204

    listing_after = client.get("/api/v1/projects", headers=auth_headers(member_token)).json()
    assert not any(p["id"] == project["id"] for p in listing_after)
