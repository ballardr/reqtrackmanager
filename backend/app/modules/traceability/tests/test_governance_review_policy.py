"""Tests for the review policy of governance (`modules.traceability.review_policy`, the routes under `/profiles/{id}/review`
and `/review-policies`): who may set it, what it validates, how a project's settings merge from profiles, its own row and the
nearest ancestor's, that the reminder sweep follows the policy (lead, default owner) and ignores it while its part is off,
the audit events, and the bundles. The engine itself runs without the module and is tested in
`tests/test_review_engine.py`."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.seams import ReviewPolicy
from app.modules.traceability import bundle
from app.modules.traceability.models import GovernanceReviewPolicy
from app.modules.traceability.tests.test_governance_profiles import _choose, _create, _exempt, _setup
from app.services import review_engine
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
    login,
)

ORG = "/api/v1/orgs/{org}/modules/traceability"
PROJECT = "/api/v1/projects/{project}/modules/traceability"
# The server's day for a request that names none, so the tests do not depend on the host's timezone.
TODAY = datetime.now(UTC).date()


def _profile_url(org_id, profile_id, suffix="") -> str:
    return ORG.format(org=org_id) + f"/profiles/{profile_id}/review{suffix}"


def _project_url(project_id, suffix="") -> str:
    return PROJECT.format(project=project_id) + f"/review-policies{suffix}"


def _principal(kind: str, principal_id) -> dict:
    return {"type": kind, "id": str(principal_id)}


def _set_profile(client, token, org_id, profile_id, artefact_type, settings, status=200):
    resp = client.put(_profile_url(org_id, profile_id, f"/{artefact_type}"), json=settings, headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _set_project(client, token, project_id, artefact_type, settings, status=200):
    resp = client.put(
        _project_url(project_id, f"/{artefact_type}"), json={"settings": settings}, headers=auth_headers(token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _policy(client, token, project_id) -> dict:
    resp = client.get(_project_url(project_id), headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry(payload: dict, artefact_type: str = "requirement") -> dict:
    return next(t for t in payload["types"] if t["artefact_type"] == artefact_type)


def _effective(client, token, project_id) -> dict:
    return _entry(_policy(client, token, project_id))["effective"]


def _part(client, token, org_id, enabled: bool) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/traceability/subcomponents/review_policies", json={"enabled": enabled},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _member(client, token, org_id, project_id, role="stakeholder") -> tuple[str, str]:
    email = f"review_policy_{uuid.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, token, org_id, email)
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


_SCOPES: dict[str, tuple[str, str]] = {}


def _requirement(client, token, project_id, *, review_date: date | None, name="Reviewed", **extra) -> dict:
    if project_id not in _SCOPES:
        _SCOPES[project_id] = create_component_and_category(client, token, project_id)
    component_id, category_id = _SCOPES[project_id]
    body = {"name": name, "component_id": component_id, "category_id": category_id, **extra}
    if review_date is not None:
        body["review_date"] = review_date.isoformat()
    resp = client.post(f"/api/v1/projects/{project_id}/requirements", json=body, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _reminded(client, token) -> list[str]:
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [r["entity_id"] for r in rows if r["type"] == "requirement_review_due"]


def _sweep(today: date | None = None) -> int:
    db = SessionLocal()
    try:
        return review_engine.send_review_reminders(db, today)
    finally:
        db.close()


def _audit(entity_type: str, entity_id: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id,
        ).order_by(AuditEvent.created_at)))
    finally:
        db.close()


def _world(client, admin_token, name):
    """An organisation with Governance on and a project in it."""
    org, token = _setup(client, admin_token, name)
    return org, create_project(client, token, org["id"], f"{name} project"), token


# --- gating, permissions and validation ----------------------------------------------------------


def test_the_routes_are_not_found_while_the_part_is_off(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Part Off Org")
    profile = _create(client, token, org["id"], "Regulated")
    assert client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).status_code == 200
    assert client.get(_project_url(project["id"]), headers=auth_headers(token)).status_code == 200
    _part(client, token, org["id"], False)
    assert client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).status_code == 404
    assert client.put(_profile_url(org["id"], profile["id"], "/requirement"), json={}, headers=auth_headers(token)).status_code == 404
    assert client.get(_project_url(project["id"]), headers=auth_headers(token)).status_code == 404
    assert client.put(
        _project_url(project["id"], "/requirement"), json={"settings": {}}, headers=auth_headers(token),
    ).status_code == 404


def test_only_a_holder_of_the_organisation_atom_sets_a_profiles_settings(client, admin_token):
    org, token = _setup(client, admin_token, "Review Org Permission Org")
    profile = _create(client, token, org["id"], "Regulated")
    create_org_user(client, token, org["id"], "review_org_member@example.com")
    member = login(client, "review_org_member@example.com", "Password123!")
    assert client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(member)).status_code == 403
    assert client.put(
        _profile_url(org["id"], profile["id"], "/requirement"), json={"interval_days": 30}, headers=auth_headers(member),
    ).status_code == 403
    other, other_token = _setup(client, admin_token, "Review Other Org")
    foreign = _create(client, other_token, other["id"], "Foreign")
    assert client.get(_profile_url(org["id"], foreign["id"]), headers=auth_headers(token)).status_code == 404


def test_only_a_holder_of_the_project_atom_sets_a_projects_settings_and_any_member_reads_them(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Project Permission Org")
    _, stakeholder = _member(client, token, org["id"], project["id"])
    assert _policy(client, stakeholder, project["id"])["can_manage"] is False
    assert _policy(client, token, project["id"])["can_manage"] is True
    refused = client.put(
        _project_url(project["id"], "/requirement"), json={"settings": {"interval_days": 30}}, headers=auth_headers(stakeholder),
    )
    assert refused.status_code == 403
    # A server administrator who is not a member holds no bypass: the part is not found for them.
    assert client.put(
        _project_url(project["id"], "/requirement"), json={"settings": {}}, headers=auth_headers(admin_token),
    ).status_code == 404


def test_the_policy_lists_the_types_with_a_review_schedule(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Types Org")
    profile = _create(client, token, org["id"], "Regulated")
    types = client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).json()["types"]
    assert [(t["artefact_type"], t["label"], t["module_key"]) for t in types] == [
        ("compliance_review", "Compliance review", "compliance"), ("requirement", "Requirement", ""),
        ("stage_phase", "Stage phase", ""), ("stage_review", "Stage review", ""),
    ]
    assert types[1]["settings"] == {"interval_days": None, "lead_days": None, "default_owner": None}
    assert [t["artefact_type"] for t in _policy(client, token, project["id"])["types"]] == [
        "compliance_review", "requirement", "stage_phase", "stage_review",
    ]
    # A type with no review schedule is not found; a risk is listed only where Risk Management is on.
    _set_profile(client, token, org["id"], profile["id"], "decision", {"interval_days": 5}, status=404)
    _set_project(client, token, project["id"], "no_such_type", {}, status=404)


def test_values_are_validated_and_a_default_owner_must_belong_to_the_organisation(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Validation Org")
    other, other_token = _setup(client, admin_token, "Review Validation Other Org")
    profile = _create(client, token, org["id"], "Regulated")
    for body in ({"interval_days": 0}, {"interval_days": 3651}, {"lead_days": -1}, {"lead_days": 366}):
        _set_profile(client, token, org["id"], profile["id"], "requirement", body, status=422)
        _set_project(client, token, project["id"], "requirement", body, status=422)
    outsider = create_org_user(client, other_token, other["id"], "review_outsider@example.com")
    foreign_group = create_org_group(client, other_token, other["id"], "Foreign group")
    for principal in (_principal("user", outsider), _principal("org_group", foreign_group)):
        _set_profile(client, token, org["id"], profile["id"], "requirement", {"default_owner": principal}, status=400)
        _set_project(client, token, project["id"], "requirement", {"default_owner": principal}, status=400)
    squad = create_project_group(client, token, project["id"], "Squad")
    # A project group belongs to one project: a profile cannot name it, the project's own row can.
    _set_profile(client, token, org["id"], profile["id"], "requirement", {"default_owner": _principal("project_group", squad)}, status=400)
    _set_project(client, token, project["id"], "requirement", {"default_owner": _principal("project_group", squad)})


def test_settings_are_stored_read_back_with_labels_and_an_empty_profile_row_is_removed(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Roundtrip Org")
    team = create_org_group(client, token, org["id"], "Review Team")
    profile = _create(client, token, org["id"], "Regulated")
    out = _set_profile(
        client, token, org["id"], profile["id"], "requirement",
        {"interval_days": 90, "lead_days": 14, "default_owner": _principal("org_group", team)},
    )
    settings = _entry(out)["settings"]
    assert settings["interval_days"] == 90 and settings["lead_days"] == 14
    assert settings["default_owner"]["label"] == "Review Team" and settings["default_owner"]["type"] == "org_group"
    out = _set_profile(client, token, org["id"], profile["id"], "requirement", {})
    assert _entry(out)["settings"] == {"interval_days": None, "lead_days": None, "default_owner": None}
    db = SessionLocal()
    try:
        assert db.scalars(select(GovernanceReviewPolicy).where(GovernanceReviewPolicy.profile_id == uuid.UUID(profile["id"]))).all() == []
    finally:
        db.close()


def test_every_change_writes_one_audit_event_with_keys_only(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Audit Org")
    member = create_org_user(client, token, org["id"], "review_audit_owner@example.com")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(
        client, token, org["id"], profile["id"], "requirement",
        {"interval_days": 30, "default_owner": _principal("user", member)},
    )
    events = [e for e in _audit("governance_profile", profile["id"]) if e.action == "review_updated"]
    assert len(events) == 1
    assert events[0].detail == {
        "artefact_type": "requirement", "settings": {"interval_days": 30, "lead_days": None, "default_owner": "user"},
    }
    assert member not in json.dumps(events[0].detail)
    _set_project(client, token, project["id"], "requirement", {"lead_days": 3})
    project_events = _audit("governance_review_policy", project["id"])
    assert [e.action for e in project_events] == ["updated"]
    assert project_events[0].detail == {
        "artefact_type": "requirement", "settings": {"interval_days": None, "lead_days": 3, "default_owner": None},
    }


# --- merging --------------------------------------------------------------------------------------


def test_the_shortest_interval_the_longest_lead_and_the_first_owner_apply_and_each_source_is_named(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Merge Org")
    exempt = create_project(client, token, org["id"], "Exempt project")
    enforced_owner = create_org_user(client, token, org["id"], "review_merge_enforced@example.com")
    default_owner = create_org_user(client, token, org["id"], "review_merge_default@example.com")
    enforced = _create(client, token, org["id"], "Regulated", mode="enforced")
    default = _create(client, token, org["id"], "Shared defaults", mode="default")
    offered = _create(client, token, org["id"], "Offered", mode="opt_in")
    _set_profile(client, token, org["id"], enforced["id"], "requirement",
                 {"interval_days": 90, "lead_days": 5, "default_owner": _principal("user", enforced_owner)})
    _set_profile(client, token, org["id"], default["id"], "requirement",
                 {"interval_days": 60, "lead_days": 10, "default_owner": _principal("user", default_owner)})
    _set_profile(client, token, org["id"], offered["id"], "requirement", {"interval_days": 30})
    _exempt(client, token, org["id"], enforced["id"], exempt["id"])

    got = _effective(client, token, project["id"])
    assert (got["interval_days"], got["interval_source"]) == (60, "Shared defaults")
    assert (got["lead_days"], got["lead_source"]) == (10, "Shared defaults")
    assert got["default_owner"]["id"] == enforced_owner and got["owner_source"] == "Regulated"

    _choose(client, token, project["id"], offered["id"], True)
    assert (_effective(client, token, project["id"])["interval_days"], _effective(client, token, project["id"])["interval_source"]) == (30, "Offered")
    _choose(client, token, project["id"], default["id"], False)
    got = _effective(client, token, project["id"])
    assert (got["lead_days"], got["lead_source"]) == (5, "Regulated")

    exempt_got = _effective(client, token, exempt["id"])
    assert exempt_got["interval_days"] == 60 and exempt_got["owner_source"] == "Shared defaults"


def test_a_project_can_tighten_but_never_relax_a_profile(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Tighten Org")
    profile = _create(client, token, org["id"], "Regulated", mode="enforced")
    _set_profile(client, token, org["id"], profile["id"], "requirement", {"interval_days": 60, "lead_days": 10})
    _set_project(client, token, project["id"], "requirement", {"interval_days": 120, "lead_days": 3})
    got = _effective(client, token, project["id"])
    assert (got["interval_days"], got["interval_source"], got["lead_days"], got["lead_source"]) == (60, "Regulated", 10, "Regulated")
    _set_project(client, token, project["id"], "requirement", {"interval_days": 14})
    got = _effective(client, token, project["id"])
    assert (got["interval_days"], got["interval_source"]) == (14, "project")
    # An empty row is a choice of nothing here: it removes no profile setting.
    _set_project(client, token, project["id"], "requirement", {})
    assert _effective(client, token, project["id"])["interval_days"] == 60


def test_a_child_follows_its_parents_row_until_it_sets_its_own(client, admin_token):
    org, token = _setup(client, admin_token, "Review Nested Org")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    _set_project(client, token, parent["id"], "requirement", {"interval_days": 45})
    entry = _entry(_policy(client, token, child["id"]))
    assert entry["own"] is None and entry["inherited_from"] == "Parent"
    assert (entry["effective"]["interval_days"], entry["effective"]["interval_source"]) == (45, "parent_project")

    _set_project(client, token, child["id"], "requirement", {})  # a choice of no policy here
    entry = _entry(_policy(client, token, child["id"]))
    assert entry["own"] == {"interval_days": None, "lead_days": None, "default_owner": None}
    assert entry["inherited_from"] is None and entry["effective"]["interval_days"] is None

    _set_project(client, token, child["id"], "requirement", {"interval_days": 7})
    assert _effective(client, token, child["id"])["interval_source"] == "project"
    _set_project(client, token, child["id"], "requirement", None)  # follows the parent again
    assert _entry(_policy(client, token, child["id"]))["inherited_from"] == "Parent"


def test_the_contributor_counts_the_types_a_profile_gives_settings_for(client, admin_token):
    org, token = _setup(client, admin_token, "Review Count Org")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], "requirement", {"lead_days": 2})
    detail = client.get(ORG.format(org=org["id"]) + f"/profiles/{profile['id']}", headers=auth_headers(token)).json()
    assert {c["key"]: c["count"] for c in detail["contributions"]}["traceability:review"] == 1


def test_the_engine_resolves_the_policy_through_the_seam(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Seam Org")
    db = SessionLocal()
    try:
        assert review_engine.review_policy(db, uuid.UUID(project["id"]), "requirement") == ReviewPolicy()
    finally:
        db.close()
    _set_project(client, token, project["id"], "requirement", {"interval_days": 30, "lead_days": 4})
    db = SessionLocal()
    try:
        assert review_engine.review_policy(db, uuid.UUID(project["id"]), "requirement") == ReviewPolicy(30, 4, None)
    finally:
        db.close()
    _part(client, token, org["id"], False)
    db = SessionLocal()
    try:
        assert review_engine.review_policy(db, uuid.UUID(project["id"]), "requirement") == ReviewPolicy()
    finally:
        db.close()


# --- the reminder sweep ---------------------------------------------------------------------------


def test_a_policy_lead_applies_to_a_requirement_with_no_lead_of_its_own(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Lead Sweep Org")
    reviewer, reviewer_token = _member(client, token, org["id"], project["id"])
    far = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=12), name="Far",
                       reviewer=_principal("user", reviewer))
    pinned = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=12), name="Pinned",
                          reviewer=_principal("user", reviewer), review_lead_days=2)
    assert _sweep() == 0
    _set_project(client, token, project["id"], "requirement", {"lead_days": 14})
    assert _sweep() == 1
    assert _reminded(client, reviewer_token) == [far["id"]]
    assert pinned["id"] not in _reminded(client, reviewer_token)  # the record's own lead wins


def test_the_default_owner_is_reminded_when_a_requirement_has_no_reviewer(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Owner Sweep Org")
    first = create_org_user(client, token, org["id"], "review_owner_first@example.com")
    second = create_org_user(client, token, org["id"], "review_owner_second@example.com")
    team = create_org_group(client, token, org["id"], "Review Owners", users=[first, second])
    empty = create_org_group(client, token, org["id"], "Nobody Reviews")
    unassigned = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=1), name="Unassigned")
    orphan = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=1), name="Orphan",
                          reviewer=_principal("org_group", empty))
    _set_project(client, token, project["id"], "requirement", {"default_owner": _principal("org_group", team)})
    assert _sweep() == 2
    for email in ("review_owner_first@example.com", "review_owner_second@example.com"):
        assert sorted(_reminded(client, login(client, email, "Password123!"))) == sorted([unassigned["id"], orphan["id"]])
    assert _reminded(client, token) == []  # the project manager is the fallback only


def test_the_project_managers_hear_about_it_when_no_reviewer_and_no_default_owner_can_be_reminded(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Manager Sweep Org")
    unassigned = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=1), name="Unassigned")
    empty = create_org_group(client, token, org["id"], "Empty owners")
    _set_project(client, token, project["id"], "requirement", {"default_owner": _principal("org_group", empty)})
    assert _sweep() == 1
    assert _reminded(client, token) == [unassigned["id"]]


def test_the_sweep_skips_a_project_whose_module_is_off_and_ignores_policy_when_the_part_is_off(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Off Sweep Org")
    reviewer, reviewer_token = _member(client, token, org["id"], project["id"])
    _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=12), name="Far",
                 reviewer=_principal("user", reviewer))
    _set_project(client, token, project["id"], "requirement", {"lead_days": 14})
    _part(client, token, org["id"], False)
    assert _sweep() == 0  # the policy is kept and does not apply while its part is off
    _part(client, token, org["id"], True)
    assert _sweep() == 1


# --- the boundary hours of a due date ---------------------------------------------------------------


# --- the scheduling rules a type applies ----------------------------------------------------------


# --- the default owner is a principal -----------------------------------------------------------------


def test_deleting_a_group_that_is_a_default_owner_clears_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Group Delete Org")
    team = create_org_group(client, token, org["id"], "Doomed owners")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], "requirement", {"default_owner": _principal("org_group", team)})
    group_url = f"/api/v1/orgs/{org['id']}/groups/{team}"
    usage = client.get(f"{group_url}/usage", headers=auth_headers(token)).json()
    assert [(i["label"], i["count"], i["mandatory"]) for i in usage["items"]] == [
        ("governance review policy default owners", 1, False),
    ]
    assert client.delete(group_url, params={"clear_optional": "true"}, headers=auth_headers(token)).status_code == 204
    types = client.get(_profile_url(org["id"], profile["id"]), headers=auth_headers(token)).json()["types"]
    assert types[0]["settings"]["default_owner"] is None


# --- bundles ---------------------------------------------------------------------------------------


def test_a_projects_own_rows_travel_in_its_bundle_with_the_owner_by_email(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Project Bundle Org")
    owner = create_org_user(client, token, org["id"], "review_bundle_owner@example.com")
    _set_project(client, token, project["id"], "requirement",
                 {"interval_days": 30, "lead_days": 6, "default_owner": _principal("user", owner)})
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json"))
    assert data[bundle.REVIEW_POLICIES_KEY] == [{
        "artefact_type": "requirement", "interval_days": 30, "lead_days": 6,
        "default_owner": {"type": "user", "email": "review_bundle_owner@example.com"},
    }]
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copied = _effective(client, token, imported.json()["project"]["id"])
    assert (copied["interval_days"], copied["lead_days"], copied["default_owner"]["id"]) == (30, 6, owner)


def test_a_project_import_leaves_out_what_the_organisation_cannot_use_and_says_so(client, admin_token):
    from app.models.project import Project
    from app.modules.traceability import review_policy

    org, project, token = _world(client, admin_token, "Review Import Warning Org")
    warnings: list[str] = []
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        assert row is not None
        review_policy.import_project_rows(
            db, row,
            [
                {"artefact_type": "requirement", "interval_days": 99999, "lead_days": 2,
                 "default_owner": {"type": "user", "email": "nobody@example.com"}},
                {"artefact_type": "no_such_type", "interval_days": 5},
            ],
            warnings.append,
        )
        assert len(warnings) == 3
        assert any("interval days" in w and "out of range" in w for w in warnings)
        assert any("default owner" in w for w in warnings)
        assert any("no review schedule" in w for w in warnings)
        stored = db.scalars(select(GovernanceReviewPolicy).where(GovernanceReviewPolicy.project_id == row.id)).one()
        assert (stored.interval_days, stored.lead_days, stored.default_owner_id) == (None, 2, None)
    finally:
        db.rollback()
        db.close()


def test_a_profiles_rows_travel_in_the_organisation_bundle(client, admin_token):
    org, token = _setup(client, admin_token, "Review Org Bundle Org")
    owner = create_org_user(client, token, org["id"], "review_org_bundle_owner@example.com")
    profile = _create(client, token, org["id"], "Regulated")
    _set_profile(client, token, org["id"], profile["id"], "requirement",
                 {"interval_days": 45, "lead_days": 9, "default_owner": _principal("user", owner)})
    exported = client.get(f"/api/v1/orgs/{org['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("org.json"))
    entry = next(e for e in data["governance_profiles"] if e["name"] == "Regulated")
    review = entry["contributions"]["traceability:review"]
    assert review[0]["kind"] == "review" and review[0]["interval_days"] == 45

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Review Org Bundle Imported Org"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code in (200, 201), imported.text
    new_org = imported.json().get("id") or imported.json()["organization"]["id"]
    from app.modules.traceability.models import GovernanceProfile

    db = SessionLocal()
    try:
        new_profile = db.scalars(select(GovernanceProfile).where(
            GovernanceProfile.organization_id == uuid.UUID(new_org), GovernanceProfile.name == "Regulated",
        )).one()
        row = db.scalars(select(GovernanceReviewPolicy).where(GovernanceReviewPolicy.profile_id == new_profile.id)).one()
        assert (row.artefact_type, row.interval_days, row.lead_days) == ("requirement", 45, 9)
    finally:
        db.close()


def test_the_review_rows_are_template_configuration():
    from app.modules.registry import get_module

    module = get_module("traceability")
    assert module is not None and module.project_bundle_hooks is not None
    assert {bundle.CHOICES_KEY, bundle.APPROVAL_POLICIES_KEY, bundle.REVIEW_POLICIES_KEY} <= set(
        module.project_bundle_hooks.template_configuration_keys
    )


# --- the requirement's review date and review route ----------------------------------------------


def _edit(client, token, project_id, requirement: dict, **changes):
    body = {
        "name": requirement["name"], "component_id": requirement["component_id"], "category_id": requirement["category_id"],
        "owner": {"type": requirement["owner"]["type"], "id": requirement["owner"]["id"]}, **changes,
    }
    return client.put(f"/api/v1/projects/{project_id}/requirements/{requirement['id']}", json=body, headers=auth_headers(token))


def test_the_interval_caps_a_requirements_review_date_when_it_is_set_or_changed(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Interval Cap Org")
    pid = project["id"]
    far = _requirement(client, token, pid, review_date=TODAY + timedelta(days=200), name="Far")
    _set_project(client, token, pid, "requirement", {"interval_days": 90})
    latest = (TODAY + timedelta(days=90)).isoformat()

    # An unchanged date is not set again, so a requirement scheduled before the policy can still be edited.
    assert _edit(client, token, pid, far, name="Renamed", review_date=far["review_date"]).status_code == 200
    refused = _edit(client, token, pid, far, review_date=(TODAY + timedelta(days=150)).isoformat())
    assert refused.status_code == 422 and latest in refused.json()["detail"]
    assert _edit(client, token, pid, far, review_date=latest).status_code == 200
    assert _edit(client, token, pid, far, review_date=None).status_code == 200  # no scheduled review is no date to cap

    component_id, category_id = create_component_and_category(client, token, pid) if pid not in _SCOPES else _SCOPES[pid]
    body = {"name": "New", "component_id": component_id, "category_id": category_id, "review_date": (TODAY + timedelta(days=91)).isoformat()}
    assert client.post(f"/api/v1/projects/{pid}/requirements", json=body, headers=auth_headers(token)).status_code == 422
    assert _requirement(client, token, pid, review_date=TODAY + timedelta(days=90), name="Within")["review_date"] == latest


def test_the_default_owner_may_record_the_review_of_a_requirement_with_no_reviewer(client, admin_token):
    org, project, token = _world(client, admin_token, "Review Default Owner Gate Org")
    pid = project["id"]
    steward, steward_token = _member(client, token, org["id"], pid)
    other, other_token = _member(client, token, org["id"], pid)
    reviewer, _ = _member(client, token, org["id"], pid)
    unassigned = _requirement(client, token, pid, review_date=TODAY + timedelta(days=5), name="Unassigned")
    assigned = _requirement(client, token, pid, review_date=TODAY + timedelta(days=5), name="Assigned", reviewer=_principal("user", reviewer))

    def record(who, requirement):
        return client.post(
            f"/api/v1/projects/{pid}/requirements/{requirement['id']}/reviews", json={"outcome": "met"}, headers=auth_headers(who),
        )

    assert record(steward_token, unassigned).status_code == 403
    _set_project(client, token, pid, "requirement", {"default_owner": _principal("user", steward)})
    assert record(steward_token, unassigned).status_code == 201
    assert record(other_token, unassigned).status_code == 403
    assert record(steward_token, assigned).status_code == 403  # a named reviewer is never replaced
