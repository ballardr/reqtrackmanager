"""A project created from a template receives Product Feedback settings and starter requests, and the people.

A starter request is new again (no decline reason or requesters); Personas and Stakeholders become drafts and
Personas keep their weight; engagements are copied as logged.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestVersion
from app.modules.product_feedback.tests._helpers import (
    create_engagement,
    create_persona,
    create_request,
    create_stakeholder,
    project_base,
    setup_with_people,
    transition,
)
from app.modules.stakeholders.models import Persona, PersonaVersion, Stakeholder, StakeholderVersion
from tests.conftest import auth_headers


def test_a_template_clone_copies_requests_as_new_and_the_people_as_drafts(client, admin_token):
    org, project, token = setup_with_people(client, admin_token, "Feedback Template Co")
    h = auth_headers(token)
    base = project_base(project["id"])
    request = create_request(client, token, project["id"], title="Export the list")
    assert transition(client, token, base, request["id"], "under_review").status_code == 200
    declined = create_request(client, token, project["id"], title="Dark mode")
    assert transition(client, token, base, declined["id"], "declined", "Out of scope.").status_code == 200
    persona = create_persona(client, token, project["id"], "Ada Operator", weight=2.0)
    assert client.post(
        f"/api/v1/projects/{project['id']}/modules/stakeholders/personas/{persona['id']}/activate", headers=h,
    ).status_code == 200
    stakeholder = create_stakeholder(client, token, project["id"], "Grace Sponsor")
    create_engagement(client, token, project["id"], stakeholder_ids=[stakeholder["id"]])
    assert client.patch(f"/api/v1/projects/{project['id']}", json={"is_template": True}, headers=h).status_code == 200

    resp = client.post(
        "/api/v1/projects",
        json={"organization_id": org["id"], "name": "Feedback From Template", "summary": "", "template_project_id": project["id"]},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    new_id = uuid.UUID(resp.json()["id"])

    db = SessionLocal()
    try:
        versions = {
            v.title: v for v in db.scalars(
                select(EnhancementRequestVersion).join(EnhancementRequest, EnhancementRequest.id == EnhancementRequestVersion.request_id)
                .where(EnhancementRequest.project_id == new_id, EnhancementRequestVersion.valid_to.is_(None))
            )
        }
        assert set(versions) == {"Export the list", "Dark mode"}
        assert all(v.status.value == "new" and not v.decline_reason for v in versions.values())

        personas = list(db.scalars(select(Persona).where(Persona.project_id == new_id)))
        assert len(personas) == 1
        persona_version = db.scalar(select(PersonaVersion).where(PersonaVersion.persona_id == personas[0].id, PersonaVersion.valid_to.is_(None)))
        assert persona_version is not None and persona_version.name == "Ada Operator" and persona_version.status.value == "draft"
        assert persona_version.weight == 2.0
        stakeholders = list(db.scalars(select(Stakeholder).where(Stakeholder.project_id == new_id)))
        assert len(stakeholders) == 1
        stakeholder_version = db.scalar(select(StakeholderVersion).where(
            StakeholderVersion.stakeholder_id == stakeholders[0].id, StakeholderVersion.valid_to.is_(None),
        ))
        assert stakeholder_version is not None and stakeholder_version.name == "Grace Sponsor" and stakeholder_version.status.value == "draft"
    finally:
        db.close()
    engagements = client.get(f"/api/v1/projects/{new_id}/modules/stakeholders/engagements", headers=h).json()
    assert [e["title"] for e in engagements] == ["Workshop"]
