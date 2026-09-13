"""Tests for the Compliance Module's Phase 34 traceability links between
core `Requirement`s and `ComplianceRequirement`s (docs/compliance-module-
plan.md Phase 34): create/list/delete, the denormalised display fields
resolved server-side, the reused core requirement-editing permission
(`ProjectRole.PROJECT_MANAGER`/`PROJECT_ADMINISTRATOR`/`STAKEHOLDER` — not
a new compliance-specific role), duplicate rejection, and cross-org
isolation on both the compliance-requirement and link-type sides.

Reuses `test_compliance_standards_api.py`'s standard/version/requirement
helpers and `test_project_compliance_api.py`'s `_project_base`, the same
way `test_compliance_mapping_and_version_impact.py` already does.
"""

from __future__ import annotations

from app.modules.compliance.tests.test_compliance_standards_api import (
    _create_requirement as _create_compliance_requirement,
)
from app.modules.compliance.tests.test_compliance_standards_api import (
    _create_standard,
    _create_version,
)
from app.modules.compliance.tests.test_project_compliance_api import _assign_project_role, _project_base
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)


def _link_types(client, token, org_id):
    resp = client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {lt["forward_name"]: lt["id"] for lt in resp.json()}


def _create_core_requirement(client, token, project_id, component_id, category_id, name="Req"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _traceability_base(project_id, requirement_id) -> str:
    return f"{_project_base(project_id)}/requirements/{requirement_id}/traceability-links"


def _setup(client, admin_token, org_id, *, project_name="Traceability Project"):
    """One project with one core requirement, plus one published-org
    compliance standard/version/requirement in the same organisation.
    Returns (project, core_requirement, standard, version, compliance_requirement)."""
    project = create_project(client, admin_token, org_id, name=project_name)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    core_req = _create_core_requirement(
        client, admin_token, project["id"], component_id, category_id, "Access control requirement"
    )
    standard = _create_standard(client, admin_token, org_id, reference="ISO-TRACE", name="Traceability Test Standard")
    version = _create_version(client, admin_token, org_id, standard["id"], version_label="2.0")
    creq = _create_compliance_requirement(
        client, admin_token, org_id, standard["id"], version["id"],
        name="Logical access control", reference="A.5.15",
    )
    return project, core_req, standard, version, creq


def test_create_and_list_traceability_link(client, admin_token, org_id):
    project, core_req, standard, _version, creq = _setup(client, admin_token, org_id)
    link_types = _link_types(client, admin_token, org_id)

    created = client.post(
        _traceability_base(project["id"], core_req["id"]),
        json={"compliance_requirement_id": creq["id"], "link_type_id": link_types["Derives from"]},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["requirement_id"] == core_req["id"]
    assert body["compliance_requirement_id"] == creq["id"]
    assert body["display_name"] == "Derives from"
    assert body["compliance_requirement_reference"] == "A.5.15"
    assert body["compliance_requirement_name"] == "Logical access control"
    assert body["standard_id"] == standard["id"]
    assert body["standard_reference"] == "ISO-TRACE"

    listed = client.get(_traceability_base(project["id"], core_req["id"]), headers=auth_headers(admin_token))
    assert listed.status_code == 200, listed.text
    assert [link["id"] for link in listed.json()] == [body["id"]]

    # The exact same (requirement, compliance requirement, link type) triple twice is rejected.
    dup = client.post(
        _traceability_base(project["id"], core_req["id"]),
        json={"compliance_requirement_id": creq["id"], "link_type_id": link_types["Derives from"]},
        headers=auth_headers(admin_token),
    )
    assert dup.status_code == 400


def test_delete_traceability_link(client, admin_token, org_id):
    project, core_req, _standard, _version, creq = _setup(client, admin_token, org_id)
    link_types = _link_types(client, admin_token, org_id)

    created = client.post(
        _traceability_base(project["id"], core_req["id"]),
        json={"compliance_requirement_id": creq["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.delete(
        f"{_traceability_base(project['id'], core_req['id'])}/{created['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text
    assert client.get(_traceability_base(project["id"], core_req["id"]), headers=auth_headers(admin_token)).json() == []

    # Deleting an already-deleted (or never-existing) link 404s.
    missing = client.delete(
        f"{_traceability_base(project['id'], core_req['id'])}/{created['id']}", headers=auth_headers(admin_token)
    )
    assert missing.status_code == 404


def test_create_and_delete_require_core_requirement_edit_role_not_compliance_officer(client, admin_token, org_id):
    """§ Phase 34's own scope note: this reuses whatever permission already
    gates editing a core requirement's own links (`ProjectRole.
    PROJECT_MANAGER`/`PROJECT_ADMINISTRATOR`/`STAKEHOLDER`), not a new,
    compliance-specific permission — a plain project `MEMBER` (view-only)
    is rejected even though they can see the project and the module."""
    project, core_req, _standard, _version, creq = _setup(client, admin_token, org_id)
    link_types = _link_types(client, admin_token, org_id)

    member_id = create_org_user(client, admin_token, org_id, "trace.viewer@example.com", role="member")
    _assign_project_role(client, admin_token, project["id"], member_id, "member")
    member_token = login(client, "trace.viewer@example.com", "Password123!")

    forbidden_create = client.post(
        _traceability_base(project["id"], core_req["id"]),
        json={"compliance_requirement_id": creq["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(member_token),
    )
    assert forbidden_create.status_code == 403

    created = client.post(
        _traceability_base(project["id"], core_req["id"]),
        json={"compliance_requirement_id": creq["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(admin_token),
    ).json()

    # The same view-only member can still read the link (project view, not edit, gates GET).
    listed = client.get(_traceability_base(project["id"], core_req["id"]), headers=auth_headers(member_token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    forbidden_delete = client.delete(
        f"{_traceability_base(project['id'], core_req['id'])}/{created['id']}", headers=auth_headers(member_token)
    )
    assert forbidden_delete.status_code == 403


def test_cannot_link_to_a_compliance_requirement_from_another_org(client, admin_token, org_id):
    project, core_req, _standard, _version, _creq = _setup(client, admin_token, org_id)
    link_types = _link_types(client, admin_token, org_id)

    other_org, other_token = create_org_admin_in(client, admin_token, "Traceability Other Org")
    other_standard = _create_standard(client, other_token, other_org["id"], reference="OTHER-ORG-STD")
    other_version = _create_version(client, other_token, other_org["id"], other_standard["id"], version_label="2.0")
    other_creq = _create_compliance_requirement(
        client, other_token, other_org["id"], other_standard["id"], other_version["id"], name="Not this org's requirement",
    )

    resp = client.post(
        _traceability_base(project["id"], core_req["id"]),
        json={"compliance_requirement_id": other_creq["id"], "link_type_id": link_types["Related to"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_cannot_use_a_link_type_from_another_org(client, admin_token, org_id):
    project, core_req, _standard, _version, creq = _setup(client, admin_token, org_id)

    other_org, other_token = create_org_admin_in(client, admin_token, "Traceability Link Type Org")
    other_org_link_type_id = _link_types(client, other_token, other_org["id"])["Related to"]

    resp = client.post(
        _traceability_base(project["id"], core_req["id"]),
        json={"compliance_requirement_id": creq["id"], "link_type_id": other_org_link_type_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_cannot_create_link_via_a_requirement_in_another_project(client, admin_token, org_id):
    project, core_req, _standard, _version, creq = _setup(client, admin_token, org_id)
    other_project = create_project(client, admin_token, org_id, name="Traceability Other Project")

    resp = client.post(
        _traceability_base(other_project["id"], core_req["id"]),
        json={"compliance_requirement_id": creq["id"], "link_type_id": _link_types(client, admin_token, org_id)["Related to"]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404
