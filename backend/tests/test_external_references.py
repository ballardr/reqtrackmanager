"""External references on any record, and the shared list of outside systems they point into.

Pins the system list (seeding, organisation and project tiers, the link template and its validation, hide and restore,
the nested-project fallback), the references on a record of a core type and of a module type (authority, tier, cap,
audit, cross-organisation rejection, the link a key resolves to), the migration of Product Feedback's table and the
bundles and templates. Each test builds its own organisation, so none depends on another's state.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import select

from alembic import command
from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.external_reference import ExternalReference, ExternalSystemDefinition
from app.services import external_references as refs
from tests.conftest import auth_headers, build_alembic_config, create_org_user, login
from tests.link_world import REQ, World

PAIN = "pain_point"

TEMPLATE = "https://tracker.example/browse/{key}"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Ref Org", context_strategy=True)


def _org(world: World) -> str:
    return f"/api/v1/orgs/{world.org['id']}/external-systems"


def _proj(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}/external-systems"


def _refs_url(project: dict, record: tuple[str, uuid.UUID]) -> str:
    return f"/api/v1/projects/{project['id']}/artefacts/{record[0]}/{record[1]}/external-references"


def _by_name(rows: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in rows}


def _systems(world: World, project: dict) -> dict[str, dict]:
    resp = world.client.get(_proj(project), headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return _by_name(resp.json())


def _member_token(world: World, project: dict, role: str = "member") -> str:
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


# --- the system list ---------------------------------------------------------------------------------------------


def test_a_new_organisation_has_the_default_systems(world):
    rows = world.client.get(_org(world), headers=auth_headers(world.token)).json()
    assert [r["name"] for r in rows] == list(refs.DEFAULT_EXTERNAL_SYSTEMS)
    assert all(r["url_template"] is None and r["is_active"] for r in rows)


def test_only_an_organisation_administrator_changes_the_organisation_list(world):
    project = world.project()
    member = _member_token(world, project)
    assert world.client.get(_org(world), headers=auth_headers(member)).status_code == 200
    assert world.client.post(_org(world), json={"name": "Linear"}, headers=auth_headers(member)).status_code == 403
    created = world.client.post(_org(world), json={"name": "Linear", "url_template": TEMPLATE}, headers=auth_headers(world.token))
    assert created.status_code == 201 and created.json()["url_template"] == TEMPLATE
    dup = world.client.post(_org(world), json={"name": "Linear"}, headers=auth_headers(world.token))
    assert dup.status_code == 400


@pytest.mark.parametrize("template", [
    "javascript:alert({key})", "https://x.example/a", "https://x.example/{key}/{key}", "https://x.example/{key}{other}",
    "ftp://x.example/{key}", "https:///{key}", "data:text/html,{key}",
])
def test_a_link_template_must_be_one_http_or_https_url_with_one_key(world, template):
    resp = world.client.post(_org(world), json={"name": "Bad", "url_template": template}, headers=auth_headers(world.token))
    assert resp.status_code == 422, resp.text
    assert "Bad" not in _by_name(world.client.get(_org(world), headers=auth_headers(world.token)).json())


def test_the_template_can_be_changed_and_cleared(world):
    jira = _by_name(world.client.get(_org(world), headers=auth_headers(world.token)).json())["Jira"]
    url = f"{_org(world)}/{jira['id']}"
    assert world.client.patch(url, json={"url_template": TEMPLATE}, headers=auth_headers(world.token)).json()["url_template"] == TEMPLATE
    assert world.client.patch(url, json={"is_active": False}, headers=auth_headers(world.token)).json()["url_template"] == TEMPLATE
    assert world.client.patch(url, json={"url_template": None}, headers=auth_headers(world.token)).json()["url_template"] is None


def test_a_project_sees_the_organisation_list_and_may_override_a_template_hide_and_restore(world):
    jira = _by_name(world.client.get(_org(world), headers=auth_headers(world.token)).json())["Jira"]
    world.client.patch(f"{_org(world)}/{jira['id']}", json={"url_template": TEMPLATE}, headers=auth_headers(world.token))
    project = world.project()
    systems = _systems(world, project)
    assert list(systems) == list(refs.DEFAULT_EXTERNAL_SYSTEMS) and systems["Jira"]["url_template"] == TEMPLATE

    own = "https://own.example/t/{key}"
    resp = world.client.put(f"{_proj(project)}/{systems['Jira']['id']}", json={"url_template": own}, headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    assert _systems(world, project)["Jira"]["url_template"] == own
    # null follows the organisation's template again.
    world.client.put(f"{_proj(project)}/{systems['Jira']['id']}", json={"url_template": None}, headers=auth_headers(world.token))
    assert _systems(world, project)["Jira"]["url_template"] == TEMPLATE

    local = world.client.post(_proj(project), json={"name": "Internal", "url_template": own}, headers=auth_headers(world.token))
    assert local.status_code == 201 and local.json()["url_template"] == own
    assert _systems(world, project)["Internal"]["source"] == "project_local"

    assert world.client.delete(f"{_proj(project)}/{systems['GitHub']['id']}", headers=auth_headers(world.token)).status_code == 204
    assert "GitHub" not in _systems(world, project)
    hidden = world.client.get(f"{_proj(project)}/hidden", headers=auth_headers(world.token)).json()
    assert [h["name"] for h in hidden] == ["GitHub"]
    restored = world.client.post(f"{_proj(project)}/restore", json={}, headers=auth_headers(world.token))
    assert restored.status_code == 200 and "GitHub" in _systems(world, project)


def test_only_project_settings_authority_changes_a_projects_list(world):
    project = world.project()
    member = _member_token(world, project)
    assert world.client.get(_proj(project), headers=auth_headers(member)).status_code == 200
    assert world.client.post(_proj(project), json={"name": "Mine"}, headers=auth_headers(member)).status_code == 403
    assert world.client.post(_proj(project), json={"name": "Mine"}, headers=auth_headers(world.token)).status_code == 201


def test_a_child_project_shows_its_parents_list_until_it_changes_its_own(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    parent_systems = _systems(world, parent)
    world.client.post(_proj(parent), json={"name": "Parent only"}, headers=auth_headers(world.token))
    assert "Parent only" in _systems(world, child)
    # The child's first change copies what it inherits, so a later parent change no longer reaches it.
    assert world.client.post(_proj(child), json={"name": "Child only"}, headers=auth_headers(world.token)).status_code == 201
    world.client.post(_proj(parent), json={"name": "Parent later"}, headers=auth_headers(world.token))
    child_names = set(_systems(world, child))
    assert {"Parent only", "Child only"} <= child_names and "Parent later" not in child_names
    assert "Parent only" not in parent_systems


def test_a_system_in_use_cannot_be_deleted_but_may_be_deactivated(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    jira = _systems(world, project)["Jira"]
    assert world.client.post(
        _refs_url(project, record), json={"system_id": jira["id"], "key": "P-1"}, headers=auth_headers(world.token),
    ).status_code == 201
    org_jira = _by_name(world.client.get(_org(world), headers=auth_headers(world.token)).json())["Jira"]
    assert world.client.delete(f"{_org(world)}/{org_jira['id']}", headers=auth_headers(world.token)).status_code == 409
    assert world.client.patch(
        f"{_org(world)}/{org_jira['id']}", json={"is_active": False}, headers=auth_headers(world.token),
    ).status_code == 200


# --- references on a record --------------------------------------------------------------------------------------


def test_a_record_of_a_core_type_takes_references_with_a_link_from_the_template(world):
    jira = _by_name(world.client.get(_org(world), headers=auth_headers(world.token)).json())["Jira"]
    world.client.patch(f"{_org(world)}/{jira['id']}", json={"url_template": TEMPLATE}, headers=auth_headers(world.token))
    project = world.project()
    record = (REQ, world.requirement(project))
    systems = _systems(world, project)
    empty = world.client.get(_refs_url(project, record), headers=auth_headers(world.token)).json()
    assert empty["references"] == [] and empty["can_edit"] is True
    assert {s["name"] for s in empty["systems"]} == set(refs.DEFAULT_EXTERNAL_SYSTEMS)

    added = world.client.post(
        _refs_url(project, record),
        json={"system_id": systems["Jira"]["id"], "key": "A/B C-1", "note": "Epic", "role": "origin"},
        headers=auth_headers(world.token),
    )
    assert added.status_code == 201, added.text
    [ref] = added.json()["references"]
    assert ref["link"] == "https://tracker.example/browse/A%2FB%20C-1" and ref["url"] is None
    assert (ref["system_name"], ref["note"], ref["role"]) == ("Jira", "Epic", "origin")

    explicit = world.client.post(
        _refs_url(project, record), json={"system_id": systems["GitHub"]["id"], "url": "https://gh.example/1"},
        headers=auth_headers(world.token),
    ).json()["references"]
    assert [r["link"] for r in explicit][-1] == "https://gh.example/1"

    patched = world.client.patch(
        f"{_refs_url(project, record)}/{ref['id']}", json={"role": None, "key": "X-2"}, headers=auth_headers(world.token),
    )
    assert patched.status_code == 200
    changed = next(r for r in patched.json()["references"] if r["id"] == ref["id"])
    assert (changed["key"], changed["role"], changed["link"]) == ("X-2", None, "https://tracker.example/browse/X-2")

    removed = world.client.delete(f"{_refs_url(project, record)}/{ref['id']}", headers=auth_headers(world.token))
    assert removed.status_code == 200 and len(removed.json()["references"]) == 1


def test_a_module_type_takes_references_too(world):
    project = world.project()
    record = (PAIN, world.pain_point(project))
    jira = _systems(world, project)["Jira"]
    resp = world.client.post(
        _refs_url(project, record), json={"system_id": jira["id"], "key": "P-9"}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    assert [r["key"] for r in resp.json()["references"]] == ["P-9"]


def test_each_change_is_audited_without_the_key_or_link(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    jira = _systems(world, project)["Jira"]
    ref = world.client.post(
        _refs_url(project, record), json={"system_id": jira["id"], "key": "SECRET-123", "url": "https://secret.example/x"},
        headers=auth_headers(world.token),
    ).json()["references"][0]
    world.client.patch(f"{_refs_url(project, record)}/{ref['id']}", json={"note": "n"}, headers=auth_headers(world.token))
    world.client.delete(f"{_refs_url(project, record)}/{ref['id']}", headers=auth_headers(world.token))
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == str(record[1]), AuditEvent.action.like("reference_%"),
        ).order_by(AuditEvent.created_at)))
    assert [e.action for e in events] == ["reference_added", "reference_updated", "reference_removed"]
    assert "SECRET-123" not in json.dumps([e.detail for e in events]) and "secret.example" not in json.dumps([e.detail for e in events])


def test_a_viewer_reads_but_cannot_change_and_a_stranger_sees_nothing(world, client, admin_token):
    project = world.project()
    record = (REQ, world.requirement(project))
    jira = _systems(world, project)["Jira"]
    viewer = _member_token(world, project)
    seen = world.client.get(_refs_url(project, record), headers=auth_headers(viewer))
    assert seen.status_code == 200 and seen.json()["can_edit"] is False
    assert world.client.post(
        _refs_url(project, record), json={"system_id": jira["id"], "key": "P-1"}, headers=auth_headers(viewer),
    ).status_code == 403

    other = World(client, admin_token, "Stranger Org", context_strategy=True)
    assert client.get(_refs_url(project, record), headers=auth_headers(other.token)).status_code in (403, 404)


def test_a_system_of_another_organisation_is_rejected(world, client, admin_token):
    project = world.project()
    record = (REQ, world.requirement(project))
    other = World(client, admin_token, "Foreign Org", context_strategy=True)
    foreign = _by_name(client.get(f"/api/v1/orgs/{other.org['id']}/external-systems", headers=auth_headers(other.token)).json())["Jira"]
    resp = world.client.post(
        _refs_url(project, record), json={"system_id": foreign["id"], "key": "P-1"}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 400, resp.text


def test_a_reference_needs_a_key_or_a_link_and_the_link_must_be_http(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    jira = _systems(world, project)["Jira"]
    for body in ({}, {"key": "  "}, {"url": "javascript:alert(1)", "key": "A"}, {"url": "data:text/html,x"}, {"url": "ftp://x/y"}):
        resp = world.client.post(
            _refs_url(project, record), json={"system_id": jira["id"], **body}, headers=auth_headers(world.token),
        )
        assert resp.status_code == 422, (body, resp.text)
    ref = world.client.post(
        _refs_url(project, record), json={"system_id": jira["id"], "key": "A"}, headers=auth_headers(world.token),
    ).json()["references"][0]
    cleared = world.client.patch(
        f"{_refs_url(project, record)}/{ref['id']}", json={"key": ""}, headers=auth_headers(world.token),
    )
    assert cleared.status_code == 400


def test_an_unregistered_type_and_an_unknown_record_are_not_found(world):
    project = world.project()
    jira = _systems(world, project)["Jira"]
    body = {"system_id": jira["id"], "key": "A"}
    bogus = world.client.post(_refs_url(project, ("nonsense", uuid.uuid4())), json=body, headers=auth_headers(world.token))
    assert bogus.status_code == 404
    missing = world.client.post(_refs_url(project, (REQ, uuid.uuid4())), json=body, headers=auth_headers(world.token))
    assert missing.status_code == 404


def test_a_record_carries_at_most_fifty_references(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    jira = _systems(world, project)["Jira"]
    for i in range(refs.MAX_REFERENCES):
        assert world.client.post(
            _refs_url(project, record), json={"system_id": jira["id"], "key": f"K-{i}"}, headers=auth_headers(world.token),
        ).status_code == 201
    over = world.client.post(
        _refs_url(project, record), json={"system_id": jira["id"], "key": "K-over"}, headers=auth_headers(world.token),
    )
    assert over.status_code == 400


def test_a_stored_link_that_is_not_http_is_never_returned_as_a_link(world):
    """Defence in depth: a template or URL written around the API still cannot become a clickable `javascript:` link."""
    project = world.project()
    record = (REQ, world.requirement(project))
    jira = _by_name(world.client.get(_org(world), headers=auth_headers(world.token)).json())["Jira"]
    world.client.post(
        _refs_url(project, record), json={"system_id": _systems(world, project)["Jira"]["id"], "key": "K-1"},
        headers=auth_headers(world.token),
    )
    with SessionLocal() as db:
        db.get(ExternalSystemDefinition, uuid.UUID(jira["id"])).url_template = "javascript:alert({key})"
        row = db.scalar(select(ExternalReference).where(ExternalReference.artefact_id == record[1]))
        row.url = None
        db.commit()
    [ref] = world.client.get(_refs_url(project, record), headers=auth_headers(world.token)).json()["references"]
    assert ref["link"] is None


def test_the_link_helper_encodes_the_key_and_prefers_the_references_own_url():
    assert refs.link_for(None, TEMPLATE, "a b/c?d#e") == "https://tracker.example/browse/a%20b%2Fc%3Fd%23e"
    assert refs.link_for("https://own.example/1", TEMPLATE, "K") == "https://own.example/1"
    assert refs.link_for(None, None, "K") is None and refs.link_for(None, TEMPLATE, "") is None
    assert refs.link_for("javascript:alert(1)", TEMPLATE, "K") is None


# --- bundles, templates and clean-up ---------------------------------------------------------------------------


def _bundle_import(world: World, bundle: bytes, name: str) -> dict:
    resp = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": name},
        files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_project_bundle_carries_the_projects_systems_and_hidden_defaults(world):
    org_jira = _by_name(world.client.get(_org(world), headers=auth_headers(world.token)).json())["Jira"]
    world.client.patch(f"{_org(world)}/{org_jira['id']}", json={"url_template": TEMPLATE}, headers=auth_headers(world.token))
    source = world.project("Source")
    systems = _systems(world, source)
    world.client.post(_proj(source), json={"name": "Internal", "url_template": "https://int.example/{key}"}, headers=auth_headers(world.token))
    world.client.put(
        f"{_proj(source)}/{systems['Jira']['id']}", json={"name": "Jira Cloud", "url_template": "https://c.example/{key}"},
        headers=auth_headers(world.token),
    )
    world.client.delete(f"{_proj(source)}/{systems['Zendesk']['id']}", headers=auth_headers(world.token))

    export = world.client.get(f"/api/v1/projects/{source['id']}/export", headers=auth_headers(world.token))
    project_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))
    assert project_json["external_systems"]["hidden"] == ["Zendesk"]

    copy = _bundle_import(world, export.content, "Copy")["project"]
    copied = _systems(world, copy)
    assert "Zendesk" not in copied and copied["Internal"]["url_template"] == "https://int.example/{key}"
    assert copied["Jira Cloud"]["url_template"] == "https://c.example/{key}"


def test_a_bundle_template_that_is_not_http_is_dropped(world):
    source = world.project("Source")
    export = world.client.get(f"/api/v1/projects/{source['id']}/export", headers=auth_headers(world.token)).content
    archive = io.BytesIO(export)
    with zipfile.ZipFile(archive) as z:
        files = {n: z.read(n) for n in z.namelist()}
    data = json.loads(files["project.json"])
    data["external_systems"] = {"rows": [
        {"org_type_name": None, "name_override": "Evil", "display_order_override": 9, "is_enabled": True, "url_template": "javascript:alert({key})"},
    ], "hidden": []}
    files["project.json"] = json.dumps(data).encode()
    patched = io.BytesIO()
    with zipfile.ZipFile(patched, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    copy = _bundle_import(world, patched.getvalue(), "Evil copy")["project"]
    assert _systems(world, copy)["Evil"]["url_template"] is None


def test_an_organisation_bundle_carries_the_list_with_its_templates(client, admin_token):
    source = World(client, admin_token, "Bundle Src Org", context_strategy=True)
    created = source.client.post(_org(source), json={"name": "Linear", "url_template": TEMPLATE}, headers=auth_headers(source.token))
    assert created.status_code == 201
    export = client.get(f"/api/v1/orgs/{source.org['id']}/export", headers=auth_headers(source.token)).content
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export)).read("org.json"))
    linear = next(e for e in org_json["external_systems"] if e["name"] == "Linear")
    assert (linear["name"], linear["url_template"]) == ("Linear", TEMPLATE)

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Restored Systems Org"}, files={"file": ("bundle.zip", export, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = imported.json()["organization"]["id"]
    with SessionLocal() as db:
        rows = {r.name: r for r in db.scalars(select(ExternalSystemDefinition).where(ExternalSystemDefinition.organization_id == new_org))}
    assert set(rows) == set(refs.DEFAULT_EXTERNAL_SYSTEMS) | {"Linear"} and rows["Linear"].url_template == TEMPLATE


def test_a_project_made_from_a_template_has_the_templates_systems(world):
    template = world.project("Template")
    world.client.post(_proj(template), json={"name": "Template tool", "url_template": TEMPLATE}, headers=auth_headers(world.token))
    systems = _systems(world, template)
    world.client.delete(f"{_proj(template)}/{systems['GitHub']['id']}", headers=auth_headers(world.token))
    world.client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(world.token))
    created = world.client.post(
        "/api/v1/projects",
        json={"organization_id": world.org["id"], "name": "From template", "summary": "", "template_project_id": template["id"]},
        headers=auth_headers(world.token),
    )
    assert created.status_code == 201, created.text
    copied = _systems(world, created.json())
    assert copied["Template tool"]["url_template"] == TEMPLATE and "GitHub" not in copied


def test_forgetting_a_record_drops_its_references(world):
    project = world.project()
    record = (REQ, world.requirement(project))
    jira = _systems(world, project)["Jira"]
    world.client.post(_refs_url(project, record), json={"system_id": jira["id"], "key": "A"}, headers=auth_headers(world.token))
    with SessionLocal() as db:
        refs.forget_record_references(db, record[0], record[1])
        db.commit()
        assert db.scalar(select(ExternalReference.id).where(ExternalReference.artefact_id == record[1])) is None


# --- the Product Feedback migration ------------------------------------------------------------------------------


def test_the_product_feedback_table_migrates_to_the_shared_one_and_back(world):
    """0204 moves every row of `enhancement_request_external_refs` (id, system, key, link, role, author and the owner
    columns from the request) and the downgrade restores them. The setup goes through the API first (a project row for
    the system only exists once a record used it); the old shape is then seeded with raw SQL in the downgraded window,
    and the schema is always returned to head."""
    from sqlalchemy import text

    from app.database import engine

    project = world.project()
    record = (REQ, world.requirement(project))
    jira = _systems(world, project)["Jira"]
    assert world.client.post(
        _refs_url(project, record), json={"system_id": jira["id"], "key": "SETUP-1"}, headers=auth_headers(world.token),
    ).status_code == 201
    with engine.begin() as conn:
        system_row = conn.execute(text(
            "SELECT id FROM project_external_systems WHERE project_id = :p"
        ), {"p": project["id"]}).scalar_one()
        owner = conn.execute(text("SELECT id FROM users LIMIT 1")).scalar_one()
    request_id, ref_id = uuid.uuid4(), uuid.uuid4()

    cfg = build_alembic_config()
    command.downgrade(cfg, "0203")
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO enhancement_requests (id, created_at, updated_at, scope, organization_id, project_id, creator_id, "
                "is_archived, unique_code) VALUES (:id, now(), now(), 'project', NULL, :p, :u, false, 'ENH-901')"
            ), {"id": request_id, "p": project["id"], "u": owner})
            conn.execute(text(
                "INSERT INTO enhancement_request_external_refs (id, request_id, project_system_id, key, url, role, created_by) "
                "VALUES (:id, :r, :s, 'MIG-1', 'https://m.example/1', 'origin', :u)"
            ), {"id": ref_id, "r": request_id, "s": system_row, "u": owner})
        command.upgrade(cfg, "0204")
        with engine.begin() as conn:
            moved = conn.execute(text(
                "SELECT artefact_type, artefact_id, project_id, org_system_id, project_system_id, key, url, role "
                "FROM external_references WHERE id = :id"
            ), {"id": ref_id}).one()
            assert conn.execute(text("SELECT to_regclass('enhancement_request_external_refs')")).scalar() is None
        assert (moved.artefact_type, moved.artefact_id) == ("enhancement_request", request_id)
        assert str(moved.project_id) == project["id"] and moved.org_system_id is None and moved.project_system_id == system_row
        assert (moved.key, moved.url, moved.role) == ("MIG-1", "https://m.example/1", "origin")

        command.downgrade(cfg, "0203")
        with engine.begin() as conn:
            back = conn.execute(text(
                "SELECT request_id, key, url, role FROM enhancement_request_external_refs WHERE id = :id"
            ), {"id": ref_id}).one()
            assert conn.execute(text("SELECT count(*) FROM external_references WHERE id = :id"), {"id": ref_id}).scalar() == 0
        assert tuple(back) == (request_id, "MIG-1", "https://m.example/1", "origin")
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM external_references WHERE artefact_id = :r"), {"r": request_id})
            conn.execute(text("DELETE FROM enhancement_requests WHERE id = :r"), {"r": request_id})
