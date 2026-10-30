"""Tests for report layouts at the organisation and project tiers: the two manage permissions, the
endpoints (`routers.report_layouts`), the additive project view with hide and restore
(`services.report_layout_scope`) and the project and organisation bundles
(`services.report_layout_bundle`). Each test builds its own organisation.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, GroupCustomRoleGrant, UserCustomRoleGrant
from app.models.definition_suppression import ProjectDefinitionSuppression
from app.services.permissions import ADMINISTRATIVE_PERMISSIONS
from app.services.rbac import MANAGE_ORG_REPORT_LAYOUTS, MANAGE_PROJECT_REPORT_LAYOUTS, get_effective_permissions
from app.services.report_layout_tree import empty_tree
from tests.conftest import auth_headers, create_org_admin_in, create_org_group, create_org_user, login
from tests.link_world import World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Tiers Org")


def tree(text: str = "Hello") -> dict:
    return {**empty_tree("document"), "nodes": [{"type": "heading", "text": text}]}


def org_url(world: World, suffix: str = "") -> str:
    return f"/api/v1/orgs/{world.org['id']}/report-layouts{suffix}"


def project_url(project: dict, suffix: str = "") -> str:
    return f"/api/v1/projects/{project['id']}/report-layouts{suffix}"


def post_layout(world: World, url: str, name: str, *, token: str | None = None, body: dict | None = None):
    return world.client.post(
        url, json={"name": name, "description": "d", "family": "document", "tree": body or tree(name)},
        headers=auth_headers(token or world.token),
    )


def new_layout(world: World, url: str, name: str, **kwargs) -> dict:
    resp = post_layout(world, url, name, **kwargs)
    assert resp.status_code == 201, resp.text
    return resp.json()


def names(world: World, project: dict, token: str | None = None) -> dict[str, dict]:
    resp = world.client.get(project_url(project), headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return {row["name"]: row for row in resp.json()}


def user_with_project_role(world: World, project: dict, role: str) -> tuple[str, str]:
    """A fresh organisation member holding `role` in `project`; returns (user id, token)."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return user_id, login(world.client, email, "Password123!")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---- permissions -----------------------------------------------------------------------------------------------


def test_both_permissions_are_administrative_atoms():
    assert MANAGE_ORG_REPORT_LAYOUTS in ADMINISTRATIVE_PERMISSIONS
    assert MANAGE_PROJECT_REPORT_LAYOUTS in ADMINISTRATIVE_PERMISSIONS


def test_who_holds_which_permission(world, db):
    project = world.project()
    held = {}
    for role in ("project_administrator", "project_manager", "stakeholder", "member"):
        user_id, _ = user_with_project_role(world, project, role)
        held[role] = get_effective_permissions(db, uuid.UUID(user_id), project_id=uuid.UUID(project["id"]))

    org_admin = get_effective_permissions(db, world.user_id, project_id=uuid.UUID(project["id"]))
    assert {MANAGE_ORG_REPORT_LAYOUTS, MANAGE_PROJECT_REPORT_LAYOUTS} <= org_admin
    for role in ("project_administrator", "project_manager"):  # a manager implies an administrator
        assert MANAGE_PROJECT_REPORT_LAYOUTS in held[role], role
        assert MANAGE_ORG_REPORT_LAYOUTS not in held[role], role
    for role in ("stakeholder", "member"):
        assert not held[role] & {MANAGE_ORG_REPORT_LAYOUTS, MANAGE_PROJECT_REPORT_LAYOUTS}, role


def test_a_custom_role_grants_a_permission_to_a_user_or_a_group(world, db):
    project = world.project()
    user_id, _ = user_with_project_role(world, project, "member")
    member_id, _ = user_with_project_role(world, project, "member")
    group_id = create_org_group(world.client, world.token, world.org["id"], "Layout authors", users=[member_id])
    role = CustomRoleDefinition(organization_id=world.org["id"], name="Layouts", description="", scope="org")
    db.add(role)
    db.flush()
    db.add(CustomRolePermission(custom_role_id=role.id, permission=MANAGE_PROJECT_REPORT_LAYOUTS))
    db.add(UserCustomRoleGrant(user_id=uuid.UUID(user_id), custom_role_id=role.id, organization_id=world.org["id"]))
    db.add(GroupCustomRoleGrant(org_group_id=uuid.UUID(group_id), custom_role_id=role.id, organization_id=world.org["id"]))
    db.commit()

    for uid in (user_id, member_id):
        assert MANAGE_PROJECT_REPORT_LAYOUTS in get_effective_permissions(db, uuid.UUID(uid), project_id=uuid.UUID(project["id"]))


# ---- organisation endpoints ------------------------------------------------------------------------------------


def test_an_org_admin_creates_reads_and_lists_a_layout(world):
    created = new_layout(world, org_url(world), "Gap report")

    assert created["origin"] == "organization" and created["project_id"] is None and created["current"]["version"] == 1
    listed = world.client.get(org_url(world), headers=auth_headers(world.token)).json()
    assert [row["name"] for row in listed] == ["Gap report"]
    assert "tree" not in listed[0] and "current" not in listed[0]
    detail = world.client.get(org_url(world, f"/{created['id']}"), headers=auth_headers(world.token)).json()
    assert detail["current"]["tree"] == tree("Gap report")


def test_a_plain_member_may_list_but_not_read_or_change(world):
    layout = new_layout(world, org_url(world), "Gap report")
    email = f"m-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    member = login(world.client, email, "Password123!")
    h = auth_headers(member)

    assert world.client.get(org_url(world), headers=h).status_code == 200
    assert world.client.get(org_url(world, f"/{layout['id']}"), headers=h).status_code == 403
    assert world.client.get(org_url(world, f"/{layout['id']}/versions"), headers=h).status_code == 403
    assert post_layout(world, org_url(world), "Mine", token=member).status_code == 403
    assert world.client.delete(org_url(world, f"/{layout['id']}"), headers=h).status_code == 403
    assert world.client.put(
        org_url(world, f"/{layout['id']}/tree"), json={"tree": tree("x"), "base_version": 1}, headers=h
    ).status_code == 403


def test_a_project_administrator_cannot_manage_organisation_layouts(world):
    project = world.project()
    _, token = user_with_project_role(world, project, "project_administrator")

    assert post_layout(world, org_url(world), "Org one", token=token).status_code == 403


def test_another_organisations_admin_reaches_nothing(client, admin_token, world):
    layout = new_layout(world, org_url(world), "Private")
    _, outsider = create_org_admin_in(client, admin_token, "Outsider Org")
    h = auth_headers(outsider)

    assert client.get(org_url(world), headers=h).status_code in (403, 404)
    assert client.get(org_url(world, f"/{layout['id']}"), headers=h).status_code in (403, 404)
    assert post_layout(world, org_url(world), "Planted", token=outsider).status_code in (403, 404)


def test_a_server_administrator_reaches_no_layout(client, admin_token, world):
    """Layouts are customer content; the server role alone gives no data access inside an organisation."""
    project = world.project()
    org_layout = new_layout(world, org_url(world), "Org wide")
    own = new_layout(world, project_url(project), "Own")
    h = auth_headers(admin_token)

    for method, url in (
        ("get", org_url(world)), ("get", org_url(world, f"/{org_layout['id']}")), ("get", project_url(project)),
        ("get", project_url(project, f"/{own['id']}")), ("get", project_url(project, f"/{own['id']}/versions")),
    ):
        assert getattr(client, method)(url, headers=h).status_code == 403, url
    assert post_layout(world, org_url(world), "Planted", token=admin_token).status_code == 403
    assert post_layout(world, project_url(project), "Planted", token=admin_token).status_code == 403
    assert client.delete(org_url(world, f"/{org_layout['id']}"), headers=h).status_code == 403
    assert client.put(
        project_url(project, f"/{org_layout['id']}/visibility"), json={"hidden": True}, headers=h
    ).status_code == 403


def test_an_invalid_tree_is_refused_with_positioned_errors(world):
    resp = post_layout(world, org_url(world), "Bad", body={**empty_tree("document"), "nodes": [{"type": "nope"}]})

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["errors"] and {"path", "message"} <= detail["errors"][0].keys()
    assert world.client.get(org_url(world), headers=auth_headers(world.token)).json() == []


def test_a_name_is_unique_per_owner_ignoring_case(world):
    new_layout(world, org_url(world), "Gap report")

    assert post_layout(world, org_url(world), "gap REPORT").status_code == 409


def test_saving_versions_conflicts_and_unchanged_saves(world):
    layout = new_layout(world, org_url(world), "Gap report")
    url = org_url(world, f"/{layout['id']}/tree")
    h = auth_headers(world.token)

    unchanged = world.client.put(url, json={"tree": tree("Gap report"), "base_version": 1}, headers=h)
    assert unchanged.status_code == 200 and unchanged.json()["current_version"] == 1

    saved = world.client.put(url, json={"tree": tree("v2"), "base_version": 1, "comment": "retitle"}, headers=h)
    assert saved.status_code == 200 and saved.json()["current_version"] == 2

    stale = world.client.put(url, json={"tree": tree("v3"), "base_version": 1}, headers=h)
    assert stale.status_code == 409 and stale.json()["detail"]["current_version"] == 2

    history = world.client.get(org_url(world, f"/{layout['id']}/versions"), headers=h).json()
    assert [v["version"] for v in history] == [2, 1] and history[0]["comment"] == "retitle"
    old = world.client.get(org_url(world, f"/{layout['id']}/versions/1"), headers=h).json()
    assert old["tree"] == tree("Gap report")
    assert world.client.get(org_url(world, f"/{layout['id']}/versions/9"), headers=h).status_code == 404


def test_rename_and_delete(world):
    layout = new_layout(world, org_url(world), "Gap report")
    h = auth_headers(world.token)

    renamed = world.client.patch(org_url(world, f"/{layout['id']}"), json={"name": "Gap analysis"}, headers=h)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Gap analysis"
    assert world.client.delete(org_url(world, f"/{layout['id']}"), headers=h).status_code == 204
    assert world.client.get(org_url(world, f"/{layout['id']}"), headers=h).status_code == 404


# ---- project view: additive tiers, hide and restore -----------------------------------------------------------


def test_a_project_sees_its_own_its_ancestors_and_the_organisations_layouts(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    new_layout(world, org_url(world), "Org wide")
    new_layout(world, project_url(parent), "From parent")
    new_layout(world, project_url(child), "Own")

    seen = names(world, child)

    assert {n: (r["origin"], r["editable"]) for n, r in seen.items()} == {
        "Own": ("project", True), "From parent": ("ancestor", False), "Org wide": ("organization", False),
    }
    assert list(seen) == ["Own", "From parent", "Org wide"]  # nearest owner first
    assert set(names(world, parent)) == {"From parent", "Org wide"}  # a parent never sees its child's


def test_a_nearer_layout_shadows_a_farther_one_of_the_same_name(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    new_layout(world, org_url(world), "Summary")
    new_layout(world, project_url(parent), "summary")
    own = new_layout(world, project_url(child), "SUMMARY")

    seen = names(world, child)

    assert len(seen) == 1 and next(iter(seen.values()))["id"] == own["id"]


def test_a_project_hides_and_restores_an_inherited_layout(world):
    project = world.project()
    layout = new_layout(world, org_url(world), "Org wide")
    h = auth_headers(world.token)

    hidden = world.client.put(project_url(project, f"/{layout['id']}/visibility"), json={"hidden": True}, headers=h)
    assert hidden.status_code == 200 and hidden.json()["hidden"] is True
    assert names(world, project)["Org wide"]["hidden"] is True

    restored = world.client.put(project_url(project, f"/{layout['id']}/visibility"), json={"hidden": False}, headers=h)
    assert restored.status_code == 200 and restored.json()["hidden"] is False


def test_restore_all_shows_every_hidden_layout(world):
    project = world.project()
    h = auth_headers(world.token)
    ids = [new_layout(world, org_url(world), n)["id"] for n in ("A", "B")]
    for layout_id in ids:
        world.client.put(project_url(project, f"/{layout_id}/visibility"), json={"hidden": True}, headers=h)

    resp = world.client.post(project_url(project, "/restore"), headers=h)

    assert resp.status_code == 200 and sorted(resp.json()["restored"]) == sorted(ids)
    assert not any(row["hidden"] for row in names(world, project).values())


def test_hiding_is_per_project_and_not_inherited_by_children(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    layout = new_layout(world, org_url(world), "Org wide")
    world.client.put(project_url(parent, f"/{layout['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))

    assert names(world, parent)["Org wide"]["hidden"] is True
    assert names(world, child)["Org wide"]["hidden"] is False


def test_a_hidden_layout_still_holds_its_name(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    new_layout(world, org_url(world), "Summary")
    from_parent = new_layout(world, project_url(parent), "Summary")
    world.client.put(project_url(child, f"/{from_parent['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))

    seen = names(world, child)

    assert len(seen) == 1 and seen["Summary"]["id"] == from_parent["id"] and seen["Summary"]["hidden"] is True


def test_only_a_manager_of_layouts_sees_hidden_ones(world):
    project = world.project()
    layout = new_layout(world, org_url(world), "Org wide")
    world.client.put(project_url(project, f"/{layout['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    _, member = user_with_project_role(world, project, "member")
    _, admin = user_with_project_role(world, project, "project_administrator")

    assert names(world, project, member) == {}
    assert names(world, project, admin)["Org wide"]["hidden"] is True


def test_a_projects_own_layout_cannot_be_hidden_only_deleted(world):
    project = world.project()
    own = new_layout(world, project_url(project), "Own")
    h = auth_headers(world.token)

    assert world.client.put(project_url(project, f"/{own['id']}/visibility"), json={"hidden": True}, headers=h).status_code == 404
    assert world.client.delete(project_url(project, f"/{own['id']}"), headers=h).status_code == 204
    assert names(world, project) == {}


def test_an_inherited_layout_is_read_only_in_the_project(world):
    project = world.project()
    inherited = new_layout(world, org_url(world), "Org wide")
    h = auth_headers(world.token)

    read = world.client.get(project_url(project, f"/{inherited['id']}"), headers=h).json()
    assert read["editable"] is False and read["current"]["tree"] == tree("Org wide")
    assert world.client.put(
        project_url(project, f"/{inherited['id']}/tree"), json={"tree": tree("x"), "base_version": 1}, headers=h
    ).status_code == 403
    assert world.client.patch(project_url(project, f"/{inherited['id']}"), json={"name": "x"}, headers=h).status_code == 403
    assert world.client.delete(project_url(project, f"/{inherited['id']}"), headers=h).status_code == 403


def test_another_projects_layout_is_not_reachable(world):
    first, second = world.project("First"), world.project("Second")
    other = new_layout(world, project_url(second), "Second's")
    h = auth_headers(world.token)

    assert world.client.get(project_url(first, f"/{other['id']}"), headers=h).status_code == 404
    assert world.client.put(project_url(first, f"/{other['id']}/visibility"), json={"hidden": True}, headers=h).status_code == 404
    assert names(world, first) == {}


def test_a_project_administrator_authors_in_their_project_only(world):
    mine, other = world.project("Mine"), world.project("Other")
    _, token = user_with_project_role(world, mine, "project_administrator")

    created = post_layout(world, project_url(mine), "Mine", token=token)
    assert created.status_code == 201
    assert post_layout(world, project_url(other), "Nope", token=token).status_code == 403
    assert names(world, mine, token)["Mine"]["editable"] is True


def test_a_plain_project_member_lists_but_cannot_read_or_author(world):
    project = world.project()
    new_layout(world, project_url(project), "Own")
    _, token = user_with_project_role(world, project, "member")

    assert "Own" in names(world, project, token)
    assert post_layout(world, project_url(project), "Mine", token=token).status_code == 403
    layout_id = names(world, project)["Own"]["id"]
    assert world.client.get(project_url(project, f"/{layout_id}"), headers=auth_headers(token)).status_code == 403


def test_deleting_an_organisation_layout_clears_the_projects_tombstones(world, db):
    project = world.project()
    layout = new_layout(world, org_url(world), "Org wide")
    world.client.put(project_url(project, f"/{layout['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    count = select(func.count()).select_from(ProjectDefinitionSuppression).where(
        ProjectDefinitionSuppression.project_id == uuid.UUID(project["id"])
    )
    assert db.scalar(count) == 1

    assert world.client.delete(org_url(world, f"/{layout['id']}"), headers=auth_headers(world.token)).status_code == 204

    db.expire_all()
    assert db.scalar(count) == 0


def test_hide_and_restore_are_audited_without_layout_text(world, db):
    project = world.project()
    layout = new_layout(world, org_url(world), "Org wide")
    h = auth_headers(world.token)
    world.client.put(project_url(project, f"/{layout['id']}/visibility"), json={"hidden": True}, headers=h)
    world.client.put(project_url(project, f"/{layout['id']}/visibility"), json={"hidden": False}, headers=h)

    events = db.scalars(select(AuditEvent).where(
        AuditEvent.entity_id == str(layout["id"]), AuditEvent.action.in_(("hidden", "restored"))
    )).all()

    assert sorted(e.action for e in events) == ["hidden", "restored"]
    assert all(e.project_id == uuid.UUID(project["id"]) and "Org wide" not in json.dumps(e.detail) for e in events)


# ---- bundles ----------------------------------------------------------------------------------------------------


def export_project(world: World, project: dict) -> bytes:
    resp = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.content


def import_project(world: World, bundle: bytes, name: str = "Imported") -> dict:
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def rewrite(bundle: bytes, member: str, edit) -> bytes:
    """The zip with `member` (a JSON file) passed through `edit`."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == member:
                parsed = json.loads(data)
                edit(parsed)
                data = json.dumps(parsed).encode()
            dst.writestr(item, data)
    return out.getvalue()


def test_a_project_bundle_carries_layouts_with_their_history_and_hides(world):
    project = world.project("Source")
    h = auth_headers(world.token)
    inherited = new_layout(world, org_url(world), "Org wide")
    world.client.put(project_url(project, f"/{inherited['id']}/visibility"), json={"hidden": True}, headers=h)
    own = new_layout(world, project_url(project), "Own report")
    world.client.put(
        project_url(project, f"/{own['id']}/tree"), json={"tree": tree("second"), "base_version": 1, "comment": "retitle"}, headers=h,
    )

    result = import_project(world, export_project(world, project))

    assert result["warnings"] == []
    copy = result["project"]
    seen = names(world, copy)
    assert seen["Own report"]["current_version"] == 2 and seen["Own report"]["origin"] == "project"
    assert seen["Org wide"]["hidden"] is True
    versions = world.client.get(project_url(copy, f"/{seen['Own report']['id']}/versions"), headers=h).json()
    assert [(v["version"], v["comment"]) for v in versions] == [(2, "retitle"), (1, "")]
    current = world.client.get(project_url(copy, f"/{seen['Own report']['id']}"), headers=h).json()
    assert current["current"]["tree"] == tree("second") and current["id"] != own["id"]


def test_margins_page_styles_and_sections_survive_a_project_bundle_round_trip(world):
    project = world.project("Source")
    h = auth_headers(world.token)
    styled = {
        **empty_tree("document"), "margins": {"top": 2, "gutter": 1}, "mirror_margins": True,
        "page_styles": [{"name": "Wide tables", "page_size": "A3", "orientation": "landscape", "margins": {"left": 1}}],
        "nodes": [{"type": "section", "page_style": "Wide tables", "children": [{"type": "text", "text": "Inside"}]}],
    }
    new_layout(world, project_url(project), "Styled", body=styled)

    result = import_project(world, export_project(world, project))

    assert result["warnings"] == []
    copy = names(world, result["project"])["Styled"]
    current = world.client.get(project_url(result["project"], f"/{copy['id']}"), headers=h).json()
    assert current["current"]["tree"] == styled


def test_a_bundle_tree_is_validated_again_and_bad_versions_are_dropped(world):
    project = world.project("Source")
    h = auth_headers(world.token)
    own = new_layout(world, project_url(project), "Own report")
    world.client.put(project_url(project, f"/{own['id']}/tree"), json={"tree": tree("second"), "base_version": 1}, headers=h)
    new_layout(world, project_url(project), "Broken")

    def corrupt(data: dict) -> None:
        for layout in data["report_layouts"]:
            if layout["name"] == "Own report":
                layout["versions"][1]["tree"]["nodes"] = [{"type": "nope"}]
            else:
                layout["versions"][0]["tree"]["nodes"] = [{"type": "nope"}]

    bundle = rewrite(export_project(world, project), "project.json", corrupt)
    result = import_project(world, bundle)

    assert any("Own report" in w and "1 version" in w for w in result["warnings"])
    assert any("Broken" in w and "skipped" in w for w in result["warnings"])
    seen = names(world, result["project"])
    assert set(seen) == {"Own report"} and seen["Own report"]["current_version"] == 1


def test_a_hide_with_no_matching_inherited_layout_is_reported(world):
    project = world.project("Source")
    org_layout = new_layout(world, org_url(world), "Org wide")
    world.client.put(project_url(project, f"/{org_layout['id']}/visibility"), json={"hidden": True}, headers=auth_headers(world.token))
    bundle = export_project(world, project)
    world.client.delete(org_url(world, f"/{org_layout['id']}"), headers=auth_headers(world.token))

    result = import_project(world, bundle)

    assert any('Hidden report layout "Org wide"' in w for w in result["warnings"])


def test_an_organisation_bundle_carries_organisation_and_project_layouts(client, admin_token, world):
    project = world.project("Source")
    h = auth_headers(world.token)
    new_layout(world, org_url(world), "Org wide")
    shared = new_layout(world, org_url(world), "Hidden here")
    world.client.put(project_url(project, f"/{shared['id']}/visibility"), json={"hidden": True}, headers=h)
    new_layout(world, project_url(project), "Own report")
    bundle = client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=h).content

    resp = client.post(
        "/api/v1/orgs/import", data={"name": f"Copy {uuid.uuid4().hex[:6]}"},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    new_org_id = resp.json()["organization"]["id"]
    mine = auth_headers(world.token)  # the source organisation's admin has an account, so the import grants them the role

    listed = client.get(f"/api/v1/orgs/{new_org_id}/report-layouts", headers=mine).json()
    assert sorted(row["name"] for row in listed) == ["Hidden here", "Org wide"]
    projects = client.get(f"/api/v1/projects?organization_id={new_org_id}", headers=mine).json()
    copy = next(p for p in projects if p["name"] == "Source")
    seen = client.get(f"/api/v1/projects/{copy['id']}/report-layouts", headers=mine).json()
    by_name = {row["name"]: row for row in seen}
    assert by_name["Own report"]["origin"] == "project"
    assert by_name["Hidden here"]["hidden"] is True and by_name["Org wide"]["hidden"] is False


def test_merging_never_overwrites_an_existing_layout(client, admin_token, world):
    h = auth_headers(world.token)
    new_layout(world, org_url(world), "Shared name")
    new_layout(world, org_url(world), "New one")
    bundle = client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=h).content

    target, target_token = create_org_admin_in(client, admin_token, "Merge Target")
    target_url = f"/api/v1/orgs/{target['id']}/report-layouts"
    kept = client.post(
        target_url, json={"name": "Shared name", "family": "document", "tree": tree("keep me")},
        headers=auth_headers(target_token),
    ).json()
    opened = client.put(
        f"/api/v1/orgs/{target['id']}/advanced-settings", json={"external_user_policy": "anyone"}, headers=auth_headers(target_token),
    )
    assert opened.status_code == 200, opened.text

    merged = client.post(
        f"/api/v1/orgs/{target['id']}/import/merge", files={"file": ("bundle.zip", bundle, "application/zip")},
        data={"resolutions": "{}"}, headers=auth_headers(target_token),
    )
    assert merged.status_code == 200, merged.text

    rows = client.get(target_url, headers=auth_headers(target_token)).json()
    assert sorted(r["name"] for r in rows) == ["New one", "Shared name", "Shared name (imported)"]
    kept_now = client.get(f"{target_url}/{kept['id']}", headers=auth_headers(target_token)).json()
    assert kept_now["current"]["tree"] == tree("keep me") and kept_now["current_version"] == 1
