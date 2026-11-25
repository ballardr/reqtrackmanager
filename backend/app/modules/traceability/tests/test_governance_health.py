"""Tests for governance health (`modules.traceability.health`, `health_router`): the organisation default and a project's
own mode, interval and check runner, the figures of the live view, the viewer restriction, reviews due against the
caller's day, the stored snapshot in both snapshot modes (lazy refresh on change, the manual refresh, the hourly sweep,
the refresh lock), who runs the baseline checks in a snapshot, the audit events, the bundles and the MCP tool list."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import Project
from app.models.user import User
from app.modules import registry
from app.modules.registry import build_mcp_tool_manifest, get_all_module_scheduled_jobs
from app.modules.traceability import bundle, health
from app.modules.traceability.mcp_tools import build_mcp_tools
from app.modules.traceability.models import GovernanceHealthSnapshot
from app.modules.traceability.tests.test_governance_baseline_policy import (
    APPROVALS,
    _member,
    _requirement,
    _set_project,
    _settings,
    _world,
)
from app.modules.traceability.tests.test_governance_profiles import _create as _create_profile
from app.modules.traceability.tests.test_governance_profiles import _setup
from tests.conftest import auth_headers, create_project

PROJECT = "/api/v1/projects/{project}/modules/traceability"
ORG = "/api/v1/orgs/{org}/modules/traceability"


def _health_url(project_id, suffix="") -> str:
    return PROJECT.format(project=project_id) + f"/health{suffix}"


def _get_health(client, token, project_id, **headers) -> dict:
    resp = client.get(_health_url(project_id), headers={**auth_headers(token), **headers})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _put_settings(client, token, project_id, mode=None, interval=None, runner=None, status=200) -> dict:
    resp = client.put(
        _health_url(project_id, "/settings"), json={"mode": mode, "interval_hours": interval, "checks_runner_id": runner},
        headers=auth_headers(token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _put_default(client, token, org_id, mode, interval=24, status=200) -> dict:
    resp = client.put(
        ORG.format(org=org_id) + "/health-defaults", json={"mode": mode, "interval_hours": interval}, headers=auth_headers(token),
    )
    assert resp.status_code == status, resp.text
    return resp.json()


def _refresh(client, token, project_id, status=200) -> dict:
    resp = client.post(_health_url(project_id, "/refresh"), headers=auth_headers(token))
    assert resp.status_code == status, resp.text
    return resp.json()


def _approve(client, token, project_id, requirement_id) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements/{requirement_id}/approve", json={}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _category(view: dict, key: str) -> dict:
    return next(c for c in view["categories"] if c["key"] == key)


def _requirement_reviews(view: dict) -> dict:
    return next(r for r in view["reviews"] if r["artefact_type"] == "requirement")


def _snapshot(project_id: str) -> GovernanceHealthSnapshot | None:
    with SessionLocal() as db:
        row = db.scalar(select(GovernanceHealthSnapshot).where(GovernanceHealthSnapshot.project_id == uuid.UUID(project_id)))
        if row is not None:
            db.expunge(row)
        return row


def _computed_at(project_id: str) -> datetime:
    """When the project's stored snapshot was read."""
    row = _snapshot(project_id)
    assert row is not None
    return row.computed_at


def _audit(entity_type: str, entity_id: str) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == entity_type, AuditEvent.entity_id == entity_id,
        ).order_by(AuditEvent.created_at)))


def _part(client, token, org_id, enabled: bool) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/traceability/subcomponents/governance_health", json={"enabled": enabled},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


# --- gating and permissions ----------------------------------------------------------------------


def test_the_routes_are_not_found_while_the_part_is_off(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Part Off Org")
    assert client.get(_health_url(project["id"]), headers=auth_headers(token)).status_code == 200
    _part(client, token, org["id"], False)
    headers = auth_headers(token)
    assert client.get(_health_url(project["id"]), headers=headers).status_code == 404
    assert client.post(_health_url(project["id"], "/refresh"), headers=headers).status_code == 404
    assert client.get(_health_url(project["id"], "/settings"), headers=headers).status_code == 404
    assert client.put(_health_url(project["id"], "/settings"), json={}, headers=headers).status_code == 404
    assert client.get(ORG.format(org=org["id"]) + "/health-defaults", headers=headers).status_code == 404


def test_any_member_reads_and_only_a_governance_manager_changes_or_refreshes(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Permission Org")
    _, stakeholder = _member(client, token, org["id"], project["id"])
    headers = auth_headers(stakeholder)
    assert client.get(_health_url(project["id"]), headers=headers).status_code == 200
    settings = client.get(_health_url(project["id"], "/settings"), headers=headers).json()
    assert settings["can_manage"] is False
    assert client.put(_health_url(project["id"], "/settings"), json={}, headers=headers).status_code == 403
    _put_settings(client, token, project["id"], mode="snapshot_on_change")
    assert _get_health(client, stakeholder, project["id"])["can_refresh"] is False
    assert client.post(_health_url(project["id"], "/refresh"), headers=headers).status_code == 403
    assert _get_health(client, token, project["id"])["can_refresh"] is True
    # The organisation default needs the organisation atom, which a project member lacks.
    assert client.get(ORG.format(org=org["id"]) + "/health-defaults", headers=headers).status_code == 403
    assert client.put(
        ORG.format(org=org["id"]) + "/health-defaults", json={"mode": "on_demand"}, headers=headers,
    ).status_code == 403
    # A server administrator who is not a member holds no bypass.
    assert client.get(_health_url(project["id"]), headers=auth_headers(admin_token)).status_code == 404


# --- settings --------------------------------------------------------------------------------------


def test_the_mode_follows_the_organisation_default_unless_the_project_chooses(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Settings Org")
    out = client.get(_health_url(project["id"], "/settings"), headers=auth_headers(token)).json()
    assert (out["mode"], out["mode_source"], out["interval_hours"], out["interval_source"]) == ("on_demand", "default", 24, "default")
    assert out["interval_options"] == [1, 6, 12, 24, 48, 72, 120, 168, 240, 336]
    assert out["on_demand_record_limit"] == health.ON_DEMAND_GUIDANCE_RECORDS and out["checks_enabled"] is False
    _manual_approvals(client, token, project["id"])
    assert client.get(_health_url(project["id"], "/settings"), headers=auth_headers(token)).json()["checks_enabled"] is True

    _put_default(client, token, org["id"], "snapshot_interval", interval=12)
    out = client.get(_health_url(project["id"], "/settings"), headers=auth_headers(token)).json()
    assert (out["mode"], out["mode_source"], out["interval_hours"], out["interval_source"]) == (
        "snapshot_interval", "organization", 12, "organization",
    )
    assert out["organization_mode"] == "snapshot_interval" and out["own_mode"] is None

    out = _put_settings(client, token, project["id"], mode="snapshot_on_change", interval=72)
    assert (out["mode"], out["mode_source"], out["interval_hours"], out["interval_source"]) == (
        "snapshot_on_change", "project", 72, "project",
    )
    out = _put_settings(client, token, project["id"])
    assert (out["mode"], out["mode_source"], out["own_mode"]) == ("snapshot_interval", "organization", None)


def test_an_interval_that_is_not_offered_is_refused(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Interval Org")
    assert _put_settings(client, token, project["id"], interval=5, status=422)
    assert _put_default(client, token, org["id"], "snapshot_interval", interval=0, status=422)
    for hours in (1, 6, 12, 24, 48, 72, 120, 168, 240, 336):
        assert _put_default(client, token, org["id"], "snapshot_interval", interval=hours)["interval_hours"] == hours


def test_a_check_runner_must_be_an_active_member_of_the_project(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Runner Org")
    manager_id, _ = _member(client, token, org["id"], project["id"], role="project_manager")
    out = _put_settings(client, token, project["id"], mode="snapshot_on_change", runner=manager_id)
    assert out["checks_runner"]["id"] == manager_id and out["runner_problem"] is None
    other = create_project(client, token, org["id"], "Elsewhere")
    assert _put_settings(client, token, other["id"], runner=manager_id, status=422)
    assert _put_settings(client, token, project["id"], runner=str(uuid.uuid4()), status=422)
    with SessionLocal() as db:
        user = db.get(User, uuid.UUID(manager_id))
        assert user is not None
        user.is_active = False
        db.commit()
    out = client.get(_health_url(project["id"], "/settings"), headers=auth_headers(token)).json()
    assert out["runner_problem"] == "The person is not an active user."


def test_settings_changes_are_audited_with_keys_only(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Audit Org")
    runner_id, _ = _member(client, token, org["id"], project["id"], role="project_manager")
    _put_default(client, token, org["id"], "snapshot_interval", interval=6)
    _put_settings(client, token, project["id"], mode="snapshot_interval", interval=24, runner=runner_id)
    [default] = _audit("governance_health_default", org["id"])
    assert default.action == "updated" and default.detail == {"mode": "snapshot_interval", "interval_hours": 6}
    [changed] = _audit("governance_health_settings", project["id"])
    assert changed.detail == {"mode": "snapshot_interval", "interval_hours": 24, "runner_set": True}


# --- the live view ---------------------------------------------------------------------------------


def test_the_live_view_counts_requirements_approved_and_rounds_the_share_down(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Live Org")
    first = _requirement(client, token, project["id"], "First")
    _requirement(client, token, project["id"], "Second")
    _requirement(client, token, project["id"], "Third")
    _approve(client, token, project["id"], first["id"])
    view = _get_health(client, token, project["id"])
    assert (view["mode"], view["source"], view["stale"]) == ("on_demand", "live", False)
    requirements = _category(view, "requirement")
    assert (requirements["label"], requirements["kind"], requirements["total"], requirements["done"]) == (
        "Requirements", "completion", 3, 1,
    )
    assert requirements["percent"] == 33 and requirements["outstanding"] == 2
    changes = _category(view, "change_request")
    assert (changes["kind"], changes["total"], changes["percent"]) == ("outstanding", 0, None)
    assert view["checks"]["status"] == "not_enabled"


def test_a_share_below_one_hundred_never_reads_as_complete():
    assert health.CategoryFigure("k", "L", "t", "completion", 1000, 999).percent == 99
    assert health.CategoryFigure("k", "L", "t", "completion", 3, 3).percent == 100
    assert health.CategoryFigure("k", "L", "t", "completion", 0, 0).percent is None


def test_an_archived_requirement_is_not_counted(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Archived Org")
    keep = _requirement(client, token, project["id"], "Keep")
    gone = _requirement(client, token, project["id"], "Gone")
    archived = client.delete(f"/api/v1/projects/{project['id']}/requirements/{gone['id']}", headers=auth_headers(token))
    assert archived.status_code == 204, archived.text
    _approve(client, token, project["id"], keep["id"])
    requirements = _category(_get_health(client, token, project["id"]), "requirement")
    assert (requirements["total"], requirements["done"], requirements["percent"]) == (1, 1, 100)


def test_every_category_is_dropped_for_a_type_the_viewer_may_not_read(client, admin_token, monkeypatch):
    org, project, token = _world(client, admin_token, "Health Viewer Org")
    _requirement(client, token, project["id"], "Only")
    real = health.readable_provider
    monkeypatch.setattr(
        health, "readable_provider", lambda db, user, p, t, held=None: None if t == "change_request" else real(db, user, p, t, held),
    )
    keys = {c["key"] for c in _get_health(client, token, project["id"])["categories"]}
    assert "requirement" in keys and "change_request" not in keys


def test_reviews_due_are_compared_with_the_callers_day(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Reviews Org")
    today = datetime.now(UTC).date()
    _requirement(client, token, project["id"], "Review today", review_date=today.isoformat())
    due = _requirement_reviews(_get_health(client, token, project["id"], **{"X-Client-Date": today.isoformat()}))
    assert due["label"] == "Requirements" and due["due"] == 1
    # At UTC-8 late in the evening the caller's day is still yesterday: the review is not yet due for them.
    yesterday = (today - timedelta(days=1)).isoformat()
    early = _requirement_reviews(_get_health(client, token, project["id"], **{"X-Client-Date": yesterday}))
    assert early["due"] == 0


# --- snapshots -------------------------------------------------------------------------------------


def test_an_interval_snapshot_is_served_as_stored_until_refreshed(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Interval Snapshot Org")
    first = _requirement(client, token, project["id"], "First")
    _put_settings(client, token, project["id"], mode="snapshot_interval", interval=24)
    view = _get_health(client, token, project["id"])
    assert view["source"] == "snapshot" and _category(view, "requirement")["done"] == 0
    stored = _snapshot(project["id"])
    assert stored is not None
    _approve(client, token, project["id"], first["id"])
    again = _get_health(client, token, project["id"])
    assert _category(again, "requirement")["done"] == 0 and again["computed_at"] == view["computed_at"]
    refreshed = _refresh(client, token, project["id"])
    assert _category(refreshed, "requirement")["done"] == 1
    assert refreshed["computed_at"] > view["computed_at"]
    assert [e.action for e in _audit("governance_health", project["id"])] == ["refreshed"]


def test_an_on_change_snapshot_recomputes_on_the_next_read_after_a_change(client, admin_token):
    org, project, token = _world(client, admin_token, "Health On Change Org")
    first = _requirement(client, token, project["id"], "First")
    _put_settings(client, token, project["id"], mode="snapshot_on_change")
    view = _get_health(client, token, project["id"])
    assert _category(view, "requirement")["done"] == 0
    assert _get_health(client, token, project["id"])["computed_at"] == view["computed_at"]
    _approve(client, token, project["id"], first["id"])
    after = _get_health(client, token, project["id"])
    assert _category(after, "requirement")["done"] == 1 and after["stale"] is False
    assert after["computed_at"] > view["computed_at"]
    # The system's own refresh leaves no audit event: only a person's Refresh now does.
    assert _audit("governance_health", project["id"]) == []


def test_a_refresh_is_refused_in_on_demand_mode(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Refresh Refused Org")
    detail = _refresh(client, token, project["id"], status=409)["detail"]
    assert "computed on demand" in detail


def test_a_reader_that_cannot_take_the_refresh_lock_is_served_the_stored_snapshot_as_stale(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Lock Org")
    first = _requirement(client, token, project["id"], "First")
    _put_settings(client, token, project["id"], mode="snapshot_on_change")
    view = _get_health(client, token, project["id"])
    _approve(client, token, project["id"], first["id"])
    holder = SessionLocal()
    try:
        holder.execute(select(func.pg_advisory_xact_lock(*health.refresh_lock_key(uuid.UUID(project["id"])))))
        served = _get_health(client, token, project["id"])
        assert served["stale"] is True and served["computed_at"] == view["computed_at"]
        assert _category(served, "requirement")["done"] == 0
        _refresh(client, token, project["id"], status=409)
    finally:
        holder.rollback()
        holder.close()
    assert _get_health(client, token, project["id"])["stale"] is False


def test_a_governed_change_marks_the_snapshot_stale_and_an_unrelated_one_does_not(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Stale Org")
    first = _requirement(client, token, project["id"], "First")
    _put_settings(client, token, project["id"], mode="snapshot_on_change")
    _get_health(client, token, project["id"])
    with SessionLocal() as db:
        project_row = db.get(Project, uuid.UUID(project["id"]))
        snapshot = db.scalar(select(GovernanceHealthSnapshot).where(GovernanceHealthSnapshot.project_id == uuid.UUID(project["id"])))
        assert project_row is not None and snapshot is not None
        assert health.is_stale(db, project_row, snapshot) is False
    _approve(client, token, project["id"], first["id"])
    with SessionLocal() as db:
        project_row = db.get(Project, uuid.UUID(project["id"]))
        snapshot = db.scalar(select(GovernanceHealthSnapshot).where(GovernanceHealthSnapshot.project_id == uuid.UUID(project["id"])))
        assert project_row is not None and snapshot is not None
        assert health.is_stale(db, project_row, snapshot) is True


def test_a_change_to_the_organisations_profiles_marks_the_snapshot_stale(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Stale Profile Org")
    _put_settings(client, token, project["id"], mode="snapshot_on_change")
    _get_health(client, token, project["id"])
    with SessionLocal() as db:
        project_row = db.get(Project, uuid.UUID(project["id"]))
        snapshot = db.scalar(select(GovernanceHealthSnapshot).where(GovernanceHealthSnapshot.project_id == uuid.UUID(project["id"])))
        assert project_row is not None and snapshot is not None
        assert health.is_stale(db, project_row, snapshot) is False
    _create_profile(client, token, org["id"], "Regulated")
    with SessionLocal() as db:
        project_row = db.get(Project, uuid.UUID(project["id"]))
        snapshot = db.scalar(select(GovernanceHealthSnapshot).where(GovernanceHealthSnapshot.project_id == uuid.UUID(project["id"])))
        assert project_row is not None and snapshot is not None
        assert health.is_stale(db, project_row, snapshot) is True


def test_the_hourly_sweep_refreshes_only_a_project_whose_interval_has_elapsed(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Sweep Org")
    _put_settings(client, token, project["id"], mode="snapshot_interval", interval=6)
    other = create_project(client, token, org["id"], "On demand")
    assert _snapshot(project["id"]) is None
    with SessionLocal() as db:
        health.refresh_due_projects(db)
    first = _computed_at(project["id"])
    assert _snapshot(other["id"]) is None
    with SessionLocal() as db:
        health.refresh_due_projects(db, now=first + timedelta(hours=2))
    assert _computed_at(project["id"]) == first
    with SessionLocal() as db:
        health.refresh_due_projects(db, now=first + timedelta(hours=6))
    assert _computed_at(project["id"]) > first


def test_the_sweep_is_registered_to_run_every_hour():
    jobs = [job for key, job in get_all_module_scheduled_jobs() if key == "traceability"]
    assert [(j.job_id, j.hour, j.minute) for j in jobs] == [("health_snapshots", None, 7)]


# --- baseline checks in a snapshot -----------------------------------------------------------------


def _manual_approvals(client, token, project_id) -> None:
    _set_project(client, token, project_id, _settings(checks=[APPROVALS], stage=False, manual=True))


def test_checks_run_as_the_viewer_on_demand(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Checks Live Org")
    first = _requirement(client, token, project["id"], "First")
    _requirement(client, token, project["id"], "Second")
    _manual_approvals(client, token, project["id"])
    checks = _get_health(client, token, project["id"])["checks"]
    assert checks["status"] == "current" and checks["run_by"] is None
    [approvals] = checks["checks"]
    assert approvals["key"] == APPROVALS
    assert approvals["types"] == [{"artefact_type": "requirement", "checked": 2, "failing": 2, "percent_passing": 0}]
    _approve(client, token, project["id"], first["id"])
    [approvals] = _get_health(client, token, project["id"])["checks"]["checks"]
    assert approvals["types"][0]["failing"] == 1 and approvals["types"][0]["percent_passing"] == 50


def test_a_snapshot_with_no_runner_runs_checks_only_when_a_person_refreshes(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Checks Person Org")
    first = _requirement(client, token, project["id"], "First")
    _requirement(client, token, project["id"], "Second")
    _manual_approvals(client, token, project["id"])
    _put_settings(client, token, project["id"], mode="snapshot_on_change")
    view = _get_health(client, token, project["id"])
    assert view["checks"]["status"] == "not_run" and view["checks"]["checks"] == []

    view = _refresh(client, token, project["id"])
    assert view["checks"]["status"] == "current" and view["checks"]["run_by"]["id"] == client.get(
        "/api/v1/auth/me", headers=auth_headers(token),
    ).json()["id"]
    ran_at = view["checks"]["run_at"]
    assert view["checks"]["checks"][0]["types"][0]["failing"] == 2

    _approve(client, token, project["id"], first["id"])
    later = _get_health(client, token, project["id"])
    assert _category(later, "requirement")["done"] == 1
    assert later["checks"]["status"] == "carried_forward" and later["checks"]["run_at"] == ran_at
    assert later["checks"]["checks"][0]["types"][0]["failing"] == 2  # the earlier results, labelled as older


def test_a_configured_runner_runs_every_refresh_and_a_missing_runner_is_reported(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Checks Runner Org")
    runner_id, _ = _member(client, token, org["id"], project["id"], role="project_manager")
    first = _requirement(client, token, project["id"], "First")
    _requirement(client, token, project["id"], "Second")
    _manual_approvals(client, token, project["id"])
    _put_settings(client, token, project["id"], mode="snapshot_on_change", runner=runner_id)
    view = _get_health(client, token, project["id"])
    assert view["checks"]["status"] == "current" and view["checks"]["run_by"]["id"] == runner_id
    assert view["checks"]["checks"][0]["types"][0]["failing"] == 2

    _approve(client, token, project["id"], first["id"])
    view = _get_health(client, token, project["id"])
    assert view["checks"]["status"] == "current" and view["checks"]["checks"][0]["types"][0]["failing"] == 1

    with SessionLocal() as db:
        user = db.get(User, uuid.UUID(runner_id))
        assert user is not None
        user.is_active = False
        db.commit()
    _requirement(client, token, project["id"], "Third")
    view = _get_health(client, token, project["id"])
    assert view["checks"]["status"] == "carried_forward" and view["checks"]["run_by"]["id"] == runner_id
    assert client.get(_health_url(project["id"], "/settings"), headers=auth_headers(token)).json()["runner_problem"]


def test_a_snapshot_stores_counts_and_keys_only(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Counts Only Org")
    _requirement(client, token, project["id"], "Secret title")
    _manual_approvals(client, token, project["id"])
    _put_settings(client, token, project["id"], mode="snapshot_on_change")
    _refresh(client, token, project["id"])
    stored = _snapshot(project["id"])
    assert stored is not None
    text = json.dumps(stored.payload)
    assert "Secret title" not in text and "REQ-" not in text


# --- bundles ---------------------------------------------------------------------------------------


def _export_org(client, token, org_id) -> bytes:
    resp = client.get(f"/api/v1/orgs/{org_id}/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.content


def test_the_organisation_default_round_trips_and_a_merge_keeps_the_targets_own(client, admin_token):
    source, source_token = _setup(client, admin_token, "Health Default Source Org")
    _put_default(client, source_token, source["id"], "snapshot_interval", interval=48)
    exported = json.loads(zipfile.ZipFile(io.BytesIO(_export_org(client, source_token, source["id"]))).read("org.json"))
    assert exported[bundle.HEALTH_DEFAULT_KEY] == {"mode": "snapshot_interval", "interval_hours": 48}
    resp = client.post(
        "/api/v1/orgs/import", data={"name": "Health Default Imported Org"},
        files={"file": ("bundle.zip", _export_org(client, source_token, source["id"]), "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code in (200, 201), resp.text
    imported_id = resp.json().get("id") or resp.json()["organization"]["id"]
    with SessionLocal() as db:
        assert health.organization_default(db, uuid.UUID(imported_id)) == (health.HealthMode.SNAPSHOT_INTERVAL, 48)

    target, target_token = _setup(client, admin_token, "Health Default Target Org")
    _put_default(client, target_token, target["id"], "snapshot_on_change")
    opened = client.put(
        f"/api/v1/orgs/{target['id']}/advanced-settings", json={"external_user_policy": "anyone"}, headers=auth_headers(target_token),
    )
    assert opened.status_code == 200, opened.text
    merged = client.post(
        f"/api/v1/orgs/{target['id']}/import/merge",
        files={"file": ("bundle.zip", _export_org(client, source_token, source["id"]), "application/zip")},
        data={"resolutions": json.dumps({})}, headers=auth_headers(target_token),
    )
    assert merged.status_code == 200, merged.text
    with SessionLocal() as db:
        assert health.organization_default(db, uuid.UUID(target["id"]))[0] is health.HealthMode.SNAPSHOT_ON_CHANGE


def test_a_project_export_import_carries_its_settings_and_a_runner_who_is_a_member(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Project Bundle Org")
    runner_id, _ = _member(client, token, org["id"], project["id"], role="project_manager")
    _put_settings(client, token, project["id"], mode="snapshot_interval", interval=72, runner=runner_id)
    exported = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(token))
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json"))
    assert data[bundle.HEALTH_SETTINGS_KEY] == {"mode": "snapshot_interval", "interval_hours": 72}
    assert data[bundle.HEALTH_RUNNER_KEY]["email"].startswith("baseline_policy_")

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Health Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(token),
    )
    assert imported.status_code == 201, imported.text
    copy_id = imported.json()["project"]["id"]
    out = client.get(_health_url(copy_id, "/settings"), headers=auth_headers(token)).json()
    assert (out["own_mode"], out["own_interval_hours"]) == ("snapshot_interval", 72)
    # The runner is a member of the source project only, so the copy does not name them.
    assert out["checks_runner"] is None


# --- MCP tools -------------------------------------------------------------------------------------


def test_every_declared_tool_is_in_the_manifest_and_none_lifts_a_control_or_approves():
    manifest = {t.name: t for t in build_mcp_tool_manifest() if t.name.startswith("traceability_")}
    declared = {f"traceability_{t.name}" for t in build_mcp_tools()}
    assert set(manifest) == declared and len(declared) == 29
    assert not [n for n in declared if "delete" in n or "exemption" in n or "approve_" in n or "reject" in n]
    assert manifest["traceability_get_governance_health"].mutates is False
    assert manifest["traceability_set_governance_health_settings"].mutates is True
    assert manifest["traceability_refresh_governance_health"].method == "POST"


def test_the_guidance_names_every_tool_it_tells_an_agent_to_call():
    definition = registry.get_module("traceability")
    assert definition is not None
    names = {f"traceability_{t.name}" for t in definition.mcp_tools}
    mentioned = {w.strip("`.,:;()") for w in definition.mcp_guidance.split() if w.strip("`.,:;()").startswith("traceability_")}
    assert mentioned and mentioned <= names


@pytest.mark.parametrize("mode", ["on_demand", "snapshot_interval", "snapshot_on_change"])
def test_every_mode_returns_the_same_shape(client, admin_token, mode):
    org, project, token = _world(client, admin_token, f"Health Shape {mode} Org")
    _requirement(client, token, project["id"], "One")
    _put_settings(client, token, project["id"], mode=mode)
    view = _get_health(client, token, project["id"])
    assert set(view) == {"mode", "source", "computed_at", "stale", "can_refresh", "categories", "reviews", "checks"}
    assert view["mode"] == mode and _category(view, "requirement")["total"] == 1
