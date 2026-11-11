"""Tests for the element type and connection type vocabularies: seeding, the module gate, the organisation and
project APIs, hiding and restoring defaults, nested-project fallback and tenant isolation. Every test builds its own
organisation."""

from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.modules.architecture.models import ArchitectureElementType
from app.modules.architecture.service import (
    CONNECTION_TYPES,
    DEFAULT_CONNECTION_TYPES,
    DEFAULT_ELEMENT_TYPES,
    ELEMENT_TYPES,
)
from app.modules.architecture.tests._helpers import (
    add_member,
    enable_module,
    grant_org_role,
    grant_project_role,
    org_base,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project

VOCABULARIES = [
    pytest.param("element-types", DEFAULT_ELEMENT_TYPES, {"shape": "cylinder"}, id="element"),
    pytest.param("connection-types", DEFAULT_CONNECTION_TYPES, {"line_style": "dashed", "directional": False}, id="connection"),
]


def _names(rows) -> list[str]:
    return [r["name"] for r in rows]


@pytest.mark.parametrize(("path", "defaults", "extra"), VOCABULARIES)
def test_new_organisation_is_seeded_with_the_defaults_in_order(client, admin_token, path, defaults, extra):
    org, _project, token = setup(client, admin_token, f"Arch seed {path}")
    rows = client.get(f"{org_base(org['id'])}/{path}", headers=auth_headers(token)).json()
    assert _names(rows) == [d[0] for d in defaults]
    assert all(r["organization_id"] == org["id"] and r["project_id"] is None for r in rows)


def test_a_disabled_module_is_not_found(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch disabled")
    resp = client.get(f"{org_base(org['id'])}/element-types", headers=auth_headers(token))
    assert resp.status_code == 404
    project = create_project(client, token, org["id"], "Arch disabled project")
    assert client.get(f"{project_base(project['id'])}/element-types", headers=auth_headers(token)).status_code == 404


@pytest.mark.parametrize(("path", "defaults", "extra"), VOCABULARIES)
def test_organisation_admin_manages_defaults(client, admin_token, path, defaults, extra):
    org, _project, token = setup(client, admin_token, f"Arch org crud {path}")
    base, h = f"{org_base(org['id'])}/{path}", auth_headers(token)

    created = client.post(base, json={"name": "Radar", "domain": "hardware", "color_light": "#112233", **extra}, headers=h)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["sort_order"] == len(defaults) and row["domain"] == "hardware" and row["color_light"] == "#112233"
    for key, value in extra.items():
        assert row[key] == value

    assert client.post(base, json={"name": "radar"}, headers=h).status_code == 400  # a name clash ignores case

    renamed = client.patch(f"{base}/{row['id']}", json={"name": "Radar unit"}, headers=h)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Radar unit"
    assert client.patch(f"{base}/{row['id']}", json={"name": defaults[0][0]}, headers=h).status_code == 400

    moved = client.post(f"{base}/{row['id']}/move", json={"direction": "up"}, headers=h)
    assert moved.status_code == 200 and moved.json()["sort_order"] == len(defaults) - 1

    assert client.delete(f"{base}/{row['id']}", headers=h).status_code == 204
    assert "Radar unit" not in _names(client.get(base, headers=h).json())


@pytest.mark.parametrize("payload", [
    {"name": "Bad", "color_light": "red"},
    {"name": "Bad", "domain": "marine"},
    {"name": ""},
])
def test_invalid_vocabulary_fields_are_rejected(client, admin_token, payload):
    org, _project, token = setup(client, admin_token, "Arch invalid")
    resp = client.post(f"{org_base(org['id'])}/element-types", json=payload, headers=auth_headers(token))
    assert resp.status_code == 422


def test_a_member_reads_but_cannot_change_the_organisation_defaults(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch org rbac")
    _user_id, member = add_member(client, token, org["id"], project["id"], "arch-org-member@example.com")
    base = f"{org_base(org['id'])}/element-types"
    assert client.get(base, headers=auth_headers(member)).status_code == 200
    assert client.post(base, json={"name": "Nope"}, headers=auth_headers(member)).status_code == 403


def test_the_org_admin_role_grants_the_organisation_defaults(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch org role")
    user_id, member = add_member(client, token, org["id"], project["id"], "arch-org-role@example.com")
    grant_org_role(client, token, org["id"], user_id, "architecture_org_admin")
    resp = client.post(f"{org_base(org['id'])}/element-types", json={"name": "Granted"}, headers=auth_headers(member))
    assert resp.status_code == 201
    # The organisation role does not change a project's own list.
    assert client.post(f"{project_base(project['id'])}/element-types", json={"name": "X"}, headers=auth_headers(member)).status_code == 403


@pytest.mark.parametrize(("path", "defaults", "extra"), VOCABULARIES)
def test_a_project_lists_the_defaults_then_its_own_rows(client, admin_token, path, defaults, extra):
    org, project, token = setup(client, admin_token, f"Arch project list {path}")
    base, h = f"{project_base(project['id'])}/{path}", auth_headers(token)
    assert _names(client.get(base, headers=h).json()) == [d[0] for d in defaults]

    created = client.post(base, json={"name": "Local", **extra}, headers=h)
    assert created.status_code == 201, created.text
    assert created.json()["project_id"] == project["id"] and created.json()["organization_id"] is None
    assert _names(client.get(base, headers=h).json())[-1] == "Local"
    # A name the project already lists, from the organisation, is a clash.
    assert client.post(base, json={"name": defaults[0][0]}, headers=h).status_code == 400
    # The organisation's own list is unchanged.
    assert "Local" not in _names(client.get(f"{org_base(org['id'])}/{path}", headers=h).json())


@pytest.mark.parametrize(("path", "defaults", "extra"), VOCABULARIES)
def test_a_project_hides_and_restores_an_organisation_default(client, admin_token, path, defaults, extra):
    org, project, token = setup(client, admin_token, f"Arch hide {path}")
    base, h = f"{project_base(project['id'])}/{path}", auth_headers(token)
    first = client.get(base, headers=h).json()[0]

    assert client.delete(f"{base}/{first['id']}", headers=h).status_code == 204
    assert first["name"] not in _names(client.get(base, headers=h).json())
    assert first["name"] in _names(client.get(f"{org_base(org['id'])}/{path}", headers=h).json())
    hidden = client.get(f"{base}/hidden", headers=h).json()
    assert [r["name"] for r in hidden] == [first["name"]]

    restored = client.post(f"{base}/restore", json={"org_type_ids": None}, headers=h)
    assert restored.status_code == 200 and [r["name"] for r in restored.json()["restored"]] == [first["name"]]
    assert first["name"] in _names(client.get(base, headers=h).json())
    assert client.get(f"{base}/hidden", headers=h).json() == []


def test_a_hidden_name_can_be_reused_by_a_project_row(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch reuse")
    base, h = f"{project_base(project['id'])}/element-types", auth_headers(token)
    first = client.get(base, headers=h).json()[0]
    client.delete(f"{base}/{first['id']}", headers=h)
    resp = client.post(base, json={"name": first["name"], "shape": "folder"}, headers=h)
    assert resp.status_code == 201 and resp.json()["project_id"] == project["id"]


def test_a_project_row_is_edited_moved_and_deleted_by_its_project_only(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch own rows")
    other = create_project(client, token, org["id"], "Arch own rows other")
    base, h = f"{project_base(project['id'])}/element-types", auth_headers(token)
    a = client.post(base, json={"name": "A"}, headers=h).json()
    b = client.post(base, json={"name": "B"}, headers=h).json()

    assert client.patch(f"{base}/{a['id']}", json={"name": "A2", "shape": "chip"}, headers=h).json()["shape"] == "chip"
    assert client.post(f"{base}/{b['id']}/move", json={"direction": "up"}, headers=h).json()["sort_order"] == 0
    assert _names(client.get(base, headers=h).json())[-2:] == ["B", "A2"]

    # Another project of the same organisation cannot reach the row, nor can an organisation default be edited here.
    other_base = f"{project_base(other['id'])}/element-types"
    assert client.patch(f"{other_base}/{a['id']}", json={"name": "X"}, headers=h).status_code == 404
    org_default = client.get(base, headers=h).json()[0]
    assert client.patch(f"{base}/{org_default['id']}", json={"name": "X"}, headers=h).status_code == 404

    assert client.delete(f"{base}/{a['id']}", headers=h).status_code == 204
    assert "A2" not in _names(client.get(base, headers=h).json())


def test_a_project_member_reads_and_the_admin_role_changes(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch project rbac")
    user_id, member = add_member(client, token, org["id"], project["id"], "arch-proj-member@example.com")
    base = f"{project_base(project['id'])}/element-types"
    assert client.get(base, headers=auth_headers(member)).status_code == 200
    assert client.post(base, json={"name": "Nope"}, headers=auth_headers(member)).status_code == 403
    assert client.get(f"{base}/hidden", headers=auth_headers(member)).status_code == 403

    grant_project_role(client, token, project["id"], user_id, "architecture_admin")
    assert client.post(base, json={"name": "Yes"}, headers=auth_headers(member)).status_code == 201


def test_another_organisations_rows_are_not_found(client, admin_token):
    org_a, _project_a, token_a = setup(client, admin_token, "Arch tenant A")
    org_b, _project_b, token_b = setup(client, admin_token, "Arch tenant B")
    foreign = client.get(f"{org_base(org_b['id'])}/element-types", headers=auth_headers(token_b)).json()[0]
    base = f"{org_base(org_a['id'])}/element-types"
    assert client.patch(f"{base}/{foreign['id']}", json={"name": "X"}, headers=auth_headers(token_a)).status_code == 404
    assert client.delete(f"{base}/{foreign['id']}", headers=auth_headers(token_a)).status_code == 404
    # An organisation admin cannot read another organisation's list at all.
    assert client.get(f"{org_base(org_b['id'])}/element-types", headers=auth_headers(token_a)).status_code in (403, 404)


def test_a_child_project_shows_its_nearest_configured_ancestor(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch nested")
    enable_module(client, token, org["id"])
    parent = create_project(client, token, org["id"], "Arch nested parent", can_be_parent=True)
    h = auth_headers(token)
    parent_base = f"{project_base(parent['id'])}/element-types"
    client.post(parent_base, json={"name": "Parent local"}, headers=h)
    first = client.get(parent_base, headers=h).json()[0]
    client.delete(f"{parent_base}/{first['id']}", headers=h)

    child = create_project(client, token, org["id"], "Arch nested child", parent_project_id=parent["id"])
    child_base = f"{project_base(child['id'])}/element-types"
    inherited = _names(client.get(child_base, headers=h).json())
    assert "Parent local" in inherited and first["name"] not in inherited
    assert client.get(f"{child_base}/hidden", headers=h).json()[0]["name"] == first["name"]

    # The child's first change copies the inherited configuration, so the parent's rows are not edited.
    created = client.post(child_base, json={"name": "Child local"}, headers=h)
    assert created.status_code == 201
    child_names = _names(client.get(child_base, headers=h).json())
    assert "Parent local" in child_names and "Child local" in child_names and first["name"] not in child_names
    parent_names = _names(client.get(parent_base, headers=h).json())
    assert "Child local" not in parent_names and "Parent local" in parent_names

    # A later change in the parent no longer reaches the child.
    parent_local = next(r for r in client.get(parent_base, headers=h).json() if r["name"] == "Parent local")
    client.patch(f"{parent_base}/{parent_local['id']}", json={"name": "Parent renamed"}, headers=h)
    assert "Parent local" in _names(client.get(child_base, headers=h).json())


def test_deleting_a_row_a_record_uses_is_refused(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch in use")
    h = auth_headers(token)
    base = f"{project_base(project['id'])}/element-types"
    local = client.post(base, json={"name": "Used"}, headers=h).json()
    default = client.get(f"{org_base(org['id'])}/element-types", headers=h).json()[0]

    def uses_everything(_db, _row_id) -> bool:
        return True

    ELEMENT_TYPES.usage_checks.append(uses_everything)
    try:
        assert client.delete(f"{base}/{local['id']}", headers=h).status_code == 409
        assert client.delete(f"{org_base(org['id'])}/element-types/{default['id']}", headers=h).status_code == 409
        # Hiding a default is allowed: it stops new use only.
        assert client.delete(f"{base}/{default['id']}", headers=h).status_code == 204
    finally:
        ELEMENT_TYPES.usage_checks.remove(uses_everything)


def test_deleting_an_organisation_default_drops_the_projects_tombstone(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch tombstone")
    h = auth_headers(token)
    base = f"{project_base(project['id'])}/connection-types"
    default = client.get(base, headers=h).json()[0]
    client.delete(f"{base}/{default['id']}", headers=h)
    assert client.delete(f"{org_base(org['id'])}/connection-types/{default['id']}", headers=h).status_code == 204
    assert client.get(f"{base}/hidden", headers=h).json() == []


def test_usable_row_accepts_only_the_projects_effective_rows(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch usable")
    h = auth_headers(token)
    base = f"{project_base(project['id'])}/element-types"
    first = client.get(base, headers=h).json()[0]
    foreign_org, _p, foreign_token = setup(client, admin_token, "Arch usable foreign")
    foreign = client.get(f"{org_base(foreign_org['id'])}/element-types", headers=auth_headers(foreign_token)).json()[0]
    client.delete(f"{base}/{first['id']}", headers=h)

    import uuid

    with SessionLocal() as db:
        project_id, org_id = uuid.UUID(project["id"]), uuid.UUID(org["id"])
        with pytest.raises(ValueError):
            ELEMENT_TYPES.usable_row(db, project_id, org_id, uuid.UUID(first["id"]))  # hidden
        with pytest.raises(ValueError):
            ELEMENT_TYPES.usable_row(db, project_id, org_id, uuid.UUID(foreign["id"]))  # another organisation
        visible = client.get(base, headers=h).json()[0]
        assert ELEMENT_TYPES.usable_row(db, project_id, org_id, uuid.UUID(visible["id"])).name == visible["name"]


def test_the_owner_check_constraint_rejects_a_row_with_two_or_no_owners(client, admin_token):
    import uuid

    from sqlalchemy.exc import IntegrityError

    org, project, _token = setup(client, admin_token, "Arch owner check")
    with SessionLocal() as db:
        db.add(ArchitectureElementType(name="Both", project_id=uuid.UUID(project["id"]), organization_id=uuid.UUID(org["id"])))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(ArchitectureElementType(name="Neither"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_both_vocabularies_register_distinct_suppression_kinds():
    assert ELEMENT_TYPES.kind != CONNECTION_TYPES.kind
    from app.services.definition_suppression import get_registered_definition_kinds

    assert {ELEMENT_TYPES.kind, CONNECTION_TYPES.kind} <= get_registered_definition_kinds()


def test_enabling_the_module_later_still_finds_the_defaults(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch enable later")
    enable_module(client, token, org["id"])
    rows = client.get(f"{org_base(org['id'])}/element-types", headers=auth_headers(token)).json()
    assert len(rows) == len(DEFAULT_ELEMENT_TYPES)


def test_every_vocabulary_change_is_audited(client, admin_token):
    from sqlalchemy import select

    from app.models.audit import AuditEvent

    org, project, token = setup(client, admin_token, "Arch audit")
    h = auth_headers(token)
    base = f"{project_base(project['id'])}/element-types"
    created = client.post(base, json={"name": "Audited"}, headers=h).json()
    first = client.get(base, headers=h).json()[0]
    client.patch(f"{base}/{created['id']}", json={"name": "Audited 2"}, headers=h)
    client.delete(f"{base}/{first['id']}", headers=h)
    client.post(f"{base}/restore", json={"org_type_ids": None}, headers=h)
    client.delete(f"{base}/{created['id']}", headers=h)
    org_row = client.post(f"{org_base(org['id'])}/element-types", json={"name": "Org audited"}, headers=h).json()

    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "architecture_element_type")))
    seen = {(e.entity_id, e.action) for e in events}
    assert (created["id"], "created") in seen and (created["id"], "updated") in seen
    assert (created["id"], "deleted") in seen
    assert (first["id"], "hidden") in seen and (first["id"], "restored") in seen
    assert (org_row["id"], "created") in seen
