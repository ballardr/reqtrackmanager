"""Tests for background custom report runs (`services.report_run_jobs`, the `/report-runs` and `.../runs` routes):
the 409 hand-off from a too-big file run, queueing, running as the requester with the larger limits, the stored
file's download rules, the notification, expiry and the retention setting. Each test builds its own organisation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.generated_report import GeneratedReport
from app.models.notification import Notification
from app.models.organization import Organization
from app.services import report_layout_eval, report_run_jobs
from app.services.files import get_storage_backend
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World
from tests.test_custom_report_run import document_tree, make_layout, member_in, project_run, sheet_tree


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Jobs Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def queue(world: World, project: dict, layout: dict, token: str | None = None, **body):
    return world.client.post(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/runs",
        json={"format": "pdf", **body}, headers=auth_headers(token or world.token),
    )


def queue_org(world: World, layout: dict, token: str | None = None, **body):
    return world.client.post(
        f"/api/v1/orgs/{world.org['id']}/custom-reports/{layout['id']}/runs",
        json={"format": "docx", **body}, headers=auth_headers(token or world.token),
    )


def drain() -> int:
    """Produces every queued job (the leader's loop does this in a running stack); returns how many."""
    count = 0
    while report_run_jobs.run_next():
        count += 1
    return count


def run_row(db, run_id: str) -> GeneratedReport:
    db.expire_all()
    row = db.get(GeneratedReport, uuid.UUID(run_id))
    assert row is not None
    return row


def get_run(world: World, run_id: str, token: str | None = None):
    return world.client.get(f"/api/v1/report-runs/{run_id}", headers=auth_headers(token or world.token))


def download(world: World, run_id: str, token: str | None = None):
    return world.client.get(f"/api/v1/report-runs/{run_id}/download", headers=auth_headers(token or world.token))


def prepared(world: World, project: dict | None = None) -> tuple[dict, dict, dict]:
    """A project with one requirement and a document layout; returns `(project, layout, queued run)`."""
    project = project or world.project()
    world.requirement(project, "One")
    layout = make_layout(world, document_tree(), "Doc", project=project)
    resp = queue(world, project, layout)
    assert resp.status_code == 202, resp.text
    return project, layout, resp.json()


# ---- the hand-off from a synchronous run -----------------------------------------------------------------------


def test_a_file_run_over_the_synchronous_limit_asks_for_a_background_run(world, monkeypatch, db):
    project = world.project()
    for i in range(5):
        world.requirement(project, f"Rule {i}")
    layout = make_layout(world, document_tree(), "Doc", project=project)
    monkeypatch.setattr(report_layout_eval, "MAX_OUTPUT", 3)

    resp = project_run(world, project, layout, format="pdf")

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "async_required"
    assert project_run(world, project, layout).status_code == 413  # the on-screen form has no file to queue


def test_the_background_limits_are_larger_than_the_synchronous_ones(world, monkeypatch, db):
    project = world.project()
    for i in range(5):
        world.requirement(project, f"Rule {i}")
    layout = make_layout(world, document_tree(), "Doc", project=project)
    monkeypatch.setattr(report_layout_eval, "MAX_OUTPUT", 3)  # 3 for a request, 15 in the background
    assert project_run(world, project, layout, format="pdf").status_code == 409

    run = queue(world, project, layout).json()
    drain()

    assert run_row(db, run["id"]).status == "ready"


# ---- queueing --------------------------------------------------------------------------------------------------


def test_queueing_records_a_queued_run_pinned_to_the_current_version(world, db):
    project, layout, run = prepared(world)

    assert run["status"] == "queued"
    row = run_row(db, run["id"])
    assert row.layout_version == layout["current_version"] and row.requested_by == world.user_id
    assert row.params["report_template_id"] is None and row.output_key is None


def test_a_file_format_the_layout_cannot_produce_and_json_are_refused(world):
    project = world.project()
    layout = make_layout(world, document_tree(), "Doc", project=project)

    assert queue(world, project, layout, format="xlsx").status_code == 400
    assert queue(world, project, layout, format="json").status_code == 400


def test_a_non_member_cannot_queue_a_project_report(world, client):
    project = world.project()
    layout = make_layout(world, document_tree(), "Doc", project=project)
    email = f"out-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(client, world.token, world.org["id"], email)

    assert queue(world, project, layout, token=login(client, email, "Password123!")).status_code in (403, 404)


def test_a_person_can_have_only_so_many_background_runs_waiting(world, monkeypatch):
    project, layout, _ = prepared(world)
    monkeypatch.setattr(report_run_jobs, "MAX_ACTIVE_PER_USER", 2)

    assert queue(world, project, layout).status_code == 202
    assert queue(world, project, layout).status_code == 429


# ---- producing -------------------------------------------------------------------------------------------------


def test_a_queued_run_is_produced_stored_and_announced(world, db):
    project, layout, run = prepared(world)

    drain()

    row = run_row(db, run["id"])
    assert row.status == "ready" and row.output_key and row.output_size and row.finished_at
    assert row.output_filename and row.output_filename.endswith(".pdf")
    assert row.source_digest and row.record_counts and row.scope_project_ids == [project["id"]]
    assert row.created_at < row.started_at  # created_at is when it was asked for
    retention = report_run_jobs.effective_retention_days(db.get(Organization, row.organization_id))
    assert abs((row.expires_at - row.finished_at) - timedelta(days=retention)) < timedelta(seconds=5)
    notes = db.scalars(select(Notification).where(Notification.entity_id == run["id"])).all()
    assert len(notes) == 1 and notes[0].type == "report_run_finished" and notes[0].title.startswith("Report ready")


def test_the_requester_downloads_the_stored_file(world):
    _, _, run = prepared(world)
    drain()

    resp = download(world, run["id"])

    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    assert "attachment" in resp.headers["content-disposition"]
    assert get_run(world, run["id"]).json()["status"] == "ready"


def test_a_table_layout_is_produced_in_the_background_as_a_workbook(world, db):
    project = world.project()
    world.requirement(project, "One")
    layout = make_layout(world, sheet_tree("Reqs"), "Sheets", project=project)
    run = queue(world, project, layout, format="xlsx").json()

    drain()

    assert download(world, run["id"]).content.startswith(b"PK")


def test_an_organisation_report_is_produced_in_the_background_for_the_projects_selected(world, db):
    chosen, other = world.project("Chosen"), world.project("Other")
    world.requirement(chosen, "In")
    world.requirement(other, "Out")
    layout = make_layout(world, document_tree(), "Everywhere")

    run = queue_org(world, layout, project_ids=[chosen["id"]]).json()
    drain()

    row = run_row(db, run["id"])
    assert row.status == "ready" and row.scope == "organization" and row.scope_project_ids == [chosen["id"]]
    assert download(world, run["id"]).content.startswith(b"PK")


def test_a_job_that_cannot_finish_even_in_the_background_fails_with_a_plain_sentence(world, db, monkeypatch):
    project, layout, run = prepared(world)
    monkeypatch.setattr(report_layout_eval, "MAX_OUTPUT", 0)

    drain()

    row = run_row(db, run["id"])
    assert row.status == "failed" and row.error == report_run_jobs.FAILURE_LIMITS and row.output_key is None
    note = db.scalars(select(Notification).where(Notification.entity_id == run["id"])).one()
    assert note.title.startswith("Report could not be produced")
    assert download(world, run["id"]).status_code == 404


def test_a_requester_who_lost_access_before_the_job_ran_gets_a_failure_not_a_file(world, db):
    project = world.project()
    world.requirement(project, "Secret")
    layout = make_layout(world, document_tree(), "Doc", project=project)
    member = member_in(world, project)
    run = queue(world, project, layout, token=member).json()
    from app.models.user import User

    db.get(User, run_row(db, run["id"]).requested_by).is_archived = True
    db.commit()

    drain()

    row = run_row(db, run["id"])
    assert row.status == "failed" and row.error == report_run_jobs.FAILURE_ACCESS and row.output_key is None


def test_the_job_runs_the_version_pinned_when_it_was_queued(world, db):
    project = world.project()
    world.requirement(project, "One")
    layout = make_layout(world, document_tree("v1 {{record.title}}"), "Doc", project=project)
    run = queue(world, project, layout).json()
    update = world.client.put(
        f"/api/v1/projects/{project['id']}/report-layouts/{layout['id']}/tree",
        json={"tree": document_tree("v2 {{record.title}}"), "base_version": layout["current_version"]},
        headers=auth_headers(world.token),
    )
    assert update.status_code == 200, update.text

    drain()

    assert run_row(db, run["id"]).layout_version == layout["current_version"]


# ---- who can fetch the file ------------------------------------------------------------------------------------


def test_nobody_else_can_see_or_download_a_run(world, client):
    project, layout, run = prepared(world)
    drain()
    other = member_in(world, project, "project_manager")

    assert get_run(world, run["id"], other).status_code == 404
    assert download(world, run["id"], other).status_code == 404
    assert world.client.delete(f"/api/v1/report-runs/{run['id']}", headers=auth_headers(other)).status_code == 404
    assert client.get("/api/v1/report-runs", headers=auth_headers(other)).json() == []
    assert [r["id"] for r in client.get("/api/v1/report-runs", headers=auth_headers(world.token)).json()] == [run["id"]]


def test_the_list_can_be_narrowed_to_an_organisation(world, client):
    _, _, run = prepared(world)
    base = "/api/v1/report-runs"

    mine = client.get(base, params={"organization_id": world.org["id"]}, headers=auth_headers(world.token)).json()
    elsewhere = client.get(base, params={"organization_id": str(uuid.uuid4())}, headers=auth_headers(world.token)).json()

    assert [r["id"] for r in mine] == [run["id"]] and elsewhere == []


def test_a_requester_who_has_since_lost_access_cannot_download_the_file(world, db):
    project = world.project()
    world.requirement(project, "One")
    layout = make_layout(world, document_tree(), "Doc", project=project)
    member = member_in(world, project)
    run = queue(world, project, layout, token=member).json()
    drain()
    assert download(world, run["id"], member).status_code == 200
    from app.models.user import User

    db.get(User, run_row(db, run["id"]).requested_by).is_archived = True
    db.commit()

    assert download(world, run["id"], member).status_code in (401, 403, 404)


# ---- generating again and the in-progress list ------------------------------------------------------------------


def again(world: World, run_id: str, token: str | None = None):
    return world.client.post(f"/api/v1/report-runs/{run_id}/again", headers=auth_headers(token or world.token))


def test_an_expired_run_can_be_generated_again_as_a_fresh_queued_run(world, db):
    project, layout, run = prepared(world)
    drain()
    world.client.delete(f"/api/v1/report-runs/{run['id']}", headers=auth_headers(world.token))
    assert get_run(world, run["id"]).json()["status"] == "expired"

    resp = again(world, run["id"])

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["run"]["id"] != run["id"] and body["run"]["status"] == "queued" and body["run"]["format"] == "pdf"
    assert body["definition_changed"] is False
    drain()
    new_row = run_row(db, body["run"]["id"])
    assert new_row.status == "ready" and new_row.layout_id == uuid.UUID(layout["id"])
    assert download(world, body["run"]["id"]).content.startswith(b"%PDF")
    assert run_row(db, run["id"]).status == "expired"  # the old row stays as provenance


def test_a_failed_run_can_be_generated_again_and_says_when_the_layout_changed(world, db):
    project, layout, run = prepared(world)
    row = run_row(db, run["id"])
    row.status, row.error = "failed", report_run_jobs.FAILURE_OTHER
    db.commit()
    world.client.put(
        f"/api/v1/projects/{project['id']}/report-layouts/{layout['id']}/tree",
        json={"tree": document_tree("v2 {{record.title}}"), "base_version": layout["current_version"]},
        headers=auth_headers(world.token),
    )

    body = again(world, run["id"]).json()

    assert body["definition_changed"] is True
    assert run_row(db, body["run"]["id"]).layout_version == layout["current_version"] + 1  # today's version, not the old one


def test_a_run_that_is_waiting_preparing_or_downloadable_is_not_generated_again(world, db):
    _, _, run = prepared(world)
    assert again(world, run["id"]).status_code == 409  # waiting
    drain()
    assert again(world, run["id"]).status_code == 409  # ready: download it


def test_generating_again_keeps_the_format_scope_and_variable_values(world, db):
    project = world.project()
    world.requirement(project, "One")
    layout = make_layout(world, sheet_tree(), "Sheet", project=project)
    run = queue(world, project, layout, format="xlsx", include_children=True).json()
    drain()
    world.client.delete(f"/api/v1/report-runs/{run['id']}", headers=auth_headers(world.token))

    body = again(world, run["id"]).json()

    new_row = run_row(db, body["run"]["id"])
    assert new_row.format == "xlsx" and new_row.project_id == uuid.UUID(project["id"])
    assert new_row.params["include_children"] is True and new_row.params["variables"] == run_row(db, run["id"]).params["variables"]


def test_only_the_requester_can_generate_a_run_again(world, db):
    project, layout, run = prepared(world)
    row = run_row(db, run["id"])
    row.status = "expired"
    db.commit()
    other = member_in(world, project)

    assert again(world, run["id"], token=other).status_code == 404


def test_a_requester_who_lost_access_cannot_generate_again(world, db):
    from app.models.user import User

    project = world.project()
    world.requirement(project, "One")
    layout = make_layout(world, document_tree(), "Doc", project=project)
    member = member_in(world, project)
    run = queue(world, project, layout, token=member).json()
    row = run_row(db, run["id"])
    row.status = "expired"
    db.get(User, row.requested_by).is_archived = True
    db.commit()

    assert again(world, run["id"], token=member).status_code in (401, 403, 404)


def test_a_deleted_layout_cannot_be_generated_again(world, db):
    project, layout, run = prepared(world)
    drain()
    world.client.delete(f"/api/v1/report-runs/{run['id']}", headers=auth_headers(world.token))
    deleted = world.client.delete(f"/api/v1/projects/{project['id']}/report-layouts/{layout['id']}", headers=auth_headers(world.token))
    assert deleted.status_code in (200, 204), deleted.text

    assert again(world, run["id"]).status_code == 404


def test_generating_again_counts_against_the_queue_limit(world, db, monkeypatch):
    _, _, first = prepared(world)
    _, _, second = prepared(world)
    drain()
    for run in (first, second):
        world.client.delete(f"/api/v1/report-runs/{run['id']}", headers=auth_headers(world.token))
    monkeypatch.setattr(report_run_jobs, "MAX_ACTIVE_PER_USER", 1)

    assert again(world, first["id"]).status_code == 202
    assert again(world, second["id"]).status_code == 429


def test_the_list_can_be_narrowed_to_runs_in_progress(world, db):
    _, _, waiting = prepared(world)
    project = world.project()
    world.requirement(project, "Two")
    done_layout = make_layout(world, document_tree(), "Done", project=project)
    done = queue(world, project, done_layout).json()
    row = run_row(db, done["id"])
    row.status = "ready"
    db.commit()

    everything = world.client.get("/api/v1/report-runs", headers=auth_headers(world.token)).json()
    active = world.client.get("/api/v1/report-runs?active=true", headers=auth_headers(world.token)).json()

    assert {r["id"] for r in everything} >= {waiting["id"], done["id"]}
    assert [r["id"] for r in active] == [waiting["id"]]


# ---- removing and expiring -------------------------------------------------------------------------------------


def test_the_requester_can_remove_the_stored_file_early(world, db):
    _, _, run = prepared(world)
    drain()
    key = run_row(db, run["id"]).output_key

    resp = world.client.delete(f"/api/v1/report-runs/{run['id']}", headers=auth_headers(world.token))

    assert resp.status_code == 200 and resp.json()["status"] == "expired"
    assert not get_storage_backend().exists(key)
    assert download(world, run["id"]).status_code == 404
    assert run_row(db, run["id"]).source_digest  # provenance stays


def test_a_queued_run_can_be_cancelled(world, db):
    _, _, run = prepared(world)

    resp = world.client.delete(f"/api/v1/report-runs/{run['id']}", headers=auth_headers(world.token))

    assert resp.json()["status"] == "failed" and resp.json()["error"] == "Cancelled."
    drain()
    assert run_row(db, run["id"]).status == "failed"


def test_a_run_being_prepared_cannot_be_removed(world, db):
    _, _, run = prepared(world)
    row = run_row(db, run["id"])
    row.status, row.started_at = "running", datetime.now(UTC)
    db.commit()

    assert world.client.delete(f"/api/v1/report-runs/{run['id']}", headers=auth_headers(world.token)).status_code == 409


def test_expiry_deletes_the_file_and_keeps_the_provenance(world, db):
    _, _, run = prepared(world)
    drain()
    row = run_row(db, run["id"])
    key = row.output_key
    assert get_storage_backend().exists(key)

    counts = report_run_jobs.expire(db, now=row.expires_at + timedelta(seconds=1))

    assert counts["expired"] >= 1
    row = run_row(db, run["id"])
    assert row.status == "expired" and row.output_key is None and row.output_size is None and row.source_digest
    assert not get_storage_backend().exists(key)
    assert download(world, run["id"]).status_code == 404


def test_a_file_past_its_expiry_is_refused_even_before_the_expiry_job_reaches_it(world, db):
    _, _, run = prepared(world)
    drain()
    row = run_row(db, run["id"])
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert download(world, run["id"]).status_code == 404


def test_a_file_not_yet_expired_is_left_alone(world, db):
    _, _, run = prepared(world)
    drain()

    report_run_jobs.expire(db)

    assert run_row(db, run["id"]).status == "ready"


def test_a_job_left_running_past_its_deadline_is_marked_failed_not_rerun(world, db):
    _, _, run = prepared(world)
    row = run_row(db, run["id"])
    row.status = "running"
    row.started_at = datetime.now(UTC) - timedelta(seconds=report_layout_eval.ASYNC_TIMEOUT_SECONDS + 600)
    db.commit()

    counts = report_run_jobs.expire(db)

    assert counts["lost"] >= 1
    row = run_row(db, run["id"])
    assert row.status == "failed" and row.error == report_run_jobs.FAILURE_LOST
    drain()
    assert run_row(db, run["id"]).status == "failed"


def test_old_provenance_rows_are_deleted_and_active_ones_never(world, db):
    project, layout, queued = prepared(world)
    assert project_run(world, project, layout, format="pdf").status_code == 200  # a completed row
    old = datetime.now(UTC) - timedelta(days=get_settings().report_run_record_retention_days + 5)
    for row in db.scalars(select(GeneratedReport).where(GeneratedReport.layout_id == uuid.UUID(layout["id"]))).all():
        row.created_at = old
    db.commit()

    counts = report_run_jobs.expire(db)

    assert counts["purged"] == 1  # the completed run; the queued job is still wanted
    assert run_row(db, queued["id"]).status == "queued"


def test_deleting_the_organisation_deletes_its_stored_report_files(world, client, db, admin_token):
    _, _, run = prepared(world)
    drain()
    key = run_row(db, run["id"]).output_key
    assert get_storage_backend().exists(key)

    resp = client.request(
        "DELETE", f"/api/v1/orgs/{world.org['id']}", json={"confirm_name": world.org["name"]}, headers=auth_headers(admin_token),
    )

    assert resp.status_code == 204, resp.text
    assert not get_storage_backend().exists(key)


# ---- retention -------------------------------------------------------------------------------------------------


def test_retention_is_the_organisations_setting_capped_by_the_platform_ceiling(db):
    settings = get_settings()
    org = Organization(name="x")

    org.report_output_retention_days = None
    assert report_run_jobs.effective_retention_days(org) == settings.report_output_default_retention_days
    org.report_output_retention_days = 1
    assert report_run_jobs.effective_retention_days(org) == 1
    org.report_output_retention_days = settings.report_output_max_retention_days + 100
    assert report_run_jobs.effective_retention_days(org) == settings.report_output_max_retention_days


def test_the_organisation_admin_sets_the_retention_in_the_advanced_settings(world, client, db):
    url = f"/api/v1/orgs/{world.org['id']}/advanced-settings"
    current = client.get(url, headers=auth_headers(world.token)).json()
    assert current["report_output_retention_days"] is None

    resp = client.put(url, json={**current, "report_output_retention_days": 3}, headers=auth_headers(world.token))

    assert resp.status_code == 200 and resp.json()["report_output_retention_days"] == 3
    assert client.put(url, json={**current, "report_output_retention_days": 0}, headers=auth_headers(world.token)).status_code == 422
    _, _, run = prepared(world)
    drain()
    row = run_row(db, run["id"])
    assert abs((row.expires_at - row.finished_at) - timedelta(days=3)) < timedelta(seconds=5)
