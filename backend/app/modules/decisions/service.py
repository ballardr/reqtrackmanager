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
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.decisions.models import DecisionTemplateDefinition, DecisionTypeDefinition

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
