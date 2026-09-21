"""
Module: modules.decisions.module

Registers the Decision Management module into the modular feature
system's registry (docs/plans/module-04-decision-management-plan.md
Phase 1) via `MODULE_DEFINITION`, mirroring `app.modules.compliance.
module`'s own registration shape.

`decision_owner` (project-scoped) and `decision_approver` (project-scoped,
the Phase 0 addendum Q2/2a "simple placeholder role") are declared here as
module-contributed roles, not additions to `ProjectRole`.

Phase 1 is data model only: `get_router()` returns `None` (no HTTP
endpoints yet — Phase 4), `implemented=False` and `default_enabled=False`
reflect that nothing here is usable by an end user yet.

`on_project_created` seeds this project's default `DecisionTypeDefinition`
rows unconditionally (mirrors Compliance's own `on_org_created` seeding —
see `service.seed_decision_types`'s own docstring for why unconditional,
not gated on module enablement). `org_creation_choices` / `on_org_created_
with_choices` are this module's first use of the org-creation-choices
extension point (`app.modules.registry`) — the three seeded ADR template
packs, opted into per-organisation rather than always seeded (Phase 0
addendum Q1).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.decisions.service import DECISION_ARTEFACT_TYPE, DECISION_TEMPLATE_PACKS
from app.modules.registry import ModuleDefinition, ModuleRoleDefinition, OrgCreationChoiceOption

DECISIONS_MODULE_KEY = "decisions"


def get_router() -> APIRouter | None:
    """No HTTP endpoints yet — Phase 4 (Backend API + audit logging)."""
    return None


def _seed_new_project(db: Session, project: Project, actor_id: uuid.UUID) -> None:
    """This module's `ModuleDefinition.on_project_created` hook. Imported
    lazily for the same import-cycle reason `app.modules.compliance.
    module`'s own hook functions are."""
    from app.modules.decisions.service import seed_decision_types

    seed_decision_types(db, project.id)


def _seed_org_templates(db: Session, organization_id: uuid.UUID, selected_keys: frozenset[str]) -> None:
    """This module's `ModuleDefinition.on_org_created_with_choices` hook.
    Imported lazily for the same import-cycle reason as `_seed_new_project`."""
    from app.modules.decisions.service import seed_decision_templates

    seed_decision_templates(db, organization_id, selected_keys)


_ORG_CREATION_CHOICES = tuple(
    OrgCreationChoiceOption(
        key=pack.choice_key,
        group_label="Decision Templates",
        label=pack.name,
        description=pack.description,
        default_selected=True,
    )
    for pack in DECISION_TEMPLATE_PACKS
)


MODULE_DEFINITION = ModuleDefinition(
    key=DECISIONS_MODULE_KEY,
    name="Decision Management",
    description=(
        "Record, approve, and supersede formal decisions made during a project's lifecycle — architecture, "
        "design, engineering, strategy, and operational."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=False,
    get_router=get_router,
    models_import_path="app.modules.decisions.models",
    migrations_dir="app/modules/decisions/migrations",
    on_project_created=_seed_new_project,
    org_creation_choices=_ORG_CREATION_CHOICES,
    on_org_created_with_choices=_seed_org_templates,
    artefact_types=(DECISION_ARTEFACT_TYPE,),
    roles=(
        ModuleRoleDefinition(
            role_key="decision_owner",
            name="Decision Owner",
            description=(
                "Creates and manages Decision records and this project's Decision Types — the module's "
                "management-level role (docs/plans/module-04-decision-management-plan.md Phase 1)."
            ),
            scope="project",
        ),
        ModuleRoleDefinition(
            role_key="decision_approver",
            name="Decision Approver",
            description=(
                "May approve, reject, and supersede Decisions in this project — the Phase 0 addendum's "
                "'simple placeholder role' for approval authority, expected to be superseded by a future "
                "Governance-module policy mechanism rather than this module building its own."
            ),
            scope="project",
        ),
    ),
)
