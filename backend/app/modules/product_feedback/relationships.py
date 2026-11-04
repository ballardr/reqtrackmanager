"""
Module: modules.product_feedback.relationships

The links that tie a request to the problem it answers and the work that delivers it.

Responsibilities:
- `ADDRESSES_SEED` (request -> Pain Point) and `REALISED_BY_SEED` (request -> Requirement): link types authored with
  the generic link endpoints, like "Requested by" (`demand.py`); there is no endpoint of their own.
- `compute_links`: for many requests at once, the Pain Points they address and the Requirements that realise them.

Design decisions:
- A request is a solution and a Pain Point is the problem it answers; a request with no Pain Point is flagged
  (never blocked), so ranking by demand cannot quietly reward the loudest asker (**Decided by: User**).
- An Engagement that evidenced the request is the existing "Requested by" link to an Engagement (`demand.py`); a
  second "Evidence" link type would say the same thing twice (**Decided by: Agent**).
- A merged duplicate's links count for the canonical request, as its requesters do: the duplicate is the same ask,
  so its problem and its delivering work are the canonical request's too. Nothing is copied, so unmerging removes
  them again.
- "Addresses" shares its name with Decision Management's link type (decision -> pain point) and merges with it, the
  same phrases and direction. Both link types let the request sit in a parent project and the problem or work in
  a child where the type's direction allows it (**Decided by: Agent**); the readers here therefore accept a link
  recorded for this request's project as well as a plain same-project one.
- Pain Point and Requirement are named by their artefact-type string, never imported: a request is linked to
  whichever of those modules is enabled, and a link to a disabled module's record simply is not offered.
- One statement per link type however many requests are asked about, so a list stays flat.

Dependencies: `modules.registry` (`LinkTypeSeed`), `models.relationship`, `models.requirement_link_type`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ArtefactType, LinkFlow, LinkNestingScope
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.product_feedback.demand import active_merged_duplicates
from app.modules.product_feedback.service import REQUEST_ARTEFACT_TYPE
from app.modules.registry import LinkTypeSeed

ADDRESSES_FORWARD = "Addresses"
ADDRESSES_REVERSE = "Is addressed by"
REALISED_BY_FORWARD = "Realised by"
REALISED_BY_REVERSE = "Realises"

PAIN_POINT_TYPE = "pain_point"
REQUIREMENT_TYPE = ArtefactType.REQUIREMENT.value

ADDRESSES_SEED = LinkTypeSeed(
    ADDRESSES_FORWARD, ADDRESSES_REVERSE, LinkFlow.FORWARD_IS_UPSTREAM,
    nesting_scope=LinkNestingScope.UPSTREAM_IN_ANCESTOR,
    allowed_source_types=(REQUEST_ARTEFACT_TYPE,), allowed_target_types=(PAIN_POINT_TYPE,),
)
REALISED_BY_SEED = LinkTypeSeed(
    REALISED_BY_FORWARD, REALISED_BY_REVERSE, LinkFlow.FORWARD_IS_DOWNSTREAM,
    nesting_scope=LinkNestingScope.UPSTREAM_IN_ANCESTOR,
    allowed_source_types=(REQUEST_ARTEFACT_TYPE,), allowed_target_types=(REQUIREMENT_TYPE,),
)


@dataclass(frozen=True)
class RequestLinks:
    """The records a request is linked to, its own and those of requests merged into it.

    Attributes:
        pain_point_ids: The Pain Points it addresses.
        requirement_ids: The Requirements that realise it.
    """

    pain_point_ids: tuple[uuid.UUID, ...] = ()
    requirement_ids: tuple[uuid.UUID, ...] = ()


NO_LINKS = RequestLinks()


def _targets(
    db: Session, project: Project, source_ids: Sequence[uuid.UUID], forward_name: str, target_type: str,
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """`{request id: target ids}` for the requests' links of one link type, in one statement. A link between this
    project and a related one (`source_project_id` set) counts when it was recorded for this project."""
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    if not source_ids:
        return out
    for source_id, target_id in db.execute(
        select(ArtefactLink.source_id, ArtefactLink.target_id)
        .join(RequirementLinkTypeDefinition, RequirementLinkTypeDefinition.id == ArtefactLink.link_type_id)
        .where(
            ArtefactLink.source_type == REQUEST_ARTEFACT_TYPE, ArtefactLink.source_id.in_(list(source_ids)),
            ArtefactLink.target_type == target_type,
            (ArtefactLink.source_project_id.is_(None)) | (ArtefactLink.source_project_id == project.id),
            RequirementLinkTypeDefinition.forward_name == forward_name,
            RequirementLinkTypeDefinition.organization_id == project.organization_id,
            (RequirementLinkTypeDefinition.project_id.is_(None)) | (RequirementLinkTypeDefinition.project_id == project.id),
        ).order_by(ArtefactLink.created_at, ArtefactLink.id)
    ).all():
        out[source_id].append(target_id)
    return out


def compute_links(db: Session, project: Project, request_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, RequestLinks]:
    """The Pain Points and Requirements of each request of `project`, in a fixed number of statements.

    Args:
        db: Active session (read only).
        project: The project the requests belong to (which decides which link types apply).
        request_ids: Project-owned requests; an organisation request has no links.

    Returns:
        `{request id: RequestLinks}` for every id given (de-duplicated, oldest link first).
    """
    ids = list(dict.fromkeys(request_ids))
    if not ids:
        return {}
    merged = active_merged_duplicates(db, ids)
    sources = list(dict.fromkeys([*ids, *(d for ds in merged.values() for d in ds)]))
    pain_points = _targets(db, project, sources, ADDRESSES_FORWARD, PAIN_POINT_TYPE)
    requirements = _targets(db, project, sources, REALISED_BY_FORWARD, REQUIREMENT_TYPE)
    result: dict[uuid.UUID, RequestLinks] = {}
    for request_id in ids:
        family = [request_id, *merged.get(request_id, ())]
        result[request_id] = RequestLinks(
            pain_point_ids=tuple(dict.fromkeys(t for s in family for t in pain_points.get(s, ()))),
            requirement_ids=tuple(dict.fromkeys(t for s in family for t in requirements.get(s, ()))),
        )
    return result
