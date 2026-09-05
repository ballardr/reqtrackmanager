"""Tests for the Compliance Module's Phase 8 Evidence API
(docs/compliance-module-plan.md Phase 8; docs/Compliance_Module_
Requirements.md §13-§15): creating evidence and linking it to a
requirement's/required action's own project-specific assessment (§13's
multi-linkage), updating metadata, archiving, revalidation and its
append-only history (§15), the §14 valid/expiring/expired derivation and
the `compliance_list_expiring_evidence` MCP-tool-backing endpoint, file
attachments reusing `services.files.upload_file` (§13), the compliance_
officer/PROJECT_MANAGER RBAC composition, and cross-project isolation
(including through the generic `GET /api/v1/files/{id}` download endpoint,
now resolved via `app.modules.registry.resolve_module_file_project_id`).

Reuses `test_compliance_standards_api.py`'s helpers for the Phase 6
standards-catalog side of setup and `test_project_compliance_api.py`'s
helpers for the Phase 7 assignment/assessment side, the same way that file
already reuses the former — this file's own job starts once a project has
a materialised requirement/required-action assessment to attach evidence
to.
"""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import auth_headers, create_org_user, create_project, login
from tests.test_project_compliance_api import (
    _assign_project_role,
    _assign_standard_to_project,
    _grant_compliance_officer,
    _project_base,
    _setup_published_standard_with_tree,
)

TODAY = date.today()


def _setup_project_with_assessment(client, admin_token, org_id, *, project_name="Evidence Project", tree=None):
    """Standard -> published version -> project assignment, returning
    (project, project_compliance, pcr_id, assessment_id) for the *child*
    requirement/required action in the tree (arbitrary — either would do;
    the child exercises the hierarchy path incidentally).

    `tree` lets a caller needing more than one project reuse a single
    `_setup_published_standard_with_tree` call (the same standard assigned
    to several projects, mirroring `test_project_compliance_api.py`'s own
    established pattern for its cross-scope-isolation test) — calling
    that helper twice in the same org would collide on its own hardcoded,
    org-unique `reference`/action-type name."""
    if tree is None:
        tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    standard, version, _parent, child, _pa, child_action = tree
    project = create_project(client, admin_token, org_id, name=project_name)
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])

    pcrs = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    pcr = next(p for p in pcrs if p["requirement_id"] == child["id"])

    assessments = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr['id']}/"
        "required-action-assessments",
        headers=auth_headers(admin_token),
    ).json()
    assessment = next(a for a in assessments if a["required_action_id"] == child_action["id"])

    return project, assignment, pcr["id"], assessment["id"]


def _create_evidence(client, token, project_id, **extra):
    payload = {"title": "IPX9 Test Certificate", **extra}
    resp = client.post(f"{_project_base(project_id)}/evidence", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Create + multi-linkage -------------------------------------------------------


def test_create_evidence_linked_to_requirement_and_action(client, admin_token, org_id):
    project, assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)

    evidence = _create_evidence(
        client, admin_token, project["id"],
        description="Thermal chamber report", issuing_organisation="Acme Test Labs",
        issued_date="2026-01-01", expiry_date="2027-01-01",
        project_compliance_requirement_ids=[pcr_id], required_action_assessment_ids=[assessment_id],
    )
    assert evidence["project_id"] == project["id"]
    assert evidence["provided_by"]
    assert evidence["provided_at"]
    assert evidence["validity_state"] == "valid"
    assert evidence["is_archived"] is False
    assert evidence["linked_requirement_ids"] == [pcr_id]
    assert evidence["linked_required_action_assessment_ids"] == [assessment_id]

    # Visible from both the requirement side and the required-action side.
    req_evidence = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/evidence",
        headers=auth_headers(admin_token),
    )
    assert req_evidence.status_code == 200, req_evidence.text
    assert [e["id"] for e in req_evidence.json()] == [evidence["id"]]

    action_evidence = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{pcr_id}/"
        f"required-action-assessments/{assessment_id}/evidence",
        headers=auth_headers(admin_token),
    )
    assert action_evidence.status_code == 200, action_evidence.text
    assert [e["id"] for e in action_evidence.json()] == [evidence["id"]]


def test_create_evidence_rejects_pcr_id_from_a_different_project(client, admin_token, org_id):
    tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    project_a, _a, pcr_id_a, _aa = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="Project A", tree=tree
    )
    project_b, _b, _pcr_b, _ab = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="Project B", tree=tree
    )

    resp = client.post(
        f"{_project_base(project_b['id'])}/evidence",
        json={"title": "Cross-project evidence", "project_compliance_requirement_ids": [pcr_id_a]},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404, resp.text


def test_link_and_unlink_evidence_is_idempotent_and_isolated(client, admin_token, org_id):
    project, _assignment, pcr_id, assessment_id = _setup_project_with_assessment(client, admin_token, org_id)
    evidence = _create_evidence(client, admin_token, project["id"])

    link = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/requirement-links",
        json={"project_compliance_requirement_id": pcr_id}, headers=auth_headers(admin_token),
    )
    assert link.status_code == 201, link.text
    assert link.json()["linked_requirement_ids"] == [pcr_id]

    # Re-linking the same pair is a no-op, not a duplicate/409.
    relink = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/requirement-links",
        json={"project_compliance_requirement_id": pcr_id}, headers=auth_headers(admin_token),
    )
    assert relink.status_code == 201, relink.text
    assert relink.json()["linked_requirement_ids"] == [pcr_id]

    action_link = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/action-links",
        json={"required_action_assessment_id": assessment_id}, headers=auth_headers(admin_token),
    )
    assert action_link.status_code == 201, action_link.text
    assert action_link.json()["linked_required_action_assessment_ids"] == [assessment_id]

    unlink = client.delete(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/requirement-links/{pcr_id}",
        headers=auth_headers(admin_token),
    )
    assert unlink.status_code == 204, unlink.text

    # Unlinking a pair that no longer exists 404s.
    unlink_again = client.delete(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/requirement-links/{pcr_id}",
        headers=auth_headers(admin_token),
    )
    assert unlink_again.status_code == 404


# --- Update / archive / revalidate -------------------------------------------------


def test_update_evidence_cannot_change_expiry_date(client, admin_token, org_id):
    """§15: expiry must only ever change via `revalidate`, never a plain
    field edit — `ComplianceEvidenceUpdate` has no `expiry_date` field at
    all, so sending one in the PATCH body is simply ignored."""
    project, _a, _p, _aa = _setup_project_with_assessment(client, admin_token, org_id)
    evidence = _create_evidence(client, admin_token, project["id"], expiry_date="2027-06-01")

    resp = client.patch(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}",
        json={"title": "Renamed", "expiry_date": "2099-01-01"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Renamed"
    assert resp.json()["expiry_date"] == "2027-06-01"


def test_archive_and_unarchive_evidence(client, admin_token, org_id):
    project, _a, _p, _aa = _setup_project_with_assessment(client, admin_token, org_id)
    evidence = _create_evidence(client, admin_token, project["id"])

    archived = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/archive", headers=auth_headers(admin_token)
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["is_archived"] is True

    double_archive = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/archive", headers=auth_headers(admin_token)
    )
    assert double_archive.status_code == 409

    unarchived = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/unarchive", headers=auth_headers(admin_token)
    )
    assert unarchived.status_code == 200
    assert unarchived.json()["is_archived"] is False

    double_unarchive = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/unarchive", headers=auth_headers(admin_token)
    )
    assert double_unarchive.status_code == 409


def test_revalidate_records_append_only_history_and_updates_expiry(client, admin_token, org_id):
    """§15's own worked example: revalidating twice must retain the first
    revalidation's own "previous expiry" rather than losing it to the
    second revalidation overwriting the row."""
    project, _a, _p, _aa = _setup_project_with_assessment(client, admin_token, org_id)
    evidence = _create_evidence(client, admin_token, project["id"], issued_date="2026-08-01", expiry_date="2027-08-01")

    first = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/revalidate",
        json={"new_expiry_date": "2028-07-15", "justification": "Annual re-test"},
        headers=auth_headers(admin_token),
    )
    assert first.status_code == 200, first.text
    assert first.json()["expiry_date"] == "2028-07-15"

    second = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/revalidate",
        json={"new_expiry_date": "2029-07-15", "justification": "Second annual re-test"},
        headers=auth_headers(admin_token),
    )
    assert second.status_code == 200, second.text
    assert second.json()["expiry_date"] == "2029-07-15"

    history = client.get(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/revalidations", headers=auth_headers(admin_token)
    )
    assert history.status_code == 200, history.text
    rows = history.json()
    assert len(rows) == 2
    assert rows[0]["previous_expiry_date"] == "2027-08-01"
    assert rows[0]["new_expiry_date"] == "2028-07-15"
    assert rows[1]["previous_expiry_date"] == "2028-07-15"
    assert rows[1]["new_expiry_date"] == "2029-07-15"
    assert rows[1]["justification"] == "Second annual re-test"


# --- §14 validity derivation + expiring-evidence listing / MCP tool endpoint ------


def test_validity_states_and_expiring_evidence_listing(client, admin_token, org_id):
    project, _a, _p, _aa = _setup_project_with_assessment(client, admin_token, org_id)

    no_expiry = _create_evidence(client, admin_token, project["id"], title="No expiry")
    valid = _create_evidence(
        client, admin_token, project["id"], title="Valid",
        expiry_date=(TODAY + timedelta(days=200)).isoformat(),
    )
    expiring_soon = _create_evidence(
        client, admin_token, project["id"], title="Expiring soon",
        expiry_date=(TODAY + timedelta(days=10)).isoformat(),
    )
    expired = _create_evidence(
        client, admin_token, project["id"], title="Expired",
        expiry_date=(TODAY - timedelta(days=5)).isoformat(),
    )
    archived_expired = _create_evidence(
        client, admin_token, project["id"], title="Archived but expired",
        expiry_date=(TODAY - timedelta(days=5)).isoformat(),
    )
    client.post(
        f"{_project_base(project['id'])}/evidence/{archived_expired['id']}/archive", headers=auth_headers(admin_token)
    )

    all_evidence = {
        e["id"]: e["validity_state"]
        for e in client.get(f"{_project_base(project['id'])}/evidence", headers=auth_headers(admin_token)).json()
    }
    assert all_evidence[no_expiry["id"]] == "no_expiry"
    assert all_evidence[valid["id"]] == "valid"
    assert all_evidence[expiring_soon["id"]] == "expiring_soon"
    assert all_evidence[expired["id"]] == "expired"
    assert all_evidence[archived_expired["id"]] == "expired"

    expiring_resp = client.get(f"{_project_base(project['id'])}/expiring-evidence", headers=auth_headers(admin_token))
    assert expiring_resp.status_code == 200, expiring_resp.text
    expiring_ids = {e["id"] for e in expiring_resp.json()}
    # Archived evidence is excluded even though it's technically expired
    # (§13's "applicable" and §14's "valid" are different questions — see
    # `ComplianceEvidenceValidityState`'s own docstring).
    assert expiring_ids == {expiring_soon["id"], expired["id"]}


# --- RBAC composition --------------------------------------------------------------


def test_evidence_mutation_rbac_composition(client, admin_token, org_id):
    """Mirrors `test_project_compliance_api.py`'s own `test_rbac_officer_
    grant_manager_override_and_member_forbidden` shape exactly: a plain
    project member (with a baseline `stakeholder` role, so they're a real
    project member rather than someone with no access at all) is
    forbidden from creating evidence but can still read it; an assigned
    `compliance_officer` can; a `PROJECT_MANAGER` with no explicit officer
    grant can too, via `require_module_role`'s existing admin-override
    composition (Phase 2), reused here unmodified."""
    project, _a, _p, _aa = _setup_project_with_assessment(client, admin_token, org_id)

    plain_member_id = create_org_user(client, admin_token, org_id, "plain.evidence@example.com", role="member")
    officer_id = create_org_user(client, admin_token, org_id, "evidence.officer@example.com", role="member")
    manager_id = create_org_user(client, admin_token, org_id, "evidence.pm@example.com", role="member")

    _assign_project_role(client, admin_token, project["id"], plain_member_id, "stakeholder")
    _assign_project_role(client, admin_token, project["id"], officer_id, "stakeholder")
    _grant_compliance_officer(client, admin_token, project["id"], officer_id)
    _assign_project_role(client, admin_token, project["id"], manager_id, "project_manager")

    plain_token = login(client, "plain.evidence@example.com", "Password123!")
    officer_token = login(client, "evidence.officer@example.com", "Password123!")
    manager_token = login(client, "evidence.pm@example.com", "Password123!")

    forbidden = client.post(
        f"{_project_base(project['id'])}/evidence", json={"title": "Should fail"}, headers=auth_headers(plain_token)
    )
    assert forbidden.status_code == 403
    read_ok = client.get(f"{_project_base(project['id'])}/evidence", headers=auth_headers(plain_token))
    assert read_ok.status_code == 200

    officer_created = _create_evidence(client, officer_token, project["id"], title="Officer-created")
    assert officer_created["title"] == "Officer-created"

    manager_created = _create_evidence(client, manager_token, project["id"], title="Manager-created")
    assert manager_created["title"] == "Manager-created"


# --- File attachments (§13's "reuse existing attachment mechanisms") --------------


def test_evidence_file_upload_download_and_isolation(client, admin_token, org_id):
    project, _a, _p, _aa = _setup_project_with_assessment(client, admin_token, org_id)
    evidence = _create_evidence(client, admin_token, project["id"])

    upload = client.post(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/files",
        files={"file": ("certificate.pdf", b"%PDF-1.4 fake certificate", "application/pdf")},
        headers=auth_headers(admin_token),
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    listed = client.get(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/files", headers=auth_headers(admin_token)
    )
    assert listed.status_code == 200
    assert [f["id"] for f in listed.json()] == [file_id]

    # Downloadable by a project member via the generic, module-agnostic
    # download endpoint — resolved through `resolve_module_file_project_id`
    # rather than any core file-link table (there is no requirement/action
    # in the chain at all here).
    download = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token))
    assert download.status_code == 200
    assert download.content == b"%PDF-1.4 fake certificate"

    # An org member with no access to this specific project cannot,
    # mirroring `test_requirement_actions.py`'s own identical outsider
    # check for a core attachment type.
    create_org_user(client, admin_token, org_id, "outsider.evidence@example.com", role="member")
    outsider_token = login(client, "outsider.evidence@example.com", "Password123!")
    blocked = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(outsider_token))
    assert blocked.status_code == 403

    unlink = client.delete(
        f"{_project_base(project['id'])}/evidence/{evidence['id']}/files/{file_id}", headers=auth_headers(admin_token)
    )
    assert unlink.status_code == 204, unlink.text

    # The non-shared upload is hard-deleted on unlink, so it 404s now.
    gone = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token))
    assert gone.status_code == 404


# --- Cross-project isolation --------------------------------------------------------


def test_cross_project_evidence_isolation(client, admin_token, org_id):
    tree = _setup_published_standard_with_tree(client, admin_token, org_id)
    project_a, _a, _pa, _aa = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="Iso A", tree=tree
    )
    project_b, _b, _pb, _ab = _setup_project_with_assessment(
        client, admin_token, org_id, project_name="Iso B", tree=tree
    )
    evidence = _create_evidence(client, admin_token, project_a["id"])

    wrong_project = client.get(
        f"{_project_base(project_b['id'])}/evidence/{evidence['id']}", headers=auth_headers(admin_token)
    )
    assert wrong_project.status_code == 404
