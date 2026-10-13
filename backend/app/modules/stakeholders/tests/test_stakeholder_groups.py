"""Tests for Stakeholder Groups (Module 2 Phase 3c, docs/plans/module-02-
stakeholders-and-personas-plan.md Phase 0 addendum 3).

Covers: the tree (create/rename/move, sibling names, cycle and depth guards),
scope rules (org vs project groups and members, cross-org isolation), transitive
membership and the list filters, `exclusive_children`, delete with child
promotion, hidden stakeholders (Phase 3b), the free-text proposals action,
stakeholder erasure, audit logging without personal data, RBAC, and bundle
round-tripping.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.stakeholders.groups import MAX_GROUP_DEPTH
from app.modules.stakeholders.models import StakeholderGroup, StakeholderGroupMember
from app.modules.stakeholders.tests.test_persona_api import (
    _add_member,
    _grant_project_role,
    _org_base,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from tests.conftest import auth_headers


def _post_group(client, token, base, name, parent=None, **extra):
    return client.post(
        base + "/stakeholder-groups", json={"name": name, "parent_group_id": parent, **extra}, headers=auth_headers(token)
    )


def _group(client, token, base, name, parent=None, **extra) -> dict:
    resp = _post_group(client, token, base, name, parent, **extra)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add(client, token, base, group_id, stakeholder_id):
    return client.post(
        f"{base}/stakeholder-groups/{group_id}/members", json={"stakeholder_id": stakeholder_id},
        headers=auth_headers(token),
    )


def _names(client, token, url) -> list[str]:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [s["name"] for s in resp.json()]


# --- Tree ------------------------------------------------------------------------------------


def test_group_tree_create_rename_move_and_sibling_names(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Tree Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    clients = _group(client, token, base, "Client", exclusive_children=True)
    acme = _group(client, token, base, "Acme", clients["id"])
    assert acme["parent_group_id"] == clients["id"] and acme["scope"] == "organization"
    assert _post_group(client, token, base, "acme", clients["id"]).status_code == 409  # case-insensitive sibling clash
    assert _post_group(client, token, base, "Acme").status_code == 201  # same name at another level is fine
    assert _post_group(client, token, base, "  ").status_code in (400, 422)
    assert _post_group(client, token, base, "Orphan", str(uuid.uuid4())).status_code == 400

    renamed = client.patch(f"{base}/stakeholder-groups/{acme['id']}", json={"name": "Acme Ltd"}, headers=h)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Acme Ltd"
    top = client.patch(f"{base}/stakeholder-groups/{acme['id']}", json={"parent_group_id": None}, headers=h)
    assert top.status_code == 200 and top.json()["parent_group_id"] is None
    listed = client.get(base + "/stakeholder-groups", headers=h).json()
    assert {g["name"]: g["child_count"] for g in listed}["Client"] == 0


def test_cycles_and_depth_are_rejected(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Cycle Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    a = _group(client, token, base, "A")
    b = _group(client, token, base, "B", a["id"])
    c = _group(client, token, base, "C", b["id"])
    for target in (a["id"], b["id"], c["id"]):  # under itself or its own descendants
        resp = client.patch(f"{base}/stakeholder-groups/{a['id']}", json={"parent_group_id": target}, headers=h)
        assert resp.status_code == 409, resp.text
    tail = c
    for i in range(MAX_GROUP_DEPTH - 3):
        tail = _group(client, token, base, f"Level {i}", tail["id"])
    assert _post_group(client, token, base, "Too deep", tail["id"]).status_code == 400


def test_reorder_among_siblings(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Order Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    first, second = _group(client, token, base, "First"), _group(client, token, base, "Second")
    moved = client.post(f"{base}/stakeholder-groups/{second['id']}/move", json={"direction": "up"}, headers=h)
    assert moved.status_code == 200
    assert [g["name"] for g in client.get(base + "/stakeholder-groups", headers=h).json()] == ["Second", "First"]
    assert first["sort_order"] < second["sort_order"]


# --- Scope rules -----------------------------------------------------------------------------


def test_org_groups_hold_only_org_stakeholders_and_project_groups_may_nest_under_org_groups(client, admin_token):
    org, project, token = _setup(client, admin_token, "Groups Scope Co")
    ob, pb = _org_base(org["id"]), _project_base(project["id"])
    shared = _create_org_stakeholder(client, token, org["id"], name="Shared Sam")
    own = _create_project_stakeholder(client, token, project["id"], name="Own Olly")
    org_group = _group(client, token, ob, "Client")
    proj_group = _group(client, token, pb, "Acme — Finance", org_group["id"])
    assert proj_group["scope"] == "project" and proj_group["project_id"] == project["id"]

    assert _add(client, token, ob, org_group["id"], shared["id"]).status_code == 204
    assert _add(client, token, pb, proj_group["id"], shared["id"]).status_code == 204  # org stakeholder in a project group
    assert _add(client, token, pb, proj_group["id"], own["id"]).status_code == 204
    # An org group never holds a project stakeholder, and the project router cannot edit an org group.
    assert _add(client, token, ob, org_group["id"], own["id"]).status_code == 404
    assert _add(client, token, pb, org_group["id"], shared["id"]).status_code == 404
    assert client.patch(f"{pb}/stakeholder-groups/{org_group['id']}", json={"name": "x"}, headers=auth_headers(token)).status_code == 404
    # An org group cannot be placed under a project group.
    moved = client.patch(f"{ob}/stakeholder-groups/{org_group['id']}", json={"parent_group_id": proj_group["id"]}, headers=auth_headers(token))
    assert moved.status_code == 400

    # Project groups are invisible to the org view; both tiers show in the project view.
    assert [g["name"] for g in client.get(ob + "/stakeholder-groups", headers=auth_headers(token)).json()] == ["Client"]
    assert {g["name"] for g in client.get(pb + "/stakeholder-groups", headers=auth_headers(token)).json()} == {"Client", "Acme — Finance"}
    org_view = {s["name"]: s for s in client.get(ob + "/stakeholders", headers=auth_headers(token)).json()}
    assert [g["name"] for g in org_view["Shared Sam"]["groups"]] == ["Client"]  # not the project group
    proj_view = {s["name"]: s for s in client.get(pb + "/stakeholders", headers=auth_headers(token)).json()}
    assert {g["name"] for g in proj_view["Shared Sam"]["groups"]} == {"Client", "Acme — Finance"}


def test_other_organisations_and_projects_cannot_reach_a_group(client, admin_token):
    org, project, token = _setup(client, admin_token, "Groups Tenancy Co")
    other_org, other_project, other_token = _setup(client, admin_token, "Groups Tenancy Other Co")
    group = _group(client, token, _org_base(org["id"]), "Private")
    pgroup = _group(client, token, _project_base(project["id"]), "Private Project")
    foreign = _create_org_stakeholder(client, other_token, other_org["id"])
    for resp in (
        client.patch(f"{_org_base(other_org['id'])}/stakeholder-groups/{group['id']}", json={"name": "x"}, headers=auth_headers(other_token)),
        client.delete(f"{_org_base(other_org['id'])}/stakeholder-groups/{group['id']}", headers=auth_headers(other_token)),
        client.get(f"{_org_base(other_org['id'])}/stakeholder-groups/{group['id']}/members", headers=auth_headers(other_token)),
        client.patch(
            f"{_project_base(other_project['id'])}/stakeholder-groups/{pgroup['id']}", json={"name": "x"},
            headers=auth_headers(other_token),
        ),
        _add(client, other_token, _org_base(other_org["id"]), group["id"], foreign["id"]),
    ):
        assert resp.status_code == 404, resp.text
    # A parent from another organisation is rejected.
    assert _post_group(client, other_token, _org_base(other_org["id"]), "Child", group["id"]).status_code == 400
    assert _post_group(client, other_token, _project_base(other_project["id"]), "Child", pgroup["id"]).status_code == 400
    # Another project's groups never show up.
    sibling = _group(client, other_token, _project_base(other_project["id"]), "Sibling Only")
    visible = client.get(_project_base(project["id"]) + "/stakeholder-groups", headers=auth_headers(token)).json()
    assert sibling["id"] not in {g["id"] for g in visible}


# --- Membership ------------------------------------------------------------------------------


def test_membership_is_transitive_and_filters_the_stakeholder_list(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Filter Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    clients = _group(client, token, base, "Client")
    acme = _group(client, token, base, "Acme", clients["id"])
    finance = _group(client, token, base, "Acme — Finance", acme["id"])
    ops = _group(client, token, base, "Operations")
    fin_person = _create_org_stakeholder(client, token, org["id"], name="Fran Finance")
    acme_person = _create_org_stakeholder(client, token, org["id"], name="Alex Acme")
    both = _create_org_stakeholder(client, token, org["id"], name="Bo Both")
    _create_org_stakeholder(client, token, org["id"], name="Nobody")
    _add(client, token, base, finance["id"], fin_person["id"])
    _add(client, token, base, acme["id"], acme_person["id"])
    _add(client, token, base, finance["id"], both["id"])
    _add(client, token, base, ops["id"], both["id"])
    assert _add(client, token, base, ops["id"], both["id"]).status_code == 409  # already in

    url = base + "/stakeholders"
    assert set(_names(client, token, f"{url}?group_id={clients['id']}")) == {"Fran Finance", "Alex Acme", "Bo Both"}
    assert set(_names(client, token, f"{url}?group_id={acme['id']}")) == {"Fran Finance", "Alex Acme", "Bo Both"}
    assert _names(client, token, f"{url}?group_id={acme['id']}&direct_only=true") == ["Alex Acme"]
    assert set(_names(client, token, f"{url}?group_id={ops['id']}")) == {"Bo Both"}
    assert client.get(f"{url}?group_id={uuid.uuid4()}", headers=h).status_code == 404

    members = client.get(f"{base}/stakeholder-groups/{acme['id']}/members", headers=h).json()
    assert {(m["name"], m["direct"]) for m in members} == {("Alex Acme", True), ("Fran Finance", False), ("Bo Both", False)}
    assert [m["name"] for m in client.get(f"{base}/stakeholder-groups/{acme['id']}/members?direct_only=true", headers=h).json()] == ["Alex Acme"]

    listed = {s["name"]: s for s in client.get(url, headers=h).json()}
    assert {g["name"] for g in listed["Bo Both"]["groups"]} == {"Acme — Finance", "Operations"}
    assert listed["Nobody"]["groups"] == []

    removed = client.delete(f"{base}/stakeholder-groups/{ops['id']}/members/{both['id']}", headers=h)
    assert removed.status_code == 204
    assert client.delete(f"{base}/stakeholder-groups/{ops['id']}/members/{both['id']}", headers=h).status_code == 404
    assert _names(client, token, f"{url}?group_id={ops['id']}") == []


def test_set_stakeholder_groups_replaces_only_this_tier(client, admin_token):
    org, project, token = _setup(client, admin_token, "Groups Set Co")
    ob, pb, h = _org_base(org["id"]), _project_base(project["id"]), auth_headers(token)
    shared = _create_org_stakeholder(client, token, org["id"])
    og1, og2 = _group(client, token, ob, "Org One"), _group(client, token, ob, "Org Two")
    pg = _group(client, token, pb, "Project One")
    url = f"{ob}/stakeholders/{shared['id']}/groups"
    assert client.put(url, json={"group_ids": [og1["id"], og2["id"]]}, headers=h).status_code == 200
    resp = client.put(f"{pb}/stakeholders/{shared['id']}/groups", json={"group_ids": [pg["id"]]}, headers=h)
    assert {g["name"] for g in resp.json()} == {"Org One", "Org Two", "Project One"}  # org memberships untouched
    resp = client.put(url, json={"group_ids": [og2["id"]]}, headers=h)
    assert [g["name"] for g in resp.json()] == ["Org Two"]
    assert client.put(url, json={"group_ids": [pg["id"]]}, headers=h).status_code == 400  # wrong tier
    assert client.put(url, json={"group_ids": []}, headers=h).json() == []
    assert [g["name"] for g in client.get(f"{pb}/stakeholders/{shared['id']}/groups", headers=h).json()] == ["Project One"]


# --- exclusive_children ----------------------------------------------------------------------


def test_exclusive_children_allows_one_branch_per_stakeholder(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Exclusive Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    clients = _group(client, token, base, "Client", exclusive_children=True)
    acme = _group(client, token, base, "Acme", clients["id"])
    acme_fin = _group(client, token, base, "Acme — Finance", acme["id"])
    beta = _group(client, token, base, "Beta", clients["id"])
    person = _create_org_stakeholder(client, token, org["id"])
    assert _add(client, token, base, acme_fin["id"], person["id"]).status_code == 204
    assert _add(client, token, base, acme["id"], person["id"]).status_code == 204  # same branch is fine
    blocked = _add(client, token, base, beta["id"], person["id"])
    assert blocked.status_code == 409 and "Acme" in blocked.json()["detail"]
    # The group set endpoint is atomic: one conflict changes nothing.
    other = _create_org_stakeholder(client, token, org["id"], name="Other")
    resp = client.put(f"{base}/stakeholders/{other['id']}/groups", json={"group_ids": [acme["id"], beta["id"]]}, headers=h)
    assert resp.status_code == 409
    assert client.get(f"{base}/stakeholders/{other['id']}/groups", headers=h).json() == []


def test_marking_a_group_exclusive_or_moving_into_one_checks_existing_members(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Exclusive Retro Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    parent = _group(client, token, base, "Region")
    north, south = _group(client, token, base, "North", parent["id"]), _group(client, token, base, "South", parent["id"])
    person = _create_org_stakeholder(client, token, org["id"])
    _add(client, token, base, north["id"], person["id"])
    _add(client, token, base, south["id"], person["id"])
    resp = client.patch(f"{base}/stakeholder-groups/{parent['id']}", json={"exclusive_children": True}, headers=h)
    assert resp.status_code == 409
    assert client.get(base + "/stakeholder-groups", headers=h).json()[0]["exclusive_children"] is False

    strict = _group(client, token, base, "Strict", exclusive_children=True)
    assert client.patch(f"{base}/stakeholder-groups/{north['id']}", json={"parent_group_id": strict["id"]}, headers=h).status_code == 200
    resp = client.patch(f"{base}/stakeholder-groups/{south['id']}", json={"parent_group_id": strict["id"]}, headers=h)
    assert resp.status_code == 409  # the person would now sit in two Strict branches


# --- Delete ----------------------------------------------------------------------------------


def test_delete_promotes_children_and_removes_memberships_but_not_stakeholders(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Delete Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    root = _group(client, token, base, "Root")
    mid = _group(client, token, base, "Mid", root["id"])
    leaf = _group(client, token, base, "Leaf", mid["id"])
    person = _create_org_stakeholder(client, token, org["id"], name="Stays")
    _add(client, token, base, mid["id"], person["id"])
    listed = {g["name"]: g for g in client.get(base + "/stakeholder-groups", headers=h).json()}
    assert listed["Mid"]["member_count"] == 1 and listed["Mid"]["child_count"] == 1

    assert client.delete(f"{base}/stakeholder-groups/{mid['id']}", headers=h).status_code == 204
    after = {g["name"]: g for g in client.get(base + "/stakeholder-groups", headers=h).json()}
    assert "Mid" not in after and after["Leaf"]["parent_group_id"] == root["id"] and leaf["id"] == after["Leaf"]["id"]
    assert _names(client, token, base + "/stakeholders") == ["Stays"]
    assert client.get(f"{base}/stakeholders/{person['id']}/groups", headers=h).json() == []
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StakeholderGroupMember).where(
            StakeholderGroupMember.group_id == uuid.UUID(mid["id"]))) == 0


def test_delete_refuses_a_promotion_that_clashes_with_a_sibling_name(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Delete Clash Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    root = _group(client, token, base, "Root")
    mid = _group(client, token, base, "Mid", root["id"])
    _group(client, token, base, "Twin", mid["id"])
    _group(client, token, base, "Twin", root["id"])
    resp = client.delete(f"{base}/stakeholder-groups/{mid['id']}", headers=h)
    assert resp.status_code == 409 and "Twin" in resp.json()["detail"]
    assert any(g["name"] == "Mid" for g in client.get(base + "/stakeholder-groups", headers=h).json())


def test_deleting_an_org_group_promotes_a_projects_child_group(client, admin_token):
    org, project, token = _setup(client, admin_token, "Groups Delete Cross Co")
    ob, pb, h = _org_base(org["id"]), _project_base(project["id"]), auth_headers(token)
    top = _group(client, token, ob, "Top")
    mid = _group(client, token, ob, "Mid", top["id"])
    child = _group(client, token, pb, "Project child", mid["id"])
    assert client.delete(f"{ob}/stakeholder-groups/{mid['id']}", headers=h).status_code == 204
    shown = {g["name"]: g for g in client.get(pb + "/stakeholder-groups", headers=h).json()}
    assert shown["Project child"]["parent_group_id"] == top["id"] and shown["Project child"]["id"] == child["id"]


# --- Phase 3b hidden stakeholders, erasure ---------------------------------------------------


def test_hidden_stakeholder_is_left_out_of_a_projects_view_of_a_group(client, admin_token):
    org, project, token = _setup(client, admin_token, "Groups Hidden Co")
    ob, pb, h = _org_base(org["id"]), _project_base(project["id"]), auth_headers(token)
    group = _group(client, token, ob, "Clients")
    shown = _create_org_stakeholder(client, token, org["id"], name="Shown")
    hidden = _create_org_stakeholder(client, token, org["id"], name="Hidden")
    _add(client, token, ob, group["id"], shown["id"])
    _add(client, token, ob, group["id"], hidden["id"])
    client.put(f"{pb}/stakeholders/{hidden['id']}/visibility", json={"hidden": True}, headers=h)

    assert [m["name"] for m in client.get(f"{pb}/stakeholder-groups/{group['id']}/members", headers=h).json()] == ["Shown"]
    assert len(client.get(f"{ob}/stakeholder-groups/{group['id']}/members", headers=h).json()) == 2
    assert {g["name"]: g["member_count"] for g in client.get(pb + "/stakeholder-groups", headers=h).json()}["Clients"] == 1
    assert _names(client, token, f"{pb}/stakeholders?group_id={group['id']}") == ["Shown"]
    project_group = _group(client, token, pb, "Local")
    assert _add(client, token, pb, project_group["id"], hidden["id"]).status_code == 404
    assert client.put(f"{pb}/stakeholders/{hidden['id']}/groups", json={"group_ids": []}, headers=h).status_code == 404


def test_erasing_a_stakeholder_removes_its_memberships_and_not_the_group(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Erase Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    group = _group(client, token, base, "Keep me")
    person = _create_org_stakeholder(client, token, org["id"])
    _add(client, token, base, group["id"], person["id"])
    assert client.delete(f"{base}/stakeholders/{person['id']}", headers=h).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StakeholderGroupMember).where(
            StakeholderGroupMember.stakeholder_id == uuid.UUID(person["id"]))) == 0
        assert db.get(StakeholderGroup, uuid.UUID(group["id"])) is not None


# --- From text, sorting ----------------------------------------------------------------------


def test_create_groups_from_free_text_and_group_by_a_root(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Text Co")
    base, h = _org_base(org["id"]), auth_headers(token)
    a1 = _create_org_stakeholder(client, token, org["id"], name="Ann", organisation_group="Acme")
    a2 = _create_org_stakeholder(client, token, org["id"], name="Al", organisation_group=" acme ")
    b1 = _create_org_stakeholder(client, token, org["id"], name="Bea", organisation_group="Beta")
    _create_org_stakeholder(client, token, org["id"], name="None", organisation_group="")
    proposals = client.get(base + "/stakeholder-groups/text-proposals", headers=h).json()
    assert [(p["name"], p["stakeholder_count"]) for p in proposals] == [("Acme", 2), ("Beta", 1)]

    assert client.post(base + "/stakeholder-groups/from-text", json={"names": ["Nope"]}, headers=h).status_code == 400
    resp = client.post(base + "/stakeholder-groups/from-text", json={"names": ["Acme", "Beta"]}, headers=h)
    assert resp.status_code == 201, resp.text
    assert resp.json()["memberships_added"] == 3 and len(resp.json()["group_ids"]) == 2
    root = next(g for g in client.get(base + "/stakeholder-groups", headers=h).json() if g["parent_group_id"] is None)
    assert root["name"] == "Organisation / group" and root["exclusive_children"] is True
    again = client.post(base + "/stakeholder-groups/from-text", json={"names": ["Acme"]}, headers=h)
    assert again.status_code == 201 and again.json()["memberships_added"] == 0  # idempotent
    after = {p["name"]: p["existing_group_id"] for p in client.get(base + "/stakeholder-groups/text-proposals", headers=h).json()}
    assert all(after.values())
    assert a1 and a2 and b1  # created above

    ordered = _names(client, token, f"{base}/stakeholders?group_by={root['id']}")
    assert ordered.index("Bea") > max(ordered.index("Ann"), ordered.index("Al")) and ordered[-1] == "None"
    leaf = next(g for g in client.get(base + "/stakeholder-groups", headers=h).json() if g["parent_group_id"])
    assert client.get(f"{base}/stakeholders?group_by={leaf['id']}", headers=h).status_code == 400  # not a top-level group


# --- RBAC, audit, bundles --------------------------------------------------------------------


def test_writes_need_the_stakeholder_manage_permission_but_viewing_does_not(client, admin_token):
    org, project, token = _setup(client, admin_token, "Groups Rbac Co")
    pb = _project_base(project["id"])
    group = _group(client, token, pb, "Existing")
    person = _create_project_stakeholder(client, token, project["id"])
    user_id, member = _add_member(client, token, org["id"], project["id"], "member@groups-rbac.example.com")
    assert [g["name"] for g in client.get(pb + "/stakeholder-groups", headers=auth_headers(member)).json()] == ["Existing"]
    assert _post_group(client, member, pb, "Nope").status_code == 403
    assert client.patch(f"{pb}/stakeholder-groups/{group['id']}", json={"name": "x"}, headers=auth_headers(member)).status_code == 403
    assert client.delete(f"{pb}/stakeholder-groups/{group['id']}", headers=auth_headers(member)).status_code == 403
    assert _add(client, member, pb, group["id"], person["id"]).status_code == 403
    assert client.put(f"{pb}/stakeholders/{person['id']}/groups", json={"group_ids": []}, headers=auth_headers(member)).status_code == 403
    assert client.post(pb + "/stakeholder-groups/from-text", json={"names": ["x"]}, headers=auth_headers(member)).status_code == 403
    assert _post_group(client, member, _org_base(org["id"]), "Nope").status_code == 403

    _grant_project_role(client, token, project["id"], user_id, "stakeholder_owner")
    assert _post_group(client, member, pb, "Now allowed").status_code == 201
    assert _post_group(client, member, _org_base(org["id"]), "Org still no").status_code == 403  # a project role is not an org one


def test_module_disabled_is_404(client, admin_token):
    from tests.conftest import create_org_admin_in, create_project

    org, token = create_org_admin_in(client, admin_token, "Groups Gate Co")
    project = create_project(client, token, org["id"], "Groups Gate Project")
    assert client.get(_project_base(project["id"]) + "/stakeholder-groups", headers=auth_headers(token)).status_code == 404


def test_group_changes_are_audit_logged_with_ids_only(client, admin_token):
    org, _, token = _setup(client, admin_token, "Groups Audit Co")
    base = _org_base(org["id"])
    group = _group(client, token, base, "Secret Client Name")
    person = _create_org_stakeholder(client, token, org["id"], name="Audited Person")
    _add(client, token, base, group["id"], person["id"])
    client.patch(f"{base}/stakeholder-groups/{group['id']}", json={"description": "d"}, headers=auth_headers(token))
    client.delete(f"{base}/stakeholder-groups/{group['id']}", headers=auth_headers(token))
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == group["id"]).order_by(AuditEvent.created_at)).all()
    assert [e.action for e in events] == ["created", "member_added", "updated", "deleted"]
    text = " ".join(str(e.detail) for e in events).lower()
    assert "secret client" not in text and "audited person" not in text


def test_org_bundle_round_trips_groups_and_memberships(client, admin_token):
    org, project, token = _setup(client, admin_token, "Groups Bundle Co")
    ob, pb, h = _org_base(org["id"]), _project_base(project["id"]), auth_headers(token)
    clients = _group(client, token, ob, "Client", exclusive_children=True)
    acme = _group(client, token, ob, "Acme", clients["id"])
    person = _create_org_stakeholder(client, token, org["id"], name="Org Person")
    own = _create_project_stakeholder(client, token, project["id"], name="Project Person")
    _add(client, token, ob, acme["id"], person["id"])
    local = _group(client, token, pb, "Acme — Finance", acme["id"])
    _add(client, token, pb, local["id"], person["id"])
    _add(client, token, pb, local["id"], own["id"])

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))
    assert [e["path"][-1]["name"] for e in org_json["stakeholder_groups"]] == ["Client", "Acme"]
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Groups Bundle Org Reimport"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["warnings"] == []
    new_org = imported.json()["organization"]["id"]
    with SessionLocal() as db:
        rows = db.scalars(select(StakeholderGroup).where(StakeholderGroup.organization_id == uuid.UUID(new_org))).all()
        groups = {g.name: g for g in rows}
        assert groups["Acme"].parent_group_id == groups["Client"].id and groups["Client"].exclusive_children is True
        assert db.scalar(select(func.count()).select_from(StakeholderGroupMember).where(
            StakeholderGroupMember.group_id == groups["Acme"].id)) == 1

    pexport = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    exported = json.loads(zipfile.ZipFile(io.BytesIO(pexport.content)).read("project.json"))
    entry = exported["project_stakeholder_groups"][0]
    assert [(p["name"], p["scope"]) for p in entry["path"]] == [("Client", "organization"), ("Acme", "organization"), ("Acme — Finance", "project")]
    reimported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Groups Bundle Reimported"},
        files={"file": ("bundle.zip", pexport.content, "application/zip")}, headers=h,
    )
    assert reimported.status_code == 201, reimported.text
    assert reimported.json()["warnings"] == []
    new_project = reimported.json()["project"]["id"]
    mine = [g for g in client.get(f"{_project_base(new_project)}/stakeholder-groups", headers=h).json() if g["scope"] == "project"]
    assert [(g["name"], g["member_count"]) for g in mine] == [("Acme — Finance", 2)]

    # A target organisation without the org parent group skips it with a warning rather than failing.
    other, _, other_token = _setup(client, admin_token, "Groups Bundle Target Co")
    foreign = client.post(
        "/api/v1/projects/import", data={"organization_id": other["id"], "name": "Groups Foreign"},
        files={"file": ("bundle.zip", pexport.content, "application/zip")}, headers=auth_headers(other_token),
    )
    assert foreign.status_code == 201, foreign.text
    assert any("parent group not found" in w for w in foreign.json()["warnings"])


def test_an_org_group_does_not_reveal_other_projects_child_groups(client, admin_token):
    org, project, token = _setup(client, admin_token, "Groups Leak Co")
    ob, pb, h = _org_base(org["id"]), _project_base(project["id"]), auth_headers(token)
    top = _group(client, token, ob, "Top")
    mid = _group(client, token, ob, "Mid", top["id"])
    _group(client, token, pb, "Secret Project Child", mid["id"])
    # Counts are of the groups the viewer can see: the org view has no child under Mid, the project view has one.
    assert {g["name"]: g["child_count"] for g in client.get(ob + "/stakeholder-groups", headers=h).json()}["Mid"] == 0
    assert {g["name"]: g["child_count"] for g in client.get(pb + "/stakeholder-groups", headers=h).json()}["Mid"] == 1
    # A promotion clash with a project's group is reported without naming it.
    _group(client, token, pb, "Secret Project Child", top["id"])
    resp = client.delete(f"{ob}/stakeholder-groups/{mid['id']}", headers=h)
    assert resp.status_code == 409 and "Secret Project Child" not in resp.json()["detail"]
    assert "a project group" in resp.json()["detail"]


def test_a_stakeholder_group_manage_grant_alone_allows_group_writes(client, admin_token):
    """The registered `(stakeholder_group, manage)` atom is honoured, and does not confer Stakeholder management."""
    from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
    from app.services.permissions import encode_permission

    org, project, token = _setup(client, admin_token, "Groups Fgac Co")
    user_id, member = _add_member(client, token, org["id"], project["id"], "fgac@groups.example.com")
    assert _post_group(client, member, _org_base(org["id"]), "Before").status_code == 403
    with SessionLocal() as db:
        role = CustomRoleDefinition(
            organization_id=uuid.UUID(org["id"]), name="Group editors", description="Test role.", scope="org",
        )
        db.add(role)
        db.flush()
        db.add(CustomRolePermission(custom_role_id=role.id, permission=encode_permission("stakeholder_group", "manage")))
        db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=uuid.UUID(org["id"])))
        db.commit()
    assert _post_group(client, member, _org_base(org["id"]), "After").status_code == 201
    stakeholder = client.post(
        _org_base(org["id"]) + "/stakeholders", json={"name": "Nope"}, headers=auth_headers(member)
    )
    assert stakeholder.status_code == 403
