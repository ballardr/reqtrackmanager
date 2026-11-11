"""Tests for requirement actions in the project bundle: the project's action types, every action with its outcome,
assignee, comments, attachments, tags and places, and its links to requirements; and that a bundle written before
actions were carried still imports.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by another test.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.file import RequirementActionFile
from app.models.project import Project
from app.models.requirement_action import RequirementAction
from tests.conftest import auth_headers
from tests.link_world import ACTION, REQ, World


def _base(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}"


def _export(world: World, project: dict) -> bytes:
    resp = world.client.get(f"{_base(project)}/export", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _import(world: World, bundle: bytes, name: str) -> tuple[dict, list[str]]:
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["project"], resp.json()["warnings"]


def _actions(world: World, project: dict) -> dict[str, dict]:
    resp = world.client.get(f"{_base(project)}/actions", params={"include_archived": "true"}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return {a["title"]: a for a in resp.json()}


def _api(world: World, method: str, url: str, **kwargs):
    resp = getattr(world.client, method)(url, headers=auth_headers(world.token), **kwargs)
    assert resp.status_code in (200, 201, 204), resp.text
    return resp


def _rich_project(world: World) -> dict:
    """Two requirements and four actions: a custom type, an outcome, an assignee, a comment with a file, a direct
    file, tags, places, an archived one and links to both requirements and to another action."""
    project = world.project("Source")
    types = _api(world, "get", f"{_base(project)}/action-types").json()
    audit = _api(world, "post", f"{_base(project)}/action-types", json={"name": "Audit"}).json()
    first, second = world.requirement(project, "First"), world.requirement(project, "Second")
    review = _api(world, "post", f"{_base(project)}/actions", json={
        "title": "Review wiring", "description": "Check every harness", "action_type_id": types[0]["id"],
        "assignee": {"type": "user", "id": str(world.user_id)}, "due_date": "2026-12-01",
    }).json()
    audit_action = _api(world, "post", f"{_base(project)}/actions", json={"title": "Audit supplier", "action_type_id": audit["id"]}).json()
    _api(world, "post", f"{_base(project)}/actions", json={"title": "Plain action", "action_type_id": types[0]["id"]})
    archived = _api(world, "post", f"{_base(project)}/actions", json={"title": "Old action", "action_type_id": types[0]["id"]}).json()
    _api(world, "patch", f"{_base(project)}/actions/{review['id']}", json={
        "title": "Review wiring", "description": "Check every harness", "action_type_id": types[0]["id"],
        "outcome_status": "completed", "due_date": "2026-12-01", "assignee": {"type": "user", "id": str(world.user_id)},
    })
    _api(world, "post", f"{_base(project)}/actions/{archived['id']}/archive")
    comment = _api(world, "post", f"{_base(project)}/actions/{review['id']}/comments", json={"body": "Done on site"}).json()
    _api(
        world, "post", f"{_base(project)}/actions/{review['id']}/comments/{comment['id']}/files",
        files={"file": ("photo.txt", b"comment bytes", "text/plain")},
    )
    _api(world, "post", f"{_base(project)}/actions/{review['id']}/files", files={"file": ("plan.txt", b"plan bytes", "text/plain")})
    _api(world, "put", f"{_base(project)}/artefacts/requirement_action/{review['id']}/tags", json={"tags": ["Safety"]})
    _api(world, "put", f"{_base(project)}/artefacts/requirement_action/{review['id']}/placements", json={
        "placements": [{"component_id": project["component_id"], "category_id": project["category_id"]}],
    })
    world.link((ACTION, uuid.UUID(review["id"])), (REQ, first))
    world.link((ACTION, uuid.UUID(review["id"])), (REQ, second))
    world.link((ACTION, uuid.UUID(audit_action["id"])), (REQ, second))
    world.link((ACTION, uuid.UUID(audit_action["id"])), (ACTION, uuid.UUID(review["id"])))
    return project


def test_a_bundle_carries_actions_with_everything_attached(client, admin_token):
    world = World(client, admin_token, "Action Bundle Org")
    source = _rich_project(world)
    original = _actions(world, source)

    copy, warnings = _import(world, _export(world, source), "Copy")

    assert warnings == []
    copied = _actions(world, copy)
    assert set(copied) == set(original) == {"Review wiring", "Audit supplier", "Plain action", "Old action"}
    for title, action in original.items():
        assert copied[title]["unique_code"] == action["unique_code"], "an action keeps its code"
        assert copied[title]["outcome_status"] == action["outcome_status"]
        assert copied[title]["is_archived"] == action["is_archived"]
    review = copied["Review wiring"]
    assert review["description"] == "Check every harness" and review["due_date"] == "2026-12-01"
    assert review["assignee"]["id"] == str(world.user_id)
    assert review["completed_at"] is not None
    assert copied["Old action"]["is_archived"] is True

    types = _api(world, "get", f"{_base(copy)}/action-types").json()
    assert {t["name"] for t in types} == {"Review", "Test", "Audit"}
    type_of = {t["id"]: t["name"] for t in types}
    assert type_of[copied["Audit supplier"]["action_type_id"]] == "Audit"

    comments = _api(world, "get", f"{_base(copy)}/actions/{review['id']}/comments").json()
    assert [c["body"] for c in comments] == ["Done on site"] and len(comments[0]["attachments"]) == 1
    files = _api(world, "get", f"{_base(copy)}/actions/{review['id']}/files").json()
    assert [f["filename"] for f in files] == ["plan.txt"]
    tags = _api(world, "get", f"{_base(copy)}/artefacts/requirement_action/{review['id']}/tags").json()
    assert [t["name"] for t in tags["tags"]] == ["Safety"]
    placed = _api(world, "get", f"{_base(copy)}/artefacts/requirement_action/{review['id']}/placements").json()
    assert [(p["component_name"], p["category_name"]) for p in placed["placements"]] == [("Software", "Performance")]
    for placement in placed["placements"]:
        copied_components = {c["id"] for c in _api(world, "get", f"{_base(copy)}/components").json()}
        assert placement["component_id"] in copied_components, "a copy never points at the source tree"


def test_a_bundle_carries_the_links_between_actions_and_requirements(client, admin_token):
    world = World(client, admin_token, "Action Link Org")
    source = _rich_project(world)
    copy, warnings = _import(world, _export(world, source), "Copy")
    assert warnings == []
    actions = _actions(world, copy)
    requirements = {r["name"]: r for r in _api(world, "get", f"{_base(copy)}/requirements").json()}

    def linked(title: str) -> list[str]:
        return sorted(r["name"] for r in _api(world, "get", f"{_base(copy)}/actions/{actions[title]['id']}/requirements").json())

    assert linked("Review wiring") == ["First", "Second"]
    assert linked("Audit supplier") == ["Second"]
    graph = _api(world, "get", f"{_base(copy)}/artefacts/requirement_action/{actions['Audit supplier']['id']}/link-graph").json()
    assert actions["Review wiring"]["id"] in json.dumps(graph), "the link between two actions came across"
    source_requirements = {r["name"]: r["id"] for r in _api(world, "get", f"{_base(source)}/requirements").json()}
    assert requirements["First"]["id"] != source_requirements["First"], "the copy links to its own requirements"


def test_the_action_counter_moves_past_imported_codes(client, admin_token):
    world = World(client, admin_token, "Action Counter Org")
    source = _rich_project(world)
    copy, _ = _import(world, _export(world, source), "Copy")
    types = _api(world, "get", f"{_base(copy)}/action-types").json()
    made = _api(world, "post", f"{_base(copy)}/actions", json={"title": "New one", "action_type_id": types[0]["id"]}).json()
    assert made["unique_code"] == "ACT-005"


def test_an_action_whose_type_the_bundle_does_not_list_gets_that_type_created(client, admin_token):
    """A child project's action may use its parent's type, which the child's own list does not carry."""
    world = World(client, admin_token, "Action Inherited Type Org")
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    with SessionLocal() as db:
        from app.models.action_type import ActionTypeDefinition

        db.query(ActionTypeDefinition).filter(ActionTypeDefinition.project_id == uuid.UUID(child["id"])).delete()
        db.commit()
    types = _api(world, "get", f"{_base(child)}/action-types").json()
    assert types, "the child falls back to its parent's types"
    _api(world, "post", f"{_base(child)}/actions", json={"title": "Inherited type", "action_type_id": types[0]["id"]})
    copy, warnings = _import(world, _export(world, child), "Standalone copy")
    assert warnings == []
    copied = _actions(world, copy)["Inherited type"]
    own = {t["id"]: t["name"] for t in _api(world, "get", f"{_base(copy)}/action-types").json()}
    assert own[copied["action_type_id"]] == types[0]["name"]


def test_a_bundle_written_before_actions_were_carried_still_imports(client, admin_token):
    world = World(client, admin_token, "Action Old Bundle Org")
    source = _rich_project(world)
    old = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_export(world, source))) as zin, zipfile.ZipFile(old, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "project.json":
                data = json.loads(content)
                for key in ("action_types", "actions", "action_links"):
                    data.pop(key)
                content = json.dumps(data).encode()
            zout.writestr(item, content)
    copy, warnings = _import(world, old.getvalue(), "Old copy")
    assert warnings == []
    assert _actions(world, copy) == {}
    assert {t["name"] for t in _api(world, "get", f"{_base(copy)}/action-types").json()} == {"Review", "Test"}


def test_a_repeated_or_malformed_action_code_is_numbered_afresh_with_a_warning(client, admin_token):
    world = World(client, admin_token, "Action Code Org")
    source = _rich_project(world)
    edited = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_export(world, source))) as zin, zipfile.ZipFile(edited, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "project.json":
                data = json.loads(content)
                data["actions"][1]["unique_code"] = data["actions"][0]["unique_code"]
                data["actions"][2]["unique_code"] = "nonsense"
                content = json.dumps(data).encode()
            zout.writestr(item, content)
    copy, warnings = _import(world, edited.getvalue(), "Edited copy")
    assert len([w for w in warnings if "numbered afresh" in w]) == 2
    codes = [a["unique_code"] for a in _actions(world, copy).values()]
    assert len(codes) == len(set(codes)) == 4


def test_deleting_the_source_leaves_the_copy_complete(client, admin_token):
    world = World(client, admin_token, "Action Independent Org")
    source = _rich_project(world)
    copy, _ = _import(world, _export(world, source), "Copy")
    with SessionLocal() as db:
        db.delete(db.get(Project, uuid.UUID(source["id"])))
        db.commit()
        copied_ids = list(db.scalars(select(RequirementAction.id).where(RequirementAction.project_id == uuid.UUID(copy["id"]))))
        assert len(copied_ids) == 4
        assert db.scalar(select(func.count()).select_from(RequirementActionFile).where(RequirementActionFile.action_id.in_(copied_ids))) == 1
