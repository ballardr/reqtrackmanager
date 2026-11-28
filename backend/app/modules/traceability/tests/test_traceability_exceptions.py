"""
Traceability exceptions (`exceptions`, `exception_cover`, `exception_router`, `exception_records`,
`exception_governance`, `exception_bundle`): the part's gating, requesting, who may and may not approve (the requester,
an organisation's enforced rule), what an approved exception covers and how it reads apart from satisfaction, expiry on
the caller's day, rule edits and removal, the state path and its locks, reviews and reminders, export, import and the
project bundle.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.traceability import bundle, exceptions
from app.modules.traceability.tests.test_governance_approval_policy import _enable as _enable_module
from app.modules.traceability.tests.test_governance_baseline_policy import _manual, _set_project, _settings
from app.modules.traceability.tests.test_governance_profiles import _create as _create_profile
from app.modules.traceability.tests.test_traceability_rules import _add_profile_rule, _add_rule, _body, _leaf
from app.services import relationships, review_engine
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_user, create_project_group, login
from tests.link_world import REQ, World

PROJECT = "/api/v1/projects/{project}/modules/traceability"
TYPE = "traceability_exception"
CHECK = "traceability:traceability_rules"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _day(offset: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


@dataclass
class Person:
    id: str
    token: str


class Scenario:
    """One project with the module on, a Required rule that requirements link to a requirement, one unlinked
    requirement, a project manager (who may approve) and a stakeholder (who may not)."""

    def __init__(self, client, admin_token, name: str) -> None:
        self.client = client
        self.world = World(client, admin_token, name)
        _enable_module(client, self.world.token, self.world.org["id"], "traceability")
        self.project = self.world.project()
        self.rule = _add_rule(client, self.world.token, self.project["id"], _body(
            "Requirements link", level="required", requires=_leaf(),
        ))
        self.requirement = self.world.requirement(self.project, "Unlinked")
        self.manager = self.person("project_manager")
        self.member = self.person("stakeholder")

    def person(self, role: str) -> Person:
        email = f"tex_{uuid.uuid4().hex[:8]}@example.com"
        user_id = create_org_user(self.client, self.world.token, self.world.org["id"], email)
        resp = self.client.post(
            f"/api/v1/projects/{self.project['id']}/roles", json={"user_id": user_id, "role": role},
            headers=auth_headers(self.world.token),
        )
        assert resp.status_code == 204, resp.text
        return Person(user_id, login(self.client, email, "Password123!"))

    def url(self, suffix: str = "") -> str:
        return PROJECT.format(project=self.project["id"]) + f"/exceptions{suffix}"

    def request(self, token: str | None = None, status: int = 201, headers: dict | None = None, **fields):
        body = {
            "artefact_type": REQ, "artefact_id": str(self.requirement), "rule_id": self.rule["id"],
            "reason": "Accepted by the customer.", **fields,
        }
        resp = self.client.post(
            self.url(), json=body, headers={**auth_headers(token or self.member.token), **(headers or {})},
        )
        assert resp.status_code == status, resp.text
        return resp.json()

    def act(self, exception: dict, action: str, token: str | None = None, status: int = 200, comment: str = "",
            headers: dict | None = None):
        resp = self.client.post(
            self.url(f"/{exception['id']}/{action}"), json={"comment": comment},
            headers={**auth_headers(token or self.manager.token), **(headers or {})},
        )
        assert resp.status_code == status, resp.text
        return resp.json()

    def get(self, exception: dict, token: str | None = None, headers: dict | None = None) -> dict:
        resp = self.client.get(
            self.url(f"/{exception['id']}"), headers={**auth_headers(token or self.world.token), **(headers or {})},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def patch(self, exception: dict, body: dict, token: str | None = None, status: int = 200):
        resp = self.client.patch(
            self.url(f"/{exception['id']}"), json=body, headers=auth_headers(token or self.member.token),
        )
        assert resp.status_code == status, resp.text
        return resp.json()

    def record_status(self, headers: dict | None = None) -> dict:
        resp = self.client.get(
            PROJECT.format(project=self.project["id"]) + f"/status/{REQ}/{self.requirement}",
            headers={**auth_headers(self.world.token), **(headers or {})},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def part(self, key: str, enabled: bool) -> None:
        resp = self.client.put(
            f"/api/v1/orgs/{self.world.org['id']}/modules/traceability/subcomponents/{key}",
            json={"enabled": enabled}, headers=auth_headers(self.world.token),
        )
        assert resp.status_code == 200, resp.text


def _events(exception_id: str) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == TYPE, AuditEvent.entity_id == exception_id,
        ).order_by(AuditEvent.created_at)))


def _notified(client, token: str) -> list[str]:
    return [n["type"] for n in client.get("/api/v1/notifications", headers=auth_headers(token)).json()]


# --- gating and requesting ---------------------------------------------------------------------------


def test_the_routes_need_the_exceptions_part_and_the_rules_part(client, admin_token):
    s = Scenario(client, admin_token, "Tex Gating Org")
    headers = auth_headers(s.world.token)
    assert client.get(s.url(), headers=headers).status_code == 200
    for part in ("traceability_exceptions", "traceability_rules"):
        s.part(part, False)
        assert client.get(s.url(), headers=headers).status_code == 404
        s.part(part, True)


def test_any_member_requests_an_exception_and_it_is_numbered_audited_and_announced(client, admin_token):
    s = Scenario(client, admin_token, "Tex Request Org")
    made = s.request()
    assert made["unique_code"] == "TEX-001" and made["status"] == "requested"
    assert made["title"] == "Exception to Requirements link"
    assert made["requester"]["id"] == s.member.id and made["covers"] is False
    assert made["no_cover_reason"] == "not_approved" and made["record"]["code"].startswith("SW-")
    assert [e.action for e in _events(made["id"])] == ["created"]
    assert "traceability_exception_requested" in _notified(client, s.manager.token)
    assert s.record_status()["status"] == "incomplete"


def test_a_request_for_the_wrong_record_rule_or_date_is_refused(client, admin_token):
    s = Scenario(client, admin_token, "Tex Invalid Org")
    s.request(status=422, rule_id=str(uuid.uuid4()))
    s.request(status=422, artefact_id=str(uuid.uuid4()))
    s.request(status=422, artefact_type="requirement_action")
    s.request(status=422, reason="   ")
    s.request(status=422, expires_on=_day(-3))
    s.request(status=422, review_date=_day(-3))


# --- who may approve ---------------------------------------------------------------------------------


def test_a_requester_who_is_not_an_organisation_administrator_never_approves(client, admin_token):
    s = Scenario(client, admin_token, "Tex Separation Org")
    own = s.request(token=s.manager.token)
    refused = s.act(own, "approve", status=403, comment="Mine.")
    assert "organisation administrator" in refused["detail"]
    assert "approve" not in s.get(own, token=s.manager.token)["actions"]
    # Named as the requester by someone else.
    named = s.request(requester={"type": "user", "id": s.manager.id})
    s.act(named, "approve", status=403, comment="Mine.")
    # A member of a requester group.
    group = create_project_group(client, s.world.token, s.project["id"], "Askers", users=[s.manager.id])
    grouped = s.request(requester={"type": "project_group", "id": group})
    s.act(grouped, "approve", status=403, comment="Ours.")
    # The requester cannot take themselves out of the field.
    other = s.request(token=s.world.token, requester={"type": "user", "id": s.manager.id})
    s.patch(other, {"requester": {"type": "user", "id": s.member.id}}, token=s.manager.token, status=403)


def _approval_mark(s: Scenario, exception: dict) -> dict:
    resp = s.client.get(
        f"/api/v1/projects/{s.project['id']}/approval-separation/status/{TYPE}/{exception['id']}",
        headers=auth_headers(s.world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_an_organisation_administrator_approves_their_own_with_a_comment_and_a_mark(client, admin_token):
    s = Scenario(client, admin_token, "Tex Admin Self Org")
    raised = s.request(token=s.world.token)
    assert "approve" in s.get(raised, token=s.world.token)["actions"]
    s.act(raised, "approve", token=s.world.token, status=400)
    done = s.act(raised, "approve", token=s.world.token, comment="Sole administrator.")
    assert done["status"] == "approved" and done["covers"] is True
    assert _approval_mark(s, raised)["self_approved"] is True
    assert "self_approved" in [e.action for e in _events(raised["id"])]
    # Named as the requester of a record someone else raised.
    named = s.request(requester={"type": "user", "id": str(s.world.user_id)})
    s.act(named, "approve", token=s.world.token, status=400)
    s.act(named, "approve", token=s.world.token, comment="Mine.")
    assert _approval_mark(s, named)["self_approved"] is True
    # Another person's approval carries no mark.
    other = s.request()
    s.act(other, "approve")
    assert _approval_mark(s, other)["self_approved"] is False


def test_the_organisation_or_project_can_require_a_separate_approver(client, admin_token):
    s = Scenario(client, admin_token, "Tex Required Separation Org")
    headers = auth_headers(s.world.token)
    project_settings = f"/api/v1/projects/{s.project['id']}/approval-separation"
    org_settings = f"/api/v1/orgs/{s.world.org['id']}/approval-separation"
    listed = client.get(project_settings, headers=headers).json()["types"]
    assert next(t for t in listed if t["artefact_type"] == TYPE)["self_approval_org_admins_only"] is True
    assert all(not t["self_approval_org_admins_only"] for t in listed if t["artefact_type"] != TYPE)
    made = s.request(token=s.world.token)
    required = client.put(f"{org_settings}/{TYPE}", json={"required": True}, headers=headers)
    assert required.status_code == 200, required.text
    assert "approve" not in s.get(made, token=s.world.token)["actions"]
    refused = s.act(made, "approve", token=s.world.token, status=403, comment="Mine.")
    assert "separate approver" in refused["detail"]
    assert _approval_mark(s, made)["needs_other_approver"] is True
    assert client.put(f"{org_settings}/{TYPE}", json={"required": False}, headers=headers).status_code == 200
    chosen = client.put(f"{project_settings}/{TYPE}", json={"separate_approver": True}, headers=headers)
    assert chosen.status_code == 200, chosen.text
    s.act(made, "approve", token=s.world.token, status=403, comment="Mine.")
    assert s.act(made, "approve")["status"] == "approved"


def test_only_an_approver_approves_and_a_policy_role_makes_one(client, admin_token):
    s = Scenario(client, admin_token, "Tex Approver Org")
    other = s.person("stakeholder")
    made = s.request()
    s.act(made, "approve", token=other.token, status=403)
    s.act(made, "reject", token=other.token, status=403, comment="No.")
    resp = client.put(
        PROJECT.format(project=s.project["id"]) + f"/approval-policies/{TYPE}",
        json={"roles": [{"kind": "project", "key": "stakeholder"}]}, headers=auth_headers(s.world.token),
    )
    assert resp.status_code == 200, resp.text
    assert s.act(made, "approve", token=other.token)["status"] == "approved"


def test_an_agent_channel_approval_needs_ai_approvals(client, admin_token):
    s = Scenario(client, admin_token, "Tex Channel Org")
    made = s.request()
    s.act(made, "approve", status=403, headers={"X-Reqtrack-Client": "mcp-server"})


def test_a_rule_an_organisation_enforces_needs_an_organisation_level_approver(client, admin_token):
    s = Scenario(client, admin_token, "Tex Enforced Org")
    profile = _create_profile(client, s.world.token, s.world.org["id"], "Corporate", mode="default")
    rule = _add_profile_rule(client, s.world.token, s.world.org["id"], profile["id"], _body("Corporate links", requires=_leaf()))
    # Approved by the project while the profile is optional...
    early = s.request(rule_id=rule["id"])
    assert s.act(early, "approve")["covers"] is True
    enforced = client.patch(
        f"/api/v1/orgs/{s.world.org['id']}/modules/traceability/profiles/{profile['id']}", json={"mode": "enforced"},
        headers=auth_headers(s.world.token),
    )
    assert enforced.status_code == 200, enforced.text
    # ...it stops covering once the organisation enforces the rule.
    after = s.get(early)
    assert after["covers"] is False and after["no_cover_reason"] == "needs_organisation_approval"
    late = s.request(rule_id=rule["id"])
    assert late["needs_organisation_approval"] is True
    s.act(late, "approve", status=403)
    s.act(late, "reject", status=403, comment="No.")
    approved = s.act(late, "approve", token=s.world.token)
    assert approved["status"] == "approved" and approved["covers"] is True


# --- what an exception covers ------------------------------------------------------------------------


def test_an_approved_exception_reads_apart_from_satisfaction_and_lets_the_baseline_through(client, admin_token):
    s = Scenario(client, admin_token, "Tex Cover Org")
    _set_project(client, s.world.token, s.project["id"], _settings(checks=[CHECK], stage=False, manual=True))
    refused = _manual(client, s.world.token, s.project["id"])
    assert refused.status_code == 409, refused.text
    made = s.request()
    assert _manual(client, s.world.token, s.project["id"]).status_code == 409
    s.act(made, "approve")
    status = s.record_status()
    assert status["status"] == "excepted" and status["highest_level"] is None
    assert status["rules"][0]["state"] == "excepted"
    assert status["rules"][0]["excepted_by"]["unique_code"] == made["unique_code"]
    assert status["rules"][0]["leaves"][0]["state"] == "unmet"
    listed = client.get(
        PROJECT.format(project=s.project["id"]) + f"/status/{REQ}", headers=auth_headers(s.world.token),
    ).json()["records"][0]
    assert (listed["status"], listed["unmet"], listed["excepted"]) == ("excepted", 0, 1)
    evaluation = client.get(
        PROJECT.format(project=s.project["id"]) + f"/rules/{s.rule['id']}/evaluation",
        headers=auth_headers(s.world.token),
    ).json()
    assert (evaluation["satisfied"], evaluation["excepted"], evaluation["unsatisfied"]) == (0, 1, 0)
    assert _manual(client, s.world.token, s.project["id"]).status_code == 201
    assert "traceability_exception_decided" in _notified(client, s.member.token)
    # Switching the part off keeps the record and removes the cover.
    s.part("traceability_exceptions", False)
    assert s.record_status()["status"] == "incomplete"


def test_expiry_is_the_last_day_covered_in_the_callers_calendar(client, admin_token):
    s = Scenario(client, admin_token, "Tex Expiry Org")
    made = s.request(expires_on=_today())
    s.act(made, "approve")
    assert s.record_status({"X-Client-Date": _today()})["status"] == "excepted"
    tomorrow = {"X-Client-Date": _day(1)}
    assert s.record_status(tomorrow)["status"] == "incomplete"
    after = s.get(made, headers=tomorrow)
    assert after["expired"] is True and after["covers"] is False and after["no_cover_reason"] == "expired"
    late = s.request(expires_on=_today())
    s.act(late, "approve", status=409, headers=tomorrow)


def test_editing_the_rule_flags_the_exception_and_deleting_it_ends_the_cover(client, admin_token):
    s = Scenario(client, admin_token, "Tex Rule Change Org")
    made = s.request()
    s.act(made, "approve")
    rules_url = PROJECT.format(project=s.project["id"]) + f"/rules/{s.rule['id']}"
    headers = auth_headers(s.world.token)
    assert client.patch(rules_url, json={"name": "Renamed", "level": "warning"}, headers=headers).status_code == 200
    assert s.get(made)["rule_changed"] is False and s.get(made)["rule_name"] == "Renamed"
    assert client.patch(rules_url, json={"requires": _leaf(min=2)}, headers=headers).status_code == 200
    changed = s.get(made)
    assert changed["rule_changed"] is True and changed["covers"] is True
    assert s.record_status()["rules"][0]["excepted_by"]["rule_changed"] is True
    assert client.delete(rules_url, headers=headers).status_code == 204
    removed = s.get(made)
    assert removed["covers"] is False and removed["no_cover_reason"] == "rule_removed"
    assert removed["rule_id"] is None and removed["rule_name"] == "Renamed"


# --- the state path and its locks --------------------------------------------------------------------


def test_the_state_path_needs_comments_and_locks_what_was_approved(client, admin_token):
    s = Scenario(client, admin_token, "Tex Path Org")
    made = s.request()
    s.act(made, "revoke", status=409, comment="Early.")
    s.act(made, "reject", status=422)
    assert s.act(made, "reject", comment="Not justified.")["decision_comment"] == "Not justified."
    again = s.act(made, "resubmit", token=s.member.token)
    assert again["status"] == "requested" and again["decided_by_id"] is None
    assert s.act(made, "withdraw", token=s.member.token)["status"] == "withdrawn"
    s.act(made, "resubmit", token=s.member.token)
    approved = s.act(made, "approve")
    assert approved["decided_by_id"] == s.manager.id
    s.patch(made, {"reason": "Changed"}, status=409)
    s.patch(made, {"expires_on": _day(10)}, status=409)
    assert s.patch(made, {"review_date": _day(10)})["review_date"] == _day(10)
    s.act(made, "archive", token=s.member.token, status=409)
    s.act(made, "revoke", status=422)
    assert s.act(made, "revoke", comment="No longer needed.")["covers"] is False
    assert s.act(made, "archive", token=s.member.token)["is_archived"] is True
    assert client.get(s.url(), headers=auth_headers(s.world.token)).json() == []
    moves = [e.detail or {} for e in _events(made["id"]) if e.action == "status_changed"]
    assert [m["to"] for m in moves] == ["rejected", "requested", "withdrawn", "requested", "approved", "revoked"]


def test_another_member_cannot_change_someone_elses_request(client, admin_token):
    s = Scenario(client, admin_token, "Tex Rights Org")
    made = s.request()
    other = s.person("stakeholder")
    s.patch(made, {"title": "Mine now"}, token=other.token, status=403)
    s.act(made, "withdraw", token=other.token, status=403)
    s.act(made, "archive", token=other.token, status=403)


def test_evidence_and_comments(client, admin_token):
    s = Scenario(client, admin_token, "Tex Evidence Org")
    made = s.request()
    headers = auth_headers(s.member.token)
    uploaded = client.post(
        s.url(f"/{made['id']}/files"), files={"file": ("letter.txt", b"Agreed.", "text/plain")}, headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    assert client.get(f"/api/v1/files/{file_id}", headers=auth_headers(s.manager.token)).status_code == 200
    comment = client.post(s.url(f"/{made['id']}/comments"), json={"body": "See the letter."}, headers=headers)
    assert comment.status_code == 201, comment.text
    s.act(made, "approve")
    assert client.delete(s.url(f"/{made['id']}/files/{file_id}"), headers=headers).status_code == 409
    assert [c["body"] for c in client.get(s.url(f"/{made['id']}/comments"), headers=headers).json()] == ["See the letter."]


# --- reviews -----------------------------------------------------------------------------------------


def test_a_review_sets_the_next_date_and_a_due_review_is_reminded_once(client, admin_token):
    s = Scenario(client, admin_token, "Tex Review Org")
    made = s.request(review_date=_day(1))
    s.act(made, "approve")
    with SessionLocal() as db:
        review_engine.send_review_reminders(db)
        review_engine.send_review_reminders(db)
    assert _notified(client, s.member.token).count("traceability_exception_review_due") == 1
    url = s.url(f"/{made['id']}/reviews")
    headers = auth_headers(s.manager.token)
    assert client.post(url, json={"next_review_date": _today()}, headers=headers).status_code == 422
    done = client.post(url, json={"next_review_date": _day(90), "notes": "Still needed."}, headers=headers)
    assert done.status_code == 200, done.text
    assert done.json()["review_date"] == _day(90)
    assert [e.action for e in _events(made["id"])][-1] == "reviewed"


# --- visibility --------------------------------------------------------------------------------------


def test_an_exception_is_hidden_from_someone_who_may_not_read_the_records_type(client, admin_token):
    s = Scenario(client, admin_token, "Tex Visibility Org")
    made = s.request()
    with SessionLocal() as db:
        from app.modules.traceability.models import TraceabilityException

        row = db.get(TraceabilityException, uuid.UUID(made["id"]))
        assert row is not None
        assert exceptions.readable({encode_permission(REQ, "view")}, [row]) == [row]
        assert exceptions.readable({encode_permission("decision", "view")}, [row]) == []


# --- no links ----------------------------------------------------------------------------------------


def test_an_exception_takes_no_links(client, admin_token):
    s = Scenario(client, admin_token, "Tex No Links Org")
    made = s.request()
    headers = auth_headers(s.world.token)
    base = f"/api/v1/projects/{s.project['id']}/artefacts"
    own = f"{base}/{TYPE}/{made['id']}"
    for suffix in ("/link-types", "/link-graph", "/link-candidates?other_type=requirement"):
        assert client.get(own + suffix, headers=headers).status_code == 404, suffix
    link_type = str(s.world.link_type("Mentions", "Mentioned by"))
    from_requirement = s.world.generic_link(s.project, (REQ, s.requirement), link_type, (TYPE, uuid.UUID(made["id"])))
    assert from_requirement.status_code == 404, from_requirement.text
    candidates = client.get(f"{base}/{REQ}/{s.requirement}/link-candidates?other_type={TYPE}", headers=headers)
    assert candidates.status_code == 404 or candidates.json()["items"] == [], candidates.text
    offered = client.get(f"{base}/{REQ}/{s.requirement}/link-types", headers=headers).json()
    assert all(TYPE not in option["target_types"] for option in offered if "target_types" in option)
    listed = client.get(f"/api/v1/orgs/{s.world.org['id']}/artefact-types", headers=headers)
    assert listed.status_code == 200 and TYPE not in [row["type"] for row in listed.json()], listed.text
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="can be linked"):
            relationships.create_link(
                db, source_type=REQ, source_id=s.requirement, target_type=TYPE, target_id=uuid.UUID(made["id"]),
                link_type_id=None, created_by=s.world.user_id,
            )
    # No traceability rule can expect a link to or from one.
    for body in (_body("To exceptions", requires=_leaf(TYPE)), _body("From exceptions", source=TYPE, requires=_leaf())):
        _add_rule(client, s.world.token, s.project["id"], body, status=422)
    options = client.get(PROJECT.format(project=s.project["id"]) + "/rules/options", headers=headers).json()
    assert TYPE not in [row["artefact_type"] for row in options["types"]]


# --- export, import and bundles -----------------------------------------------------------------------


def _csv_rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import_csv(s: Scenario, rows: list[dict], *, token: str):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    resp = s.client.post(
        f"/api/v1/projects/{s.project['id']}/records/{TYPE}/import", params={"dry_run": "false"},
        files={"file": ("records.csv", out.getvalue().encode(), "text/csv")}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_list_exports_and_an_import_raises_requests_without_approving(client, admin_token):
    s = Scenario(client, admin_token, "Tex Table Org")
    made = s.request()
    s.act(made, "approve")
    export = client.get(f"/api/v1/projects/{s.project['id']}/records/{TYPE}/export", headers=auth_headers(s.world.token))
    [row] = _csv_rows(export)
    assert (row["code"], row["rule"], row["status"], row["covers"]) == ("TEX-001", "Requirements link", "Approved", "Yes")
    new = {"code": "", "record": row["record"], "rule": row["rule"], "reason": "Imported", "status": "Approved"}
    result = _import_csv(s, [new], token=s.member.token)
    assert (result["created"], result["failed"]) == (1, 0), result
    rows = client.get(s.url(), headers=auth_headers(s.world.token)).json()
    assert [(r["unique_code"], r["status"]) for r in rows] == [("TEX-001", "approved"), ("TEX-002", "requested")]
    locked = _import_csv(s, [{"code": "TEX-001", "reason": "Rewritten"}], token=s.world.token)
    assert locked["failed"] == 1
    unknown = _import_csv(s, [{"code": "", "record": "SW-PERF-999", "rule": row["rule"], "reason": "x"}], token=s.world.token)
    assert unknown["failed"] == 1


def test_exceptions_travel_in_the_project_bundle(client, admin_token):
    s = Scenario(client, admin_token, "Tex Bundle Org")
    made = s.request(expires_on=_day(30))
    s.act(made, "approve")
    client.post(s.url(f"/{made['id']}/comments"), json={"body": "Agreed in writing."}, headers=auth_headers(s.member.token))
    headers = auth_headers(s.world.token)
    exported = client.get(f"/api/v1/projects/{s.project['id']}/export", headers=headers)
    assert exported.status_code == 200, exported.text
    data = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("project.json"))
    [entry] = data[bundle.EXCEPTIONS_KEY]
    assert entry["record"]["artefact_type"] == REQ and entry["rule"] == {"name": "Requirements link", "profile": None}

    def import_copy(name: str) -> dict:
        resp = client.post(
            "/api/v1/projects/import", data={"organization_id": s.world.org["id"], "name": name},
            files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=headers,
        )
        assert resp.status_code == 201, resp.text
        url = PROJECT.format(project=resp.json()["project"]["id"]) + "/exceptions"
        [row] = client.get(url, headers=headers).json()
        comments = client.get(f"{url}/{row['id']}/comments", headers=headers).json()
        assert [c["body"] for c in comments] == ["Agreed in writing."]
        return row

    copy = import_copy("Copy")
    assert (copy["status"], copy["covers"], copy["rule_changed"], copy["expires_on"]) == ("approved", True, False, _day(30))
    settings = client.put(
        f"/api/v1/orgs/{s.world.org['id']}/advanced-settings", json={"allow_imported_approval_state": False},
        headers=headers,
    )
    assert settings.status_code == 200, settings.text
    stripped = import_copy("Stripped")
    assert (stripped["status"], stripped["covers"], stripped["decided_by_id"]) == ("requested", False, None)
