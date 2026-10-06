"""Tests for project-level link types (docs/plans/platform-enhancements-2026-10-plan.md
Phase 5c): a project's own link types inherited by descendants, hiding organisation
types, project-scope artefact-type rules (nearest wins), the organisation lock, the
tenant-isolation rules around a type that is no longer simply "the organisation's",
and deleting a type other projects use (keep by copy).

Each test builds its own organisation (`tests.link_world.World`), so none depends on
state left by another test or run.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.services.link_type_scope import LinkRuleError, assert_link_type_usable
from app.services.link_types import ensure_org_link_type, validate_link_allowed
from tests.conftest import auth_headers, create_org_user, create_project, login
from tests.link_world import ACTION, REQ, World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Project Link Types Org")


def _lt(project: dict, suffix: str = "") -> str:
    return f"/api/v1/projects/{project['id']}/link-types{suffix}"


def _tree(world: World) -> tuple[dict, dict, dict, dict]:
    """A parent project with two children and a sibling root: `(parent, child, sibling_child, other_root)`."""
    parent = create_project(world.client, world.token, world.org["id"], "Parent", can_be_parent=True)
    child = create_project(world.client, world.token, world.org["id"], "Child", parent_project_id=parent["id"], can_be_parent=True)
    sibling = create_project(world.client, world.token, world.org["id"], "Sibling", parent_project_id=parent["id"])
    other = create_project(world.client, world.token, world.org["id"], "Other root")
    return parent, child, sibling, other


def _with_content(world: World, project: dict) -> dict:
    """Adds a component/category (as `component_id`/`category_id`) so requirements can be created
    (a no-op for a project `World.project` already set up)."""
    from tests.conftest import create_component_and_category

    if "component_id" in project:
        return project
    project["component_id"], project["category_id"] = create_component_and_category(world.client, world.token, project["id"])
    return project


def _create_local(world: World, project: dict, forward: str, reverse: str = "Reverse", token: str | None = None, **extra):
    return world.client.post(
        _lt(project), json={"forward_name": forward, "reverse_name": reverse, **extra},
        headers=auth_headers(token or world.token),
    )


def _local(world: World, project: dict, forward: str, reverse: str = "Reverse", **extra) -> dict:
    resp = _create_local(world, project, forward, reverse, **extra)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _panel(world: World, project: dict, token: str | None = None) -> dict[str, dict]:
    resp = world.client.get(_lt(project), headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return {row["forward_name"]: row for row in resp.json()["items"]}


def _offered(world: World, project: dict, artefact: tuple[str, uuid.UUID]) -> set[str]:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/link-types",
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return {o["forward_name"] for o in resp.json()}


def _rename(world: World, project: dict, type_id: str, forward: str = "z", reverse: str = "z", **extra):
    return world.client.patch(
        _lt(project, f"/{type_id}"), json={"forward_name": forward, "reverse_name": reverse, **extra},
        headers=auth_headers(world.token),
    )


def _put_rule(world: World, project: dict, artefact_type: str, link_type_ids: list[str]):
    return world.client.put(
        f"/api/v1/projects/{project['id']}/artefact-link-rules/{artefact_type}", json={"link_type_ids": link_type_ids},
        headers=auth_headers(world.token),
    )


def _member_token(world: World, project: dict, role: str) -> str:
    """A user with only `role` on `project` (not an org admin)."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


def _set_lock(world: World, locks: list[str], token: str | None = None):
    return world.client.put(
        f"/api/v1/orgs/{world.org['id']}/project-customisation", json={"locks": locks},
        headers=auth_headers(token or world.token),
    )


def _db_type(type_id: str) -> RequirementLinkTypeDefinition | None:
    db = SessionLocal()
    try:
        return db.get(RequirementLinkTypeDefinition, uuid.UUID(type_id))
    finally:
        db.close()


def _link_type_ids_of(source_id: uuid.UUID) -> set[uuid.UUID]:
    db = SessionLocal()
    try:
        return set(db.scalars(select(ArtefactLink.link_type_id).where(ArtefactLink.source_id == source_id)).all())
    finally:
        db.close()


def _audit(entity_type: str, action: str | None = None) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        query = select(AuditEvent).where(AuditEvent.entity_type == entity_type)
        if action is not None:
            query = query.where(AuditEvent.action == action)
        return list(db.scalars(query).all())
    finally:
        db.close()


# --- scope: own, inherited, never sideways or upward ------------------------------------------


def test_project_sees_org_own_and_ancestors_types_but_never_siblings_or_descendants(world):
    parent, child, sibling, other = _tree(world)
    _local(world, parent, "Parent only")
    _local(world, child, "Child only")
    _local(world, sibling, "Sibling only")

    assert {"Related to", "Parent only"} <= set(_panel(world, parent)) and "Child only" not in _panel(world, parent)
    child_panel = _panel(world, child)
    assert {"Related to", "Parent only", "Child only"} <= set(child_panel) and "Sibling only" not in child_panel
    assert "Parent only" not in _panel(world, other)  # an unrelated root sees only the organisation's types

    assert child_panel["Related to"]["scope"] == "organization" and child_panel["Related to"]["editable"] is False
    assert child_panel["Parent only"]["scope"] == "inherited" and child_panel["Parent only"]["editable"] is False
    assert child_panel["Parent only"]["owner_project_name"] == "Parent"
    assert child_panel["Child only"]["scope"] == "project" and child_panel["Child only"]["editable"] is True


def test_inherited_owner_name_is_withheld_from_someone_who_cannot_see_the_parent(world):
    parent, child, _sibling, _other = _tree(world)
    _local(world, parent, "Parent only")
    viewer = _member_token(world, child, "member")  # member of the child only
    row = _panel(world, child, token=viewer)["Parent only"]
    assert row["scope"] == "inherited" and row["owner_project_name"] is None


def test_organisation_list_returns_organisation_wide_types_only(world):
    parent, _child, _sibling, _other = _tree(world)
    _local(world, parent, "Private to parent")
    member_email = f"m-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], member_email)
    member = login(world.client, member_email, "Password123!")
    rows = world.client.get(f"/api/v1/orgs/{world.org['id']}/link-types", headers=auth_headers(member)).json()
    assert "Private to parent" not in {r["forward_name"] for r in rows} and all(r["project_id"] is None for r in rows)


# --- using a type: isolation ---------------------------------------------------------------------


def test_a_local_type_is_usable_in_its_project_and_descendants_but_not_siblings_or_ancestors(world):
    parent, child, sibling, other = _tree(world)
    for project in (parent, child, sibling, other):
        _with_content(world, project)
    mine = _local(world, child, "Child verb")
    grand = create_project(world.client, world.token, world.org["id"], "Grandchild", parent_project_id=child["id"])
    _with_content(world, grand)

    def try_link(project: dict) -> int:
        a, b = world.requirement(project, "A"), world.requirement(project, "B")
        return world.generic_link(project, (REQ, a), mine["id"], (REQ, b)).status_code

    assert try_link(child) == 201 and try_link(grand) == 201
    assert try_link(parent) == 400 and try_link(sibling) == 400 and try_link(other) == 400


def test_the_requirement_link_endpoint_applies_the_same_check(world):
    parent, child, _sibling, _other = _tree(world)
    _with_content(world, parent)
    _with_content(world, child)
    mine = _local(world, child, "Child verb")
    a, b = world.requirement(parent, "A"), world.requirement(parent, "B")
    resp = world.client.post(
        f"/api/v1/projects/{parent['id']}/requirements/{a}/links",
        json={"target_requirement_id": str(b), "link_type_id": mine["id"]}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 400
    ca, cb = world.requirement(child, "CA"), world.requirement(child, "CB")
    ok = world.client.post(
        f"/api/v1/projects/{child['id']}/requirements/{ca}/links",
        json={"target_requirement_id": str(cb), "link_type_id": mine["id"]}, headers=auth_headers(world.token),
    )
    assert ok.status_code == 201, ok.text


def test_another_organisations_type_is_rejected_with_the_same_message(world, client, admin_token):
    project = _with_content(world, world.project("Mine"))
    foreign = World(client, admin_token, "Foreign Org")
    foreign_project = foreign.project("Theirs")
    theirs = _local(foreign, foreign_project, "Foreign local")
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    resp = world.generic_link(project, (REQ, a), theirs["id"], (REQ, b))
    sibling_resp = world.generic_link(project, (REQ, a), uuid.uuid4(), (REQ, b))
    assert resp.status_code == sibling_resp.status_code == 400
    assert resp.json()["detail"] == sibling_resp.json()["detail"]  # a probe learns nothing from the message


def test_validator_checks_usability_even_for_fixed_semantic_callers(world):
    parent, child, _sibling, _other = _tree(world)
    mine = _local(world, child, "Child verb")
    db = SessionLocal()
    try:
        row = db.get(RequirementLinkTypeDefinition, uuid.UUID(mine["id"]))
        with pytest.raises(LinkRuleError):
            validate_link_allowed(db, link_type=row, source_type=REQ, target_type=REQ, project_id=uuid.UUID(parent["id"]))
        validate_link_allowed(db, link_type=row, source_type=REQ, target_type=REQ, project_id=uuid.UUID(child["id"]))
    finally:
        db.close()


def test_org_admin_cannot_edit_rule_or_reassign_into_a_project_local_type(world):
    parent, _child, _sibling, _other = _tree(world)
    _with_content(world, parent)
    local = _local(world, parent, "Local verb")
    org_url = f"/api/v1/orgs/{world.org['id']}"
    admin = auth_headers(world.token)
    assert world.client.patch(
        f"{org_url}/link-types/{local['id']}", json={"forward_name": "x", "reverse_name": "y"}, headers=admin
    ).status_code == 404
    assert world.client.delete(f"{org_url}/link-types/{local['id']}", headers=admin).status_code == 404
    assert world.client.post(f"{org_url}/link-types/{local['id']}/move", json={"direction": "up"}, headers=admin).status_code == 404
    assert world.client.get(f"{org_url}/link-types/{local['id']}/usage", headers=admin).status_code == 404
    org_rule = world.client.put(f"{org_url}/artefact-link-rules/{REQ}", json={"link_type_ids": [local["id"]]}, headers=admin)
    assert org_rule.status_code == 422  # an organisation rule may name organisation-wide types only

    related = world.link_types_by_name()["Related to"]["id"]
    a, b = world.requirement(parent, "A"), world.requirement(parent, "B")
    assert world.generic_link(parent, (REQ, a), related, (REQ, b)).status_code == 201
    reassign = world.client.delete(
        f"{org_url}/link-types/{related}", params={"reassign_to_id": local["id"]}, headers=admin
    )
    assert reassign.status_code == 400  # would point other projects' links at a type they cannot use


def test_lazy_seed_ignores_a_same_named_local_type(world):
    project = world.project("P")
    local = _local(world, project, "Addresses")  # not provided by the org yet (seeded lazily)
    db = SessionLocal()
    try:
        created = ensure_org_link_type(db, uuid.UUID(world.org["id"]), "Addresses")
        db.commit()
        assert created.project_id is None and str(created.id) != local["id"]
    finally:
        db.close()


def test_phrases_still_show_for_a_link_whose_type_is_no_longer_usable(world):
    parent, child, _sibling, _other = _tree(world)
    _with_content(world, child)
    mine = _local(world, child, "Child verb", "Child reverse")
    a, b = world.requirement(child, "A"), world.requirement(child, "B")
    assert world.generic_link(child, (REQ, a), mine["id"], (REQ, b)).status_code == 201
    # Locking makes the type dormant (it cannot be used), yet the existing link still reads with its phrase.
    assert _set_lock(world, ["link_types"]).status_code == 200
    edges = world.graph(child, (REQ, a)).json()["edges"]
    assert [e["phrase"] for e in edges] == ["Child verb"]
    assert world.generic_link(child, (REQ, a), mine["id"], (REQ, world.requirement(child, "C"))).status_code == 400


# --- names ----------------------------------------------------------------------------------


def test_names_clash_up_front_with_the_organisation_and_ancestors_case_insensitively(world):
    parent, child, sibling, _other = _tree(world)
    assert _create_local(world, parent, "related TO").status_code == 400  # the organisation's "Related to"
    _local(world, parent, "Parent verb")
    clash = _create_local(world, child, "PARENT VERB")
    assert clash.status_code == 400 and "parent project" in clash.json()["detail"]
    assert _create_local(world, parent, "Parent verb").status_code == 400  # strict within one scope
    assert _create_local(world, sibling, "Shared name").status_code == 201
    assert _create_local(world, child, "Shared name").status_code == 201  # siblings may reuse a name


def test_a_parent_adding_a_name_a_child_has_shadows_the_childs_without_leaking_or_breaking_links(world):
    parent, child, _sibling, _other = _tree(world)
    _with_content(world, child)
    childs = _local(world, child, "Same name", "Child reverse")
    a, b = world.requirement(child, "A"), world.requirement(child, "B")
    assert world.generic_link(child, (REQ, a), childs["id"], (REQ, b)).status_code == 201

    parents = _local(world, parent, "same NAME", "Parent reverse")  # allowed: the parent cannot see the child's
    assert parents["scope"] == "project"
    panel = _panel(world, child)
    assert panel["Same name"]["shadowed_by_scope"] == "inherited" and panel["same NAME"]["shadowed_by_scope"] is None
    offered = _offered(world, child, (REQ, a))
    assert "same NAME" in offered and "Same name" not in offered  # only the winner is offered
    assert world.generic_link(child, (REQ, a), childs["id"], (REQ, world.requirement(child, "C"))).status_code == 400
    # The existing link still reads with the shadowed type's own phrase.
    assert [e["phrase"] for e in world.graph(child, (REQ, a)).json()["edges"]] == ["Same name"]
    # The parent's panel never reveals the child's type.
    assert "Same name" not in _panel(world, parent)


def test_rename_is_checked_the_same_way_and_never_touches_links(world):
    parent, child, _sibling, _other = _tree(world)
    _with_content(world, child)
    mine = _local(world, child, "Old name", "Old reverse")
    a, b = world.requirement(child, "A"), world.requirement(child, "B")
    assert world.generic_link(child, (REQ, a), mine["id"], (REQ, b)).status_code == 201
    assert _rename(world, child, mine["id"], "Related to", "x").status_code == 400
    ok = world.client.patch(
        _lt(child, f"/{mine['id']}"), json={"forward_name": "New name", "reverse_name": "New reverse", "flow": "forward_is_upstream"},
        headers=auth_headers(world.token),
    )
    assert ok.status_code == 200 and ok.json()["forward_name"] == "New name" and ok.json()["flow"] == "forward_is_upstream"
    assert [e["phrase"] for e in world.graph(child, (REQ, a)).json()["edges"]] == ["New name"]
    # Not editable from another project, nor an organisation type from here.
    assert _rename(world, parent, mine["id"]).status_code == 404
    related = world.link_types_by_name()["Related to"]["id"]
    assert _rename(world, child, related).status_code == 404


def test_restrictions_on_a_local_type_are_validated_and_enforced(world):
    project = _with_content(world, world.project("P"))
    assert _create_local(world, project, "Bad", allowed_source_types=["nope"]).status_code == 422
    narrow = _local(world, project, "Actions only", allowed_source_types=[ACTION], allowed_target_types=[ACTION])
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    resp = world.generic_link(project, (REQ, a), narrow["id"], (REQ, b))
    assert resp.status_code == 400 and "cannot start from" in resp.json()["detail"]


# --- hide / show -----------------------------------------------------------------------------------


def test_hiding_an_org_type_removes_it_from_pickers_but_not_from_existing_links(world):
    project = _with_content(world, world.project("P"))
    related = world.link_types_by_name()["Related to"]["id"]
    a, b, c = (world.requirement(project, n) for n in "ABC")
    assert world.generic_link(project, (REQ, a), related, (REQ, b)).status_code == 201

    hide = world.client.put(_lt(project, f"/{related}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    assert hide.status_code == 200 and hide.json()["hidden"] is True and hide.json()["hidden_here"] is True
    assert "Related to" not in _offered(world, project, (REQ, a))
    assert world.generic_link(project, (REQ, a), related, (REQ, c)).status_code == 400
    assert [e["phrase"] for e in world.graph(project, (REQ, a)).json()["edges"]] == ["Related to"]  # still reads

    clear = world.client.put(_lt(project, f"/{related}/visibility"), json={"hidden": None}, headers=auth_headers(world.token))
    assert clear.status_code == 200 and clear.json()["hidden"] is False and clear.json()["hidden_here"] is None
    assert "Related to" in _offered(world, project, (REQ, a))
    assert world.generic_link(project, (REQ, a), related, (REQ, c)).status_code == 201


def test_a_parents_hide_carries_down_and_a_child_can_show_it_again(world):
    parent, child, sibling, _other = _tree(world)
    related = world.link_types_by_name()["Related to"]["id"]
    assert world.client.put(_lt(parent, f"/{related}/visibility"), json={"hidden": True}, headers=auth_headers(world.token)).status_code == 200
    child_row = _panel(world, child)["Related to"]
    assert child_row["hidden"] is True and child_row["hidden_by_inherited"] is True and child_row["hidden_here"] is None
    assert world.client.put(_lt(child, f"/{related}/visibility"), json={"hidden": False}, headers=auth_headers(world.token)).status_code == 200
    assert _panel(world, child)["Related to"]["hidden"] is False
    assert _panel(world, sibling)["Related to"]["hidden"] is True  # the sibling still inherits the hide


def test_hiding_does_not_block_a_fixed_semantic_creator(world):
    project = world.project("P")
    related = world.link_types_by_name()["Related to"]["id"]
    world.client.put(_lt(project, f"/{related}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    db = SessionLocal()
    try:
        row = db.get(RequirementLinkTypeDefinition, uuid.UUID(related))
        project_id = uuid.UUID(project["id"])
        validate_link_allowed(db, link_type=row, source_type=REQ, target_type=REQ, project_id=project_id)  # fixed action
        with pytest.raises(LinkRuleError):
            validate_link_allowed(db, link_type=row, source_type=REQ, target_type=REQ, project_id=project_id, enforce_offered=True)
        assert_link_type_usable(db, db.get(Project, project_id), row)
    finally:
        db.close()


def test_hiding_something_unreachable_is_a_404(world):
    parent, child, _sibling, other = _tree(world)
    mine = _local(world, child, "Child verb")
    resp = world.client.put(_lt(parent, f"/{mine['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    assert resp.status_code == 404  # a descendant's type is not reachable from its parent
    resp = world.client.put(_lt(other, f"/{uuid.uuid4()}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    assert resp.status_code == 404


# --- artefact-type rules at project scope ----------------------------------------------------------


def test_project_rule_replaces_the_organisation_rule_and_nearest_wins(world):
    parent, child, sibling, _other = _tree(world)
    for project in (parent, child, sibling):
        _with_content(world, project)
    types = world.link_types_by_name()
    related, depends, implements = (types[n]["id"] for n in ("Related to", "Depends on", "Implements"))
    org_url = f"/api/v1/orgs/{world.org['id']}/artefact-link-rules/{REQ}"
    assert world.client.put(org_url, json={"link_type_ids": [related]}, headers=auth_headers(world.token)).status_code == 200

    def usable(project: dict) -> set[str]:
        a = world.requirement(project, f"A{uuid.uuid4().hex[:4]}")
        return _offered(world, project, (REQ, a)) & {"Related to", "Depends on", "Implements"}

    assert usable(sibling) == {"Related to"}
    # The parent's rule widens it entirely (replaces, not merges) ...
    put = world.client.put(
        f"/api/v1/projects/{parent['id']}/artefact-link-rules/{REQ}", json={"link_type_ids": [depends]},
        headers=auth_headers(world.token),
    )
    assert put.status_code == 200 and put.json()["source"] == "project" and put.json()["own"] is True
    assert usable(parent) == {"Depends on"} and usable(child) == {"Depends on"}
    # ... a child's own rule wins over the parent's ...
    world.client.put(
        f"/api/v1/projects/{child['id']}/artefact-link-rules/{REQ}", json={"link_type_ids": [implements]},
        headers=auth_headers(world.token),
    )
    assert usable(child) == {"Implements"}
    # ... and the org endpoint still reports only the organisation's rule.
    org_rules = {r["artefact_type"]: r["link_type_ids"] for r in world.client.get(
        f"/api/v1/orgs/{world.org['id']}/artefact-link-rules", headers=auth_headers(world.token)).json()}
    assert org_rules[REQ] == [related]

    rows = {r["artefact_type"]: r for r in world.client.get(
        f"/api/v1/projects/{sibling['id']}/artefact-link-rules", headers=auth_headers(world.token)).json()}
    assert rows[REQ]["source"] == "inherited" and rows[REQ]["own"] is False  # the sibling uses the parent's rule
    child_rows = {r["artefact_type"]: r for r in world.client.get(
        f"/api/v1/projects/{child['id']}/artefact-link-rules", headers=auth_headers(world.token)).json()}
    assert child_rows[REQ]["source"] == "project" and child_rows[REQ]["own"] is True

    cleared = world.client.delete(f"/api/v1/projects/{child['id']}/artefact-link-rules/{REQ}", headers=auth_headers(world.token))
    assert cleared.status_code == 204
    assert usable(child) == {"Depends on"}  # the parent's rule applies again


def test_a_project_rule_also_governs_the_legacy_typed_endpoints(client, admin_token):
    """The typed Decision -> Requirement endpoint keeps working but is checked against the project's rules."""
    world = World(client, admin_token, "Legacy Rules Org", decisions=True)
    project = world.project("Legacy")
    requirement = world.requirement(project, "R")
    decision = world.decision(project)
    related = world.link_types_by_name()["Related to"]["id"]
    url = f"/api/v1/projects/{project['id']}/modules/decisions/{decision}/requirement-links"
    body = {"requirement_id": str(requirement), "kind": "implements"}
    assert _put_rule(world, project, "decision", [related]).status_code == 200
    refused = client.post(url, json=body, headers=auth_headers(world.token))
    assert refused.status_code in (400, 409) and "limited to specific link types" in refused.json()["detail"]
    cleared = client.delete(f"/api/v1/projects/{project['id']}/artefact-link-rules/decision", headers=auth_headers(world.token))
    assert cleared.status_code == 204
    assert client.post(url, json=body, headers=auth_headers(world.token)).status_code == 201


def test_project_rule_validation(world):
    parent, child, _sibling, _other = _tree(world)
    mine = _local(world, child, "Child verb")
    base = f"/api/v1/projects/{parent['id']}/artefact-link-rules/{REQ}"
    related = world.link_types_by_name()["Related to"]["id"]
    assert world.client.put(base, json={"link_type_ids": [mine["id"]]}, headers=auth_headers(world.token)).status_code == 422
    assert world.client.put(base, json={"link_type_ids": []}, headers=auth_headers(world.token)).status_code == 422
    assert _put_rule(world, parent, "not_a_type", [related]).status_code == 422
    ok = world.client.put(
        f"/api/v1/projects/{child['id']}/artefact-link-rules/{REQ}", json={"link_type_ids": [mine["id"]]}, headers=auth_headers(world.token)
    )
    assert ok.status_code == 200  # a project rule may name a type usable in that project


# --- the organisation lock --------------------------------------------------------------------------


def test_lock_forbids_project_changes_makes_them_dormant_and_unlock_restores_them(world):
    project = _with_content(world, world.project("P"))
    related = world.link_types_by_name()["Related to"]["id"]
    mine = _local(world, project, "Local verb")
    world.client.put(_lt(project, f"/{related}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    a, b = world.requirement(project, "A"), world.requirement(project, "B")

    summary = world.client.get(f"/api/v1/orgs/{world.org['id']}/project-customisation", headers=auth_headers(world.token)).json()
    assert summary == {"locks": [], "local_link_type_count": 1, "local_link_type_project_count": 1}
    locked = _set_lock(world, ["link_types"])
    assert locked.status_code == 200 and locked.json()["locks"] == ["link_types"]

    panel = world.client.get(_lt(project), headers=auth_headers(world.token)).json()
    assert panel["locked"] is True and "Local verb" not in {r["forward_name"] for r in panel["items"]}
    assert all(r["scope"] == "organization" and not r["hidden"] for r in panel["items"])  # the hide is dormant too
    assert "Related to" in _offered(world, project, (REQ, a)) and "Local verb" not in _offered(world, project, (REQ, a))
    assert world.generic_link(project, (REQ, a), mine["id"], (REQ, b)).status_code == 400

    admin = auth_headers(world.token)
    assert _create_local(world, project, "Another").status_code == 403
    assert _rename(world, project, mine["id"], "x", "y").status_code == 403
    assert world.client.put(_lt(project, f"/{related}/visibility"), json={"hidden": False}, headers=admin).status_code == 403
    assert world.client.delete(_lt(project, f"/{mine['id']}"), headers=admin).status_code == 403
    assert _put_rule(world, project, REQ, [related]).status_code == 403
    assert "organisation uses one shared set" in _create_local(world, project, "Another").json()["detail"]

    assert _set_lock(world, []).status_code == 200
    panel = _panel(world, project)
    assert panel["Local verb"]["scope"] == "project" and panel["Related to"]["hidden"] is True  # nothing was deleted
    assert world.generic_link(project, (REQ, a), mine["id"], (REQ, b)).status_code == 201
    actions = [e.action for e in _audit("organization")]
    assert actions.count("project_customisation_locks_changed") == 2


def test_lock_validation_and_authorisation(world):
    assert _set_lock(world, ["nonsense"]).status_code == 422
    member_email = f"m-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], member_email)
    member = login(world.client, member_email, "Password123!")
    assert _set_lock(world, ["link_types"], token=member).status_code == 403
    # A member may read it, so a project admin can tell whether their controls are available.
    assert world.client.get(f"/api/v1/orgs/{world.org['id']}/project-customisation", headers=auth_headers(member)).status_code == 200


# --- authorisation ------------------------------------------------------------------------------------


def test_only_project_managers_may_change_and_non_members_may_not_read(world, client, admin_token):
    project = world.project("P")
    member = _member_token(world, project, "member")
    manager = _member_token(world, project, "project_manager")
    assert _create_local(world, project, "By member", token=member).status_code == 403
    assert client.get(_lt(project), headers=auth_headers(member)).status_code == 200  # members can read the panel
    created = _create_local(world, project, "By manager", token=manager)
    assert created.status_code == 201

    outsider = World(client, admin_token, "Outsider Org").token
    assert client.get(_lt(project), headers=auth_headers(outsider)).status_code == 403
    assert _create_local(world, project, "By outsider", token=outsider).status_code == 403
    related = world.link_types_by_name()["Related to"]["id"]
    assert client.put(_lt(project, f"/{related}/visibility"), json={"hidden": True}, headers=auth_headers(member)).status_code == 403


def test_every_change_is_audited_with_project_and_organisation(world):
    project = world.project("P")
    related = world.link_types_by_name()["Related to"]["id"]
    mine = _local(world, project, "Audited")
    _rename(world, project, mine["id"], "Audited 2", "r")
    world.client.put(_lt(project, f"/{related}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    _put_rule(world, project, REQ, [related])
    world.client.delete(_lt(project, f"/{mine['id']}"), headers=auth_headers(world.token))
    events = [e for e in _audit("requirement_link_type_definition") + _audit("artefact_type_link_rule") if e.project_id is not None]
    assert {e.action for e in events} >= {"created", "renamed", "hidden", "updated", "deleted"}
    assert all(str(e.project_id) == project["id"] and str(e.organization_id) == world.org["id"] for e in events)


# --- deleting a type other projects use -----------------------------------------------------------------


def _usage(world: World, project: dict, type_id: str, **params) -> dict:
    resp = world.client.get(_lt(project, f"/{type_id}/usage"), params=params, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _delete(world: World, project: dict, type_id: str, token: str | None = None, **params):
    return world.client.delete(_lt(project, f"/{type_id}"), params=params, headers=auth_headers(token or world.token))


def test_delete_unused_local_type_and_the_in_use_contract(world):
    project = _with_content(world, world.project("P"))
    unused = _local(world, project, "Unused")
    assert _delete(world, project, unused["id"]).status_code == 204 and _db_type(unused["id"]) is None

    used = _local(world, project, "Used", "Used reverse")
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    assert world.generic_link(project, (REQ, a), used["id"], (REQ, b)).status_code == 201
    assert _delete(world, project, used["id"]).status_code == 409  # unchanged contract: count, no mode
    usage = _usage(world, project, used["id"])
    assert usage["link_count"] == 1 and usage["is_last"] is False and usage["keep_available"] is False
    assert "Used" not in {c["forward_name"] for c in usage["candidates"]} and "Related to" in {c["forward_name"] for c in usage["candidates"]}

    related = world.link_types_by_name()["Related to"]["id"]
    moved = _delete(world, project, used["id"], mode="reassign", reassign_to_id=related)
    assert moved.status_code == 200 and moved.json()["moved"] == 1
    assert _link_type_ids_of(a) == {uuid.UUID(related)} and _db_type(used["id"]) is None


def test_local_type_cannot_be_reassigned_to_a_type_the_project_cannot_use(world):
    parent, child, _sibling, _other = _tree(world)
    _with_content(world, parent)
    mine = _local(world, parent, "Mine")
    others = _local(world, child, "Childs")  # not reachable from the parent
    a, b = world.requirement(parent, "A"), world.requirement(parent, "B")
    world.generic_link(parent, (REQ, a), mine["id"], (REQ, b))
    resp = _delete(world, parent, mine["id"], mode="reassign", reassign_to_id=others["id"])
    assert resp.status_code == 400


def _parent_child_with_links(world: World, count_children: int = 1):
    """A parent-owned local type with a link in the parent and in `count_children` children."""
    parent = create_project(world.client, world.token, world.org["id"], "Parent", can_be_parent=True)
    _with_content(world, parent)
    mine = _local(world, parent, "Shared verb", "Shared reverse", flow="forward_is_upstream")
    pa, pb = world.requirement(parent, "PA"), world.requirement(parent, "PB")
    assert world.generic_link(parent, (REQ, pa), mine["id"], (REQ, pb)).status_code == 201
    children = []
    for i in range(count_children):
        child = create_project(world.client, world.token, world.org["id"], f"Child {i}", parent_project_id=parent["id"], can_be_parent=True)
        _with_content(world, child)
        ca, cb = world.requirement(child, "CA"), world.requirement(child, "CB")
        assert world.generic_link(child, (REQ, ca), mine["id"], (REQ, cb)).status_code == 201
        children.append((child, ca))
    return parent, mine, (pa, pb), children


def test_keep_by_copy_leaves_the_type_with_the_children_and_removes_the_parents_links(world):
    parent, mine, (pa, _pb), [(child, ca)] = _parent_child_with_links(world)
    usage = _usage(world, parent, mine["id"], keep_in_projects=True)
    assert usage["link_count"] == 2 and usage["moved_link_count"] == 1
    assert usage["keep_available"] is True and usage["keep_project_count"] == 1

    assert _delete(world, parent, mine["id"], keep_in_projects=True).status_code == 409  # the parent's own link needs a mode
    resp = _delete(world, parent, mine["id"], mode="remove_links", keep_in_projects=True)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"moved": 0, "merged": 0, "removed": 1, "copies_created": 1, "copies_renamed": []}

    copy = _panel(world, child)["Shared verb"]
    assert copy["scope"] == "project" and copy["editable"] is True and copy["flow"] == "forward_is_upstream"
    assert copy["id"] != mine["id"] and _db_type(mine["id"]) is None
    assert [e["phrase"] for e in world.graph(child, (REQ, ca)).json()["edges"]] == ["Shared verb"]  # the child sees no change
    assert _link_type_ids_of(pa) == set()  # the parent's own link was removed
    created = [e for e in _audit("requirement_link_type_definition", "created") if str(e.project_id) == child["id"]]
    assert len(created) == 1 and created[0].detail["copied_from"] == mine["id"]  # audited in the child


def test_one_copy_per_branch_at_the_top_most_affected_project(world):
    parent, mine, _own, [(child, _ca)] = _parent_child_with_links(world)
    grandchild = create_project(world.client, world.token, world.org["id"], "Grandchild", parent_project_id=child["id"])
    _with_content(world, grandchild)
    ga, gb = world.requirement(grandchild, "GA"), world.requirement(grandchild, "GB")
    assert world.generic_link(grandchild, (REQ, ga), mine["id"], (REQ, gb)).status_code == 201
    sibling = create_project(world.client, world.token, world.org["id"], "Sibling", parent_project_id=parent["id"])
    _with_content(world, sibling)
    sa, sb = world.requirement(sibling, "SA"), world.requirement(sibling, "SB")
    assert world.generic_link(sibling, (REQ, sa), mine["id"], (REQ, sb)).status_code == 201

    resp = _delete(world, parent, mine["id"], mode="remove_links", keep_in_projects=True)
    assert resp.status_code == 200 and resp.json()["copies_created"] == 2  # child (covers grandchild) + sibling
    assert "Shared verb" in _panel(world, child) and _panel(world, child)["Shared verb"]["scope"] == "project"
    grand_row = _panel(world, grandchild)["Shared verb"]
    assert grand_row["scope"] == "inherited"  # inherits the child's copy, no second copy of its own
    assert _panel(world, sibling)["Shared verb"]["scope"] == "project"
    assert {e["phrase"] for e in world.graph(grandchild, (REQ, ga)).json()["edges"]} == {"Shared verb"}


def test_a_copy_whose_name_is_taken_is_renamed_never_merged(world):
    parent, mine, _own, [(child, _ca)] = _parent_child_with_links(world)
    # The parent's type is deleted while an organisation type of the same name appears (the copy would clash).
    org_dup = world.client.post(
        f"/api/v1/orgs/{world.org['id']}/link-types",
        json={"forward_name": "Shared verb", "reverse_name": "Org reverse"}, headers=auth_headers(world.token),
    )
    assert org_dup.status_code == 201  # allowed: shadows the parent's local one
    resp = _delete(world, parent, mine["id"], mode="remove_links", keep_in_projects=True)
    assert resp.status_code == 200 and resp.json()["copies_renamed"] == ["Shared verb (copy)"]
    row = _panel(world, child)["Shared verb (copy)"]
    assert row["scope"] == "project" and row["reverse_name"] == "Shared reverse"  # same meaning, own name


def test_a_child_you_cannot_manage_still_keeps_the_type_but_is_never_moved_or_removed(world):
    parent, mine, _own, [(child, ca)] = _parent_child_with_links(world)
    manager = _member_token(world, parent, "project_manager")  # manages the parent only
    blocked = _delete(world, parent, mine["id"], token=manager, mode="remove_links")
    assert blocked.status_code == 409
    assert "1 other project" in blocked.json()["detail"] and "Child" not in blocked.json()["detail"]  # count only, no names
    usage = _usage_as(world, parent, mine["id"], manager)
    assert usage["unmanageable_project_count"] == 1

    ok = _delete(world, parent, mine["id"], token=manager, mode="remove_links", keep_in_projects=True)
    assert ok.status_code == 200 and ok.json()["copies_created"] == 1
    assert [e["phrase"] for e in world.graph(child, (REQ, ca)).json()["edges"]] == ["Shared verb"]


def _usage_as(world: World, project: dict, type_id: str, token: str) -> dict:
    resp = world.client.get(_lt(project, f"/{type_id}/usage"), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_moving_links_in_a_child_requires_managing_that_child(world):
    parent, mine, _own, [(child, _ca)] = _parent_child_with_links(world)
    manager = _member_token(world, parent, "project_manager")
    related = world.link_types_by_name()["Related to"]["id"]
    blocked = _delete(world, parent, mine["id"], token=manager, mode="reassign", reassign_to_id=related)
    assert blocked.status_code == 409 and _db_type(mine["id"]) is not None  # nothing changed


def test_deleting_an_org_wide_type_can_keep_it_for_the_projects_using_it(world):
    project = _with_content(world, world.project("Using"))
    other = _with_content(world, world.project("Also using"))
    org_type = world.link_type("Org verb", "Org reverse", flow="forward_is_downstream")
    for p in (project, other):
        a, b = world.requirement(p, "A"), world.requirement(p, "B")
        assert world.generic_link(p, (REQ, a), org_type, (REQ, b)).status_code == 201
    org_url = f"/api/v1/orgs/{world.org['id']}/link-types/{org_type}"
    usage = world.client.get(org_url + "/usage", params={"keep_in_projects": True}, headers=auth_headers(world.token)).json()
    assert usage["keep_available"] is True and usage["keep_project_count"] == 2 and usage["moved_link_count"] == 0

    resp = world.client.delete(org_url, params={"keep_in_projects": True}, headers=auth_headers(world.token))
    assert resp.status_code == 200 and resp.json()["copies_created"] == 2
    for p in (project, other):
        copies = [r for r in _panel(world, p).values() if r["scope"] == "project"]
        assert len(copies) == 1 and copies[0]["flow"] == "forward_is_downstream"
    assert _db_type(str(org_type)) is None


def test_keep_by_copy_is_refused_under_the_lock_and_for_nothing_to_keep(world):
    project = _with_content(world, world.project("Using"))
    org_type = world.link_type("Org verb", "Org reverse")
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    world.generic_link(project, (REQ, a), org_type, (REQ, b))
    assert _set_lock(world, ["link_types"]).status_code == 200
    org_url = f"/api/v1/orgs/{world.org['id']}/link-types/{org_type}"
    usage = world.client.get(org_url + "/usage", headers=auth_headers(world.token)).json()
    assert usage["keep_available"] is False  # copies would be dormant
    resp = world.client.delete(org_url, params={"keep_in_projects": True, "mode": "remove_links"}, headers=auth_headers(world.token))
    assert resp.status_code == 409


def test_copy_carries_the_visibility_choices_so_children_see_what_they_saw(world):
    parent, mine, _own, [(child, _ca)] = _parent_child_with_links(world)
    assert world.client.put(_lt(child, f"/{mine['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token)).status_code == 200
    assert _delete(world, parent, mine["id"], mode="remove_links", keep_in_projects=True).status_code == 200
    assert _panel(world, child)["Shared verb"]["hidden"] is True


def _propose_add_link(world: World, project: dict, source: uuid.UUID, target: uuid.UUID, link_type_id: str):
    """Approves `source`, makes the project require change requests for links, and proposes an ADD_LINK."""
    headers = auth_headers(world.token)
    assert world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{source}/approve", headers=headers
    ).status_code == 200
    assert world.client.patch(
        f"/api/v1/projects/{project['id']}", json={"require_change_request_for_approved_links": True}, headers=headers
    ).status_code == 200
    return world.client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "add_link", "requirement_id": str(source), "proposed_link_target_requirement_id": str(target),
            "proposed_link_type_id": link_type_id, "reason": "traceability gap",
        },
        headers=headers,
    )


def test_change_request_cannot_propose_a_type_the_project_cannot_use(world):
    parent, child, _sibling, _other = _tree(world)
    _with_content(world, parent)
    mine = _local(world, child, "Child verb")
    a, b = world.requirement(parent, "A"), world.requirement(parent, "B")
    resp = _propose_add_link(world, parent, a, b, mine["id"])
    assert resp.status_code == 400


def test_pending_change_requests_in_a_kept_child_follow_the_copy(world):
    from app.models.change_request import ChangeRequestVersion

    parent, mine, _own, [(child, _ca)] = _parent_child_with_links(world)
    a, b = world.requirement(child, "A"), world.requirement(child, "B")
    cr = _propose_add_link(world, child, a, b, mine["id"])
    assert cr.status_code == 201, cr.text

    # Without keeping, a pending request proposing the type blocks removal ...
    assert _delete(world, parent, mine["id"], mode="remove_links").status_code == 409
    # ... but a kept child's request is repointed to the child's copy.
    assert _delete(world, parent, mine["id"], mode="remove_links", keep_in_projects=True).status_code == 200
    copy_id = _panel(world, child)["Shared verb"]["id"]
    db = SessionLocal()
    try:
        proposed = db.scalars(select(ChangeRequestVersion.proposed_link_type_id).where(
            ChangeRequestVersion.proposed_link_type_id.is_not(None))).all()
        assert proposed == [uuid.UUID(copy_id)]
    finally:
        db.close()


def test_deleting_the_organisation_removes_project_local_types_cleanly(world, client, admin_token):
    project = _with_content(world, world.project("P"))
    mine = _local(world, project, "Doomed")
    a, b = world.requirement(project, "A"), world.requirement(project, "B")
    assert world.generic_link(project, (REQ, a), mine["id"], (REQ, b)).status_code == 201
    resp = client.request(
        "DELETE", f"/api/v1/orgs/{world.org['id']}", json={"confirm_name": world.org["name"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    assert _db_type(mine["id"]) is None


def test_migration_0067_keeps_existing_types_organisation_wide_and_round_trips(world):
    """Existing link types gain `project_id` NULL (organisation-wide); downgrading drops
    project-local rows only and restores the organisation-wide uniqueness; upgrading again works."""
    from sqlalchemy import text

    from alembic import command
    from app.database import engine
    from tests.conftest import build_alembic_config

    project = world.project("P")
    _local(world, project, "Local only")
    org_types_before = set(world.link_types_by_name())
    command.downgrade(build_alembic_config(), "0066")
    try:
        with engine.connect() as conn:
            columns = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'requirement_link_type_definitions'"
            ))}
            names = {r[0] for r in conn.execute(text(
                "SELECT forward_name FROM requirement_link_type_definitions WHERE organization_id = :o"), {"o": world.org["id"]})}
        assert "project_id" not in columns
        assert names == org_types_before  # the local type is gone, the organisation's are untouched
    finally:
        command.upgrade(build_alembic_config(), "head")
    with engine.connect() as conn:
        scopes = {r[0] for r in conn.execute(text(
            "SELECT project_id FROM requirement_link_type_definitions WHERE organization_id = :o"), {"o": world.org["id"]})}
        locks = conn.execute(text("SELECT project_customisation_locks FROM organizations WHERE id = :o"), {"o": world.org["id"]}).scalar()
    assert scopes == {None} and locks == []
