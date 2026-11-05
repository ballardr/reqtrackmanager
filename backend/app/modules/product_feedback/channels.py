"""
Module: modules.product_feedback.channels

The channel per ask: how each requester of a request asked (a support ticket, a call, an e-mail).

Responsibilities:
- `channels_by_request`: many requests' requesters' channels in a fixed number of statements.
- `set_channels`: records, changes or clears the channel of requesters of one request.

Design decisions:
- One row per `(request, party)` on `EnhancementRequestRequesterChannel`, matched to the current requesters on read
  and holding no foreign key to the party (it belongs to another module), exactly as the informed record does.
- A merged duplicate's requesters keep the channel they were given on the duplicate; a row on the canonical request
  for the same party overrides it, and clearing removes both.
- A requester reached only through an Engagement has no row (the Engagement is the channel; the UI says so).
- Setting needs the triager gate and every party to be a current requester; the whole call fails on one bad party.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback.demand import active_merged_duplicates, compute_demand
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestRequesterChannel
from app.modules.product_feedback.vocabularies import REQUEST_CHANNELS, resolve_channel

PartyKey = tuple[str, uuid.UUID]


@dataclass(frozen=True)
class ChannelChoice:
    """The channel one requester asked through.

    Attributes:
        id: The project's channel row (an id the project's channel picker accepts).
        name: Its effective name.
    """

    id: uuid.UUID
    name: str


def channels_by_request(
    db: Session, request_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, dict[PartyKey, ChannelChoice]]:
    """`{request id: {(party type, party id): channel}}` for each request, including the channels given on the
    duplicates merged into it (its own row wins), in a fixed number of statements. A request with none is present
    with an empty mapping."""
    out: dict[uuid.UUID, dict[PartyKey, ChannelChoice]] = {i: {} for i in request_ids}
    if not out:
        return out
    merged = active_merged_duplicates(db, list(out))
    sources = list(dict.fromkeys([*out, *(d for ds in merged.values() for d in ds)]))
    rows: dict[uuid.UUID, list[EnhancementRequestRequesterChannel]] = {}
    for row in db.scalars(select(EnhancementRequestRequesterChannel).where(
        EnhancementRequestRequesterChannel.request_id.in_(sources)
    ).order_by(EnhancementRequestRequesterChannel.created_at)):
        rows.setdefault(row.request_id, []).append(row)
    names = REQUEST_CHANNELS.display_names(db, {(None, r.channel_id) for rs in rows.values() for r in rs})
    for request_id in out:
        for source_id in (*merged.get(request_id, ()), request_id):
            for row in rows.get(source_id, ()):
                out[request_id][(row.party_type, row.party_id)] = ChannelChoice(
                    row.channel_id, names.get((None, row.channel_id)) or "",
                )
    return out


def set_channels(
    db: Session, project: Project, request: EnhancementRequest, parties: Sequence[PartyKey],
    channel_id: uuid.UUID | None, actor: User,
) -> int:
    """Sets (or, with `channel_id` `None`, clears) the channel of `parties` on `request`.

    Args:
        db: Active session; the caller has locked the request row, checked the actor may and commits.
        project: The request's project (decides who its requesters are and which channels it offers).
        request: A project-owned request.
        parties: `(type, id)` of requesters; each must be a current requester of the request.
        channel_id: An `EffectiveType.id` of the project's channel list, or `None` to clear.
        actor: The acting user.

    Returns:
        How many parties changed.

    Raises:
        ValueError: If the request is archived, a party is not one of its requesters or the channel is not an
            enabled one of the project.
    """
    if request.is_archived:
        raise ValueError("An archived request cannot be changed; unarchive it first.")
    requesters = {(r.artefact_type, r.id) for r in compute_demand(db, project, [request.id])[request.id].requesters}
    wanted = list(dict.fromkeys(parties))
    for key in wanted:
        if key not in requesters:
            raise ValueError("Every party must be a requester of this request.")
    row_id = resolve_channel(db, project, channel_id) if channel_id is not None else None
    duplicate_ids = active_merged_duplicates(db, [request.id]).get(request.id, [])
    existing: dict[PartyKey, list[EnhancementRequestRequesterChannel]] = {}
    for r in db.scalars(select(EnhancementRequestRequesterChannel).where(
        EnhancementRequestRequesterChannel.request_id.in_([request.id, *duplicate_ids])
    )):
        existing.setdefault((r.party_type, r.party_id), []).append(r)
    changed = 0
    for key in wanted:
        rows = existing.get(key, [])
        own = next((r for r in rows if r.request_id == request.id), None)
        if row_id is None:
            # Clearing also removes what was given on a merged duplicate, or the channel would reappear.
            for r in rows:
                db.delete(r)
            changed += 1 if rows else 0
        elif own is None:
            db.add(EnhancementRequestRequesterChannel(
                request_id=request.id, party_type=key[0], party_id=key[1], channel_id=row_id, set_by=actor.id,
            ))
            changed += 1
        elif own.channel_id != row_id:
            own.channel_id, own.set_by = row_id, actor.id
            changed += 1
    db.flush()
    return changed
