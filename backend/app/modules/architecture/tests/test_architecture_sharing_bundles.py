"""Tests for sharing in the bundles: a project's collections and their members travel and their grants never do, a connection
that ends at an element another owner shares travels as a reference and is rebuilt only where the person importing can read
it, a template keeps no connection to a shared element, and the organisation bundle carries organisation-owned elements
and collections (without grants). Every test builds its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import Project
from app.modules.architecture.export import reset_for_template
from app.modules.architecture.models import ArchitectureCollection, ArchitectureCollectionGrant, ArchitectureElement
from app.modules.architecture.tests._helpers import (
    add_member,
    grant,
    make_architect,
    make_collection,
    make_connection,
    make_element,
    make_org_element,
    org_base,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_project


def _export(client, token, project_id) -> tuple[bytes, dict]:
    resp = client.get(f"/api/v1/projects/{project_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content, json.loads(zipfile.ZipFile(io.BytesIO(resp.content)).read("project.json"))


def _import(client, token, org_id, content: bytes, name: str) -> dict:
    resp = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": name},
        files={"file": ("bundle.zip", content, "application/zip")}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_collections_and_members_travel_but_grants_never_do(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch bundle collections")
    consumer = create_project(client, token, org["id"], "Arch bundle collections consumer")
    top = make_element(client, token, owner["id"], "Platform")
    base = project_base(owner["id"])
    collection = make_collection(client, token, base, "Infra", members=[top["id"]])
    grant(client, token, base, collection["id"], project_id=consumer["id"])

    content, data = _export(client, token, owner["id"])
    assert data["architecture_collections"] == [{"name": "Infra", "description": "", "members": [top["unique_code"]]}]

    copy = _import(client, token, org["id"], content, "Arch bundle collections copy")["project"]
    shown = client.get(f"{project_base(copy['id'])}/collections", headers=auth_headers(token)).json()
    assert [(c["name"], c["member_count"], c["grant_count"]) for c in shown] == [("Infra", 1, 0)]
    with SessionLocal() as db:
        copied = db.scalar(select(ArchitectureCollection).where(ArchitectureCollection.project_id == uuid.UUID(copy["id"])))
        assert copied is not None
        assert db.scalar(select(ArchitectureCollectionGrant).where(ArchitectureCollectionGrant.collection_id == copied.id)) is None


def test_a_connection_to_a_shared_element_is_rebuilt_only_where_the_importer_can_read_it(client, admin_token):
    org, owner, token = setup(client, admin_token, "Arch bundle foreign")
    consumer = create_project(client, token, org["id"], "Arch bundle foreign consumer")
    shared = make_element(client, token, owner["id"], "Platform", activate=True)
    local = make_element(client, token, consumer["id"], "Local app")
    base = project_base(owner["id"])
    collection = make_collection(client, token, base, "Infra", members=[shared["id"]])
    grant(client, token, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.bundleforeign@example.com")
    make_connection(client, architect, consumer["id"], local["id"], shared["id"], name="Uses platform")

    content, data = _export(client, token, consumer["id"])
    exported = data["architecture_connections"][0]
    assert exported["target_code"] is None
    assert exported["target_ref"] == {"owner": "project", "owner_code": owner["code"], "code": shared["unique_code"]}
    assert "Platform" not in json.dumps(exported)

    # An administrator can read the element, so the copy keeps the connection to the same shared element.
    copy = _import(client, token, org["id"], content, "Arch bundle foreign copy")
    connections = client.get(f"{project_base(copy['project']['id'])}/connections", headers=auth_headers(token)).json()
    assert [(c["name"], c["target_element_id"], c["target_shared"]) for c in connections] == [("Uses platform", shared["id"], True)]

    # Resolution is per person: a member who can read the element finds it, and after the grant is revoked nobody
    # without access to the owning project does (the import then skips the connection and says so).
    from app.models.user import User
    from app.modules.architecture.export import _resolve_foreign

    member_id, _member_token = add_member(client, token, org["id"], consumer["id"], "arch.bundleforeign3@example.com")
    ref = exported["target_ref"]
    with SessionLocal() as db:
        project, person = db.get(Project, uuid.UUID(consumer["id"])), db.get(User, uuid.UUID(member_id))
        assert project is not None and person is not None
        assert str(_resolve_foreign(db, project, person, ref)) == shared["id"]
    gone = client.get(f"{base}/collections/{collection['id']}", headers=auth_headers(token)).json()["grants"][0]
    client.delete(f"{base}/collections/{collection['id']}/grants/{gone['id']}", headers=auth_headers(token))
    with SessionLocal() as db:
        project, person = db.get(Project, uuid.UUID(consumer["id"])), db.get(User, uuid.UUID(member_id))
        assert project is not None and person is not None
        assert _resolve_foreign(db, project, person, ref) is None
        assert _resolve_foreign(db, project, person, {**ref, "owner_code": "NOPE"}) is None


def test_a_template_drops_connections_to_shared_elements_and_keeps_surviving_members():
    data: dict[str, Any] = {
        "architecture_elements": [{"unique_code": "ELM-001", "name": "A", "status": "active"}],
        "architecture_connections": [
            {"unique_code": "CON-001", "source_code": "ELM-001", "target_code": None,
             "target_ref": {"owner": "project", "owner_code": "INFRA", "code": "ELM-009"}, "status": "active"},
        ],
        "architecture_collections": [{"name": "Infra", "description": "", "members": ["ELM-001", "ELM-002"]}],
        "architecture_links": [],
    }
    reset_for_template(data)
    assert data["architecture_connections"] == []
    assert data["architecture_collections"][0]["members"] == ["ELM-001"]


def test_the_organisation_bundle_carries_organisation_elements_and_collections_without_grants(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch bundle org share")
    parent = make_org_element(client, token, org["id"], "Platform", activate=True, ports=[{"name": "Main"}])
    make_org_element(client, token, org["id"], "Broker", parent_id=parent["id"])
    base = org_base(org["id"])
    collection = make_collection(client, token, base, "Org infra", members=[parent["id"]])
    grant(client, token, base, collection["id"], project_id=project["id"])

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert export.status_code == 200, export.text
    org_json = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))
    assert {e["name"] for e in org_json["architecture_org_elements"]} == {"Platform", "Broker"}
    assert org_json["architecture_org_collections"] == [{"name": "Org infra", "description": "", "members": [parent["unique_code"]]}]

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Arch bundle org share copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        elements = {e.name: e for e in db.scalars(select(ArchitectureElement).where(ArchitectureElement.organization_id == new_org))}
        collections = list(db.scalars(select(ArchitectureCollection).where(ArchitectureCollection.organization_id == new_org)))
        grants = list(db.scalars(select(ArchitectureCollectionGrant).where(
            ArchitectureCollectionGrant.collection_id.in_([c.id for c in collections]),
        )))
    assert set(elements) == {"Platform", "Broker"} and elements["Broker"].parent_id == elements["Platform"].id
    assert [c.name for c in collections] == ["Org infra"] and grants == []
