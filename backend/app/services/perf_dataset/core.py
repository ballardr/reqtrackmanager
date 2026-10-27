"""
Module: services.perf_dataset.core

The core artefact types' dataset generators: requirements (with their version history, tags, comments, links
and audit events) and requirement actions (with their links to requirements).

Responsibilities:
- Write the same rows the application's create paths write (`services.requirements.create_requirement`,
  `routers.actions`, `services.tags.set_record_tags`, `routers.requirements.comments`, `create_link`) for
  thousands of records at once, in proportions taken from the dataset spec.
- Keep the counters the application relies on ahead of the generated codes (`Project.next_requirement_seq`,
  `Project.next_action_seq`).
- Report the realised link-degree histogram, so "links per record" is a measured fact of the run.

Design decisions:
- Bulk Core inserts, not the API: 20,000 requirements and their links and history through HTTP would take hours
  and would measure the API, not the data. Drift from the real create path is guarded by the parity test, which
  compares the populated columns of a generated row with an API-created one.
- Link endpoints are drawn from a Zipf-weighted distribution (`hub_exponent`), giving a heavy tail: most
  requirements have a few links and a handful are hubs with hundreds. Edges are oriented from the earlier to the
  later requirement so directional link types can never form a cycle.
- History is the fastest-growing data: every extra version adds a version row and an audit event, as an edit does.

Dependencies: SQLAlchemy models, `perf_dataset.context/textgen`, `models.*`.
"""

from __future__ import annotations

import itertools
import math
import random
import uuid
from datetime import date, datetime, timedelta

from app.models.audit import AuditEvent
from app.models.change_request import ReviewComment
from app.models.enums import (
    ArtefactType,
    PrincipalType,
    RequirementActionOutcome,
    RequirementLevel,
    RequirementStatus,
    ReviewTargetType,
)
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.models.tag import ArtefactTag, Tag
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import ANCHOR, CHUNK, PerfProjectContext, insert_rows, uuid_from

#: Final-status mix of generated requirements.
_STATUS_MIX = (
    (RequirementStatus.DRAFT, 0.35),
    (RequirementStatus.REVIEWED, 0.15),
    (RequirementStatus.APPROVED, 0.45),
    (RequirementStatus.ARCHIVED, 0.05),
)
_OUTCOME_MIX = ((RequirementActionOutcome.PENDING, 0.6), (RequirementActionOutcome.COMPLETED, 0.35), (RequirementActionOutcome.FAILED, 0.05))
_TAG_WORDS = (
    "safety security performance usability legal regulatory hardware software mechanical electrical thermal "
    "interface reliability maintainability supplier release-1 release-2 customer internal critical deferred "
    "verified review-needed accessibility data audit"
).split()
#: Link-degree histogram bucket upper bounds (inclusive); the last is open-ended.
_DEGREE_BUCKETS = (0, 1, 2, 5, 10, 50, 100)
_MAX_EXTRA_VERSIONS = 10


class AuditBuffer:
    """Collects audit rows and writes them in chunks, so a hundred thousand events never sit in memory at once."""

    def __init__(self, ctx: PerfProjectContext) -> None:
        self._ctx = ctx
        self._rows: list[dict] = []

    def add(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        actor_id: uuid.UUID | None,
        at: datetime,
        *,
        detail: dict | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> None:
        """Queues one event (project-scoped, like the routers' `log_event` calls)."""
        self._rows.append(
            {
                "id": uuid_from(self._ctx.rng),
                "organization_id": organization_id,
                "project_id": self._ctx.project_uuid,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "action": action,
                "actor_id": actor_id,
                "detail": detail,
                "created_at": at,
            }
        )
        if len(self._rows) >= CHUNK:
            self.flush()

    def flush(self) -> None:
        """Writes the queued events."""
        if self._rows:
            self._ctx.add_count("audit_events", insert_rows(self._ctx.db, AuditEvent, self._rows))
            self._rows = []


def _weighted(rng: random.Random, mix: tuple) -> object:
    """One value from `((value, probability), ...)`."""
    roll, total = rng.random(), 0.0
    for value, probability in mix:
        total += probability
        if roll < total:
            return value
    return mix[-1][0]


def extra_versions(rng: random.Random, mean_versions: float) -> int:
    """Edits after creation: geometric with mean `mean_versions - 1`, capped."""
    mean_extra = mean_versions - 1
    if mean_extra <= 0:
        return 0
    p = 1 / (1 + mean_extra)
    count = 0
    while count < _MAX_EXTRA_VERSIONS and rng.random() > p:
        count += 1
    return count


def _poisson(rng: random.Random, mean: float) -> int:
    """A Poisson draw (Knuth), fine for the small means used here."""
    if mean <= 0:
        return 0
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _zipf_cumulative(rng: random.Random, n: int, exponent: float) -> list[float]:
    """Cumulative Zipf weights over `n` items in a random rank order (so hubs are not the first rows)."""
    ranks = list(range(1, n + 1))
    rng.shuffle(ranks)
    return list(itertools.accumulate(1 / (rank**exponent) for rank in ranks))


def _bucket(degree: int) -> str:
    """The histogram label for a link degree."""
    for bound in _DEGREE_BUCKETS:
        if degree <= bound:
            return str(bound) if bound <= 1 else f"<={bound}"
    return f">{_DEGREE_BUCKETS[-1]}"


def _at(rng: random.Random, earliest: datetime, latest: datetime) -> datetime:
    """A random instant in `[earliest, latest]`."""
    span = max(int((latest - earliest).total_seconds()), 1)
    return earliest + timedelta(seconds=rng.randrange(span))


def generate_requirements(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's requirements and everything hanging off them.

    Writes `requirements`, `requirement_versions`, `tags`, `artefact_tags`, `review_comments`, requirement-to-
    requirement `artefact_links` (including links to the parent project when nested) and their audit events, and
    advances `Project.next_requirement_seq`. Records the ids in `ctx.shared["requirement"]` and the realised link
    degree histogram in `ctx.histogram`.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name (also accumulated in `ctx.counts`).
    """
    spec, rng, db = ctx.spec, ctx.rng, ctx.db
    count = spec.requirements_per_project
    project_id = ctx.project_uuid
    org_id = ctx.organization_uuid
    component_of = {category[0]: category for category in ctx.project.categories}
    categories = list(component_of.values())
    prefixes = {component_id: prefix for component_id, prefix in ctx.project.components}
    stage_ids = [uuid.UUID(s) for s in ctx.project.stage_ids]
    audit = AuditBuffer(ctx)
    start_counts = dict(ctx.counts)

    requirement_rows, version_rows = [], []
    approved_ids: list[uuid.UUID] = []
    requirement_ids: list[uuid.UUID] = []
    created_times: list[datetime] = []
    for index in range(count):
        requirement_id = uuid_from(rng)
        requirement_ids.append(requirement_id)
        category_id, component_id, category_prefix = categories[index % len(categories)]
        creator = rng.choice(ctx.user_ids)
        created = ANCHOR - timedelta(days=rng.uniform(1, 540))
        created_times.append(created)
        final_status = _weighted(rng, _STATUS_MIX)
        extra = extra_versions(rng, spec.ratios.versions_per_requirement)
        archived = final_status is RequirementStatus.ARCHIVED
        completed = final_status is RequirementStatus.APPROVED and rng.random() < 0.25
        requirement_rows.append(
            {
                "id": requirement_id,
                "project_id": project_id,
                "component_id": uuid.UUID(component_id),
                "category_id": uuid.UUID(category_id),
                "unique_code": f"{prefixes[component_id]}-{category_prefix}-{index + 1:03d}",
                "creator_id": creator,
                "is_archived": archived,
                "archived_at": created + timedelta(days=30) if archived else None,
                "archived_by": creator if archived else None,
                "is_completed": completed,
                "completed_at": created + timedelta(days=45) if completed else None,
                "completed_by": creator if completed else None,
                "created_at": created,
                "updated_at": created,
            }
        )
        audit.add("requirement", requirement_id, "created", creator, created)
        valid_from = created
        stage_id = stage_ids[0] if rng.random() < 0.6 else rng.choice(stage_ids)
        review_date = date(2026, 1, 1) + timedelta(days=rng.randrange(0, 900)) if rng.random() < 0.3 else None
        reviewer = rng.choice(ctx.user_ids) if review_date and rng.random() < 0.7 else None
        name, reasoning = textgen.title(rng), textgen.paragraphs(rng, empty_chance=0.05, short_max=3)
        clarification = textgen.paragraphs(rng, empty_chance=0.6, short_max=2)
        description = textgen.paragraphs(rng, empty_chance=0.3, short_max=4, long_chance=0.12)
        for number in range(1, extra + 2):
            last = number == extra + 1
            author = creator if number == 1 else rng.choice(ctx.user_ids)
            next_from = valid_from + timedelta(hours=rng.uniform(1, 24 * 20))
            if number > 1:
                if rng.random() < 0.5:
                    name = textgen.title(rng)
                reasoning = textgen.paragraphs(rng, empty_chance=0.05, short_max=3)
                audit.add("requirement", requirement_id, "updated", author, valid_from, detail={"change_note": "Reworded."})
            status = final_status if last else (RequirementStatus.REVIEWED if number == extra and rng.random() < 0.3 else RequirementStatus.DRAFT)
            approver = rng.choice(ctx.user_ids) if status is RequirementStatus.APPROVED else None
            if approver and last:
                audit.add("requirement", requirement_id, "approved", approver, valid_from + timedelta(minutes=5))
                if not archived:
                    approved_ids.append(requirement_id)
            version_rows.append(
                {
                    "id": uuid_from(rng),
                    "requirement_id": requirement_id,
                    "version_number": number,
                    "valid_from": valid_from,
                    "valid_to": None if last else next_from,
                    "name": name,
                    "reasoning": reasoning,
                    "clarification": clarification,
                    "description": description,
                    "status": status,
                    "target_stage_id": stage_id,
                    "level": RequirementLevel.REQUIREMENT,
                    "owner_type": PrincipalType.USER.value,
                    "owner_id": creator,
                    "approval_authority_id": approver,
                    "sort_order": index,
                    "custom_fields": {},
                    "change_request_id": None,
                    "change_note": "Initial creation." if number == 1 else "Reworded.",
                    "review_date": review_date,
                    "review_lead_days": 14 if review_date else None,
                    "reviewer_type": PrincipalType.USER.value if reviewer else None,
                    "reviewer_id": reviewer,
                    "review_reminder_sent_at": None,
                    "created_by": author,
                    "created_at": valid_from,
                }
            )
            valid_from = next_from
    ctx.add_count("requirements", insert_rows(db, Requirement, requirement_rows))
    ctx.add_count("requirement_versions", insert_rows(db, RequirementVersion, version_rows))
    del requirement_rows, version_rows
    ctx.shared["requirement"] = requirement_ids
    #: Locked (approved, not archived) requirements: the only ones a change request may modify.
    ctx.shared["requirement_approved"] = approved_ids

    _generate_tags(ctx, audit, requirement_ids, created_times, org_id)
    _generate_comments(ctx, requirement_ids, created_times)
    _generate_links(ctx, audit, requirement_ids, created_times)
    audit.flush()
    db.query(Project).filter(Project.id == project_id).update({Project.next_requirement_seq: count + 1})
    return {table: ctx.counts.get(table, 0) - start_counts.get(table, 0) for table in ctx.counts}


def _generate_tags(
    ctx: PerfProjectContext, audit: AuditBuffer, requirement_ids: list[uuid.UUID], created: list[datetime], org_id: uuid.UUID
) -> None:
    """The project's tag vocabulary and the tags attached to requirements (skewed toward a few popular tags)."""
    rng, spec = ctx.rng, ctx.spec
    vocabulary = max(1, spec.ratios.tag_vocabulary)
    names = [(_TAG_WORDS[i % len(_TAG_WORDS)] + ("" if i < len(_TAG_WORDS) else f"-{i // len(_TAG_WORDS) + 1}")) for i in range(vocabulary)]
    tags = [
        {
            "id": uuid_from(rng),
            "organization_id": org_id,
            "project_id": ctx.project_uuid,
            "name": name,
            "name_key": name.casefold(),
            "colour": None,
            "created_by": ctx.user_ids[0],
            "created_at": ANCHOR - timedelta(days=600),
            "updated_at": ANCHOR - timedelta(days=600),
        }
        for name in names
    ]
    ctx.add_count("tags", insert_rows(ctx.db, Tag, tags))
    ctx.tags = [(tag["id"], tag["name"]) for tag in tags]
    cumulative = list(itertools.accumulate(1 / ((i + 1) ** 0.8) for i in range(vocabulary)))
    attachments = []
    for index, requirement_id in enumerate(requirement_ids):
        wanted = min(_poisson(rng, spec.ratios.tags_per_requirement), vocabulary)
        chosen: set[int] = set()
        while len(chosen) < wanted:
            chosen.add(rng.choices(range(vocabulary), cum_weights=cumulative)[0])
        for tag_index in sorted(chosen):
            at = created[index] + timedelta(hours=1)
            tag = tags[tag_index]
            attachments.append(
                {
                    "tag_id": tag["id"],
                    "artefact_type": ArtefactType.REQUIREMENT.value,
                    "artefact_id": requirement_id,
                    "project_id": ctx.project_uuid,
                    "created_by": ctx.user_ids[0],
                    "created_at": at,
                }
            )
            audit.add(
                "requirement",
                requirement_id,
                "tagged",
                ctx.user_ids[0],
                at,
                detail={"tag": tag["name"], "tag_id": str(tag["id"])},
                organization_id=org_id,
            )
    ctx.add_count("artefact_tags", insert_rows(ctx.db, ArtefactTag, attachments))


def _generate_comments(ctx: PerfProjectContext, requirement_ids: list[uuid.UUID], created: list[datetime]) -> None:
    """Review comments on requirements; a few threads are long (Zipf-weighted choice of requirement)."""
    rng = ctx.rng
    total = round(len(requirement_ids) * ctx.spec.ratios.comments)
    if total == 0:
        return
    cumulative = list(itertools.accumulate(1 / ((i + 1) ** 0.5) for i in range(len(requirement_ids))))
    order = list(range(len(requirement_ids)))
    rng.shuffle(order)
    rows = []
    for _ in range(total):
        index = order[rng.choices(range(len(order)), cum_weights=cumulative)[0]]
        at = _at(rng, created[index], ANCHOR)
        rows.append(
            {
                "id": uuid_from(rng),
                "target_type": ReviewTargetType.REQUIREMENT,
                "target_id": requirement_ids[index],
                "author_id": rng.choice(ctx.user_ids),
                "body": textgen.sentences(rng, rng.randint(1, 4)),
                "edited_at": None,
                "created_at": at,
                "updated_at": at,
            }
        )
    ctx.add_count("review_comments", insert_rows(ctx.db, ReviewComment, rows))


def _generate_links(ctx: PerfProjectContext, audit: AuditBuffer, requirement_ids: list[uuid.UUID], created: list[datetime]) -> None:
    """Requirement-to-requirement links with a heavy-tailed degree distribution, plus links to the parent project."""
    rng, spec = ctx.rng, ctx.spec
    n = len(requirement_ids)
    usable = list(ctx.link_type_ids)
    ctx.histogram = {}
    if n < 2 or not usable or spec.ratios.mean_degree <= 0:
        return
    wanted = min(round(n * spec.ratios.mean_degree / 2), n * (n - 1) // 4)
    cumulative = _zipf_cumulative(rng, n, spec.ratios.hub_exponent)
    seen: set[tuple[int, int]] = set()
    degree = [0] * n
    attempts = 0
    while len(seen) < wanted and attempts < wanted * 20:
        attempts += 1
        a, b = rng.choices(range(n), cum_weights=cumulative, k=2)
        if a == b:
            continue
        pair = (a, b) if a < b else (b, a)
        if pair in seen:
            continue
        seen.add(pair)
        degree[a] += 1
        degree[b] += 1
    rows = []
    for source, target in sorted(seen):
        link_type_id, _scope = rng.choice(usable)
        at = _at(rng, max(created[source], created[target]), ANCHOR)
        link_id = uuid_from(rng)
        author = rng.choice(ctx.user_ids)
        rows.append(
            {
                "id": link_id,
                "source_type": ArtefactType.REQUIREMENT.value,
                "source_id": requirement_ids[source],
                "target_type": ArtefactType.REQUIREMENT.value,
                "target_id": requirement_ids[target],
                "link_type_id": link_type_id,
                "source_project_id": None,
                "target_project_id": None,
                "created_by": author,
                "created_at": at,
                "updated_at": at,
            }
        )
        audit.add(
            "requirement_link",
            link_id,
            "created",
            author,
            at,
            detail={
                "source_requirement_id": str(requirement_ids[source]),
                "target_requirement_id": str(requirement_ids[target]),
                "link_type_id": str(link_type_id),
            },
        )
    for value in degree:
        key = _bucket(value)
        ctx.histogram[key] = ctx.histogram.get(key, 0) + 1
    ctx.histogram["max"] = max(degree)
    ctx.histogram["links"] = len(seen)
    ctx.shared["hubs"] = [requirement_ids[i] for i in sorted(range(n), key=lambda i: -degree[i])[:3]]

    parent_ids = (ctx.parent_shared or {}).get("requirement")
    cross_types = [t for t in usable if t[1] == "ancestor_either_way"]
    if parent_ids and cross_types and ctx.project.parent_id:
        cross = round(len(seen) * spec.ratios.cross_level_link_fraction)
        for _ in range(cross):
            source = rng.randrange(n)
            target = rng.choice(parent_ids)
            link_type_id, _scope = rng.choice(cross_types)
            at = _at(rng, created[source], ANCHOR)
            link_id = uuid_from(rng)
            author = rng.choice(ctx.user_ids)
            rows.append(
                {
                    "id": link_id,
                    "source_type": ArtefactType.REQUIREMENT.value,
                    "source_id": requirement_ids[source],
                    "target_type": ArtefactType.REQUIREMENT.value,
                    "target_id": target,
                    "link_type_id": link_type_id,
                    "source_project_id": ctx.project_uuid,
                    "target_project_id": uuid.UUID(ctx.project.parent_id),
                    "created_by": author,
                    "created_at": at,
                    "updated_at": at,
                }
            )
        ctx.histogram["cross_level_links"] = cross
    ctx.add_count("artefact_links", insert_rows(ctx.db, ArtefactLink, rows))


def generate_actions(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's actions, each linked to one to three requirements, with audit events.

    Needs `ctx.shared["requirement"]` from `generate_requirements`. Advances `Project.next_action_seq`.

    Args:
        ctx: The project's context.

    Returns:
        Rows written by table name.
    """
    rng, db = ctx.rng, ctx.db
    requirement_ids = ctx.shared.get("requirement", [])
    total = round(len(requirement_ids) * ctx.spec.ratios.actions)
    if total == 0 or not ctx.action_type_ids:
        return {}
    start_counts = dict(ctx.counts)
    audit = AuditBuffer(ctx)
    org_id = ctx.organization_uuid
    actions, links = [], []
    for index in range(total):
        action_id = uuid_from(rng)
        creator = rng.choice(ctx.user_ids)
        created = ANCHOR - timedelta(days=rng.uniform(1, 400))
        outcome = _weighted(rng, _OUTCOME_MIX)
        done = outcome is not RequirementActionOutcome.PENDING
        assignee = rng.choice(ctx.user_ids) if rng.random() < 0.7 else None
        title = textgen.title(rng)
        actions.append(
            {
                "id": action_id,
                "project_id": ctx.project_uuid,
                "unique_code": f"ACT-{index + 1:03d}",
                "action_type_id": rng.choice(ctx.action_type_ids),
                "title": title,
                "description": textgen.paragraphs(rng, empty_chance=0.3, short_max=3),
                "outcome_status": outcome,
                "assignee_type": PrincipalType.USER.value if assignee else None,
                "assignee_id": assignee,
                "due_date": date(2026, 1, 1) + timedelta(days=rng.randrange(0, 600)) if rng.random() < 0.6 else None,
                "completed_at": created + timedelta(days=10) if done else None,
                "completed_by": assignee or creator if done else None,
                "creator_id": creator,
                "is_archived": False,
                "archived_at": None,
                "archived_by": None,
                "created_at": created,
                "updated_at": created,
            }
        )
        audit.add(
            "requirement_action",
            action_id,
            "created",
            creator,
            created,
            organization_id=org_id,
            detail={"unique_code": f"ACT-{index + 1:03d}", "title": title},
        )
        for requirement_id in rng.sample(requirement_ids, min(rng.randint(1, 3), len(requirement_ids))):
            links.append(
                {
                    "id": uuid_from(rng),
                    "source_type": ArtefactType.REQUIREMENT_ACTION.value,
                    "source_id": action_id,
                    "target_type": ArtefactType.REQUIREMENT.value,
                    "target_id": requirement_id,
                    "link_type_id": None,
                    "source_project_id": None,
                    "target_project_id": None,
                    "created_by": creator,
                    "created_at": created,
                    "updated_at": created,
                }
            )
    ctx.add_count("requirement_actions", insert_rows(db, RequirementAction, actions))
    ctx.add_count("artefact_links", insert_rows(db, ArtefactLink, links))
    audit.flush()
    db.query(Project).filter(Project.id == ctx.project_uuid).update({Project.next_action_seq: total + 1})
    return {table: ctx.counts.get(table, 0) - start_counts.get(table, 0) for table in ctx.counts}
