"""Tests for Risk reviews on the core review engine with a governance review policy: the interval that caps the next
review date, the default owner who may review and is reminded for an unowned risk, the reminder lead (policy, then the
project's default), the caller's day for the future-date rule at the extremes of the timezones, and the adapter's due
list. Without a policy the behaviour is pinned by `test_risk_reviews.py`."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import update

from app.database import SessionLocal
from app.models.project import Project
from app.modules.risk_management.alerts import REVIEW_DUE_TYPE
from app.modules.risk_management.tests._helpers import add_member, create_risk, project_base, setup, user_ref
from app.services import review_engine
from tests.conftest import auth_headers, create_org_user

TRACEABILITY = "/api/v1/orgs/{org}/modules/traceability"
POLICY = "/api/v1/projects/{project}/modules/traceability/review-policies/risk"


def _today() -> date:
    return datetime.now(UTC).date()


def _plus(days: int) -> str:
    return (_today() + timedelta(days=days)).isoformat()


def _world(client, admin_token, name):
    """An organisation with Risk Management and Governance on, and a project."""
    org, project, token = setup(client, admin_token, name)
    resp = client.put(
        TRACEABILITY.format(org=org["id"]), json={"enabled": True, "default_project_enabled": True}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return org, project, token


def _set_policy(client, token, project_id, settings) -> None:
    resp = client.put(POLICY.format(project=project_id), json={"settings": settings}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def _review(client, token, project_id, risk_id, next_review, headers=None):
    return client.post(
        f"{project_base(project_id)}/risks/{risk_id}/reviews",
        json={"outcome": "confirmed", "notes": "Still valid.", "next_review_date": next_review},
        headers={**auth_headers(token), **(headers or {})},
    )


def _sweep() -> int:
    with SessionLocal() as db:
        return review_engine.send_review_reminders(db)


def _notifications(client, token, kind) -> list[dict]:
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [r for r in rows if r["type"] == kind]


def test_a_risk_is_listed_in_the_review_policy_while_its_module_is_on(client, admin_token):
    _org, project, token = _world(client, admin_token, "Risk Policy Types Co")
    resp = client.get(POLICY.format(project=project["id"]).rsplit("/risk", 1)[0], headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert {t["artefact_type"] for t in resp.json()["types"]} >= {"requirement", "risk"}


def test_the_interval_caps_the_next_review_date_and_a_review_then_needs_one(client, admin_token):
    _org, project, token = _world(client, admin_token, "Risk Policy Interval Co")
    risk = create_risk(client, token, project["id"])
    _set_policy(client, token, project["id"], {"interval_days": 30})

    too_late = _review(client, token, project["id"], risk["id"], _plus(31))
    assert too_late.status_code == 409 and _plus(30) in too_late.json()["detail"]
    assert _review(client, token, project["id"], risk["id"], None).status_code == 409
    assert _review(client, token, project["id"], risk["id"], _plus(30)).status_code == 201


def test_without_an_interval_any_future_date_or_none_is_accepted(client, admin_token):
    _org, project, token = _world(client, admin_token, "Risk Policy No Interval Co")
    risk = create_risk(client, token, project["id"])
    assert _review(client, token, project["id"], risk["id"], _plus(400)).status_code == 201
    assert _review(client, token, project["id"], risk["id"], None).status_code == 201


def test_the_next_review_must_be_after_the_callers_day_at_both_ends_of_the_timezones(client, admin_token):
    _org, project, token = _world(client, admin_token, "Risk Policy Day Co")
    risk = create_risk(client, token, project["id"])
    # UTC+14: the caller's day is already tomorrow in UTC, so the UTC day plus one is their today.
    ahead = {"X-Client-Date": _plus(1)}
    assert _review(client, token, project["id"], risk["id"], _plus(1), ahead).status_code == 409
    assert _review(client, token, project["id"], risk["id"], _plus(2), ahead).status_code == 201
    # UTC-12: the caller's day is still yesterday in UTC, so the UTC day is their tomorrow.
    behind = {"X-Client-Date": _plus(-1)}
    assert _review(client, token, project["id"], risk["id"], _plus(0), behind).status_code == 201
    assert _review(client, token, project["id"], risk["id"], _plus(-1), behind).status_code == 409


def test_the_default_owner_may_review_an_unowned_risk_and_is_reminded_for_it(client, admin_token):
    org, project, token = _world(client, admin_token, "Risk Policy Owner Co")
    steward_id, steward_token = add_member(client, token, org["id"], project["id"], f"steward-{uuid.uuid4().hex[:8]}@risk-policy.example.com")
    owner_id = create_org_user(client, token, org["id"], f"owner-{uuid.uuid4().hex[:8]}@risk-policy.example.com")
    unowned = create_risk(client, token, project["id"], review_date=_plus(-1))
    owned = create_risk(client, token, project["id"], owner=user_ref(owner_id))

    assert _review(client, steward_token, project["id"], unowned["id"], _plus(10)).status_code == 403
    _set_policy(client, token, project["id"], {"default_owner": {"type": "user", "id": steward_id}})
    assert _review(client, steward_token, project["id"], owned["id"], _plus(10)).status_code == 403  # the owner stays the reviewer
    assert _sweep() == 1
    assert len(_notifications(client, steward_token, "risk_review_overdue")) == 1
    assert _review(client, steward_token, project["id"], unowned["id"], _plus(10)).status_code == 201


def test_the_reminder_lead_is_the_policys_then_the_projects_default(client, admin_token):
    _org, project, token = _world(client, admin_token, "Risk Policy Lead Co")
    risk = create_risk(client, token, project["id"], review_date=_plus(12))
    assert _sweep() == 0  # the project's default lead is 7 days

    _set_policy(client, token, project["id"], {"lead_days": 14})
    assert _sweep() == 1
    assert [n["entity_id"] for n in _notifications(client, token, REVIEW_DUE_TYPE)] == [risk["id"]]

    other = create_risk(client, token, project["id"], review_date=_plus(20))
    _set_policy(client, token, project["id"], {})
    assert _sweep() == 0
    with SessionLocal() as db:
        db.execute(update(Project).where(Project.id == uuid.UUID(project["id"])).values(review_reminder_lead_days_default=21))
        db.commit()
    assert _sweep() == 1
    assert other["id"] in {n["entity_id"] for n in _notifications(client, token, REVIEW_DUE_TYPE)}


def test_the_adapter_lists_open_risks_due_on_or_before_the_day_oldest_first(client, admin_token):
    _org, project, token = _world(client, admin_token, "Risk Policy Due Co")
    later = create_risk(client, token, project["id"], review_date=_plus(-1))
    earlier = create_risk(client, token, project["id"], review_date=_plus(-5))
    create_risk(client, token, project["id"], review_date=_plus(30))
    create_risk(client, token, project["id"])
    with SessionLocal() as db:
        due = review_engine.due_reviews(db, uuid.UUID(project["id"]), _today())
    assert [(t, str(d.artefact_id)) for t, d in due] == [("risk", earlier["id"]), ("risk", later["id"])]


def test_a_second_review_reminder_is_not_sent_for_the_same_date_and_a_new_date_rearms_it(client, admin_token):
    _org, project, token = _world(client, admin_token, "Risk Policy Once Co")
    risk = create_risk(client, token, project["id"], review_date=_plus(3))
    assert _sweep() == 1
    assert _sweep() == 0
    assert _review(client, token, project["id"], risk["id"], _plus(2)).status_code == 201
    assert _sweep() == 1
