"""
Module: modules.stakeholders.perf_dataset

The dataset generators for the Stakeholders module's artefact types: personas, stakeholders (with influence and
interest levels), needs, stakeholder groups (a tree, with members), engagements (with facilitators, participants
and covered personas) and research findings.

Responsibilities:
- Write each type's identity and version rows, group membership, engagement facilitators, comments, tags,
  cross-type links (including the participant, covers, represents and has-need relationships the application reads
  by name) and audit events, and each type's project sequence counter.

Design decisions:
- Project-scoped records only: an organisation-scoped persona, stakeholder or group is shared across projects and
  belongs to no one project, so it is not part of a per-project dataset (a stated gap of the generator).
- Relationships the application reads by name (participants, represents, has need) are written with that link
  type, so "last engaged", the represented-persona list and a need's holders have real data to read.
- A finding belongs to one engagement of the project; findings are spread over the engagements, with a few
  engagements holding many.

Dependencies: `perf_dataset.records`, this module's models and enums, `services.scoring`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.modules.stakeholders.engagements import (
    COVERS_FORWARD,
    ENGAGEMENT_ARTEFACT_TYPE,
    ENGAGEMENT_CODE_PREFIX,
    FINDING_ARTEFACT_TYPE,
    FINDING_CODE_PREFIX,
    PARTICIPANT_FORWARD,
)
from app.modules.stakeholders.enums import (
    EngagementChannel,
    NeedStatus,
    PersonaStatus,
    StakeholderScope,
    StakeholderStatus,
    TargetCadence,
)
from app.modules.stakeholders.groups import GROUP_ARTEFACT_TYPE, GROUP_CODE_PREFIX
from app.modules.stakeholders.models import (
    Engagement,
    EngagementComment,
    EngagementFacilitator,
    Persona,
    PersonaComment,
    PersonaTypeDefinition,
    PersonaVersion,
    ProjectPersonaType,
    ProjectStakeholderType,
    ResearchFinding,
    Stakeholder,
    StakeholderComment,
    StakeholderGroup,
    StakeholderGroupMember,
    StakeholderNeed,
    StakeholderNeedComment,
    StakeholderNeedVersion,
    StakeholderTypeDefinition,
    StakeholderVersion,
)
from app.modules.stakeholders.scoring import INFLUENCE_AXIS_KEY, INTEREST_AXIS_KEY, STAKEHOLDER_SCORING_SCHEME_KEY
from app.modules.stakeholders.service import (
    HAS_NEED_FORWARD,
    NEED_ARTEFACT_TYPE,
    NEED_CODE_PREFIX,
    PERSONA_ARTEFACT_TYPE,
    PERSONA_CODE_PREFIX,
    REPRESENTS_FORWARD,
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_CODE_PREFIX,
)
from app.services.perf_dataset import textgen
from app.services.perf_dataset.context import PerfProjectContext, insert_rows, uuid_from
from app.services.perf_dataset.core import extra_versions
from app.services.perf_dataset.records import (
    Partner,
    RecordBatch,
    add_comments,
    add_tags,
    at_between,
    created_at,
    link_to_earlier,
    pick_weighted,
    project_type_ids,
)
from app.services.scoring import list_levels

_LIFECYCLE_MIX = (("draft", 0.2), ("active", 0.7), ("retired", 0.1))


def _delta(ctx: PerfProjectContext, start: dict[str, int]) -> dict[str, int]:
    return {table: ctx.counts.get(table, 0) - start.get(table, 0) for table in ctx.counts}


def _versioned(
    ctx: PerfProjectContext, *, artefact_type: str, prefix: str, identity: Any, version_model: Any, fk: str,
    comment_model: Any, status_enum: Any, project_scope: bool, content: Any, partners: Any,
) -> dict[str, int]:
    """Shared body of the versioned types (persona, stakeholder, need). `content(rng, n)` returns the version's
    columns and a display title."""
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(artefact_type, len(ctx.shared.get("requirement", [])))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, artefact_type, prefix, identity)
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        final = status_enum(pick_weighted(rng, _LIFECYCLE_MIX))
        archived = rng.random() < 0.03
        record_id = batch.new_id()
        _columns, title = content(rng, 1)
        row = {"id": record_id, "is_archived": archived, "archived_at": created + timedelta(days=90) if archived else None,
               "archived_by": creator if archived else None}
        if project_scope:
            row.update({"scope": StakeholderScope.PROJECT, "organization_id": None})
        batch.add(row, creator=creator, at=created, title=title)
        extra = extra_versions(rng, ctx.spec.ratios.versions_per_requirement)
        valid_from = created
        for number in range(1, extra + 2):
            last = number == extra + 1
            author = creator if number == 1 else rng.choice(ctx.user_ids)
            next_from = valid_from + timedelta(hours=rng.uniform(1, 24 * 30))
            columns, _title = content(rng, number)
            if number > 1:
                batch.audit_event(record_id, "updated", author, valid_from, {"change_note": "Reworded."})
            batch.satellite(version_model, {
                "id": batch.new_id(), fk: record_id, "version_number": number, "valid_from": valid_from,
                "valid_to": None if last else next_from, **columns, "status": final if last else status_enum("draft"),
                "change_note": "Initial creation." if number == 1 else "Reworded.", "created_by": author, "created_at": valid_from,
            })
            valid_from = next_from
    batch.write()
    add_comments(ctx, batch, comment_model, fk)
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, partners)
    return _delta(ctx, start)


def generate_personas(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's personas."""
    type_ids = project_type_ids(ctx, ProjectPersonaType, PersonaTypeDefinition)

    def content(rng, number):
        name = textgen.title(rng)
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.6 else None
        return {
            "name": name, "description": textgen.paragraphs(rng, empty_chance=0.1, short_max=3),
            "org_type_id": None, "project_type_id": rng.choice(type_ids) if type_ids and rng.random() < 0.8 else None,
            "role_title": textgen.title(rng)[:60], "goals": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
            "needs": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
            "behaviours": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
            "context_environment": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
            "skills_proficiency": textgen.sentences(rng, 1), "frequency_of_use": rng.choice(("daily", "weekly", "monthly")),
            "constraints": textgen.paragraphs(rng, empty_chance=0.4, short_max=2), "weight": rng.choice((1, 2, 3, 5, 8)),
            "owner_type": "user" if owner else None, "owner_id": owner, "champion_type": None, "champion_id": None,
        }, name

    return _versioned(
        ctx, artefact_type=PERSONA_ARTEFACT_TYPE, prefix=PERSONA_CODE_PREFIX, identity=Persona, version_model=PersonaVersion,
        fk="persona_id", comment_model=PersonaComment, status_enum=PersonaStatus, project_scope=True, content=content,
        partners=[("requirement", 0.6), ("decision", 0.4)],
    )


def generate_stakeholders(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's stakeholders, with influence and interest levels and the personas they represent."""
    type_ids = project_type_ids(ctx, ProjectStakeholderType, StakeholderTypeDefinition)
    levels = list_levels(ctx.db, ctx.organization_uuid, STAKEHOLDER_SCORING_SCHEME_KEY)
    influence = [lv.id for lv in levels.get(INFLUENCE_AXIS_KEY, [])]
    interest = [lv.id for lv in levels.get(INTEREST_AXIS_KEY, [])]

    def content(rng, number):
        name = textgen.title(rng)
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.5 else None
        return {
            "name": name, "description": textgen.paragraphs(rng, empty_chance=0.2, short_max=2),
            "org_type_id": None, "project_type_id": rng.choice(type_ids) if type_ids and rng.random() < 0.8 else None,
            "role": textgen.title(rng)[:60], "organisation_group": textgen.title(rng)[:60],
            "interests": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
            "responsibilities": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
            "goals_needs": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
            "priorities": textgen.paragraphs(rng, empty_chance=0.4, short_max=1),
            "constraints": textgen.paragraphs(rng, empty_chance=0.5, short_max=1),
            "workflows_scenarios": textgen.paragraphs(rng, empty_chance=0.5, short_max=2),
            "contact_info": "", "target_cadence": rng.choice(list(TargetCadence)) if rng.random() < 0.7 else None,
            "availability_constraints": "", "influence_level_id": rng.choice(influence) if influence and rng.random() < 0.8 else None,
            "interest_level_id": rng.choice(interest) if interest and rng.random() < 0.8 else None,
            "owner_type": "user" if owner else None, "owner_id": owner, "user_id": None,
        }, name

    return _versioned(
        ctx, artefact_type=STAKEHOLDER_ARTEFACT_TYPE, prefix=STAKEHOLDER_CODE_PREFIX, identity=Stakeholder,
        version_model=StakeholderVersion, fk="stakeholder_id", comment_model=StakeholderComment,
        status_enum=StakeholderStatus, project_scope=True, content=content,
        partners=[Partner(PERSONA_ARTEFACT_TYPE, 0.5, forward_name=REPRESENTS_FORWARD), ("requirement", 0.5)],
    )


def generate_needs(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's stakeholder needs, held by stakeholders and personas."""

    def content(rng, number):
        name = textgen.title(rng)
        owner = rng.choice(ctx.user_ids) if rng.random() < 0.5 else None
        return {
            "name": name, "description": textgen.paragraphs(rng, empty_chance=0.1, short_max=3),
            "rationale": textgen.paragraphs(rng, empty_chance=0.3, short_max=2),
            "owner_type": "user" if owner else None, "owner_id": owner,
        }, name

    return _versioned(
        ctx, artefact_type=NEED_ARTEFACT_TYPE, prefix=NEED_CODE_PREFIX, identity=StakeholderNeed,
        version_model=StakeholderNeedVersion, fk="need_id", comment_model=StakeholderNeedComment, status_enum=NeedStatus,
        project_scope=False, content=content,
        partners=[
            Partner(STAKEHOLDER_ARTEFACT_TYPE, 0.35, forward_name=HAS_NEED_FORWARD, record_is_target=True),
            Partner(PERSONA_ARTEFACT_TYPE, 0.15, forward_name=HAS_NEED_FORWARD, record_is_target=True),
            ("requirement", 0.5),
        ],
    )


def generate_groups(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's stakeholder groups as a shallow tree, with stakeholders as members."""
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(GROUP_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, GROUP_ARTEFACT_TYPE, GROUP_CODE_PREFIX, StakeholderGroup, has_creator=False)
    depth: dict = {}
    for index in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        name = textgen.title(rng)[:80]
        parents = [i for i in batch.ids if depth[i] < 3]
        parent = rng.choice(parents) if parents and rng.random() < 0.6 else None
        record_id = batch.new_id()
        depth[record_id] = depth[parent] + 1 if parent else 1
        batch.add(
            {"id": record_id, "scope": StakeholderScope.PROJECT, "organization_id": None, "parent_group_id": parent, "name": name,
             "description": textgen.paragraphs(rng, empty_chance=0.3, short_max=2), "exclusive_children": rng.random() < 0.2,
             "sort_order": index},
            creator=creator, at=created, title=name,
        )
    members = []
    stakeholders = ctx.shared.get(STAKEHOLDER_ARTEFACT_TYPE, [])
    seen = set()
    for stakeholder_id in stakeholders:
        for group_id in rng.sample(batch.ids, min(rng.choice((0, 1, 1, 2)), len(batch.ids))):
            if (group_id, stakeholder_id) in seen:
                continue
            seen.add((group_id, stakeholder_id))
            members.append({"id": uuid_from(rng), "group_id": group_id, "stakeholder_id": stakeholder_id, "created_at": created_at(rng)})
    batch.write()
    ctx.add_count("stakeholder_group_members", insert_rows(ctx.db, StakeholderGroupMember, members))
    add_tags(ctx, batch)
    return _delta(ctx, start)


def generate_engagements(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's engagements with facilitators, participants and the personas they cover."""
    rng = ctx.rng
    count = ctx.spec.ratios.count_for(ENGAGEMENT_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    if count == 0:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, ENGAGEMENT_ARTEFACT_TYPE, ENGAGEMENT_CODE_PREFIX, Engagement)
    facilitators = []
    for _ in range(count):
        creator, created = rng.choice(ctx.user_ids), created_at(rng)
        title = textgen.title(rng)
        record_id = batch.new_id()
        held = (created + timedelta(days=rng.randint(0, 14))).date()
        batch.add(
            {"id": record_id, "title": title, "channel": rng.choice(list(EngagementChannel)), "engagement_date": held,
             "purpose": textgen.sentences(rng, 1), "summary": textgen.paragraphs(rng, empty_chance=0.2, short_max=3),
             "notes": textgen.paragraphs(rng, empty_chance=0.4, short_max=3), "consent_recorded": rng.random() < 0.7,
             "retain_until": held + timedelta(days=730) if rng.random() < 0.5 else None},
            creator=creator, at=created, title=title,
        )
        for position, person in enumerate(rng.sample(ctx.user_ids, min(rng.choice((1, 1, 2)), len(ctx.user_ids)))):
            facilitators.append({
                "id": uuid_from(rng), "engagement_id": record_id, "sort_order": position, "facilitator_type": "user",
                "facilitator_id": person, "created_at": created, "updated_at": created,
            })
    batch.write()
    ctx.add_count("engagement_facilitators", insert_rows(ctx.db, EngagementFacilitator, facilitators))
    add_comments(ctx, batch, EngagementComment, "engagement_id")
    add_tags(ctx, batch)
    link_to_earlier(
        ctx, batch,
        [Partner(STAKEHOLDER_ARTEFACT_TYPE, 0.6, forward_name=PARTICIPANT_FORWARD),
         Partner(PERSONA_ARTEFACT_TYPE, 0.2, forward_name=COVERS_FORWARD), ("requirement", 0.2)],
    )
    return _delta(ctx, start)


def generate_findings(ctx: PerfProjectContext) -> dict[str, int]:
    """Writes the project's research findings, a few engagements holding most of them."""
    rng = ctx.rng
    engagements = ctx.shared.get(ENGAGEMENT_ARTEFACT_TYPE, [])
    count = ctx.spec.ratios.count_for(FINDING_ARTEFACT_TYPE, len(ctx.shared.get("requirement", [])))
    if count == 0 or not engagements:
        return {}
    start = dict(ctx.counts)
    batch = RecordBatch.start(ctx, FINDING_ARTEFACT_TYPE, FINDING_CODE_PREFIX, ResearchFinding)
    engagement_times = ctx.created_times[ENGAGEMENT_ARTEFACT_TYPE]
    weights = [1 / ((i + 1) ** 0.6) for i in range(len(engagements))]
    for _ in range(count):
        index = rng.choices(range(len(engagements)), weights=weights)[0]
        creator, created = rng.choice(ctx.user_ids), at_between(rng, engagement_times[index])
        title = textgen.title(rng)
        batch.add(
            {"engagement_id": engagements[index], "title": title, "description": textgen.paragraphs(rng, empty_chance=0.1, short_max=3)},
            creator=creator, at=created, title=title,
        )
    batch.write()
    add_tags(ctx, batch)
    link_to_earlier(ctx, batch, [("requirement", 0.5), (NEED_ARTEFACT_TYPE, 0.3), ("pain_point", 0.2)])
    return _delta(ctx, start)
