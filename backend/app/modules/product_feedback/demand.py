"""
Module: modules.product_feedback.demand

Demand aggregation: who stands behind an enhancement request, and how much weight they carry.

Responsibilities:
- `REQUESTED_BY_SEED` and the link-type names: a request is "Requested by" a Stakeholder, a Persona or an
  Engagement, authored through the generic link endpoints.
- `compute_demand`: for many requests at once, the de-duplicated requesters (each a Stakeholder or Persona),
  the Engagements the request was raised in, the requester count and the weighted demand.

Design decisions:
- Requesters are *parties*, de-duplicated by `(type, id)`: a Stakeholder who asked directly and also took part
  in a linked Engagement counts once. An Engagement expands to its participants and the Personas it covered
  (**Decided by: User**); the expansion is Module 2's, reached through `registry.resolve_demand_parties`, so
  this module never imports the people it counts.
- Weighted demand is the sum of each party's weight (a Stakeholder's Influence level, a Persona's effective
  weight); a party with no weight counts as 1, so demand never silently drops someone (**Decided by: Agent**).
- A request's demand is the union of its own requesters and those of every request with an *active* merge into
  it (`EnhancementRequestMerge`). Nothing is copied, so unmerging removes exactly the duplicate's contribution
  and a requester added to the duplicate later is picked up while the merge lasts.
- A party the project cannot see is dropped by the provider, so it is neither counted nor named.
- Demand is a project-tier concept: an inbox request cannot be a link source (an inbox record has no project),
  so an organisation request has no requesters until triage moves it into a project.
- One set of statements per target type however many requests are asked about, so a list stays flat.

Dependencies: `modules.registry` (`resolve_demand_parties`, `LinkTypeSeed`), `models.relationship`, `models.requirement_link_type`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.product_feedback.models import EnhancementRequestMerge
from app.modules.product_feedback.service import REQUEST_ARTEFACT_TYPE
from app.modules.registry import DemandParty, LinkTypeSeed, resolve_demand_parties

REQUESTED_BY_FORWARD = "Requested by"
REQUESTED_BY_REVERSE = "Requests"

#: Record types a request can be "Requested by". Stakeholders and Personas are people; an Engagement is where
#: they were heard.
REQUESTER_TYPES = ("stakeholder", "persona", "engagement")

REQUESTED_BY_SEED = LinkTypeSeed(
    REQUESTED_BY_FORWARD, REQUESTED_BY_REVERSE,
    allowed_source_types=(REQUEST_ARTEFACT_TYPE,), allowed_target_types=REQUESTER_TYPES,
)

#: A party with no weight counts as this much.
DEFAULT_WEIGHT = 1.0


@dataclass(frozen=True)
class Requester:
    """One de-duplicated party behind a request.

    Attributes:
        artefact_type: `"stakeholder"` or `"persona"`.
        id: The party record's id.
        label: Display name.
        weight: The party's own weight, `None` when unset (it then counts `DEFAULT_WEIGHT`).
        from_merge: True when the party is reached only through a merged duplicate.
        via_engagement: True when the party is reached through a linked Engagement (alone or as well as directly).
        link_id: The request's own "Requested by" link to this party, which removes it as a requester; `None` when the
            party is reached only through an Engagement or a merged duplicate (remove the Engagement, or undo the merge).
    """

    artefact_type: str
    id: uuid.UUID
    label: str
    weight: float | None
    from_merge: bool
    via_engagement: bool
    link_id: uuid.UUID | None = None

    @property
    def effective_weight(self) -> float:
        """What the party adds to weighted demand."""
        return self.weight if self.weight is not None else DEFAULT_WEIGHT


@dataclass(frozen=True)
class Demand:
    """A request's demand.

    Attributes:
        requesters: The distinct parties, heaviest first.
        engagement_ids: The Engagements the request was raised in (own and merged), in id order.
        engagement_links: `{engagement id: the request's own "Requested by" link to it}`, for the ones it is linked to
            directly (an Engagement reached through a merged duplicate has none here).
    """

    requesters: tuple[Requester, ...]
    engagement_ids: tuple[uuid.UUID, ...]
    engagement_links: Mapping[uuid.UUID, uuid.UUID] = field(default_factory=dict)

    @property
    def count(self) -> int:
        """How many distinct parties asked."""
        return len(self.requesters)

    @property
    def weighted(self) -> float:
        """The sum of the parties' effective weights."""
        return round(sum(r.effective_weight for r in self.requesters), 4)


EMPTY_DEMAND = Demand((), ())


def active_merged_duplicates(db: Session, canonical_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    """`{canonical id: ids of the requests actively merged into it}`, in one statement (canonicals with none are absent)."""
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    if not canonical_ids:
        return out
    for canonical_id, duplicate_id in db.execute(
        select(EnhancementRequestMerge.canonical_id, EnhancementRequestMerge.duplicate_id).where(
            EnhancementRequestMerge.canonical_id.in_(list(canonical_ids)), EnhancementRequestMerge.unmerged_at.is_(None),
        ).order_by(EnhancementRequestMerge.merged_at)
    ).all():
        out[canonical_id].append(duplicate_id)
    return out


def _linked_targets(
    db: Session, project: Project, source_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[tuple[str, uuid.UUID, uuid.UUID]]]:
    """`{request id: [(target type, target id, link id)]}` for the requests' "Requested by" links, in one statement."""
    out: dict[uuid.UUID, list[tuple[str, uuid.UUID, uuid.UUID]]] = defaultdict(list)
    if not source_ids:
        return out
    for source_id, target_type, target_id, link_id in db.execute(
        select(ArtefactLink.source_id, ArtefactLink.target_type, ArtefactLink.target_id, ArtefactLink.id)
        .join(RequirementLinkTypeDefinition, RequirementLinkTypeDefinition.id == ArtefactLink.link_type_id)
        .where(
            ArtefactLink.source_type == REQUEST_ARTEFACT_TYPE, ArtefactLink.source_id.in_(list(source_ids)),
            ArtefactLink.target_type.in_(REQUESTER_TYPES), ArtefactLink.source_project_id.is_(None),
            RequirementLinkTypeDefinition.forward_name == REQUESTED_BY_FORWARD,
            RequirementLinkTypeDefinition.organization_id == project.organization_id,
            (RequirementLinkTypeDefinition.project_id.is_(None)) | (RequirementLinkTypeDefinition.project_id == project.id),
        )
    ).all():
        out[source_id].append((target_type, target_id, link_id))
    return out


def compute_demand(db: Session, project: Project, request_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Demand]:
    """The demand of each request of `project`, in a fixed number of statements however many are asked.

    Args:
        db: Active session (read only).
        project: The project the requests belong to (which decides what is visible).
        request_ids: Project-owned requests; an organisation request has no links and so gets `EMPTY_DEMAND`.

    Returns:
        `{request id: Demand}` for every id given.
    """
    ids = list(dict.fromkeys(request_ids))
    if not ids:
        return {}
    merged = active_merged_duplicates(db, ids)
    sources = list(dict.fromkeys([*ids, *(d for ds in merged.values() for d in ds)]))
    targets = _linked_targets(db, project, sources)

    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for linked in targets.values():
        for target_type, target_id, _ in linked:
            wanted[target_type].add(target_id)
    parties: dict[str, dict[uuid.UUID, list[DemandParty]]] = {
        target_type: resolve_demand_parties(db, project.id, target_type, sorted(target_ids))
        for target_type, target_ids in wanted.items()
    }

    def expand(
        source_id: uuid.UUID, own: bool, found: dict[tuple[str, uuid.UUID], list], engagements: dict[uuid.UUID, uuid.UUID | None],
    ) -> None:
        """Adds one source's parties to `found` (`[party, own, via engagement, own link id]`) and its Engagements to
        `engagements` (`{id: own link id or None}`)."""
        for target_type, target_id, link_id in targets.get(source_id, ()):
            expanded = parties.get(target_type, {}).get(target_id)
            if expanded is None:
                continue
            if target_type == "engagement":
                engagements[target_id] = link_id if own else engagements.get(target_id)
            for party in expanded:
                entry = found.setdefault((party.artefact_type, party.id), [party, False, False, None])
                entry[1] = entry[1] or own
                entry[2] = entry[2] or target_type == "engagement"
                if own and target_type != "engagement":
                    entry[3] = link_id

    result: dict[uuid.UUID, Demand] = {}
    for request_id in ids:
        found: dict[tuple[str, uuid.UUID], list] = {}
        engagements: dict[uuid.UUID, uuid.UUID | None] = {}
        expand(request_id, True, found, engagements)
        for duplicate_id in merged.get(request_id, ()):
            expand(duplicate_id, False, found, engagements)
        requesters = sorted(
            (
                Requester(p.artefact_type, p.id, p.label, p.weight, not own, via_engagement, link_id)
                for p, own, via_engagement, link_id in found.values()
            ),
            key=lambda r: (-r.effective_weight, r.label.casefold(), str(r.id)),
        )
        result[request_id] = Demand(
            tuple(requesters), tuple(sorted(engagements, key=str)),
            {e: link for e, link in engagements.items() if link is not None},
        )
    return result
