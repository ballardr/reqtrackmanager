"""A project created from a template receives Context & Strategy configuration and starter records as drafts.

Pain Point types (local, overridden, hidden defaults) travel unchanged; Strategies, Future States and Guiding
Principles become drafts, Pain Points are submitted with no scores and Open Questions are open with no due date.
Links between copied records are kept; a link to a requirement is not (a clone renumbers requirements).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.relationship import ArtefactLink
from app.modules.context_strategy.models import (
    FutureStateVersion,
    GuidingPrincipleVersion,
    OpenQuestion,
    PainPoint,
    PainPointFile,
    PainPointScore,
    ProjectPainPointType,
    Strategy,
    StrategyVersion,
)
from app.modules.context_strategy.tests.test_context_strategy_export_import import CS, _build, _cs, _setup
from tests.conftest import auth_headers


def test_a_template_clone_copies_context_strategy_configuration_and_fresh_drafts(client, admin_token):
    org, project, token = _setup(client, admin_token, "CS Template Co")
    h = auth_headers(token)
    _build(client, token, org, project)
    assert client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=h).status_code == 200

    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "CS From Template", "summary": "", "template_project_id": project["id"]},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    new_id = uuid.UUID(resp.json()["id"])
    base = _cs(new_id)
    assert CS in base

    db = SessionLocal()
    try:
        types = {r.name_override: r for r in db.scalars(select(ProjectPainPointType).where(ProjectPainPointType.project_id == new_id))}
        assert types["Project-only"].definition_override == "Only here." and types["Project-only"].org_type_id is None
        assert types["Customer"].definition_override == "People who pay." and types["Customer"].org_type_id is not None

        pain_points = {p.title: p for p in db.scalars(select(PainPoint).where(PainPoint.project_id == new_id))}
        assert set(pain_points) == {"Slow reports", "Confusing menu"}
        assert all(p.status.value == "submitted" and not p.is_archived for p in pain_points.values())
        assert not db.scalars(select(PainPointScore).where(PainPointScore.pain_point_id.in_([p.id for p in pain_points.values()]))).all()
        assert db.scalar(select(PainPointFile).where(PainPointFile.pain_point_id == pain_points["Slow reports"].id)) is not None

        strategy = db.scalar(select(Strategy).where(Strategy.project_id == new_id))
        assert strategy is not None
        version = db.scalar(select(StrategyVersion).where(StrategyVersion.strategy_id == strategy.id, StrategyVersion.valid_to.is_(None)))
        assert version is not None and version.status.value == "draft" and version.title == "Grow"  # it was proposed in the template
        future = db.scalar(select(FutureStateVersion).join(FutureStateVersion.future_state).where(FutureStateVersion.valid_to.is_(None)))
        assert future is not None
        principles = list(db.scalars(select(GuidingPrincipleVersion).where(GuidingPrincipleVersion.valid_to.is_(None))))
        assert all(p.status.value == "draft" for p in principles)

        question = db.scalar(select(OpenQuestion).where(OpenQuestion.project_id == new_id))
        assert question is not None and question.status.value == "open" and question.due_date is None

        # The pain point -> strategy link between two copied records is kept.
        links = list(db.scalars(select(ArtefactLink).where(ArtefactLink.source_id == pain_points["Slow reports"].id)))
        assert [link.target_id for link in links] == [strategy.id]
    finally:
        db.close()
    assert client.get(base + "/pain-point-types", headers=h).status_code == 200
