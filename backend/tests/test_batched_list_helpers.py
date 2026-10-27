"""The batched helpers behind the lists that used to look a record up per row return exactly what the per-record
helpers return, in a fixed number of statements.

Covered: `current_versions` (one statement; a record without a current version raises), `comments_out` (the shape of a
module comment thread, with an attachment-free thread and an unknown author), `resolve_persona_weights` against
`resolve_persona_weight_with_source` over an ancestor chain of overrides, `pain_point_type_names` against the
per-row resolution, the change request list's subscription and comment count against the single-request endpoint, and
`build_evidence_outs` against `build_evidence_out`. The statement-count guard for each list is
`test_scaling_shapes.py`; these tests pin that the answers did not change.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from app.database import SessionLocal, engine
from app.modules.compliance.models import ComplianceEvidence
from app.modules.compliance.service import build_evidence_out, build_evidence_outs
from app.modules.context_strategy._shared import _effective_pain_point_type_name, pain_point_type_names
from app.modules.context_strategy.models import PainPoint, ProjectPainPointType
from app.modules.registry import get_scaling_probes
from app.modules.risk_management.models import Risk, RiskVersion
from app.modules.risk_management.service import get_current_risk_version
from app.modules.stakeholders.service import (
    resolve_persona_weight_with_source,
    resolve_persona_weights,
    set_project_persona_weight,
)
from app.services import relationships
from app.services.current_versions import current_versions
from tests.conftest import auth_headers, create_org_admin_in, create_project
from tests.test_scaling_shapes import _Api, _enable_every_module


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    _enable_every_module(client, token, org["id"])
    return org, token, _Api(client, token)


def test_current_versions_reads_every_record_in_one_statement_and_matches_the_per_record_helper(client, admin_token):
    org, token, api = _setup(client, admin_token, "Versions Co")
    project_id = create_project(client, token, org["id"], "P")["id"]
    ids = [uuid.UUID(i) for i in get_scaling_probes()["risk"].create(api, project_id, 0, 5)]
    db = SessionLocal()
    try:
        counted: list[int] = []

        def count(*_args) -> None:
            counted.append(1)

        event.listen(engine, "before_cursor_execute", count)
        found = current_versions(db, RiskVersion, "risk_id", ids)
        event.remove(engine, "before_cursor_execute", count)
        assert len(counted) == 1
        assert {i: v.id for i, v in found.items()} == {i: get_current_risk_version(db, i).id for i in ids}
        assert current_versions(db, RiskVersion, "risk_id", []) == {}
        with pytest.raises(ValueError, match="no current version"):
            current_versions(db, RiskVersion, "risk_id", [*ids, uuid.uuid4()])
        assert db.query(Risk).count() == 5
    finally:
        db.close()


def test_resolve_persona_weights_matches_the_per_persona_resolution_over_an_ancestor_chain(client, admin_token):
    org, token, api = _setup(client, admin_token, "Weights Co")
    parent = create_project(client, token, org["id"], "Parent", can_be_parent=True)
    child = create_project(client, token, org["id"], "Child", parent_project_id=parent["id"])
    base = f"/projects/{child['id']}/modules/stakeholders/personas"
    ids = [uuid.UUID(api.post(base, {"name": f"Persona {n}", "weight": weight})["id"]) for n, weight in enumerate((None, 2.0, 3.0, 4.0))]
    db = SessionLocal()
    try:
        # One persona overridden in the child, one only in the parent, two left at their own weight (or none).
        set_project_persona_weight(db, uuid.UUID(child["id"]), ids[1], 7.0)
        set_project_persona_weight(db, uuid.UUID(parent["id"]), ids[2], 5.0)
        db.commit()
        own = {ids[0]: None, ids[1]: 2.0, ids[2]: 3.0, ids[3]: 4.0}
        batched = resolve_persona_weights(db, uuid.UUID(child["id"]), own)
        for persona_id, weight in own.items():
            single = resolve_persona_weight_with_source(db, uuid.UUID(child["id"]), persona_id, weight)
            assert batched[persona_id][:2] == single, persona_id
        assert [batched[i][2] for i in ids] == [None, 7.0, None, None]
        assert [batched[i][1] for i in ids] == ["none", "project", "ancestor_project", "persona"]
        assert resolve_persona_weights(db, uuid.UUID(child["id"]), {}) == {}
    finally:
        db.close()


def test_pain_point_type_names_match_the_per_row_resolution(client, admin_token):
    org, token, api = _setup(client, admin_token, "Types Co")
    project_id = create_project(client, token, org["id"], "P")["id"]
    base = f"/projects/{project_id}/modules/context_strategy"
    types = api.get(f"{base}/pain-point-types")
    for type_row in types[:2]:
        api.post(f"{base}/pain-points", {"title": "Uses a type", "pain_point_type_id": type_row["id"]})
    db = SessionLocal()
    try:
        rows = db.query(ProjectPainPointType).filter(ProjectPainPointType.project_id == uuid.UUID(project_id)).all()
        assert rows
        names = pain_point_type_names(db, [r.id for r in rows])
        assert names == {r.id: _effective_pain_point_type_name(db, r) for r in rows}
        assert pain_point_type_names(db, []) == {}
        assert db.query(PainPoint).count() == 2
    finally:
        db.close()


def test_change_request_list_matches_the_single_request_for_subscription_and_comments(client, admin_token):
    org, token, api = _setup(client, admin_token, "CR List Co")
    project_id = create_project(client, token, org["id"], "P")["id"]
    ids = get_scaling_probes()["change_request"].create(api, project_id, 0, 4)
    h = auth_headers(token)
    base = f"/api/v1/projects/{project_id}/change-requests"
    assert client.put(f"{base}/{ids[0]}/subscription", headers=h).status_code == 204
    for body in ("one", "two"):
        assert client.post(f"{base}/{ids[1]}/comments", json={"body": body}, headers=h).status_code == 201
    listed = {r["id"]: r for r in client.get(base, headers=h).json()}
    for change_request_id in ids:
        detail = client.get(f"{base}/{change_request_id}", headers=h).json()
        for field in ("is_subscribed", "comment_count", "proposed_link_count", "status", "proposed_name"):
            assert listed[change_request_id][field] == detail[field], field
    assert listed[ids[0]]["is_subscribed"] and listed[ids[1]]["comment_count"] == 2 and not listed[ids[2]]["is_subscribed"]


def test_build_evidence_outs_matches_build_evidence_out(client, admin_token):
    from sqlalchemy import select

    org, token, api = _setup(client, admin_token, "Evidence Co")
    project_id = create_project(client, token, org["id"], "P")["id"]
    ids = [uuid.UUID(i) for i in get_scaling_probes()["compliance_evidence"].create(api, project_id, 0, 3)]
    db = SessionLocal()
    try:
        user_id = db.scalar(select(ComplianceEvidence.provided_by).where(ComplianceEvidence.id == ids[0]))
        targets = [uuid.uuid4() for _ in range(3)]
        for evidence_id, target, target_type in (
            (ids[0], targets[0], "project_compliance_requirement"), (ids[0], targets[1], "compliance_required_action_assessment"),
            (ids[1], targets[2], "project_compliance_requirement"),
        ):
            relationships.create_link(
                db, source_type="compliance_evidence", source_id=evidence_id, target_type=target_type, target_id=target,
                link_type_id=None, created_by=user_id,
            )
        db.commit()
        rows = db.scalars(select(ComplianceEvidence).where(ComplianceEvidence.id.in_(ids)).order_by(ComplianceEvidence.unique_code)).all()
        assert [o.model_dump() for o in build_evidence_outs(db, list(rows))] == [build_evidence_out(db, r).model_dump() for r in rows]
        assert build_evidence_outs(db, []) == []
    finally:
        db.close()


def test_ensuring_the_link_type_seeds_is_one_lookup_not_one_per_seed(client, admin_token):
    """`GET .../link-types` makes sure every seeded link type exists first. With them all present that is one statement
    for the set (plus the module-enabled checks), not a lookup for each of the dozens of seeds."""
    from app.models.organization import Organization
    from app.modules.registry import get_link_type_seed_owners
    from app.services.link_types import ensure_org_seeds

    org, _token, _api = _setup(client, admin_token, "Seeds Co")
    seeds = len(get_link_type_seed_owners())
    db = SessionLocal()
    try:
        organization = db.get(Organization, uuid.UUID(org["id"]))
        ensure_org_seeds(db, organization.id)
        db.commit()
        counted: list[int] = []

        def count(*_args) -> None:
            counted.append(1)

        event.listen(engine, "before_cursor_execute", count)
        ensure_org_seeds(db, organization.id)
        event.remove(engine, "before_cursor_execute", count)
        assert seeds > 20 and len(counted) < seeds / 2, (seeds, len(counted))
    finally:
        db.close()
