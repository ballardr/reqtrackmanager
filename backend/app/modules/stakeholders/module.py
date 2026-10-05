"""
Module: modules.stakeholders.module

Registers the Stakeholders & Personas module into the modular feature
system's registry via `MODULE_DEFINITION` (docs/plans/module-02-stakeholders-
and-personas-plan.md). Phase 1.1 delivers the Persona artefact.

Registered contributions:
- Roles (not additions to core enums): `persona_owner` (project) and
  `org_persona_owner` (org) gate create/edit/archive/retire; only the project
  role carries the FGAC `(persona, manage)` atom, since an org-level role's
  atoms would apply to every project; `persona_type_admin` (org) gates the org
  Persona type vocabulary. There is no approver role because Personas have no
  approval gate (Phase 0 resolution 6).
- `artefact_types=("persona",)` so personas are valid `ArtefactLink`
  endpoints and get FGAC atoms.
- `scoring_target_providers["persona"]`: the generic hook Module 1's
  per-persona Pain Point scoring reads (Phase 0 resolution 10), so Context &
  Strategy never imports this module.
- `on_org_created` seeds each new organisation's default Persona types; the
  migration backfills existing organisations.
- Org and project bundle hooks (`export.py`) so personas travel with an
  organisation/project export.
- One sub-component, `persona`, so a project can switch Personas off without
  disabling the whole module (Stakeholder joins in Phase 1.2).

`default_enabled=False`: an organisation opts in explicitly, matching the
other new modules.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.registry import (
    McpToolDefinition,
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
)
from app.modules.stakeholders._shared import PERSONA_MANAGE_PERMISSION
from app.modules.stakeholders.export import export_org_data, export_project_data, import_org_data, import_project_data
from app.modules.stakeholders.service import (
    PERSONA_ARTEFACT_TYPE,
    PERSONA_TYPES,
    STAKEHOLDERS_MODULE_KEY,
    persona_scoring_targets,
)

_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}"


def get_router() -> APIRouter | None:
    """The org-scoped router; imported lazily to avoid import cycles with
    this module's own registration."""
    from app.modules.stakeholders.router import router

    return router


def get_project_router() -> APIRouter | None:
    """The project-scoped router; imported lazily like `get_router`."""
    from app.modules.stakeholders.project_router import router

    return router


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """`ModuleDefinition.resolve_file_owner_project_id`: the project owning a
    file attached to a project-scoped persona (or its comment), else `None`."""
    from app.modules.stakeholders.service import resolve_persona_file_project_id

    return resolve_persona_file_project_id(db, file_id)


def _seed_org_defaults(db: Session, organization_id: UUID) -> None:
    """`ModuleDefinition.on_org_created`: seeds the default Persona types."""
    PERSONA_TYPES.seed_defaults(db, organization_id)


def _artefact_ids_in_organization(db: Session, organization_id: UUID) -> set[UUID]:
    """`ModuleDefinition.artefact_ids_in_organization`: every persona in the
    organisation, org-scoped or in one of its projects, for org deletion's
    polymorphic cleanup."""
    from app.models.project import Project
    from app.modules.stakeholders.models import Persona

    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    return set(db.scalars(select(Persona.id).where(
        or_(Persona.organization_id == organization_id, Persona.project_id.in_(project_ids))
    )).all())


_PROJECT_ID_PARAM = {
    "name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The owning project.",
}
_PERSONA_ID_PARAM = {
    "name": "persona_id", "type": "uuid", "required": True, "in": "path", "description": "The Persona.",
}


def _body(name: str, type_: str, description: str, *, required: bool = False) -> dict:
    return {"name": name, "type": type_, "required": required, "in": "body", "description": description}


_PERSONA_FIELD_PARAMS = [
    _body("description", "string", "Free-text summary."),
    _body("persona_type_id", "uuid", "An effective Persona type id (GET .../persona-types)."),
    _body("role_title", "string", "Job title/role the persona represents."),
    _body("goals", "string", "What the persona is trying to achieve."),
    _body("needs", "string", "What the persona needs."),
    _body("behaviours", "string", "How the persona behaves."),
    _body("context_environment", "string", "Where and how the persona works."),
    _body("skills_proficiency", "string", "Skills and proficiency."),
    _body("frequency_of_use", "string", "How often the persona uses the product."),
    _body("constraints", "string", "Constraints the persona operates under."),
    _body("weight", "number", "Importance weight for per-persona scoring (positive); null clears it."),
    _body("owner_id", "uuid", "User who owns this record."),
    _body("champion_id", "uuid", "User accountable for keeping this persona accurate."),
]


def _build_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """Persona read and write tools (no approval-gated action exists, so no
    `require_ai_approvals_enabled` handling is needed)."""
    persona_path = f"{_PROJECT_ROUTER_PREFIX}/personas/{{persona_id}}"
    return (
        McpToolDefinition(
            name="list_personas", description="Lists a project's Personas, including its organisation's shared ones.",
            method="GET", path_template=f"{_PROJECT_ROUTER_PREFIX}/personas", params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="get_persona", description="Fetches a single Persona.", method="GET",
            path_template=persona_path, params=[_PROJECT_ID_PARAM, _PERSONA_ID_PARAM],
        ),
        McpToolDefinition(
            name="create_persona", description="Creates a project-scoped Persona in Draft status.", method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/personas",
            params=[_PROJECT_ID_PARAM, _body("name", "string", "Display name.", required=True), *_PERSONA_FIELD_PARAMS],
        ),
        McpToolDefinition(
            name="update_persona",
            description="Updates a project-scoped Persona; only the fields supplied change.", method="PUT",
            path_template=persona_path,
            params=[_PROJECT_ID_PARAM, _PERSONA_ID_PARAM, _body("name", "string", "Display name."),
                    *_PERSONA_FIELD_PARAMS, _body("change_note", "string", "Reason for the change.")],
        ),
        McpToolDefinition(
            name="activate_persona", description="Moves a Draft or Retired Persona to Active.", method="POST",
            path_template=f"{persona_path}/activate", params=[_PROJECT_ID_PARAM, _PERSONA_ID_PARAM,
                                                              _body("comment", "string", "Optional comment.")],
        ),
        McpToolDefinition(
            name="retire_persona", description="Moves a Draft or Active Persona to Retired.", method="POST",
            path_template=f"{persona_path}/retire", params=[_PROJECT_ID_PARAM, _PERSONA_ID_PARAM,
                                                            _body("comment", "string", "Optional comment.")],
        ),
    )


MODULE_DEFINITION = ModuleDefinition(
    key=STAKEHOLDERS_MODULE_KEY,
    name="Stakeholders & Personas",
    description=(
        "Record Personas — representative user archetypes with goals, needs, behaviours and an importance weight "
        "— at organisation or project level, with configurable types, a Draft/Active/Retired lifecycle and full "
        "version history. Personas are the targets Pain Points are scored against."
    ),
    version="0.1.0",
    default_enabled=False,
    implemented=True,
    get_router=get_router,
    get_project_router=get_project_router,
    resolve_file_owner_project_id=resolve_file_owner_project_id,
    on_org_created=_seed_org_defaults,
    models_import_path="app.modules.stakeholders.models",
    migrations_dir="app/modules/stakeholders/migrations",
    frontend_manifest=ModuleFrontendManifest(
        tier="installed",
        nav_label="Personas",
        nav_path=f"/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}/personas",
        nav_icon="users",
    ),
    artefact_types=(PERSONA_ARTEFACT_TYPE,),
    artefact_ids_in_organization=_artefact_ids_in_organization,
    sub_components=(ModuleSubComponentDefinition(key="persona", name="Personas", default_enabled=True),),
    scoring_target_providers={PERSONA_ARTEFACT_TYPE: persona_scoring_targets},
    org_bundle_hooks=ModuleOrgBundleHooks(export=export_org_data, import_=import_org_data),
    project_bundle_hooks=ModuleProjectBundleHooks(export=export_project_data, import_=import_project_data),
    roles=(
        ModuleRoleDefinition(
            role_key="persona_owner", name="Persona Owner",
            description="Creates, edits, retires and re-weights project-scoped Personas and manages the project's Persona types.",
            scope="project", permissions=(PERSONA_MANAGE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="org_persona_owner", name="Organisation Persona Owner",
            description="Creates, edits and retires organisation-scoped Personas shared by every project in the organisation.",
            # Deliberately carries no FGAC atom: an org-level role's atoms apply to every project in the
            # organisation, which would let an org persona owner manage all project personas.
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="persona_type_admin", name="Persona Type Admin",
            description="Manages the organisation's shared Persona type vocabulary (Primary/Secondary/Negative by default).",
            scope="org",
        ),
    ),
    mcp_tools=_build_mcp_tools(),
)
