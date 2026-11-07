"""Navigation names: validation against the registry's stable keys, per-key resolution (own, nearest ancestor,
organisation, built-in), who may read and change them, the catalogue following module enablement, audit without
the text, and the project bundle, organisation bundle and template clone."""

import io
import json
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.registry import get_module_registry
from app.services import nav_labels
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

DECISIONS = "decisions:"


def _project_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/nav-labels"


def _org_url(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/nav-labels"


def _enable(client, token, org_id, module_key="decisions") -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{module_key}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _item(body: dict, key: str) -> dict:
    return next(i for i in body["items"] if i["key"] == key)


def test_keys_are_stable_and_contain_no_project_id():
    keys = nav_labels.valid_keys()
    assert {"overview", "requirements", "change-requests", "actions", "files", "reviews-due", "history", "admin"} <= keys
    assert DECISIONS in keys
    assert not any("{" in key or "/projects/" in key for key in keys)
    # Every registered module entry has exactly one key.
    entries = [item for item in nav_labels.module_items()]
    assert len({item.key for item in entries}) == len(entries)
    assert {item.module_key for item in entries} <= set(get_module_registry())


def test_a_project_renames_an_entry_and_restores_it(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    before = client.get(_project_url(project["id"]), headers=headers).json()
    assert _item(before, "requirements")["effective"] is None
    assert _item(before, "requirements")["path"] == f"/projects/{project['id']}/requirements"

    renamed = client.put(_project_url(project["id"]), json={"names": {"requirements": "  Needs   list "}}, headers=headers)
    assert renamed.status_code == 200, renamed.text
    item = _item(renamed.json(), "requirements")
    assert (item["own"], item["effective"]) == ("Needs list", "Needs list")

    restored = client.put(_project_url(project["id"]), json={"names": {}}, headers=headers).json()
    assert _item(restored, "requirements")["effective"] is None


def test_unknown_keys_overlong_and_control_character_names_are_refused(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    for names in ({"not-an-entry": "X"}, {"requirements": "x" * 41}, {"requirements": "Bad\x07name"}):
        resp = client.put(_project_url(project["id"]), json={"names": names}, headers=headers)
        assert resp.status_code == 422, names
    assert client.put(_project_url(project["id"]), json={"names": {"requirements": "x" * 40}}, headers=headers).status_code == 200


def test_a_blank_name_restores_the_entry(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    client.put(_project_url(project["id"]), json={"names": {"actions": "Tasks"}}, headers=headers)
    body = client.put(_project_url(project["id"]), json={"names": {"actions": "   "}}, headers=headers).json()
    assert _item(body, "actions")["own"] is None


def test_resolution_is_per_key_project_then_ancestor_then_organisation(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, name="Parent", can_be_parent=True)
    child = create_project(client, admin_token, org_id, name="Child", parent_project_id=parent["id"])
    headers = auth_headers(admin_token)
    client.put(_org_url(org_id), json={"names": {"actions": "Org tasks", "files": "Org documents", "history": "Org log"}}, headers=headers)
    client.put(_project_url(parent["id"]), json={"names": {"actions": "Parent tasks", "files": "Parent documents"}}, headers=headers)
    client.put(_project_url(child["id"]), json={"names": {"actions": "Child tasks"}}, headers=headers)

    body = client.get(_project_url(child["id"]), headers=headers).json()
    assert (_item(body, "actions")["effective"], _item(body, "actions")["inherited"]) == ("Child tasks", "Parent tasks")
    assert (_item(body, "files")["effective"], _item(body, "files")["inherited_from"]) == ("Parent documents", "ancestor")
    assert (_item(body, "history")["effective"], _item(body, "history")["inherited_from"]) == ("Org log", "organisation")
    assert _item(body, "overview")["effective"] is None


def test_the_catalogue_follows_module_enablement_but_stored_names_survive_a_switch_off(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Nav names org")
    project = create_project(client, token, org["id"])
    headers = auth_headers(token)
    assert DECISIONS not in {i["key"] for i in client.get(_project_url(project["id"]), headers=headers).json()["items"]}

    _enable(client, token, org["id"])
    listed = client.get(_project_url(project["id"]), headers=headers).json()
    assert _item(listed, DECISIONS)["path"] == f"/projects/{project['id']}/modules/decisions"
    client.put(_project_url(project["id"]), json={"names": {DECISIONS: "ADRs"}}, headers=headers)

    client.put(f"/api/v1/orgs/{org['id']}/modules/decisions", json={"enabled": False}, headers=headers)
    assert DECISIONS not in {i["key"] for i in client.get(_project_url(project["id"]), headers=headers).json()["items"]}
    client.put(f"/api/v1/orgs/{org['id']}/modules/decisions", json={"enabled": True}, headers=headers)
    assert _item(client.get(_project_url(project["id"]), headers=headers).json(), DECISIONS)["effective"] == "ADRs"


def test_only_project_managers_change_names_and_only_organisation_administrators_change_defaults(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    admin = auth_headers(admin_token)
    user_id = create_org_user(client, admin_token, org_id, "nav-member@example.com")
    client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=admin)
    member = auth_headers(login(client, "nav-member@example.com", "Password123!"))

    assert client.get(_project_url(project["id"]), headers=member).status_code == 200
    assert client.put(_project_url(project["id"]), json={"names": {"actions": "Tasks"}}, headers=member).status_code == 403
    assert client.get(_org_url(org_id), headers=member).status_code == 403
    assert client.put(_org_url(org_id), json={"names": {"actions": "Tasks"}}, headers=member).status_code == 403


def test_an_organisation_administrator_cannot_reach_another_organisation(client, admin_token):
    first, first_token = create_org_admin_in(client, admin_token, "Nav isolation one")
    second, _second_token = create_org_admin_in(client, admin_token, "Nav isolation two")
    headers = auth_headers(first_token)
    assert client.get(_org_url(second["id"]), headers=headers).status_code == 403
    assert client.put(_org_url(second["id"]), json={"names": {"actions": "X"}}, headers=headers).status_code == 403
    assert client.get(_org_url(first["id"]), headers=headers).status_code == 200


def test_changes_are_audited_with_keys_and_never_the_text(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    client.put(_project_url(project["id"]), json={"names": {"actions": "Secretive tasks name"}}, headers=headers)
    client.put(_org_url(org_id), json={"names": {"files": "Secretive documents name"}}, headers=headers)
    db = SessionLocal()
    try:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "nav_labels")).all()
        details = [e.detail for e in events if e.entity_id in (project["id"], org_id)]
        assert {"keys": ["actions"], "count": 1} in details and {"keys": ["files"], "count": 1} in details
        assert "Secretive" not in json.dumps(details)
    finally:
        db.close()


def test_the_project_bundle_round_trips_names_and_skips_unknown_keys_with_a_warning(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    client.put(_project_url(project["id"]), json={"names": {"actions": "Tasks", "files": "Documents"}}, headers=headers)
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=headers)
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    assert json.loads(archive.read("project.json"))["nav_label_overrides"] == {"actions": "Tasks", "files": "Documents"}

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Names copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    body = client.get(_project_url(imported.json()["project"]["id"]), headers=headers).json()
    assert (_item(body, "actions")["own"], _item(body, "files")["own"]) == ("Tasks", "Documents")

    # A name for an entry this installation does not have is dropped with a warning; the rest still import.
    rewritten = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(export.content)) as source, zipfile.ZipFile(rewritten, "w") as target:
        for entry in source.namelist():
            data = source.read(entry)
            if entry == "project.json":
                content = json.loads(data)
                content["nav_label_overrides"]["gone_module:page"] = "Lost"
                data = json.dumps(content).encode()
            target.writestr(entry, data)
    again = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Names copy two"},
        files={"file": ("bundle.zip", rewritten.getvalue(), "application/zip")}, headers=headers,
    )
    assert again.status_code == 201, again.text
    assert any("navigation name" in w for w in again.json()["warnings"])
    assert _item(client.get(_project_url(again.json()["project"]["id"]), headers=headers).json(), "actions")["own"] == "Tasks"


def test_the_organisation_bundle_round_trips_default_names(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    client.put(_org_url(org_id), json={"names": {"history": "Audit trail"}}, headers=headers)
    export = client.get(f"/api/v1/orgs/{org_id}/export", headers=headers)
    assert json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))["nav_label_overrides"] == {"history": "Audit trail"}
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Nav defaults copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    new_org = imported.json()["organization"]["id"]
    assert _item(client.get(_org_url(new_org), headers=headers).json(), "history")["own"] == "Audit trail"


def test_a_template_clone_copies_the_projects_names(client, admin_token, org_id):
    headers = auth_headers(admin_token)
    template = create_project(client, admin_token, org_id, name="Names template")
    client.put(_project_url(template["id"]), json={"names": {"actions": "Tasks"}}, headers=headers)
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=headers)
    cloned = client.post(
        "/api/v1/projects",
        json={"organization_id": org_id, "name": "From names template", "summary": "", "template_project_id": template["id"]},
        headers=headers,
    )
    assert cloned.status_code == 201, cloned.text
    assert _item(client.get(_project_url(cloned.json()["id"]), headers=headers).json(), "actions")["own"] == "Tasks"
