"""
Module: services.perf_dataset.records

The building blocks every non-core artefact type's dataset generator uses, so a module's generator is the type's own
columns and nothing else.

Responsibilities:
- `RecordBatch`: collects a type's identity rows, satellite rows (versions, scores, reviews) and "created" audit
  events, then writes them with chunked Core inserts and moves the project's sequence counter past the generated
  codes.
- `add_comments`, `add_tags`: comment threads and tags on a type's records, in the same proportions as requirements.
- `link_to_earlier`: cross-type links from a type's records to records of types generated before it, with a
  heavy-tailed number of links per target (hubs) and a share to the parent project.
- `scoring_levels`, `org_link_types`, `pick_*`: small lookups of organisation vocabulary the rows must reference.

Design decisions:
- A module registers only its own `PerfDatasetGenerator`; nothing here names a module's type. A type's link partners
  are the types it asks for by string, which must have been generated earlier (`PerfDatasetGenerator.order`).
- Counters are written as the application leaves them: one `ProjectSequenceCounter` row per type with `next_seq`
  one past the last generated code, so the next record a person creates is numbered correctly.
- Cross-type links use a link type that permits both ends when the organisation has one, else are untyped (the
  application stores untyped links too); a cross-level link needs a type with the ancestor scope and is skipped for a
  pair that has none.

Dependencies: SQLAlchemy models, `perf_dataset.context/core/textgen`.
"""

from __future__ import annotations

import itertools
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models.relationship import ArtefactLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.sequence import ProjectSequenceCounter
from app.models.tag import ArtefactTag
from app.services.link_types import get_org_link_type
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import ANCHOR, CHUNK, PerfProjectContext, insert_rows, uuid_from
from app.services.perf_dataset.core import AuditBuffer


def created_at(rng: random.Random, *, max_days: float = 540) -> datetime:
    """A creation instant between one day and `max_days` before the fixed anchor."""
    return ANCHOR - timedelta(days=rng.uniform(1, max_days))


def at_between(rng: random.Random, earliest: datetime, latest: datetime = ANCHOR) -> datetime:
    """A random instant in `[earliest, latest]`."""
    span = max(int((latest - earliest).total_seconds()), 1)
    return earliest + timedelta(seconds=rng.randrange(span))


def pick_weighted(rng: random.Random, mix: Sequence[tuple[Any, float]]) -> Any:
    """One value from `((value, probability), ...)`."""
    roll, total = rng.random(), 0.0
    for value, probability in mix:
        total += probability
        if roll < total:
            return value
    return mix[-1][0]


@dataclass
class RecordBatch:
    """Rows for one artefact type in one project, written together.

    Attributes:
        ctx: The project's generation context.
        artefact_type: The registered type string (also the audit `entity_type` and the sequence counter key).
        prefix: The code prefix (`RSK` in `RSK-001`).
        identity_model: The ORM class of the type's identity table.
        ids: Ids of the records added, in code order (also published as `ctx.shared[artefact_type]`).
        created: Each record's creation instant, parallel to `ids`.
        has_creator: Whether the identity table has a `creator_id` column (a stakeholder group has none).
    """

    ctx: PerfProjectContext
    artefact_type: str
    prefix: str
    identity_model: Any
    audit: AuditBuffer
    ids: list[uuid.UUID] = field(default_factory=list)
    created: list[datetime] = field(default_factory=list)
    has_creator: bool = True
    _identity: list[dict] = field(default_factory=list)
    _satellites: dict[Any, list[dict]] = field(default_factory=dict)

    @classmethod
    def start(
        cls, ctx: PerfProjectContext, artefact_type: str, prefix: str, identity_model: Any, *, has_creator: bool = True
    ) -> RecordBatch:
        """A batch for `artefact_type` in `ctx`'s project."""
        return cls(ctx, artefact_type, prefix, identity_model, AuditBuffer(ctx), has_creator=has_creator)

    def code(self) -> str:
        """The next code (`PREFIX-nnn`), numbered from 1 in the order records are added."""
        return f"{self.prefix}-{len(self.ids) + 1:03d}"

    def new_id(self) -> uuid.UUID:
        """A fresh deterministic id for a record or a satellite row."""
        return uuid_from(self.ctx.rng)

    def add(self, row: dict, *, creator: uuid.UUID, at: datetime, title: str, detail: dict | None = None) -> uuid.UUID:
        """Adds one identity row and its "created" audit event; returns the record id.

        Args:
            row: Column values for the identity table; `id`, `project_id`, `unique_code`, `creator_id` and the
                timestamps are filled in here unless given.
            creator: The author.
            at: The creation instant.
            title: Shown in the audit detail.
            detail: Extra audit detail.
        """
        record_id = row.setdefault("id", self.new_id())
        code = row.setdefault("unique_code", self.code())
        row.setdefault("project_id", self.ctx.project_uuid)
        if self.has_creator:
            row.setdefault("creator_id", creator)
        row.setdefault("created_at", at)
        row.setdefault("updated_at", at)
        self._identity.append(row)
        self.ids.append(record_id)
        self.created.append(at)
        self.audit.add(
            self.artefact_type, record_id, "created", creator, at, detail={"unique_code": code, "title": title, **(detail or {})}
        )
        return record_id

    def satellite(self, model: Any, row: dict) -> None:
        """Queues a row of a satellite table (a version, a score, a review) written with the identity rows."""
        self._satellites.setdefault(model, []).append(row)

    def audit_event(self, record_id: uuid.UUID, action: str, actor: uuid.UUID | None, at: datetime, detail: dict | None = None) -> None:
        """Queues a further audit event for a record (an edit, a transition)."""
        self.audit.add(self.artefact_type, record_id, action, actor, at, detail=detail)

    def write(self) -> int:
        """Writes every queued row, advances the sequence counter past the codes and publishes the ids.

        Returns:
            The number of identity rows written.
        """
        ctx = self.ctx
        if self._identity:
            ctx.add_count(self.identity_model.__tablename__, insert_rows(ctx.db, self.identity_model, self._identity))
        for model, rows in self._satellites.items():
            ctx.add_count(model.__tablename__, insert_rows(ctx.db, model, rows))
        self.audit.flush()
        if self.ids:
            ctx.add_count(
                "project_sequence_counters",
                insert_rows(
                    ctx.db,
                    ProjectSequenceCounter,
                    [{
                        "id": uuid_from(ctx.rng), "project_id": ctx.project_uuid, "artefact_type": self.artefact_type,
                        "next_seq": len(self.ids) + 1, "created_at": ANCHOR, "updated_at": ANCHOR,
                    }],
                ),
            )
        ctx.shared[self.artefact_type] = self.ids
        ctx.created_times[self.artefact_type] = self.created
        written = len(self._identity)
        self._identity, self._satellites = [], {}
        return written


def add_comments(
    ctx: PerfProjectContext, batch: RecordBatch, model: Any, fk: str, *, mean: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Writes comment threads on a batch's records (a few threads are long), at the requirements' comment ratio.

    Args:
        ctx: The project's context.
        batch: The records that were added (call before or after `write`; it only reads ids and times).
        model: The type's comment model (`fk`, `author_id`, `body`, `edited_at`, `created_at`, `updated_at`).
        fk: The comment model's foreign-key attribute naming the record.
        mean: Comments per record; defaults to the spec's requirement comment ratio.
        extra: Column values added to every comment (the shared comment table's `target_type`).
    """
    rng = ctx.rng
    n = len(batch.ids)
    total = round(n * (ctx.spec.ratios.comments if mean is None else mean))
    if total == 0 or n == 0:
        return
    cumulative = list(itertools.accumulate(1 / ((i + 1) ** 0.5) for i in range(n)))
    order = list(range(n))
    rng.shuffle(order)
    rows = []
    for _ in range(total):
        index = order[rng.choices(range(n), cum_weights=cumulative)[0]]
        at = at_between(rng, batch.created[index])
        rows.append({
            "id": uuid_from(rng), fk: batch.ids[index], "author_id": rng.choice(ctx.user_ids),
            "body": textgen.sentences(rng, rng.randint(1, 4)), "edited_at": None, "created_at": at, "updated_at": at,
            **(extra or {}),
        })
    ctx.add_count(model.__tablename__, insert_rows(ctx.db, model, rows))


def add_tags(ctx: PerfProjectContext, batch: RecordBatch) -> None:
    """Attaches tags from the project's vocabulary to a batch's records (popular tags are chosen more), with the
    "tagged" audit events the application writes. Does nothing when the project has no tags."""
    rng, spec = ctx.rng, ctx.spec
    if not ctx.tags or not batch.ids:
        return
    vocabulary = len(ctx.tags)
    cumulative = list(itertools.accumulate(1 / ((i + 1) ** 0.8) for i in range(vocabulary)))
    rows = []
    for index, record_id in enumerate(batch.ids):
        wanted = min(_poisson(rng, spec.ratios.tags_per_requirement), vocabulary)
        chosen: set[int] = set()
        while len(chosen) < wanted:
            chosen.add(rng.choices(range(vocabulary), cum_weights=cumulative)[0])
        for tag_index in sorted(chosen):
            at = batch.created[index] + timedelta(hours=1)
            tag_id, name = ctx.tags[tag_index]
            rows.append({
                "tag_id": tag_id, "artefact_type": batch.artefact_type, "artefact_id": record_id,
                "project_id": ctx.project_uuid, "created_by": ctx.user_ids[0], "created_at": at,
            })
            batch.audit.add(
                batch.artefact_type, record_id, "tagged", ctx.user_ids[0], at,
                detail={"tag": name, "tag_id": str(tag_id)}, organization_id=ctx.organization_uuid,
            )
    ctx.add_count("artefact_tags", insert_rows(ctx.db, ArtefactTag, rows))
    batch.audit.flush()


def _poisson(rng: random.Random, mean: float) -> int:
    """A Poisson draw (Knuth), fine for the small means used here."""
    import math

    if mean <= 0:
        return 0
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def org_link_types(ctx: PerfProjectContext) -> list[RequirementLinkTypeDefinition]:
    """The organisation's link types that are not dedicated to one action (cached on the context's `org_state`)."""
    cached = ctx.org_state.get("_link_types")
    if cached is None:
        cached = list(ctx.db.scalars(
            select(RequirementLinkTypeDefinition).where(
                RequirementLinkTypeDefinition.organization_id == ctx.organization_uuid,
                RequirementLinkTypeDefinition.project_id.is_(None),
                RequirementLinkTypeDefinition.dedicated_endpoint.is_(False),
            ).order_by(RequirementLinkTypeDefinition.sort_order)
        ))
        ctx.org_state["_link_types"] = cached
    return cached


def link_types_between(ctx: PerfProjectContext, source_type: str, target_type: str) -> list[RequirementLinkTypeDefinition]:
    """Link types whose restrictions allow `source_type` -> `target_type` (an empty restriction allows any)."""
    return [
        t for t in org_link_types(ctx)
        if (not t.allowed_source_types or source_type in t.allowed_source_types)
        and (not t.allowed_target_types or target_type in t.allowed_target_types)
    ]


@dataclass(frozen=True)
class Partner:
    """A type a batch's records link to, with how.

    Attributes:
        artefact_type: The partner type (generated earlier in this project).
        weight: Its share of the batch's links.
        forward_name: Use this organisation link type (by forward name) instead of any type that permits the pair;
            for a relationship the application reads by name (a participant, a represented persona).
        record_is_target: The partner record is the link's source and the batch's record its target.
        untyped: Write the links without a link type (as the application does for evidence links).
    """

    artefact_type: str
    weight: float
    forward_name: str | None = None
    record_is_target: bool = False
    untyped: bool = False


def link_to_earlier(
    ctx: PerfProjectContext,
    batch: RecordBatch,
    partners: Sequence[tuple[str, float] | Partner],
    *,
    degree_scale: float = 1.0,
) -> int:
    """Links a batch's records to records of earlier-generated types.

    Each record draws a number of outgoing links with mean `mean_degree * degree_scale` split across `partners` by
    weight; the partner record is chosen with a Zipf weight, so a few partner records become hubs. On top of that the
    most-weighted partner record of each type is planted with up to `hub_max_degree` links (fewer where the batch has
    fewer records), so a hub of hundreds to a thousand links exists at the larger tiers. In a nested project a share
    (`cross_level_link_fraction`) of the links go to the parent project's records of the partner type, and a share
    (`dormant_link_fraction`) to a sibling project's, which is outside the project's ancestry and so dormant; both need
    a link type with the ancestor scope for the pair.

    Records the realised degree of every record in `ctx.degrees` and per type pair in `ctx.pair_stats`.

    Args:
        ctx: The project's context.
        batch: The records whose links are written.
        partners: `(partner artefact type, weight)` pairs or `Partner`s; a type with no records in `ctx.shared`
            is skipped.
        degree_scale: Multiplier on the spec's mean degree for this type.

    Returns:
        The number of links written.
    """
    rng, ratios = ctx.rng, ctx.spec.ratios
    if not batch.ids or ratios.mean_degree <= 0:
        return 0
    normalised = [p if isinstance(p, Partner) else Partner(p[0], p[1]) for p in partners]
    available = [p for p in normalised if ctx.shared.get(p.artefact_type)]
    if not available:
        return 0
    total_weight = sum(p.weight for p in available)
    audit = AuditBuffer(ctx)
    rows: list[dict] = []
    seen: set[tuple[uuid.UUID, str, uuid.UUID]] = set()
    parent_id = uuid.UUID(ctx.project.parent_id) if ctx.project.parent_id else None
    dormant = 0

    for partner in available:
        partner_type = partner.artefact_type
        source_type, target_type = (partner_type, batch.artefact_type) if partner.record_is_target else (batch.artefact_type, partner_type)
        targets = ctx.shared[partner_type]
        n = len(targets)
        mean = ratios.mean_degree * degree_scale * partner.weight / total_weight
        order = list(range(n))
        rng.shuffle(order)
        cumulative = list(itertools.accumulate(1 / ((i + 1) ** ratios.hub_exponent) for i in range(n)))
        if partner.untyped:
            types = []
        elif partner.forward_name:
            named = get_org_link_type(ctx.db, ctx.organization_uuid, partner.forward_name)
            types = [named] if named is not None else []
        else:
            types = link_types_between(ctx, source_type, target_type)
        cross_types = [t for t in types if getattr(t.nesting_scope, "value", str(t.nesting_scope)) == "ancestor_either_way"]
        parent_targets = (ctx.parent_shared or {}).get(partner_type) if parent_id and cross_types else None
        sibling_targets = [(pid, shared[partner_type]) for pid, shared in ctx.siblings if shared.get(partner_type)] if cross_types else []
        pair = f"{source_type}>{target_type}"
        partner_degree: dict[uuid.UUID, int] = {}

        def emit(record_index: int, partner_id: uuid.UUID, link_type: Any, project_pair: tuple[Any, Any],
                 partner_type: str = partner_type, partner_record_is_target: bool = partner.record_is_target,
                 source_type: str = source_type, target_type: str = target_type, pair: str = pair,
                 partner_degree: dict[uuid.UUID, int] = partner_degree) -> None:
            record_id = batch.ids[record_index]
            at = at_between(rng, batch.created[record_index])
            author, link_id = rng.choice(ctx.user_ids), uuid_from(rng)
            end_a, end_b = (partner_id, record_id) if partner_record_is_target else (record_id, partner_id)
            rows.append({
                "id": link_id, "source_type": source_type, "source_id": end_a, "target_type": target_type, "target_id": end_b,
                "link_type_id": link_type.id if link_type else None,
                "source_project_id": project_pair[0], "target_project_id": project_pair[1],
                "created_by": author, "created_at": at, "updated_at": at,
            })
            audit.add(
                "artefact_link", link_id, "created", author, at,
                detail={"source_type": source_type, "source_id": str(end_a), "target_type": target_type, "target_id": str(end_b)},
            )
            partner_degree[partner_id] = partner_degree.get(partner_id, 0) + 1
            for end_type, end_id in ((source_type, end_a), (target_type, end_b)):
                counts = ctx.degrees.setdefault(end_type, {})
                counts[end_id] = counts.get(end_id, 0) + 1

        here = ctx.project_uuid
        for index in range(len(batch.ids)):
            for _ in range(_poisson(rng, mean)):
                roll = rng.random()
                if parent_targets and roll < ratios.cross_level_link_fraction:
                    target_id, project_pair = rng.choice(parent_targets), ((parent_id, here) if partner.record_is_target else (here, parent_id))
                    link_type = rng.choice(cross_types)
                elif sibling_targets and roll > 1 - ratios.dormant_link_fraction:
                    sibling_id, sibling_ids = rng.choice(sibling_targets)
                    target_id, project_pair = rng.choice(sibling_ids), ((sibling_id, here) if partner.record_is_target else (here, sibling_id))
                    link_type = rng.choice(cross_types)
                    dormant += 1
                else:
                    target_id, project_pair = targets[order[rng.choices(range(n), cum_weights=cumulative)[0]]], (None, None)
                    link_type = rng.choice(types) if types else None
                key = (batch.ids[index], partner_type, target_id)
                if key in seen:
                    continue
                seen.add(key)
                emit(index, target_id, link_type, project_pair)

        # Plant the hub: the highest-weighted partner record gets links from as many of the batch's records as the cap allows.
        if ratios.hub_max_degree > 0:
            hub = targets[order[0]]
            wanted = min(ratios.hub_max_degree, len(batch.ids)) - partner_degree.get(hub, 0)
            candidates = [i for i in range(len(batch.ids)) if (batch.ids[i], partner_type, hub) not in seen]
            for index in rng.sample(candidates, max(0, min(wanted, len(candidates)))):
                seen.add((batch.ids[index], partner_type, hub))
                emit(index, hub, rng.choice(types) if types else None, (None, None))

        stats = ctx.pair_stats.setdefault(pair, {"links": 0, "max_partner_degree": 0})
        stats["links"] += sum(partner_degree.values())
        stats["max_partner_degree"] = max(stats["max_partner_degree"], max(partner_degree.values(), default=0))

    audit.flush()
    cross_level = sum(1 for row in rows if row["source_project_id"] is not None)
    ctx.histogram["cross_type_links"] = ctx.histogram.get("cross_type_links", 0) + len(rows)
    ctx.histogram["cross_type_cross_level_links"] = ctx.histogram.get("cross_type_cross_level_links", 0) + cross_level
    ctx.histogram["dormant_links"] = ctx.histogram.get("dormant_links", 0) + dormant
    ctx.histogram["cross_type_max"] = max(
        ctx.histogram.get("cross_type_max", 0), max((d for counts in ctx.degrees.values() for d in counts.values()), default=0)
    )
    for start in range(0, len(rows), CHUNK):
        ctx.add_count("artefact_links", insert_rows(ctx.db, ArtefactLink, rows[start:start + CHUNK]))
    return len(rows)


def project_type_ids(ctx: PerfProjectContext, project_type_model: Any, org_type_model: Any) -> list[uuid.UUID]:
    """The ids of the project's type-vocabulary rows, creating the pass-through rows the application creates lazily.

    A type an organisation defines is used in a project through a `Project<X>Type` row (`org_type_id` set, no
    override). The application writes it the first time a record picks the type; the generator writes one per active
    organisation type so records can reference them.

    Args:
        ctx: The project's context.
        project_type_model: The `Project<X>Type` class (`project_id`, `org_type_id`, `is_enabled`).
        org_type_model: The matching organisation type class (`organization_id`, `is_active`, `sort_order`).

    Returns:
        The project's type ids (its own overrides included), possibly empty when the organisation defines none.
    """
    db = ctx.db
    existing = list(db.scalars(select(project_type_model.id).where(project_type_model.project_id == ctx.project_uuid)))
    if existing:
        return existing
    org_types = list(db.scalars(
        select(org_type_model.id)
        .where(org_type_model.organization_id == ctx.organization_uuid, org_type_model.is_active.is_(True))
        .order_by(org_type_model.sort_order)
    ))
    rows = [
        {"id": uuid_from(ctx.rng), "project_id": ctx.project_uuid, "org_type_id": org_type, "is_enabled": True,
         "created_at": ANCHOR, "updated_at": ANCHOR}
        for org_type in org_types
    ]
    ctx.add_count(project_type_model.__tablename__, insert_rows(db, project_type_model, rows))
    return [row["id"] for row in rows]
