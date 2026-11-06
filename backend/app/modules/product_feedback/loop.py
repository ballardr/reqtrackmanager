"""
Module: modules.product_feedback.loop

Closing the loop: telling the people who asked what became of their request.

Responsibilities:
- `set_informed`: records (or withdraws) that requesters were told the outcome of a delivered or declined request.
- `informed_by_request`: the informed rows of many requests in one statement.
- `open_loop_requests`: the delivered or declined requests of a project that still have a requester not told.
- `delivery_state`: whether the requirements realising a request are all complete, the cue to mark it delivered.

Design decisions:
- Only requesters are tracked, never free-text names, and nothing is sent: a triager tells the person by whatever
  means they use and ticks them off here (**Decided by: User**; no e-mail goes to people outside the organisation).
- A requester is anyone `demand.compute_demand` reports for the request, those reached through a merged
  duplicate included, so the list a triager works through is the same union demand is counted over.
- The informed row is keyed by the party and matched to the current requesters on every read, so removing a
  link or ending a merge hides the row and restoring it brings the record back; nothing is deleted behind the user.
- Telling someone is only recordable once there is an outcome to tell (delivered or declined); withdrawing a
  record is always allowed (a mistaken tick, or a request reopened).
- "Delivered" stays a hand-set status (**Decided by: User**). `delivery_state` only supplies the prompt: the linked
  Requirements' completion overlay, never an automatic transition, which would couple this module to core
  requirement semantics.
- Nothing here commits or checks who may do it; the caller owns the transaction, the gate and the audit event.

Dependencies: this module's models, `demand`, `relationships` and `service`; core `Requirement`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.requirement import Requirement
from app.models.user import User
from app.modules.product_feedback.demand import Demand, compute_demand
from app.modules.product_feedback.enums import EnhancementRequestStatus
from app.modules.product_feedback.labels import request_status_label
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestInformed, EnhancementRequestVersion
from app.modules.product_feedback.service import get_current_version

_S = EnhancementRequestStatus

#: Statuses with an outcome to tell requesters about.
CLOSED_STATUSES = frozenset({_S.DELIVERED, _S.DECLINED})

PartyKey = tuple[str, uuid.UUID]


def informed_by_request(db: Session, request_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[PartyKey, EnhancementRequestInformed]]:
    """`{request id: {(party type, party id): row}}` for the requests, in one statement (requests with none are absent)."""
    out: dict[uuid.UUID, dict[PartyKey, EnhancementRequestInformed]] = defaultdict(dict)
    if not request_ids:
        return out
    for row in db.scalars(select(EnhancementRequestInformed).where(EnhancementRequestInformed.request_id.in_(list(request_ids)))):
        out[row.request_id][(row.party_type, row.party_id)] = row
    return out


def open_count(demand: Demand, status: EnhancementRequestStatus, informed: Iterable[PartyKey]) -> int:
    """How many of the request's requesters still have to be told: zero until the request is delivered or declined."""
    if status not in CLOSED_STATUSES:
        return 0
    told = set(informed)
    return sum(1 for r in demand.requesters if (r.artefact_type, r.id) not in told)


def set_informed(
    db: Session, project: Project, request: EnhancementRequest, parties: Sequence[PartyKey], informed: bool, note: str,
    actor: User,
) -> int:
    """Records that `parties` were told the request's outcome, or withdraws that record.

    Args:
        db: Active session; the caller has locked the request row, checked the actor may and commits.
        project: The request's project (decides who its requesters are).
        request: A project-owned request.
        parties: `(type, id)` of requesters; each must be a current requester of the request.
        informed: True to record, False to withdraw.
        note: Free text kept with a recorded row (ignored when withdrawing).
        actor: The acting user.

    Returns:
        How many parties changed (one already in the wanted state is left alone).

    Raises:
        ValueError: If the request is archived, has no outcome yet (recording only) or a party is not one of its
            requesters.
    """
    if request.is_archived:
        raise ValueError("An archived request cannot be changed; unarchive it first.")
    version = get_current_version(db, request.id)
    if informed and version.status not in CLOSED_STATUSES:
        raise ValueError(
            f"A request that is {request_status_label(version.status.value).lower()} has no outcome to tell "
            "requesters about yet; deliver or decline it first."
        )
    requesters = {(r.artefact_type, r.id) for r in compute_demand(db, project, [request.id])[request.id].requesters}
    wanted = list(dict.fromkeys(parties))
    for key in wanted:
        if key not in requesters:
            raise ValueError("Every party must be a requester of this request.")
    existing = informed_by_request(db, [request.id]).get(request.id, {})
    changed = 0
    now = datetime.now(UTC)
    for key in wanted:
        row = existing.get(key)
        if informed and row is None:
            db.add(EnhancementRequestInformed(
                request_id=request.id, party_type=key[0], party_id=key[1], informed_by=actor.id, informed_at=now,
                note=note.strip(),
            ))
            changed += 1
        elif informed and row is not None and note.strip() and row.note != note.strip():
            row.note = note.strip()
            changed += 1
        elif not informed and row is not None:
            db.delete(row)
            changed += 1
    db.flush()
    return changed


@dataclass(frozen=True)
class OpenLoop:
    """A closed request with requesters still to be told.

    Attributes:
        request: The request.
        version: Its current version (the status and decline reason).
        demand: Its requesters.
        uninformed: The requesters not yet told, in demand order.
    """

    request: EnhancementRequest
    version: EnhancementRequestVersion
    demand: Demand
    uninformed: tuple[tuple[str, uuid.UUID], ...]


def open_loop_requests(db: Session, project: Project) -> list[OpenLoop]:
    """The project's delivered or declined, unarchived requests that have a requester not yet told, oldest first,
    in a fixed number of statements.

    Args:
        db: Active session (read only).
        project: The project to read.

    Returns:
        One `OpenLoop` per such request, ordered by code.
    """
    rows = db.execute(
        select(EnhancementRequest, EnhancementRequestVersion)
        .join(EnhancementRequestVersion, EnhancementRequestVersion.request_id == EnhancementRequest.id)
        .where(
            EnhancementRequest.project_id == project.id, EnhancementRequest.is_archived.is_(False),
            EnhancementRequestVersion.valid_to.is_(None), EnhancementRequestVersion.status.in_(CLOSED_STATUSES),
        ).order_by(EnhancementRequest.unique_code)
    ).all()
    if not rows:
        return []
    closed = [request for request, _ in rows]
    versions = {request.id: version for request, version in rows}
    demand = compute_demand(db, project, [r.id for r in closed])
    informed = informed_by_request(db, [r.id for r in closed])
    out: list[OpenLoop] = []
    for request in closed:
        told = informed.get(request.id, {})
        pending = tuple((r.artefact_type, r.id) for r in demand[request.id].requesters if (r.artefact_type, r.id) not in told)
        if pending:
            out.append(OpenLoop(request, versions[request.id], demand[request.id], pending))
    return out


def requirements_complete(db: Session, requirement_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, bool]:
    """`{requirement id: is_completed}` (the completion overlay, independent of approval status) for those that exist."""
    if not requirement_ids:
        return {}
    return {
        rid: bool(done) for rid, done in db.execute(
            select(Requirement.id, Requirement.is_completed).where(Requirement.id.in_(list(requirement_ids)))
        ).all()
    }


def delivery_state(db: Session, requirement_ids: Sequence[uuid.UUID]) -> bool | None:
    """Whether every realising requirement is complete: `None` when there are none (nothing to prompt on)."""
    if not requirement_ids:
        return None
    done = requirements_complete(db, requirement_ids)
    return all(done.get(rid, False) for rid in requirement_ids)
