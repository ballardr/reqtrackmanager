"""
Module: modules.stakeholders.demand

This module's `ModuleDefinition.demand_party_providers`: how another module (Product Feedback) counts who
stands behind a record without importing the people it counts.

Responsibilities:
- `stakeholder_parties` / `persona_parties`: a Stakeholder or Persona visible to the project is its own party,
  weighted by the Stakeholder's Influence level or the Persona's effective weight (`None` when neither is set).
- `engagement_parties`: an Engagement of the project stands for the Stakeholders who took part and the
  Personas it covered, each expanded exactly as above.

Design decisions:
- A record the project cannot see (another project's, an organisation record hidden from the project, a
  disabled sub-component) is absent from the result, so a count never discloses it.
- An archived record still counts: someone who asked and has since left is still a person who asked.
- Anonymous research participants have no record and no weight, so they are not parties.
- Each provider reads in a fixed number of statements however many ids it is given.

Dependencies: `modules.registry` (`DemandParty`), this module's models and service, `models.scoring`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.scoring import ScoringLevel
from app.modules.registry import DemandParty, is_module_subcomponent_enabled
from app.modules.stakeholders.engagements import (
    COVERS_FORWARD,
    ENGAGEMENT_ARTEFACT_TYPE,
    PARTICIPANT_FORWARD,
)
from app.modules.stakeholders.enums import PersonaScope, StakeholderScope
from app.modules.stakeholders.models import Engagement, Persona, PersonaVersion, Stakeholder, StakeholderVersion
from app.modules.stakeholders.service import (
    PERSONA_ARTEFACT_TYPE,
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDERS_MODULE_KEY,
    hidden_persona_ids,
    hidden_stakeholder_ids,
    link_type_id_if_exists,
    resolve_persona_weights,
)
from app.services.current_versions import current_versions


def stakeholder_parties(
    db: Session, project_id: uuid.UUID, ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[DemandParty]]:
    """`demand_party_providers["stakeholder"]`: each visible Stakeholder as its own party, weighted by the
    weight of its Influence level (`None` when it has no level). `{}` while the `stakeholder` sub-component is
    off for the project."""
    project = db.get(Project, project_id)
    if project is None or not ids or not is_module_subcomponent_enabled(
        db, project_id, STAKEHOLDERS_MODULE_KEY, "stakeholder",
    ):
        return {}
    rows = db.scalars(select(Stakeholder).where(
        Stakeholder.id.in_(list(ids)),
        or_(
            (Stakeholder.scope == StakeholderScope.PROJECT) & (Stakeholder.project_id == project_id),
            (Stakeholder.scope == StakeholderScope.ORGANIZATION)
            & (Stakeholder.organization_id == project.organization_id),
        ),
    )).all()
    hidden = hidden_stakeholder_ids(db, project_id)
    visible = [s.id for s in rows if s.id not in hidden]
    versions = current_versions(db, StakeholderVersion, "stakeholder_id", visible)
    level_ids = {v.influence_level_id for v in versions.values() if v.influence_level_id is not None}
    weights = (
        {lvl.id: float(lvl.weight) for lvl in db.scalars(select(ScoringLevel).where(ScoringLevel.id.in_(level_ids)))}
        if level_ids else {}
    )
    return {
        sid: [DemandParty(
            STAKEHOLDER_ARTEFACT_TYPE, sid, versions[sid].name,
            weights.get(versions[sid].influence_level_id) if versions[sid].influence_level_id else None,
        )]
        for sid in visible
    }


def persona_parties(
    db: Session, project_id: uuid.UUID, ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[DemandParty]]:
    """`demand_party_providers["persona"]`: each visible Persona as its own party, weighted by its effective
    weight in the project (`None` when unset). `{}` while the `persona` sub-component is off for the project."""
    project = db.get(Project, project_id)
    if project is None or not ids or not is_module_subcomponent_enabled(
        db, project_id, STAKEHOLDERS_MODULE_KEY, "persona",
    ):
        return {}
    rows = db.scalars(select(Persona).where(
        Persona.id.in_(list(ids)),
        or_(
            (Persona.scope == PersonaScope.PROJECT) & (Persona.project_id == project_id),
            (Persona.scope == PersonaScope.ORGANIZATION) & (Persona.organization_id == project.organization_id),
        ),
    )).all()
    hidden = hidden_persona_ids(db, project_id)
    visible = [p.id for p in rows if p.id not in hidden]
    versions = current_versions(db, PersonaVersion, "persona_id", visible)
    weights = resolve_persona_weights(db, project_id, {pid: versions[pid].weight for pid in visible})
    return {
        pid: [DemandParty(PERSONA_ARTEFACT_TYPE, pid, versions[pid].name, weights[pid][0])] for pid in visible
    }


def engagement_parties(
    db: Session, project_id: uuid.UUID, ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[DemandParty]]:
    """`demand_party_providers["engagement"]`: for each engagement of the project, the visible Stakeholders who
    took part and the visible Personas it covered. An engagement with neither is present with an empty list."""
    project = db.get(Project, project_id)
    if project is None or not ids:
        return {}
    engagement_ids = list(db.scalars(select(Engagement.id).where(
        Engagement.id.in_(list(ids)), Engagement.project_id == project_id,
    )))
    out: dict[uuid.UUID, list[DemandParty]] = {eid: [] for eid in engagement_ids}
    if not engagement_ids:
        return out
    wanted: dict[str, dict[uuid.UUID, set[uuid.UUID]]] = {STAKEHOLDER_ARTEFACT_TYPE: {}, PERSONA_ARTEFACT_TYPE: {}}
    for forward, target_type in ((PARTICIPANT_FORWARD, STAKEHOLDER_ARTEFACT_TYPE), (COVERS_FORWARD, PERSONA_ARTEFACT_TYPE)):
        type_id = link_type_id_if_exists(db, project.organization_id, forward)
        if type_id is None:
            continue
        for source_id, target_id in db.execute(select(ArtefactLink.source_id, ArtefactLink.target_id).where(
            ArtefactLink.source_type == ENGAGEMENT_ARTEFACT_TYPE, ArtefactLink.source_id.in_(engagement_ids),
            ArtefactLink.target_type == target_type, ArtefactLink.link_type_id == type_id,
            ArtefactLink.source_project_id.is_(None),
        )).all():
            wanted[target_type].setdefault(target_id, set()).add(source_id)
    for target_type, provider in ((STAKEHOLDER_ARTEFACT_TYPE, stakeholder_parties), (PERSONA_ARTEFACT_TYPE, persona_parties)):
        for target_id, parties in provider(db, project_id, list(wanted[target_type])).items():
            for engagement_id in wanted[target_type][target_id]:
                out[engagement_id].extend(parties)
    return out
