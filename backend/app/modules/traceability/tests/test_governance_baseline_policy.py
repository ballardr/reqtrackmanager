"""Tests for the baseline policy of governance (`modules.traceability.baseline_policy`, the checks in `baseline_checks`, the
routes under `/profiles/{id}/baseline` and `/baseline-policy` and the preview `/baseline-checks`): who may set it, what it
validates, how a project's policy merges from profiles, its own row and the nearest ancestor's, that a stage and a manual
baseline are refused with every failure listed and nothing approved, that the required-fields and required-approvals
checks judge what they say, the audit events and the bundles. The core seam runs without the module and is tested in
`tests/test_baseline_checks.py`."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import Project
from app.models.requirement import Baseline
from app.modules.seams import BaselinePolicy, GovernanceSeam
from app.modules.traceability import baseline_policy, bundle
from app.modules.traceability.models import GovernanceBaselinePolicy
from app.modules.traceability.tests.test_governance_profiles import _choose, _create, _exempt, _setup
from app.services import governance_seams
from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login
from tests.stage_helpers import move_stage

ORG = "/api/v1/orgs/{org}/modules/traceability"
PROJECT = "/api/v1/projects/{project}/modules/traceability"
FIELDS = "traceability:required_fields"
APPROVALS = "traceability:required_approvals"
DESCRIPTION = {"artefact_type": "requirement", "field_key": "description"}
REASONING = {"artefact_type": "requirement", "field_key": "reasoning"}


def _profile_url(org_id, profile_id, suffix="") -> str:
    return ORG.format(org=org_id) + f"/profiles/{profile_id}/baseline{suffix}"


def _project_url(project_id, suffix="/baseline-policy") -> str:
    return PROJECT.format(project=project_id) + suffix


def _settings(checks=(), fields=(), stage=True, manual=False, notify=True) -> dict:
    return {
        "applies_to_stage": stage, "applies_to_manual": manual, "notify_managers": notify, "checks": list(checks),
        "required_fields": list(fields),
    }


def _set_profile(client, token, org_id, profile_id, settings, status=200):
    resp = client.put(_profile_url(org_id, profile_id), json=settings, headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _set_project(client, token, project_id, settings, status=200):
    resp = client.put(_project_url(project_id), json={"settings": settings}, headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _policy(client, token, project_id) -> dict:
    resp = client.get(_project_url(project_id), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _part(client, token, org_id, enabled: bool) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/traceability/subcomponents/baseline_policies", json={"enabled": enabled},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _world(client, admin_token, name):
    """An organisation with Governance on, a project in it and its administrator's token."""
    org, token = _setup(client, admin_token, name)
    return org, create_project(client, token, org["id"], f"{name} project"), token


def _member(client, token, org_id, project_id, role="stakeholder") -> tuple[str, str]:
    email = f"baseline_policy_{uuid.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, token, org_id, email)
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


_SCOPES: dict[str, tuple[str, str]] = {}


def _requirement(client, token, project_id, name="Boot within 3s", **extra) -> dict:
    if project_id not in _SCOPES:
        _SCOPES[project_id] = create_component_and_category(client, token, project_id)
    component_id, category_id = _SCOPES[project_id]
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id, **extra}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _edit_requirement(client, token, project_id, requirement_id, **changes) -> None:
    current = client.get(f"/api/v1/projects/{project_id}/requirements/{requirement_id}", headers=auth_headers(token)).json()
    body = {
        "name": current["name"], "reasoning": current["reasoning"], "clarification": current["clarification"],
        "description": current["description"], "component_id": current["component_id"],
        "category_id": current["category_id"], "owner": current["owner"], **changes,
    }
    resp = client.put(f"/api/v1/projects/{project_id}/requirements/{requirement_id}", json=body, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _status(client, token, project_id, requirement_id) -> str:
    return client.get(f"/api/v1/projects/{project_id}/requirements/{requirement_id}", headers=auth_headers(token)).json()["status"]


def _stage_id(client, token, project_id) -> str:
    return client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(token)).json()[0]["id"]


def _lock(client, token, project_id):
    return move_stage(client, project_id, _stage_id(client, token, project_id), "approved", headers=auth_headers(token))


def _manual(client, token, project_id):
    return client.post(f"/api/v1/projects/{project_id}/baselines", json={"label": "Manual"}, headers=auth_headers(token))


def _baseline_count(project_id: str) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Baseline).where(Baseline.project_id == uuid.UUID(project_id))).all())


def _audit(entity_type: str, entity_id: str) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id,
        ).order_by(AuditEvent.created_at)))


# --- gating, permissions and validation ----------------------------------------------------------


def test_the_routes_are_not_found_while_the_part_is_off(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Part Off Org")
    profile = _create(client, token, org["id"], "Regulated")
    assert client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).status_code == 200
    assert client.get(_project_url(project["id"]), headers=auth_headers(token)).status_code == 200
    _part(client, token, org["id"], False)
    headers = auth_headers(token)
    assert client.get(_profile_url(org["id"], profile["id"]), headers=headers).status_code == 404
    assert client.put(_profile_url(org["id"], profile["id"]), json=_settings(), headers=headers).status_code == 404
    assert client.get(_profile_url(org["id"], profile["id"], f"/fields?project_id={project['id']}"), headers=headers).status_code == 404
    assert client.get(_project_url(project["id"]), headers=headers).status_code == 404
    assert client.put(_project_url(project["id"]), json={"settings": None}, headers=headers).status_code == 404
    assert client.get(_project_url(project["id"], "/baseline-checks?kind=manual"), headers=headers).status_code == 404


def test_only_a_holder_of_the_organisation_atom_sets_a_profiles_policy(client, admin_token):
    org, token = _setup(client, admin_token, "Baseline Org Permission Org")
    profile = _create(client, token, org["id"], "Regulated")
    create_org_user(client, token, org["id"], "baseline_org_member@example.com")
    member = login(client, "baseline_org_member@example.com", "Password123!")
    assert client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(member)).status_code == 403
    assert client.put(_profile_url(org["id"], profile["id"]), json=_settings(), headers=auth_headers(member)).status_code == 403
    other, other_token = _setup(client, admin_token, "Baseline Other Org")
    foreign = _create(client, other_token, other["id"], "Foreign")
    assert client.get(_profile_url(org["id"], foreign["id"]), headers=auth_headers(token)).status_code == 404


def test_only_a_holder_of_the_project_atom_sets_or_previews_a_projects_policy_and_any_member_reads_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Project Permission Org")
    _, stakeholder = _member(client, token, org["id"], project["id"])
    assert _policy(client, stakeholder, project["id"])["can_manage"] is False
    assert _policy(client, token, project["id"])["can_manage"] is True
    headers = auth_headers(stakeholder)
    assert client.put(_project_url(project["id"]), json={"settings": _settings()}, headers=headers).status_code == 403
    assert client.get(_project_url(project["id"], "/baseline-checks?kind=manual"), headers=headers).status_code == 403
    # A server administrator who is not a member holds no bypass: the part is not found for them.
    assert client.put(_project_url(project["id"]), json={"settings": None}, headers=auth_headers(admin_token)).status_code == 404


def test_the_policy_offers_the_two_checks_and_the_types_a_baseline_can_hold(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Options Org")
    profile = _create(client, token, org["id"], "Regulated")
    out = client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).json()
    assert out["settings"] == _settings()
    assert [(o["key"], o["name"], o["module_key"], o["artefact_types"]) for o in out["check_options"]] == [
        (FIELDS, "Required fields", "traceability", []), (APPROVALS, "Required approvals", "traceability", ["requirement"]),
    ]
    assert [(t["artefact_type"], t["label"]) for t in out["types"]] == [("requirement", "Requirement")]
    fields = _policy(client, token, project["id"])["field_options"]["requirement"]
    assert {"description", "reasoning", "owner"} <= {f["key"] for f in fields}
    assert "keywords" in {f["key"] for f in fields}
    assert client.get(
        _profile_url(org["id"], profile["id"], f"/fields?project_id={project['id']}"), headers=auth_headers(token),
    ).json()["types"]["requirement"] == fields


def test_the_profile_field_options_are_those_of_a_project_of_the_organisation_only(client, admin_token):
    org, token = _setup(client, admin_token, "Baseline Fields Org")
    other, other_token = _setup(client, admin_token, "Baseline Fields Other Org")
    foreign = create_project(client, other_token, other["id"], "Foreign project")
    profile = _create(client, token, org["id"], "Regulated")
    assert client.get(
        _profile_url(org["id"], profile["id"], f"/fields?project_id={foreign['id']}"), headers=auth_headers(token),
    ).status_code == 404


def test_values_are_validated_and_a_profile_takes_any_field_key_where_a_project_takes_only_its_own(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Validation Org")
    profile = _create(client, token, org["id"], "Regulated")
    neither = _settings(stage=False, manual=False)
    unknown_check = _settings(checks=["traceability:no_such_check"])
    unknown_type = _settings(checks=[FIELDS], fields=[{"artefact_type": "no_such_type", "field_key": "description"}])
    blank_key = _settings(checks=[FIELDS], fields=[{"artefact_type": "requirement", "field_key": " "}])
    for body in (neither, unknown_check, unknown_type, blank_key):
        _set_profile(client, token, org["id"], profile["id"], body, status=422)
        _set_project(client, token, project["id"], body, status=422)
    custom = _settings(checks=[FIELDS], fields=[{"artefact_type": "requirement", "field_key": "cf_safety_class"}])
    _set_profile(client, token, org["id"], profile["id"], custom)  # custom fields differ per project, so a profile cannot check it
    _set_project(client, token, project["id"], custom, status=422)


def test_settings_are_stored_read_back_and_an_empty_profile_row_is_removed(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Roundtrip Org")
    profile = _create(client, token, org["id"], "Regulated")
    body = _settings(checks=[APPROVALS, FIELDS, FIELDS], fields=[REASONING, DESCRIPTION, DESCRIPTION], stage=True, manual=True)
    out = _set_profile(client, token, org["id"], profile["id"], body)["settings"]
    assert out == _settings(checks=[APPROVALS, FIELDS], fields=[DESCRIPTION, REASONING], stage=True, manual=True)
    cleared = _set_profile(client, token, org["id"], profile["id"], _settings())["settings"]
    assert cleared == _settings()
    with SessionLocal() as db:
        assert db.scalars(select(GovernanceBaselinePolicy).where(GovernanceBaselinePolicy.profile_id == uuid.UUID(profile["id"]))).all() == []


def test_every_change_writes_one_audit_event_with_keys_only(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Audit Org")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], _settings(checks=[FIELDS], fields=[DESCRIPTION], manual=True))
    events = [e for e in _audit("governance_profile", profile["id"]) if e.action == "baseline_updated"]
    assert len(events) == 1
    assert events[0].detail == {
        "applies_to_stage": True, "applies_to_manual": True, "notify_managers": True, "checks": [FIELDS],
        "required_fields": {"requirement": ["description"]},
    }
    _set_project(client, token, project["id"], _settings(checks=[APPROVALS]))
    project_events = _audit("governance_baseline_policy", project["id"])
    assert [e.action for e in project_events] == ["updated"]
    assert (project_events[0].detail or {}).get("checks") == [APPROVALS]


# --- merging --------------------------------------------------------------------------------------


def _effective_checks(policy: dict) -> dict[str, dict]:
    return {c["key"]: c for c in policy["checks"]}


def test_each_source_keeps_the_baseline_kinds_it_chose_and_is_named(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Merge Org")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], _settings(checks=[FIELDS], fields=[DESCRIPTION], stage=True))
    _set_project(client, token, project["id"], _settings(checks=[APPROVALS, FIELDS], fields=[REASONING], stage=False, manual=True))
    policy = _policy(client, token, project["id"])
    checks = _effective_checks(policy)
    assert (checks[FIELDS]["stage"], checks[FIELDS]["manual"], checks[FIELDS]["sources"]) == (True, True, ["Regulated", "project"])
    assert (checks[APPROVALS]["stage"], checks[APPROVALS]["manual"], checks[APPROVALS]["sources"]) == (False, True, ["project"])
    assert all(c["available"] and c["name"] for c in policy["checks"])
    fields = {f["field_key"]: f for f in policy["required_fields"]}
    assert (fields["description"]["stage"], fields["description"]["manual"], fields["description"]["sources"]) == (True, False, ["Regulated"])
    assert (fields["reasoning"]["stage"], fields["reasoning"]["manual"], fields["reasoning"]["field_label"]) == (False, True, "Reasoning")
    with SessionLocal() as db:
        resolved = governance_seams.resolve_project_policy(db, uuid.UUID(project["id"]), GovernanceSeam.BASELINE)
        assert resolved == BaselinePolicy(stage_checks=(FIELDS,), manual_checks=(APPROVALS, FIELDS))
        assert baseline_policy.required_fields(db, uuid.UUID(project["id"]), "stage") == {"requirement": ("description",)}
        assert baseline_policy.required_fields(db, uuid.UUID(project["id"]), "manual") == {"requirement": ("reasoning",)}


def test_managers_are_notified_unless_every_applying_policy_switches_it_off(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Notify Org")
    profile = _create(client, token, org["id"], "Regulated")
    assert _policy(client, token, project["id"])["notify_managers"] is True  # no policy holds a check
    _set_project(client, token, project["id"], _settings(checks=[FIELDS], notify=False))
    assert _policy(client, token, project["id"])["notify_managers"] is False
    assert _policy(client, token, project["id"])["own"]["notify_managers"] is False
    with SessionLocal() as db:
        resolved = governance_seams.resolve_project_policy(db, uuid.UUID(project["id"]), GovernanceSeam.BASELINE)
        assert resolved == BaselinePolicy(stage_checks=(FIELDS,), notify_managers=False)
    # A profile that holds a check and asks for the notice cannot be switched off by the project.
    _set_profile(client, token, org["id"], profile["id"], _settings(checks=[APPROVALS], notify=True))
    assert _policy(client, token, project["id"])["notify_managers"] is True
    _set_profile(client, token, org["id"], profile["id"], _settings(checks=[APPROVALS], notify=False))
    assert _policy(client, token, project["id"])["notify_managers"] is False


def test_the_notify_flag_is_stored_audited_and_defaults_on(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Notify Store Org")
    profile = _create(client, token, org["id"], "Regulated")
    stored = _set_profile(client, token, org["id"], profile["id"], _settings(checks=[FIELDS], notify=False))
    assert stored["settings"]["notify_managers"] is False
    event = [e for e in _audit("governance_profile", profile["id"]) if e.action == "baseline_updated"][-1]
    assert (event.detail or {}).get("notify_managers") is False
    omitted = client.put(
        _profile_url(org["id"], profile["id"]), json={"checks": [FIELDS]}, headers=auth_headers(token),
    )
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["settings"]["notify_managers"] is True


def test_an_exempt_or_opted_out_project_does_not_get_a_profiles_policy(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Profile Reach Org")
    enforced = _create(client, token, org["id"], "Enforced")
    optional = _create(client, token, org["id"], "Optional", mode="opt_in")
    _set_profile(client, token, org["id"], enforced["id"], _settings(checks=[APPROVALS]))
    _set_profile(client, token, org["id"], optional["id"], _settings(checks=[FIELDS]))
    assert list(_effective_checks(_policy(client, token, project["id"]))) == [APPROVALS]
    _choose(client, token, project["id"], optional["id"], True)
    assert set(_effective_checks(_policy(client, token, project["id"]))) == {APPROVALS, FIELDS}
    _exempt(client, token, org["id"], enforced["id"], project["id"], reason="Sandbox")
    assert set(_effective_checks(_policy(client, token, project["id"]))) == {FIELDS}


def test_a_child_follows_its_parents_row_until_it_sets_its_own(client, admin_token):
    org, token = _setup(client, admin_token, "Baseline Nested Org")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    _set_project(client, token, parent["id"], _settings(checks=[APPROVALS]))
    policy = _policy(client, token, child["id"])
    assert policy["own"] is None and policy["inherited_from"] == "Parent"
    assert _effective_checks(policy)[APPROVALS]["sources"] == ["parent_project"]

    _set_project(client, token, child["id"], _settings())  # a choice of no baseline checks here
    policy = _policy(client, token, child["id"])
    assert policy["own"] == _settings() and policy["inherited_from"] is None and policy["checks"] == []

    _set_project(client, token, child["id"], _settings(checks=[FIELDS]))
    assert list(_effective_checks(_policy(client, token, child["id"]))) == [FIELDS]
    _set_project(client, token, child["id"], None)  # follows the parent again
    assert _policy(client, token, child["id"])["inherited_from"] == "Parent"


def test_the_contributor_counts_a_profiles_policy(client, admin_token):
    org, token = _setup(client, admin_token, "Baseline Count Org")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], _settings(checks=[FIELDS, APPROVALS]))
    detail = client.get(ORG.format(org=org["id"]) + f"/profiles/{profile['id']}", headers=auth_headers(token)).json()
    assert {c["key"]: c["count"] for c in detail["contributions"]}["traceability:baseline"] == 2


def test_switching_the_part_off_stops_the_policy_applying_and_keeps_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Off Org")
    _requirement(client, token, project["id"])
    _set_project(client, token, project["id"], _settings(checks=[FIELDS], fields=[DESCRIPTION], manual=True))
    assert _manual(client, token, project["id"]).status_code == 409
    _part(client, token, org["id"], False)
    assert _manual(client, token, project["id"]).status_code == 201  # the policy does not apply while its part is off
    _part(client, token, org["id"], True)
    assert _manual(client, token, project["id"]).status_code == 409  # and it was kept


# --- required fields ------------------------------------------------------------------------------


def test_a_stage_baseline_is_refused_with_every_blank_required_field_and_nothing_is_approved(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Fields Stage Org")
    bare = _requirement(client, token, project["id"], "Bare")
    half = _requirement(client, token, project["id"], "Half", description="Described")
    full = _requirement(client, token, project["id"], "Full", description="Described", reasoning="Because")
    _set_project(client, token, project["id"], _settings(checks=[FIELDS], fields=[DESCRIPTION, REASONING]))

    refused = _lock(client, token, project["id"])
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["message"] == "The baseline was refused: 2 records failed 1 baseline check. Nothing was approved or stored."
    by_message = sorted((f["code"], f["message"]) for f in detail["failures"])
    assert by_message == sorted([
        (bare["unique_code"], "The field Description is required and is blank."),
        (bare["unique_code"], "The field Reasoning is required and is blank."),
        (half["unique_code"], "The field Reasoning is required and is blank."),
    ])
    assert {f["check_name"] for f in detail["failures"]} == {"Required fields"}
    assert all(f["artefact_type"] == "requirement" for f in detail["failures"])
    for requirement in (bare, half, full):
        assert _status(client, token, project["id"], requirement["id"]) == "draft"
    assert _baseline_count(project["id"]) == 0

    _edit_requirement(client, token, project["id"], bare["id"], description="Now described", reasoning="Now reasoned")
    _edit_requirement(client, token, project["id"], half["id"], reasoning="Now reasoned")
    assert _lock(client, token, project["id"]).status_code == 200
    assert _status(client, token, project["id"], bare["id"]) == "approved"
    assert _baseline_count(project["id"]) == 1


def test_a_policy_for_stage_baselines_does_not_stop_a_manual_baseline_and_the_preview_agrees(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Kinds Org")
    requirement = _requirement(client, token, project["id"])
    _set_project(client, token, project["id"], _settings(checks=[FIELDS], fields=[DESCRIPTION], stage=True, manual=False))
    assert _manual(client, token, project["id"]).status_code == 201
    stage_id = _stage_id(client, token, project["id"])
    headers = auth_headers(token)
    preview = client.get(_project_url(project["id"], f"/baseline-checks?kind=stage&stage_id={stage_id}"), headers=headers).json()
    assert preview["kind"] == "stage" and preview["checks"] == [{"key": FIELDS, "name": "Required fields"}]
    assert [(f["code"], f["message"]) for f in preview["failures"]] == [
        (requirement["unique_code"], "The field Description is required and is blank."),
    ]
    manual = client.get(_project_url(project["id"], "/baseline-checks?kind=manual"), headers=headers).json()
    assert manual["checks"] == [] and manual["failures"] == []
    assert client.get(_project_url(project["id"], "/baseline-checks?kind=stage"), headers=headers).status_code == 422
    assert _baseline_count(project["id"]) == 1  # the preview wrote nothing
    assert _status(client, token, project["id"], requirement["id"]) == "draft"


def test_a_required_field_the_project_has_no_column_for_is_skipped(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Skipped Field Org")
    _requirement(client, token, project["id"])
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], _settings(
        checks=[FIELDS], fields=[{"artefact_type": "requirement", "field_key": "cf_unknown_here"}], manual=True,
    ))
    policy = _policy(client, token, project["id"])
    assert [(f["field_key"], f["field_label"]) for f in policy["required_fields"]] == [("cf_unknown_here", None)]
    assert _manual(client, token, project["id"]).status_code == 201


# --- required approvals ---------------------------------------------------------------------------


def test_a_manual_baseline_demands_requirements_that_are_already_approved(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Manual Approvals Org")
    first = _requirement(client, token, project["id"], "First")
    second = _requirement(client, token, project["id"], "Second")
    _set_project(client, token, project["id"], _settings(checks=[APPROVALS], stage=False, manual=True))
    refused = _manual(client, token, project["id"])
    assert refused.status_code == 409
    failures = refused.json()["detail"]["failures"]
    assert sorted(f["code"] for f in failures) == sorted([first["unique_code"], second["unique_code"]])
    assert {f["message"] for f in failures} == {"The requirement is not approved (status draft)."}
    for requirement in (first, second):
        approved = client.post(
            f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve", json={}, headers=auth_headers(token),
        )
        assert approved.status_code == 200, approved.text
    assert _manual(client, token, project["id"]).status_code == 201


def test_a_stage_baseline_lists_every_draft_the_separation_rule_bars_the_person_from_approving(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Stage Approvals Org")
    _, manager = _member(client, token, org["id"], project["id"], role="project_manager")
    mine = _requirement(client, manager, project["id"], "Mine")
    also_mine = _requirement(client, manager, project["id"], "Also mine")
    theirs = _requirement(client, token, project["id"], "Theirs")
    resp = client.put(
        f"/api/v1/projects/{project['id']}/approval-separation/requirement", json={"separate_approver": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    _set_project(client, token, project["id"], _settings(checks=[APPROVALS]))

    refused = _lock(client, manager, project["id"])
    assert refused.status_code == 409, refused.text
    failures = refused.json()["detail"]["failures"]
    assert sorted(f["code"] for f in failures) == sorted([mine["unique_code"], also_mine["unique_code"]])
    assert all("separate approver is required" in f["message"] for f in failures)
    assert _status(client, manager, project["id"], theirs["id"]) == "draft"
    assert _baseline_count(project["id"]) == 0
    # The other manager is barred from the one record they created, and only that one.
    other = _lock(client, token, project["id"])
    assert other.status_code == 409
    assert [f["code"] for f in other.json()["detail"]["failures"]] == [theirs["unique_code"]]
    assert _baseline_count(project["id"]) == 0


# --- bundles ---------------------------------------------------------------------------------------


def test_a_projects_own_policy_travels_in_its_bundle(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Project Bundle Org")
    _set_project(client, token, project["id"], _settings(checks=[FIELDS, APPROVALS], fields=[DESCRIPTION], stage=True, manual=True))
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json"))
    assert data[bundle.BASELINE_POLICY_KEY] == {
        "applies_to_stage": True, "applies_to_manual": True, "notify_managers": True, "checks": [APPROVALS, FIELDS],
        "required_fields": [{"artefact_type": "requirement", "fields": ["description"]}],
    }
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copied = _policy(client, token, imported.json()["project"]["id"])["own"]
    assert copied == _settings(checks=[APPROVALS, FIELDS], fields=[DESCRIPTION], stage=True, manual=True)


def test_the_notify_flag_travels_in_the_project_bundle(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Notify Bundle Org")
    _set_project(client, token, project["id"], _settings(checks=[FIELDS], notify=False))
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Notify Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    assert _policy(client, token, imported.json()["project"]["id"])["own"]["notify_managers"] is False


def test_a_project_import_leaves_out_what_the_organisation_cannot_use_and_says_so(client, admin_token):
    org, project, token = _world(client, admin_token, "Baseline Import Warning Org")
    warnings: list[str] = []
    entry = {
        "applies_to_stage": False, "applies_to_manual": False,
        "checks": [FIELDS, "someone_else:their_check"],
        "required_fields": [
            {"artefact_type": "requirement", "fields": ["description", "no_such_column"]},
            {"artefact_type": "no_such_type", "fields": ["x"]},
        ],
    }
    with SessionLocal() as db:
        row = db.get(Project, uuid.UUID(project["id"]))
        assert row is not None
        baseline_policy.import_project_row(db, row, entry, warnings.append)
        assert len(warnings) == 3
        assert any("someone_else:their_check" in w for w in warnings)
        assert any("no_such_column" in w for w in warnings)
        assert any("no_such_type" in w for w in warnings)
        stored = baseline_policy.export_project_row(db, row)
        db.rollback()
    # A policy naming neither baseline kind takes the default (stage baselines).
    assert stored == {
        "applies_to_stage": True, "applies_to_manual": False, "notify_managers": True, "checks": [FIELDS],
        "required_fields": [{"artefact_type": "requirement", "fields": ["description"]}],
    }


def test_a_profiles_policy_travels_in_the_organisation_bundle(client, admin_token):
    org, token = _setup(client, admin_token, "Baseline Org Bundle Org")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], _settings(checks=[FIELDS], fields=[DESCRIPTION], manual=True))
    exported = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("org.json"))
    entry = next(e for e in data["governance_profiles"] if e["name"] == "Regulated")
    [row] = entry["contributions"]["traceability:baseline"]
    assert row["kind"] == "baseline" and row["checks"] == [FIELDS] and row["applies_to_manual"] is True

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Baseline Org Bundle Imported Org"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code in (200, 201), imported.text
    new_org = imported.json().get("id") or imported.json()["organization"]["id"]
    from app.modules.traceability.models import GovernanceProfile

    with SessionLocal() as db:
        new_profile = db.scalars(select(GovernanceProfile).where(
            GovernanceProfile.organization_id == uuid.UUID(new_org), GovernanceProfile.name == "Regulated",
        )).one()
        assert baseline_policy.profile_policy(db, new_profile) == baseline_policy.BaselineSettings(
            True, True, (FIELDS,), (baseline_policy.RequiredField("requirement", "description"),), True,
        )


def test_the_baseline_policy_is_template_configuration():
    from app.modules.registry import get_module

    module = get_module("traceability")
    assert module is not None and module.project_bundle_hooks is not None
    assert bundle.BASELINE_POLICY_KEY in module.project_bundle_hooks.template_configuration_keys


def test_every_type_a_baseline_holds_that_has_an_approval_gate_is_judged_by_the_approval_check():
    """A type with both an approval gate and a snapshot provider needs its own entry in `required_approvals`."""
    from app.modules import registry
    from app.modules.traceability import baseline_checks
    from app.services import approval_separation

    gated = set(approval_separation.approval_gates())
    held = {"requirement", *registry.get_baseline_snapshot_providers()}
    assert (gated & held) <= set(baseline_checks.APPROVAL_CHECKED_TYPES)
