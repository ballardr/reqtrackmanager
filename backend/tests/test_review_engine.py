"""Tests for the core review engine (`services.review_engine`) and the requirement's review adapter (`services.reviews`),
which run with no governance module: the reminder sweep and its recipients, the day a due date is compared with, the
boundary hours at which a review clears a due date, the scheduling rules a type applies (interval, lead), the adapter
contract, and a second schedule model going through the same engine. How a governance policy changes them is tested in
`modules/traceability/tests/test_governance_review_policy.py`."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.notification import NotificationType
from app.models.requirement import Requirement, RequirementReview, RequirementVersion
from app.modules import registry
from app.modules.seams import DueReview, ReminderMark, ReviewAdapter, ReviewPolicy, ReviewReminder
from app.services import review_engine
from app.services.reviews import get_due_reviews_for_project, send_due_review_reminders
from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login

TODAY = date.today()

_SCOPES: dict[str, tuple[str, str]] = {}


def _principal(kind: str, principal_id) -> dict:
    return {"type": kind, "id": str(principal_id)}


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


def _member(client, token, org_id, project_id, role="stakeholder") -> tuple[str, str]:
    email = f"review_engine_{uuid.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, token, org_id, email)
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _world(client, admin_token, org_id):
    """A project in the default organisation, which has no governance module on."""
    return create_project(client, admin_token, org_id)


def test_without_a_policy_the_sweep_reminds_the_reviewer_within_the_projects_lead(client, admin_token, org_id):
    project = _world(client, admin_token, org_id)
    token = admin_token
    reviewer, reviewer_token = _member(client, token, org_id, project["id"])
    soon = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=5), name="Soon",
                        reviewer=_principal("user", reviewer))
    later = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=30), name="Later",
                         reviewer=_principal("user", reviewer))
    own_lead = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=20), name="Own lead",
                            reviewer=_principal("user", reviewer), review_lead_days=25)
    assert _sweep() == 2
    assert sorted(_reminded(client, reviewer_token)) == sorted([soon["id"], own_lead["id"]])
    assert later["id"] not in _reminded(client, reviewer_token)
    # Each version is reminded once.
    assert _sweep() == 0
    assert sorted(_reminded(client, reviewer_token)) == sorted([soon["id"], own_lead["id"]])


def test_the_project_managers_hear_about_a_requirement_with_no_reviewer(client, admin_token, org_id):
    project = _world(client, admin_token, org_id)
    unassigned = _requirement(client, admin_token, project["id"], review_date=TODAY + timedelta(days=1), name="Unassigned")
    assert _sweep() == 1
    assert _reminded(client, admin_token) == [unassigned["id"]]


def test_the_sweep_compares_with_the_given_day_and_defaults_to_the_utc_day(client, admin_token, org_id):
    project = _world(client, admin_token, org_id)
    token = admin_token
    reviewer, reviewer_token = _member(client, token, org_id, project["id"])
    due = date(TODAY.year, TODAY.month, TODAY.day) + timedelta(days=10)
    requirement = _requirement(client, token, project["id"], review_date=due, reviewer=_principal("user", reviewer))
    # The window opens 7 days before the date: the day before it is closed, the day it opens is open.
    assert _sweep(due - timedelta(days=8)) == 0
    assert _sweep(due - timedelta(days=7)) == 1
    assert _reminded(client, reviewer_token) == [requirement["id"]]


def test_a_requirement_review_does_not_move_the_review_date_and_clears_the_due_list(client, admin_token, org_id):
    project = _world(client, admin_token, org_id)
    token = admin_token
    requirement = _requirement(client, token, project["id"], review_date=TODAY - timedelta(days=1))
    db = SessionLocal()
    try:
        due = review_engine.due_reviews(db, uuid.UUID(project["id"]), TODAY)
        assert [(t, d.artefact_id, d.due_on) for t, d in due] == [
            ("requirement", uuid.UUID(requirement["id"]), TODAY - timedelta(days=1)),
        ]
    finally:
        db.close()
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/reviews", json={"outcome": "met"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    db = SessionLocal()
    try:
        assert review_engine.due_reviews(db, uuid.UUID(project["id"]), TODAY) == []
        assert db.scalar(select(RequirementVersion.review_date).where(
            RequirementVersion.requirement_id == uuid.UUID(requirement["id"]), RequirementVersion.valid_to.is_(None),
        )) == TODAY - timedelta(days=1)
    finally:
        db.close()


def test_the_due_list_compares_with_the_callers_day(client, admin_token, org_id):
    project = _world(client, admin_token, org_id)
    token = admin_token
    utc_today = datetime.now(UTC).date()
    ahead = _requirement(client, token, project["id"], review_date=utc_today + timedelta(days=1), name="Tomorrow")
    behind = _requirement(client, token, project["id"], review_date=utc_today, name="Today")
    url = f"/api/v1/projects/{project['id']}/requirements/reviews/due"

    def due_ids(client_day: date | None) -> set[str]:
        headers = auth_headers(token) | ({"X-Client-Date": client_day.isoformat()} if client_day else {})
        return {r["requirement_id"] for r in client.get(url, headers=headers).json()}

    assert due_ids(None) == {behind["id"]}
    # East of Greenwich, before the UTC day turns (UTC+10 in the morning): the caller's day is already tomorrow.
    assert due_ids(utc_today + timedelta(days=1)) == {behind["id"], ahead["id"]}
    # West of Greenwich (UTC-8 in the evening): the caller's day is still yesterday, so today's date is not yet due.
    assert due_ids(utc_today - timedelta(days=1)) == set()


def test_a_review_clears_a_due_date_once_it_falls_on_or_after_the_start_of_that_day_anywhere(client, admin_token, org_id):
    project = _world(client, admin_token, org_id)
    token = admin_token
    due_on = datetime.now(UTC).date()
    early = _requirement(client, token, project["id"], review_date=due_on, name="Early")
    on_time = _requirement(client, token, project["id"], review_date=due_on, name="On time")
    midnight = datetime(due_on.year, due_on.month, due_on.day, tzinfo=UTC)
    db = SessionLocal()
    try:
        for requirement_id, reviewed_at in (
            # 08:00 on the due date at UTC+10 is 22:00 UTC the day before: on the due date for the person who recorded it.
            (early["id"], midnight - timedelta(hours=2)),
            (on_time["id"], midnight + timedelta(hours=9)),
        ):
            requirement = db.get(Requirement, uuid.UUID(requirement_id))
            assert requirement is not None
            version = db.scalars(select(RequirementVersion).where(
                RequirementVersion.requirement_id == requirement.id, RequirementVersion.valid_to.is_(None),
            )).one()
            db.add(RequirementReview(
                requirement_id=requirement.id, requirement_version_id=version.id, reviewed_by=version.created_by,
                reviewed_at=reviewed_at, outcome="met",
            ))
        too_early = _requirement(client, token, project["id"], review_date=due_on, name="Too early")
        requirement = db.get(Requirement, uuid.UUID(too_early["id"]))
        assert requirement is not None
        version = db.scalars(select(RequirementVersion).where(
            RequirementVersion.requirement_id == requirement.id, RequirementVersion.valid_to.is_(None),
        )).one()
        # 15 hours before the date began in UTC is before it began anywhere.
        db.add(RequirementReview(
            requirement_id=requirement.id, requirement_version_id=version.id, reviewed_by=version.created_by,
            reviewed_at=midnight - timedelta(hours=15), outcome="met",
        ))
        db.commit()
        still_due = {r.id for _, r in get_due_reviews_for_project(db, uuid.UUID(project["id"]))}
        assert still_due == {uuid.UUID(too_early["id"])}
    finally:
        db.close()


def test_the_interval_is_the_longest_gap_between_reviews():
    policy = ReviewPolicy(interval_days=90)
    assert review_engine.next_due_date(policy, date(2026, 11, 25)) == date(2027, 2, 23)
    assert review_engine.next_due_date(ReviewPolicy(), date(2026, 11, 25)) is None
    review_engine.check_next_review_date(policy, date(2026, 11, 25), date(2027, 2, 23))
    review_engine.check_next_review_date(policy, date(2026, 11, 25), date(2026, 12, 1))
    review_engine.check_next_review_date(ReviewPolicy(), date(2026, 11, 25), None)
    review_engine.check_next_review_date(ReviewPolicy(), date(2026, 11, 25), date(2030, 1, 1))
    with pytest.raises(ValueError, match="no later than 2027-02-23"):
        review_engine.check_next_review_date(policy, date(2026, 11, 25), date(2027, 2, 24))
    with pytest.raises(ValueError, match="needs a next review date"):
        review_engine.check_next_review_date(policy, date(2026, 11, 25), None)


def test_the_reminder_lead_is_the_records_then_the_policys_then_the_projects():
    assert review_engine.reminder_lead_days(3, ReviewPolicy(lead_days=10), 7) == 3
    assert review_engine.reminder_lead_days(None, ReviewPolicy(lead_days=10), 7) == 10
    assert review_engine.reminder_lead_days(None, ReviewPolicy(lead_days=0), 7) == 0
    assert review_engine.reminder_lead_days(None, ReviewPolicy(), 5) == 5
    assert review_engine.reminder_lead_days(None, ReviewPolicy(), None) == review_engine.DEFAULT_REMINDER_LEAD_DAYS
    due = date(2026, 12, 1)
    assert review_engine.reminder_open(due, 7, date(2026, 11, 24)) is True
    assert review_engine.reminder_open(due, 7, date(2026, 11, 23)) is False
    assert review_engine.reminder_open(due, 7, date(2026, 12, 9)) is True  # overdue, still to be reminded


def test_a_type_that_stores_its_next_review_date_runs_through_the_same_engine(client, admin_token, org_id, monkeypatch):
    project = _world(client, admin_token, org_id)
    token = admin_token
    reviewer, reviewer_token = _member(client, token, org_id, project["id"])
    record_id = uuid.uuid4()
    marked: list[uuid.UUID] = []
    due_on = TODAY + timedelta(days=3)

    adapter = ReviewAdapter(
        schedule="next_review_date",
        due_reviews=lambda db, project_id, as_of: (
            [DueReview(record_id, due_on)] if project_id == uuid.UUID(project["id"]) and due_on <= as_of else []
        ),
        pending_reminders=lambda db: [
            ReviewReminder(
                artefact_id=record_id, project_id=uuid.UUID(project["id"]), due_on=due_on, title="A stored date",
                code="DEMO-001", owner=None,
            ),
        ] if not marked else [],
        mark_reminded=lambda db, marks, when: marked.extend(m.artefact_id for m in marks),
        notification_type=NotificationType.REQUIREMENT_REVIEW_DUE.value,
    )
    real = registry.get_review_adapters
    monkeypatch.setattr(registry, "get_review_adapters", lambda: {**real(), "demo_record": ("", adapter)})

    db = SessionLocal()
    try:
        assert review_engine.due_reviews(db, uuid.UUID(project["id"]), TODAY) == []
        assert review_engine.due_reviews(db, uuid.UUID(project["id"]), due_on) == [("demo_record", DueReview(record_id, due_on))]
    finally:
        db.close()
    assert _sweep() == 1
    assert marked == [record_id]
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    body = next(r["body"] for r in rows if r["entity_id"] == str(record_id))
    assert body == f"DEMO-001 is due for review by {due_on.isoformat()}."
    assert _sweep() == 0


def test_an_adapter_gives_every_reminder_part_or_none():
    with pytest.raises(ValueError, match="together"):
        ReviewAdapter(schedule="review_record", due_reviews=lambda db, project_id, as_of: [], notification_type="x")


def test_the_requirement_keeps_its_reminder_body_and_title(client, admin_token, org_id):
    project = _world(client, admin_token, org_id)
    token = admin_token
    requirement = _requirement(client, token, project["id"], review_date=TODAY + timedelta(days=2), name="Pump limits")
    send_due_review_reminders_db = SessionLocal()
    try:
        send_due_review_reminders(send_due_review_reminders_db)
    finally:
        send_due_review_reminders_db.close()
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    row = next(r for r in rows if r["entity_id"] == requirement["id"])
    assert row["title"] == "Review due: Pump limits"
    assert row["body"] == f"{project['code']}-{requirement['unique_code']} is due for review by {(TODAY + timedelta(days=2)).isoformat()}."
    assert row["entity_type"] == "requirement"


def test_an_adapter_with_an_overdue_type_sends_one_due_and_one_overdue_reminder_per_date(client, admin_token, org_id, monkeypatch):
    project = _world(client, admin_token, org_id)
    token = admin_token
    record_id = uuid.uuid4()
    due_on = TODAY - timedelta(days=2)
    state: dict[str, date | None] = {"due": None, "overdue": None}
    seen: list[tuple[str, bool]] = []

    def mark(db, marks: list[ReminderMark], when):
        for m in marks:
            state["overdue" if m.overdue else "due"] = m.due_on

    adapter = ReviewAdapter(
        schedule="next_review_date",
        due_reviews=lambda db, project_id, as_of: [],
        pending_reminders=lambda db: [
            ReviewReminder(
                artefact_id=record_id, project_id=uuid.UUID(project["id"]), due_on=due_on, title="Two stage", code="DEMO-002",
                reminded_for=state["due"], overdue_reminded_for=state["overdue"],
            ),
        ],
        mark_reminded=mark,
        notification_type=NotificationType.REQUIREMENT_REVIEW_DUE.value,
        overdue_notification_type="requirement_review_due",
        message=lambda reminder, overdue: (seen.append((reminder.code, overdue)) or ("T", "overdue" if overdue else "due")),
        fallback_recipients=lambda db, reminder: {u for u in review_engine.get_effective_project_managers(db, reminder.project_id)},
    )
    real = registry.get_review_adapters
    monkeypatch.setattr(registry, "get_review_adapters", lambda: {**real(), "two_stage": ("", adapter)})

    assert _sweep(TODAY) == 1  # past its date: the overdue reminder, not a "due" one
    assert seen == [("DEMO-002", True)]
    assert state == {"due": None, "overdue": due_on}
    assert _sweep(TODAY) == 0
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    assert [r["body"] for r in rows if r["entity_id"] == str(record_id)] == ["overdue"]  # the project manager, by the fallback


def test_an_adapters_sub_component_must_be_effective_for_it_to_apply(client, admin_token, org_id, monkeypatch):
    project = _world(client, admin_token, org_id)
    record_id = uuid.uuid4()
    adapter = ReviewAdapter(
        schedule="next_review_date", due_reviews=lambda db, project_id, as_of: [DueReview(record_id, TODAY)],
        sub_component="no_such_part",
    )
    real = registry.get_review_adapters
    monkeypatch.setattr(registry, "get_review_adapters", lambda: {**real(), "gated": ("risk_management", adapter)})
    with SessionLocal() as db:
        assert [t for t, _ in review_engine.due_reviews(db, uuid.UUID(project["id"]), TODAY)] == []


def test_an_adapter_that_sends_no_reminders_cannot_set_reminder_options():
    with pytest.raises(ValueError, match="sends no reminders"):
        ReviewAdapter(schedule="review_record", due_reviews=lambda db, project_id, as_of: [], overdue_notification_type="x")
