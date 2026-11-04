"""Tests for the shared layout draft (`services.report_layouts`, `routers.report_layouts`): create, update, read and discard,
the revision conflict, an identical draft being dropped, an invalid draft being stored but not published, publishing as the
next version in one transaction, scoping and permissions, that no run, list, copy or bundle sees a draft, and that versions
are still never updated. Each test builds its own organisation.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.report_layout import ReportLayoutDraft, ReportLayoutVersion
from app.services.report_layout_tree import MAX_TREE_BYTES, empty_tree
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Drafts Org")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def tree(text: str = "Hello") -> dict:
    return {**empty_tree("document"), "nodes": [{"type": "heading", "text": text}]}


def org_url(world: World, suffix: str = "") -> str:
    return f"/api/v1/orgs/{world.org['id']}/report-layouts{suffix}"


def project_url(project: dict, suffix: str = "") -> str:
    return f"/api/v1/projects/{project['id']}/report-layouts{suffix}"


def new_layout(world: World, url: str, name: str = "Gap report", body: dict | None = None) -> dict:
    resp = world.client.post(
        url, json={"name": name, "description": "d", "family": "document", "tree": body or tree(name)}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def put_draft(world: World, url: str, body: dict, *, base: int = 1, revision: int = 0, token: str | None = None):
    return world.client.put(
        f"{url}/draft", json={"tree": body, "base_version": base, "revision": revision}, headers=auth_headers(token or world.token),
    )


def draft_of(resp) -> dict:
    assert resp.status_code == 200, resp.text
    return resp.json()["draft"]


def publish(world: World, url: str, **body):
    return world.client.put(f"{url}/tree", json={"from_draft": True, **body}, headers=auth_headers(world.token))


def versions(world: World, url: str) -> list[dict]:
    return world.client.get(f"{url}/versions", headers=auth_headers(world.token)).json()


# ---- create, update, read, discard -----------------------------------------------------------------------------


def test_a_draft_is_created_updated_read_and_discarded(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    h = auth_headers(world.token)
    assert world.client.get(f"{url}/draft", headers=h).status_code == 404
    assert world.client.get(url, headers=h).json()["draft"] is None

    first = draft_of(put_draft(world, url, tree("One")))
    assert first["revision"] == 1 and first["base_version"] == 1 and first["tree"] == tree("One") and first["problems"] == []
    assert first["updated_by"] == str(world.user_id) and first["updated_by_name"]
    second = draft_of(put_draft(world, url, tree("Two"), revision=1))
    assert second["revision"] == 2 and second["tree"] == tree("Two")

    read = world.client.get(f"{url}/draft", headers=h).json()
    assert read["tree"] == tree("Two") and read["revision"] == 2
    summary = world.client.get(url, headers=h).json()["draft"]
    assert summary["revision"] == 2 and summary["base_version"] == 1 and "tree" not in summary
    assert world.client.get(url, headers=h).json()["current"]["tree"] == tree("Gap report")

    assert world.client.delete(f"{url}/draft", headers=h).status_code == 204
    assert world.client.get(f"{url}/draft", headers=h).status_code == 404
    assert world.client.delete(f"{url}/draft", headers=h).status_code == 404
    assert world.client.get(url, headers=h).json()["draft"] is None


def test_an_autosave_changes_no_version(world, db):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")

    revision = 0
    for n in range(5):
        revision = draft_of(put_draft(world, url, tree(f"Edit {n}"), revision=revision))["revision"]

    assert [v["version"] for v in versions(world, url)] == [1]
    assert db.scalar(select(func.count()).select_from(ReportLayoutDraft)) >= 1
    assert world.client.get(url, headers=auth_headers(world.token)).json()["current_version"] == 1


def test_a_draft_equal_to_the_saved_version_is_removed_not_stored(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    h = auth_headers(world.token)
    draft_of(put_draft(world, url, tree("Changed")))

    cleared = put_draft(world, url, tree("Gap report"), revision=1)

    assert cleared.status_code == 200 and cleared.json()["draft"] is None
    assert world.client.get(f"{url}/draft", headers=h).status_code == 404
    assert put_draft(world, url, tree("Gap report")).json()["draft"] is None  # nothing to store


def test_an_invalid_tree_is_stored_with_its_problems_but_cannot_be_published(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    broken = {**empty_tree("document"), "nodes": [{"type": "nope"}]}

    saved = draft_of(put_draft(world, url, broken))

    assert saved["tree"] == broken and saved["problems"] and saved["problems"][0]["path"].startswith("nodes[0]")
    assert world.client.get(f"{url}/draft", headers=auth_headers(world.token)).json()["problems"] == saved["problems"]
    refused = publish(world, url)
    assert refused.status_code == 422 and refused.json()["detail"]["errors"]
    assert [v["version"] for v in versions(world, url)] == [1]
    assert world.client.get(f"{url}/draft", headers=auth_headers(world.token)).status_code == 200  # the draft is kept


def test_a_tree_over_the_size_limit_is_refused(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    huge = {**empty_tree("document"), "pad": "x" * (MAX_TREE_BYTES + 10)}

    assert put_draft(world, url, huge).status_code == 422
    assert world.client.get(f"{url}/draft", headers=auth_headers(world.token)).status_code == 404


def test_the_base_version_must_be_a_real_one(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")

    assert put_draft(world, url, tree("x"), base=2).status_code == 422
    assert put_draft(world, url, tree("x"), base=0).status_code == 422  # below the schema's minimum


# ---- conflicts -------------------------------------------------------------------------------------------------


def test_a_stale_revision_is_refused_naming_who_changed_it(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("Mine")))
    email = f"b-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email, role="org_admin")
    draft_of(put_draft(world, url, tree("Theirs"), revision=1))

    stale = put_draft(world, url, tree("Mine again"), revision=1)

    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "draft_conflict" and detail["draft"]["revision"] == 2 and detail["draft"]["updated_by_name"]
    assert world.client.get(f"{url}/draft", headers=auth_headers(world.token)).json()["tree"] == tree("Theirs")


def test_a_write_expecting_a_draft_that_is_gone_is_a_conflict_with_no_draft(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("Mine")))
    world.client.delete(f"{url}/draft", headers=auth_headers(world.token))

    gone = put_draft(world, url, tree("Mine again"), revision=1)

    assert gone.status_code == 409 and gone.json()["detail"]["draft"] is None


def test_a_write_expecting_no_draft_when_one_exists_is_a_conflict(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("First")))

    assert put_draft(world, url, tree("Second"), revision=0).status_code == 409


def test_a_new_draft_cannot_start_from_an_old_version(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    world.client.put(f"{url}/tree", json={"tree": tree("v2"), "base_version": 1}, headers=auth_headers(world.token))

    stale = put_draft(world, url, tree("From v1"), base=1)

    assert stale.status_code == 409 and stale.json()["detail"]["current_version"] == 2
    assert draft_of(put_draft(world, url, tree("From v2"), base=2))["base_version"] == 2


# ---- publishing ------------------------------------------------------------------------------------------------


def test_publishing_makes_the_next_version_and_removes_the_draft(world, db):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("Final")))

    resp = publish(world, url, comment="ready", draft_revision=1)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_version"] == 2 and body["current"]["tree"] == tree("Final") and body["current"]["comment"] == "ready"
    assert body["current"]["created_by"] == str(world.user_id) and body["draft"] is None
    assert world.client.get(f"{url}/draft", headers=auth_headers(world.token)).status_code == 404
    assert [(v["version"], v["comment"]) for v in versions(world, url)] == [(2, "ready"), (1, "")]
    event = db.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == layout["id"], AuditEvent.action == "version_saved")
    ).one()
    assert event.detail["version"] == 2 and event.detail["from_draft"] is True and "Final" not in str(event.detail)


def test_publishing_someone_elses_draft_makes_the_publisher_the_author(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    email = f"p-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email, role="org_admin")
    other = login(world.client, email, "Password123!")
    draft_of(put_draft(world, url, tree("Theirs"), token=other))

    resp = publish(world, url)

    assert resp.status_code == 200 and resp.json()["current"]["created_by"] == str(world.user_id)


def test_publishing_with_no_draft_is_not_found(world):
    layout = new_layout(world, org_url(world))

    assert publish(world, org_url(world, f"/{layout['id']}")).status_code == 404


def test_publishing_a_draft_written_since_is_a_conflict_and_keeps_the_draft(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("A")))
    draft_of(put_draft(world, url, tree("B"), revision=1))

    stale = publish(world, url, draft_revision=1)

    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "draft_conflict"
    assert world.client.get(f"{url}/draft", headers=auth_headers(world.token)).json()["tree"] == tree("B")
    assert [v["version"] for v in versions(world, url)] == [1]


def test_publishing_after_a_version_was_published_meanwhile_is_a_conflict_and_keeps_the_draft(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("Draft")))
    world.client.put(f"{url}/tree", json={"tree": tree("Direct"), "base_version": 1}, headers=auth_headers(world.token))

    stale = publish(world, url)

    assert stale.status_code == 409 and stale.json()["detail"]["current_version"] == 2
    still = world.client.get(f"{url}/draft", headers=auth_headers(world.token)).json()
    assert still["tree"] == tree("Draft") and still["base_version"] == 1
    assert world.client.get(url, headers=auth_headers(world.token)).json()["draft"]["base_version"] == 1
    # Writing the draft on the current version moves its base, and then it publishes.
    draft_of(put_draft(world, url, tree("Draft"), base=2, revision=1))
    assert publish(world, url).json()["current_version"] == 3


def test_a_failed_publish_keeps_the_draft_in_the_same_transaction(world, db):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, {**empty_tree("document"), "nodes": [{"type": "nope"}]}))

    assert publish(world, url).status_code == 422

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ReportLayoutDraft).where(ReportLayoutDraft.layout_id == uuid.UUID(layout["id"]))) == 1
    assert db.scalar(select(func.count()).select_from(ReportLayoutVersion).where(ReportLayoutVersion.layout_id == uuid.UUID(layout["id"]))) == 1


def test_a_save_names_a_tree_or_the_draft_never_both_or_neither(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}/tree")
    h = auth_headers(world.token)

    assert world.client.put(url, json={}, headers=h).status_code == 422
    assert world.client.put(url, json={"tree": tree("x"), "from_draft": True}, headers=h).status_code == 422
    assert world.client.put(url, json={"from_draft": True, "base_version": 1}, headers=h).status_code == 422
    assert world.client.put(url, json={"tree": tree("x")}, headers=h).status_code == 422  # a base version is required
    assert world.client.put(url, json={"tree": tree("x"), "base_version": 1, "draft_revision": 1}, headers=h).status_code == 422


def test_a_direct_save_leaves_the_draft_alone(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("Unfinished")))

    saved = world.client.put(f"{url}/tree", json={"tree": tree("Agent"), "base_version": 1}, headers=auth_headers(world.token))

    assert saved.status_code == 200 and saved.json()["current_version"] == 2
    assert saved.json()["draft"]["base_version"] == 1  # an agent or script learns a person has unpublished work


# ---- discard audit, cascade, immutability ----------------------------------------------------------------------


def test_discarding_is_audited_without_the_tree_and_autosave_is_not(world, db):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("Secret wording")))
    draft_of(put_draft(world, url, tree("More secret wording"), revision=1))
    world.client.delete(f"{url}/draft", headers=auth_headers(world.token))

    events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == layout["id"]).order_by(AuditEvent.created_at)).all()

    assert [e.action for e in events] == ["created", "draft_discarded"]
    assert events[1].actor_id == world.user_id and events[1].detail["revision"] == 2
    assert "secret" not in " ".join(str(e.detail) for e in events).casefold()


def test_deleting_the_layout_deletes_its_draft(world, db):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("x")))

    assert world.client.delete(url, headers=auth_headers(world.token)).status_code == 204

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ReportLayoutDraft).where(ReportLayoutDraft.layout_id == uuid.UUID(layout["id"]))) == 0


def test_a_saved_version_is_still_never_rewritten(world, db):
    layout = new_layout(world, org_url(world))
    draft_of(put_draft(world, org_url(world, f"/{layout['id']}"), tree("x")))
    version = db.scalars(select(ReportLayoutVersion).where(ReportLayoutVersion.layout_id == uuid.UUID(layout["id"]))).one()
    version.tree = tree("Tampered")

    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()


# ---- scope and permissions -------------------------------------------------------------------------------------


def test_a_plain_member_cannot_touch_a_draft(world):
    layout = new_layout(world, org_url(world))
    url = org_url(world, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("x")))
    email = f"m-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    h = auth_headers(login(world.client, email, "Password123!"))

    assert world.client.get(f"{url}/draft", headers=h).status_code == 403
    assert world.client.put(f"{url}/draft", json={"tree": tree("y"), "base_version": 1, "revision": 1}, headers=h).status_code == 403
    assert world.client.delete(f"{url}/draft", headers=h).status_code == 403
    assert world.client.put(f"{url}/tree", json={"from_draft": True}, headers=h).status_code == 403


def test_another_owners_layout_draft_is_not_found_through_this_scope(world):
    first, second = world.project("First"), world.project("Second")
    other = new_layout(world, project_url(second), "Second's")
    own = new_layout(world, project_url(first), "First's")

    assert put_draft(world, project_url(first, f"/{other['id']}"), tree("x")).status_code == 404
    assert put_draft(world, org_url(world, f"/{own['id']}"), tree("x")).status_code == 404


def test_a_project_drafts_its_own_layout(world):
    project = world.project()
    layout = new_layout(world, project_url(project), "Mine")
    url = project_url(project, f"/{layout['id']}")

    assert draft_of(put_draft(world, url, tree("Project edit")))["revision"] == 1
    assert world.client.get(url, headers=auth_headers(world.token)).json()["draft"]["revision"] == 1
    assert publish(world, url).json()["current_version"] == 2
    assert world.client.get(f"{url}/draft", headers=auth_headers(world.token)).status_code == 404


def test_a_project_cannot_draft_an_inherited_layout_or_see_its_draft(world):
    project = world.project()
    inherited = new_layout(world, org_url(world), "Org wide")
    draft_of(put_draft(world, org_url(world, f"/{inherited['id']}"), tree("Org unfinished")))
    url = project_url(project, f"/{inherited['id']}")
    h = auth_headers(world.token)

    assert put_draft(world, url, tree("x")).status_code == 403
    assert world.client.get(f"{url}/draft", headers=h).status_code == 403
    assert world.client.delete(f"{url}/draft", headers=h).status_code == 403
    assert world.client.put(f"{url}/tree", json={"from_draft": True}, headers=h).status_code == 403
    seen = world.client.get(url, headers=h).json()
    assert seen["editable"] is False and seen["draft"] is None and seen["current"]["tree"] == tree("Org wide")


def test_a_plain_project_member_cannot_draft(world):
    project = world.project()
    layout = new_layout(world, project_url(project), "Mine")
    email = f"v-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    world.client.post(f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "viewer"}, headers=auth_headers(world.token))
    token = login(world.client, email, "Password123!")

    assert put_draft(world, project_url(project, f"/{layout['id']}"), tree("x"), token=token).status_code == 403


# ---- nothing else sees a draft ---------------------------------------------------------------------------------


def test_a_run_a_list_a_duplicate_and_a_bundle_see_versions_not_the_draft(world, db):
    project = world.project("Source")
    layout = new_layout(world, project_url(project), "Report", body=tree("Published wording"))
    url = project_url(project, f"/{layout['id']}")
    draft_of(put_draft(world, url, tree("Unpublished wording")))
    h = auth_headers(world.token)

    run = world.client.get(f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": "html"}, headers=h)
    assert run.status_code == 200
    assert b"Published wording" in run.content and b"Unpublished wording" not in run.content

    listed = world.client.get(project_url(project), headers=h).json()
    assert [row["name"] for row in listed] == ["Report"] and "draft" not in listed[0]

    copy = world.client.post(
        f"/api/v1/projects/{project['id']}/report-duplicate",
        json={"target": "project", "kind": "layout", "source_id": layout["id"]}, headers=h,
    )
    assert copy.status_code == 200, copy.text
    copied = world.client.get(project_url(project, f"/{copy.json()['new_id']}"), headers=h).json()
    assert copied["current"]["tree"] == tree("Published wording") and copied["draft"] is None

    bundle = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as z:
        everything = b"".join(z.read(n) for n in z.namelist())
    assert b"Published wording" in everything and b"Unpublished wording" not in everything


def test_listing_layouts_reads_no_drafts(world, db):
    from sqlalchemy import event

    from app.database import engine

    for n in range(3):
        layout = new_layout(world, org_url(world), f"L{n}")
        draft_of(put_draft(world, org_url(world, f"/{layout['id']}"), tree(f"d{n}")))
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert world.client.get(org_url(world), headers=auth_headers(world.token)).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert not any("report_layout_drafts" in s for s in statements)

