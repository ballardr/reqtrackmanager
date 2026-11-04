"""Tests for the project Files page's API (`services.project_files`): the report image library as a source, the
filters (file name, source, file type, uploader, upload window), project and nested-project scope, paging with the
filters, and that the file name searched for is never logged or audited.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.file import FileAsset
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World
from tests.test_report_images import layout_body, png, project_images, upload


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Files Page Org")


def files_url(project: dict, suffix: str = "") -> str:
    return f"/api/v1/projects/{project['id']}/files{suffix}"


def attach(world: World, project: dict, name: str, data: bytes = b"data", content_type: str = "text/plain") -> str:
    """Attaches a file to a fresh requirement of the project; returns the file id."""
    req = world.requirement(project, f"Has {name}")
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req}/files",
        files={"file": (name, data, content_type)}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def library(world: World, project: dict, name: str = "logo.png", **png_args) -> str:
    resp = upload(world, project_images(project), png(**png_args), name)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def search(world: World, project: dict, body: dict | None = None, query: str = "", token: str | None = None):
    return world.client.post(
        files_url(project, f"/search{query}"), json=body or {}, headers=auth_headers(token or world.token),
    )


def names(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return sorted(r["file"]["filename"] for r in resp.json())


def stamp(file_id: str, *, created_at: datetime | None = None, uploaded_by: str | None = None) -> None:
    """Sets a file's upload time and uploader directly (the API always uses now and the caller)."""
    with SessionLocal() as db:
        asset = db.get(FileAsset, uuid.UUID(file_id))
        if created_at is not None:
            asset.created_at = created_at
        if uploaded_by is not None:
            asset.uploaded_by = uuid.UUID(uploaded_by)
        db.commit()


def test_a_library_picture_is_listed_with_its_source_and_no_record(world):
    project = world.project("Alpha")
    picture = library(world, project)
    attach(world, project, "spec.txt")

    rows = {r["file"]["id"]: r for r in world.client.get(files_url(project), headers=auth_headers(world.token)).json()}

    row = rows[picture]
    assert row["source"] == "report_image" and row["file"]["filename"] == "logo.png" and row["file"]["content_type"] == "image/png"
    assert row["requirement_id"] is None and row["action_id"] is None and row["comment_id"] is None
    assert row["uploaded_by_display_name"] and row["file"]["size_bytes"] > 0


def test_a_library_picture_used_by_a_layout_is_still_one_row(world):
    project = world.project("Alpha")
    picture = library(world, project)
    made = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts", json=layout_body("Uses it", picture),
        headers=auth_headers(world.token),
    )
    assert made.status_code == 201, made.text

    assert names(world.client.get(files_url(project), headers=auth_headers(world.token))) == ["logo.png"]


def test_another_projects_and_the_organisations_pictures_are_not_listed(world):
    project, other = world.project("Alpha"), world.project("Beta")
    library(world, other, "beta-only.png")
    org_picture = upload(world, f"/api/v1/orgs/{world.org['id']}/report-images", png(), "org-logo.png")
    assert org_picture.status_code == 201, org_picture.text
    library(world, project, "alpha.png")

    assert names(world.client.get(files_url(project), headers=auth_headers(world.token))) == ["alpha.png"]


def test_a_confidential_picture_follows_the_librarys_rule_and_stays_listed_for_members(world):
    project = world.project("Alpha")
    picture = library(world, project, "secret.png")
    marked = world.client.patch(
        f"/api/v1/files/{picture}/confidential", json={"confidential": True}, headers=auth_headers(world.token),
    )
    assert marked.status_code == 200, marked.text

    rows = world.client.get(files_url(project), headers=auth_headers(world.token)).json()

    assert [(r["file"]["filename"], r["file"]["confidential"]) for r in rows] == [("secret.png", True)]


def test_a_person_with_no_role_on_the_project_cannot_list_or_search_or_see_the_uploaders(world):
    project = world.project("Alpha")
    library(world, project)
    outsider = f"outsider-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], outsider)
    token = login(world.client, outsider, "Password123!")

    assert world.client.get(files_url(project), headers=auth_headers(token)).status_code == 403
    assert search(world, project, token=token).status_code == 403
    assert world.client.get(files_url(project, "/uploaders"), headers=auth_headers(token)).status_code == 403


def test_search_matches_the_file_name_only_and_ignores_case_and_wildcards(world):
    project = world.project("Alpha")
    attach(world, project, "Site-Plan_v2.txt")
    attach(world, project, "budget.txt")
    attach(world, project, "100%.txt")
    # The text of a file's requirement and its content are not searched, only its name.
    req = world.requirement(project, "Mentions plan in its title")
    assert req

    assert names(search(world, project, {"search": "site-plan"})) == ["Site-Plan_v2.txt"]
    assert names(search(world, project, {"search": "PLAN"})) == ["Site-Plan_v2.txt"]
    assert names(search(world, project, {"search": "%"})) == ["100%.txt"]  # a literal percent sign, not a wildcard
    assert names(search(world, project, {"search": "_"})) == ["Site-Plan_v2.txt"]  # a literal underscore
    assert names(search(world, project, {"search": "nothing-like-this"})) == []
    assert names(search(world, project, {"search": "  "})) == ["100%.txt", "Site-Plan_v2.txt", "budget.txt"]


def test_source_filter_keeps_only_the_chosen_sources(world):
    project = world.project("Alpha")
    attach(world, project, "attached.txt")
    library(world, project, "picture.png")

    assert names(search(world, project, {"sources": ["report_image"]})) == ["picture.png"]
    assert names(search(world, project, {"sources": ["requirement_attachment"]})) == ["attached.txt"]
    assert names(search(world, project, {"sources": ["action_attachment", "comment_attachment"]})) == []
    assert names(search(world, project, {"sources": ["requirement_attachment", "report_image"]})) == ["attached.txt", "picture.png"]
    assert names(search(world, project, {})) == ["attached.txt", "picture.png"]


def test_file_type_filter_splits_images_documents_and_others(world):
    project = world.project("Alpha")
    attach(world, project, "notes.txt", content_type="text/plain")
    attach(world, project, "spec.pdf", b"%PDF-1.4", "application/pdf")
    attach(world, project, "sheet.xlsx", b"x", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    attach(world, project, "archive.zip", b"PK", "application/zip")
    attach(world, project, "photo.jpg", png(), "image/jpeg")
    library(world, project, "logo.png")

    assert names(search(world, project, {"kind": "image"})) == ["logo.png", "photo.jpg"]
    assert names(search(world, project, {"kind": "document"})) == ["notes.txt", "sheet.xlsx", "spec.pdf"]
    assert names(search(world, project, {"kind": "other"})) == ["archive.zip"]


def test_uploader_filter_and_the_uploader_choices(world):
    project = world.project("Alpha")
    mine = attach(world, project, "mine.txt")
    theirs = attach(world, project, "theirs.txt")
    colleague = create_org_user(world.client, world.token, world.org["id"], f"colleague-{uuid.uuid4().hex[:6]}@example.com")
    stamp(theirs, uploaded_by=colleague)

    assert names(search(world, project, {"uploaded_by": str(world.user_id)})) == ["mine.txt"]
    assert names(search(world, project, {"uploaded_by": colleague})) == ["theirs.txt"]
    people = world.client.get(files_url(project, "/uploaders"), headers=auth_headers(world.token)).json()
    assert sorted(p["id"] for p in people) == sorted([str(world.user_id), colleague])
    assert [p["display_name"].lower() for p in people] == sorted(p["display_name"].lower() for p in people)
    assert mine


def window(day: str, tz_hours: int) -> dict:
    """The two UTC instants bounding a person's local calendar day `day` at UTC+`tz_hours` (what the browser sends)."""
    zone = timezone(timedelta(hours=tz_hours))
    start = datetime.fromisoformat(day).replace(tzinfo=zone)
    return {
        "uploaded_from": start.astimezone(UTC).isoformat(),
        "uploaded_before": (start + timedelta(days=1)).astimezone(UTC).isoformat(),
    }


def test_the_upload_window_respects_the_boundary_hours_at_utc_plus_10_and_minus_8(world):
    project = world.project("Alpha")
    early = attach(world, project, "early-in-sydney.txt")  # 09:00 on 4 Nov at UTC+10 = 23:00 UTC on 3 Nov
    late = attach(world, project, "late-in-la.txt")  # 23:00 on 4 Nov at UTC-8 = 07:00 UTC on 5 Nov
    stamp(early, created_at=datetime(2026, 11, 3, 23, 0, tzinfo=UTC))
    stamp(late, created_at=datetime(2026, 11, 5, 7, 0, tzinfo=UTC))

    sydney = window("2026-11-04", 10)
    los_angeles = window("2026-11-04", -8)

    assert names(search(world, project, sydney)) == ["early-in-sydney.txt"]
    assert names(search(world, project, los_angeles)) == ["late-in-la.txt"]
    # The start is inclusive and the end exclusive: a file at the exact instant of a boundary falls in one day only.
    edge = attach(world, project, "edge.txt")
    stamp(edge, created_at=datetime.fromisoformat(sydney["uploaded_before"]))
    assert "edge.txt" not in names(search(world, project, sydney))
    assert "edge.txt" in names(search(world, project, window("2026-11-05", 10)))
    # One-sided windows work.
    assert "early-in-sydney.txt" not in names(search(world, project, {"uploaded_from": sydney["uploaded_before"]}))
    assert names(search(world, project, {"uploaded_before": sydney["uploaded_from"]})) == []


def test_a_time_without_a_zone_is_refused(world):
    project = world.project("Alpha")

    resp = search(world, project, {"uploaded_from": "2026-11-04T00:00:00"})

    assert resp.status_code == 422


def test_filters_combine_and_the_count_and_paging_follow_them(world):
    project = world.project("Alpha")
    for index in range(5):
        attach(world, project, f"report-{index}.txt")
    attach(world, project, "other.txt")
    library(world, project, "report-logo.png")

    first = search(world, project, {"search": "report", "sources": ["requirement_attachment"]}, "?limit=2&offset=0")
    last = search(world, project, {"search": "report", "sources": ["requirement_attachment"]}, "?limit=2&offset=4")

    assert first.headers["X-Total-Count"] == last.headers["X-Total-Count"] == "5"
    assert len(first.json()) == 2 and len(last.json()) == 1
    everything = world.client.get(files_url(project), headers=auth_headers(world.token))
    assert everything.headers["X-Total-Count"] == "7"


def test_filters_apply_across_the_related_projects_in_scope_and_never_leak_an_unrelated_one(world):
    root = world.project("Root")
    child = world.project("Child", parent=root)
    stranger = world.project("Stranger")
    library(world, root, "root-logo.png")
    library(world, child, "child-logo.png")
    attach(world, root, "root-notes.txt")
    library(world, stranger, "stranger-logo.png")

    own = search(world, child, {"kind": "image"})
    wide = search(world, child, {"kind": "image"}, "?project_scope=parents")

    assert names(own) == ["child-logo.png"]
    assert names(wide) == ["child-logo.png", "root-logo.png"]
    labelled = {r["file"]["filename"]: r["from_project_id"] for r in wide.json()}
    assert labelled == {"child-logo.png": None, "root-logo.png": root["id"]}
    assert wide.headers["X-Total-Count"] == "2"
    people = world.client.get(files_url(child, "/uploaders?project_scope=parents"), headers=auth_headers(world.token)).json()
    assert [p["id"] for p in people] == [str(world.user_id)]  # one person once, though both projects have their uploads


def test_the_search_text_is_never_logged_audited_or_put_in_a_url(world, caplog):
    project = world.project("Alpha")
    attach(world, project, "payroll-merger.txt")
    needle = "zq-needle-8841"
    with SessionLocal() as db:
        before = len(db.scalars(select(AuditEvent)).all())

    with caplog.at_level(logging.DEBUG):
        resp = search(world, project, {"search": needle})

    assert resp.status_code == 200 and resp.json() == []
    assert needle not in caplog.text
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent)).all()
    assert len(events) == before  # a read writes no audit event
    assert not any(needle in str(event.detail) for event in events)
    assert needle not in str(resp.request.url)
