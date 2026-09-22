"""Tests for Decision Management's Phase 3 relationships (docs/plans/
module-04-decision-management-plan.md Phase 3): Decision <-> Requirement
(Implements/Affects) and the two plain Decision <-> Decision relationships
(Depends on/Conflicts with) — Supersedes already has its own coverage in
test_decisions_workflow.py.

No HTTP endpoint exists yet for any of this (Phase 4 adds the API), so —
same "data-model-only phase, test through the layer that exists" approach
the earlier phases established — these tests call
`app.modules.decisions.service`'s Phase 3 functions directly against a real
database session, and assert on the resulting `ArtefactLink` rows and the
shared, lazily-created `RequirementLinkTypeDefinition` rows.
"""

from __future__ import annotations

import uuid

import pytest

from app.database import SessionLocal
from app.models.enums import ArtefactType
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.decisions.models import Decision, DecisionTypeDefinition
from app.modules.decisions.service import (
    AFFECTS_LINK_TYPE_FORWARD_NAME,
    AFFECTS_LINK_TYPE_REVERSE_NAME,
    CONFLICTS_WITH_LINK_TYPE_FORWARD_NAME,
    DEPENDS_ON_LINK_TYPE_FORWARD_NAME,
    IMPLEMENTS_LINK_TYPE_FORWARD_NAME,
    IMPLEMENTS_LINK_TYPE_REVERSE_NAME,
    DecisionDecisionLinkKind,
    DecisionRequirementLinkKind,
    create_decision_decision_link,
    create_decision_requirement_link,
)
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project


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


def _create_requirement(client, token, project_id, component_id, category_id, name="Req") -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _setup_project(client, admin_token, org_name: str):
    org, org_admin_token = create_org_admin_in(client, admin_token, org_name)
    project = create_project(client, org_admin_token, org["id"], f"{org_name} Project")
    user_id = _current_user_id(client, org_admin_token)
    decision_type_id = _first_decision_type_id(uuid.UUID(project["id"]))
    return org, org_admin_token, project, user_id, decision_type_id


def test_create_decision_implements_requirement_link(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Implements Co")
    project_id = uuid.UUID(project["id"])
    decision_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id, "Access control")

    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        requirement_row = db.get(Requirement, uuid.UUID(requirement["id"]))
        link = create_decision_requirement_link(
            db, decision=decision, requirement=requirement_row, kind=DecisionRequirementLinkKind.IMPLEMENTS,
            actor_id=user_id,
        )
        db.commit()
        assert link.source_id == decision_id
        assert link.source_type == "decision"
        assert link.target_id == uuid.UUID(requirement["id"])
        assert link.target_type == ArtefactType.REQUIREMENT.value
    finally:
        db.close()

    db = SessionLocal()
    try:
        link_type = db.query(RequirementLinkTypeDefinition).filter(
            RequirementLinkTypeDefinition.organization_id == uuid.UUID(org["id"]),
            RequirementLinkTypeDefinition.forward_name == IMPLEMENTS_LINK_TYPE_FORWARD_NAME,
        ).one()
    finally:
        db.close()
    assert link_type.reverse_name == IMPLEMENTS_LINK_TYPE_REVERSE_NAME


def test_create_decision_affects_requirement_link_creates_link_type_on_first_use(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Affects Co")
    project_id = uuid.UUID(project["id"])
    decision_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id, "Latency budget")

    db = SessionLocal()
    try:
        assert db.query(RequirementLinkTypeDefinition).filter(
            RequirementLinkTypeDefinition.organization_id == uuid.UUID(org["id"]),
            RequirementLinkTypeDefinition.forward_name == AFFECTS_LINK_TYPE_FORWARD_NAME,
        ).first() is None

        decision = db.get(Decision, decision_id)
        requirement_row = db.get(Requirement, uuid.UUID(requirement["id"]))
        create_decision_requirement_link(
            db, decision=decision, requirement=requirement_row, kind=DecisionRequirementLinkKind.AFFECTS,
            actor_id=user_id,
        )
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        link_type = db.query(RequirementLinkTypeDefinition).filter(
            RequirementLinkTypeDefinition.organization_id == uuid.UUID(org["id"]),
            RequirementLinkTypeDefinition.forward_name == AFFECTS_LINK_TYPE_FORWARD_NAME,
        ).one()
    finally:
        db.close()
    assert link_type.reverse_name == AFFECTS_LINK_TYPE_REVERSE_NAME


def test_decision_requirement_link_rejects_cross_project(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Cross Project Co")
    project_id = uuid.UUID(project["id"])
    decision_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")

    other_project = create_project(client, token, org["id"], "Other Project")
    other_component_id, other_category_id = create_component_and_category(client, token, other_project["id"])
    other_requirement = _create_requirement(client, token, other_project["id"], other_component_id, other_category_id)

    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        other_requirement_row = db.get(Requirement, uuid.UUID(other_requirement["id"]))
        with pytest.raises(ValueError, match="same project"):
            create_decision_requirement_link(
                db, decision=decision, requirement=other_requirement_row, kind=DecisionRequirementLinkKind.IMPLEMENTS,
                actor_id=user_id,
            )
        db.rollback()
    finally:
        db.close()


def test_decision_requirement_link_rejects_duplicate(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Duplicate Link Co")
    project_id = uuid.UUID(project["id"])
    decision_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id)

    db = SessionLocal()
    try:
        decision = db.get(Decision, decision_id)
        requirement_row = db.get(Requirement, uuid.UUID(requirement["id"]))
        create_decision_requirement_link(
            db, decision=decision, requirement=requirement_row, kind=DecisionRequirementLinkKind.IMPLEMENTS,
            actor_id=user_id,
        )
        db.commit()

        decision = db.get(Decision, decision_id)
        requirement_row = db.get(Requirement, uuid.UUID(requirement["id"]))
        with pytest.raises(ValueError, match="already has"):
            create_decision_requirement_link(
                db, decision=decision, requirement=requirement_row, kind=DecisionRequirementLinkKind.IMPLEMENTS,
                actor_id=user_id,
            )
        db.rollback()
    finally:
        db.close()


def test_create_decision_decision_depends_on_link(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Depends On Co")
    project_id = uuid.UUID(project["id"])
    a_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    b_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")

    db = SessionLocal()
    try:
        link = create_decision_decision_link(
            db, source_decision=db.get(Decision, a_id), target_decision=db.get(Decision, b_id),
            kind=DecisionDecisionLinkKind.DEPENDS_ON, actor_id=user_id,
        )
        db.commit()
        assert link.source_id == a_id
        assert link.target_id == b_id
        assert link.source_type == "decision"
        assert link.target_type == "decision"
    finally:
        db.close()

    db = SessionLocal()
    try:
        link_type = db.query(RequirementLinkTypeDefinition).filter(
            RequirementLinkTypeDefinition.organization_id == uuid.UUID(org["id"]),
            RequirementLinkTypeDefinition.forward_name == DEPENDS_ON_LINK_TYPE_FORWARD_NAME,
        ).one()
    finally:
        db.close()
    assert link_type is not None


def test_create_decision_decision_conflicts_with_link(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Conflicts Co")
    project_id = uuid.UUID(project["id"])
    a_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    b_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")

    db = SessionLocal()
    try:
        create_decision_decision_link(
            db, source_decision=db.get(Decision, a_id), target_decision=db.get(Decision, b_id),
            kind=DecisionDecisionLinkKind.CONFLICTS_WITH, actor_id=user_id,
        )
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        assert db.query(RequirementLinkTypeDefinition).filter(
            RequirementLinkTypeDefinition.organization_id == uuid.UUID(org["id"]),
            RequirementLinkTypeDefinition.forward_name == CONFLICTS_WITH_LINK_TYPE_FORWARD_NAME,
        ).first() is not None
    finally:
        db.close()


def test_decision_decision_link_rejects_self_link(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Self Link Co")
    project_id = uuid.UUID(project["id"])
    a_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")

    db = SessionLocal()
    try:
        a = db.get(Decision, a_id)
        with pytest.raises(ValueError, match="cannot link to itself"):
            create_decision_decision_link(
                db, source_decision=a, target_decision=a, kind=DecisionDecisionLinkKind.DEPENDS_ON, actor_id=user_id,
            )
        db.rollback()
    finally:
        db.close()


def test_decision_decision_link_rejects_cross_project(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Decision Cross Project Co")
    project_id = uuid.UUID(project["id"])
    a_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")

    other_project = create_project(client, token, org["id"], "Other Project")
    other_decision_type_id = _first_decision_type_id(uuid.UUID(other_project["id"]))
    cross_id = _create_decision(
        project_id=uuid.UUID(other_project["id"]), decision_type_id=other_decision_type_id, user_id=user_id, code="DEC-001",
    )

    db = SessionLocal()
    try:
        a = db.get(Decision, a_id)
        cross = db.get(Decision, cross_id)
        with pytest.raises(ValueError, match="same project"):
            create_decision_decision_link(
                db, source_decision=a, target_decision=cross, kind=DecisionDecisionLinkKind.DEPENDS_ON,
                actor_id=user_id,
            )
        db.rollback()
    finally:
        db.close()


def test_decision_decision_link_rejects_duplicate(client, admin_token):
    org, token, project, user_id, decision_type_id = _setup_project(client, admin_token, "Decision Decision Duplicate Co")
    project_id = uuid.UUID(project["id"])
    a_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-001")
    b_id = _create_decision(project_id=project_id, decision_type_id=decision_type_id, user_id=user_id, code="DEC-002")

    db = SessionLocal()
    try:
        create_decision_decision_link(
            db, source_decision=db.get(Decision, a_id), target_decision=db.get(Decision, b_id),
            kind=DecisionDecisionLinkKind.DEPENDS_ON, actor_id=user_id,
        )
        db.commit()

        with pytest.raises(ValueError, match="already has"):
            create_decision_decision_link(
                db, source_decision=db.get(Decision, a_id), target_decision=db.get(Decision, b_id),
                kind=DecisionDecisionLinkKind.DEPENDS_ON, actor_id=user_id,
            )
        db.rollback()
    finally:
        db.close()
