"""Tests for groups as Persona / Stakeholder / Need owners and Persona champions
(users and groups on parity).

Covers: each principal kind on create, update and clear; the display fields of a
group; an organisation-scoped record rejecting a project group while a project
record accepts only its own project's group; cross-organisation rejection;
versions carrying the owner so history shows who owned each version; deleting a
group that owns records (usage counts current versions only, blocked, reassigned,
cleared, the audit event names the record, older versions keep a deleted group);
project and organisation bundle round trips (a group matched by name, an
unmatched one left empty with a warning, a bundle from before groups restored);
and the migration backfilling existing rows to `user`.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select, text

from alembic import command
from app.database import SessionLocal, engine
from app.models.audit import AuditEvent
from app.modules.stakeholders.models import Persona, PersonaVersion
from app.modules.stakeholders.service import get_current_persona_version
from app.modules.stakeholders.tests.test_need_api import _create_need, _needs
from app.modules.stakeholders.tests.test_persona_api import (
    _create_org_persona,
    _create_project_persona,
    _org_base,
    _project_base,
    _setup,
)
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from tests.conftest import (
    auth_headers,
    build_alembic_config,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
)


def _user(user_id) -> dict:
    return {"type": "user", "id": str(user_id)}


def _me(client, token) -> str:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


# --- Create, update, clear: each principal kind ---------------------------------------------------


def test_each_artefact_takes_each_principal_kind_and_shows_a_group_by_name(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Kinds Co")
    member = create_org_user(client, token, org["id"], "kinds_member@sp.example.com")
    team = create_org_group(client, token, org["id"], "Platform Team", users=[member])
    squad = create_project_group(client, token, project["id"], "Squad", users=[member])

    persona = _create_project_persona(
        client, token, project["id"], owner={"type": "org_group", "id": team}, champion={"type": "project_group", "id": squad},
    )
    assert persona["owner"] == {"type": "org_group", "id": team, "label": "Platform Team", "member_count": 1, "exists": True}
    assert persona["champion"]["label"] == "Squad" and persona["champion"]["type"] == "project_group"

    stakeholder = _create_project_stakeholder(client, token, project["id"], owner={"type": "project_group", "id": squad})
    assert stakeholder["owner"]["label"] == "Squad"
    need = _create_need(client, token, project["id"], owner={"type": "org_group", "id": team})
    assert need["owner"]["label"] == "Platform Team"
    by_user = _create_project_persona(client, token, project["id"], name="By user", owner=_user(member))
    assert by_user["owner"]["type"] == "user" and by_user["champion"] is None

    h = auth_headers(token)
    listed = {p["id"]: p for p in client.get(_project_base(project["id"]) + "/personas", headers=h).json()}
    assert listed[persona["id"]]["owner"]["label"] == "Platform Team"
    assert listed[by_user["id"]]["owner"]["id"] == member
    assert client.get(_project_base(project["id"]) + "/stakeholders", headers=h).json()[0]["owner"]["label"] == "Squad"
    assert client.get(_needs(project["id"]), headers=h).json()[0]["owner"]["label"] == "Platform Team"


def test_update_switches_and_clears_principals_and_versions_keep_each_owner(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Update Co")
    me = _me(client, token)
    team = create_org_group(client, token, org["id"], "Owners")
    persona = _create_project_persona(client, token, project["id"], owner=_user(me), champion=_user(me))
    url = f"{_project_base(project['id'])}/personas/{persona['id']}"
    h = auth_headers(token)

    switched = client.put(url, json={"owner": {"type": "org_group", "id": team}}, headers=h)
    assert switched.status_code == 200, switched.text
    assert switched.json()["owner"]["label"] == "Owners" and switched.json()["champion"]["id"] == me  # untouched

    renamed = client.put(url, json={"goals": "More goals"}, headers=h).json()
    assert renamed["owner"]["id"] == team, "an unrelated edit carries the group owner forward"

    cleared = client.put(url, json={"owner": None, "champion": None}, headers=h).json()
    assert cleared["owner"] is None and cleared["champion"] is None

    versions = client.get(url + "/versions", headers=h).json()
    assert [(v["owner"] or {}).get("type") for v in versions] == ["user", "org_group", "org_group", None]
    assert versions[1]["owner"]["label"] == "Owners"

    # A response is a valid request body (the extra display fields on the principal are ignored).
    again = client.put(url, json={"owner": switched.json()["owner"]}, headers=h)
    assert again.status_code == 200 and again.json()["owner"]["id"] == team


def test_stakeholder_and_need_versions_show_group_owners(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Versions Co")
    team = create_org_group(client, token, org["id"], "Version Team")
    h = auth_headers(token)
    stakeholder = _create_project_stakeholder(client, token, project["id"], owner={"type": "org_group", "id": team})
    client.put(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}", json={"role": "Sponsor"}, headers=h)
    history = client.get(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}/versions", headers=h).json()
    assert [v["owner"]["label"] for v in history] == ["Version Team", "Version Team"]

    need = _create_need(client, token, project["id"], owner={"type": "org_group", "id": team})
    client.put(f"{_needs(project['id'])}/{need['id']}", json={"rationale": "Refined"}, headers=h)
    need_history = client.get(f"{_needs(project['id'])}/{need['id']}/versions", headers=h).json()
    assert [v["owner"]["type"] for v in need_history] == ["org_group", "org_group"]


# --- Validation ------------------------------------------------------------------------------------


def test_foreign_and_wrong_scope_principals_are_rejected(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Reject Co")
    other_project = create_project(client, token, org["id"], "Other Project")
    elsewhere = create_project_group(client, token, other_project["id"], "Elsewhere")
    own = create_project_group(client, token, project["id"], "Own Squad")
    other_org, other_token = create_org_admin_in(client, admin_token, "Stakeholder Principal Foreign Co")
    foreign_group = create_org_group(client, other_token, other_org["id"], "Foreign Team")
    foreign_user = create_org_user(client, other_token, other_org["id"], "foreign_owner@sp.example.com")
    h = auth_headers(token)

    for bad in (
        {"type": "org_group", "id": foreign_group}, {"type": "user", "id": foreign_user},
        {"type": "project_group", "id": elsewhere}, {"type": "org_group", "id": str(uuid.uuid4())},
    ):
        for url, payload in (
            (_project_base(project["id"]) + "/personas", {"name": "P"}),
            (_project_base(project["id"]) + "/stakeholders", {"name": "S"}),
            (_needs(project["id"]), {"name": "N"}),
        ):
            assert client.post(url, json={**payload, "owner": bad}, headers=h).status_code == 400, (url, bad)
        assert client.post(
            _project_base(project["id"]) + "/personas", json={"name": "P", "champion": bad}, headers=h,
        ).status_code == 400

    # An organisation-scoped record is shared by every project, so it cannot name a project group.
    org_url = _org_base(org["id"])
    project_group_owner = {"type": "project_group", "id": own}
    assert client.post(org_url + "/personas", json={"name": "P", "owner": project_group_owner}, headers=h).status_code == 400
    assert client.post(org_url + "/stakeholders", json={"name": "S", "owner": project_group_owner}, headers=h).status_code == 400
    good = _create_org_persona(client, token, org["id"], owner={"type": "org_group", "id": create_org_group(client, token, org["id"], "Org Wide")})
    assert client.put(
        f"{org_url}/personas/{good['id']}", json={"owner": project_group_owner}, headers=h,
    ).status_code == 400
    assert client.post(_project_base(project["id"]) + "/personas", json={"name": "P", "owner": project_group_owner}, headers=h).status_code == 201


# --- Deleting a group that owns records -------------------------------------------------------------


def test_deleting_an_owner_group_counts_current_versions_blocks_reassigns_and_audits_the_record(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Delete Co")
    me = _me(client, token)
    team = create_org_group(client, token, org["id"], "Doomed Team")
    h = auth_headers(token)
    persona = _create_project_persona(
        client, token, project["id"], owner={"type": "org_group", "id": team}, champion={"type": "org_group", "id": team},
    )
    url = f"{_project_base(project['id'])}/personas/{persona['id']}"
    client.put(url, json={"owner": _user(me)}, headers=h)  # version 1 keeps the group, version 2 does not
    client.put(url, json={"owner": {"type": "org_group", "id": team}}, headers=h)  # version 3 names it again
    stakeholder = _create_org_stakeholder(client, token, org["id"], owner={"type": "org_group", "id": team})
    need = _create_need(client, token, project["id"], owner={"type": "org_group", "id": team})
    group_url = f"/api/v1/orgs/{org['id']}/groups/{team}"

    usage = client.get(f"{group_url}/usage", headers=h).json()
    assert {(i["label"], i["count"], i["mandatory"]) for i in usage["items"]} == {
        ("persona owners", 1, False), ("persona champions", 1, False),
        ("stakeholder owners", 1, False), ("stakeholder need owners", 1, False),
    }, "older versions are not counted"
    assert usage["total"] == 4 and usage["mandatory_total"] == 0

    assert client.delete(group_url, headers=h).status_code == 409
    done = client.delete(group_url, params={"replacement_type": "user", "replacement_id": me}, headers=h)
    assert done.status_code == 204, done.text

    after = client.get(url, headers=h).json()
    assert after["owner"]["id"] == me and after["champion"]["id"] == me
    assert client.get(f"{_org_base(org['id'])}/stakeholders/{stakeholder['id']}", headers=h).json()["owner"]["id"] == me
    assert client.get(f"{_needs(project['id'])}/{need['id']}", headers=h).json()["owner"]["id"] == me

    history = client.get(url + "/versions", headers=h).json()
    assert history[0]["owner"]["label"] == "Deleted group" and history[0]["owner"]["exists"] is False

    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "principal_reassigned")).all()
        assert {str(e.entity_id) for e in events} >= {persona["id"], stakeholder["id"], need["id"]}


def test_clear_optional_empties_owners_and_a_project_group_can_be_replaced(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Clear Co")
    h = auth_headers(token)
    team = create_org_group(client, token, org["id"], "Clear Team")
    persona = _create_project_persona(client, token, project["id"], owner={"type": "org_group", "id": team})
    resp = client.delete(f"/api/v1/orgs/{org['id']}/groups/{team}", params={"clear_optional": "true"}, headers=h)
    assert resp.status_code == 204, resp.text
    assert client.get(f"{_project_base(project['id'])}/personas/{persona['id']}", headers=h).json()["owner"] is None

    squad = create_project_group(client, token, project["id"], "Doomed Squad")
    stakeholder = _create_project_stakeholder(client, token, project["id"], owner={"type": "project_group", "id": squad})
    successor = create_org_group(client, token, org["id"], "Successor")
    url = f"/api/v1/projects/{project['id']}/groups/{squad}"
    assert client.delete(url, headers=h).status_code == 409
    done = client.delete(url, params={"replacement_type": "org_group", "replacement_id": successor}, headers=h)
    assert done.status_code == 204, done.text
    owner = client.get(f"{_project_base(project['id'])}/stakeholders/{stakeholder['id']}", headers=h).json()["owner"]
    assert owner["type"] == "org_group" and owner["id"] == successor


# --- Bundles -----------------------------------------------------------------------------------------


def _export(client, token, url) -> bytes:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _rewrite(content: bytes, member: str, mutate) -> bytes:
    """The bundle `content` with the JSON file `member` passed through `mutate(data)` (edited in place)."""
    archive = zipfile.ZipFile(io.BytesIO(content))
    data = json.loads(archive.read(member))
    mutate(data)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as rewritten:
        for item in archive.infolist():
            rewritten.writestr(item, json.dumps(data) if item.filename == member else archive.read(item.filename))
    return out.getvalue()


def test_project_bundle_matches_groups_by_name_and_warns_when_a_group_is_missing(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Bundle Co")
    h = auth_headers(token)
    me = _me(client, token)
    team = create_org_group(client, token, org["id"], "Bundle Team")
    squad = create_project_group(client, token, project["id"], "Bundle Squad")
    _create_project_persona(
        client, token, project["id"], name="Round trip",
        owner={"type": "org_group", "id": team}, champion={"type": "project_group", "id": squad},
    )
    _create_project_stakeholder(client, token, project["id"], name="Round trip S", owner=_user(me))
    _create_need(client, token, project["id"], name="Round trip N", owner={"type": "org_group", "id": team})

    content = _export(client, token, f"/api/v1/projects/{project['id']}/export")
    bundle = json.loads(zipfile.ZipFile(io.BytesIO(content)).read("project.json"))
    assert bundle["project_personas"][0]["owner"] == {"type": "org_group", "name": "Bundle Team"}
    assert bundle["project_personas"][0]["champion"] == {"type": "project_group", "name": "Bundle Squad"}
    assert bundle["project_stakeholders"][0]["owner"]["email"]

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Principal Reimported"},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    new_base = _project_base(imported.json()["project"]["id"])
    persona = client.get(new_base + "/personas?include_org=false", headers=h).json()[0]
    assert persona["owner"]["label"] == "Bundle Team", "the org group is matched by name"
    assert persona["champion"]["label"] == "Bundle Squad" and persona["champion"]["id"] != squad, "the new project's own group"
    assert client.get(new_base + "/stakeholders?include_org=false", headers=h).json()[0]["owner"]["id"] == me
    assert client.get(new_base + "/needs", headers=h).json()[0]["owner"]["label"] == "Bundle Team"

    def rename_groups(data):
        for record in (*data["project_personas"], *data["project_stakeholder_needs"]):
            for field in ("owner", "champion"):
                if record.get(field) and "name" in record[field]:
                    record[field]["name"] = "No Such Group"

    missing = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Principal Missing Group"},
        files={"file": ("bundle.zip", _rewrite(content, "project.json", rename_groups), "application/zip")}, headers=h,
    )
    assert missing.status_code == 201, missing.text
    warnings = missing.json()["warnings"]
    assert any("Persona 'Round trip' owner" in w and "left unset" in w for w in warnings)
    assert any("Persona 'Round trip' champion" in w for w in warnings)
    assert any("Stakeholder Need 'Round trip N' owner" in w for w in warnings)
    unset = client.get(_project_base(missing.json()["project"]["id"]) + "/personas?include_org=false", headers=h).json()[0]
    assert unset["owner"] is None and unset["champion"] is None


def test_org_bundle_leaves_an_unmatched_group_empty_with_a_warning(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Org Bundle Co")
    team = create_org_group(client, token, org["id"], "Source Only Team")
    _create_org_persona(client, token, org["id"], name="Org owned", owner={"type": "org_group", "id": team})
    content = _export(client, token, f"/api/v1/orgs/{org['id']}/export")

    def import_as(name: str, bundle: bytes) -> dict:
        resp = client.post(
            "/api/v1/orgs/import", data={"name": name},
            files={"file": ("bundle.zip", bundle, "application/zip")}, headers=auth_headers(admin_token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def owner_of(imported: dict):
        with SessionLocal() as db:
            persona = db.scalars(select(Persona).where(Persona.organization_id == uuid.UUID(imported["organization"]["id"]))).one()
            return get_current_persona_version(db, persona.id)

    matched = import_as("Principal Org Reimport", content)
    assert owner_of(matched).owner_type == "org_group", "the org's groups travel with it, so the name matches"

    def rename_group(data):
        data["personas"][0]["owner"]["name"] = "No Such Group"

    unmatched = import_as("Principal Org Reimport Missing", _rewrite(content, "org.json", rename_group))
    assert any("Persona 'Org owned' owner" in w and "left unset" in w for w in unmatched["warnings"])
    version = owner_of(unmatched)
    assert version.owner_type is None and version.owner_id is None


def test_a_bundle_written_before_groups_existed_still_restores_its_user_owner(client, admin_token):
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Legacy Bundle Co")
    h = auth_headers(token)
    email = client.get("/api/v1/auth/me", headers=h).json()["email"]
    _create_project_persona(client, token, project["id"], name="Legacy", owner=_user(_me(client, token)))
    content = _export(client, token, f"/api/v1/projects/{project['id']}/export")

    def to_legacy_shape(data):
        persona = data["project_personas"][0]
        persona.pop("owner")
        persona.pop("champion")
        persona["owner_email"] = email

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Legacy Reimported"},
        files={"file": ("bundle.zip", _rewrite(content, "project.json", to_legacy_shape), "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    restored = client.get(_project_base(imported.json()["project"]["id"]) + "/personas?include_org=false", headers=h).json()[0]
    assert restored["owner"]["type"] == "user" and restored["owner"]["id"] == _me(client, token)


# --- Migration backfill --------------------------------------------------------------------------------


def test_migration_backfills_existing_versions_to_user(client, admin_token):
    """Runs the real 0077 migration: a persona version written in the pre-migration shape (no `*_type`
    columns) ends up with `user` for its owner and champion, and a null stays null."""
    org, project, token = _setup(client, admin_token, "Stakeholder Principal Migration Co")
    me = _me(client, token)
    persona = _create_project_persona(client, token, project["id"], name="Legacy")
    version_id = uuid.uuid4()
    command.downgrade(build_alembic_config(), "0076")
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE persona_versions SET valid_to = now() WHERE persona_id = :p AND valid_to IS NULL"), {"p": persona["id"]})
            conn.execute(
                text(
                    "INSERT INTO persona_versions (id, persona_id, version_number, valid_from, name, description, role_title, "
                    "goals, needs, behaviours, context_environment, skills_proficiency, frequency_of_use, constraints, status, "
                    "owner_id, change_note, created_by, created_at) VALUES (:id, :p, 2, now(), 'Legacy', '', '', '', '', '', "
                    "'', '', '', '', 'draft', :me, '', :me, now())"
                ),
                {"id": version_id, "p": persona["id"], "me": me},
            )
    finally:
        command.upgrade(build_alembic_config(), "head")

    with SessionLocal() as db:
        row = db.get(PersonaVersion, version_id)
        assert (row.owner_type, str(row.owner_id)) == ("user", me)
        assert row.champion_type is None and row.champion_id is None
    resp = client.get(f"{_project_base(project['id'])}/personas/{persona['id']}", headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["owner"]["id"] == me
