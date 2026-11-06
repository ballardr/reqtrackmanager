"""Tests for the project's submission policy: any member may submit by default, a project administrator can restrict
submission to triagers (and change it back), only someone who manages the project may change it, the change is
audited, and the record-table import follows the same gate. Each test builds its own organisation."""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.product_feedback.tests._helpers import (
    add_member,
    create_request,
    grant_project_role,
    project_base,
    setup,
)
from tests.conftest import auth_headers


def _put(client, token, project_id, policy):
    return client.put(
        project_base(project_id) + "/settings", json={"submission_policy": policy}, headers=auth_headers(token),
    )


def test_the_default_policy_lets_any_member_submit(client, admin_token):
    org, project, admin = setup(client, admin_token, "Policy Default Co")
    _, member = add_member(client, admin, org["id"], project["id"], "member.policy@example.com")
    resp = client.get(project_base(project["id"]) + "/settings", headers=auth_headers(member))
    assert resp.status_code == 200 and resp.json() == {"submission_policy": "members", "request_page_sections": None}
    assert create_request(client, member, project["id"])["status"] == "new"


def test_restricting_submission_stops_members_but_not_triagers(client, admin_token):
    org, project, admin = setup(client, admin_token, "Policy Restrict Co")
    _, member = add_member(client, admin, org["id"], project["id"], "member.restrict@example.com")
    triager_id, triager = add_member(client, admin, org["id"], project["id"], "triager.restrict@example.com")
    grant_project_role(client, admin, project["id"], triager_id, "feedback_triager")
    assert _put(client, admin, project["id"], "triagers").json() == {"submission_policy": "triagers", "request_page_sections": None}

    body = {"title": "Please"}
    assert client.post(project_base(project["id"]) + "/requests", json=body, headers=auth_headers(member)).status_code == 403
    assert client.post(project_base(project["id"]) + "/requests", json=body, headers=auth_headers(triager)).status_code == 201
    assert client.get(project_base(project["id"]) + "/settings", headers=auth_headers(member)).json() == {
        "submission_policy": "triagers", "request_page_sections": None,
    }

    assert _put(client, admin, project["id"], "members").status_code == 200
    assert client.post(project_base(project["id"]) + "/requests", json=body, headers=auth_headers(member)).status_code == 201


def test_only_someone_who_manages_the_project_may_change_the_policy(client, admin_token):
    org, project, admin = setup(client, admin_token, "Policy Authority Co")
    triager_id, triager = add_member(client, admin, org["id"], project["id"], "triager.authority@example.com")
    grant_project_role(client, admin, project["id"], triager_id, "feedback_triager")
    _, member = add_member(client, admin, org["id"], project["id"], "member.authority@example.com")
    assert _put(client, member, project["id"], "triagers").status_code == 403
    assert _put(client, triager, project["id"], "triagers").status_code == 403
    assert _put(client, admin, project["id"], "triagers").status_code == 200


def test_an_unknown_policy_is_refused(client, admin_token):
    _, project, admin = setup(client, admin_token, "Policy Unknown Co")
    assert _put(client, admin, project["id"], "everyone").status_code == 422


def test_changing_the_policy_is_audited(client, admin_token):
    _, project, admin = setup(client, admin_token, "Policy Audit Co")
    _put(client, admin, project["id"], "triagers")
    with SessionLocal() as db:
        events = list(db.scalars(select(AuditEvent).where(
            AuditEvent.entity_type == "project_feedback_settings", AuditEvent.project_id == project["id"],
        )))
    assert len(events) == 1 and events[0].action == "updated"
    assert events[0].detail is not None
    assert events[0].detail["submission_policy"] == {"from": "members", "to": "triagers"}


def test_a_project_sets_clears_and_validates_the_default_order_of_a_request_page(client, admin_token):
    org, project, admin = setup(client, admin_token, "Policy Sections Co")
    _, member = add_member(client, admin, org["id"], project["id"], "member.sections@example.com")
    url = project_base(project["id"]) + "/settings"
    h = auth_headers(admin)

    chosen = client.put(url, json={"request_page_sections": ["demand", "details", "scoring"]}, headers=h)
    assert chosen.status_code == 200, chosen.text
    # Only what is sent changes: the submission policy is untouched, and any member can read the order.
    assert chosen.json() == {"submission_policy": "members", "request_page_sections": ["demand", "details", "scoring"]}
    assert client.get(url, headers=auth_headers(member)).json()["request_page_sections"] == ["demand", "details", "scoring"]
    assert _put(client, admin, project["id"], "triagers").json()["request_page_sections"] == ["demand", "details", "scoring"]

    # A member cannot change it, a repeated key or a malformed key is refused, and null returns to the built-in order.
    assert client.put(url, json={"request_page_sections": ["demand"]}, headers=auth_headers(member)).status_code == 403
    assert client.put(url, json={"request_page_sections": ["demand", "demand"]}, headers=h).status_code == 422
    assert client.put(url, json={"request_page_sections": ["Demand!"]}, headers=h).status_code == 422
    assert client.put(url, json={"request_page_sections": [f"s{i}" for i in "abcdefghijklmnopqrstu"]}, headers=h).status_code == 422
    cleared = client.put(url, json={"request_page_sections": None}, headers=h)
    assert cleared.json() == {"submission_policy": "triagers", "request_page_sections": None}

    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "project_feedback_settings")).all()
    assert any((e.detail or {}).get("request_page_sections") == {"count": 3} for e in events)
