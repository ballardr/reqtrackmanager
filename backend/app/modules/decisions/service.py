"""
Module: modules.decisions.service

Service layer: seeding (`seed_decision_types`, `seed_decision_templates` with
the Nygard, MADR and Y-Statement packs), the audited, uncommitted status
workflow (`_ALLOWED_TRANSITIONS`) and relationships. Supersession links the old
Decision and flips it to `SUPERSEDED` only once the new one is `APPROVED`,
whichever happens last (`_maybe_supersede`). The content lock after approval
lives at the router layer; other modules' targets are not linked here.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ArtefactType, LinkFlow, LinkNestingScope, PermissionLevel
from app.models.project import Project
from app.models.relationship import ArtefactLink
from app.models.requirement import Requirement
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.modules.decisions.enums import DecisionStatus
from app.modules.decisions.models import (
    Decision,
    DecisionComment,
    DecisionCommentFile,
    DecisionFile,
    DecisionTemplateDefinition,
    DecisionTypeDefinition,
)
from app.modules.registry import LinkTypeSeed
from app.services.audit import log_event
from app.services.lifecycles import check_move
from app.services.link_types import ensure_org_link_type
from app.services.permissions import encode_permission
from app.services.relationships import create_link, get_link_between, get_links_from

# Source overview §13/10.2's default list, seeded per new project — a
# project's own admin may add/rename/reorder/remove from there.
DEFAULT_DECISION_TYPES: list[str] = ["Architecture", "Design", "Engineering", "Strategy", "Operational"]

# This module's artefact-type string, registered on
# `ModuleDefinition.artefact_types`; used for `Decision.unique_code` and links.
DECISION_ARTEFACT_TYPE = "decision"
DECISION_CODE_PREFIX = "DEC"

# The unscoped `(decision, approve_baseline)` atom on the `decision_approver`
# role (`module.py`); the approval check also tests its sub-type-scoped form
# (the decision's type name) for callers holding only a per-type grant.
DECISION_APPROVE_PERMISSION = encode_permission(DECISION_ARTEFACT_TYPE, PermissionLevel.APPROVE_BASELINE.value)

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
    Mirrors `services.definitions.seed_action_types`'s identical shape. A project that already has its own
    types (copied from a template) is left as it is, so the defaults never duplicate or override the template's."""
    if db.scalar(select(DecisionTypeDefinition.id).where(DecisionTypeDefinition.project_id == project_id).limit(1)) is not None:
        return
    for i, name in enumerate(DEFAULT_DECISION_TYPES):
        db.add(DecisionTypeDefinition(project_id=project_id, name=name, sort_order=i))


# Safety cap on the walk up the project tree; matches
# `project_hierarchy._PROJECT_TREE_ITERATION_CAP`, which is module-private.
_PROJECT_TREE_ITERATION_CAP = 5000


def resolve_effective_decision_types(db: Session, project_id: uuid.UUID) -> list[DecisionTypeDefinition]:
    """Returns the decision types a project offers when creating a Decision:
    its own if it has any, else its nearest ancestor's (walking
    `Project.parent_project_id`), else an empty list at an unconfigured root.

    Mirrors `resolve_effective_action_types`: always on, independent of
    `role_inheritance_mode`. It does not check access to the parent: callers
    have already checked access to `project_id`, and only the parent's
    decision-type names (low-sensitivity metadata) are visible through a child.
    """
    visited: set[uuid.UUID] = set()
    current_id: uuid.UUID | None = project_id
    iterations = 0
    while current_id is not None and current_id not in visited and iterations < _PROJECT_TREE_ITERATION_CAP:
        iterations += 1
        visited.add(current_id)
        own = db.scalars(
            select(DecisionTypeDefinition)
            .where(DecisionTypeDefinition.project_id == current_id)
            .order_by(DecisionTypeDefinition.sort_order)
        ).all()
        if own:
            return list(own)
        current_id = db.scalar(select(Project.parent_project_id).where(Project.id == current_id))
    return []


def list_decision_type_names_for_organization(db: Session, organization_id: uuid.UUID) -> list[str]:
    """Returns the distinct `DecisionTypeDefinition.name` values in use anywhere
    in `organization_id`, sorted: this module's
    `ModuleDefinition.subtype_providers["decision"]`, which fills the Role
    Management sub-type picker and validates a permission sub-type at write time.

    A flat union across the organisation's projects, not the per-project
    hierarchy fallback: a permission `subtype` is compared as a plain string
    with a decision's own type name, so only the set of names is needed. A role
    scoped to a name absent from a project never matches there.

    Args:
        db: An active database session.
        organization_id: The organisation to list Decision Type names for.

    Returns:
        Sorted, deduplicated Decision Type names.
    """
    names = db.scalars(
        select(DecisionTypeDefinition.name)
        .join(Project, Project.id == DecisionTypeDefinition.project_id)
        .where(Project.organization_id == organization_id)
        .distinct()
    ).all()
    return sorted(names)


def seed_decision_templates(db: Session, organization_id: uuid.UUID, selected_keys: frozenset[str]) -> None:
    """Adds one `DecisionTemplateDefinition` row per selected pack in
    `DECISION_TEMPLATE_PACKS` (not committed/flushed — caller owns the
    transaction) — this module's `ModuleDefinition.on_org_created_with_
    choices` hook. Packs whose `choice_key` isn't in `selected_keys` are
    skipped entirely (opt-in, not unconditional).

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


# --- approval, rejection, and supersession workflow --------------

# Legal `DecisionStatus` transitions: forward through the in-flight states;
# `REJECTED` from `PROPOSED` or `UNDER_REVIEW`; `SUPERSEDED` only from
# `APPROVED`, via `_maybe_supersede`/`_supersede_predecessors`.
_ALLOWED_TRANSITIONS: dict[DecisionStatus, frozenset[DecisionStatus]] = {
    DecisionStatus.DRAFT: frozenset({DecisionStatus.PROPOSED}),
    DecisionStatus.PROPOSED: frozenset({DecisionStatus.UNDER_REVIEW, DecisionStatus.REJECTED}),
    DecisionStatus.UNDER_REVIEW: frozenset({DecisionStatus.APPROVED, DecisionStatus.REJECTED}),
    DecisionStatus.APPROVED: frozenset({DecisionStatus.SUPERSEDED}),
    DecisionStatus.REJECTED: frozenset(),
    DecisionStatus.SUPERSEDED: frozenset(),
}

# The `RequirementLinkTypeDefinition` name of the typed supersession link
# `create_supersession` creates or reuses.
SUPERSEDES_LINK_TYPE_FORWARD_NAME = "Supersedes"
SUPERSEDES_LINK_TYPE_REVERSE_NAME = "Is superseded by"


def _transition_status(
    db: Session, decision: Decision, new_status: DecisionStatus, actor_id: uuid.UUID, *,
    action: str, comment: str | None = None, via_mcp: bool = False,
) -> Decision:
    """Validates and applies a `Decision.status` transition, then records it
    via `services.audit.log_event` (not committed).

    `via_mcp` adds `"via": "mcp"` to the logged `detail`; only
    `approve_decision`/`reject_decision` pass it.

    Raises:
        ValueError: if `new_status` isn't reachable from `decision.status`
            per `_ALLOWED_TRANSITIONS` (the router returns 409).
    """
    check_move(db, decision.project_id, DECISION_ARTEFACT_TYPE, decision.status.value, new_status.value)
    decision.status = new_status
    detail = {}
    if comment:
        detail["comment"] = comment
    if via_mcp:
        detail["via"] = "mcp"
    log_event(
        db, entity_type=DECISION_ARTEFACT_TYPE, entity_id=decision.id, action=action,
        actor_id=actor_id, project_id=decision.project_id,
        detail=detail or None,
    )
    db.flush()
    return decision


def propose_decision(db: Session, decision: Decision, actor_id: uuid.UUID) -> Decision:
    """`DRAFT` -> `PROPOSED`: the decision is ready for others to review."""
    return _transition_status(db, decision, DecisionStatus.PROPOSED, actor_id, action="proposed")


def submit_decision_for_review(db: Session, decision: Decision, actor_id: uuid.UUID) -> Decision:
    """`PROPOSED` -> `UNDER_REVIEW`: formal review/approval has started."""
    return _transition_status(db, decision, DecisionStatus.UNDER_REVIEW, actor_id, action="submitted_for_review")


def reject_decision(
    db: Session, decision: Decision, actor_id: uuid.UUID, *, comment: str | None = None, via_mcp: bool = False,
) -> Decision:
    """`PROPOSED`/`UNDER_REVIEW` -> `REJECTED`. Rejected Decisions remain
    queryable (§13/10.6) — never hard-deleted, same as
    every other soft-delete convention in this codebase; this is a status
    value, not an archive. `via_mcp` — see `_transition_status`'s own
    docstring."""
    return _transition_status(
        db, decision, DecisionStatus.REJECTED, actor_id, action="rejected", comment=comment, via_mcp=via_mcp,
    )


def approve_decision(
    db: Session, decision: Decision, actor_id: uuid.UUID, *, comment: str | None = None, via_mcp: bool = False,
) -> Decision:
    """`UNDER_REVIEW` -> `APPROVED`. Also flips any predecessor Decision
    this one already supersedes (a `create_supersession` link created
    before this approval) to `SUPERSEDED` —
    see `_supersede_predecessors`. `via_mcp` — see `_transition_status`'s
    own docstring."""
    _transition_status(
        db, decision, DecisionStatus.APPROVED, actor_id, action="approved", comment=comment, via_mcp=via_mcp,
    )
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
    """This organisation's link type identified by `forward_name`, created on
    first use from the registered seed (`services.link_types.ensure_org_link_type`;
    `reverse_name` is the fallback phrase for an unseeded name). Deliberately
    lazy: no core-file default-list edit or migration backfill is needed."""
    return ensure_org_link_type(db, organization_id, forward_name, reverse_name)


def _maybe_supersede(db: Session, *, new_decision: Decision, old_decision: Decision, actor_id: uuid.UUID) -> None:
    """Flips `old_decision` to `SUPERSEDED` if both halves of the
    supersession condition are already true at this exact moment: the
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
    direction of the supersession condition than `_maybe_
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
    """Records that `new_decision` supersedes `old_decision`: creates the typed
    `"Supersedes"` `ArtefactLink` (§13/10.6), then flips `old_decision` to
    `SUPERSEDED` at once if `new_decision` is already `APPROVED`
    (`_maybe_supersede`), otherwise when it reaches `APPROVED`.

    Args:
        db: Active session; not committed.
        new_decision: The superseding Decision (the link's source).
        old_decision: The superseded Decision (the link's target).
        actor_id: The user recording this relationship.

    Returns:
        The created `ArtefactLink`.

    Raises:
        ValueError: if the Decisions are the same row or in different
            projects, `old_decision` is already `SUPERSEDED`, `new_decision`
            is `REJECTED`/`SUPERSEDED` (it can never reach `APPROVED`), or
            the supersession link already exists.
    """
    if new_decision.id == old_decision.id:
        raise ValueError("A Decision cannot supersede itself.")
    if new_decision.project_id != old_decision.project_id:
        raise ValueError("A Decision can only supersede another Decision in the same project.")
    if old_decision.status == DecisionStatus.SUPERSEDED:
        raise ValueError("This Decision has already been superseded.")
    if new_decision.status in (DecisionStatus.REJECTED, DecisionStatus.SUPERSEDED):
        # A supersession from a REJECTED/SUPERSEDED Decision (terminal, no
        # outgoing transitions) would never resolve into the status change its
        # name implies and would mislead the relationship graph.
        raise ValueError(
            f"A '{new_decision.status.value}' Decision can never be approved, so it cannot supersede another Decision."
        )

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
        link_type_id=link_type.id, created_by=actor_id, enforce_rules=False,  # fixed-semantic lifecycle step
    )
    _maybe_supersede(db, new_decision=new_decision, old_decision=old_decision, actor_id=actor_id)
    return link


# --- relationships to Requirements and other Decisions -----------

# §13/10.7 Decision<->Requirement relationship names; `_get_or_create_link_type`
# creates a missing one (an admin may have renamed or deleted a seeded row).
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
    """Which of §13/10.7's two Decision -> Requirement
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
    """Records that `decision` either `Implements` or `Affects` `requirement`
    (§13/10.7): creates the typed `ArtefactLink` with `decision` as source.

    Args:
        db: Active session; not committed.
        decision: The linking Decision (the link's source).
        requirement: The target Requirement.
        kind: Which relationship name to use.
        actor_id: The user recording this relationship.

    Returns:
        The created `ArtefactLink`.

    Raises:
        ValueError: if they are in different projects, or this link exists.
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
        link_type_id=link_type.id, created_by=actor_id, project_id=decision.project_id,
    )


def create_decision_decision_link(
    db: Session, *, source_decision: Decision, target_decision: Decision, kind: DecisionDecisionLinkKind,
    actor_id: uuid.UUID,
) -> ArtefactLink:
    """Records a `Depends on` or `Conflicts with` relationship from
    `source_decision` to `target_decision` (`"Supersedes"` has
    `create_supersession`).

    Args:
        db: Active session; not committed.
        source_decision: The linking Decision (the link's source).
        target_decision: The target Decision.
        kind: Which relationship name to use.
        actor_id: The user recording this relationship.

    Returns:
        The created `ArtefactLink`.

    Raises:
        ValueError: if the Decisions are the same row or in different
            projects, or this exact link already exists.
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
        link_type_id=link_type.id, created_by=actor_id, project_id=source_decision.project_id,
    )


# --- file-ownership resolution hook -------------------------------


def resolve_decision_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project of the Decision it is attached
    to, directly (`DecisionFile`) or through a `DecisionComment`
    (`DecisionCommentFile`): this module's
    `ModuleDefinition.resolve_file_owner_project_id` hook.

    Returns:
        The owning project's id, or `None`.
    """
    direct_link = db.scalar(select(DecisionFile).where(DecisionFile.file_id == file_id))
    if direct_link is not None:
        decision = db.get(Decision, direct_link.decision_id)
        return decision.project_id if decision is not None else None

    comment_link = db.scalar(select(DecisionCommentFile).where(DecisionCommentFile.file_id == file_id))
    if comment_link is not None:
        comment = db.get(DecisionComment, comment_link.comment_id)
        if comment is not None:
            decision = db.get(Decision, comment.decision_id)
            return decision.project_id if decision is not None else None

    return None


# Link types shipped by this module (`ModuleDefinition.link_type_seeds`). Other
# modules' type strings are plain names, not imports; a restriction naming an
# uninstalled module's type matches nothing.
LINK_TYPE_SEEDS: tuple[LinkTypeSeed, ...] = (
    LinkTypeSeed(
        "Addresses", "Is addressed by", LinkFlow.FORWARD_IS_UPSTREAM,
        nesting_scope=LinkNestingScope.UPSTREAM_IN_ANCESTOR,
        allowed_source_types=(DECISION_ARTEFACT_TYPE,), allowed_target_types=("pain_point",),
    ),
    LinkTypeSeed(
        "Resolves", "Is resolved by", LinkFlow.FORWARD_IS_UPSTREAM,
        nesting_scope=LinkNestingScope.UPSTREAM_IN_ANCESTOR,
        allowed_source_types=(DECISION_ARTEFACT_TYPE,), allowed_target_types=("open_question",),
    ),
    LinkTypeSeed(
        "Supports", "Is supported by", LinkFlow.FORWARD_IS_UPSTREAM,
        nesting_scope=LinkNestingScope.UPSTREAM_IN_ANCESTOR,
        allowed_source_types=(DECISION_ARTEFACT_TYPE,), allowed_target_types=("strategy",),
    ),
    LinkTypeSeed(
        "Guided by", "Guides", LinkFlow.FORWARD_IS_UPSTREAM,
        nesting_scope=LinkNestingScope.UPSTREAM_IN_ANCESTOR,
        allowed_source_types=(DECISION_ARTEFACT_TYPE,), allowed_target_types=("guiding_principle",),
    ),
    LinkTypeSeed(
        "Constrained by", "Constrains", LinkFlow.FORWARD_IS_UPSTREAM,
        nesting_scope=LinkNestingScope.UPSTREAM_IN_ANCESTOR,
        allowed_source_types=(DECISION_ARTEFACT_TYPE,), allowed_target_types=("project_compliance_requirement",),
    ),
    LinkTypeSeed(
        AFFECTS_LINK_TYPE_FORWARD_NAME, AFFECTS_LINK_TYPE_REVERSE_NAME,
        allowed_source_types=(DECISION_ARTEFACT_TYPE,), allowed_target_types=(ArtefactType.REQUIREMENT.value,),
    ),
    LinkTypeSeed(
        SUPERSEDES_LINK_TYPE_FORWARD_NAME, SUPERSEDES_LINK_TYPE_REVERSE_NAME,
        allowed_source_types=(DECISION_ARTEFACT_TYPE,), allowed_target_types=(DECISION_ARTEFACT_TYPE,),
        dedicated_endpoint=True,
    ),
)
