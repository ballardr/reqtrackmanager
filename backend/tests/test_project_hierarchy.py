"""Tests for hierarchical (parent/child) projects: cycle prevention,
cross-org rejection, forward-inheritance modes (MIRROR_ALL/MIRROR_ROLE/
MEMBER_ONLY, chain-breaking), the member-source (reverse) mechanism and its
authorization asymmetry, C-U-08 interaction, and the `parent_required`
bypass guard — see docs/decisions.md's "Hierarchical projects" entry for the
full design and the security corrections made during planning that these
tests specifically pin down."""

from uuid import UUID

from app.database import SessionLocal
from app.models.enums import ProjectRole
from app.services.rbac import get_project_users_by_role
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _set_parent(client, token, project_id, **kwargs):
    return client.patch(f"/api/v1/projects/{project_id}", json=kwargs, headers=auth_headers(token))


def _assign_role(client, token, project_id, user_id, role):
    return client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token)
    )


def _revoke_role(client, token, project_id, user_id, role):
    return client.delete(f"/api/v1/projects/{project_id}/roles/{user_id}/{role}", headers=auth_headers(token))


# --- Cycle prevention / cross-org --------------------------------------------


def test_project_cannot_be_its_own_parent(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Self Parent")
    resp = _set_parent(client, admin_token, project["id"], parent_project_id=project["id"])
    assert resp.status_code == 400


def test_deep_cycle_is_rejected(client, admin_token, org_id):
    a = create_project(client, admin_token, org_id, "Cycle A")
    b = create_project(client, admin_token, org_id, "Cycle B", parent_project_id=a["id"])
    c = create_project(client, admin_token, org_id, "Cycle C", parent_project_id=b["id"])
    resp = _set_parent(client, admin_token, a["id"], parent_project_id=c["id"])
    assert resp.status_code == 400


def test_cannot_parent_project_from_another_organization(client, admin_token, org_id):
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Hierarchy Other Org")
    other_project = create_project(client, other_admin_token, other_org["id"], "Foreign Parent")
    my_project = create_project(client, admin_token, org_id, "My Project")

    resp = _set_parent(client, admin_token, my_project["id"], parent_project_id=other_project["id"])
    assert resp.status_code in (400, 403)


def test_attach_requires_managing_the_target_parent_not_just_viewing_it(client, admin_token, org_id):
    """A caller who can view but not manage the intended parent must not be
    able to attach a project to it (decision 12)."""
    parent = create_project(client, admin_token, org_id, "Unmanaged Parent")
    viewer_id = create_org_user(client, admin_token, org_id, "hier_viewer@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], viewer_id, "stakeholder").status_code == 204
    other_project = create_project(client, admin_token, org_id, "Other Project")
    assert _assign_role(client, admin_token, other_project["id"], viewer_id, "project_manager").status_code == 204

    viewer_token = login(client, "hier_viewer@example.com", "Password123!")
    resp = _set_parent(client, viewer_token, other_project["id"], parent_project_id=parent["id"])
    assert resp.status_code == 403


# --- Forward inheritance modes -----------------------------------------------


def test_mirror_all_mirrors_every_role(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "MirrorAll Parent")
    stakeholder_id = create_org_user(client, admin_token, org_id, "mirror_all_sh@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], stakeholder_id, "stakeholder").status_code == 204

    child = create_project(
        client, admin_token, org_id, "MirrorAll Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_all",
    )

    token = login(client, "mirror_all_sh@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def test_mirror_role_only_mirrors_the_filtered_role(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "MirrorRole Parent")
    pm_id = create_org_user(client, admin_token, org_id, "mirror_role_pm@example.com", role="member")
    sh_id = create_org_user(client, admin_token, org_id, "mirror_role_sh@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], pm_id, "project_manager").status_code == 204
    assert _assign_role(client, admin_token, parent["id"], sh_id, "stakeholder").status_code == 204

    child = create_project(
        client, admin_token, org_id, "MirrorRole Child",
        parent_project_id=parent["id"], role_inheritance_mode="mirror_role",
        role_inheritance_filter_role="project_manager",
    )

    pm_token = login(client, "mirror_role_pm@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(pm_token)).status_code == 200

    sh_token = login(client, "mirror_role_sh@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(sh_token)).status_code == 403


def test_member_only_grants_baseline_regardless_of_parent_role(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "MemberOnly Parent")
    pm_id = create_org_user(client, admin_token, org_id, "member_only_pm@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], pm_id, "project_manager").status_code == 204

    child = create_project(
        client, admin_token, org_id, "MemberOnly Child",
        parent_project_id=parent["id"], role_inheritance_mode="member_only",
    )

    token = login(client, "member_only_pm@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token)).status_code == 200
    # Baseline MEMBER only — updating child settings requires manage rights,
    # which a MEMBER_ONLY-derived MEMBER role must not confer.
    resp = client.patch(f"/api/v1/projects/{child['id']}", json={"summary": "nope"}, headers=auth_headers(token))
    assert resp.status_code == 403


def test_chain_breaks_at_first_none_ancestor(client, admin_token, org_id):
    """grandparent -> parent (mode=none) -> child (mode=mirror_all): the
    grandparent's manager must NOT reach the child, since the chain breaks
    at the parent's own NONE mode."""
    grandparent = create_project(client, admin_token, org_id, "Chain Grandparent")
    gp_manager_id = create_org_user(client, admin_token, org_id, "chain_break_gp@example.com", role="member")
    assert _assign_role(client, admin_token, grandparent["id"], gp_manager_id, "project_manager").status_code == 204

    parent = create_project(
        client, admin_token, org_id, "Chain Parent", parent_project_id=grandparent["id"],
        role_inheritance_mode="none",
    )
    child = create_project(
        client, admin_token, org_id, "Chain Child", parent_project_id=parent["id"],
        role_inheritance_mode="mirror_all",
    )

    token = login(client, "chain_break_gp@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token)).status_code == 403


# --- C-U-08 --------------------------------------------------------------


def test_cannot_disable_inheritance_when_only_manager_is_inherited(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "CU08 Parent")
    pm_id = create_org_user(client, admin_token, org_id, "cu08_pm@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], pm_id, "project_manager").status_code == 204

    child = create_project(
        client, admin_token, org_id, "CU08 Child", parent_project_id=parent["id"],
        role_inheritance_mode="mirror_all",
    )
    # A manually-created project's creator becomes a manager via the
    # default "Project Managers" *group* (C-U-10), not a direct
    # UserProjectRole — remove them from that group (not
    # DELETE .../roles/..., which would be a no-op here) to leave child
    # with zero *direct* managers of its own. admin_token remains an
    # inherited manager of child throughout, via their own still-intact
    # direct manager status on parent.
    creator_id = _get_project_creator_id(client, admin_token)
    groups = client.get(f"/api/v1/projects/{child['id']}/groups", headers=auth_headers(admin_token)).json()
    manager_group = next(g for g in groups if g["role"] == "project_manager")
    remove = client.delete(
        f"/api/v1/projects/{child['id']}/groups/{manager_group['id']}/members/{creator_id}",
        headers=auth_headers(admin_token),
    )
    assert remove.status_code == 204, remove.text

    # Now switching child's mode away from mirror_all would leave it with
    # zero effective managers (its only ones were inherited) — blocked.
    resp = _set_parent(client, admin_token, child["id"], role_inheritance_mode="none")
    assert resp.status_code == 400


def test_cu08_unaffected_by_switching_to_member_only(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "CU08 MemberOnly Parent")
    child = create_project(
        client, admin_token, org_id, "CU08 MemberOnly Child", parent_project_id=parent["id"],
        role_inheritance_mode="mirror_all",
    )
    # admin is child's own direct manager regardless of inheritance, so
    # switching away from a manager-contributing mode is always safe here.
    resp = _set_parent(client, admin_token, child["id"], role_inheritance_mode="member_only")
    assert resp.status_code == 200, resp.text


def _get_project_creator_id(client, admin_token):
    resp = client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# --- Member-source mechanism -------------------------------------------------


def test_member_source_grants_baseline_member_on_the_parent(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "MemberSource Parent")
    child = create_project(client, admin_token, org_id, "MemberSource Child", parent_project_id=parent["id"])
    child_only_user = create_org_user(client, admin_token, org_id, "member_source_child_user@example.com", role="member")
    assert _assign_role(client, admin_token, child["id"], child_only_user, "stakeholder").status_code == 204

    add = client.post(
        f"/api/v1/projects/{parent['id']}/member-sources",
        json={"source_project_id": child["id"]}, headers=auth_headers(admin_token),
    )
    assert add.status_code == 201, add.text

    token = login(client, "member_source_child_user@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{parent['id']}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    # Baseline only — must not be able to manage the parent.
    manage_resp = client.patch(f"/api/v1/projects/{parent['id']}", json={"summary": "nope"}, headers=auth_headers(token))
    assert manage_resp.status_code == 403


def test_member_source_does_not_leak_org_wide_visibility_as_membership(client, admin_token, org_id):
    """Regression test for a real RBAC-escalation bug found in this
    branch's own hardening pass: `_has_member_source_access` used to check
    `_direct_effective_project_roles` (which includes the `ORG_WIDE`
    baseline grant) instead of `_direct_project_member_ids` (which
    deliberately excludes it, per that helper's own docstring). Listing an
    `ORG_WIDE`-visible child as a member source used to grant every user in
    the organisation real `MEMBER` access to the parent — not just a read
    grant on the child, but actual access to a potentially far more
    sensitive parent — regardless of whether they held any concrete role on
    the child at all."""
    parent = create_project(client, admin_token, org_id, "MS OrgWide Parent")
    child = create_project(client, admin_token, org_id, "MS OrgWide Child", parent_project_id=parent["id"])
    assert _set_parent(client, admin_token, child["id"], visibility="org_wide").status_code == 200
    assert client.post(
        f"/api/v1/projects/{parent['id']}/member-sources",
        json={"source_project_id": child["id"]}, headers=auth_headers(admin_token),
    ).status_code == 201

    # A user with no direct/group role on either project, only baseline
    # org membership (which grants ORG_WIDE view of the child alone) must
    # not gain access to the parent through the member-source mechanism.
    create_org_user(client, admin_token, org_id, "ms_org_wide_bystander@example.com", role="member")
    token = login(client, "ms_org_wide_bystander@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token)).status_code == 200
    resp = client.get(f"/api/v1/projects/{parent['id']}", headers=auth_headers(token))
    assert resp.status_code == 403, resp.text


def test_member_source_multilevel_requires_both_hops(client, admin_token, org_id):
    grandparent = create_project(client, admin_token, org_id, "MS Grandparent")
    parent = create_project(client, admin_token, org_id, "MS Parent", parent_project_id=grandparent["id"])
    child = create_project(client, admin_token, org_id, "MS Child", parent_project_id=parent["id"])
    grandchild_user = create_org_user(client, admin_token, org_id, "ms_grandchild_user@example.com", role="member")
    assert _assign_role(client, admin_token, child["id"], grandchild_user, "stakeholder").status_code == 204

    # Only parent -> child listed so far; grandparent has not listed parent.
    assert client.post(
        f"/api/v1/projects/{parent['id']}/member-sources",
        json={"source_project_id": child["id"]}, headers=auth_headers(admin_token),
    ).status_code == 201

    token = login(client, "ms_grandchild_user@example.com", "Password123!")
    # Reaches parent (one hop) but not grandparent yet (second hop missing).
    assert client.get(f"/api/v1/projects/{parent['id']}", headers=auth_headers(token)).status_code == 200
    assert client.get(f"/api/v1/projects/{grandparent['id']}", headers=auth_headers(token)).status_code == 403

    # Add the second hop.
    assert client.post(
        f"/api/v1/projects/{grandparent['id']}/member-sources",
        json={"source_project_id": parent["id"]}, headers=auth_headers(admin_token),
    ).status_code == 201
    assert client.get(f"/api/v1/projects/{grandparent['id']}", headers=auth_headers(token)).status_code == 200


def test_child_manager_cannot_add_itself_as_a_member_source(client, admin_token, org_id):
    """The key regression test for the caught-and-fixed authorization
    issue: a user who manages a child but holds no role on the parent must
    not be able to add that child to the parent's member-source list —
    only someone who manages the *parent* can."""
    parent = create_project(client, admin_token, org_id, "MS Auth Parent")
    child_manager_id = create_org_user(client, admin_token, org_id, "ms_child_manager@example.com", role="member")
    child = create_project(client, admin_token, org_id, "MS Auth Child", parent_project_id=parent["id"])
    assert _assign_role(client, admin_token, child["id"], child_manager_id, "project_manager").status_code == 204

    token = login(client, "ms_child_manager@example.com", "Password123!")
    resp = client.post(
        f"/api/v1/projects/{parent['id']}/member-sources",
        json={"source_project_id": child["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_parent_manager_can_add_a_child_with_zero_access_to_it(client, admin_token, org_id):
    """The parent's own manager can add a child as a member source even
    with no role on the child themselves — authorization lives entirely on
    the parent side."""
    parent = create_project(client, admin_token, org_id, "MS Parent Only Auth")
    child = create_project(client, admin_token, org_id, "MS Child No Parent Access")
    # Reparent child under parent (admin manages both here; simulate a
    # parent-only-manager scenario by using a fresh parent-only admin).
    other_admin_id = create_org_user(client, admin_token, org_id, "ms_parent_only_admin@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], other_admin_id, "project_manager").status_code == 204
    assert _set_parent(client, admin_token, child["id"], parent_project_id=parent["id"]).status_code == 200

    token = login(client, "ms_parent_only_admin@example.com", "Password123!")
    resp = client.post(
        f"/api/v1/projects/{parent['id']}/member-sources",
        json={"source_project_id": child["id"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text


def test_member_source_must_be_an_actual_direct_child(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "MS Not A Child Parent")
    unrelated = create_project(client, admin_token, org_id, "MS Unrelated Project")
    resp = client.post(
        f"/api/v1/projects/{parent['id']}/member-sources",
        json={"source_project_id": unrelated["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_stale_member_source_grants_nothing_after_child_reparented(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "MS Stale Parent")
    other_parent = create_project(client, admin_token, org_id, "MS Stale Other Parent")
    child = create_project(client, admin_token, org_id, "MS Stale Child", parent_project_id=parent["id"])
    child_user = create_org_user(client, admin_token, org_id, "ms_stale_user@example.com", role="member")
    assert _assign_role(client, admin_token, child["id"], child_user, "stakeholder").status_code == 204
    assert client.post(
        f"/api/v1/projects/{parent['id']}/member-sources",
        json={"source_project_id": child["id"]}, headers=auth_headers(admin_token),
    ).status_code == 201

    token = login(client, "ms_stale_user@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{parent['id']}", headers=auth_headers(token)).status_code == 200

    # Reparent child away — the parent's stale member-source row must
    # become inert (live-revalidated, not cleaned up).
    assert _set_parent(client, admin_token, child["id"], parent_project_id=other_parent["id"]).status_code == 200
    assert client.get(f"/api/v1/projects/{parent['id']}", headers=auth_headers(token)).status_code == 403


# --- parent_required bypass guard --------------------------------------------


def test_parent_required_bypass_is_closed(client, admin_token, org_id):
    """The specific scenario that motivated `parent_required` (decision
    11): an actor with no org-level role creates a child under a project
    they manage via the relaxed path, then must not be able to detach it
    into an unrestricted root project."""
    parent = create_project(client, admin_token, org_id, "ParentRequired Parent")
    plain_manager_id = create_org_user(client, admin_token, org_id, "parent_required_pm@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], plain_manager_id, "project_manager").status_code == 204

    token = login(client, "parent_required_pm@example.com", "Password123!")
    create_resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Relaxed Child", "summary": "", "parent_project_id": parent["id"]},
        headers=auth_headers(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    child = create_resp.json()

    # Attempt to detach via the child's own PATCH — must be blocked.
    resp = _set_parent(client, token, child["id"], parent_project_id=None)
    assert resp.status_code == 403

    # Attempt to detach via the parent-initiated endpoint — also blocked,
    # even though this same actor manages the parent too.
    resp2 = client.delete(f"/api/v1/projects/{parent['id']}/children/{child['id']}", headers=auth_headers(token))
    assert resp2.status_code == 403

    # An actual org admin can still detach it.
    resp3 = _set_parent(client, admin_token, child["id"], parent_project_id=None)
    assert resp3.status_code == 200, resp3.text


def test_relaxed_path_rejected_without_a_parent(client, admin_token, org_id):
    """A caller with no org-level role and no parent_project_id must still
    be rejected outright — the relaxed path only ever applies to children."""
    create_org_user(client, admin_token, org_id, "no_org_role_creator@example.com", role="member")
    token = login(client, "no_org_role_creator@example.com", "Password123!")
    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "Should Fail", "summary": ""},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_org_toggle_disables_the_relaxed_path(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "Toggle Off Parent")
    manager_id = create_org_user(client, admin_token, org_id, "toggle_off_pm@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], manager_id, "project_manager").status_code == 204

    settings = client.get(f"/api/v1/orgs/{org_id}/advanced-settings", headers=auth_headers(admin_token)).json()
    settings["allow_relaxed_child_project_creation"] = False
    assert client.put(
        f"/api/v1/orgs/{org_id}/advanced-settings", json=settings, headers=auth_headers(admin_token)
    ).status_code == 200

    token = login(client, "toggle_off_pm@example.com", "Password123!")
    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "Should Fail Too", "summary": "", "parent_project_id": parent["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


# --- SOC2 review findings: regression tests -------------------------------


def test_get_project_redacts_parent_for_a_viewer_without_parent_access(client, admin_token, org_id):
    """GET /{project_id} is require_project_view-gated (any role), not
    manage-gated — a plain viewer of the child must not learn a hidden
    parent's identity just by fetching the project directly, the same rule
    list_projects already applies (SOC2 review finding)."""
    parent = create_project(client, admin_token, org_id, "Redact Parent")
    child = create_project(client, admin_token, org_id, "Redact Child", parent_project_id=parent["id"])
    viewer_id = create_org_user(client, admin_token, org_id, "redact_viewer@example.com", role="member")
    assert _assign_role(client, admin_token, child["id"], viewer_id, "stakeholder").status_code == 204

    token = login(client, "redact_viewer@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["parent_project_id"] is None
    assert body["parent_project_name"] is None

    # The project's own manager (admin, who also manages parent) still sees it.
    admin_resp = client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(admin_token)).json()
    assert admin_resp["parent_project_id"] == parent["id"]
    assert admin_resp["parent_project_name"] == "Redact Parent"


def test_get_project_shows_true_parent_to_a_manager_with_no_independent_parent_access(client, admin_token, org_id):
    """Regression test for a real bug found in this branch's own hardening
    pass: `_project_out_with_redacted_parent` used to redact the parent for
    *every* caller lacking independent view access to it, with no exemption
    for a caller who manages the child itself — contradicting
    `ProjectAdminPage.tsx`'s own documented assumption (and
    docs/decisions.md's "Hierarchical projects" entry) that a project's own
    manager always sees the true parent there, since they already hold the
    highest authority over the relationship. A manager who happens to have
    no role at all on the parent (a realistic, unremarkable case — managing
    a child implies nothing about the parent) used to see a redacted
    `parent_project_id: null` on the very form used to edit that
    relationship, which — combined with that form always resending
    `parent_project_id` on every save — silently detached the project from
    its real parent on the next unrelated settings save."""
    parent = create_project(client, admin_token, org_id, "Manager Redact Parent")
    child = create_project(client, admin_token, org_id, "Manager Redact Child", parent_project_id=parent["id"])
    manager_id = create_org_user(client, admin_token, org_id, "redact_child_manager@example.com", role="member")
    assert _assign_role(client, admin_token, child["id"], manager_id, "project_manager").status_code == 204

    token = login(client, "redact_child_manager@example.com", "Password123!")
    # Confirm this manager genuinely has no independent access to the
    # parent — the interesting case, not a false positive from some other
    # source of access.
    assert client.get(f"/api/v1/projects/{parent['id']}", headers=auth_headers(token)).status_code == 403

    resp = client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["parent_project_id"] == parent["id"]
    assert body["parent_project_name"] == "Manager Redact Parent"


def test_member_source_listed_sibling_does_not_leak_via_mirror_all(client, admin_token, org_id):
    """Decoupling: a member-source-listed C1's users must not leak into an
    unrelated sibling C2 via P's forward MIRROR_ALL (SOC2 review check)."""
    p = create_project(client, admin_token, org_id, "Decouple P")
    c1 = create_project(client, admin_token, org_id, "Decouple C1", parent_project_id=p["id"])
    c2 = create_project(
        client, admin_token, org_id, "Decouple C2", parent_project_id=p["id"], role_inheritance_mode="mirror_all",
    )
    c1_user = create_org_user(client, admin_token, org_id, "decouple_c1_user@example.com", role="member")
    assert _assign_role(client, admin_token, c1["id"], c1_user, "stakeholder").status_code == 204
    assert client.post(
        f"/api/v1/projects/{p['id']}/member-sources", json={"source_project_id": c1["id"]}, headers=auth_headers(admin_token)
    ).status_code == 201

    token = login(client, "decouple_c1_user@example.com", "Password123!")
    # Reaches P via member-source...
    assert client.get(f"/api/v1/projects/{p['id']}", headers=auth_headers(token)).status_code == 200
    # ...but must NOT reach sibling C2 via P's MIRROR_ALL.
    assert client.get(f"/api/v1/projects/{c2['id']}", headers=auth_headers(token)).status_code == 403


def test_inherited_manager_receives_change_request_notification(client, admin_token, org_id):
    """A PROJECT_MANAGER who holds that role purely via forward inheritance
    must still be notified of change-request events, per decision 5 (SOC2
    review finding on get_project_users_by_role)."""
    parent = create_project(client, admin_token, org_id, "Notify Parent")
    inherited_pm = create_org_user(client, admin_token, org_id, "notify_inherited_pm@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], inherited_pm, "project_manager").status_code == 204
    child = create_project(
        client, admin_token, org_id, "Notify Child", parent_project_id=parent["id"], role_inheritance_mode="mirror_all",
    )
    db = SessionLocal()
    try:
        managers = get_project_users_by_role(db, UUID(child["id"]), ProjectRole.PROJECT_MANAGER)
    finally:
        db.close()
    assert UUID(inherited_pm) in managers


# --- Provenance and materialize (decisions 9/10) -----------------------


def test_effective_members_shows_provenance_for_direct_and_inherited_users(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "Provenance Parent")
    pm_id = create_org_user(client, admin_token, org_id, "provenance_pm@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], pm_id, "project_manager").status_code == 204

    child = create_project(
        client, admin_token, org_id, "Provenance Child", parent_project_id=parent["id"],
        role_inheritance_mode="mirror_all",
    )
    direct_stakeholder = create_org_user(client, admin_token, org_id, "provenance_direct_sh@example.com", role="member")
    assert _assign_role(client, admin_token, child["id"], direct_stakeholder, "stakeholder").status_code == 204

    resp = client.get(f"/api/v1/projects/{child['id']}/effective-members", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    members = {m["user_id"]: m for m in resp.json()}

    assert members[pm_id]["effective_role"] == "project_manager"
    assert any(s["kind"] == "forward_inherited" and s["via_project_name"] == "Provenance Parent" for s in members[pm_id]["sources"])

    assert members[direct_stakeholder]["effective_role"] == "stakeholder"
    assert any(s["kind"] == "direct" for s in members[direct_stakeholder]["sources"])


def test_effective_members_requires_manage_not_just_view(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Provenance Auth")
    viewer_id = create_org_user(client, admin_token, org_id, "provenance_viewer@example.com", role="member")
    assert _assign_role(client, admin_token, project["id"], viewer_id, "stakeholder").status_code == 204
    token = login(client, "provenance_viewer@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{project['id']}/effective-members", headers=auth_headers(token))
    assert resp.status_code == 403


def test_materialize_converts_inherited_access_to_direct_and_survives_disabling_inheritance(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, "Materialize Parent")
    pm_id = create_org_user(client, admin_token, org_id, "materialize_pm@example.com", role="member")
    assert _assign_role(client, admin_token, parent["id"], pm_id, "project_manager").status_code == 204

    child = create_project(
        client, admin_token, org_id, "Materialize Child", parent_project_id=parent["id"],
        role_inheritance_mode="mirror_all",
    )
    token = login(client, "materialize_pm@example.com", "Password123!")
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token)).status_code == 200

    result = client.post(f"/api/v1/projects/{child['id']}/materialize-inherited-access", headers=auth_headers(admin_token))
    assert result.status_code == 200, result.text
    body = result.json()
    assert any(c["user_id"] == pm_id and c["role"] == "project_manager" for c in body["created"])

    # Idempotent: calling again creates nothing new for this user.
    result2 = client.post(f"/api/v1/projects/{child['id']}/materialize-inherited-access", headers=auth_headers(admin_token))
    assert not any(c["user_id"] == pm_id for c in result2.json()["created"])
    assert any(s["user_id"] == pm_id for s in result2.json()["skipped"])

    # Disabling inheritance no longer removes pm_id's access — they kept
    # their own direct role from materialization.
    assert _set_parent(client, admin_token, child["id"], role_inheritance_mode="none").status_code == 200
    assert client.get(f"/api/v1/projects/{child['id']}", headers=auth_headers(token)).status_code == 200
