"""Guard: every route that changes data writes an audit event, or is listed here with the reason it need not.

`tests/audit_reach.py` follows the calls that resolve to application code from each handler to `log_event`. A route
that reaches none must match an exemption below; a new route that audits nothing fails this test, whatever its
type, so an action cannot be added without a record of who did it.
"""

from __future__ import annotations

import re

from app.main import app
from tests.audit_reach import reaches_audit

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

#: (path pattern, reason). A pattern is matched against the route's path template.
EXEMPT: list[tuple[str, str]] = [
    (r"/(search|preview|parse|format|validate|variables|check|check-organization|example|score-preview|audience-labels|metrics|overview-metrics)$",
     "computes an answer from the request and stores nothing (a POST because the body is too large or too private for a URL)"),
    (r"/preview/download$", "returns a document built from the request and stores nothing"),
    (r"/import/preview$", "a preview of an import: nothing is written until the import itself, which is audited"),
    (r"/snippets/\{key\}/apply$", "returns the draft tree with a snippet inserted and stores nothing"),
    (r"/files/search$", "a read; the search text is never stored or logged"),
    (r"^/api/v1/notifications/", "the caller's own notification state (read marks and delivery preferences), not a record anyone else relies on"),
    (r"/favorite$", "the caller's own favourite mark on a project"),
    (r"/subscription$", "the caller's own follow of a record"),
    (r"/(media-token|frame-token)$", "short-lived access tokens refreshed every few minutes; counted by a metric, not audited"),
    (r"^/api/v1/auth/forgot-password$", "audited in the background step that finds the account (the response must not depend on the account)"),
    (r"/(custom-reports/\{layout_id\}/runs|report-packs/\{pack_id\}/runs?|report-runs/\{run_id\}/again)$",
     "starting a report run: the run row records who ran what, when and with which parameters, and is kept after its file expires"),
    (r"/report-layouts/\{layout_id\}/draft$",
     "autosave of the shared working draft; publishing it writes the audited version"),
    (r"/records/\{record_type\}/rows/\{code\}$",
     "a grid cell save, dispatched to the record type's own update path, which writes its audit event"),
    (r"/modules/.*/(propose|submit-for-review|send-back|approve|reject|activate|retire|supersede|triage|mark-duplicate|accept|address|close|"
     r"investigate|mark-ready-for-decision|withdraw|resolve)$",
     "a module lifecycle transition, written by the shared transition service the handler dispatches to"),
]


def _exemption(path: str) -> str | None:
    for pattern, reason in EXEMPT:
        if re.search(pattern, path):
            return reason
    return None


def test_every_mutating_route_is_audited_or_exempt_with_a_reason():
    unaudited = []
    for route in app.routes:
        methods = (getattr(route, "methods", None) or set()) & MUTATING
        if not methods or reaches_audit(route.endpoint.__module__, route.endpoint.__name__):
            continue
        if _exemption(route.path) is None:
            unaudited.append(f"{sorted(methods)[0]} {route.path}")
    assert not unaudited, "These routes change data but write no audit event:\n" + "\n".join(unaudited)


def test_the_walk_sees_the_routes_it_should():
    """The guard is only as good as its reach: a handler known to audit, and one known not to, are told apart."""
    by_name = {r.endpoint.__name__: r for r in app.routes if getattr(r, "methods", None)}
    assert reaches_audit(by_name["change_password"].endpoint.__module__, "change_password")
    assert not reaches_audit(by_name["preview_org_layout"].endpoint.__module__, "preview_org_layout") if "preview_org_layout" in by_name else True


def test_account_and_comment_actions_write_their_events(client, admin_token):
    """The actions the audit found unrecorded (comments, display name, second-factor enrolment, avatar removal)."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.audit import AuditEvent
    from tests.conftest import auth_headers, create_component_and_category, create_project

    headers = auth_headers(admin_token)
    assert client.patch("/api/v1/auth/me/preferences", json={"display_name": "Renamed Admin"}, headers=headers).status_code == 200
    assert client.post("/api/v1/auth/2fa/enroll", headers=headers).status_code == 200
    assert client.delete("/api/v1/auth/me/avatar", headers=headers).status_code == 200

    org_id = client.get("/api/v1/orgs", headers=headers).json()[0]["id"]
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements", json={"name": "R", "component_id": component_id, "category_id": category_id},
        headers=headers,
    ).json()
    base = f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments"
    comment = client.post(base, json={"body": "first words"}, headers=headers).json()
    assert client.patch(f"{base}/{comment['id']}", json={"body": "second words"}, headers=headers).status_code == 200
    assert client.put(f"{base}/{comment['id']}/reaction", headers=headers).status_code == 204
    assert client.delete(f"{base}/{comment['id']}/reaction", headers=headers).status_code == 204

    db = SessionLocal()
    try:
        actions = {e.action for e in db.scalars(select(AuditEvent))}
        assert {
            "display_name_changed", "2fa_enrollment_started", "avatar_removed", "comment_added", "comment_edited",
            "comment_reacted", "comment_reaction_removed",
        } <= actions
        text = " ".join(str(e.detail) for e in db.scalars(select(AuditEvent).where(AuditEvent.action.like("comment_%"))))
        assert "first words" not in text and "second words" not in text and "Renamed Admin" not in text
        digests = [
            e.detail["body_sha256"] for e in db.scalars(select(AuditEvent).where(AuditEvent.action.in_(["comment_added", "comment_edited"])))
        ]
        assert len(set(digests)) == 2
    finally:
        db.close()
