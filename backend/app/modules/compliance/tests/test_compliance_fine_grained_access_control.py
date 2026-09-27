"""Tests for the Compliance Module's Fine-Grained Access Control Phase 6
(docs/plans/core-fine-grained-access-control-plan.md): the `permissions`
declared on all four of this module's `ModuleRoleDefinition`s
(`compliance_manager`, `compliance_officer`, `standards_manager`,
`standards_contributor`, `module.py`), and the two endpoints migrated to
accept `require_permission` as an alternative to their existing
`require_module_role` gate — `create_evidence`/`update_evidence`
(`project_router/evidence.py`, the org/project composition axis) and
`update_requirement` (`router/version_requirements.py`, the entity-scoped
`"standard"` axis).

Regression coverage first (no new grant — every existing role's access to
these three endpoints must be unaffected by this phase), then the two new
capability proofs the plan's own Phase 6 scope names explicitly: a plain
custom role reaching the evidence endpoints without ever holding
`compliance_officer`, and an entity-scoped (`"standard"`) custom role
reaching `update_requirement` without ever holding `standards_manager`/
`standards_contributor`.

Reuses existing helpers from `test_compliance_standards_api.py` (plain
standard/version/requirement CRUD), `test_compliance_standard_scoped_
rbac.py` (`compliance_manager`/standard-scoped role grants), and
`test_project_compliance_api.py`/`test_compliance_evidence_api.py`
(project assignment/assessment + evidence setup), the same way those files
already reuse each other."""

from __future__ import annotations

from app.modules.compliance.service import (
    COMPLIANCE_EVIDENCE_MANAGE_PERMISSION,
    COMPLIANCE_STANDARD_CONTENT_MANAGE_PERMISSION,
)
from app.modules.compliance.tests.test_compliance_evidence_api import _setup_project_with_assessment
from app.modules.compliance.tests.test_compliance_standard_scoped_rbac import _grant_standard_role
from app.modules.compliance.tests.test_compliance_standards_api import (
    _base,
    _create_requirement,
    _create_standard,
    _create_version,
    _grant_compliance_manager,
)
from app.modules.compliance.tests.test_project_compliance_api import _grant_compliance_officer, _project_base
from tests.conftest import auth_headers, create_org_user, login


def _create_custom_role(client, admin_token, org_id, *, name, scope, permissions):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/custom-roles",
        json={"name": name, "description": "", "scope": scope, "permissions": permissions},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _grant_custom_role_to_user(client, admin_token, org_id, role_id, user_id, *, project_id=None, scope_entity_id=None):
    resp = client.post(
        f"/api/v1/orgs/{org_id}/custom-roles/{role_id}/users/{user_id}",
        json={"project_id": project_id, "scope_entity_id": scope_entity_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


# --- Regression: every existing role's access is unaffected ----------------


def test_evidence_create_update_regression_officer_and_plain_member(client, admin_token, org_id):
    """`create_evidence`/`update_evidence` still gate on `compliance_officer`
    exactly as before this phase (the `_require_officer` branch of
    `_require_evidence_manage` is tried first and succeeds outright for an
    officer), and a plain org member with no compliance role and no new
    permission grant still gets 403 on both — proving the additive
    `require_permission` fallback never *widens* access for a caller with
    nothing to fall back on."""
    project, _assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="FGAC Evidence Regression Project"
    )

    officer_id = create_org_user(client, admin_token, org_id, "fgac.officer@example.com", role="member")
    _grant_compliance_officer(client, admin_token, project["id"], officer_id)
    officer_token = login(client, "fgac.officer@example.com", "Password123!")

    created = client.post(
        f"{_project_base(project['id'])}/evidence", json={"title": "Regression Evidence"},
        headers=auth_headers(officer_token),
    )
    assert created.status_code == 201, created.text
    evidence_id = created.json()["id"]

    updated = client.patch(
        f"{_project_base(project['id'])}/evidence/{evidence_id}",
        json={"title": "Regression Evidence (updated)", "description": "", "issuing_organisation": None, "notes": ""},
        headers=auth_headers(officer_token),
    )
    assert updated.status_code == 200, updated.text

    create_org_user(client, admin_token, org_id, "fgac.plainmember@example.com", role="member")
    plain_token = login(client, "fgac.plainmember@example.com", "Password123!")
    forbidden_create = client.post(
        f"{_project_base(project['id'])}/evidence", json={"title": "Should Not Be Created"},
        headers=auth_headers(plain_token),
    )
    assert forbidden_create.status_code == 403
    forbidden_update = client.patch(
        f"{_project_base(project['id'])}/evidence/{evidence_id}",
        json={"title": "Should Not Update", "description": "", "issuing_organisation": None, "notes": ""},
        headers=auth_headers(plain_token),
    )
    assert forbidden_update.status_code == 403


def test_update_requirement_regression_standard_roles_and_plain_member(client, admin_token, org_id):
    """`update_requirement` still gates on `standards_manager`/`standards_
    contributor` (or org-wide `compliance_manager`, via `overridden_by`)
    exactly as before, and a plain org member still gets 403 — the
    entity-scoped-axis counterpart of the evidence regression test above."""
    standard = _create_standard(client, admin_token, org_id, reference="FGAC-REG-1", name="FGAC Regression Standard")
    version = _create_version(client, admin_token, org_id, standard["id"])
    requirement = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="Original Name")

    contributor_id = create_org_user(client, admin_token, org_id, "fgac.contributor@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], contributor_id, "standards_contributor")
    contributor_token = login(client, "fgac.contributor@example.com", "Password123!")

    updated = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        json={"reference": None, "name": "Updated By Contributor", "description": "", "reasoning": ""},
        headers=auth_headers(contributor_token),
    )
    assert updated.status_code == 200, updated.text

    create_org_user(client, admin_token, org_id, "fgac.plainmember2@example.com", role="member")
    plain_token = login(client, "fgac.plainmember2@example.com", "Password123!")
    forbidden = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        json={"reference": None, "name": "Should Not Update", "description": "", "reasoning": ""},
        headers=auth_headers(plain_token),
    )
    assert forbidden.status_code == 403

    # Org-wide `compliance_manager` still overrides the standard-scoped
    # check too (`overridden_by=(("org", "compliance_manager"),)`, unrelated
    # to this phase but exercised through the new combinator's first,
    # role-based branch, not the `require_permission` fallback).
    manager_id = create_org_user(client, admin_token, org_id, "fgac.manager@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "fgac.manager@example.com", "Password123!")
    updated_by_manager = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        json={"reference": None, "name": "Updated By Compliance Manager", "description": "", "reasoning": ""},
        headers=auth_headers(manager_token),
    )
    assert updated_by_manager.status_code == 200, updated_by_manager.text


# --- New capability: a plain permission-scoped custom role ------------------


def test_evidence_manage_permission_custom_role_reaches_create_and_update_without_officer_role(
    client, admin_token, org_id
):
    """The concrete new capability this phase's org/project-axis migration
    adds: a custom role granting only `(compliance_evidence, manage)`
    (no `compliance_officer` module role at all) reaches `create_evidence`/
    `update_evidence`."""
    project, _assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="FGAC Evidence Custom Role Project"
    )
    grantee_id = create_org_user(client, admin_token, org_id, "fgac.evidence.custom@example.com", role="member")
    grantee_token = login(client, "fgac.evidence.custom@example.com", "Password123!")

    forbidden = client.post(
        f"{_project_base(project['id'])}/evidence", json={"title": "Not Yet Permitted"},
        headers=auth_headers(grantee_token),
    )
    assert forbidden.status_code == 403

    role = _create_custom_role(
        client, admin_token, org_id, name="Evidence Manager (custom)", scope="project",
        permissions=[COMPLIANCE_EVIDENCE_MANAGE_PERMISSION],
    )
    _grant_custom_role_to_user(client, admin_token, org_id, role["id"], grantee_id, project_id=project["id"])

    created = client.post(
        f"{_project_base(project['id'])}/evidence", json={"title": "Permitted By Custom Role"},
        headers=auth_headers(grantee_token),
    )
    assert created.status_code == 201, created.text
    evidence_id = created.json()["id"]

    updated = client.patch(
        f"{_project_base(project['id'])}/evidence/{evidence_id}",
        json={"title": "Updated By Custom Role", "description": "", "issuing_organisation": None, "notes": ""},
        headers=auth_headers(grantee_token),
    )
    assert updated.status_code == 200, updated.text


def test_evidence_manage_permission_check_still_404s_when_module_disabled(client, admin_token, org_id):
    """The subtle edge Fine-Grained Access Control Phase 4 flagged: a
    caller who only reaches this endpoint via the new `require_permission`
    fallback (never `compliance_officer`) must still 404, not succeed or
    403, once the module is disabled — `_require_evidence_manage` tries
    `_require_officer` first, which performs its own module-enabled check
    before ever falling back to the permission atom, so the disabled-module
    404 is never bypassed by holding the new grant."""
    project, _assignment, _pcr_id, _assessment_id = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="FGAC Evidence Disabled Module Project"
    )
    grantee_id = create_org_user(client, admin_token, org_id, "fgac.evidence.disabled@example.com", role="member")
    grantee_token = login(client, "fgac.evidence.disabled@example.com", "Password123!")
    role = _create_custom_role(
        client, admin_token, org_id, name="Evidence Manager (disabled module)", scope="project",
        permissions=[COMPLIANCE_EVIDENCE_MANAGE_PERMISSION],
    )
    _grant_custom_role_to_user(client, admin_token, org_id, role["id"], grantee_id, project_id=project["id"])

    disable_resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/compliance", json={"enabled": False}, headers=auth_headers(admin_token)
    )
    assert disable_resp.status_code == 200, disable_resp.text
    try:
        resp = client.post(
            f"{_project_base(project['id'])}/evidence", json={"title": "Should 404"},
            headers=auth_headers(grantee_token),
        )
        assert resp.status_code == 404
    finally:
        client.put(f"/api/v1/orgs/{org_id}/modules/compliance", json={"enabled": True}, headers=auth_headers(admin_token))


# --- New capability: an entity-scoped ("standard") custom role -------------


def test_standard_content_manage_entity_scoped_custom_role_reaches_update_requirement(client, admin_token, org_id):
    """The concrete new capability this phase's entity-scoped-axis migration
    adds — the actual point of building Phase 5's registry first: a custom
    role granting `(project_compliance_requirement, manage)` scoped to one
    specific standard reaches `update_requirement` for that standard
    without ever holding `standards_manager`/`standards_contributor` (or
    org-wide `compliance_manager`) at all."""
    standard = _create_standard(client, admin_token, org_id, reference="FGAC-ENT-1", name="FGAC Entity Standard")
    other_standard = _create_standard(client, admin_token, org_id, reference="FGAC-ENT-2", name="FGAC Other Standard")
    version = _create_version(client, admin_token, org_id, standard["id"])
    requirement = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="Entity Scoped Req")

    grantee_id = create_org_user(client, admin_token, org_id, "fgac.standard.custom@example.com", role="member")
    grantee_token = login(client, "fgac.standard.custom@example.com", "Password123!")

    forbidden = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        json={"reference": None, "name": "Not Yet Permitted", "description": "", "reasoning": ""},
        headers=auth_headers(grantee_token),
    )
    assert forbidden.status_code == 403

    role = _create_custom_role(
        client, admin_token, org_id, name="Standard Content Manager (custom)", scope="standard",
        permissions=[COMPLIANCE_STANDARD_CONTENT_MANAGE_PERMISSION],
    )
    _grant_custom_role_to_user(client, admin_token, org_id, role["id"], grantee_id, scope_entity_id=standard["id"])

    updated = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        json={"reference": None, "name": "Updated By Entity Scoped Custom Role", "description": "", "reasoning": ""},
        headers=auth_headers(grantee_token),
    )
    assert updated.status_code == 200, updated.text

    # Tenant/entity isolation: the same grant, scoped to `standard`, must
    # never satisfy a check against a *different* standard's own content —
    # `require_permission`'s `entity_scope` resolution is per specific
    # entity id, not per module/organisation.
    other_version = _create_version(client, admin_token, org_id, other_standard["id"])
    other_requirement = _create_requirement(
        client, admin_token, org_id, other_standard["id"], other_version["id"], name="Other Standard Req"
    )
    still_forbidden = client.patch(
        f"{_base(org_id)}/standards/{other_standard['id']}/versions/{other_version['id']}/requirements/"
        f"{other_requirement['id']}",
        json={"reference": None, "name": "Should Still Be Forbidden", "description": "", "reasoning": ""},
        headers=auth_headers(grantee_token),
    )
    assert still_forbidden.status_code == 403
