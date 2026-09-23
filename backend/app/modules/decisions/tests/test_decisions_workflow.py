"""Tests for Decision Management's Phase 2 workflow (docs/plans/module-04-
decision-management-plan.md Phase 2): status transitions, rejection, and
the supersession relationship.

No HTTP endpoint exists yet for any of this (Phase 4 adds the API), so —
same "data-model-only phase, test through the layer that exists" approach
`test_decisions_seeding.py` established for Phase 1 — these tests call
`app.modules.decisions.service`'s Phase 2 functions directly against a real
database session, and assert on `Decision.status` and `AuditEvent` rows
rather than an HTTP response body.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.modules.decisions.service import (
    SUPERSEDES_LINK_TYPE_FORWARD_NAME,
    SUPERSEDES_LINK_TYPE_REVERSE_NAME,
    approve_decision,
    create_supersession,
    propose_decision,
    reject_decision,
    submit_decision_for_review,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _current_user_id(client, token: str) -> uuid.UUID:
    resp = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return uuid.UUID(resp.json()["id"])


def _first_decision_type_id(project_id: uuid.UUID) -> uuid.UUID:
    db = SessionLocal()
    try:
        return db.query(DecisionTypeDefinition.id).filter(
            DecisionTypeDefinition.project_id == project_id
        ).first()[0]
    finally:
        db.close()


def _create_decision(*, project_id: uuid.UUID, decision_type_id: uuid.UUID, user_id: uuid.UUID, code: str) -> uuid.UUID:
    """Inserts a `Decision` row directly (no create endpoint exists until
    Phase 4) and returns its id."""
    db = SessionLocal()
    try:
        decision = Decision(
            project_id=project_id, unique_code=code, title=f"Decision {code}",
            decision_statement="A statement.", decision_type_id=decision_type_id,
            owner_id=user_id, creator_id=user_id,
        )
        db.add(decision)
        db.commit()
        return decision.id
    finally:
        db.close()


def _status(decision_id: uuid.UUID) -> DecisionStatus:
    db = SessionLocal()
    try:
        return db.get(Decision, decision_id).status
    finally:
        db.close()


def _audit_actions(entity_id: uuid.UUID) -> list[str]:
    db = SessionLocal()
    try:
        rows = db.query(AuditEvent.action).filter(
            AuditEvent.entity_type == "decision", AuditEvent.entity_id == str(entity_id)
        ).order_by(AuditEvent.created_at).all()
    finally:
        db.close()
    return [action for (action,) in rows]


def _setup_project(client, admin_token, org_name: str):
    org, org_admin_token = create_org_admin_in(client, admin_token, org_name)
    project = create_project(client, org_admin_token, org["id"], f"{org_name} Project")
    user_id = _current_user_id(client, org_admin_token)
    decision_type_id = _first_decision_type_id(uuid.UUID(project["id"]))
    return project, user_id, decision_type_id


def test_full_legal_transition_sequence_is_recorded_in_audit_log(client, admin_token):
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Workflow Happy Path Co")
    decision_id = _create_decision(
        project_id=uuid.UUID(project["id"]), decision_type_id=decision_type_id, user_id=user_id, code="DEC-001"
    )

    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        propose_decision(db, decision, user_id)
        db.commit()
        decision = db.get(Decision, decision_id)
        submit_decision_for_review(db, decision, user_id)
        db.commit()
        decision = db.get(Decision, decision_id)
        approve_decision(db, decision, user_id, comment="Looks good.")
        db.commit()
    finally:
        db.close()

    assert _status(decision_id) == DecisionStatus.APPROVED
    assert _audit_actions(decision_id) == ["proposed", "submitted_for_review", "approved"]


def test_rejecting_from_under_review_records_the_comment(client, admin_token):
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Workflow Rejection Co")
    decision_id = _create_decision(
        project_id=uuid.UUID(project["id"]), decision_type_id=decision_type_id, user_id=user_id, code="DEC-001"
    )

    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        propose_decision(db, decision, user_id)
        submit_decision_for_review(db, decision, user_id)
        reject_decision(db, decision, user_id, comment="Not aligned with strategy.")
        db.commit()
    finally:
        db.close()

    assert _status(decision_id) == DecisionStatus.REJECTED
    db = SessionLocal()
    try:
        event = db.query(AuditEvent).filter(
            AuditEvent.entity_type == "decision", AuditEvent.entity_id == str(decision_id), AuditEvent.action == "rejected"
        ).one()
    finally:
        db.close()
    assert event.detail == {"comment": "Not aligned with strategy."}


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        (DecisionStatus.DRAFT, DecisionStatus.APPROVED),
        (DecisionStatus.DRAFT, DecisionStatus.UNDER_REVIEW),
        (DecisionStatus.APPROVED, DecisionStatus.REJECTED),
        (DecisionStatus.REJECTED, DecisionStatus.PROPOSED),
    ],
)
def test_illegal_transitions_are_rejected(client, admin_token, from_status, to_status):
    project, user_id, decision_type_id = _setup_project(client, admin_token, f"Decision Illegal {from_status}-{to_status} Co")
    decision_id = _create_decision(
        project_id=uuid.UUID(project["id"]), decision_type_id=decision_type_id, user_id=user_id, code="DEC-001"
    )

    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        decision.status = from_status
        db.commit()

        decision = db.get(Decision, decision_id)
        transition_fn = {
            DecisionStatus.PROPOSED: propose_decision,
            DecisionStatus.UNDER_REVIEW: submit_decision_for_review,
            DecisionStatus.APPROVED: approve_decision,
            DecisionStatus.REJECTED: reject_decision,
        }[to_status]
        with pytest.raises(ValueError, match="Cannot move a Decision"):
            transition_fn(db, decision, user_id)
        db.rollback()
    finally:
        db.close()

    assert _status(decision_id) == from_status


def test_supersession_link_created_but_new_decision_not_yet_approved_does_not_flip_old_status(client, admin_token):
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Supersession Deferred Co")
    project_id = uuid.UUID(project["id"])
    old_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    new_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")

    db = SessionLocal()
    try:
        old_decision = db.get(Decision, old_id)
        propose_decision(db, old_decision, user_id)
        submit_decision_for_review(db, old_decision, user_id)
        approve_decision(db, old_decision, user_id)
        db.commit()

        old_decision = db.get(Decision, old_id)
        new_decision = db.get(Decision, new_id)
        link = create_supersession(db, new_decision=new_decision, old_decision=old_decision, actor_id=user_id)
        db.commit()
        assert link.source_id == new_id
        assert link.target_id == old_id
    finally:
        db.close()

    # New decision is still DRAFT, so the old one must not flip yet.
    assert _status(old_id) == DecisionStatus.APPROVED

    db = SessionLocal()
    try:
        new_decision = db.get(Decision, new_id)
        propose_decision(db, new_decision, user_id)
        submit_decision_for_review(db, new_decision, user_id)
        approve_decision(db, new_decision, user_id)
        db.commit()
    finally:
        db.close()

    # Now that the new decision is approved, the old one flips.
    assert _status(old_id) == DecisionStatus.SUPERSEDED
    assert "superseded" in _audit_actions(old_id)


def test_supersession_created_after_new_decision_already_approved_flips_immediately(client, admin_token):
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Supersession Immediate Co")
    project_id = uuid.UUID(project["id"])
    old_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    new_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")

    db = SessionLocal()
    try:
        for decision_id in (old_id, new_id):
            decision = db.get(Decision, decision_id)
            propose_decision(db, decision, user_id)
            submit_decision_for_review(db, decision, user_id)
            approve_decision(db, decision, user_id)
        db.commit()

        old_decision = db.get(Decision, old_id)
        new_decision = db.get(Decision, new_id)
        create_supersession(db, new_decision=new_decision, old_decision=old_decision, actor_id=user_id)
        db.commit()
    finally:
        db.close()

    assert _status(old_id) == DecisionStatus.SUPERSEDED


def test_supersedes_link_type_is_created_once_per_org_and_reused(client, admin_token):
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Supersession Link Type Co")
    project_id = uuid.UUID(project["id"])
    org_id = uuid.UUID(project["organization_id"])
    a_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    b_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")
    c_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-003")

    db = SessionLocal()
    try:
        create_supersession(db, new_decision=db.get(Decision, b_id), old_decision=db.get(Decision, a_id), actor_id=user_id)
        create_supersession(db, new_decision=db.get(Decision, c_id), old_decision=db.get(Decision, b_id), actor_id=user_id)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        link_types = db.query(RequirementLinkTypeDefinition).filter(
            RequirementLinkTypeDefinition.organization_id == org_id,
            RequirementLinkTypeDefinition.forward_name == SUPERSEDES_LINK_TYPE_FORWARD_NAME,
        ).all()
    finally:
        db.close()
    assert len(link_types) == 1
    assert link_types[0].reverse_name == SUPERSEDES_LINK_TYPE_REVERSE_NAME


def test_supersession_validation_errors(client, admin_token):
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Supersession Validation Co")
    project_id = uuid.UUID(project["id"])
    a_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    b_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")

    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Decision Supersession Other Org Co")
    other_project = create_project(client, other_org_admin_token, other_org["id"], "Other Project")
    other_user_id = _current_user_id(client, other_org_admin_token)
    other_decision_type_id = _first_decision_type_id(uuid.UUID(other_project["id"]))
    cross_project_id = _create_decision(
        project_id=uuid.UUID(other_project["id"]), decision_type_id=other_decision_type_id,
        user_id=other_user_id, code="DEC-001",
    )

    db = SessionLocal()
    try:
        a = db.get(Decision, a_id)
        b = db.get(Decision, b_id)
        cross = db.get(Decision, cross_project_id)

        with pytest.raises(ValueError, match="cannot supersede itself"):
            create_supersession(db, new_decision=a, old_decision=a, actor_id=user_id)

        with pytest.raises(ValueError, match="same project"):
            create_supersession(db, new_decision=b, old_decision=cross, actor_id=user_id)

        create_supersession(db, new_decision=b, old_decision=a, actor_id=user_id)
        db.commit()

        b = db.get(Decision, b_id)
        a = db.get(Decision, a_id)
        with pytest.raises(ValueError, match="already supersedes"):
            create_supersession(db, new_decision=b, old_decision=a, actor_id=user_id)
        db.rollback()
    finally:
        db.close()


def test_cannot_supersede_an_already_superseded_decision(client, admin_token):
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Double Supersession Co")
    project_id = uuid.UUID(project["id"])
    a_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    b_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")
    c_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-003")

    db = SessionLocal()
    try:
        for decision_id in (a_id, b_id):
            decision = db.get(Decision, decision_id)
            propose_decision(db, decision, user_id)
            submit_decision_for_review(db, decision, user_id)
            approve_decision(db, decision, user_id)
        db.commit()

        # b supersedes a immediately (b is already APPROVED).
        create_supersession(db, new_decision=db.get(Decision, b_id), old_decision=db.get(Decision, a_id), actor_id=user_id)
        db.commit()
    finally:
        db.close()

    assert _status(a_id) == DecisionStatus.SUPERSEDED

    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="already been superseded"):
            create_supersession(db, new_decision=db.get(Decision, c_id), old_decision=db.get(Decision, a_id), actor_id=user_id)
        db.rollback()
    finally:
        db.close()


# --- 2026-09-23 hardening pass: supersession status guard + approve/reject race ----


def test_create_supersession_rejects_a_new_decision_that_can_never_be_approved(client, admin_token):
    """A `REJECTED`/`SUPERSEDED` Decision can never reach `APPROVED`
    (`_ALLOWED_TRANSITIONS` has no outgoing edges for either), so recording
    it as superseding another Decision would create a link that can never
    resolve into the status transition its own name implies — found and
    fixed in a 2026-09-23 hardening pass. DRAFT/PROPOSED/UNDER_REVIEW
    remain allowed (existing `test_supersession_validation_errors`
    coverage), since those can still reach APPROVED later."""
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Supersession Guard Co")
    project_id = uuid.UUID(project["id"])
    old_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    rejected_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")
    superseded_new_id = _create_decision(
        project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-003"
    )
    predecessor_id = _create_decision(
        project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-004"
    )

    db = SessionLocal()
    try:
        rejected = db.get(Decision, rejected_id)
        propose_decision(db, rejected, user_id)
        reject_decision(db, rejected, user_id, comment="No longer needed.")

        for decision_id in (superseded_new_id, predecessor_id):
            decision = db.get(Decision, decision_id)
            propose_decision(db, decision, user_id)
            submit_decision_for_review(db, decision, user_id)
            approve_decision(db, decision, user_id)
        db.commit()

        # Give superseded_new_id a predecessor of its own so it becomes SUPERSEDED.
        create_supersession(
            db, new_decision=db.get(Decision, predecessor_id), old_decision=db.get(Decision, superseded_new_id),
            actor_id=user_id,
        )
        db.commit()
    finally:
        db.close()

    assert _status(rejected_id) == DecisionStatus.REJECTED
    assert _status(superseded_new_id) == DecisionStatus.SUPERSEDED

    db = SessionLocal()
    try:
        old_decision = db.get(Decision, old_id)
        with pytest.raises(ValueError, match="can never be approved"):
            create_supersession(db, new_decision=db.get(Decision, rejected_id), old_decision=old_decision, actor_id=user_id)
        db.rollback()

        old_decision = db.get(Decision, old_id)
        with pytest.raises(ValueError, match="can never be approved"):
            create_supersession(
                db, new_decision=db.get(Decision, superseded_new_id), old_decision=old_decision, actor_id=user_id,
            )
        db.rollback()
    finally:
        db.close()


def test_concurrent_approve_and_reject_on_the_same_decision_are_serialized(client, admin_token):
    """Two real, overlapping transactions — one approving, one rejecting
    the same `UNDER_REVIEW` Decision — must not both succeed: without a
    row lock, both could read status == UNDER_REVIEW before either
    commits and both pass `_ALLOWED_TRANSITIONS`, leaving the audit trail
    showing contradictory events. With the row-locked fetch
    (`_get_decision_in_project_for_update`, mirroring `change_requests.
    workflow.decide_change_request`'s identical fix), the second call's
    status check must run against the first one's already-committed
    result and fail cleanly instead. Locks directly at the DB layer (real
    `SELECT ... FOR UPDATE`, real threads, real separate sessions) rather
    than through the HTTP layer, mirroring `test_project_sequence_
    counters.py::test_concurrent_generation_never_produces_duplicate_
    codes`'s own established pattern for proving a lock actually
    serializes concurrent callers."""
    project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Approve Reject Race Co")
    project_id = uuid.UUID(project["id"])
    decision_id = _create_decision(
        project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001"
    )
    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        propose_decision(db, decision, user_id)
        submit_decision_for_review(db, decision, user_id)
        db.commit()
    finally:
        db.close()
    assert _status(decision_id) == DecisionStatus.UNDER_REVIEW

    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}
    outcomes_lock = threading.Lock()
    errors: list[BaseException] = []

    def worker(action: str):
        db = SessionLocal()
        try:
            barrier.wait(timeout=5)
            locked = db.scalar(select(Decision).where(Decision.id == decision_id).with_for_update())
            try:
                if action == "approve":
                    approve_decision(db, locked, user_id, comment="Approving.")
                else:
                    reject_decision(db, locked, user_id, comment="Rejecting.")
                db.commit()
                with outcomes_lock:
                    outcomes[action] = "succeeded"
            except ValueError:
                db.rollback()
                with outcomes_lock:
                    outcomes[action] = "conflict"
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors` for the assertion below
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(action,)) for action in ("approve", "reject")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    # Exactly one side must have won; the loser must see a clean conflict,
    # never a silent double-success.
    assert sorted(outcomes.values()) == ["conflict", "succeeded"]
    final_status = _status(decision_id)
    assert final_status in (DecisionStatus.APPROVED, DecisionStatus.REJECTED)
    winner = "approve" if final_status == DecisionStatus.APPROVED else "reject"
    assert outcomes[winner] == "succeeded"
