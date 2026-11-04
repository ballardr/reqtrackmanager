"""Tests for triaging an organisation-inbox request into a project (`move-to-project`): the id, status, comments and
history are kept; the code is renumbered from the project's counter; tags are re-resolved in the project's vocabulary;
files become project files; and the gates in both tiers apply. Each test builds its own organisation."""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.file import FileAsset
from app.models.relationship import ArtefactLink
from app.models.tag import ArtefactTag, Tag
from app.models.user import User
from app.modules.product_feedback.tests._helpers import (
    add_member,
    create_inbox_request,
    create_request,
    grant_org_role,
    org_base,
    project_base,
    setup,
    transition,
)
from app.services import tags as tag_service
from tests.conftest import auth_headers, create_project

TYPE = "enhancement_request"


def move(client, token, org_id, request_id, project_id):
    return client.post(
        f"{org_base(org_id)}/requests/{request_id}/move-to-project", json={"project_id": project_id},
        headers=auth_headers(token),
    )


def any_user_id():
    """Some existing user, to stand as the actor or creator of a row a test writes directly."""
    with SessionLocal() as db:
        return db.scalar(select(User.id).limit(1))


def _is_org_resource(db, file_id) -> bool:
    """Whether a stored file is an organisation shared resource."""
    asset = db.get(FileAsset, file_id)
    assert asset is not None
    return asset.is_org_resource


def tag_inbox_request(org_id, request_id, user_id, names: list[str]) -> None:
    with SessionLocal() as db:
        tag_service.set_record_tags(
            db, scope=tag_service.TagScope(org_id, None), actor_id=user_id, artefact_type=TYPE,
            artefact_id=request_id, names=names,
        )
        db.commit()


def test_a_moved_request_keeps_its_id_status_and_history_and_takes_the_projects_next_code(client, admin_token):
    org, project, token = setup(client, admin_token, "Triage Move Co")
    h = auth_headers(token)
    create_request(client, token, project["id"])  # the project's ENH-001
    inbox = create_inbox_request(client, token, org["id"], title="Dark mode")
    assert inbox["unique_code"] == "ENH-001"
    inbox_base = org_base(org["id"])
    assert transition(client, token, inbox_base, inbox["id"], "under_review").status_code == 200
    client.post(f"{inbox_base}/requests/{inbox['id']}/comments", json={"body": "Seen twice"}, headers=h)

    resp = move(client, token, org["id"], inbox["id"], project["id"])
    assert resp.status_code == 200, resp.text
    moved = resp.json()
    assert moved["id"] == inbox["id"] and moved["scope"] == "project"
    assert moved["project_id"] == project["id"] and moved["organization_id"] is None
    assert moved["unique_code"] == "ENH-002" and moved["status"] == "under_review" and moved["title"] == "Dark mode"

    path = f"{project_base(project['id'])}/requests/{inbox['id']}"
    assert client.get(path, headers=h).json()["unique_code"] == "ENH-002"
    assert [c["body"] for c in client.get(f"{path}/comments", headers=h).json()] == ["Seen twice"]
    versions = client.get(f"{path}/versions", headers=h).json()
    assert versions[-1]["change_note"].startswith("Moved from the organisation inbox (ENH-001)")
    assert versions[-1]["status"] == "under_review" and len(versions) == 3
    # It left the inbox, and the inbox's next code is unaffected.
    assert client.get(f"{inbox_base}/requests", headers=h).json() == []
    assert client.get(f"{inbox_base}/requests/{inbox['id']}", headers=h).status_code == 404
    assert create_inbox_request(client, token, org["id"], title="Next")["unique_code"] == "ENH-002"


def test_the_move_is_one_audit_event_carrying_the_old_code(client, admin_token):
    org, project, token = setup(client, admin_token, "Triage Audit Co")
    inbox = create_inbox_request(client, token, org["id"])
    assert move(client, token, org["id"], inbox["id"], project["id"]).status_code == 200
    with SessionLocal() as db:
        events = list(db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == TYPE, AuditEvent.entity_id == inbox["id"], AuditEvent.action == "moved_to_project")
        ))
    assert len(events) == 1
    assert str(events[0].project_id) == project["id"] and str(events[0].organization_id) == org["id"]
    detail = events[0].detail or {}
    assert detail["from_code"] == "ENH-001" and detail["to_code"] == "ENH-001"
    assert "Dark mode" not in str(detail)  # content is never put in the audit trail
    activity = client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{TYPE}/{inbox['id']}/activity", headers=auth_headers(token),
    )
    assert activity.status_code == 200, activity.text
    assert len(activity.json()["entries"]) >= 2  # the inbox-era "created" event and the move


def test_tags_move_into_the_projects_vocabulary(client, admin_token):
    org, project, token = setup(client, admin_token, "Triage Tags Co")
    inbox = create_inbox_request(client, token, org["id"])
    tag_inbox_request(org["id"], inbox["id"], any_user_id(), ["UX", "Mobile"])
    assert move(client, token, org["id"], inbox["id"], project["id"]).status_code == 200
    with SessionLocal() as db:
        tags = list(db.scalars(
            select(Tag).join(ArtefactTag, ArtefactTag.tag_id == Tag.id)
            .where(ArtefactTag.artefact_type == TYPE, ArtefactTag.artefact_id == inbox["id"])
        ))
        rows = list(db.scalars(select(ArtefactTag).where(ArtefactTag.artefact_id == inbox["id"])))
    assert sorted(t.name for t in tags) == ["Mobile", "UX"]
    assert all(str(t.project_id) == project["id"] for t in tags)  # no organisation tag is left on a project record
    assert all(str(r.project_id) == project["id"] for r in rows)


def test_files_become_project_files_and_follow_project_authorisation(client, admin_token):
    org, project, token = setup(client, admin_token, "Triage Files Co")
    h = auth_headers(token)
    inbox = create_inbox_request(client, token, org["id"])
    base = f"{org_base(org['id'])}/requests/{inbox['id']}"
    upload = client.post(f"{base}/files", files={"file": ("evidence.txt", b"proof", "text/plain")}, headers=h)
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]
    comment = client.post(f"{base}/comments", json={"body": "See attached"}, headers=h).json()
    on_comment = client.post(
        f"{base}/comments/{comment['id']}/files", files={"file": ("shot.png", b"png", "image/png")}, headers=h,
    ).json()["id"]
    with SessionLocal() as db:
        assert all(_is_org_resource(db, f) for f in (file_id, on_comment))

    assert move(client, token, org["id"], inbox["id"], project["id"]).status_code == 200
    with SessionLocal() as db:
        assert not any(_is_org_resource(db, f) for f in (file_id, on_comment))
    files = client.get(f"{project_base(project['id'])}/requests/{inbox['id']}/files", headers=h).json()
    assert [f["id"] for f in files] == [file_id]


def test_only_an_organisation_triager_may_move(client, admin_token):
    org, project, admin = setup(client, admin_token, "Triage Gate Co")
    member_id, member = add_member(client, admin, org["id"], project["id"], "member.triage@example.com")
    inbox = create_inbox_request(client, member, org["id"])
    assert move(client, member, org["id"], inbox["id"], project["id"]).status_code == 403
    grant_org_role(client, admin, org["id"], member_id, "org_feedback_triager")
    assert move(client, member, org["id"], inbox["id"], project["id"]).status_code == 200


def test_the_target_project_must_be_in_the_organisation_and_openable_with_the_list_enabled(client, admin_token):
    org, project, admin = setup(client, admin_token, "Triage Target Co")
    other_org, other_project, _ = setup(client, admin_token, "Triage Other Co")
    inbox = create_inbox_request(client, admin, org["id"])
    assert move(client, admin, org["id"], inbox["id"], other_project["id"]).status_code == 404
    assert move(client, admin, org["id"], inbox["id"], "00000000-0000-0000-0000-000000000000").status_code == 404

    # A project the triager cannot open looks absent too.
    closed = create_project(client, admin, org["id"], "Triage Closed Project")
    member_id, member = add_member(client, admin, org["id"], project["id"], "triager.closed@example.com")
    grant_org_role(client, admin, org["id"], member_id, "org_feedback_triager")
    resp = move(client, member, org["id"], inbox["id"], closed["id"])
    assert resp.status_code in (403, 404)
    # The request is untouched by the refusals.
    assert client.get(f"{org_base(org['id'])}/requests/{inbox['id']}", headers=auth_headers(admin)).status_code == 200


def test_an_organisation_triager_is_an_effective_triager_in_the_organisations_projects(client, admin_token):
    """The organisation triager role carries the `(enhancement_request, manage)` permission, and an organisation-level
    permission applies in every project of the organisation (the platform's permission cascade). So the target
    project's submission policy never stops an organisation triager; the check in the move stays as the second gate."""
    org, project, admin = setup(client, admin_token, "Triage Policy Co")
    member_id, member = add_member(client, admin, org["id"], project["id"], "member.policy@example.com")
    inbox = create_inbox_request(client, member, org["id"])
    resp = client.put(project_base(project["id"]) + "/settings", json={"submission_policy": "triagers"}, headers=auth_headers(admin))
    assert resp.status_code == 200, resp.text
    assert client.post(
        project_base(project["id"]) + "/requests", json={"title": "Blocked"}, headers=auth_headers(member),
    ).status_code == 403
    grant_org_role(client, admin, org["id"], member_id, "org_feedback_triager")
    moved = move(client, member, org["id"], inbox["id"], project["id"])
    assert moved.status_code == 200 and moved.json()["scope"] == "project"


def test_a_request_with_a_link_is_not_moved(client, admin_token):
    org, project, token = setup(client, admin_token, "Triage Link Co")
    inbox = create_inbox_request(client, token, org["id"])
    other = create_request(client, token, project["id"])
    with SessionLocal() as db:
        db.add(ArtefactLink(
            source_type=TYPE, source_id=inbox["id"], target_type=TYPE, target_id=other["id"], created_by=any_user_id(),
        ))
        db.commit()
    resp = move(client, token, org["id"], inbox["id"], project["id"])
    assert resp.status_code == 409 and "links" in resp.json()["detail"]
    assert client.get(f"{org_base(org['id'])}/requests/{inbox['id']}", headers=auth_headers(token)).json()["scope"] == "organization"


def test_a_project_request_cannot_be_moved_again(client, admin_token):
    org, project, token = setup(client, admin_token, "Triage Twice Co")
    inbox = create_inbox_request(client, token, org["id"])
    assert move(client, token, org["id"], inbox["id"], project["id"]).status_code == 200
    # It is no longer an inbox request, so the inbox route no longer finds it.
    assert move(client, token, org["id"], inbox["id"], project["id"]).status_code == 404


def test_an_archived_request_keeps_its_archived_state_through_the_move(client, admin_token):
    org, project, token = setup(client, admin_token, "Triage Archived Co")
    inbox = create_inbox_request(client, token, org["id"])
    client.post(f"{org_base(org['id'])}/requests/{inbox['id']}/archive", headers=auth_headers(token))
    moved = move(client, token, org["id"], inbox["id"], project["id"]).json()
    assert moved["is_archived"] is True and moved["scope"] == "project"
