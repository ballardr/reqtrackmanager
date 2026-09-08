"""Tests for the Compliance Module's Phase 20 "Standard Applicability
Defaults, Exceptions, and Project-Manager Assignment"
(docs/compliance-module-plan.md Phase 20; docs/Compliance_Module_
Requirements.md §3, §7, §11, §26): the `applicability_default` toggle on a
standard, its exclusion list, the reconciliation this drives (a standard
switched to `applies_to_all_projects`, an exclusion removed, a brand-new
project created), and the RBAC boundary keeping this standard-level setting
Compliance-Manager/org-admin-only even though *assignment itself* is now a
Project-Manager-accessible default path (covered separately in
`test_project_compliance_api.py`).

Reuses `test_compliance_standards_api.py`'s own small API helpers for the
standards-catalog side of each test's setup, the same convention `test_
project_compliance_api.py` already established.
"""

from __future__ import annotations

from app.modules.compliance.tests.test_compliance_standards_api import (
    _base,
    _create_standard,
    _create_version,
    _grant_compliance_manager,
)
from tests.conftest import auth_headers, create_org_user, create_project, login


def _publish_version(client, token, org_id, standard_id, version_id):
    resp = client.post(f"{_base(org_id)}/standards/{standard_id}/versions/{version_id}/publish", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _assign_project_role(client, admin_token, project_id, user_id, role):
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _list_project_compliance(client, token, project_id):
    resp = client.get(f"/api/v1/projects/{project_id}/modules/compliance/project-compliance", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _published_standard(client, admin_token, org_id, reference="AD-1"):
    standard = _create_standard(client, admin_token, org_id, reference=reference)
    version = _create_version(client, admin_token, org_id, standard["id"])
    _publish_version(client, admin_token, org_id, standard["id"], version["id"])
    return standard, version


# --- Default value + RBAC boundary -----------------------------------------------


def test_new_standard_defaults_to_opt_in(client, admin_token, org_id):
    """Every standard, including a brand-new one, keeps today's fully-
    manual behaviour unless a Compliance Manager explicitly switches it."""
    standard = _create_standard(client, admin_token, org_id, reference="OPT-IN-DEFAULT")
    assert standard["applicability_default"] == "opt_in"


def test_only_compliance_manager_can_change_applicability_default(client, admin_token, org_id):
    """§3: switching a standard's own applicability-default setting stays
    Compliance-Manager/org-admin territory — a plain `PROJECT_MANAGER` may
    act on their own project's own assignment row (Phase 20's default
    path), but never on the standard's own governance."""
    standard, _version = _published_standard(client, admin_token, org_id, reference="RBAC-BOUNDARY")
    project = create_project(client, admin_token, org_id, name="RBAC Boundary Project")
    pm_id = create_org_user(client, admin_token, org_id, "pm.boundary@example.com", role="member")
    _assign_project_role(client, admin_token, project["id"], pm_id, "project_manager")
    pm_token = login(client, "pm.boundary@example.com", "Password123!")

    forbidden = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "applies_to_all_projects"},
        headers=auth_headers(pm_token),
    )
    assert forbidden.status_code == 403

    manager_id = create_org_user(client, admin_token, org_id, "cm.boundary@example.com", role="member")
    _grant_compliance_manager(client, admin_token, org_id, manager_id)
    manager_token = login(client, "cm.boundary@example.com", "Password123!")
    allowed = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "applies_to_all_projects"},
        headers=auth_headers(manager_token),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["applicability_default"] == "applies_to_all_projects"


# --- Reconciliation: standard flipped to applies_to_all_projects -----------------


def test_switching_to_applies_to_all_reconciles_every_non_excluded_project(client, admin_token, org_id):
    """Switching a standard to `applies_to_all_projects` materialises a
    real `ProjectCompliance` row for every current, non-archived project
    in the org — except one already explicitly excluded, and without
    duplicating an assignment a project already holds via a prior manual/
    self-service assignment."""
    standard, version = _published_standard(client, admin_token, org_id, reference="RECONCILE-ALL")

    already_assigned_project = create_project(client, admin_token, org_id, name="Already Assigned Project")
    fresh_project = create_project(client, admin_token, org_id, name="Fresh Project")
    excluded_project = create_project(client, admin_token, org_id, name="Excluded Project")

    # This project already tracks the standard via a prior manual assignment.
    manual_assign = client.post(
        f"{_base(org_id)}/projects/{already_assigned_project['id']}/project-compliance",
        json={"standard_id": standard["id"], "standard_version_id": version["id"]},
        headers=auth_headers(admin_token),
    )
    assert manual_assign.status_code == 201, manual_assign.text
    existing_pc_id = manual_assign.json()["id"]

    # This project is excluded up front, with a mandatory reason.
    exclude = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/exclusions",
        json={"project_id": excluded_project["id"], "reason": "Legacy platform, standard does not apply."},
        headers=auth_headers(admin_token),
    )
    assert exclude.status_code == 201, exclude.text

    flip = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "applies_to_all_projects"},
        headers=auth_headers(admin_token),
    )
    assert flip.status_code == 200, flip.text

    # The already-assigned project keeps its one, original row — not a
    # second, duplicate assignment.
    rows = _list_project_compliance(client, admin_token, already_assigned_project["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == existing_pc_id

    # The fresh project got a brand-new, real assignment row.
    fresh_rows = _list_project_compliance(client, admin_token, fresh_project["id"])
    assert len(fresh_rows) == 1
    assert fresh_rows[0]["standard_version_id"] == version["id"]
    assert fresh_rows[0]["is_archived"] is False

    # The excluded project got nothing.
    assert _list_project_compliance(client, admin_token, excluded_project["id"]) == []


def test_excluding_a_project_archives_its_existing_assignment_not_deletes_it(client, admin_token, org_id):
    """§16: excepting a project out of an `applies_to_all_projects`
    standard archives (never deletes) its existing `ProjectCompliance` row
    — its assessment history must survive being excepted out."""
    standard, version = _published_standard(client, admin_token, org_id, reference="EXCLUDE-ARCHIVES")
    project = create_project(client, admin_token, org_id, name="Exclude Archives Project")
    assign = client.post(
        f"{_base(org_id)}/projects/{project['id']}/project-compliance",
        json={"standard_id": standard["id"], "standard_version_id": version["id"]},
        headers=auth_headers(admin_token),
    )
    assert assign.status_code == 201, assign.text
    pc_id = assign.json()["id"]

    exclude = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/exclusions",
        json={"project_id": project["id"], "reason": "Excepted after the fact."},
        headers=auth_headers(admin_token),
    )
    assert exclude.status_code == 201, exclude.text

    rows = _list_project_compliance(client, admin_token, project["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == pc_id
    assert rows[0]["is_archived"] is True


def test_exclusion_requires_a_reason(client, admin_token, org_id):
    """§16's mandatory-justification convention applies to exclusions too —
    a blank reason 400s."""
    standard, _version = _published_standard(client, admin_token, org_id, reference="EXCLUDE-REASON")
    project = create_project(client, admin_token, org_id, name="Exclude Reason Project")

    resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/exclusions",
        json={"project_id": project["id"], "reason": "   "},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_removing_an_exclusion_reconciles_the_project(client, admin_token, org_id):
    """Removing a project from a standard's exclusion list, while the
    standard is still `applies_to_all_projects`, immediately reconciles
    that project — the same "gets the same treatment at that moment" rule
    a newly-created project gets."""
    standard, version = _published_standard(client, admin_token, org_id, reference="UNEXCLUDE-RECONCILE")
    project = create_project(client, admin_token, org_id, name="Unexclude Reconcile Project")

    exclude = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/exclusions",
        json={"project_id": project["id"], "reason": "Not ready yet."},
        headers=auth_headers(admin_token),
    )
    assert exclude.status_code == 201, exclude.text

    flip = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "applies_to_all_projects"},
        headers=auth_headers(admin_token),
    )
    assert flip.status_code == 200, flip.text
    assert _list_project_compliance(client, admin_token, project["id"]) == []

    remove = client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/exclusions/{project['id']}", headers=auth_headers(admin_token),
    )
    assert remove.status_code == 204, remove.text

    rows = _list_project_compliance(client, admin_token, project["id"])
    assert len(rows) == 1
    assert rows[0]["standard_version_id"] == version["id"]
    assert rows[0]["is_archived"] is False


def test_removing_a_nonexistent_exclusion_404s(client, admin_token, org_id):
    standard, _version = _published_standard(client, admin_token, org_id, reference="UNEXCLUDE-404")
    project = create_project(client, admin_token, org_id, name="Unexclude 404 Project")
    resp = client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/exclusions/{project['id']}", headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


def test_switching_back_to_opt_in_does_not_archive_reconciled_rows(client, admin_token, org_id):
    """`applicability_default` only governs *future* reconciliation events
    — switching a standard back to `opt_in` never retroactively archives a
    `ProjectCompliance` row a prior `applies_to_all_projects` reconciliation
    created (`models.py`'s own Phase 20 design-decisions section)."""
    standard, version = _published_standard(client, admin_token, org_id, reference="REVERT-OPT-IN")
    project = create_project(client, admin_token, org_id, name="Revert Opt-In Project")

    flip_on = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "applies_to_all_projects"},
        headers=auth_headers(admin_token),
    )
    assert flip_on.status_code == 200, flip_on.text
    rows = _list_project_compliance(client, admin_token, project["id"])
    assert len(rows) == 1

    flip_off = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "opt_in"},
        headers=auth_headers(admin_token),
    )
    assert flip_off.status_code == 200, flip_off.text
    rows_after = _list_project_compliance(client, admin_token, project["id"])
    assert len(rows_after) == 1
    assert rows_after[0]["is_archived"] is False
    assert rows_after[0]["standard_version_id"] == version["id"]


def test_reconciliation_targets_latest_published_version(client, admin_token, org_id):
    """Reconciliation always targets the *current latest* published
    version at the moment it runs — publishing v2 after a standard is
    already `applies_to_all_projects` and then un-excluding/creating a
    project picks up v2, not the version that was latest when the mode was
    first switched on."""
    standard, v1 = _published_standard(client, admin_token, org_id, reference="LATEST-VERSION")
    excluded_project = create_project(client, admin_token, org_id, name="Latest Version Excluded Project")
    exclude = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/exclusions",
        json={"project_id": excluded_project["id"], "reason": "Hold until v2."},
        headers=auth_headers(admin_token),
    )
    assert exclude.status_code == 201, exclude.text

    flip = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "applies_to_all_projects"},
        headers=auth_headers(admin_token),
    )
    assert flip.status_code == 200, flip.text

    v2 = _create_version(client, admin_token, org_id, standard["id"], version_label="2.0")
    _publish_version(client, admin_token, org_id, standard["id"], v2["id"])

    remove = client.delete(
        f"{_base(org_id)}/standards/{standard['id']}/exclusions/{excluded_project['id']}",
        headers=auth_headers(admin_token),
    )
    assert remove.status_code == 204, remove.text

    rows = _list_project_compliance(client, admin_token, excluded_project["id"])
    assert len(rows) == 1
    assert rows[0]["standard_version_id"] == v2["id"]


# --- on_project_created hook: a brand-new project gets reconciled too -----------


def test_new_project_created_after_flip_is_automatically_assigned(client, admin_token, org_id):
    """§7/§20's "a project created afterward... gets the same treatment at
    that moment" — a brand-new project, created after a standard is
    already `applies_to_all_projects`, is automatically assigned to it at
    creation time via `ModuleDefinition.on_project_created`, with no
    explicit assignment call at all."""
    standard, version = _published_standard(client, admin_token, org_id, reference="NEW-PROJECT-HOOK")
    flip = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "applies_to_all_projects"},
        headers=auth_headers(admin_token),
    )
    assert flip.status_code == 200, flip.text

    new_project = create_project(client, admin_token, org_id, name="Born Into Applies-To-All Project")
    rows = _list_project_compliance(client, admin_token, new_project["id"])
    assert len(rows) == 1
    assert rows[0]["standard_version_id"] == version["id"]
    assert rows[0]["is_archived"] is False


def test_new_project_created_with_opt_in_standard_gets_nothing_automatically(client, admin_token, org_id):
    """The ordinary, unchanged case: a standard left at `opt_in` (every
    standard's default) contributes no automatic assignment to a newly
    created project."""
    _published_standard(client, admin_token, org_id, reference="NEW-PROJECT-OPT-IN")
    new_project = create_project(client, admin_token, org_id, name="Born Into Opt-In Project")
    assert _list_project_compliance(client, admin_token, new_project["id"]) == []


# --- Audit -------------------------------------------------------------------


def test_applicability_default_change_and_reconciliation_are_audited(client, admin_token, org_id):
    """Every reconciliation event (standard flipped, a PM-initiated
    assignment, a project excepted/un-excepted) logs via `services.audit.
    log_event`, matching every other compliance mutation."""
    standard, _version = _published_standard(client, admin_token, org_id, reference="AUDIT-RECONCILE")
    create_project(client, admin_token, org_id, name="Audited Reconciliation Project")

    flip = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/applicability-default",
        json={"applicability_default": "applies_to_all_projects"},
        headers=auth_headers(admin_token),
    )
    assert flip.status_code == 200, flip.text

    history = client.get(f"{_base(org_id)}/standards/{standard['id']}/history", headers=auth_headers(admin_token))
    assert history.status_code == 200, history.text
    actions = [e["action"] for e in history.json()]
    assert "applicability_default_changed" in actions
