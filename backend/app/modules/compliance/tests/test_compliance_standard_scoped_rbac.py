"""Tests for the Compliance Module's Phase 22 standard-scoped RBAC
(docs/compliance-module-plan.md Phase 22): the two new `standards_manager`/
`standards_contributor` module-contributed roles (scope `"standard"`,
module system `ModuleRoleDefinition`'s new generalised entity-scope
mechanism), their composition with org-scoped `compliance_manager`/
`OrgRole.ORG_ADMIN`/`is_server_admin`, standard-creation auto-granting the
creator, the standard's own member-list grant/revoke endpoints, and the
"a standard must always have at least one standards_manager" floor
(including the org-group SSO fallback).

Every test uses the real `/api/v1/orgs/{organization_id}/modules/compliance`
endpoints via the `client` fixture, mirroring `test_compliance_standards_
api.py`'s own style."""

from __future__ import annotations

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers, create_org_user, login


def _base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/compliance"


def _create_standard(client, token, org_id, *, reference="ISO-27001", name="Corporate Security Standard", **extra):
    payload = {"reference": reference, "name": name, "initial_version_label": "1.0", **extra}
    resp = client.post(f"{_base(org_id)}/standards", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _grant_compliance_manager(client, admin_token, org_id, user_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": "compliance", "role_key": "compliance_manager"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _grant_standard_role(client, token, org_id, standard_id, user_id, role_key, *, expect=204):
    resp = client.post(
        f"{_base(org_id)}/standards/{standard_id}/members/{user_id}/roles",
        json={"role_key": role_key}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp


def _revoke_standard_role(client, token, org_id, standard_id, user_id, role_key):
    return client.delete(
        f"{_base(org_id)}/standards/{standard_id}/members/{user_id}/roles/{role_key}", headers=auth_headers(token),
    )


def _create_org_group(client, admin_token, org_id, name="Compliance Managers"):
    resp = client.post(f"/api/v1/orgs/{org_id}/groups", json={"name": name}, headers=auth_headers(admin_token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _add_org_group_member(client, admin_token, org_id, group_id, user_id):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/groups/{group_id}/members", json={"user_id": user_id}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _set_fallback_group(client, admin_token, org_id, group_id):
    resp = client.put(
        f"{_base(org_id)}/settings", json={"default_standards_manager_group_id": group_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _grant_standard_group_role(client, token, org_id, standard_id, group_id, role_key, *, expect=204):
    resp = client.post(
        f"{_base(org_id)}/standards/{standard_id}/group-roles",
        json={"org_group_id": group_id, "role_key": role_key}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp


def _revoke_standard_group_role(client, token, org_id, standard_id, group_id, role_key):
    return client.delete(
        f"{_base(org_id)}/standards/{standard_id}/group-roles/{group_id}/{role_key}", headers=auth_headers(token),
    )


# --- Standard creation auto-grants the creator -------------------------------


def test_create_standard_auto_grants_creator_standards_manager(client, admin_token, org_id):
    manager_id = create_org_user(client, admin_token, org_id, "standard_creator@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "standard_creator@example.com", "Password123!")

    standard = _create_standard(client, manager_token, org_id, reference="AUTO-1", name="Auto Grant Standard")

    resp = client.get(f"{_base(org_id)}/standards/{standard['id']}/members", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(m["user_id"] == manager_id and "standards_manager" in m["role_keys"] for m in body["members"])


# --- Override composition -----------------------------------------------------


def test_org_compliance_manager_satisfies_standard_manage_with_no_per_standard_grant(client, admin_token, org_id):
    """A plain `compliance_manager` grant (org-scoped) must satisfy the
    standard-scoped `standards_manager` check via `ModuleRoleDefinition.
    overridden_by`, with no per-standard grant of its own."""
    standard = _create_standard(client, admin_token, org_id, reference="OVR-1")
    manager_id = create_org_user(client, admin_token, org_id, "org_wide_manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "org_wide_manager@example.com", "Password123!")

    resp = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}",
        json={"name": "Renamed via org override", "description": "", "issuing_organisation": None,
              "owner_id": standard["owner_id"]},
        headers=auth_headers(manager_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed via org override"


def test_org_admin_satisfies_standard_manage(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="OVR-2")
    create_org_user(client, admin_token, org_id, "org_admin_standard@example.com", role="org_admin")
    org_admin_token = login(client, "org_admin_standard@example.com", "Password123!")

    resp = client.post(f"{_base(org_id)}/standards/{standard['id']}/archive", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text


def test_plain_org_member_cannot_manage_a_standard_with_no_grant(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="OVR-3")
    create_org_user(client, admin_token, org_id, "plain_standard_viewer@example.com", role="member")
    plain_token = login(client, "plain_standard_viewer@example.com", "Password123!")

    resp = client.post(f"{_base(org_id)}/standards/{standard['id']}/archive", headers=auth_headers(plain_token))
    assert resp.status_code == 403


def test_direct_standards_manager_grant_satisfies_manage_on_that_standard_only(client, admin_token, org_id):
    standard_a = _create_standard(client, admin_token, org_id, reference="OVR-4A")
    standard_b = _create_standard(client, admin_token, org_id, reference="OVR-4B")
    user_id = create_org_user(client, admin_token, org_id, "narrow_manager@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard_a["id"], user_id, "standards_manager")
    user_token = login(client, "narrow_manager@example.com", "Password123!")

    resp = client.post(f"{_base(org_id)}/standards/{standard_a['id']}/archive", headers=auth_headers(user_token))
    assert resp.status_code == 200, resp.text

    # No grant on standard_b -> 403.
    resp = client.post(f"{_base(org_id)}/standards/{standard_b['id']}/archive", headers=auth_headers(user_token))
    assert resp.status_code == 403


# --- standards_contributor: draft content yes, publish/retire/members no ------


def test_standards_contributor_can_edit_draft_requirement_but_not_publish_or_manage_members(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="CONTRIB-1")
    versions = client.get(f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token))
    version = versions.json()[0]

    contributor_id = create_org_user(client, admin_token, org_id, "contributor@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], contributor_id, "standards_contributor")
    contributor_token = login(client, "contributor@example.com", "Password123!")

    # May create a requirement on the draft version.
    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements",
        json={"name": "Contributor-authored requirement"}, headers=auth_headers(contributor_token),
    )
    assert resp.status_code == 201, resp.text
    requirement = resp.json()

    # May update it too.
    resp = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        json={"name": "Updated by contributor", "reference": "", "description": "", "reasoning": ""},
        headers=auth_headers(contributor_token),
    )
    assert resp.status_code == 200, resp.text

    # May not publish the version.
    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/publish",
        headers=auth_headers(contributor_token),
    )
    assert resp.status_code == 403

    # May not archive the standard.
    resp = client.post(f"{_base(org_id)}/standards/{standard['id']}/archive", headers=auth_headers(contributor_token))
    assert resp.status_code == 403

    # May not manage the standard's own member list.
    other_id = create_org_user(client, admin_token, org_id, "someone_else@example.com", role="member")
    resp = _grant_standard_role(
        client, contributor_token, org_id, standard["id"], other_id, "standards_contributor", expect=403
    )


# --- Effective-roles resolution excludes a revoked grant -----------------------


def test_revoking_standard_role_removes_access(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="REVOKE-1")
    # Grant a second manager first so removing the first isn't blocked by the floor.
    second_manager_id = create_org_user(client, admin_token, org_id, "second_manager@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], second_manager_id, "standards_manager")

    contributor_id = create_org_user(client, admin_token, org_id, "revocable_contributor@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], contributor_id, "standards_contributor")
    contributor_token = login(client, "revocable_contributor@example.com", "Password123!")

    versions = client.get(f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token))
    version = versions.json()[0]
    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements",
        json={"name": "Before revoke"}, headers=auth_headers(contributor_token),
    )
    assert resp.status_code == 201

    resp = _revoke_standard_role(client, admin_token, org_id, standard["id"], contributor_id, "standards_contributor")
    assert resp.status_code == 204

    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements",
        json={"name": "After revoke"}, headers=auth_headers(contributor_token),
    )
    assert resp.status_code == 403


# --- "Last standards_manager" floor -------------------------------------------


def test_removing_last_explicit_standards_manager_400s_with_no_fallback_group(client, admin_token, org_id):
    manager_id = create_org_user(client, admin_token, org_id, "sole_manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "sole_manager@example.com", "Password123!")
    standard = _create_standard(client, manager_token, org_id, reference="FLOOR-1")

    # manager_id is the standard's only explicit standards_manager (auto-granted on creation).
    resp = _revoke_standard_role(client, admin_token, org_id, standard["id"], manager_id, "standards_manager")
    assert resp.status_code == 400, resp.text


def test_removing_last_explicit_standards_manager_succeeds_with_nonempty_fallback_group(client, admin_token, org_id):
    manager_id = create_org_user(client, admin_token, org_id, "sole_manager_2@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "sole_manager_2@example.com", "Password123!")
    standard = _create_standard(client, manager_token, org_id, reference="FLOOR-2")

    fallback_member_id = create_org_user(client, admin_token, org_id, "fallback_member@example.com", role="member")
    group_id = _create_org_group(client, admin_token, org_id, name="Fallback Compliance Managers")
    _add_org_group_member(client, admin_token, org_id, group_id, fallback_member_id)
    _set_fallback_group(client, admin_token, org_id, group_id)

    resp = _revoke_standard_role(client, admin_token, org_id, standard["id"], manager_id, "standards_manager")
    assert resp.status_code == 204, resp.text

    # The fallback group's member now resolves as an effective standards manager.
    resp = client.get(f"{_base(org_id)}/standards/{standard['id']}/members", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["manager_floor_covered_by_fallback"] is True


def test_removing_last_member_of_fallback_group_that_is_a_standards_only_coverage_is_blocked(client, admin_token, org_id):
    """Mirrors the project/org floor's own 'can't leave zero' shape one
    level up: if a standard's manager floor is currently satisfied *only*
    by the fallback group (no explicit grant of its own), removing that
    group's last member must itself be blocked."""
    manager_id = create_org_user(client, admin_token, org_id, "sole_manager_3@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "sole_manager_3@example.com", "Password123!")
    standard = _create_standard(client, manager_token, org_id, reference="FLOOR-3")

    fallback_member_id = create_org_user(client, admin_token, org_id, "fallback_member_only@example.com", role="member")
    group_id = _create_org_group(client, admin_token, org_id, name="Only Fallback")
    _add_org_group_member(client, admin_token, org_id, group_id, fallback_member_id)
    _set_fallback_group(client, admin_token, org_id, group_id)

    # Remove the explicit grant so the standard now relies entirely on the fallback group.
    resp = _revoke_standard_role(client, admin_token, org_id, standard["id"], manager_id, "standards_manager")
    assert resp.status_code == 204, resp.text

    # Now remove the group's only member — this must be blocked the same way
    # "remove a project's last manager" already is (routers/orgs.py's own
    # remove_org_group_member 400 shape), since this org's whole compliance
    # fallback floor is currently resting on this one person.
    resp = client.delete(
        f"/api/v1/orgs/{org_id}/groups/{group_id}/members/{fallback_member_id}", headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_manage_gate_audit_logged(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="AUDIT-1")
    other_id = create_org_user(client, admin_token, org_id, "audit_grantee@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], other_id, "standards_manager")

    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(
            AuditEvent.entity_type == "user_module_role", AuditEvent.action == "granted",
            AuditEvent.entity_id == other_id,
        ).first()
        assert event is not None
        assert event.detail["role_key"] == "standards_manager"
        assert event.detail["standard_id"] == standard["id"]
    finally:
        db.close()


# --- Group-based grants (module system Phase 30) -------------------------------


def test_group_grant_satisfies_standard_manage_for_group_member(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="GROUP-1")
    group_member_id = create_org_user(client, admin_token, org_id, "group_grant_member@example.com", role="member")
    group_id = _create_org_group(client, admin_token, org_id, name="Standard Contributors Group")
    _add_org_group_member(client, admin_token, org_id, group_id, group_member_id)

    # Not yet granted — refused.
    member_token = login(client, "group_grant_member@example.com", "Password123!")
    resp = client.post(f"{_base(org_id)}/standards/{standard['id']}/archive", headers=auth_headers(member_token))
    assert resp.status_code == 403

    _grant_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_manager")
    resp = client.post(f"{_base(org_id)}/standards/{standard['id']}/archive", headers=auth_headers(member_token))
    assert resp.status_code == 200, resp.text


def test_removing_group_member_removes_access_granted_via_group(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="GROUP-2")
    group_member_id = create_org_user(client, admin_token, org_id, "group_grant_leaver@example.com", role="member")
    group_id = _create_org_group(client, admin_token, org_id, name="Leaver Group")
    _add_org_group_member(client, admin_token, org_id, group_id, group_member_id)
    _grant_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_contributor")

    versions = client.get(f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token))
    version = versions.json()[0]
    member_token = login(client, "group_grant_leaver@example.com", "Password123!")
    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements",
        json={"name": "Via group, before leaving"}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 201, resp.text

    resp = client.delete(
        f"/api/v1/orgs/{org_id}/groups/{group_id}/members/{group_member_id}", headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text

    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements",
        json={"name": "Via group, after leaving"}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


def test_revoking_group_role_removes_access(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="GROUP-3")
    group_member_id = create_org_user(client, admin_token, org_id, "group_grant_revoked@example.com", role="member")
    group_id = _create_org_group(client, admin_token, org_id, name="Revoked Grant Group")
    _add_org_group_member(client, admin_token, org_id, group_id, group_member_id)
    _grant_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_contributor")
    member_token = login(client, "group_grant_revoked@example.com", "Password123!")

    resp = client.post(f"{_base(org_id)}/standards/{standard['id']}/archive", headers=auth_headers(member_token))
    assert resp.status_code == 403  # contributor, not manager

    resp = _revoke_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_contributor")
    assert resp.status_code == 204, resp.text

    versions = client.get(f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token))
    version = versions.json()[0]
    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements",
        json={"name": "After group grant revoked"}, headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


def test_standard_group_grant_appears_in_members_roster_with_member_count(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="GROUP-4")
    group_member_id = create_org_user(client, admin_token, org_id, "group_grant_roster@example.com", role="member")
    group_id = _create_org_group(client, admin_token, org_id, name="Roster Group")
    _add_org_group_member(client, admin_token, org_id, group_id, group_member_id)
    _grant_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_contributor")

    resp = client.get(f"{_base(org_id)}/standards/{standard['id']}/members", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    group_members = resp.json()["group_members"]
    assert len(group_members) == 1
    assert group_members[0]["org_group_id"] == group_id
    assert group_members[0]["group_name"] == "Roster Group"
    assert group_members[0]["role_keys"] == ["standards_contributor"]
    assert group_members[0]["member_count"] == 1


def test_standards_contributor_cannot_call_group_grant_endpoints(client, admin_token, org_id):
    """RBAC boundary mirroring `test_standards_contributor_can_edit_draft_
    requirement_but_not_publish_or_manage_members`'s own assertion, one
    mechanism further: a contributor may not grant or revoke a group role
    either, same manager-tier-only gate as the direct-user endpoints."""
    standard = _create_standard(client, admin_token, org_id, reference="GROUP-5")
    contributor_id = create_org_user(client, admin_token, org_id, "group_endpoint_contributor@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], contributor_id, "standards_contributor")
    contributor_token = login(client, "group_endpoint_contributor@example.com", "Password123!")
    group_id = _create_org_group(client, admin_token, org_id, name="Boundary Test Group")

    _grant_standard_group_role(
        client, contributor_token, org_id, standard["id"], group_id, "standards_contributor", expect=403
    )
    resp = _revoke_standard_group_role(client, contributor_token, org_id, standard["id"], group_id, "standards_contributor")
    assert resp.status_code == 403


def test_removing_last_explicit_manager_succeeds_when_a_group_grant_covers_the_floor(client, admin_token, org_id):
    manager_id = create_org_user(client, admin_token, org_id, "group_floor_creator@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "group_floor_creator@example.com", "Password123!")
    standard = _create_standard(client, manager_token, org_id, reference="GROUP-FLOOR-1")

    group_manager_id = create_org_user(client, admin_token, org_id, "group_floor_manager@example.com", role="member")
    group_id = _create_org_group(client, admin_token, org_id, name="Group Floor Managers")
    _add_org_group_member(client, admin_token, org_id, group_id, group_manager_id)
    _grant_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_manager")

    # manager_id is the only *direct* standards_manager — a group grant with
    # a member now also covers the floor, so removing it must succeed.
    resp = _revoke_standard_role(client, admin_token, org_id, standard["id"], manager_id, "standards_manager")
    assert resp.status_code == 204, resp.text


def test_removing_only_group_manager_grant_400s_with_no_other_coverage(client, admin_token, org_id):
    manager_id = create_org_user(client, admin_token, org_id, "group_floor_only_creator@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "group_floor_only_creator@example.com", "Password123!")
    standard = _create_standard(client, manager_token, org_id, reference="GROUP-FLOOR-2")

    group_manager_id = create_org_user(client, admin_token, org_id, "group_floor_only_manager@example.com", role="member")
    group_id = _create_org_group(client, admin_token, org_id, name="Only Group Floor Managers")
    _add_org_group_member(client, admin_token, org_id, group_id, group_manager_id)
    _grant_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_manager")

    # Remove the creator's own direct grant first, leaving the group grant
    # as the standard's only manager coverage.
    resp = _revoke_standard_role(client, admin_token, org_id, standard["id"], manager_id, "standards_manager")
    assert resp.status_code == 204, resp.text

    # Now removing the group's own grant must 400 — it's the last coverage.
    resp = _revoke_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_manager")
    assert resp.status_code == 400, resp.text


def test_group_grant_audit_logged(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="GROUP-AUDIT-1")
    group_id = _create_org_group(client, admin_token, org_id, name="Audit Group")
    _grant_standard_group_role(client, admin_token, org_id, standard["id"], group_id, "standards_manager")

    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(
            AuditEvent.entity_type == "group_module_role", AuditEvent.action == "granted",
            AuditEvent.entity_id == group_id,
        ).first()
        assert event is not None
        assert event.detail["role_key"] == "standards_manager"
        assert event.detail["standard_id"] == standard["id"]
    finally:
        db.close()
