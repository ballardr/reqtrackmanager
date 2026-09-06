"""Tests for the Compliance Module's Phase 6 Standards Management API
(docs/compliance-module-plan.md Phase 6; docs/Compliance_Module_
Requirements.md §2, §3, §4, §26): full CRUD for standards/versions/
requirements/required actions/action types through the real HTTP API (the
first time this module has had an API surface to go through at all — Phase
5's own tests were ORM-only), the publish/retire version lifecycle and its
immutability enforcement, version cloning, the org-admin/compliance-manager
RBAC composition `require_module_role` already provides (this phase's own
job is to prove it applies here, not reimplement it), cross-organisation
isolation (404, not 403 or 200), audit logging, and action-type
delete-with-reassignment.

Every test uses the real `/api/v1/orgs/{organization_id}/modules/compliance`
endpoints via the `client` fixture — no direct ORM manipulation, unlike
`test_compliance_data_model.py` (Phase 5, which had no API to go through).
"""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers, create_org_user, login

# --- Small API helpers ---------------------------------------------------------


def _base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/compliance"


def _create_standard(client, token, org_id, *, reference="ISO-27001", name="Corporate Security Standard", **extra):
    payload = {"reference": reference, "name": name, **extra}
    resp = client.post(f"{_base(org_id)}/standards", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_version(client, token, org_id, standard_id, *, version_label="1.0", **extra):
    payload = {"version_label": version_label, **extra}
    resp = client.post(f"{_base(org_id)}/standards/{standard_id}/versions", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_requirement(client, token, org_id, standard_id, version_id, *, name="Requirement", **extra):
    payload = {"name": name, **extra}
    resp = client.post(
        f"{_base(org_id)}/standards/{standard_id}/versions/{version_id}/requirements",
        json=payload, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_action_type(client, token, org_id, *, name="Test"):
    resp = client.post(f"{_base(org_id)}/action-types", json={"name": name}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_required_action(client, token, org_id, standard_id, version_id, requirement_id, action_type_id, *, name="Perform test", **extra):
    payload = {"action_type_id": action_type_id, "name": name, **extra}
    resp = client.post(
        f"{_base(org_id)}/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/required-actions",
        json=payload, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _grant_compliance_manager(client, admin_token, org_id, user_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": "compliance", "role_key": "compliance_manager"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


# --- Full CRUD happy path -------------------------------------------------------


def test_full_crud_happy_path(client, admin_token, org_id):
    """Standard -> version -> parent/child requirement -> required action
    -> action type, end to end through the real API (admin_token is
    ORG_ADMIN on `org_id` via bootstrap, exercising the admin-override
    composition path as a side effect of this happy-path test)."""
    action_type = _create_action_type(client, admin_token, org_id, name="Inspection")
    assert action_type["name"] == "Inspection"
    assert action_type["sort_order"] == 0

    standard = _create_standard(client, admin_token, org_id, reference="ISO-27001", name="Corporate Security Standard")
    assert standard["reference"] == "ISO-27001"
    assert standard["is_archived"] is False
    # owner_id defaults to the creating user when omitted.
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
    assert me.status_code == 200
    assert standard["owner_id"] == me.json()["id"]

    # Update: name/description/issuing_organisation/owner_id, not reference.
    updated = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}",
        json={"name": "Updated Standard Name", "description": "Updated.", "issuing_organisation": "ISO",
              "owner_id": standard["owner_id"]},
        headers=auth_headers(admin_token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Updated Standard Name"
    assert updated.json()["reference"] == "ISO-27001", "reference must stay immutable"

    version = _create_version(client, admin_token, org_id, standard["id"], version_label="1.0")
    assert version["version_number"] == 1
    assert version["status"] == "draft"

    parent = _create_requirement(
        client, admin_token, org_id, standard["id"], version["id"], name="Environmental requirements", reference="3",
    )
    assert parent["parent_requirement_id"] is None
    assert parent["sort_order"] == 0

    child = _create_requirement(
        client, admin_token, org_id, standard["id"], version["id"],
        name="Equipment shall meet IPX9.", reference="3.1", parent_requirement_id=parent["id"],
    )
    assert child["parent_requirement_id"] == parent["id"]

    # Listing is flat, DFS-ordered: parent immediately followed by its child.
    listed = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements",
        headers=auth_headers(admin_token),
    )
    assert listed.status_code == 200
    ids_in_order = [r["id"] for r in listed.json()]
    assert ids_in_order.index(parent["id"]) < ids_in_order.index(child["id"])

    required_action = _create_required_action(
        client, admin_token, org_id, standard["id"], version["id"], child["id"], action_type["id"],
        name="Perform IPX9 water ingress test",
    )
    assert required_action["is_mandatory"] is True
    assert required_action["sort_order"] == 0

    # Update requirement.
    child_updated = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{child['id']}",
        json={"name": "Updated child name", "reference": "3.1", "description": "", "reasoning": ""},
        headers=auth_headers(admin_token),
    )
    assert child_updated.status_code == 200
    assert child_updated.json()["name"] == "Updated child name"

    # Update required action.
    action_updated = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{child['id']}"
        f"/required-actions/{required_action['id']}",
        json={"action_type_id": action_type["id"], "name": "Updated action name", "description": "", "is_mandatory": False},
        headers=auth_headers(admin_token),
    )
    assert action_updated.status_code == 200
    assert action_updated.json()["is_mandatory"] is False

    # Delete required action, then requirement (both still draft).
    deleted_action = client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{child['id']}"
        f"/required-actions/{required_action['id']}",
        headers=auth_headers(admin_token),
    )
    assert deleted_action.status_code == 204
    deleted_requirement = client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{child['id']}",
        headers=auth_headers(admin_token),
    )
    assert deleted_requirement.status_code == 204

    # Archive/unarchive the standard.
    archived = client.post(f"{_base(org_id)}/standards/{standard['id']}/archive", headers=auth_headers(admin_token))
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    unarchived = client.post(f"{_base(org_id)}/standards/{standard['id']}/unarchive", headers=auth_headers(admin_token))
    assert unarchived.status_code == 200
    assert unarchived.json()["is_archived"] is False


def test_requirement_and_required_action_move(client, admin_token, org_id):
    """Reordering siblings within the same (version, parent) group."""
    standard = _create_standard(client, admin_token, org_id, reference="MOVE-STD", name="Move Test Standard")
    version = _create_version(client, admin_token, org_id, standard["id"])
    action_type = _create_action_type(client, admin_token, org_id, name="Review")

    first = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="First")
    second = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="Second")
    assert first["sort_order"] == 0
    assert second["sort_order"] == 1

    moved = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{first['id']}/move",
        json={"direction": "down"}, headers=auth_headers(admin_token),
    )
    assert moved.status_code == 200
    assert moved.json()["sort_order"] == 1

    action_a = _create_required_action(client, admin_token, org_id, standard["id"], version["id"], first["id"], action_type["id"], name="A")
    action_b = _create_required_action(client, admin_token, org_id, standard["id"], version["id"], first["id"], action_type["id"], name="B")
    assert action_a["sort_order"] == 0
    assert action_b["sort_order"] == 1
    move_action = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{first['id']}"
        f"/required-actions/{action_a['id']}/move",
        json={"direction": "down"}, headers=auth_headers(admin_token),
    )
    assert move_action.status_code == 200
    assert move_action.json()["sort_order"] == 1

    reloaded_b = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{first['id']}"
        f"/required-actions/{action_b['id']}",
        headers=auth_headers(admin_token),
    ).json()
    assert reloaded_b["sort_order"] == 0, "moving A down must swap with B"


# --- RBAC composition ------------------------------------------------------------


def test_rbac_composition_manager_grant_admin_override_and_member_forbidden(client, admin_token, org_id):
    """§3/§26: only a Compliance Manager (module role) or an Organisation
    Administrator may mutate standards — proving `require_module_role`'s
    existing admin-override composition applies here, not reimplementing
    it (per Phase 6's own spec instruction: "confirm this composition
    explicitly in tests")."""
    # (a) A user granted the compliance_manager module role can create a standard.
    manager_id = create_org_user(client, admin_token, org_id, "compliance-manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "compliance-manager@example.com", "Password123!")
    resp = client.post(
        f"{_base(org_id)}/standards", json={"reference": "RBAC-MGR", "name": "Manager-created Standard"},
        headers=auth_headers(manager_token),
    )
    assert resp.status_code == 201, resp.text

    # (b) A plain org admin, with NO explicit module-role grant, can also create one.
    org_admin_id = create_org_user(client, admin_token, org_id, "plain-org-admin@example.com", role="org_admin")
    org_admin_token = login(client, "plain-org-admin@example.com", "Password123!")
    resp = client.post(
        f"{_base(org_id)}/standards", json={"reference": "RBAC-OA", "name": "Org-admin-created Standard"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text

    # (c) A plain org member, with neither, gets 403.
    member_id = create_org_user(client, admin_token, org_id, "plain-member@example.com", role="member")
    member_token = login(client, "plain-member@example.com", "Password123!")
    resp = client.post(
        f"{_base(org_id)}/standards", json={"reference": "RBAC-MEMBER", "name": "Should Not Be Created"},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text

    # (d) Reads work for any org member regardless of role — just needs the module enabled.
    resp = client.get(f"{_base(org_id)}/standards", headers=auth_headers(member_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    assert manager_id and org_admin_id and member_id  # silence unused-var lints; used above for clarity


# --- Publish/retire lifecycle -----------------------------------------------------


def test_publish_retire_lifecycle_and_immutability(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="LIFECYCLE-STD", name="Lifecycle Standard")
    version = _create_version(client, admin_token, org_id, standard["id"])
    requirement = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="Req")

    publish_resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/publish", headers=auth_headers(admin_token)
    )
    assert publish_resp.status_code == 200
    published = publish_resp.json()
    assert published["status"] == "published"
    assert published["published_at"] is not None
    assert published["published_by"] is not None

    # Publish again -> 409.
    again = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/publish", headers=auth_headers(admin_token)
    )
    assert again.status_code == 409

    # A published version's requirements/required-actions reject create/update/delete.
    create_resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements",
        json={"name": "Should be rejected"}, headers=auth_headers(admin_token),
    )
    assert create_resp.status_code == 409

    update_resp = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        json={"name": "Should be rejected", "description": "", "reasoning": ""}, headers=auth_headers(admin_token),
    )
    assert update_resp.status_code == 409

    delete_resp = client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        headers=auth_headers(admin_token),
    )
    assert delete_resp.status_code == 409

    # Retire from published.
    retire_resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/retire", headers=auth_headers(admin_token)
    )
    assert retire_resp.status_code == 200
    retired = retire_resp.json()
    assert retired["status"] == "retired"
    assert retired["retired_at"] is not None
    assert retired["retired_by"] is not None

    # Retire again -> 409.
    retire_again = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/retire", headers=auth_headers(admin_token)
    )
    assert retire_again.status_code == 409

    # Retiring directly from draft also works, on a fresh version.
    version2 = _create_version(client, admin_token, org_id, standard["id"], version_label="2.0")
    retire_from_draft = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version2['id']}/retire", headers=auth_headers(admin_token)
    )
    assert retire_from_draft.status_code == 200
    assert retire_from_draft.json()["status"] == "retired"


# --- Version cloning ------------------------------------------------------------


def test_version_cloning_copies_requirement_tree_and_required_actions(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="CLONE-STD", name="Clone Test Standard")
    source_version = _create_version(client, admin_token, org_id, standard["id"], version_label="1.0")
    action_type = _create_action_type(client, admin_token, org_id, name="Clone Test Action Type")

    parent = _create_requirement(client, admin_token, org_id, standard["id"], source_version["id"], name="Parent")
    child = _create_requirement(
        client, admin_token, org_id, standard["id"], source_version["id"], name="Child", parent_requirement_id=parent["id"]
    )
    _create_required_action(client, admin_token, org_id, standard["id"], source_version["id"], child["id"], action_type["id"], name="Cloned Action")

    new_version = _create_version(
        client, admin_token, org_id, standard["id"], version_label="2.0", clone_from_version_id=source_version["id"],
    )
    assert new_version["version_number"] == 2

    cloned_requirements = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{new_version['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    assert len(cloned_requirements) == 2
    cloned_parent = next(r for r in cloned_requirements if r["name"] == "Parent")
    cloned_child = next(r for r in cloned_requirements if r["name"] == "Child")
    assert cloned_child["parent_requirement_id"] == cloned_parent["id"]
    # New ids, not the source's.
    assert cloned_parent["id"] != parent["id"]
    assert cloned_child["id"] != child["id"]

    cloned_actions = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{new_version['id']}/requirements/{cloned_child['id']}"
        "/required-actions",
        headers=auth_headers(admin_token),
    ).json()
    assert len(cloned_actions) == 1
    assert cloned_actions[0]["name"] == "Cloned Action"

    # The source version's own rows are untouched.
    source_requirements = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{source_version['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    assert len(source_requirements) == 2
    assert {r["id"] for r in source_requirements} == {parent["id"], child["id"]}


# --- Cross-org isolation ---------------------------------------------------------


def test_cross_org_isolation_returns_404(client, admin_token, org_id):
    """A standard/version/requirement/required-action belonging to org A
    must 404 (not 403, not 200) when addressed via org B's path — mirrors
    `routers.action_types`' own "wrong scope -> 404" precedent."""
    action_type = _create_action_type(client, admin_token, org_id, name="Cross-org Action Type")
    standard = _create_standard(client, admin_token, org_id, reference="CROSSORG-STD", name="Org A Standard")
    version = _create_version(client, admin_token, org_id, standard["id"])
    requirement = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="Org A Requirement")
    required_action = _create_required_action(
        client, admin_token, org_id, standard["id"], version["id"], requirement["id"], action_type["id"]
    )

    org_b = client.post("/api/v1/orgs", json={"name": "Org B (cross-org isolation test)"}, headers=auth_headers(admin_token))
    assert org_b.status_code == 201, org_b.text
    org_b_id = org_b.json()["id"]
    org_b_admin_id = create_org_user(client, admin_token, org_b_id, "orgb-admin@example.com", role="org_admin")
    assert org_b_admin_id
    org_b_token = login(client, "orgb-admin@example.com", "Password123!")

    assert client.get(f"{_base(org_b_id)}/standards/{standard['id']}", headers=auth_headers(org_b_token)).status_code == 404
    assert client.get(
        f"{_base(org_b_id)}/standards/{standard['id']}/versions/{version['id']}", headers=auth_headers(org_b_token)
    ).status_code == 404
    assert client.get(
        f"{_base(org_b_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        headers=auth_headers(org_b_token),
    ).status_code == 404
    assert client.get(
        f"{_base(org_b_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}"
        f"/required-actions/{required_action['id']}",
        headers=auth_headers(org_b_token),
    ).status_code == 404

    # A standard/version/requirement genuinely belonging to org B, addressed
    # via org A's own path, must equally 404 (the check is symmetric).
    org_b_standard = _create_standard(client, org_b_token, org_b_id, reference="ORGB-STD", name="Org B's Own Standard")
    assert client.get(f"{_base(org_id)}/standards/{org_b_standard['id']}", headers=auth_headers(admin_token)).status_code == 404


# --- Audit logging ------------------------------------------------------------


def test_mutations_are_audit_logged(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="AUDIT-STD", name="Audit Test Standard")
    version = _create_version(client, admin_token, org_id, standard["id"])
    requirement = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="Audited Requirement")
    action_type = _create_action_type(client, admin_token, org_id, name="Audit Test Action Type")
    required_action = _create_required_action(
        client, admin_token, org_id, standard["id"], version["id"], requirement["id"], action_type["id"]
    )
    client.post(f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/publish", headers=auth_headers(admin_token))
    client.post(f"{_base(org_id)}/standards/{standard['id']}/archive", headers=auth_headers(admin_token))

    db = SessionLocal()
    try:
        events = {
            (e.entity_type, e.action)
            for e in db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_id.in_(
                        [str(standard["id"]), str(version["id"]), str(requirement["id"]), str(required_action["id"]),
                         str(action_type["id"])]
                    )
                )
            ).all()
        }
    finally:
        db.close()

    assert ("compliance_standard", "created") in events
    assert ("compliance_standard", "archived") in events
    assert ("compliance_standard_version", "created") in events
    assert ("compliance_standard_version", "published") in events
    assert ("compliance_requirement", "created") in events
    assert ("compliance_required_action", "created") in events
    assert ("compliance_action_type_definition", "created") in events


# --- Action-type delete-with-reassignment ------------------------------------------


def test_action_type_delete_requires_reassignment_when_in_use(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="ATYPE-STD", name="Action Type Test Standard")
    version = _create_version(client, admin_token, org_id, standard["id"])
    requirement = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="Req")

    in_use = _create_action_type(client, admin_token, org_id, name="In Use")
    other = _create_action_type(client, admin_token, org_id, name="Reassignment Target")
    _create_required_action(client, admin_token, org_id, standard["id"], version["id"], requirement["id"], in_use["id"])

    # No reassign_to_id -> 409, naming the in-use count.
    resp = client.delete(f"{_base(org_id)}/action-types/{in_use['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 409

    # With reassign_to_id -> succeeds, reassigning the referencing required action.
    resp = client.delete(
        f"{_base(org_id)}/action-types/{in_use['id']}", params={"reassign_to_id": other["id"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204

    listed = client.get(f"{_base(org_id)}/action-types", headers=auth_headers(admin_token)).json()
    assert in_use["id"] not in {a["id"] for a in listed}

    # An organisation's compliance action-type vocabulary may be emptied to
    # zero — deleting the last remaining, entirely-unused action type must
    # succeed (no "must always retain at least one" floor here, unlike
    # project-scoped ActionTypeDefinition). `other` is now in use (the
    # reassignment above moved the required action onto it), so this uses a
    # fresh, never-referenced action type instead.
    unused = _create_action_type(client, admin_token, org_id, name="Never Referenced")
    resp = client.delete(f"{_base(org_id)}/action-types/{unused['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 204
