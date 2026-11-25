"""Tests for the lifecycle policy of governance profiles (`modules.traceability.lifecycle_policy`, the profile routes under
`/profiles/{id}/lifecycle`): who may set it, what it validates, how it binds the projects a profile applies to (Enforced,
exempt, Default and opted out, Opt-in), how several sources merge (the organisation's requirement and several profiles
unite, any profile may forbid skipping), what switching the part off does, the audit events, the counts beside a
profile and the organisation bundle round trip."""

from __future__ import annotations

import io
import json
import uuid as uuid_lib
import zipfile

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.traceability import lifecycle_policy
from app.modules.traceability.models import GovernanceLifecycleRequirement, GovernanceLifecycleSkipPolicy, GovernanceProfile
from app.modules.traceability.tests.test_governance_profiles import _choose, _create, _exempt, _setup
from tests.conftest import auth_headers, create_org_user, create_project

BASE = "/api/v1/orgs/{org}/modules/traceability/profiles/{profile}/lifecycle"
PROJECT_LIFECYCLES = "/api/v1/projects/{project}/lifecycles"


def _policy_url(org_id, profile_id, suffix="") -> str:
    return BASE.format(org=org_id, profile=profile_id) + suffix


def _require(client, token, org_id, profile_id, artefact_type, states, status=200):
    resp = client.put(
        _policy_url(org_id, profile_id, f"/{artefact_type}"), json={"required": states}, headers=auth_headers(token)
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _forbid_skip(client, token, org_id, profile_id, forbidden=True):
    resp = client.put(_policy_url(org_id, profile_id, "/skip"), json={"forbidden": forbidden}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _lifecycles(client, token, project_id) -> dict:
    resp = client.get(PROJECT_LIFECYCLES.format(project=project_id), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _lifecycle(client, token, project_id, artefact_type) -> dict:
    return next(x for x in _lifecycles(client, token, project_id)["lifecycles"] if x["artefact_type"] == artefact_type)


def _turn_off(client, token, project_id, artefact_type, states):
    return client.put(
        PROJECT_LIFECYCLES.format(project=project_id) + f"/{artefact_type}", json={"disabled_states": states},
        headers=auth_headers(token),
    )


def _enable_decisions(client, token, org_id) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/decisions", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _audit(profile_id: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == "governance_profile", AuditEvent.entity_id == profile_id,
        ).order_by(AuditEvent.created_at)))
    finally:
        db.close()


# --- gating and validation ------------------------------------------------------------------


def test_the_lifecycle_routes_are_not_found_while_the_part_is_off(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Part Off Org")
    profile = _create(client, token, org["id"], "Regulated")
    url = _policy_url(org["id"], profile["id"])
    assert client.get(url, headers=auth_headers(token)).status_code == 200
    off = client.put(
        f"/api/v1/orgs/{org['id']}/modules/traceability/subcomponents/lifecycle_policies", json={"enabled": False},
        headers=auth_headers(token),
    )
    assert off.status_code == 200, off.text
    assert client.get(url, headers=auth_headers(token)).status_code == 404
    assert client.put(url + "/requirement", json={"required": []}, headers=auth_headers(token)).status_code == 404
    assert client.put(url + "/skip", json={"forbidden": True}, headers=auth_headers(token)).status_code == 404


def test_only_a_holder_of_the_organisation_atom_sets_a_profiles_lifecycle_policy(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Permission Org")
    profile = _create(client, token, org["id"], "Regulated")
    create_org_user(client, token, org["id"], "lifecycle_policy_member@example.com")
    member = client.post(
        "/api/v1/auth/login", json={"email": "lifecycle_policy_member@example.com", "password": "Password123!"}
    ).json()["access_token"]
    url = _policy_url(org["id"], profile["id"])
    assert client.get(url, headers=auth_headers(member)).status_code == 403
    assert client.put(url + "/requirement", json={"required": ["reviewed"]}, headers=auth_headers(member)).status_code == 403
    assert client.put(url + "/skip", json={"forbidden": True}, headers=auth_headers(member)).status_code == 403


def test_a_profile_of_another_organisation_is_not_found(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Own Org")
    other, other_token = _setup(client, admin_token, "Lifecycle Policy Other Org")
    foreign = _create(client, other_token, other["id"], "Foreign")
    assert client.get(_policy_url(org["id"], foreign["id"]), headers=auth_headers(token)).status_code == 404
    assert client.put(
        _policy_url(org["id"], foreign["id"], "/requirement"), json={"required": []}, headers=auth_headers(token)
    ).status_code == 404


def test_the_policy_lists_the_types_with_optional_states_the_organisation_can_use(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Listing Org")
    profile = _create(client, token, org["id"], "Regulated")
    url = _policy_url(org["id"], profile["id"])
    before = {t["artefact_type"]: t for t in client.get(url, headers=auth_headers(token)).json()["types"]}
    assert "requirement" in before and "decision" not in before
    assert before["requirement"]["module_key"] == ""
    assert [s["key"] for s in before["requirement"]["states"]] == ["reviewed"]
    assert before["requirement"]["states"][0]["label"] == "Reviewed"
    assert "change_request" not in before  # no optional state, so nothing a profile can require

    _enable_decisions(client, token, org["id"])
    after = {t["artefact_type"]: t for t in client.get(url, headers=auth_headers(token)).json()["types"]}
    assert [s["key"] for s in after["decision"]["states"]] == ["proposed", "under_review"]


def test_a_profile_requires_only_optional_states_of_a_registered_type(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Validation Org")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], "no_such_type", [], status=404)
    _require(client, token, org["id"], profile["id"], "requirement", ["approved"], status=422)  # gated, never optional
    _require(client, token, org["id"], profile["id"], "requirement", ["draft"], status=422)  # the start of the path
    _require(client, token, org["id"], profile["id"], "requirement", ["nonsense"], status=422)
    shown = _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    assert next(t for t in shown["types"] if t["artefact_type"] == "requirement")["required"] == ["reviewed"]
    cleared = _require(client, token, org["id"], profile["id"], "requirement", [])
    assert next(t for t in cleared["types"] if t["artefact_type"] == "requirement")["required"] == []


def test_every_change_writes_one_audit_event_with_keys_only(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Audit Org")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    _forbid_skip(client, token, org["id"], profile["id"])
    events = {e.action: e.detail for e in _audit(profile["id"])}
    assert events["lifecycle_updated"] == {"artefact_type": "requirement", "required_states": ["reviewed"]}
    assert events["lifecycle_skip_updated"] == {"forbidden": True}


# --- how it binds projects ------------------------------------------------------------------


def test_an_enforced_profile_requires_the_state_in_every_project_it_reaches_until_it_is_exempt(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Enforced Org")
    bound = create_project(client, token, org["id"], "Bound")
    exempt = create_project(client, token, org["id"], "Exempt")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    _exempt(client, token, org["id"], profile["id"], exempt["id"], reason="Pilot")

    shown = _lifecycle(client, token, bound["id"], "requirement")
    assert shown["required"] == ["reviewed"] and shown["required_by_profiles"] == {"reviewed": ["Regulated"]}
    assert shown["exempt"] is False
    assert "reviewed" in {n for moves in shown["transitions"].values() for n in moves}
    refused = _turn_off(client, token, bound["id"], "requirement", ["reviewed"])
    assert refused.status_code == 409, refused.text

    free = _lifecycle(client, token, exempt["id"], "requirement")
    assert free["required"] == [] and free["required_by_profiles"] == {}
    assert _turn_off(client, token, exempt["id"], "requirement", ["reviewed"]).status_code == 200
    assert _lifecycle(client, token, exempt["id"], "requirement")["disabled"] == ["reviewed"]


def test_a_requirement_wins_over_a_choice_the_project_stored_earlier(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Stored Choice Org")
    project = create_project(client, token, org["id"], "Stored")
    assert _turn_off(client, token, project["id"], "requirement", ["reviewed"]).status_code == 200
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    bound = _lifecycle(client, token, project["id"], "requirement")
    assert bound["disabled"] == [] and bound["required"] == ["reviewed"]
    assert bound["own_disabled"] == ["reviewed"]  # the project's choice is kept
    client.delete(f"/api/v1/orgs/{org['id']}/modules/traceability/profiles/{profile['id']}", headers=auth_headers(token))
    assert _lifecycle(client, token, project["id"], "requirement")["disabled"] == ["reviewed"]


def test_a_default_profile_applies_until_the_project_opts_out(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Default Org")
    project = create_project(client, token, org["id"], "Defaulted")
    profile = _create(client, token, org["id"], "Shared defaults", mode="default")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == ["reviewed"]
    _choose(client, token, project["id"], profile["id"], False)
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == []
    _choose(client, token, project["id"], profile["id"], None)
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == ["reviewed"]


def test_an_opt_in_profile_applies_only_where_the_project_chooses_it(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Opt In Org")
    project = create_project(client, token, org["id"], "Chooser")
    profile = _create(client, token, org["id"], "Optional", mode="opt_in")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == []
    _choose(client, token, project["id"], profile["id"], True)
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == ["reviewed"]


def test_a_profile_that_does_not_reach_a_project_does_not_bind_it(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Targets Org")
    reached = create_project(client, token, org["id"], "Reached")
    other = create_project(client, token, org["id"], "Other")
    profile = _create(
        client, token, org["id"], "Selected", target_kind="selected_projects",
        targets=[{"project_id": reached["id"], "include_children": False}],
    )
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    assert _lifecycle(client, token, reached["id"], "requirement")["required"] == ["reviewed"]
    assert _lifecycle(client, token, other["id"], "requirement")["required"] == []


def test_the_organisations_requirement_and_several_profiles_unite(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Merge Org")
    _enable_decisions(client, token, org["id"])
    project = create_project(client, token, org["id"], "Merged")
    first = _create(client, token, org["id"], "Alpha")
    second = _create(client, token, org["id"], "Beta")
    _require(client, token, org["id"], first["id"], "decision", ["proposed"])
    _require(client, token, org["id"], second["id"], "decision", ["proposed", "under_review"])
    organisation = client.put(
        f"/api/v1/orgs/{org['id']}/lifecycles/decision", json={"required_states": ["proposed"]}, headers=auth_headers(token),
    )
    assert organisation.status_code == 200, organisation.text

    shown = _lifecycle(client, token, project["id"], "decision")
    assert shown["required"] == ["proposed", "under_review"]
    assert shown["required_by_profiles"] == {"proposed": ["Alpha", "Beta"], "under_review": ["Beta"]}
    assert _turn_off(client, token, project["id"], "decision", ["under_review"]).status_code == 409

    # Exempting the project from the organisation's requirement does not lift a profile's.
    exempt = client.post(
        f"/api/v1/orgs/{org['id']}/lifecycles/decision/exemptions", json={"project_id": project["id"]}, headers=auth_headers(token),
    )
    assert exempt.status_code == 200, exempt.text
    still = _lifecycle(client, token, project["id"], "decision")
    assert still["exempt"] is True and still["required"] == ["proposed", "under_review"]


def test_a_nested_project_is_bound_through_a_target_that_includes_children(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Nested Org")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    profile = _create(
        client, token, org["id"], "Tree", target_kind="selected_projects",
        targets=[{"project_id": parent["id"], "include_children": True}],
    )
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    assert _lifecycle(client, token, child["id"], "requirement")["required"] == ["reviewed"]


def test_switching_the_part_off_in_a_project_removes_the_profiles_effect_and_keeps_its_rows(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Switch Off Org")
    project = create_project(client, token, org["id"], "Switched")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == ["reviewed"]

    url = f"/api/v1/projects/{project['id']}/modules/traceability/subcomponents/lifecycle_policies"
    assert client.put(url, json={"enabled": False}, headers=auth_headers(token)).status_code == 200
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == []
    assert client.put(url, json={"enabled": True}, headers=auth_headers(token)).status_code == 200
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == ["reviewed"]


def test_a_project_without_the_module_is_not_bound(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Module Off Project Org")
    project = create_project(client, token, org["id"], "Plain")
    profile = _create(client, token, org["id"], "Regulated")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    off = client.put(
        f"/api/v1/projects/{project['id']}/modules/traceability/enablement", json={"enabled": False},
        headers=auth_headers(token),
    )
    assert off.status_code == 200, off.text
    assert _lifecycle(client, token, project["id"], "requirement")["required"] == []


# --- skipping steps -------------------------------------------------------------------------


def test_a_profile_that_forbids_skipping_binds_its_projects_and_names_itself(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Skip Org")
    project = create_project(client, token, org["id"], "Skipper")
    profile = _create(client, token, org["id"], "No skipping")
    assert _lifecycles(client, token, project["id"])["skip"]["forbidden"] is False
    _forbid_skip(client, token, org["id"], profile["id"])

    skip = _lifecycles(client, token, project["id"])["skip"]
    assert skip["forbidden"] is True and skip["forbidden_by_profiles"] == ["No skipping"] and skip["allowed"] is False
    refused = client.put(
        PROJECT_LIFECYCLES.format(project=project["id"]) + "/skip", json={"allowed": True}, headers=auth_headers(token),
    )
    assert refused.status_code == 409, refused.text

    _exempt(client, token, org["id"], profile["id"], project["id"])
    assert _lifecycles(client, token, project["id"])["skip"]["forbidden"] is False
    allowed = client.put(
        PROJECT_LIFECYCLES.format(project=project["id"]) + "/skip", json={"allowed": True}, headers=auth_headers(token),
    )
    assert allowed.status_code == 200, allowed.text


def test_an_organisation_exemption_from_the_ban_does_not_lift_a_profiles_ban(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Skip Exempt Org")
    project = create_project(client, token, org["id"], "Doubly bound")
    profile = _create(client, token, org["id"], "No skipping")
    _forbid_skip(client, token, org["id"], profile["id"])
    assert client.put(
        f"/api/v1/orgs/{org['id']}/lifecycles/skip", json={"forbidden": True}, headers=auth_headers(token)
    ).status_code == 200
    assert client.post(
        f"/api/v1/orgs/{org['id']}/lifecycles/skip/exemptions", json={"project_id": project["id"]}, headers=auth_headers(token),
    ).status_code == 200
    skip = _lifecycles(client, token, project["id"])["skip"]
    assert skip["forbidden"] is True and skip["exempt"] is False and skip["forbidden_by_profiles"] == ["No skipping"]


# --- the contributor ------------------------------------------------------------------------


def test_deleting_a_profile_removes_its_lifecycle_rows(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Delete Org")
    profile = _create(client, token, org["id"], "Doomed")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    _forbid_skip(client, token, org["id"], profile["id"])
    assert client.delete(
        f"/api/v1/orgs/{org['id']}/modules/traceability/profiles/{profile['id']}", headers=auth_headers(token)
    ).status_code == 204
    db = SessionLocal()
    try:
        pid = uuid_lib.UUID(profile["id"])
        assert db.scalar(select(GovernanceLifecycleRequirement.id).where(GovernanceLifecycleRequirement.profile_id == pid)) is None
        assert db.scalar(select(GovernanceLifecycleSkipPolicy.id).where(GovernanceLifecycleSkipPolicy.profile_id == pid)) is None
    finally:
        db.close()


def test_the_profile_list_counts_the_lifecycle_policy_it_holds(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Count Org")
    _enable_decisions(client, token, org["id"])
    profile = _create(client, token, org["id"], "Counted")
    empty = _create(client, token, org["id"], "Empty")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    _require(client, token, org["id"], profile["id"], "decision", ["proposed", "under_review"])
    _forbid_skip(client, token, org["id"], profile["id"])
    listed = {
        p["name"]: {c["key"]: c for c in p["contributions"]}
        for p in client.get(f"/api/v1/orgs/{org['id']}/modules/traceability/profiles", headers=auth_headers(token)).json()
    }
    assert listed["Counted"]["traceability:lifecycle"]["count"] == 3  # two types and the ban on skipping
    assert listed["Counted"]["traceability:lifecycle"]["name"] == "Lifecycle policy"
    assert listed["Empty"]["traceability:lifecycle"]["count"] == 0
    assert empty["id"]


def test_the_profile_list_leaves_the_kind_out_while_the_part_is_off(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Count Off Org")
    _create(client, token, org["id"], "Quiet")
    client.put(
        f"/api/v1/orgs/{org['id']}/modules/traceability/subcomponents/lifecycle_policies", json={"enabled": False},
        headers=auth_headers(token),
    )
    listed = client.get(f"/api/v1/orgs/{org['id']}/modules/traceability/profiles", headers=auth_headers(token)).json()
    assert all(c["key"] != "traceability:lifecycle" for p in listed for c in p["contributions"])


def test_a_profile_without_lifecycle_policy_resolves_to_nothing(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Nothing Org")
    project = create_project(client, token, org["id"], "Plain")
    _create(client, token, org["id"], "Empty")
    db = SessionLocal()
    try:
        assert lifecycle_policy.resolve_project_policy(db, uuid_lib.UUID(project["id"])) is None
    finally:
        db.close()


# --- the organisation bundle ----------------------------------------------------------------


def _export(client, token, org_id) -> bytes:
    resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def _rows(org_id: str) -> dict[str, dict]:
    """Each profile's lifecycle rows by profile name."""
    db = SessionLocal()
    try:
        out: dict[str, dict] = {}
        for profile in db.scalars(select(GovernanceProfile).where(GovernanceProfile.organization_id == uuid_lib.UUID(org_id))):
            out[profile.name] = {
                "required": sorted(
                    (r.artefact_type, r.state) for r in db.scalars(
                        select(GovernanceLifecycleRequirement).where(GovernanceLifecycleRequirement.profile_id == profile.id)
                    )
                ),
                "skip_forbidden": bool(db.scalar(
                    select(GovernanceLifecycleSkipPolicy.forbidden).where(GovernanceLifecycleSkipPolicy.profile_id == profile.id)
                )),
            }
        return out
    finally:
        db.close()


def test_lifecycle_policy_travels_with_its_profile_in_the_organisation_bundle(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Bundle Source Org")
    _enable_decisions(client, token, org["id"])
    profile = _create(client, token, org["id"], "Regulated")
    _create(client, token, org["id"], "Bare")
    _require(client, token, org["id"], profile["id"], "requirement", ["reviewed"])
    _require(client, token, org["id"], profile["id"], "decision", ["under_review"])
    _forbid_skip(client, token, org["id"], profile["id"])
    expected = {
        "Regulated": {"required": [("decision", "under_review"), ("requirement", "reviewed")], "skip_forbidden": True},
        "Bare": {"required": [], "skip_forbidden": False},
    }
    assert _rows(org["id"]) == expected

    bundle_bytes = _export(client, token, org["id"])
    exported = json.loads(zipfile.ZipFile(io.BytesIO(bundle_bytes)).read("org.json"))
    entry = next(e for e in exported["governance_profiles"] if e["name"] == "Regulated")
    assert entry["contributions"]["traceability:lifecycle"] == [
        {"kind": "required_states", "artefact_type": "decision", "states": ["under_review"]},
        {"kind": "required_states", "artefact_type": "requirement", "states": ["reviewed"]},
        {"kind": "skip", "forbidden": True},
    ]
    assert next(e for e in exported["governance_profiles"] if e["name"] == "Bare")["contributions"] == {}

    resp = client.post(
        "/api/v1/orgs/import", data={"name": "Lifecycle Policy Bundle Imported Org"},
        files={"file": ("bundle.zip", bundle_bytes, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code in (200, 201), resp.text
    imported_id = resp.json().get("id") or resp.json()["organization"]["id"]
    assert _rows(imported_id) == expected


def test_an_import_skips_what_is_no_longer_registered_and_says_so(client, admin_token):
    org, token = _setup(client, admin_token, "Lifecycle Policy Import Warn Org")
    profile = _create(client, token, org["id"], "Target")
    warnings: list[str] = []
    db = SessionLocal()
    try:
        lifecycle_policy.import_rows(
            db, uuid_lib.UUID(profile["id"]),
            [
                {"kind": "required_states", "artefact_type": "gone_type", "states": ["x"]},
                {"kind": "required_states", "artefact_type": "requirement", "states": ["approved"]},
                {"kind": "mystery"},
                {"kind": "required_states", "artefact_type": "requirement", "states": ["reviewed"]},
            ],
            warnings.append,
        )
        db.commit()
    finally:
        db.close()
    assert len(warnings) == 3
    assert any("gone_type" in w for w in warnings) and any("unknown kind" in w for w in warnings)
    assert _rows(org["id"])["Target"]["required"] == [("requirement", "reviewed")]


@pytest.mark.parametrize("states", [["reviewed", "reviewed"]])
def test_repeating_a_state_requires_it_once(client, admin_token, states):
    org, token = _setup(client, admin_token, "Lifecycle Policy Repeat Org")
    profile = _create(client, token, org["id"], "Regulated")
    shown = _require(client, token, org["id"], profile["id"], "requirement", states)
    assert next(t for t in shown["types"] if t["artefact_type"] == "requirement")["required"] == ["reviewed"]
    assert _rows(org["id"])["Regulated"]["required"] == [("requirement", "reviewed")]
