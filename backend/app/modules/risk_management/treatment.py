"""
Module: modules.risk_management.treatment

Risk-to-engineering relationships and the "linked to" versus "effectively
treats" distinction (docs/plans/module-03-risk-management-plan.md Phase 3,
Phase 0 resolution 3).

Responsibilities:
- Say which `ArtefactLink`s are *treatment links* of a risk (the families below).
- List a risk's treatment links with the far end resolved and authorised, each
  with its `RiskTreatmentAssessment` (none means `proposed`).
- Record an assessment, and count the effective ones (the `Mitigated` guard and
  the "treated" flag on `RiskOut`).

Design decisions:
- Relationships are made, listed and removed through the generic link system
  (`routers.artefact_links`, link-type seeds), not a Risk-specific endpoint:
  any artefact can already link to a risk, and a second authoring path would
  need its own copy of the tenancy, nesting and change-request rules. This
  module adds only the one thing the generic link cannot hold, the verdict.
- Two families count as treatment, because only they assert that something
  reduces the risk: "Mitigates" (a requirement, design or other artefact
  mitigates the risk; the risk is the link's target) and "Treated by" (the risk
  is treated by an action; the risk is the link's source). "Verified by",
  "Impacts", "Addressed by" and "Related to" describe the risk without
  asserting treatment, so they carry no verdict. Decided by: Agent.
- A link in the opposite direction to its family ("this risk mitigates that
  requirement") is not a treatment link: the type's meaning would be inverted.
- Visibility reuses `ArtefactResolver`, the link graph's rule, so this listing
  can never show a far end the caller could not open elsewhere. The effective
  count is a server-side fact and ignores the caller.

Dependencies: `services.relationships`, `services.link_graph` (resolver),
`services.link_types`, this module's models.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.registry import ArtefactSummary, get_artefact_type_label
from app.modules.risk_management.enums import TreatmentAssessmentStatus
from app.modules.risk_management.models import RiskTreatmentAssessment
from app.services.link_graph import ArtefactResolver
from app.services.link_nesting import is_link_live
from app.services.link_types import get_org_link_type
from app.services.relationships import get_all_links

RISK_TYPE = "risk"

#: Core default link type: `<artefact> Mitigates <risk>`; the risk is the target.
MITIGATES_FORWARD = "Mitigates"
#: Seeded by this module: `<risk> Treated by <action>`; the risk is the source.
TREATED_BY_FORWARD = "Treated by"
TREATED_BY_REVERSE = "Treats"
#: Seeded by this module: `<risk> Impacts <requirement or design>`.
IMPACTS_FORWARD = "Impacts"
IMPACTS_REVERSE = "Is impacted by"

#: `(forward name, whether the risk is the link's source)` per treatment family.
TREATMENT_FAMILIES: tuple[tuple[str, bool], ...] = ((MITIGATES_FORWARD, False), (TREATED_BY_FORWARD, True))


@dataclass(frozen=True)
class TreatmentLink:
    """One treatment link of a risk, as seen by a caller.

    Attributes:
        link: The `ArtefactLink`.
        phrase: How it reads from the risk's side ("Is mitigated by", "Treated by").
        other_type / other: The far end's artefact type and summary.
        assessment: The verdict row, or `None` while the link is merely proposed.
    """

    link: ArtefactLink
    phrase: str
    other_type: str
    other: ArtefactSummary
    assessment: RiskTreatmentAssessment | None

    @property
    def status(self) -> TreatmentAssessmentStatus:
        """The verdict (`PROPOSED` when no row exists)."""
        return self.assessment.status if self.assessment is not None else TreatmentAssessmentStatus.PROPOSED


def _family_link_types(db: Session, organization_id: uuid.UUID) -> dict[uuid.UUID, tuple[RequirementLinkTypeDefinition, bool]]:
    """`{link_type_id: (link type, risk_is_source)}` for the organisation's
    treatment-family link types that exist."""
    found = {}
    for forward, risk_is_source in TREATMENT_FAMILIES:
        link_type = get_org_link_type(db, organization_id, forward)
        if link_type is not None:
            found[link_type.id] = (link_type, risk_is_source)
    return found


def _treatment_link_rows(
    db: Session, project: Project, risk_id: uuid.UUID
) -> list[tuple[ArtefactLink, RequirementLinkTypeDefinition, bool]]:
    """`(link, link type, risk_is_source)` for each live link of the risk that
    belongs to a treatment family and runs in that family's direction."""
    families = _family_link_types(db, project.organization_id)
    if not families:
        return []
    chain_cache: dict[uuid.UUID, list[uuid.UUID]] = {}
    rows = []
    for link in get_all_links(db, RISK_TYPE, risk_id, include_cross_project=True):
        entry = families.get(link.link_type_id) if link.link_type_id else None
        if entry is None:
            continue
        link_type, risk_is_source = entry
        at_risk_end = (
            (link.source_type, link.source_id) if risk_is_source else (link.target_type, link.target_id)
        ) == (RISK_TYPE, risk_id)
        if at_risk_end and is_link_live(db, link, chain_cache):
            rows.append((link, link_type, risk_is_source))
    return rows


def treatment_link_ids(db: Session, project: Project, risk_id: uuid.UUID) -> set[uuid.UUID]:
    """Ids of the risk's treatment links (visibility not considered)."""
    return {link.id for link, _type, _src in _treatment_link_rows(db, project, risk_id)}


def list_treatment_links(
    db: Session, project: Project, risk_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[list[TreatmentLink], int]:
    """The risk's treatment links the caller may see, plus how many were left out.

    A link whose far end is not a visible record (another tenant's project, a
    disabled module, a type the caller cannot `view`) is counted in the second
    value and never described, so the listing reveals nothing the link graph
    would not.

    Args:
        project: The risk's project (the request project).
        risk_id: The risk.
        user_id: The caller.

    Returns:
        `(links ordered by creation, hidden count)`.
    """
    rows = _treatment_link_rows(db, project, risk_id)
    if not rows:
        return [], 0
    resolver = ArtefactResolver(db, project, user_id, include_related=True)
    wanted: dict[str, set[uuid.UUID]] = {}
    for link, _type, risk_is_source in rows:
        far_type, far_id = (link.target_type, link.target_id) if risk_is_source else (link.source_type, link.source_id)
        wanted.setdefault(far_type, set()).add(far_id)
    resolver.resolve(wanted)
    verdicts = {
        a.link_id: a
        for a in db.scalars(select(RiskTreatmentAssessment).where(RiskTreatmentAssessment.risk_id == risk_id)).all()
    }
    out: list[TreatmentLink] = []
    hidden = 0
    for link, link_type, risk_is_source in sorted(rows, key=lambda r: r[0].created_at):
        far_type, far_id = (link.target_type, link.target_id) if risk_is_source else (link.source_type, link.source_id)
        summary = resolver.visible((far_type, far_id))
        if summary is None:
            hidden += 1
            continue
        phrase = link_type.forward_name if risk_is_source else link_type.reverse_name
        out.append(TreatmentLink(link, phrase, far_type, summary, verdicts.get(link.id)))
    return out, hidden


def far_type_label(treatment: TreatmentLink) -> str:
    """The display name of the far end's artefact type."""
    return get_artefact_type_label(treatment.other_type)


def assess_treatment(
    db: Session, *, risk_id: uuid.UUID, link_id: uuid.UUID, status: TreatmentAssessmentStatus, rationale: str,
    actor_id: uuid.UUID,
) -> RiskTreatmentAssessment:
    """Creates or replaces the verdict on a treatment link. The caller has
    authorised the actor and checked the link is one of the risk's treatment
    links. Does not commit or audit-log.

    Raises:
        ValueError: If an `EFFECTIVE` or `INEFFECTIVE` verdict has no rationale.
    """
    rationale = rationale.strip()
    if status in (TreatmentAssessmentStatus.EFFECTIVE, TreatmentAssessmentStatus.INEFFECTIVE) and not rationale:
        raise ValueError(f"A rationale is required to mark a treatment {status.value}.")
    row = db.scalar(select(RiskTreatmentAssessment).where(RiskTreatmentAssessment.link_id == link_id))
    if row is None:
        row = RiskTreatmentAssessment(link_id=link_id, risk_id=risk_id)
        db.add(row)
    row.status = status
    row.rationale = rationale
    row.reassessment_reason = ""
    row.assessed_by = actor_id
    row.assessed_at = datetime.now(UTC)
    db.flush()
    return row


def effective_treatment_counts(db: Session, risk_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """`{risk_id: number of effective treatment links}` (risks with none are absent)."""
    if not risk_ids:
        return {}
    rows = db.execute(
        select(RiskTreatmentAssessment.risk_id, func.count())
        .where(
            RiskTreatmentAssessment.risk_id.in_(risk_ids),
            RiskTreatmentAssessment.status == TreatmentAssessmentStatus.EFFECTIVE,
        )
        .group_by(RiskTreatmentAssessment.risk_id)
    ).all()
    return {risk_id: count for risk_id, count in rows}
