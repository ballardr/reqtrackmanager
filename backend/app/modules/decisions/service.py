"""
Module: modules.decisions.service

Seeding logic for Decision Management's two definition tables:

- `seed_decision_types` — the project-scoped `DecisionTypeDefinition`
  defaults, called unconditionally from `on_project_created`
  (`module.py`), mirroring `services.definitions.seed_action_types`'s
  identical shape.
- `seed_decision_templates` — the org-scoped `DecisionTemplateDefinition`
  seeded ADR template packs, called from `on_org_created_with_choices`
  (`module.py`) with whichever pack keys the caller selected on the
  org-creation form (Phase 0 addendum Q1 — opt-in, not unconditional).

`DECISION_TEMPLATE_PACKS` holds the three seeded packs' content (Phase 0
addendum Q7): Nygard (the original, minimal ADR format), MADR (Markdown
Architectural Decision Records, the fuller format), and Y-Statement (the
compressed single-sentence form). Each pack's prompt text is guidance
shown to a user filling in a new Decision from that template (Phase 5) —
not validation, not enforced structure.

Phase 2 (docs/plans/module-04-decision-management-plan.md) adds the
approval/rejection/supersession workflow, entirely at this service layer —
no router exists until Phase 4, and per that plan's Phase 0 addendum item 8
supersession is deliberately built now rather than deferred to Phase 3:

- `propose_decision` / `submit_decision_for_review` / `approve_decision` /
  `reject_decision` — the `DecisionStatus` transitions
  (`DRAFT -> PROPOSED -> UNDER_REVIEW -> APPROVED`, with `REJECTED`
  reachable from `PROPOSED`/`UNDER_REVIEW`), each validated against
  `_ALLOWED_TRANSITIONS` and recorded via `services.audit.log_event`
  (Phase 0 activity 3 — reusing the audit-log pattern rather than a
  bespoke approval-history table), mirroring `services.stages.
  complete_stage`'s shape: a plain service function that mutates status and
  writes the audit event in one call, without committing (the eventual
  Phase 4 router owns the transaction, same as every other service
  function in this codebase).
- `create_supersession` — creates the typed `ArtefactLink` (Module 0's
  polymorphic relationship model, `services.relationships.create_link`)
  recording that one Decision supersedes another, using a `"Supersedes"` /
  `"Is superseded by"` `RequirementLinkTypeDefinition` row this module
  fetches-or-creates on demand for the owning organisation (that table is
  already a generic, org-shared vocabulary — see its own module docstring
  — so this is an ordinary consumer of an existing extension point, not a
  new core mechanism; no `DEFAULT_LINK_TYPES` core-file edit or migration
  backfill is needed since it's created lazily, the first time any Decision
  in that organisation is actually superseded).
- Per Phase 0 addendum item 8, the *old* Decision's status only flips to
  `SUPERSEDED` once the supersession link exists **and** the *new* Decision
  itself reaches `APPROVED` — not before, and not automatically for a
  predecessor that isn't currently `APPROVED` (e.g. one already `REJECTED`
  or itself `SUPERSEDED`). This condition is checked from both directions
  it can become true: `create_supersession` (the link is created after the
  new Decision is already approved) and `approve_decision` (the new
  Decision is approved after the link already exists) — see `_maybe_
  supersede`/`_supersede_predecessors`.
- Content-field immutability once a Decision reaches `APPROVED`/
  `SUPERSEDED` (source overview §13/10.6) is deliberately **not** enforced
  here — every existing lock-after-approval check in this codebase
  (`services.requirements.is_locked`'s call sites) lives at the router
  layer, and no Decision router/update endpoint exists until Phase 4. It
  belongs there, not in this phase.

Phase 3 (docs/plans/module-04-decision-management-plan.md) adds the two
buildable-now relationship groups, both plain `ArtefactLink` (Module 0)
consumers using the same lazy fetch-or-create `RequirementLinkTypeDefinition`
pattern `create_supersession` already established — generalised here into
`_get_or_create_link_type` rather than duplicated four more times:

- `create_decision_requirement_link` — Decision -> Requirement, either
  `"Implements"` or `"Affects"` (source overview §13/10.7).
- `create_decision_decision_link` — Decision -> Decision, either
  `"Depends on"` or `"Conflicts with"` (`"Supersedes"` already has its own
  dedicated `create_supersession`, above, because it also drives the
  status-flip side effect these two plain relationships don't have).

The five other relationship targets in the plan's Phase 3 scope (Open
Question, Pain Point, Strategy, Guiding Principle, Compliance, Design) are
reserved but deferred to Phase 6, blocked on modules that don't exist yet —
deliberately not built here.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ArtefactType
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import Decision, DecisionTemplateDefinition, DecisionTypeDefinition
from app.services.audit import log_event
from app.services.relationships import create_link, get_link_between, get_links_from

# Source overview §13/10.2's default list, seeded per new project — a
# project's own admin may add/rename/reorder/remove from there.
DEFAULT_DECISION_TYPES: list[str] = ["Architecture", "Design", "Engineering", "Strategy", "Operational"]

# This module's own artefact-type string, registered on `ModuleDefinition.
# artefact_types` (module.py) — used today only by `services.sequences.
# generate_unique_code` for `Decision.unique_code`; Phase 3 will also use it
# for Decision<->Requirement/Decision<->Decision artefact links.
DECISION_ARTEFACT_TYPE = "decision"

# This module's own key prefix for `OrgCreationChoiceOption.key` /
# `run_on_org_created_hooks`'s `selected_choice_keys` — namespaced so a
# future module's own choice keys can never collide with these.
_CHOICE_KEY_PREFIX = "decisions:"


@dataclass(frozen=True)
class DecisionTemplatePack:
    """One seeded `DecisionTemplateDefinition`'s content, keyed for the
    org-creation choice picker (`module.py`'s `org_creation_choices`)."""

    choice_key: str
    name: str
    description: str
    context_prompt: str | None
    options_considered_prompt: str | None
    chosen_option_prompt: str | None
    rationale_prompt: str | None
    consequences_prompt: str | None
    assumptions_prompt: str | None
    constraints_prompt: str | None


DECISION_TEMPLATE_PACKS: tuple[DecisionTemplatePack, ...] = (
    DecisionTemplatePack(
        choice_key=f"{_CHOICE_KEY_PREFIX}adr_nygard",
        name="Nygard (Classic ADR)",
        description="Michael Nygard's original, minimal ADR format — Context, Decision, Consequences.",
        context_prompt=(
            "What is the issue that we're seeing that is motivating this decision or change? State the "
            "facts, forces, and constraints as if explaining them to someone new to the project."
        ),
        options_considered_prompt=(
            "Optional under this format — Nygard's original template has no separate \"options considered\" "
            "section. Leave blank, or list alternatives here if useful."
        ),
        chosen_option_prompt="What is the change that we're actually proposing or have agreed to?",
        rationale_prompt=(
            "Optional under this format — Nygard folds rationale into the decision statement itself rather "
            "than a separate section."
        ),
        consequences_prompt=(
            "What becomes easier or more difficult to do because of this change? List all consequences, "
            "not just the ones that favour the decision."
        ),
        assumptions_prompt=None,
        constraints_prompt=None,
    ),
    DecisionTemplatePack(
        choice_key=f"{_CHOICE_KEY_PREFIX}adr_madr",
        name="MADR (Markdown Architectural Decision Records)",
        description="The fuller ADR format — decision drivers, considered options, and pros/cons.",
        context_prompt=(
            "Describe the context and problem statement, e.g. in free form using two to three sentences, "
            "or as an illustrative story. You may want to phrase the problem as a question."
        ),
        options_considered_prompt='List the options considered, e.g. "Option 1: Title", "Option 2: Title".',
        chosen_option_prompt=(
            'State the chosen option, e.g. "Option 2, because it resolves force X while satisfying quality '
            'attribute Y at an acceptable cost."'
        ),
        rationale_prompt=(
            "What decision drivers led to this choice? E.g. a force, concern, requirement, or "
            "non-functional need each option was evaluated against."
        ),
        consequences_prompt="List the consequences: Good, because ...; Bad, because ...; and any neutral ones.",
        assumptions_prompt="State any assumptions this decision relies on.",
        constraints_prompt="State any constraints (technical, organisational, regulatory) that bounded the options.",
    ),
    DecisionTemplatePack(
        choice_key=f"{_CHOICE_KEY_PREFIX}adr_y_statement",
        name="Y-Statement",
        description="The compressed, single-sentence ADR form.",
        context_prompt="Describe the use case or user story this decision addresses, and the concern/quality it must satisfy.",
        options_considered_prompt="List the option(s) considered as alternatives to the chosen one.",
        chosen_option_prompt=(
            'Complete the Y-statement: "In the context of <use case/user story>, facing <concern>, we '
            'decided for <option> to achieve <quality>, accepting <downside>."'
        ),
        rationale_prompt="Why does the chosen option achieve the target quality better than the alternatives?",
        consequences_prompt="What downside(s) are being accepted in exchange for the chosen quality attribute?",
        assumptions_prompt=None,
        constraints_prompt=None,
    ),
)


def seed_decision_types(db: Session, project_id: uuid.UUID) -> None:
    """Adds the 5 default `DecisionTypeDefinition` rows for a newly
    created project (not committed/flushed — caller owns the transaction).
    Mirrors `services.definitions.seed_action_types`'s identical shape."""
    for i, name in enumerate(DEFAULT_DECISION_TYPES):
        db.add(DecisionTypeDefinition(project_id=project_id, name=name, sort_order=i))


def seed_decision_templates(db: Session, organization_id: uuid.UUID, selected_keys: frozenset[str]) -> None:
    """Adds one `DecisionTemplateDefinition` row per selected pack in
    `DECISION_TEMPLATE_PACKS` (not committed/flushed — caller owns the
    transaction) — this module's `ModuleDefinition.on_org_created_with_
    choices` hook. Packs whose `choice_key` isn't in `selected_keys` are
    skipped entirely (Phase 0 addendum Q1 — opt-in, not unconditional).

    Guards against re-seeding a pack the organisation already has a
    same-named template for (belt-and-braces: `on_org_created_with_choices`
    is only ever called once per organisation today, at creation, but a
    duplicate-name insert would otherwise violate this table's
    `UniqueConstraint("organization_id", "name")` if it ever were).
    """
    packs_to_seed = [pack for pack in DECISION_TEMPLATE_PACKS if pack.choice_key in selected_keys]
    if not packs_to_seed:
        return
    existing_names = set(
        db.scalars(
            select(DecisionTemplateDefinition.name).where(DecisionTemplateDefinition.organization_id == organization_id)
        )
    )
    next_sort_order = len(existing_names)
    for pack in packs_to_seed:
        if pack.name in existing_names:
            continue
        db.add(
            DecisionTemplateDefinition(
                organization_id=organization_id,
                name=pack.name,
                description=pack.description,
                context_prompt=pack.context_prompt,
                options_considered_prompt=pack.options_considered_prompt,
                chosen_option_prompt=pack.chosen_option_prompt,
                rationale_prompt=pack.rationale_prompt,
                consequences_prompt=pack.consequences_prompt,
                assumptions_prompt=pack.assumptions_prompt,
                constraints_prompt=pack.constraints_prompt,
                sort_order=next_sort_order,
            )
        )
        next_sort_order += 1


# --- Phase 2: approval, rejection, and supersession workflow --------------

# Legal `DecisionStatus` transitions (Phase 0 addendum Q1/Q4, `enums.
# DecisionStatus`'s own docstring): forward through the four "in-flight"
# states, `REJECTED` reachable from either `PROPOSED` or `UNDER_REVIEW`,
# `SUPERSEDED` reachable only from `APPROVED` and only via `_maybe_
# supersede`/`_supersede_predecessors` below, never a direct caller choice.
_ALLOWED_TRANSITIONS: dict[DecisionStatus, frozenset[DecisionStatus]] = {
    DecisionStatus.DRAFT: frozenset({DecisionStatus.PROPOSED}),
    DecisionStatus.PROPOSED: frozenset({DecisionStatus.UNDER_REVIEW, DecisionStatus.REJECTED}),
    DecisionStatus.UNDER_REVIEW: frozenset({DecisionStatus.APPROVED, DecisionStatus.REJECTED}),
    DecisionStatus.APPROVED: frozenset({DecisionStatus.SUPERSEDED}),
    DecisionStatus.REJECTED: frozenset(),
    DecisionStatus.SUPERSEDED: frozenset(),
}

# This module's own `RequirementLinkTypeDefinition` name for the typed
# supersession link `create_supersession` creates/reuses — see module
# docstring for why that (already generic, org-shared) table is the right
# extension point rather than a new mechanism.
SUPERSEDES_LINK_TYPE_FORWARD_NAME = "Supersedes"
SUPERSEDES_LINK_TYPE_REVERSE_NAME = "Is superseded by"


def _transition_status(
    db: Session, decision: Decision, new_status: DecisionStatus, actor_id: uuid.UUID, *,
    action: str, comment: str | None = None,
) -> Decision:
    """Validates and applies a `Decision.status` transition, then records it
    via `services.audit.log_event` (not committed — caller's transaction).

    Raises:
        ValueError: if `new_status` isn't reachable from `decision.status`
            per `_ALLOWED_TRANSITIONS` — mirrors `services.relationships.
            create_link`'s own convention of a plain `ValueError` for a
            service-layer validation failure, for the eventual Phase 4
            router to translate into an HTTP 409.
    """
    if new_status not in _ALLOWED_TRANSITIONS[decision.status]:
        raise ValueError(f"Cannot move a Decision from '{decision.status.value}' to '{new_status.value}'.")
    decision.status = new_status
    log_event(
        db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action=action,
        actor_id=actor_id, project_id=decision.project_id,
        detail={"comment": comment} if comment else None,
    )
    db.flush()
    return decision


def propose_decision(db: Session, decision: Decision, actor_id: uuid.UUID) -> Decision:
    """`DRAFT` -> `PROPOSED`: the decision is ready for others to review."""
    return _transition_status(db, decision, DecisionStatus.PROPOSED, actor_id, action="proposed")


def submit_decision_for_review(db: Session, decision: Decision, actor_id: uuid.UUID) -> Decision:
    """`PROPOSED` -> `UNDER_REVIEW`: formal review/approval has started."""
    return _transition_status(db, decision, DecisionStatus.UNDER_REVIEW, actor_id, action="submitted_for_review")


def reject_decision(db: Session, decision: Decision, actor_id: uuid.UUID, *, comment: str | None = None) -> Decision:
    """`PROPOSED`/`UNDER_REVIEW` -> `REJECTED`. Rejected Decisions remain
    queryable (source overview §13/10.6) — never hard-deleted, same as
    every other soft-delete convention in this codebase; this is a status
    value, not an archive."""
    return _transition_status(db, decision, DecisionStatus.REJECTED, actor_id, action="rejected", comment=comment)


def approve_decision(db: Session, decision: Decision, actor_id: uuid.UUID, *, comment: str | None = None) -> Decision:
    """`UNDER_REVIEW` -> `APPROVED`. Also flips any predecessor Decision
    this one already supersedes (a `create_supersession` link created
    before this approval) to `SUPERSEDED`, per Phase 0 addendum item 8 —
    see `_supersede_predecessors`."""
    _transition_status(db, decision, DecisionStatus.APPROVED, actor_id, action="approved", comment=comment)
    _supersede_predecessors(db, decision, actor_id)
    return decision


def _project_organization_id(db: Session, project_id: uuid.UUID) -> uuid.UUID:
    """Resolves a project's owning organisation — needed because
    `RequirementLinkTypeDefinition` (the supersession link type's home
    table) is org-scoped while `Decision` is project-scoped."""
    organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    if organization_id is None:
        raise ValueError(f"Project {project_id} not found.")
    return organization_id


def _get_or_create_link_type(
    db: Session, organization_id: uuid.UUID, *, forward_name: str, reverse_name: str
) -> RequirementLinkTypeDefinition:
    """Returns this organisation's link type identified by `forward_name`,
    creating it on first use (see module docstring — deliberately lazy, no
    core-file default-list edit or migration backfill needed). Generalised
    from `create_supersession`'s original single-purpose helper so Phase 3's
    Implements/Affects/Depends-on/Conflicts-with links reuse the exact same
    fetch-or-create logic rather than duplicating it four more times —
    `RequirementLinkTypeDefinition` is already a generic, org-shared
    vocabulary table (see its own module docstring), not something to grow a
    dedicated helper per link type."""
    link_type = db.scalar(
        select(RequirementLinkTypeDefinition).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == forward_name,
        )
    )
    if link_type is not None:
        return link_type
    next_sort_order = db.scalar(
        select(func.count())
        .select_from(RequirementLinkTypeDefinition)
        .where(RequirementLinkTypeDefinition.organization_id == organization_id)
    )
    link_type = RequirementLinkTypeDefinition(
        organization_id=organization_id,
        forward_name=forward_name,
        reverse_name=reverse_name,
        sort_order=next_sort_order,
    )
    db.add(link_type)
    db.flush()
    return link_type


def _maybe_supersede(db: Session, *, new_decision: Decision, old_decision: Decision, actor_id: uuid.UUID) -> None:
    """Flips `old_decision` to `SUPERSEDED` if both halves of Phase 0
    addendum item 8's condition are already true at this exact moment: the
    supersession link exists (implied — this is only ever called once it
    does) and `new_decision` is already `APPROVED`. A no-op otherwise
    (including if `old_decision` isn't currently `APPROVED` — superseding
    only ever overwrites a previously-approved decision's status, never a
    `DRAFT`/`REJECTED`/already-`SUPERSEDED` one)."""
    if new_decision.status == DecisionStatus.APPROVED and old_decision.status == DecisionStatus.APPROVED:
        old_decision.status = DecisionStatus.SUPERSEDED
        log_event(
            db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=old_decision.id, action="superseded",
            actor_id=actor_id, project_id=old_decision.project_id,
            detail={"superseded_by_decision_id": str(new_decision.id)},
        )
        db.flush()


def _supersede_predecessors(db: Session, decision: Decision, actor_id: uuid.UUID) -> None:
    """Called once `decision` itself reaches `APPROVED` (from
    `approve_decision`): flips every still-`APPROVED` Decision it already
    supersedes (an outgoing `"Supersedes"`-typed link created earlier, back
    when this Decision wasn't approved yet) to `SUPERSEDED` — the other
    direction of Phase 0 addendum item 8's condition than `_maybe_
    supersede` handles."""
    organization_id = _project_organization_id(db, decision.project_id)
    link_type = db.scalar(
        select(RequirementLinkTypeDefinition).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == SUPERSEDES_LINK_TYPE_FORWARD_NAME,
        )
    )
    if link_type is None:
        return  # No Decision in this organisation has ever been superseded yet.
    predecessor_ids = {
        link.target_id
        for link in get_links_from(db, DECISION_ARTEFACT_TYPE, decision.id)
        if link.target_type == DECISION_ARTEFACT_TYPE and link.link_type_id == link_type.id
    }
    if not predecessor_ids:
        return
    predecessors = db.scalars(
        select(Decision).where(Decision.id.in_(predecessor_ids), Decision.status == DecisionStatus.APPROVED)
    ).all()
    for predecessor in predecessors:
        predecessor.status = DecisionStatus.SUPERSEDED
        log_event(
            db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=predecessor.id, action="superseded",
            actor_id=actor_id, project_id=predecessor.project_id,
            detail={"superseded_by_decision_id": str(decision.id)},
        )
    db.flush()


def create_supersession(db: Session, *, new_decision: Decision, old_decision: Decision, actor_id: uuid.UUID):
    """Records that `new_decision` supersedes `old_decision`: creates the
    typed `"Supersedes"` `ArtefactLink` (source overview §13/10.6), then
    immediately flips `old_decision` to `SUPERSEDED` if `new_decision` is
    already `APPROVED` (see `_maybe_supersede`) — otherwise the flip
    happens later, when/if `new_decision` itself reaches `APPROVED` via
    `approve_decision`.

    Args:
        db: Active session; not committed (caller's transaction).
        new_decision: The superseding Decision (the link's source).
        old_decision: The superseded Decision (the link's target).
        actor_id: The user recording this relationship.

    Returns:
        The created `ArtefactLink`.

    Raises:
        ValueError: if `new_decision`/`old_decision` are the same row, are
            in different projects (supersession is scoped to one project's
            Decision set, same as `DecisionTypeDefinition`), `old_decision`
            is already `SUPERSEDED`, or this exact supersession link
            already exists.
    """
    if new_decision.id == old_decision.id:
        raise ValueError("A Decision cannot supersede itself.")
    if new_decision.project_id != old_decision.project_id:
        raise ValueError("A Decision can only supersede another Decision in the same project.")
    if old_decision.status == DecisionStatus.SUPERSEDED:
        raise ValueError("This Decision has already been superseded.")

    organization_id = _project_organization_id(db, new_decision.project_id)
    link_type = _get_or_create_link_type(
        db, organization_id,
        forward_name=SUPERSEDES_LINK_TYPE_FORWARD_NAME, reverse_name=SUPERSEDES_LINK_TYPE_REVERSE_NAME,
    )

    if (
        get_link_between(
            db, source_type=DECISION_ARTEFACT_TYPE, source_id=new_decision.id,
            target_type=DECISION_ARTEFACT_TYPE, target_id=old_decision.id, link_type_id=link_type.id,
        )
        is not None
    ):
        raise ValueError("This Decision already supersedes that one.")

    link = create_link(
        db, source_type=DECISION_ARTEFACT_TYPE, source_id=new_decision.id,
        target_type=DECISION_ARTEFACT_TYPE, target_id=old_decision.id,
        link_type_id=link_type.id, created_by=actor_id,
    )
    _maybe_supersede(db, new_decision=new_decision, old_decision=old_decision, actor_id=actor_id)
    return link


# --- Phase 3: relationships to Requirements and other Decisions -----------

# Source overview §13/10.7's Decision<->Requirement relationship names.
# Both already exist in `services.definitions.DEFAULT_LINK_TYPES` except
# "Affects" — `_get_or_create_link_type` creates on miss regardless (an org
# admin may have renamed/deleted a seeded row, or the org may predate it).
IMPLEMENTS_LINK_TYPE_FORWARD_NAME = "Implements"
IMPLEMENTS_LINK_TYPE_REVERSE_NAME = "Is implemented by"
AFFECTS_LINK_TYPE_FORWARD_NAME = "Affects"
AFFECTS_LINK_TYPE_REVERSE_NAME = "Is affected by"

# Decision<->Decision relationship names other than "Supersedes" (which has
# its own dedicated `create_supersession`, above, for the status-flip side
# effect these two plain relationships don't have).
DEPENDS_ON_LINK_TYPE_FORWARD_NAME = "Depends on"
DEPENDS_ON_LINK_TYPE_REVERSE_NAME = "Is a dependency of"
CONFLICTS_WITH_LINK_TYPE_FORWARD_NAME = "Conflicts with"
CONFLICTS_WITH_LINK_TYPE_REVERSE_NAME = "Conflicts with"


class DecisionRequirementLinkKind(str, enum.Enum):
    """Which of source overview §13/10.7's two Decision -> Requirement
    relationship names `create_decision_requirement_link` should use."""

    IMPLEMENTS = "implements"
    AFFECTS = "affects"


_DECISION_REQUIREMENT_LINK_NAMES: dict[DecisionRequirementLinkKind, tuple[str, str]] = {
    DecisionRequirementLinkKind.IMPLEMENTS: (IMPLEMENTS_LINK_TYPE_FORWARD_NAME, IMPLEMENTS_LINK_TYPE_REVERSE_NAME),
    DecisionRequirementLinkKind.AFFECTS: (AFFECTS_LINK_TYPE_FORWARD_NAME, AFFECTS_LINK_TYPE_REVERSE_NAME),
}


class DecisionDecisionLinkKind(str, enum.Enum):
    """Which of the two plain (non-supersession) Decision -> Decision
    relationship names `create_decision_decision_link` should use."""

    DEPENDS_ON = "depends_on"
    CONFLICTS_WITH = "conflicts_with"


_DECISION_DECISION_LINK_NAMES: dict[DecisionDecisionLinkKind, tuple[str, str]] = {
    DecisionDecisionLinkKind.DEPENDS_ON: (DEPENDS_ON_LINK_TYPE_FORWARD_NAME, DEPENDS_ON_LINK_TYPE_REVERSE_NAME),
    DecisionDecisionLinkKind.CONFLICTS_WITH: (
        CONFLICTS_WITH_LINK_TYPE_FORWARD_NAME, CONFLICTS_WITH_LINK_TYPE_REVERSE_NAME,
    ),
}


def create_decision_requirement_link(
    db: Session, *, decision: Decision, requirement: Requirement, kind: DecisionRequirementLinkKind,
    actor_id: uuid.UUID,
) -> ArtefactLink:
    """Records that `decision` either `Implements` or `Affects`
    `requirement` (source overview §13/10.7): creates the typed
    `ArtefactLink`, with `decision` as the source, using the same lazy
    fetch-or-create `RequirementLinkTypeDefinition` pattern
    `create_supersession` established.

    Args:
        db: Active session; not committed (caller's transaction).
        decision: The linking Decision (the link's source).
        requirement: The target Requirement.
        kind: Which relationship name to use.
        actor_id: The user recording this relationship.

    Returns:
        The created `ArtefactLink`.

    Raises:
        ValueError: if `decision` and `requirement` are in different
            projects, or this exact link already exists.
    """
    if decision.project_id != requirement.project_id:
        raise ValueError("A Decision can only link to a Requirement in the same project.")

    organization_id = _project_organization_id(db, decision.project_id)
    forward_name, reverse_name = _DECISION_REQUIREMENT_LINK_NAMES[kind]
    link_type = _get_or_create_link_type(db, organization_id, forward_name=forward_name, reverse_name=reverse_name)

    if (
        get_link_between(
            db, source_type=DECISION_ARTEFACT_TYPE, source_id=decision.id,
            target_type=ArtefactType.REQUIREMENT.value, target_id=requirement.id, link_type_id=link_type.id,
        )
        is not None
    ):
        raise ValueError(f"This Decision already has a '{forward_name}' link to that Requirement.")

    return create_link(
        db, source_type=DECISION_ARTEFACT_TYPE, source_id=decision.id,
        target_type=ArtefactType.REQUIREMENT.value, target_id=requirement.id,
        link_type_id=link_type.id, created_by=actor_id,
    )


def create_decision_decision_link(
    db: Session, *, source_decision: Decision, target_decision: Decision, kind: DecisionDecisionLinkKind,
    actor_id: uuid.UUID,
) -> ArtefactLink:
    """Records a `Depends on` or `Conflicts with` relationship from
    `source_decision` to `target_decision` — the two plain Decision<->
    Decision relationships (`"Supersedes"` has its own dedicated
    `create_supersession`, above, for the status-flip side effect these two
    don't have).

    Args:
        db: Active session; not committed (caller's transaction).
        source_decision: The linking Decision (the link's source).
        target_decision: The target Decision.
        kind: Which relationship name to use.
        actor_id: The user recording this relationship.

    Returns:
        The created `ArtefactLink`.

    Raises:
        ValueError: if `source_decision`/`target_decision` are the same
            row, are in different projects, or this exact link already
            exists.
    """
    if source_decision.id == target_decision.id:
        raise ValueError("A Decision cannot link to itself.")
    if source_decision.project_id != target_decision.project_id:
        raise ValueError("A Decision can only link to another Decision in the same project.")

    organization_id = _project_organization_id(db, source_decision.project_id)
    forward_name, reverse_name = _DECISION_DECISION_LINK_NAMES[kind]
    link_type = _get_or_create_link_type(db, organization_id, forward_name=forward_name, reverse_name=reverse_name)

    if (
        get_link_between(
            db, source_type=DECISION_ARTEFACT_TYPE, source_id=source_decision.id,
            target_type=DECISION_ARTEFACT_TYPE, target_id=target_decision.id, link_type_id=link_type.id,
        )
        is not None
    ):
        raise ValueError(f"This Decision already has a '{forward_name}' link to that Decision.")

    return create_link(
        db, source_type=DECISION_ARTEFACT_TYPE, source_id=source_decision.id,
        target_type=DECISION_ARTEFACT_TYPE, target_id=target_decision.id,
        link_type_id=link_type.id, created_by=actor_id,
    )
