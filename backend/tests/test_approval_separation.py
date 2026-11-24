"""
Tests for approval separation (`services.approval_separation`, `routers.approval_separation`): which types the rule
covers, the default (the creator may approve, marked), a project that requires a separate approver, an organisation
requirement with exemptions, the comment a deliberate self-approval needs, nested projects, permissions, the audit
trail, the per-record status and the bundles.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.audit import AuditEvent
from app.models.lifecycle import RecordSelfApproval
from app.modules.context_strategy.tests.test_context_strategy_api import (
    _add_plain_member,
    _advance_project_strategy_to_under_review,
    _create_project_strategy,
    _grant_project_module_role,
    _project_base,
)
from app.modules.registry import get_lifecycles
from app.services.approval_separation import approval_gates
from app.services.lifecycles import validate_definition
from tests.conftest import (
    SessionLocal,
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)
from tests.stage_helpers import move_stage

GATED_TYPES = {
    "requirement", "change_request", "decision", "risk", "strategy", "future_state", "guiding_principle",
}


# --- the registry --------------------------------------------------------------------------------


def test_every_type_with_an_approval_gate_is_covered():
    assert set(approval_gates()) == GATED_TYPES


@pytest.mark.parametrize("artefact_type", sorted(t for t in get_lifecycles() if get_lifecycles()[t][1].gated))
def test_a_gated_type_names_its_record_model(artefact_type):
    _, definition = get_lifecycles()[artefact_type]
    assert definition.record_model is not None and hasattr(definition.record_model, "creator_id")
    assert validate_definition(definition) == []


# --- helpers -------------------------------------------------------------------------------------


def _setup(client, admin_token, name: str, *, can_be_parent: bool = False):
    org, token = create_org_admin_in(client, admin_token, name)
    for key in ("context_strategy", "decisions", "risk_management"):
        resp = client.put(f"/api/v1/orgs/{org['id']}/modules/{key}", json={"enabled": True}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
    project = create_project(client, token, org["id"], f"{name} project", can_be_parent=can_be_parent or None)
    return org, project, token


def _project_manager(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "project_manager"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _put_project(client, token, project_id, artefact_type, separate):
    return client.put(
        f"/api/v1/projects/{project_id}/approval-separation/{artefact_type}", json={"separate_approver": separate},
        headers=auth_headers(token),
    )


def _get_project(client, token, project_id) -> dict:
    resp = client.get(f"/api/v1/projects/{project_id}/approval-separation", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry(payload: dict, artefact_type: str) -> dict:
    return next(x for x in payload["types"] if x["artefact_type"] == artefact_type)


def _put_org(client, token, org_id, artefact_type, required):
    return client.put(
        f"/api/v1/orgs/{org_id}/approval-separation/{artefact_type}", json={"required": required},
        headers=auth_headers(token),
    )


def _exempt(client, token, org_id, artefact_type, project_id, include_children=False):
    return client.post(
        f"/api/v1/orgs/{org_id}/approval-separation/{artefact_type}/exemptions",
        json={"project_id": project_id, "include_children": include_children}, headers=auth_headers(token),
    )


_SCOPES: dict[str, tuple[str, str]] = {}


def _requirement(client, token, project_id, name="Boot fast") -> str:
    if project_id not in _SCOPES:
        _SCOPES[project_id] = create_component_and_category(client, token, project_id)
    component_id, category_id = _SCOPES[project_id]
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _approve_requirement(client, token, project_id, requirement_id, comment=None):
    return client.post(
        f"/api/v1/projects/{project_id}/requirements/{requirement_id}/approve",
        json={} if comment is None else {"comment": comment}, headers=auth_headers(token),
    )


def _status(client, token, project_id, artefact_type, record_id) -> dict:
    resp = client.get(
        f"/api/v1/projects/{project_id}/approval-separation/status/{artefact_type}/{record_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events(record_id: str, action: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.query(AuditEvent).filter(AuditEvent.entity_id == record_id, AuditEvent.action == action))
    finally:
        db.close()


# --- the default ---------------------------------------------------------------------------------


def test_by_default_the_creator_may_approve_without_a_comment_and_the_record_is_marked(client, admin_token):
    _, project, token = _setup(client, admin_token, "Separation Default Co")
    payload = _get_project(client, token, project["id"])
    assert {t["artefact_type"] for t in payload["types"]} >= {"requirement", "change_request", "decision", "risk"}
    entry = _entry(payload, "requirement")
    assert entry["own"] is None and entry["chosen"] is False and entry["separate"] is False
    assert entry["source"] == "default" and entry["label"] == "Requirement"

    requirement = _requirement(client, token, project["id"])
    assert _status(client, token, project["id"], "requirement", requirement)["self_approved"] is False
    assert _approve_requirement(client, token, project["id"], requirement).status_code == 200

    marked = _status(client, token, project["id"], "requirement", requirement)
    assert marked["self_approved"] is True and marked["approved_at"] is not None and marked["approved_by_name"]
    assert len(_events(requirement, "self_approved")) == 1
    assert _events(requirement, "self_approved")[0].detail == {"self_approved": True}


def test_another_person_approving_leaves_no_mark(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Other Co")
    _, other = _project_manager(client, token, org["id"], project["id"], "separation_other_pm@example.com")
    requirement = _requirement(client, token, project["id"])
    assert _approve_requirement(client, other, project["id"], requirement).status_code == 200
    assert _status(client, token, project["id"], "requirement", requirement)["self_approved"] is False
    assert _events(requirement, "self_approved") == []


# --- a project that requires a separate approver -------------------------------------------------


def test_a_project_requiring_a_separate_approver_refuses_the_creator_and_accepts_another_person(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Project Co")
    _, other = _project_manager(client, token, org["id"], project["id"], "separation_project_pm@example.com")
    assert _put_project(client, token, project["id"], "requirement", True).status_code == 200
    requirement = _requirement(client, token, project["id"])

    refused = _approve_requirement(client, token, project["id"], requirement, "I checked it.")
    assert refused.status_code == 403
    assert "different person" in refused.json()["detail"]
    assert _status(client, token, project["id"], "requirement", requirement)["needs_other_approver"] is True
    assert _status(client, other, project["id"], "requirement", requirement)["needs_other_approver"] is False

    assert _approve_requirement(client, other, project["id"], requirement).status_code == 200
    assert _status(client, token, project["id"], "requirement", requirement)["self_approved"] is False


def test_the_server_refuses_the_creator_even_through_the_edit_endpoint_and_a_baseline(client, admin_token):
    _, project, token = _setup(client, admin_token, "Separation Routes Co")
    assert _put_project(client, token, project["id"], "requirement", True).status_code == 200
    requirement = _requirement(client, token, project["id"])
    current = client.get(f"/api/v1/projects/{project['id']}/requirements/{requirement}", headers=auth_headers(token)).json()
    component_id, category_id = _SCOPES[project["id"]]
    edit = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement}",
        json={
            "name": current["name"], "component_id": component_id, "category_id": category_id, "owner": current["owner"],
            "status": "approved", "change_note": "Approving through the edit form.",
        },
        headers=auth_headers(token),
    )
    assert edit.status_code == 403, edit.text
    stage_id = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(token)).json()[0]["id"]
    baseline = move_stage(client, project["id"], stage_id, "approved", headers=auth_headers(token))
    assert baseline.status_code == 403, baseline.text
    assert client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement}", headers=auth_headers(token)
    ).json()["status"] != "approved"


def test_a_deliberate_self_approval_needs_a_comment(client, admin_token):
    _, project, token = _setup(client, admin_token, "Separation Comment Co")
    assert _put_project(client, token, project["id"], "requirement", False).status_code == 200
    requirement = _requirement(client, token, project["id"])
    missing = _approve_requirement(client, token, project["id"], requirement)
    assert missing.status_code == 400 and "comment is required" in missing.json()["detail"]
    assert _approve_requirement(client, token, project["id"], requirement, "  ").status_code == 400
    assert _approve_requirement(client, token, project["id"], requirement, "Checked against the test report.").status_code == 200
    assert _status(client, token, project["id"], "requirement", requirement)["self_approved"] is True


def test_a_change_request_follows_its_own_setting(client, admin_token):
    _, project, token = _setup(client, admin_token, "Separation CR Co")
    requirement = _requirement(client, token, project["id"])
    other_requirement = _requirement(client, token, project["id"], "Second")
    assert _approve_requirement(client, token, project["id"], requirement).status_code == 200
    assert _approve_requirement(client, token, project["id"], other_requirement).status_code == 200

    def submitted() -> str:
        cr = client.post(
            f"/api/v1/projects/{project['id']}/change-requests",
            json={
                "kind": "modify_requirement", "requirement_id": requirement, "changed_fields": ["name"],
                "proposed_name": f"Renamed {uuid.uuid4().hex[:6]}", "reason": "Reason",
            },
            headers=auth_headers(token),
        )
        assert cr.status_code == 201, cr.text
        sent = client.post(
            f"/api/v1/projects/{project['id']}/change-requests/{cr.json()['id']}/submit", headers=auth_headers(token)
        )
        assert sent.status_code == 200, sent.text
        return cr.json()["id"]

    def decide(cr_id: str, note: str = "ok"):
        return client.post(
            f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/decide",
            json={"approve": True, "note": note}, headers=auth_headers(token),
        )

    assert _put_project(client, token, project["id"], "change_request", True).status_code == 200
    first = submitted()
    assert decide(first).status_code == 403
    # The requirement's own setting is independent of the change request's.
    assert _entry(_get_project(client, token, project["id"]), "requirement")["separate"] is False

    assert _put_project(client, token, project["id"], "change_request", False).status_code == 200
    assert decide(first, "").status_code == 400
    assert decide(first).status_code == 200
    assert _status(client, token, project["id"], "change_request", first)["self_approved"] is True


def test_a_strategy_approved_by_its_creator_is_refused_when_a_separate_approver_is_required(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Strategy Co")
    user_id, approver = _add_plain_member(client, token, org["id"], project["id"], "separation_strategy_approver@example.com")
    _grant_project_module_role(client, token, project["id"], user_id, "strategy_approver")
    # The creator holds the approver permission too, as an organisation administrator does.
    assert _put_project(client, token, project["id"], "strategy", True).status_code == 200
    strategy = _create_project_strategy(client, token, project["id"])
    _advance_project_strategy_to_under_review(client, token, project["id"], strategy["id"])
    url = f"{_project_base(project['id'])}/strategies/{strategy['id']}/approve"
    assert client.post(url, json={"comment": "Fine."}, headers=auth_headers(token)).status_code == 403
    assert client.post(url, json={"comment": "Fine."}, headers=auth_headers(approver)).status_code == 200


# --- the organisation ----------------------------------------------------------------------------


def test_an_organisation_requirement_binds_every_project_and_beats_a_stored_choice(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Org Co")
    assert _put_project(client, token, project["id"], "requirement", False).status_code == 200
    assert _put_org(client, token, org["id"], "requirement", True).status_code == 200

    entry = _entry(_get_project(client, token, project["id"]), "requirement")
    assert entry["required"] is True and entry["separate"] is True and entry["own"] is False

    refused = _put_project(client, token, project["id"], "requirement", False)
    assert refused.status_code == 409 and "organisation requires" in refused.json()["detail"]
    requirement = _requirement(client, token, project["id"])
    assert _approve_requirement(client, token, project["id"], requirement, "ok").status_code == 403

    assert _put_org(client, token, org["id"], "requirement", False).status_code == 200
    entry = _entry(_get_project(client, token, project["id"]), "requirement")
    assert entry["separate"] is False and entry["own"] is False, "the project's own choice is kept"


def test_an_exempt_project_may_let_its_creator_approve_with_a_comment(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Exempt Co")
    other = create_project(client, token, org["id"], "Separation Other Project")
    assert _put_org(client, token, org["id"], "requirement", True).status_code == 200
    assert _exempt(client, token, org["id"], "requirement", project["id"]).status_code == 200

    entry = _entry(_get_project(client, token, project["id"]), "requirement")
    assert entry["exempt"] is True and entry["required"] is False and entry["separate"] is False
    requirement = _requirement(client, token, project["id"])
    assert _approve_requirement(client, token, project["id"], requirement).status_code == 400
    assert _approve_requirement(client, token, project["id"], requirement, "Solo project.").status_code == 200

    other_requirement = _requirement(client, token, other["id"])
    assert _approve_requirement(client, token, other["id"], other_requirement, "ok").status_code == 403

    removed = client.delete(
        f"/api/v1/orgs/{org['id']}/approval-separation/requirement/exemptions/{project['id']}", headers=auth_headers(token),
    )
    assert removed.status_code == 200
    assert _entry(_get_project(client, token, project["id"]), "requirement")["separate"] is True


def test_an_exemption_covers_children_only_when_asked(client, admin_token):
    org, parent, token = _setup(client, admin_token, "Separation Children Co", can_be_parent=True)
    child = create_project(client, token, org["id"], "Separation Child", parent_project_id=parent["id"])
    assert _put_org(client, token, org["id"], "decision", True).status_code == 200
    assert _exempt(client, token, org["id"], "decision", parent["id"]).status_code == 200
    assert _entry(_get_project(client, token, child["id"]), "decision")["separate"] is True
    assert _exempt(client, token, org["id"], "decision", parent["id"], include_children=True).status_code == 200
    assert _entry(_get_project(client, token, child["id"]), "decision")["separate"] is False


def test_a_child_without_a_choice_follows_its_nearest_ancestor(client, admin_token):
    org, parent, token = _setup(client, admin_token, "Separation Nested Co", can_be_parent=True)
    child = create_project(client, token, org["id"], "Separation Nested Child", parent_project_id=parent["id"])
    assert _put_project(client, token, parent["id"], "risk", True).status_code == 200
    payload = _get_project(client, token, child["id"])
    entry = _entry(payload, "risk")
    assert payload["has_parent"] is True
    assert entry["own"] is None and entry["chosen"] is True and entry["source"] == "parent_project"
    assert _put_project(client, token, child["id"], "risk", None).status_code == 200
    assert _entry(_get_project(client, token, child["id"]), "risk")["source"] == "parent_project"


def test_an_organisation_requirement_applies_to_a_record_without_a_project(client, admin_token):
    from app.services.approval_separation import resolve_separation

    org, _, token = _setup(client, admin_token, "Separation Org Owned Co")
    assert _put_org(client, token, org["id"], "strategy", True).status_code == 200
    db = SessionLocal()
    try:
        owned = resolve_separation(db, artefact_type="strategy", organization_id=uuid.UUID(org["id"]), project_id=None)
        assert owned.separate is True and owned.deliberate is False
        other = resolve_separation(db, artefact_type="future_state", organization_id=uuid.UUID(org["id"]), project_id=None)
        assert other.separate is False
    finally:
        db.close()


# --- permissions and validation ------------------------------------------------------------------


def test_only_the_lifecycle_permissions_change_the_setting(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Permission Co")
    member = create_org_user(client, token, org["id"], "separation_member@example.com")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": member, "role": "member"}, headers=auth_headers(token)
    )
    member_token = login(client, "separation_member@example.com", "Password123!")
    assert _get_project(client, member_token, project["id"])["can_manage"] is False
    assert _put_project(client, member_token, project["id"], "requirement", True).status_code == 403
    assert _put_org(client, member_token, org["id"], "requirement", True).status_code == 403
    assert client.get(f"/api/v1/orgs/{org['id']}/approval-separation", headers=auth_headers(member_token)).status_code == 403
    assert _get_project(client, token, project["id"])["can_manage"] is True


def test_an_unknown_type_and_a_foreign_project_are_refused(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Validate Co")
    assert _put_project(client, token, project["id"], "pain_point", True).status_code == 404
    assert _put_org(client, token, org["id"], "no_such_type", True).status_code == 404
    other_org, other_project, _ = _setup(client, admin_token, "Separation Foreign Co")
    assert _exempt(client, token, org["id"], "requirement", other_project["id"]).status_code == 404
    missing = client.delete(
        f"/api/v1/orgs/{org['id']}/approval-separation/requirement/exemptions/{project['id']}", headers=auth_headers(token)
    )
    assert missing.status_code == 404
    assert other_org["id"] != org["id"]


def test_the_record_status_stays_inside_its_project(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Status Co")
    other = create_project(client, token, org["id"], "Separation Status Other")
    requirement = _requirement(client, token, project["id"])
    resp = client.get(
        f"/api/v1/projects/{other['id']}/approval-separation/status/requirement/{requirement}", headers=auth_headers(token)
    )
    assert resp.status_code == 404
    missing = client.get(
        f"/api/v1/projects/{project['id']}/approval-separation/status/requirement/{uuid.uuid4()}",
        headers=auth_headers(token),
    )
    assert missing.status_code == 404


def test_changes_are_audited_with_keys_only(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Audit Co")
    assert _put_project(client, token, project["id"], "risk", True).status_code == 200
    assert _put_org(client, token, org["id"], "risk", True).status_code == 200
    assert _exempt(client, token, org["id"], "risk", project["id"]).status_code == 200
    db = SessionLocal()
    try:
        events = db.query(AuditEvent).filter(AuditEvent.entity_type == "approval_separation").all()
        by_action = {e.action: e for e in events if e.organization_id == uuid.UUID(org["id"])}
        assert set(by_action) >= {"project_updated", "organization_updated", "exemption_added"}
        assert by_action["project_updated"].detail == {"artefact_type": "risk", "from": None, "to": True, "inherits": False}
        assert by_action["organization_updated"].detail == {"artefact_type": "risk", "required": True}
    finally:
        db.close()


def test_the_self_approval_mark_is_replaced_by_each_approval(client, admin_token):
    from app.models.user import User
    from app.services.approval_separation import enforce_approval

    org, project, token = _setup(client, admin_token, "Separation Mark Co")
    _, other_token = _project_manager(client, token, org["id"], project["id"], "separation_mark_pm@example.com")
    requirement = _requirement(client, token, project["id"])
    assert _approve_requirement(client, token, project["id"], requirement).status_code == 200
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]
    them = client.get("/api/v1/auth/me", headers=auth_headers(other_token)).json()["id"]
    db = SessionLocal()
    try:
        record_id = uuid.UUID(requirement)
        assert db.query(RecordSelfApproval).filter_by(record_id=record_id).count() == 1
        kwargs = {
            "artefact_type": "requirement", "record_id": record_id, "creator_id": uuid.UUID(me),
            "organization_id": uuid.UUID(org["id"]), "project_id": uuid.UUID(project["id"]),
        }
        assert enforce_approval(db, user=db.get(User, uuid.UUID(them)), comment=None, **kwargs) is False
        db.commit()
        assert db.query(RecordSelfApproval).filter_by(record_id=record_id).count() == 0
        assert enforce_approval(db, user=db.get(User, uuid.UUID(me)), comment=None, **kwargs) is True
        assert enforce_approval(db, user=db.get(User, uuid.UUID(me)), comment=None, **kwargs) is True
        db.commit()
        assert db.query(RecordSelfApproval).filter_by(record_id=record_id).count() == 1
    finally:
        db.close()


# --- bundles and templates -----------------------------------------------------------------------


def test_project_bundle_round_trip_keeps_the_choice(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Bundle Co")
    assert _put_project(client, token, project["id"], "decision", True).status_code == 200
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert export.status_code == 200
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Imported separation project"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    entry = _entry(_get_project(client, token, imported.json()["project"]["id"]), "decision")
    assert entry["own"] is True and entry["separate"] is True


def test_an_imported_choice_never_relaxes_an_organisation_requirement(client, admin_token):
    org, project, token = _setup(client, admin_token, "Separation Bundle Required Co")
    assert _put_project(client, token, project["id"], "decision", False).status_code == 200
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert _put_org(client, token, org["id"], "decision", True).status_code == 200
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Imported under requirement"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    entry = _entry(_get_project(client, token, imported.json()["project"]["id"]), "decision")
    assert entry["own"] is False and entry["separate"] is True


def test_a_project_made_from_a_template_passes_the_choice_on(client, admin_token):
    org, template, token = _setup(client, admin_token, "Separation Template Co")
    assert _put_project(client, token, template["id"], "risk", True).status_code == 200
    client.patch(f"/api/v1/projects/{template['id']}", json={"is_template": True}, headers=auth_headers(token))
    created = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "From template", "summary": "", "template_project_id": template["id"]},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    assert _entry(_get_project(client, token, created.json()["id"]), "risk")["separate"] is True


def test_organisation_bundle_round_trip_keeps_requirements_and_exemptions(client, admin_token):
    from app.models.lifecycle import OrganizationApprovalSeparationExemption, OrganizationApprovalSeparationRequirement

    org, project, token = _setup(client, admin_token, "Separation Org Bundle Co")
    assert _put_org(client, token, org["id"], "change_request", True).status_code == 200
    assert _exempt(client, token, org["id"], "change_request", project["id"], True).status_code == 200
    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert export.status_code == 200, export.text
    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Separation Org Copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org_id = imported.json()["organization"]["id"]
    db = SessionLocal()
    try:
        requirements = db.query(OrganizationApprovalSeparationRequirement).filter_by(organization_id=new_org_id).all()
        assert [r.artefact_type for r in requirements] == ["change_request"]
        exemptions = db.query(OrganizationApprovalSeparationExemption).filter_by(organization_id=new_org_id).all()
        assert len(exemptions) == 1 and exemptions[0].include_children is True
        assert str(exemptions[0].project_id) != project["id"]
    finally:
        db.close()


# --- the module types ----------------------------------------------------------------------------


def test_a_decision_follows_the_setting(client, admin_token):
    from app.modules.decisions.models import Decision
    from app.modules.decisions.service import propose_decision, submit_decision_for_review
    from app.modules.decisions.tests.test_decisions_api import _base as _decision_base
    from app.modules.decisions.tests.test_decisions_workflow import (
        _create_decision,
        _current_user_id,
        _first_decision_type_id,
    )

    _, project, token = _setup(client, admin_token, "Separation Decision Co")
    user_id = _current_user_id(client, token)
    decision_id = _create_decision(
        project_id=uuid.UUID(project["id"]), decision_type_id=_first_decision_type_id(uuid.UUID(project["id"])),
        user_id=user_id, code="DEC-001",
    )
    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        propose_decision(db, decision, user_id)
        submit_decision_for_review(db, decision, user_id)
        db.commit()
    finally:
        db.close()
    url = f"{_decision_base(project['id'])}/{decision_id}/approve"
    assert _put_project(client, token, project["id"], "decision", True).status_code == 200
    assert client.post(url, json={"comment": "Fine."}, headers=auth_headers(token)).status_code == 403
    assert _put_project(client, token, project["id"], "decision", False).status_code == 200
    assert client.post(url, json={}, headers=auth_headers(token)).status_code == 400
    assert client.post(url, json={"comment": "Fine."}, headers=auth_headers(token)).status_code == 200
    assert _status(client, token, project["id"], "decision", str(decision_id))["self_approved"] is True


def test_a_risk_acceptance_follows_the_setting(client, admin_token):
    from app.modules.risk_management.tests._helpers import create_risk
    from app.modules.risk_management.tests.test_risk_lifecycle import _move, _score, _url, _walk

    _, project, token = _setup(client, admin_token, "Separation Risk Co")
    risk = create_risk(client, token, project["id"])
    _score(client, token, project, risk)
    _score(client, token, project, risk, residual=True)
    client.put(_url(project["id"], risk["id"]), json={"acceptance_criteria": "Within appetite."}, headers=auth_headers(token))
    _walk(client, token, project["id"], risk["id"], "assessed")
    assert _put_project(client, token, project["id"], "risk", True).status_code == 200
    refused = _move(client, token, project["id"], risk["id"], "accepted", comment="Signed off")
    assert refused.status_code == 403, refused.text
    assert _put_project(client, token, project["id"], "risk", False).status_code == 200
    assert _move(client, token, project["id"], risk["id"], "accepted", comment="Signed off").status_code == 200
    assert _status(client, token, project["id"], "risk", risk["id"])["self_approved"] is True
