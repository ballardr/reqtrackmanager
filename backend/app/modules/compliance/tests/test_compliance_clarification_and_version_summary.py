"""Tests for the Compliance Module's Phase 24 (docs/compliance-module-plan.md
Phase 24; docs/Compliance_Module_Requirements.md §4, §31): post-publish
requirement clarification (`PATCH .../requirements/{id}/clarify`) and a
standard version's always-editable `summary` field
(`PATCH .../versions/{version_id}`).

Reuses `test_compliance_standards_api.py`'s/`test_project_compliance_api.py`'s
existing small API helpers for setup, the same way this module's other test
files already do."""

from __future__ import annotations

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.compliance.tests.test_compliance_standards_api import (
    _base,
    _create_requirement,
    _create_standard,
)
from app.modules.compliance.tests.test_project_compliance_api import _publish_version
from tests.conftest import auth_headers, create_org_user, login


def _grant_standard_role(client, token, org_id, standard_id, user_id, role_key, *, expect=204):
    resp = client.post(
        f"{_base(org_id)}/standards/{standard_id}/members/{user_id}/roles",
        json={"role_key": role_key}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp


def _clarify(client, token, org_id, standard_id, version_id, requirement_id, **payload):
    body = {"name": "Access control policy", "clarification_note": "Fixed a typo.", **payload}
    return client.patch(
        f"{_base(org_id)}/standards/{standard_id}/versions/{version_id}/requirements/{requirement_id}/clarify",
        json=body, headers=auth_headers(token),
    )


def _update_version_summary(client, token, org_id, standard_id, version_id, summary):
    return client.patch(
        f"{_base(org_id)}/standards/{standard_id}/versions/{version_id}",
        json={"summary": summary}, headers=auth_headers(token),
    )


def _setup_published_standard_with_requirement(client, admin_token, org_id, *, reference="CLARIFY-1"):
    standard = _create_standard(client, admin_token, org_id, reference=reference)
    version = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token)
    ).json()[0]
    requirement = _create_requirement(
        client, admin_token, org_id, standard["id"], version["id"],
        name="Access control policy", reference="A.5.1", description="Original description.",
    )
    _publish_version(client, admin_token, org_id, standard["id"], version["id"])
    return standard, version, requirement


# --- Clarification: version-status gating -------------------------------------


def test_clarify_succeeds_on_published_version(client, admin_token, org_id):
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id)

    resp = _clarify(
        client, admin_token, org_id, standard["id"], version["id"], requirement["id"],
        name="Access control policy", description="Corrected description.", clarification_note="Fixed wording.",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["description"] == "Corrected description."
    assert body["clarification_count"] == 1
    assert body["last_clarification_note"] == "Fixed wording."
    assert body["last_clarified_at"] is not None
    assert body["last_clarified_by"] is not None

    # A second clarification increments the count rather than resetting it.
    resp2 = _clarify(
        client, admin_token, org_id, standard["id"], version["id"], requirement["id"],
        name="Access control policy", description="Corrected description.", clarification_note="Second fix.",
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["clarification_count"] == 2
    assert resp2.json()["last_clarification_note"] == "Second fix."


def test_clarify_requires_a_note(client, admin_token, org_id):
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id)

    resp = _clarify(
        client, admin_token, org_id, standard["id"], version["id"], requirement["id"], clarification_note="   ",
    )
    assert resp.status_code == 400, resp.text


def test_clarify_rejected_on_draft_version(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="CLARIFY-DRAFT")
    version = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token)
    ).json()[0]
    requirement = _create_requirement(client, admin_token, org_id, standard["id"], version["id"], name="Draft requirement")

    resp = _clarify(client, admin_token, org_id, standard["id"], version["id"], requirement["id"], name="Draft requirement")
    assert resp.status_code == 409, resp.text


def test_clarify_rejected_on_retired_version(client, admin_token, org_id):
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id, reference="CLARIFY-RETIRE")
    retire_resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/retire", headers=auth_headers(admin_token)
    )
    assert retire_resp.status_code == 200, retire_resp.text

    resp = _clarify(client, admin_token, org_id, standard["id"], version["id"], requirement["id"], name="Access control policy")
    assert resp.status_code == 409, resp.text


def test_ordinary_update_endpoint_still_409s_on_published_version(client, admin_token, org_id):
    """A substantive-shaped change (via the ordinary, non-clarify update
    endpoint) still 409s on a published version exactly as before this
    phase — the clarify endpoint is a narrow, distinct addition, not a
    loosening of `_require_draft_version` itself."""
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id, reference="CLARIFY-409")

    resp = client.patch(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/requirements/{requirement['id']}",
        json={"name": "Substantively different requirement", "reference": "A.5.1", "description": "", "reasoning": ""},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_clarify_audit_logged_with_before_and_after(client, admin_token, org_id):
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id, reference="CLARIFY-AUDIT")

    resp = _clarify(
        client, admin_token, org_id, standard["id"], version["id"], requirement["id"],
        name="Access control policy", description="Corrected description.", clarification_note="Fixed wording.",
    )
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(
            AuditEvent.entity_type == "compliance_requirement", AuditEvent.action == "clarified",
            AuditEvent.entity_id == requirement["id"],
        ).first()
        assert event is not None
        assert event.detail["clarification_note"] == "Fixed wording."
        assert event.detail["before"]["description"] == "Original description."
        assert event.detail["after"]["description"] == "Corrected description."
    finally:
        db.close()


# --- Clarification + version summary: RBAC boundary ----------------------------


def test_standards_contributor_cannot_clarify_or_edit_published_version_summary(client, admin_token, org_id):
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id, reference="CLARIFY-RBAC-1")
    contributor_id = create_org_user(client, admin_token, org_id, "clarify_contributor@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], contributor_id, "standards_contributor")
    contributor_token = login(client, "clarify_contributor@example.com", "Password123!")

    resp = _clarify(client, contributor_token, org_id, standard["id"], version["id"], requirement["id"], name="Access control policy")
    assert resp.status_code == 403

    resp2 = _update_version_summary(client, contributor_token, org_id, standard["id"], version["id"], "Should be rejected.")
    assert resp2.status_code == 403


def test_standards_manager_can_clarify_and_edit_published_version_summary(client, admin_token, org_id):
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id, reference="CLARIFY-RBAC-2")
    manager_id = create_org_user(client, admin_token, org_id, "clarify_manager@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], manager_id, "standards_manager")
    manager_token = login(client, "clarify_manager@example.com", "Password123!")

    resp = _clarify(client, manager_token, org_id, standard["id"], version["id"], requirement["id"], name="Access control policy")
    assert resp.status_code == 200, resp.text

    resp2 = _update_version_summary(client, manager_token, org_id, standard["id"], version["id"], "Now deprecated.")
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["summary"] == "Now deprecated."


def test_org_compliance_manager_override_can_clarify_and_edit_published_version_summary(client, admin_token, org_id):
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id, reference="CLARIFY-RBAC-3")
    manager_id = create_org_user(client, admin_token, org_id, "clarify_org_manager@example.com", role="member")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{manager_id}/module-roles",
        json={"module_key": "compliance", "role_key": "compliance_manager"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text
    manager_token = login(client, "clarify_org_manager@example.com", "Password123!")

    resp = _clarify(client, manager_token, org_id, standard["id"], version["id"], requirement["id"], name="Access control policy")
    assert resp.status_code == 200, resp.text

    resp2 = _update_version_summary(client, manager_token, org_id, standard["id"], version["id"], "Now deprecated.")
    assert resp2.status_code == 200, resp2.text


def test_org_admin_override_can_clarify_and_edit_published_version_summary(client, admin_token, org_id):
    standard, version, requirement = _setup_published_standard_with_requirement(client, admin_token, org_id, reference="CLARIFY-RBAC-4")
    create_org_user(client, admin_token, org_id, "clarify_org_admin@example.com", role="org_admin")
    org_admin_token = login(client, "clarify_org_admin@example.com", "Password123!")

    resp = _clarify(client, org_admin_token, org_id, standard["id"], version["id"], requirement["id"], name="Access control policy")
    assert resp.status_code == 200, resp.text

    resp2 = _update_version_summary(client, org_admin_token, org_id, standard["id"], version["id"], "Now deprecated.")
    assert resp2.status_code == 200, resp2.text


# --- Version summary: editable at every lifecycle stage -------------------------


def test_version_summary_editable_at_every_status(client, admin_token, org_id):
    standard = _create_standard(client, admin_token, org_id, reference="SUMMARY-1")
    version = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token)
    ).json()[0]

    # Draft.
    resp = _update_version_summary(client, admin_token, org_id, standard["id"], version["id"], "Draft summary.")
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == "Draft summary."

    # Published.
    _publish_version(client, admin_token, org_id, standard["id"], version["id"])
    resp = _update_version_summary(client, admin_token, org_id, standard["id"], version["id"], "Published summary.")
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == "Published summary."

    # Retired — the motivating example: marking a retired version deprecated.
    retire_resp = client.post(
        f"{_base(org_id)}/standards/{standard['id']}/versions/{version['id']}/retire", headers=auth_headers(admin_token)
    )
    assert retire_resp.status_code == 200, retire_resp.text
    resp = _update_version_summary(client, admin_token, org_id, standard["id"], version["id"], "Deprecated — superseded.")
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == "Deprecated — superseded."


def test_standards_contributor_can_edit_draft_version_summary(client, admin_token, org_id):
    """The stage-dependent RBAC split: a contributor may edit `summary`
    while the version is still `DRAFT` (the ordinary contributor-level
    field-write this module already permits everywhere else) — only once
    published/retired does it require `standards_manager`-or-override."""
    standard = _create_standard(client, admin_token, org_id, reference="SUMMARY-CONTRIB")
    version = client.get(
        f"{_base(org_id)}/standards/{standard['id']}/versions", headers=auth_headers(admin_token)
    ).json()[0]
    contributor_id = create_org_user(client, admin_token, org_id, "summary_contributor@example.com", role="member")
    _grant_standard_role(client, admin_token, org_id, standard["id"], contributor_id, "standards_contributor")
    contributor_token = login(client, "summary_contributor@example.com", "Password123!")

    resp = _update_version_summary(client, contributor_token, org_id, standard["id"], version["id"], "Contributor edit.")
    assert resp.status_code == 200, resp.text
