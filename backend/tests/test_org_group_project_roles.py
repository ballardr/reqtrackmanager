"""Tests for direct org-group project role grants (PR4 of the follow-up UX
batch, 2026-09, docs/decisions.md): an org group holding a project role
*directly*, as its own independently-revocable `OrgGroupProjectRole` row
(`POST`/`DELETE /{project_id}/group-roles/...`), parallel to how
`UserProjectRole` already works for a single user — genuinely distinct from,
and additive alongside, nesting an org group inside a `ProjectGroup`
(C-U-12, `test_org_group_nesting.py`).

Covers: grant/revoke and their provenance (`kind="direct_org_group_role"`,
`via_group_id`/`via_group_name`), idempotent grant, cross-tenant rejection,
403 for a non-manager, audit logging, two groups granting the same role
producing two source entries (matching the existing `direct_group`/
`direct_org_group` precedent in `test_effective_members_provenance.py`),
descendant-expansion through a nested subgroup, the C-U-08 "at least one
manager" guard's actual (narrow, documented) behavior for this mechanism,
and — the highest-risk, most novel part of this PR — the inheritance
cascade: an org group's direct grant on an ancestor/source project flowing
down through forward inheritance (`role_inheritance_mode`) and the
member-source mechanism (`ProjectMemberSource`) the same way a user's own
direct grant already does.
"""

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import OrgGroupProjectRole, UserProjectRole
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _create_org_group(client, admin_token, org_id, name):
    return client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": name}, headers=auth_headers(admin_token)
    ).json()


def _add_org_group_member(client, admin_token, org_id, group_id, user_id):
    return client.post(
        f"/api/v1/orgs/{org_id}/groups/{group_id}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )


def _nest_org_group(client, admin_token, org_id, parent_group_id, child_group_id):
    return client.post(
        f"/api/v1/orgs/{org_id}/groups/{parent_group_id}/members",
        json={"member_org_group_id": child_group_id}, headers=auth_headers(admin_token),
    )


def _grant(client, token, project_id, org_group_id, role):
    return client.post(
        f"/api/v1/projects/{project_id}/group-roles",
        json={"org_group_id": org_group_id, "role": role}, headers=auth_headers(token),
    )


def _revoke(client, token, project_id, org_group_id, role):
    return client.delete(
        f"/api/v1/projects/{project_id}/group-roles/{org_group_id}/{role}", headers=auth_headers(token)
    )


def _kinds_for_role(sources: list[dict], role: str) -> set[str]:
    return {s["kind"] for s in sources if s["role"] == role}


def _effective_sources_for(client, admin_token, project_id, user_id) -> list[dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/effective-members", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    member = next((m for m in resp.json() if m["user_id"] == user_id), None)
    return member["sources"] if member else []


# --- Grant / revoke basics ---------------------------------------------------


def test_grant_gives_group_member_effective_role_with_provenance(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Direct Group Grant Project")
    user_id = create_org_user(client, admin_token, org_id, "direct-group-grant-user@example.com", role="member")
    org_group = _create_org_group(client, admin_token, org_id, "Grant Recipients")
    assert _add_org_group_member(client, admin_token, org_id, org_group["id"], user_id).status_code == 204

    assert _grant(client, admin_token, project["id"], org_group["id"], "stakeholder").status_code == 204

    sources = _effective_sources_for(client, admin_token, project["id"], user_id)
    entries = [s for s in sources if s["kind"] == "direct_org_group_role" and s["role"] == "stakeholder"]
    assert len(entries) == 1, sources
    assert entries[0]["via_group_id"] == org_group["id"]
    assert entries[0]["via_group_name"] == "Grant Recipients"

    # Sanity: the grant is real access, not just a provenance-row artefact.
    token = login(client, "direct-group-grant-user@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token)).status_code == 200


def test_revoke_removes_the_grant(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Direct Group Revoke Project")
    user_id = create_org_user(client, admin_token, org_id, "direct-group-revoke-user@example.com", role="member")
    org_group = _create_org_group(client, admin_token, org_id, "Revoke Recipients")
    assert _add_org_group_member(client, admin_token, org_id, org_group["id"], user_id).status_code == 204
    assert _grant(client, admin_token, project["id"], org_group["id"], "stakeholder").status_code == 204
    assert _kinds_for_role(_effective_sources_for(client, admin_token, project["id"], user_id), "stakeholder") == {
        "direct_org_group_role"
    }

    assert _revoke(client, admin_token, project["id"], org_group["id"], "stakeholder").status_code == 204

    sources = _effective_sources_for(client, admin_token, project["id"], user_id)
    assert _kinds_for_role(sources, "stakeholder") == set(), "the role must be fully gone after revoke"

    db = SessionLocal()
    try:
        remaining = db.scalars(
            select(OrgGroupProjectRole).where(
                OrgGroupProjectRole.org_group_id == org_group["id"], OrgGroupProjectRole.project_id == project["id"]
            )
        ).all()
    finally:
        db.close()
    assert remaining == []


def test_grant_is_idempotent_no_duplicate_row_or_error(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Idempotent Grant Project")
    org_group = _create_org_group(client, admin_token, org_id, "Idempotent Group")

    assert _grant(client, admin_token, project["id"], org_group["id"], "member").status_code == 204
    assert _grant(client, admin_token, project["id"], org_group["id"], "member").status_code == 204

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(OrgGroupProjectRole).where(
                OrgGroupProjectRole.org_group_id == org_group["id"], OrgGroupProjectRole.project_id == project["id"]
            )
        ).all()
    finally:
        db.close()
    assert len(rows) == 1, "granting the same (group, project, role) twice must not create a duplicate row"


def test_revoke_of_a_nonexistent_grant_is_a_no_op_204(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Revoke Noop Project")
    org_group = _create_org_group(client, admin_token, org_id, "Never Granted Group")
    assert _revoke(client, admin_token, project["id"], org_group["id"], "member").status_code == 204


def test_revoke_of_a_nonexistent_grant_does_not_fabricate_an_audit_event(client, admin_token, org_id):
    """Hardening-pass regression test: the no-op path used to unconditionally
    log a "revoked" audit event and resolve group membership even when
    nothing was actually removed — a caller could fabricate audit-trail
    entries for grants that never existed by calling revoke against any
    real org group in their own organisation with no matching grant."""
    project = create_project(client, admin_token, org_id, "Revoke Noop Audit Project")
    org_group = _create_org_group(client, admin_token, org_id, "Never Granted Audit Group")
    assert _revoke(client, admin_token, project["id"], org_group["id"], "member").status_code == 204

    db = SessionLocal()
    try:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "org_group_project_role", AuditEvent.entity_id == org_group["id"]
                )
            )
        )
    finally:
        db.close()
    assert events == [], "a no-op revoke must not write any audit event"


def test_revoke_404s_for_an_org_group_belonging_to_a_different_organization(client, admin_token, org_id):
    """Hardening-pass regression test: `org_group_id` was previously never
    validated at all before use — the delete itself was safely scoped by
    its own `project_id` filter, so no real cross-tenant grant could be
    removed, but an unvalidated id still let the endpoint run a real
    membership-resolution query against an arbitrary group and log a
    fabricated audit event (see the no-op test above). `_get_group_in_project`'s
    sibling `ProjectGroupRole`-scoped endpoint 404s a foreign group; this
    endpoint now does the same for a foreign *org* group."""
    project = create_project(client, admin_token, org_id, "Revoke Cross Tenant Project")
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Other Group Revoke Org")
    foreign_group = _create_org_group(client, other_admin_token, other_org["id"], "Foreign Revoke Group")

    resp = _revoke(client, admin_token, project["id"], foreign_group["id"], "member")
    assert resp.status_code == 404


def test_revoke_404s_for_a_nonexistent_org_group_id(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Revoke Bogus Group Project")
    resp = _revoke(client, admin_token, project["id"], "00000000-0000-0000-0000-000000000000", "member")
    assert resp.status_code == 404


def test_two_org_groups_granting_same_role_produce_two_source_entries(client, admin_token, org_id):
    """Matches the existing `direct_group`/`direct_org_group` precedent
    (`test_effective_members_provenance.py`): two *different* groups
    granting the identical role to the same user must appear as two
    separate source entries, distinguishable by `via_group_id`/
    `via_group_name`, never collapsed."""
    project = create_project(client, admin_token, org_id, "Two Direct Groups Same Role Project")
    user_id = create_org_user(client, admin_token, org_id, "two-direct-groups@example.com", role="member")
    group_a = _create_org_group(client, admin_token, org_id, "Direct Alpha")
    group_b = _create_org_group(client, admin_token, org_id, "Direct Beta")
    for group in (group_a, group_b):
        assert _add_org_group_member(client, admin_token, org_id, group["id"], user_id).status_code == 204
        assert _grant(client, admin_token, project["id"], group["id"], "member").status_code == 204

    sources = _effective_sources_for(client, admin_token, project["id"], user_id)
    entries = [s for s in sources if s["kind"] == "direct_org_group_role" and s["role"] == "member"]
    assert len(entries) == 2, sources
    assert {e["via_group_id"] for e in entries} == {group_a["id"], group_b["id"]}
    assert {e["via_group_name"] for e in entries} == {"Direct Alpha", "Direct Beta"}


def test_direct_grant_cascades_to_a_nested_subgroup_members(client, admin_token, org_id):
    """The direct role is granted to the *outer* group; a user who is only
    a direct member of a subgroup nested inside it must still get the role,
    matching the same ancestor-closure treatment `direct_org_group`'s
    (nested-in-a-ProjectGroup) resolution already gets."""
    project = create_project(client, admin_token, org_id, "Nested Subgroup Cascade Project")
    user_id = create_org_user(client, admin_token, org_id, "nested-subgroup-user@example.com", role="member")
    outer = _create_org_group(client, admin_token, org_id, "Outer Group")
    inner = _create_org_group(client, admin_token, org_id, "Inner Group")
    assert _nest_org_group(client, admin_token, org_id, outer["id"], inner["id"]).status_code == 204
    assert _add_org_group_member(client, admin_token, org_id, inner["id"], user_id).status_code == 204

    assert _grant(client, admin_token, project["id"], outer["id"], "stakeholder").status_code == 204

    sources = _effective_sources_for(client, admin_token, project["id"], user_id)
    entries = [s for s in sources if s["kind"] == "direct_org_group_role" and s["role"] == "stakeholder"]
    assert len(entries) == 1
    assert entries[0]["via_group_id"] == outer["id"], "provenance must name the group the grant actually lives on"


# --- Cross-tenant / authorization -------------------------------------------


def test_grant_rejects_an_org_group_from_a_different_organization(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Cross Tenant Grant Project")
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Other Group Grant Org")
    foreign_group = _create_org_group(client, other_admin_token, other_org["id"], "Foreign Group")

    resp = _grant(client, admin_token, project["id"], foreign_group["id"], "member")
    assert resp.status_code == 400


def test_grant_and_revoke_require_project_manage(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Non Manager Grant Project")
    org_group = _create_org_group(client, admin_token, org_id, "Non Manager Group")
    outsider_id = create_org_user(client, admin_token, org_id, "non-manager-grant@example.com", role="member")
    # A bare org-role user with no role at all on this project cannot manage it.
    outsider_token = login(client, "non-manager-grant@example.com", "Password123!")

    assert _grant(client, outsider_token, project["id"], org_group["id"], "member").status_code == 403

    # Also confirmed against a genuine but insufficient project role
    # (stakeholder, not manager/administrator).
    assert client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": outsider_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).status_code == 204
    stakeholder_token = login(client, "non-manager-grant@example.com", "Password123!")
    assert _grant(client, stakeholder_token, project["id"], org_group["id"], "member").status_code == 403

    # Revoke, too — grant for real via the admin first.
    assert _grant(client, admin_token, project["id"], org_group["id"], "member").status_code == 204
    assert _revoke(client, stakeholder_token, project["id"], org_group["id"], "member").status_code == 403


# --- Audit logging ------------------------------------------------------------


def test_grant_and_revoke_are_audit_logged(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Audited Group Grant Project")
    org_group = _create_org_group(client, admin_token, org_id, "Audited Group")

    assert _grant(client, admin_token, project["id"], org_group["id"], "stakeholder").status_code == 204
    assert _revoke(client, admin_token, project["id"], org_group["id"], "stakeholder").status_code == 204

    db = SessionLocal()
    try:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "org_group_project_role", AuditEvent.entity_id == org_group["id"]
                )
            )
        )
    finally:
        db.close()
    actions = [e.action for e in events]
    assert "granted" in actions
    assert "revoked" in actions
    granted_event = next(e for e in events if e.action == "granted")
    revoked_event = next(e for e in events if e.action == "revoked")
    assert granted_event.detail.get("role") == "stakeholder"
    assert revoked_event.detail.get("role") == "stakeholder"
    assert granted_event.project_id is not None and str(granted_event.project_id) == project["id"]


def test_idempotent_grant_no_op_does_not_create_a_second_audit_event(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Idempotent Audit Project")
    org_group = _create_org_group(client, admin_token, org_id, "Idempotent Audit Group")
    assert _grant(client, admin_token, project["id"], org_group["id"], "member").status_code == 204
    assert _grant(client, admin_token, project["id"], org_group["id"], "member").status_code == 204

    db = SessionLocal()
    try:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "org_group_project_role", AuditEvent.entity_id == org_group["id"],
                    AuditEvent.action == "granted",
                )
            )
        )
    finally:
        db.close()
    assert len(events) == 1, "a no-op re-grant must not log a second audit event, matching assign_project_role"


# --- C-U-08 "at least one manager" guard -------------------------------------


def test_revoking_a_groups_manager_role_succeeds_when_a_real_manager_remains(client, admin_token, org_id):
    """The project creator holds a real direct PROJECT_MANAGER grant
    (C-U-10) throughout, so revoking a group's manager-role grant — even
    though it removes PROJECT_MANAGER-level access from every group member —
    must succeed normally."""
    project = create_project(client, admin_token, org_id, "Group Manager Revoke OK Project")
    user_id = create_org_user(client, admin_token, org_id, "group-manager-revoke-ok@example.com", role="member")
    org_group = _create_org_group(client, admin_token, org_id, "Manager Group")
    assert _add_org_group_member(client, admin_token, org_id, org_group["id"], user_id).status_code == 204
    assert _grant(client, admin_token, project["id"], org_group["id"], "project_manager").status_code == 204

    token = login(client, "group-manager-revoke-ok@example.com", "Password123!")
    assert client.patch(
        f"/api/v1/projects/{project['id']}", json={"summary": "via group manager"}, headers=auth_headers(token)
    ).status_code == 200

    assert _revoke(client, admin_token, project["id"], org_group["id"], "project_manager").status_code == 204
    assert client.patch(
        f"/api/v1/projects/{project['id']}", json={"summary": "no longer manager"}, headers=auth_headers(token)
    ).status_code == 403


def test_revoking_a_groups_manager_role_is_blocked_if_no_real_manager_remains(client, admin_token, org_id):
    """Defense-in-depth pin, mirroring `delete_project_group`'s identical
    post-check: `get_effective_project_managers` never counts a
    group-derived manager (nested-org-group or this direct-grant mechanism
    alike) towards the C-U-08 floor, so this state can't normally be
    reached through the API (the existing `revoke_project_role`/
    `remove_project_group_member`/`delete_project_group` guards all already
    prevent removing a project's *last real* direct manager). Constructed
    here by deleting the creator's own `UserProjectRole` row directly via
    the database — bypassing every one of those API-level guards — to prove
    the group-role revoke endpoint's own post-check still catches an
    already-zero-real-manager state rather than silently allowing the
    revoke through."""
    project = create_project(client, admin_token, org_id, "Group Manager Revoke Blocked Project")
    org_group = _create_org_group(client, admin_token, org_id, "Only Manager Group")
    assert _grant(client, admin_token, project["id"], org_group["id"], "project_manager").status_code == 204

    db = SessionLocal()
    try:
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.project_id == project["id"], UserProjectRole.role == "project_manager",
            )
        )
        db.commit()
    finally:
        db.close()

    resp = _revoke(client, admin_token, project["id"], org_group["id"], "project_manager")
    assert resp.status_code == 400, resp.text

    # The row must still be present — the guard rejected before the
    # transaction committed, not after it already deleted the row.
    db = SessionLocal()
    try:
        remaining = db.scalars(
            select(OrgGroupProjectRole).where(
                OrgGroupProjectRole.org_group_id == org_group["id"], OrgGroupProjectRole.project_id == project["id"]
            )
        ).all()
    finally:
        db.close()
    assert len(remaining) == 1


# --- Inheritance cascade (Step 4 — the highest-risk, most novel part) -------


def test_cascade_mirror_all_from_org_group_direct_grant(client, admin_token, org_id):
    """A user whose only path to a role on the parent is via an org group's
    *direct* grant (not nesting) must still see that role cascade to a
    MIRROR_ALL child, exactly like a user's own direct `UserProjectRole`
    grant already does."""
    parent = create_project(client, admin_token, org_id, "Cascade MirrorAll Parent", can_be_parent=True)
    user_id = create_org_user(client, admin_token, org_id, "cascade-mirror-all-user@example.com", role="member")
    org_group = _create_org_group(client, admin_token, org_id, "Cascade MirrorAll Group")
    assert _add_org_group_member(client, admin_token, org_id, org_group["id"], user_id).status_code == 204
    assert _grant(client, admin_token, parent["id"], org_group["id"], "stakeholder").status_code == 204

    child = create_project(
        client, admin_token, org_id, "Cascade MirrorAll Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_all",
    )

    token = login(client, "cascade-mirror-all-user@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token)).status_code == 200

    sources = _effective_sources_for(client, admin_token, child["id"], user_id)
    inherited = [s for s in sources if s["kind"] == "forward_inherited" and s["role"] == "stakeholder"]
    assert len(inherited) == 1, sources
    assert inherited[0]["via_project_id"] == parent["id"]
    assert inherited[0]["via_mode"] == "mirror_all"


def test_cascade_mirror_role_from_org_group_direct_grant(client, admin_token, org_id):
    """MIRROR_ROLE must only mirror the filtered role: an org-group-direct
    PROJECT_MANAGER grant cascades to a MIRROR_ROLE(project_manager) child,
    but an org-group-direct STAKEHOLDER grant does not."""
    parent = create_project(client, admin_token, org_id, "Cascade MirrorRole Parent", can_be_parent=True)
    manager_id = create_org_user(client, admin_token, org_id, "cascade-mirror-role-pm@example.com", role="member")
    stakeholder_id = create_org_user(client, admin_token, org_id, "cascade-mirror-role-sh@example.com", role="member")
    manager_group = _create_org_group(client, admin_token, org_id, "Cascade MirrorRole Manager Group")
    stakeholder_group = _create_org_group(client, admin_token, org_id, "Cascade MirrorRole Stakeholder Group")
    assert _add_org_group_member(client, admin_token, org_id, manager_group["id"], manager_id).status_code == 204
    assert _add_org_group_member(client, admin_token, org_id, stakeholder_group["id"], stakeholder_id).status_code == 204
    assert _grant(client, admin_token, parent["id"], manager_group["id"], "project_manager").status_code == 204
    assert _grant(client, admin_token, parent["id"], stakeholder_group["id"], "stakeholder").status_code == 204

    child = create_project(
        client, admin_token, org_id, "Cascade MirrorRole Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_role",
        role_inheritance_filter_role="project_manager",
    )

    manager_token = login(client, "cascade-mirror-role-pm@example.com", "Password123!")
    stakeholder_token = login(client, "cascade-mirror-role-sh@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(manager_token)).status_code == 200
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(stakeholder_token)).status_code == 403


def test_cascade_member_only_from_org_group_direct_grant(client, admin_token, org_id):
    """MEMBER_ONLY forward inheritance grants baseline MEMBER regardless of
    which role the org group's direct grant actually holds on the parent."""
    parent = create_project(client, admin_token, org_id, "Cascade MemberOnly Parent", can_be_parent=True)
    user_id = create_org_user(client, admin_token, org_id, "cascade-member-only-user@example.com", role="member")
    org_group = _create_org_group(client, admin_token, org_id, "Cascade MemberOnly Group")
    assert _add_org_group_member(client, admin_token, org_id, org_group["id"], user_id).status_code == 204
    assert _grant(client, admin_token, parent["id"], org_group["id"], "project_manager").status_code == 204

    child = create_project(
        client, admin_token, org_id, "Cascade MemberOnly Child",
        parent_project_id=parent["id"], role_inheritance_mode="member_only",
    )

    token = login(client, "cascade-member-only-user@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token)).status_code == 200
    # Baseline MEMBER only — not the parent's actual PROJECT_MANAGER role.
    assert client.patch(
        f"/api/v1/projects/{child['id']}", json={"summary": "nope"}, headers=auth_headers(token)
    ).status_code == 403


def test_cascade_via_member_source_mechanism(client, admin_token, org_id):
    """The reverse (member-source) mechanism must also pick up an org
    group's direct grant on the source project, the same way it already
    picks up a user's own direct grant."""
    receiving = create_project(client, admin_token, org_id, "Cascade MemberSource Receiving")
    source = create_project(client, admin_token, org_id, "Cascade MemberSource Source")
    user_id = create_org_user(client, admin_token, org_id, "cascade-member-source-user@example.com", role="member")
    org_group = _create_org_group(client, admin_token, org_id, "Cascade MemberSource Group")
    assert _add_org_group_member(client, admin_token, org_id, org_group["id"], user_id).status_code == 204
    assert _grant(client, admin_token, source["id"], org_group["id"], "project_manager").status_code == 204

    assert client.post(
        f"/api/v1/projects/{receiving['id']}/member-sources",
        json={"source_project_id": source["id"], "mirror_mode": "mirror_all"}, headers=auth_headers(admin_token),
    ).status_code == 201

    token = login(client, "cascade-member-source-user@example.com", "Password123!")
    # A real PROJECT_MANAGER on the source (via the group's direct grant)
    # mirrors as PROJECT_MANAGER on the receiving project.
    assert client.patch(
        f"/api/v1/projects/{receiving['id']}", json={"summary": "mirrored via group grant"},
        headers=auth_headers(token),
    ).status_code == 200

    sources = _effective_sources_for(client, admin_token, receiving["id"], user_id)
    inherited = [s for s in sources if s["kind"] == "member_source_inherited" and s["role"] == "project_manager"]
    assert len(inherited) == 1, sources
    assert inherited[0]["via_project_id"] == source["id"]


# --- Project-list visibility --------------------------------------------------


def test_grant_makes_the_project_appear_in_the_groups_members_own_project_list(client, admin_token, org_id):
    """Regression: `_accessible_project_ids` (the function behind `GET
    /projects`, search, and the hierarchy endpoints — distinct from
    `get_effective_project_roles`, which `GET /{project_id}` already uses
    directly) used to only ever cover a user's *direct* membership, never a
    role reached only via an org group. `GET /{project_id}` has therefore
    always worked for a user whose only access is a group's direct grant
    (see `test_grant_gives_group_member_effective_role_with_provenance`'s
    own sanity check above) — but before this fix, that same project simply
    never appeared in the user's own project list. This would have failed
    with the project missing from `listing` before the `_accessible_
    project_ids` fix (docs/decisions.md)."""
    project = create_project(client, admin_token, org_id, "List Visibility Via Group Grant")
    user_id = create_org_user(client, admin_token, org_id, "list-visibility-user@example.com", role="member")
    org_group = _create_org_group(client, admin_token, org_id, "List Visibility Group")
    assert _add_org_group_member(client, admin_token, org_id, org_group["id"], user_id).status_code == 204
    assert _grant(client, admin_token, project["id"], org_group["id"], "member").status_code == 204

    token = login(client, "list-visibility-user@example.com", "Password123!")
    listing = client.get("/api/v1/projects", headers=auth_headers(token)).json()
    assert any(p["id"] == project["id"] for p in listing), listing


def test_nested_org_group_membership_also_appears_in_the_project_list(client, admin_token, org_id):
    """Same regression, for the pre-existing nested-org-group mechanism
    (`ProjectGroupMember.org_group_id`, not this PR's new direct grant) -
    confirms the `_accessible_project_ids` fix covers both, not just the
    newly-added source."""
    project = create_project(client, admin_token, org_id, "List Visibility Via Nesting")
    user_id = create_org_user(client, admin_token, org_id, "list-visibility-nested-user@example.com", role="member")
    org_group = _create_org_group(client, admin_token, org_id, "List Visibility Nested Group")
    assert _add_org_group_member(client, admin_token, org_id, org_group["id"], user_id).status_code == 204
    project_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Nested"},
        headers=auth_headers(admin_token),
    ).json()
    grant_role = client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/roles", json={"role": "member"},
        headers=auth_headers(admin_token),
    )
    assert grant_role.status_code == 204, grant_role.text
    nested = client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members",
        json={"org_group_id": org_group["id"]}, headers=auth_headers(admin_token),
    )
    assert nested.status_code == 204, nested.text

    token = login(client, "list-visibility-nested-user@example.com", "Password123!")
    listing = client.get("/api/v1/projects", headers=auth_headers(token)).json()
    assert any(p["id"] == project["id"] for p in listing), listing


# --- Per-group materialize (PR6 of the members/groups directory rework
# plan, docs/decisions.md) ----------------------------------------------------
#
# `POST /{project_id}/materialize-inherited-access/group/{org_group_id}`
# converts an org group's own forward-/member-source-inherited role on a
# project (via `get_group_inherited_project_roles`, walking this group's
# `OrgGroupProjectRole` grants on ancestor/source projects — the cascade
# this same test module already exercises above for user-level effective
# access) into a direct `OrgGroupProjectRole` grant on that project. Same
# rank-based idempotency and audit action
# (`inherited_access_materialized`) as the per-user endpoint, entity type
# `org_group_project_role` instead of `project`/`user_project_role`.


def _materialize_group(client, token, project_id, org_group_id):
    return client.post(
        f"/api/v1/projects/{project_id}/materialize-inherited-access/group/{org_group_id}",
        headers=auth_headers(token),
    )


def test_materialize_for_group_converts_forward_inherited_grant_to_direct(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "Group Materialize Parent", can_be_parent=True)
    org_group = _create_org_group(client, admin_token, org_id, "Group Materialize Group")
    assert _grant(client, admin_token, parent["id"], org_group["id"], "project_manager").status_code == 204

    child = create_project(
        client, admin_token, org_id, "Group Materialize Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_all",
    )

    result = _materialize_group(client, admin_token, child["id"], org_group["id"])
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["created"] == [{"org_group_id": org_group["id"], "role": "project_manager"}], body

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(OrgGroupProjectRole.role).where(
                OrgGroupProjectRole.org_group_id == org_group["id"], OrgGroupProjectRole.project_id == child["id"],
            )
        ).all()
    finally:
        db.close()
    assert set(rows) == {"project_manager"}


def test_materialize_for_group_is_idempotent(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "Group Materialize Idempotent Parent", can_be_parent=True)
    org_group = _create_org_group(client, admin_token, org_id, "Group Materialize Idempotent Group")
    assert _grant(client, admin_token, parent["id"], org_group["id"], "stakeholder").status_code == 204
    child = create_project(
        client, admin_token, org_id, "Group Materialize Idempotent Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_all",
    )

    first = _materialize_group(client, admin_token, child["id"], org_group["id"])
    assert first.status_code == 200, first.text
    assert any(c["org_group_id"] == org_group["id"] for c in first.json()["created"])

    second = _materialize_group(client, admin_token, child["id"], org_group["id"])
    assert second.status_code == 200, second.text
    assert not any(c["org_group_id"] == org_group["id"] for c in second.json()["created"])
    assert any(s["org_group_id"] == org_group["id"] for s in second.json()["skipped"])

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(OrgGroupProjectRole).where(
                OrgGroupProjectRole.org_group_id == org_group["id"], OrgGroupProjectRole.project_id == child["id"],
            )
        ).all()
    finally:
        db.close()
    assert len(rows) == 1, "must not create a duplicate direct grant on a second call"

    db = SessionLocal()
    try:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "org_group_project_role", AuditEvent.entity_id == org_group["id"],
                    AuditEvent.action == "inherited_access_materialized",
                )
            )
        )
    finally:
        db.close()
    assert len(events) == 1, "a no-op re-materialize must not log a second audit event"


def test_materialize_for_group_selects_highest_ranked_inherited_role(client, admin_token, org_id):
    """The group holds two direct grants on the parent at different ranks
    (STAKEHOLDER and PROJECT_MANAGER); both cascade to the MIRROR_ALL
    child as inherited, but only the higher-ranked one should be written
    as the direct grant, matching the per-user endpoint's own `_ROLE_RANK`
    selection."""
    parent = create_project(client, admin_token, org_id, "Group Materialize Rank Parent", can_be_parent=True)
    org_group = _create_org_group(client, admin_token, org_id, "Group Materialize Rank Group")
    assert _grant(client, admin_token, parent["id"], org_group["id"], "stakeholder").status_code == 204
    assert _grant(client, admin_token, parent["id"], org_group["id"], "project_manager").status_code == 204

    child = create_project(
        client, admin_token, org_id, "Group Materialize Rank Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_all",
    )

    result = _materialize_group(client, admin_token, child["id"], org_group["id"])
    assert result.status_code == 200, result.text
    assert result.json()["created"] == [{"org_group_id": org_group["id"], "role": "project_manager"}], result.json()

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(OrgGroupProjectRole.role).where(
                OrgGroupProjectRole.org_group_id == org_group["id"], OrgGroupProjectRole.project_id == child["id"],
            )
        ).all()
    finally:
        db.close()
    assert set(rows) == {"project_manager"}, "only the single highest-ranked inherited role must become direct"


def test_materialize_for_group_is_a_noop_when_group_has_no_inherited_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Group Materialize No Inherited Project")
    org_group = _create_org_group(client, admin_token, org_id, "Group Materialize No Inherited Group")

    result = _materialize_group(client, admin_token, project["id"], org_group["id"])
    assert result.status_code == 200, result.text
    assert result.json() == {"created": [], "skipped": []}

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(OrgGroupProjectRole).where(
                OrgGroupProjectRole.org_group_id == org_group["id"], OrgGroupProjectRole.project_id == project["id"],
            )
        ).all()
    finally:
        db.close()
    assert rows == []


def test_materialize_for_group_via_member_source_mechanism(client, admin_token, org_id):
    receiving = create_project(client, admin_token, org_id, "Group Materialize MemberSource Receiving")
    source = create_project(client, admin_token, org_id, "Group Materialize MemberSource Source")
    org_group = _create_org_group(client, admin_token, org_id, "Group Materialize MemberSource Group")
    assert _grant(client, admin_token, source["id"], org_group["id"], "member").status_code == 204
    assert client.post(
        f"/api/v1/projects/{receiving['id']}/member-sources",
        json={"source_project_id": source["id"], "mirror_mode": "mirror_all"}, headers=auth_headers(admin_token),
    ).status_code == 201

    result = _materialize_group(client, admin_token, receiving["id"], org_group["id"])
    assert result.status_code == 200, result.text
    assert result.json()["created"] == [{"org_group_id": org_group["id"], "role": "member"}], result.json()


def test_materialize_for_group_audit_log_has_expected_detail(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "Group Materialize Audit Parent", can_be_parent=True)
    org_group = _create_org_group(client, admin_token, org_id, "Group Materialize Audit Group")
    assert _grant(client, admin_token, parent["id"], org_group["id"], "project_manager").status_code == 204
    child = create_project(
        client, admin_token, org_id, "Group Materialize Audit Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_all",
    )

    assert _materialize_group(client, admin_token, child["id"], org_group["id"]).status_code == 200

    db = SessionLocal()
    try:
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_type == "org_group_project_role", AuditEvent.entity_id == org_group["id"],
                AuditEvent.action == "inherited_access_materialized",
            )
        )
    finally:
        db.close()
    assert event is not None
    assert event.project_id is not None and str(event.project_id) == child["id"]
    assert any(
        c["org_group_id"] == org_group["id"] and c["role"] == "project_manager" for c in event.detail.get("created", [])
    )


def test_materialize_for_group_requires_project_manage(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "Group Materialize NonManager Parent", can_be_parent=True)
    org_group = _create_org_group(client, admin_token, org_id, "Group Materialize NonManager Group")
    assert _grant(client, admin_token, parent["id"], org_group["id"], "project_manager").status_code == 204
    child = create_project(
        client, admin_token, org_id, "Group Materialize NonManager Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_all",
    )
    outsider_id = create_org_user(client, admin_token, org_id, "group-materialize-outsider@example.com", role="member")
    assert client.post(
        f"/api/v1/projects/{child['id']}/roles", json={"user_id": outsider_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).status_code == 204
    outsider_token = login(client, "group-materialize-outsider@example.com", "Password123!")

    resp = _materialize_group(client, outsider_token, child["id"], org_group["id"])
    assert resp.status_code == 403
