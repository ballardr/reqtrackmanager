"""Tests for the `link` permission level: the vocabulary, the "every record type" atom, the generic link endpoints
accepting `link` or `manage`, the graph's `can_link`, the audit detail, and the
`Link editor` preset role.

Each test builds its own organisation (`tests.link_world.World`), so none depends on
state left by another test or run.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, GroupCustomRoleGrant
from app.models.enums import PermissionLevel
from app.models.organization import OrgGroup, OrgGroupMember
from app.models.relationship import ArtefactLink
from app.modules.registry import get_all_registered_artefact_types
from app.services.custom_role_presets import PRESETS
from app.services.permissions import ALL_ARTEFACT_TYPES, encode_permission, get_all_permissions, validate_permission_key
from app.services.rbac import permission_satisfied
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import REQ, World

DEC = "decision"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Link Permission Org", decisions=True)


def _member(world: World, project: dict) -> tuple[str, str]:
    """A plain project `member` (view only); returns `(user_id, token)`."""
    email = f"linker-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return user_id, login(world.client, email, "Password123!")


def _custom_role(world: World, permissions: list[str], scope: str = "project") -> str:
    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/custom-roles",
        json={"name": f"Role {uuid.uuid4().hex[:6]}", "description": "", "scope": scope, "permissions": permissions},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _grant(world: World, role_id: str, user_id: str, project: dict | None) -> None:
    resp = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/custom-roles/{role_id}/users/{user_id}",
        json={"project_id": project["id"] if project else None}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 204, resp.text


def _linker(world: World, project: dict, permissions: list[str]) -> str:
    """A project member who additionally holds a project-scoped custom role with `permissions`."""
    user_id, token = _member(world, project)
    _grant(world, _custom_role(world, permissions), user_id, project)
    return token


def _link_url(project: dict, artefact: tuple[str, uuid.UUID], link_id=None) -> str:
    base = f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/links"
    return f"{base}/{link_id}" if link_id else base


def _link_audit(link_id: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == "artefact_link", AuditEvent.entity_id == str(link_id)
        )).all())
    finally:
        db.close()


# --- vocabulary ---------------------------------------------------------------------------------


def test_vocabulary_lists_link_for_every_registered_type_and_for_all_types(world):
    db = SessionLocal()
    try:
        keys = {p.key for p in get_all_permissions(db, uuid.UUID(world.org["id"]))}
    finally:
        db.close()
    for artefact_type in get_all_registered_artefact_types():
        assert encode_permission(artefact_type, PermissionLevel.LINK.value) in keys
    for level in PermissionLevel:
        assert encode_permission(ALL_ARTEFACT_TYPES, level.value) in keys


def test_all_types_atom_is_valid_only_without_a_subtype(world):
    db = SessionLocal()
    try:
        org_id = uuid.UUID(world.org["id"])
        validate_permission_key(db, org_id, "*:link:")
        for bad in ("*:link:Architecture", "*:nonsense:", "other:link:"):
            with pytest.raises(ValueError):
                validate_permission_key(db, org_id, bad)
    finally:
        db.close()


def test_all_types_atom_covers_types_registered_later():
    held = {"*:link:"}
    assert permission_satisfied(held, "requirement:link:")
    assert permission_satisfied(held, "a_module_type_registered_next_month:link:")
    assert permission_satisfied(held, "decision:link:Architecture")
    assert not permission_satisfied(held, "requirement:manage:")  # only the level it names
    assert not permission_satisfied({"requirement:link:"}, "decision:link:")


# --- the generic endpoints ----------------------------------------------------------------------


def test_link_only_user_can_link_and_unlink_but_not_edit_or_approve(world, client):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    related = world.link_types_by_name()["Related to"]["id"]
    token = _linker(world, project, [encode_permission(REQ, "link")])

    created = client.post(
        _link_url(project, req),
        json={"link_type_id": str(related), "direction": "outgoing", "other_type": DEC, "other_id": str(dec[1])},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    link_id = created.json()["id"]
    deleted = client.delete(_link_url(project, req, link_id), headers=auth_headers(token))
    assert deleted.status_code == 204, deleted.text

    # `link` confers nothing else on the requirement.
    assert client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req[1]}", json={
            "name": "Renamed", "component_id": project["component_id"], "category_id": project["category_id"],
            "owner": {"type": "user", "id": str(world.user_id)},
        },
        headers=auth_headers(token),
    ).status_code == 403
    assert client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req[1]}/approve", headers=auth_headers(token)
    ).status_code == 403


def test_view_only_member_is_still_refused(world):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    related = world.link_types_by_name()["Related to"]["id"]
    _user, token = _member(world, project)
    assert world.generic_link(project, req, related, dec, token=token).status_code == 403


def test_link_is_per_artefact_type_of_the_page(world):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    related = world.link_types_by_name()["Related to"]["id"]
    token = _linker(world, project, [encode_permission(REQ, "link")])
    assert world.generic_link(project, req, related, dec, token=token).status_code == 201
    # The same link from the decision's page needs `link` on decisions.
    assert world.generic_link(project, dec, world.link_types_by_name()["Implements"]["id"], req, token=token).status_code == 403


def test_manage_alone_still_works(world):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    related = world.link_types_by_name()["Related to"]["id"]
    token = _linker(world, project, [encode_permission(REQ, "manage")])
    assert world.generic_link(project, req, related, dec, token=token).status_code == 201


def test_all_types_grant_links_from_any_page(world):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    types = world.link_types_by_name()
    token = _linker(world, project, ["*:link:"])
    assert world.generic_link(project, req, types["Related to"]["id"], dec, token=token).status_code == 201
    assert world.generic_link(project, dec, types["Implements"]["id"], req, token=token).status_code == 201


def test_project_scoped_grant_does_not_apply_in_another_project(world):
    first, second = world.project("First"), world.project("Second")
    req_first, dec_first = (REQ, world.requirement(first)), (DEC, world.decision(first, "DEC-A"))
    req_second, dec_second = (REQ, world.requirement(second)), (DEC, world.decision(second, "DEC-B"))
    related = world.link_types_by_name()["Related to"]["id"]
    user_id, token = _member(world, first)
    client = world.client
    assert client.post(
        f"/api/v1/projects/{second['id']}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(world.token),
    ).status_code in (200, 201, 204)
    _grant(world, _custom_role(world, [encode_permission(REQ, "link")]), user_id, first)
    assert world.generic_link(first, req_first, related, dec_first, token=token).status_code == 201
    assert world.generic_link(second, req_second, related, dec_second, token=token).status_code == 403


def test_group_grant_works(world):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    related = world.link_types_by_name()["Related to"]["id"]
    user_id, token = _member(world, project)
    role_id = _custom_role(world, [encode_permission(REQ, "link")])
    db = SessionLocal()
    try:
        group = OrgGroup(organization_id=world.org["id"], name=f"Linkers {uuid.uuid4().hex[:4]}")
        db.add(group)
        db.flush()
        db.add(OrgGroupMember(org_group_id=group.id, user_id=uuid.UUID(user_id)))
        db.add(GroupCustomRoleGrant(
            org_group_id=group.id, custom_role_id=uuid.UUID(role_id), organization_id=world.org["id"],
            project_id=project["id"],
        ))
        db.commit()
    finally:
        db.close()
    assert world.generic_link(project, req, related, dec, token=token).status_code == 201


def test_approved_requirement_in_a_change_request_project_is_still_refused(world, client):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    related = world.link_types_by_name()["Related to"]["id"]
    token = _linker(world, project, [encode_permission(REQ, "link")])
    assert client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req[1]}/approve", headers=auth_headers(world.token)
    ).status_code == 200
    client.patch(
        f"/api/v1/projects/{project['id']}", json={"require_change_request_for_approved_links": True},
        headers=auth_headers(world.token),
    )
    refused = world.generic_link(project, req, related, dec, token=token)
    assert refused.status_code == 409 and "change request" in refused.json()["detail"]


def test_link_rules_still_apply_to_a_link_only_user(world):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    created = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/link-types",
        json={
            "forward_name": f"Only decisions {uuid.uuid4().hex[:4]}", "reverse_name": "Back",
            "allowed_source_types": [DEC], "allowed_target_types": [DEC],
        },
        headers=auth_headers(world.token),
    )
    assert created.status_code == 201, created.text
    restricted = created.json()["id"]
    token = _linker(world, project, [encode_permission(REQ, "link")])
    assert world.generic_link(project, req, restricted, dec, token=token).status_code == 400


def test_graph_can_link_follows_the_link_level(world):
    project = world.project()
    req = world.requirement(project)
    _user, view_token = _member(world, project)
    link_token = _linker(world, project, [encode_permission(REQ, "link")])
    assert world.graph(project, (REQ, req), token=view_token).json()["can_link"] is False
    assert world.graph(project, (REQ, req), token=link_token).json()["can_link"] is True


def test_audit_records_which_permission_authorised_the_link(world, client):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    related = world.link_types_by_name()["Related to"]["id"]
    token = _linker(world, project, [encode_permission(REQ, "link")])
    link_id = world.generic_link(project, req, related, dec, token=token).json()["id"]
    assert client.delete(_link_url(project, req, link_id), headers=auth_headers(token)).status_code == 204
    assert [e.detail["authorised_by"] for e in _link_audit(link_id)] == ["link", "link"]

    # `manage` is recorded as `manage` even when `link` would also have sufficed.
    both = _linker(world, project, [encode_permission(REQ, "link"), encode_permission(REQ, "manage")])
    other_id = world.generic_link(project, req, related, dec, token=both).json()["id"]
    assert [e.detail["authorised_by"] for e in _link_audit(other_id)] == ["manage"]


# --- the Link editor preset ---------------------------------------------------------------------


def test_a_new_organisation_gets_the_link_editor_preset(world):
    db = SessionLocal()
    try:
        role = db.scalar(select(CustomRoleDefinition).where(
            CustomRoleDefinition.organization_id == world.org["id"], CustomRoleDefinition.name == "Link editor"
        ))
        assert role is not None and role.scope == "project"
        permissions = set(db.scalars(select(CustomRolePermission.permission).where(
            CustomRolePermission.custom_role_id == role.id
        )).all())
    finally:
        db.close()
    assert permissions == {"*:view:", "*:link:"}


def test_preset_role_can_be_granted_and_links(world):
    project = world.project()
    req, dec = (REQ, world.requirement(project)), (DEC, world.decision(project))
    related = world.link_types_by_name()["Related to"]["id"]
    roles = world.client.get(f"/api/v1/orgs/{world.org['id']}/custom-roles", headers=auth_headers(world.token)).json()
    preset_id = next(r["id"] for r in roles if r["name"] == "Link editor")
    user_id, token = _member(world, project)
    _grant(world, preset_id, user_id, project)
    assert world.generic_link(project, req, related, dec, token=token).status_code == 201


def test_presets_endpoint_lists_the_definitions_for_org_admins_only(world, client):
    listed = client.get(f"/api/v1/orgs/{world.org['id']}/custom-role-presets", headers=auth_headers(world.token))
    assert listed.status_code == 200
    assert [p["key"] for p in listed.json()] == [p.key for p in PRESETS]
    member_id = create_org_user(client, world.token, world.org["id"], f"m-{uuid.uuid4().hex[:6]}@example.com")
    assert member_id
    token = login(client, next(
        u["email"] for u in client.get(f"/api/v1/orgs/{world.org['id']}/users", headers=auth_headers(world.token)).json()
        if u["user_id"] == member_id
    ), "Password123!")
    assert client.get(
        f"/api/v1/orgs/{world.org['id']}/custom-role-presets", headers=auth_headers(token)
    ).status_code == 403


# --- default roles: link while a record is not approved ------------------------------------------------


def _with_role(world: World, project: dict, role: str) -> str:
    """A user holding only the built-in project `role`; returns their token."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


def _links_between(first: uuid.UUID, second: uuid.UUID) -> list:
    db = SessionLocal()
    try:
        return list(db.scalars(select(ArtefactLink).where(
            ArtefactLink.source_id.in_([first, second]), ArtefactLink.target_id.in_([first, second])
        )).all())
    finally:
        db.close()


def _approve(world: World, project: dict, requirement: uuid.UUID) -> None:
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement}/approve", headers=auth_headers(world.token)
    )
    assert resp.status_code == 200, resp.text


def _post_link(world: World, project: dict, page, other, token: str):
    related = world.link_types_by_name()["Related to"]["id"]
    return world.client.post(
        _link_url(project, page),
        json={"link_type_id": str(related), "direction": "outgoing", "other_type": other[0], "other_id": str(other[1])},
        headers=auth_headers(token),
    )


@pytest.mark.parametrize("role", ["stakeholder", "project_administrator"])
def test_stakeholders_and_administrators_link_and_unlink_unapproved_requirements(world, role):
    project = world.project()
    a, b = (REQ, world.requirement(project, "A")), (REQ, world.requirement(project, "B"))
    token = _with_role(world, project, role)
    created = _post_link(world, project, a, b, token)
    assert created.status_code == 201, created.text
    assert [e.detail["authorised_by"] for e in _link_audit(created.json()["id"])] == ["role"]
    deleted = world.client.delete(_link_url(project, a, created.json()["id"]), headers=auth_headers(token))
    assert deleted.status_code == 204, deleted.text


def test_a_plain_member_cannot_link_even_an_unapproved_requirement(world):
    project = world.project()
    a, b = (REQ, world.requirement(project, "A")), (REQ, world.requirement(project, "B"))
    assert _post_link(world, project, a, b, _with_role(world, project, "member")).status_code == 403


def test_default_roles_cannot_link_an_approved_requirement_from_either_end(world):
    project = world.project()
    approved = world.requirement(project, "Approved")
    draft = world.requirement(project, "Draft")
    _approve(world, project, approved)
    token = _with_role(world, project, "stakeholder")
    from_approved = _post_link(world, project, (REQ, approved), (REQ, draft), token)
    from_draft = _post_link(world, project, (REQ, draft), (REQ, approved), token)  # the approved one is the other end
    assert from_approved.status_code == 403 and "Link permission" in from_approved.json()["detail"]
    assert from_draft.status_code == 403
    assert _links_between(approved, draft) == []


def test_default_roles_cannot_remove_a_link_from_an_approved_requirement(world):
    project = world.project()
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    link_id = world.generic_link(project, (REQ, a), world.link_types_by_name()["Related to"]["id"], (REQ, b)).json()["id"]
    _approve(world, project, a)
    token = _with_role(world, project, "project_administrator")
    refused = world.client.delete(_link_url(project, (REQ, b), link_id), headers=auth_headers(token))
    assert refused.status_code == 403


def test_the_link_permission_links_an_approved_requirement_in_any_state(world):
    project = world.project()
    approved, other = world.requirement(project, "Approved"), world.requirement(project, "Other")
    _approve(world, project, approved)
    token = _linker(world, project, [encode_permission(REQ, "link")])
    created = _post_link(world, project, (REQ, approved), (REQ, other), token)
    assert created.status_code == 201, created.text
    assert [e.detail["authorised_by"] for e in _link_audit(created.json()["id"])] == ["link"]


def test_a_project_that_requires_change_requests_for_links_still_refuses_everyone_directly(world):
    project = world.project()
    approved, other = world.requirement(project, "Approved"), world.requirement(project, "Other")
    _approve(world, project, approved)
    world.client.patch(
        f"/api/v1/projects/{project['id']}", json={"require_change_request_for_approved_links": True},
        headers=auth_headers(world.token),
    )
    token = _linker(world, project, [encode_permission(REQ, "link")])
    assert _post_link(world, project, (REQ, approved), (REQ, other), token).status_code == 409


def test_default_roles_do_not_reach_a_modules_records(world):
    project = world.project()
    dec, req = (DEC, world.decision(project)), (REQ, world.requirement(project))
    token = _with_role(world, project, "stakeholder")
    assert _post_link(world, project, dec, req, token).status_code == 403  # a module's types need `link` or `manage`


def test_graph_reports_direct_and_proposing_rights_per_record_state(world):
    project = world.project()
    draft, approved = world.requirement(project, "Draft"), world.requirement(project, "Approved")
    _approve(world, project, approved)

    def flags(token: str, requirement: uuid.UUID) -> tuple[bool, bool]:
        graph = world.graph(project, (REQ, requirement), token=token).json()
        return graph["can_link"], graph["can_propose"]

    stakeholder = _with_role(world, project, "stakeholder")
    assert flags(stakeholder, draft) == (True, True)
    assert flags(stakeholder, approved) == (False, True)  # may still propose it through a change request
    assert flags(_with_role(world, project, "member"), draft) == (False, False)
    assert flags(_linker(world, project, [encode_permission(REQ, "link")]), approved) == (True, True)


def test_the_finder_accepts_the_draft_id_for_a_stakeholder(world):
    project = world.project()
    draft = f"/api/v1/projects/{project['id']}/artefacts/{REQ}/{uuid.UUID(int=0)}/link-types"
    assert world.client.get(draft, headers=auth_headers(_with_role(world, project, "stakeholder"))).status_code == 200
    assert world.client.get(draft, headers=auth_headers(_with_role(world, project, "member"))).status_code == 403
