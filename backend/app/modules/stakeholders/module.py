"""
Module: modules.stakeholders.module

Registers the Stakeholders & Personas module into the modular feature
system's registry via `MODULE_DEFINITION` (docs/plans/module-02-stakeholders-
and-personas-plan.md). Phase 1.1 delivers the Persona artefact, Phase 1.2 the
Stakeholder artefact, Phase 2 the Stakeholder Need artefact.

Registered contributions:
- Roles (not additions to core enums): `persona_owner` (project) and
  `org_persona_owner` (org) gate create/edit/archive/retire; only the project
  role carries the FGAC `(persona, manage)` atom, since an org-level role's
  atoms would apply to every project; `persona_type_admin` (org) gates the org
  Persona type vocabulary. There is no approver role because Personas have no
  approval gate (Phase 0 resolution 6).
- The same trio for Stakeholders: `stakeholder_owner` (project, carries the FGAC
  `(stakeholder, manage)` atom), `org_stakeholder_owner` (org, no atom) and
  `stakeholder_type_admin` (org; also administers the `stakeholder` scoring
  scheme's levels and bands).
- `stakeholder_need_owner` (project; carries the FGAC `(stakeholder_need, manage)`
  atom) for Stakeholder Needs, which are project-scoped only so have no org role.
- `artefact_types=("persona", "stakeholder", "stakeholder_need")` so all three
  are valid `ArtefactLink` endpoints and get FGAC atoms.
- `scoring_schemes`: the Influence × Interest `stakeholder` scheme (`scoring.py`).
- `scoring_target_providers["persona"]`: the generic hook Module 1's
  per-persona Pain Point scoring reads (Phase 0 resolution 10), so Context &
  Strategy never imports this module.
- `on_org_created` seeds each new organisation's default Persona and
  Stakeholder types; the migrations backfill existing organisations.
- Org and project bundle hooks (`export.py` for Personas,
  `stakeholder_export.py` for Stakeholders, composed here — Personas first,
  since Stakeholders link to them) so both travel with an organisation/project
  export.
- Three sub-components, `persona`, `stakeholder` and `stakeholder_need`, so a
  project can switch any off without disabling the whole module.

`default_enabled=False`: an organisation opts in explicitly, matching the
other new modules.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.registry import (
    McpToolDefinition,
    ModuleDefinition,
    ModuleFrontendManifest,
    ModuleNavEntry,
    ModuleOrgBundleHooks,
    ModuleProjectBundleHooks,
    ModuleRoleDefinition,
    ModuleSubComponentDefinition,
)
from app.modules.stakeholders import export as persona_export
from app.modules.stakeholders import need_export, relationship_export, stakeholder_export
from app.modules.stakeholders._need_shared import NEED_MANAGE_PERMISSION
from app.modules.stakeholders._shared import PERSONA_MANAGE_PERMISSION
from app.modules.stakeholders._stakeholder_shared import STAKEHOLDER_MANAGE_PERMISSION
from app.modules.stakeholders.scoring import STAKEHOLDER_SCORING_SCHEME
from app.modules.stakeholders.service import (
    NEED_ARTEFACT_TYPE,
    PERSONA_ARTEFACT_TYPE,
    PERSONA_TYPES,
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_TYPES,
    STAKEHOLDERS_MODULE_KEY,
    persona_scoring_targets,
)

_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}"


def get_router() -> APIRouter | None:
    """The org-scoped router (Persona + Stakeholder routes); imported lazily
    to avoid import cycles with this module's own registration."""
    from app.modules.stakeholders.router import router
    from app.modules.stakeholders.stakeholder_router import router as stakeholder_router

    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(stakeholder_router)
    return combined


def get_project_router() -> APIRouter | None:
    """The project-scoped router (Persona + Stakeholder routes); imported
    lazily like `get_router`."""
    from app.modules.stakeholders.need_project_router import router as need_router
    from app.modules.stakeholders.project_router import router
    from app.modules.stakeholders.relationship_project_router import router as relationship_router
    from app.modules.stakeholders.stakeholder_project_router import router as stakeholder_router

    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(stakeholder_router)
    combined.include_router(need_router)
    combined.include_router(relationship_router)
    return combined


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """`ModuleDefinition.resolve_file_owner_project_id`: the project owning a
    file attached to a project-scoped persona, stakeholder or need (or its
    comment), else `None`."""
    from app.modules.stakeholders.service import (
        resolve_need_file_project_id,
        resolve_persona_file_project_id,
        resolve_stakeholder_file_project_id,
    )

    return (
        resolve_persona_file_project_id(db, file_id) or resolve_stakeholder_file_project_id(db, file_id)
        or resolve_need_file_project_id(db, file_id)
    )


def _seed_org_defaults(db: Session, organization_id: UUID) -> None:
    """`ModuleDefinition.on_org_created`: seeds the default Persona and
    Stakeholder types."""
    PERSONA_TYPES.seed_defaults(db, organization_id)
    STAKEHOLDER_TYPES.seed_defaults(db, organization_id)


def _export_org(db: Session, org) -> dict:
    """Org bundle export: the Persona and Stakeholder halves merged (disjoint keys)."""
    return {**persona_export.export_org_data(db, org), **stakeholder_export.export_org_data(db, org)}


def _import_org(db, org, data, users, warnings, resolutions) -> None:
    """Org bundle import: Personas first, since Stakeholders link to them."""
    persona_export.import_org_data(db, org, data, users, warnings, resolutions)
    stakeholder_export.import_org_data(db, org, data, users, warnings, resolutions)


def _export_project(db: Session, project):
    """Project bundle export: the three parts' data and attachment assets merged."""
    persona_data, persona_assets = persona_export.export_project_data(db, project)
    stakeholder_data, stakeholder_assets = stakeholder_export.export_project_data(db, project)
    need_data, need_assets = need_export.export_project_data(db, project)
    relationship_data = relationship_export.export_project_data(db, project)
    return (
        {**persona_data, **stakeholder_data, **need_data, **relationship_data},
        {**persona_assets, **stakeholder_assets, **need_assets},
    )


def _import_project(db, project, data, file_bytes_by_ref, current_user, users, warnings) -> None:
    """Project bundle import: Personas, then Stakeholders (which link to them),
    then Needs (which link to both), then the §10.5 relationships (which need
    all of those plus other modules' Pain Points and Decisions)."""
    persona_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)
    stakeholder_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)
    need_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)
    relationship_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)


def _artefact_ids_in_organization(db: Session, organization_id: UUID) -> set[UUID]:
    """`ModuleDefinition.artefact_ids_in_organization`: every persona,
    stakeholder and need in the organisation, org-scoped or in one of its
    projects, for org deletion's polymorphic cleanup."""
    from app.models.project import Project
    from app.modules.stakeholders.models import Persona, Stakeholder, StakeholderNeed

    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    ids: set[UUID] = set()
    for model in (Persona, Stakeholder):
        ids |= set(db.scalars(select(model.id).where(
            or_(model.organization_id == organization_id, model.project_id.in_(project_ids))
        )).all())
    ids |= set(db.scalars(select(StakeholderNeed.id).where(StakeholderNeed.project_id.in_(project_ids))).all())
    return ids


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


_STAKEHOLDER_ID_PARAM = {
    "name": "stakeholder_id", "type": "uuid", "required": True, "in": "path", "description": "The Stakeholder.",
}

_STAKEHOLDER_FIELD_PARAMS = [
    _body("description", "string", "Free-text summary."),
    _body("stakeholder_type_id", "uuid", "An effective Stakeholder type id (GET .../stakeholder-types)."),
    _body("role", "string", "The stakeholder's role/job title."),
    _body("organisation_group", "string", "The organisation or group they belong to."),
    _body("interests", "string", "What they are interested in."),
    _body("responsibilities", "string", "What they are responsible for."),
    _body("goals_needs", "string", "Their goals and needs."),
    _body("priorities", "string", "Their priorities."),
    _body("constraints", "string", "Constraints they operate under."),
    _body("workflows_scenarios", "string", "Relevant workflows / use scenarios."),
    _body("contact_info", "string", "Contact/reference information (Confidential personal data)."),
    _body("target_cadence", "string", "Goal engagement cadence: one_off, ad_hoc, weekly, monthly, quarterly, yearly."),
    _body("availability_constraints", "string", "Their limits on engagement."),
    _body("influence_level_id", "uuid", "Influence level id from the `stakeholder` scoring scheme."),
    _body("interest_level_id", "uuid", "Interest level id from the `stakeholder` scoring scheme."),
    _body("owner_id", "uuid", "User who owns this record."),
    _body("user_id", "uuid", "The platform user this stakeholder is, if any."),
]


_NEED_ID_PARAM = {
    "name": "need_id", "type": "uuid", "required": True, "in": "path", "description": "The Stakeholder Need.",
}

_NEED_FIELD_PARAMS = [
    _body("description", "string", "The need in the stakeholder's own words."),
    _body("rationale", "string", "Why it matters, its source or evidence."),
    _body("owner_id", "uuid", "User who owns this record."),
]


def _path(name: str, description: str) -> dict:
    return {"name": name, "type": "uuid", "required": True, "in": "path", "description": description}


def _query(name: str, type_: str, description: str) -> dict:
    return {"name": name, "type": type_, "required": True, "in": "query", "description": description}


def _build_link_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """Link tools (Phase 3): the §10.5 relationships, "represents Persona", "has
    need" and "gives rise to". Writes need the same role as the REST endpoints;
    removing a link deletes only the link, never either record."""
    prefix = _PROJECT_ROUTER_PREFIX
    link_id = _path("link_id", "The relationship's link id (from the list tool).")
    kind_body = [
        _body("kind", "string", "A relationship kind key (see list_relationship_kinds).", required=True),
        _body("target_type", "string", "The target's artefact type, e.g. pain_point, requirement, decision.", required=True),
        _body("target_id", "uuid", "The target record's id (it must belong to this project).", required=True),
    ]
    tools: list[McpToolDefinition] = [
        McpToolDefinition(
            name="list_relationship_kinds", method="GET", path_template=f"{prefix}/relationship-kinds",
            description="Lists the relationship kinds a Stakeholder or Persona can have and which targets are linkable now.",
            params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="list_relationship_targets", method="GET", path_template=f"{prefix}/relationship-targets",
            description="Lists the project's records of one target type a relationship can point at.",
            params=[_PROJECT_ID_PARAM, _query("target_type", "string", "e.g. pain_point, requirement, decision.")],
        ),
        McpToolDefinition(
            name="list_incoming_relationships", method="GET", path_template=f"{prefix}/relationships/incoming",
            description="Lists the Stakeholders and Personas related to one Pain Point, Requirement or Decision.",
            params=[_PROJECT_ID_PARAM, _query("target_type", "string", "The target's artefact type."),
                    _query("target_id", "uuid", "The target record's id.")],
        ),
    ]
    for holder, label, holder_param in (
        ("stakeholder", "Stakeholder", _STAKEHOLDER_ID_PARAM), ("persona", "Persona", _PERSONA_ID_PARAM),
    ):
        base = f"{prefix}/{holder}s/{{{holder}_id}}"
        tools += [
            McpToolDefinition(
                name=f"list_{holder}_relationships", method="GET", path_template=f"{base}/relationships",
                description=f"Lists a {label}'s relationships to this project's Pain Points, Requirements and Decisions.",
                params=[_PROJECT_ID_PARAM, holder_param],
            ),
            McpToolDefinition(
                name=f"add_{holder}_relationship", method="POST", path_template=f"{base}/relationships",
                description=f"Adds a relationship from a {label} to a record of this project.",
                params=[_PROJECT_ID_PARAM, holder_param, *kind_body],
            ),
            McpToolDefinition(
                name=f"remove_{holder}_relationship", method="DELETE", path_template=f"{base}/relationships/{{link_id}}",
                description=f"Removes one of a {label}'s relationships (the link only).",
                params=[_PROJECT_ID_PARAM, holder_param, link_id],
            ),
        ]
    stakeholder_base = f"{prefix}/stakeholders/{{stakeholder_id}}"
    need_base = f"{prefix}/needs/{{need_id}}"
    tools += [
        McpToolDefinition(
            name="list_stakeholder_personas", method="GET", path_template=f"{stakeholder_base}/personas",
            description="Lists the Personas a Stakeholder represents.", params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM],
        ),
        McpToolDefinition(
            name="add_stakeholder_persona", method="POST", path_template=f"{stakeholder_base}/personas",
            description="Records that a project-scoped Stakeholder represents a Persona.",
            params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM, _body("persona_id", "uuid", "The Persona.", required=True)],
        ),
        McpToolDefinition(
            name="remove_stakeholder_persona", method="DELETE", path_template=f"{stakeholder_base}/personas/{{persona_id}}",
            description="Removes a Stakeholder's \"represents\" link to a Persona (the link only).",
            params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM, _PERSONA_ID_PARAM],
        ),
        McpToolDefinition(
            name="list_need_holders", method="GET", path_template=f"{need_base}/holders",
            description="Lists the Stakeholders and Personas that have a Stakeholder Need.",
            params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM],
        ),
        McpToolDefinition(
            name="add_need_holder", method="POST", path_template=f"{need_base}/holders",
            description="Records that a Stakeholder or Persona has a Stakeholder Need.",
            params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM,
                    _body("kind", "string", "stakeholder or persona.", required=True),
                    _body("id", "uuid", "The Stakeholder's or Persona's id.", required=True)],
        ),
        McpToolDefinition(
            name="remove_need_holder", method="DELETE", path_template=f"{need_base}/holders/{{kind}}/{{holder_id}}",
            description="Removes a \"has need\" link (the link only).",
            params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM,
                    {"name": "kind", "type": "string", "required": True, "in": "path", "description": "stakeholder or persona."},
                    _path("holder_id", "The Stakeholder's or Persona's id.")],
        ),
        McpToolDefinition(
            name="list_need_requirements", method="GET", path_template=f"{need_base}/requirements",
            description="Lists the Requirements a Stakeholder Need gave rise to.", params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM],
        ),
        McpToolDefinition(
            name="add_need_requirement", method="POST", path_template=f"{need_base}/requirements",
            description="Records that a Stakeholder Need gave rise to a Requirement of this project.",
            params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM, _body("requirement_id", "uuid", "The Requirement.", required=True)],
        ),
        McpToolDefinition(
            name="remove_need_requirement", method="DELETE", path_template=f"{need_base}/requirements/{{requirement_id}}",
            description="Removes a \"gives rise to\" link (the link only).",
            params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM, _path("requirement_id", "The Requirement.")],
        ),
    ]
    return tuple(tools)


def _build_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """Persona, Stakeholder and Stakeholder Need read and write tools (no approval-gated action
    exists, so no `require_ai_approvals_enabled` handling is needed). There is
    deliberately no MCP tool for erasing a stakeholder: irreversible deletion
    of personal data stays a human action in the UI."""
    persona_path = f"{_PROJECT_ROUTER_PREFIX}/personas/{{persona_id}}"
    stakeholder_path = f"{_PROJECT_ROUTER_PREFIX}/stakeholders/{{stakeholder_id}}"
    need_path = f"{_PROJECT_ROUTER_PREFIX}/needs/{{need_id}}"
    return _build_link_mcp_tools() + (
        McpToolDefinition(
            name="list_personas",
            description=(
                "Lists a project's Personas, including its organisation's shared ones except those hidden from the "
                "project (pass include_hidden=true to list those too, flagged by project_hidden)."
            ),
            method="GET", path_template=f"{_PROJECT_ROUTER_PREFIX}/personas",
            params=[_PROJECT_ID_PARAM, {
                "name": "include_hidden", "type": "boolean", "required": False, "in": "query",
                "description": "Also list organisation Personas hidden from this project.",
            }],
        ),
        McpToolDefinition(
            name="set_persona_visibility",
            description=(
                "Hides an organisation Persona from this project (hidden=true), or shows it again where an ancestor "
                "project hides it (hidden=false). A hidden Persona is no longer scored or linkable here. Only this "
                "project's override changes; the shared Persona and its links are untouched."
            ),
            method="PUT", path_template=f"{persona_path}/visibility",
            params=[_PROJECT_ID_PARAM, _PERSONA_ID_PARAM,
                    _body("hidden", "boolean", "True to hide from this project, false to show it.", required=True)],
        ),
        McpToolDefinition(
            name="reset_persona_visibility",
            description="Removes this project's visibility override for an organisation Persona, reverting to the inherited state.",
            method="DELETE", path_template=f"{persona_path}/visibility",
            params=[_PROJECT_ID_PARAM, _PERSONA_ID_PARAM],
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
        McpToolDefinition(
            name="list_stakeholders",
            description=(
                "Lists a project's Stakeholders, including its organisation's shared ones except those hidden from "
                "the project (pass include_hidden=true to list those too, flagged by project_hidden)."
            ),
            method="GET", path_template=f"{_PROJECT_ROUTER_PREFIX}/stakeholders",
            params=[_PROJECT_ID_PARAM, {
                "name": "include_hidden", "type": "boolean", "required": False, "in": "query",
                "description": "Also list organisation Stakeholders hidden from this project.",
            }],
        ),
        McpToolDefinition(
            name="set_stakeholder_visibility",
            description=(
                "Hides an organisation Stakeholder from this project (hidden=true), or shows it again where an "
                "ancestor project hides it (hidden=false). Only this project's override changes; the shared "
                "Stakeholder, its links and needs are untouched."
            ),
            method="PUT", path_template=f"{stakeholder_path}/visibility",
            params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM,
                    _body("hidden", "boolean", "True to hide from this project, false to show it.", required=True)],
        ),
        McpToolDefinition(
            name="reset_stakeholder_visibility",
            description="Removes this project's visibility override for an organisation Stakeholder, reverting to the inherited state.",
            method="DELETE", path_template=f"{stakeholder_path}/visibility",
            params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM],
        ),
        McpToolDefinition(
            name="get_stakeholder", description="Fetches a single Stakeholder.", method="GET",
            path_template=stakeholder_path, params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM],
        ),
        McpToolDefinition(
            name="create_stakeholder", description="Creates a project-scoped Stakeholder in Draft status.",
            method="POST", path_template=f"{_PROJECT_ROUTER_PREFIX}/stakeholders",
            params=[_PROJECT_ID_PARAM, _body("name", "string", "Display name.", required=True),
                    *_STAKEHOLDER_FIELD_PARAMS],
        ),
        McpToolDefinition(
            name="update_stakeholder",
            description="Updates a project-scoped Stakeholder; only the fields supplied change.", method="PUT",
            path_template=stakeholder_path,
            params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM, _body("name", "string", "Display name."),
                    *_STAKEHOLDER_FIELD_PARAMS, _body("change_note", "string", "Reason for the change.")],
        ),
        McpToolDefinition(
            name="activate_stakeholder", description="Moves a Draft or Retired Stakeholder to Active.",
            method="POST", path_template=f"{stakeholder_path}/activate",
            params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM, _body("comment", "string", "Optional comment.")],
        ),
        McpToolDefinition(
            name="retire_stakeholder", description="Moves a Draft or Active Stakeholder to Retired.",
            method="POST", path_template=f"{stakeholder_path}/retire",
            params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM, _body("comment", "string", "Optional comment.")],
        ),
        McpToolDefinition(
            name="list_stakeholder_needs", description="Lists a project's Stakeholder Needs.", method="GET",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/needs", params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="get_stakeholder_need", description="Fetches a single Stakeholder Need.", method="GET",
            path_template=need_path, params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM],
        ),
        McpToolDefinition(
            name="create_stakeholder_need", description="Creates a Stakeholder Need in Draft status.", method="POST",
            path_template=f"{_PROJECT_ROUTER_PREFIX}/needs",
            params=[_PROJECT_ID_PARAM, _body("name", "string", "Short title of the need.", required=True),
                    *_NEED_FIELD_PARAMS],
        ),
        McpToolDefinition(
            name="update_stakeholder_need",
            description="Updates a Stakeholder Need; only the fields supplied change.", method="PUT",
            path_template=need_path,
            params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM, _body("name", "string", "Short title of the need."),
                    *_NEED_FIELD_PARAMS, _body("change_note", "string", "Reason for the change.")],
        ),
        McpToolDefinition(
            name="activate_stakeholder_need", description="Moves a Draft or Retired Stakeholder Need to Active.",
            method="POST", path_template=f"{need_path}/activate",
            params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM, _body("comment", "string", "Optional comment.")],
        ),
        McpToolDefinition(
            name="retire_stakeholder_need", description="Moves a Draft or Active Stakeholder Need to Retired.",
            method="POST", path_template=f"{need_path}/retire",
            params=[_PROJECT_ID_PARAM, _NEED_ID_PARAM, _body("comment", "string", "Optional comment.")],
        ),
    )


# Hand-written agent usage guidance, embedded in the MCP skill (see ModuleDefinition.mcp_guidance).
_MCP_GUIDANCE = (Path(__file__).parent / "mcp_guidance.md").read_text(encoding="utf-8")


MODULE_DEFINITION = ModuleDefinition(
    key=STAKEHOLDERS_MODULE_KEY,
    name="Stakeholders & Personas",
    description=(
        "Record Personas — representative user archetypes with goals, needs, behaviours and an importance weight "
        "— and Stakeholders — the people and groups with an interest in the project, rated on Influence and "
        "Interest — at organisation or project level, with configurable types, a Draft/Active/Retired lifecycle "
        "and full version history. A Stakeholder can represent Personas; Personas are the targets Pain Points are "
        "scored against. Stakeholder Needs record what a Stakeholder or Persona needs, separately from the "
        "Requirements it gave rise to."
    ),
    version="0.3.0",
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
        additional_nav_entries=(
            ModuleNavEntry(
                nav_label="Stakeholders",
                nav_path=f"/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}/stakeholders",
                nav_icon="user-round",
            ),
            ModuleNavEntry(
                nav_label="Needs",
                nav_path=f"/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}/needs",
                nav_icon="target",
            ),
        ),
    ),
    artefact_types=(PERSONA_ARTEFACT_TYPE, STAKEHOLDER_ARTEFACT_TYPE, NEED_ARTEFACT_TYPE),
    artefact_ids_in_organization=_artefact_ids_in_organization,
    sub_components=(
        ModuleSubComponentDefinition(key="persona", name="Personas", default_enabled=True),
        ModuleSubComponentDefinition(key="stakeholder", name="Stakeholders", default_enabled=True),
        ModuleSubComponentDefinition(key="stakeholder_need", name="Stakeholder Needs", default_enabled=True),
    ),
    scoring_schemes=(STAKEHOLDER_SCORING_SCHEME,),
    scoring_target_providers={PERSONA_ARTEFACT_TYPE: persona_scoring_targets},
    org_bundle_hooks=ModuleOrgBundleHooks(export=_export_org, import_=_import_org),
    project_bundle_hooks=ModuleProjectBundleHooks(export=_export_project, import_=_import_project),
    roles=(
        ModuleRoleDefinition(
            role_key="persona_owner", name="Persona Owner",
            description=(
                "Creates, edits, retires and re-weights project-scoped Personas, manages the project's Persona "
                "types, and hides organisation Personas from the project."
            ),
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
        ModuleRoleDefinition(
            role_key="stakeholder_owner", name="Stakeholder Owner",
            description=(
                "Creates, edits, retires and permanently deletes project-scoped Stakeholders, manages their "
                "Persona links, manages the project's Stakeholder types, and hides organisation Stakeholders "
                "from the project."
            ),
            scope="project", permissions=(STAKEHOLDER_MANAGE_PERMISSION,),
        ),
        ModuleRoleDefinition(
            role_key="org_stakeholder_owner", name="Organisation Stakeholder Owner",
            description=(
                "Creates, edits, retires and permanently deletes organisation-scoped Stakeholders shared by every "
                "project in the organisation."
            ),
            # Deliberately carries no FGAC atom, for the same reason `org_persona_owner` carries none.
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="stakeholder_type_admin", name="Stakeholder Type Admin",
            description=(
                "Manages the organisation's shared Stakeholder type vocabulary and the Influence/Interest scoring "
                "levels, default model and rating bands."
            ),
            scope="org",
        ),
        ModuleRoleDefinition(
            role_key="stakeholder_need_owner", name="Stakeholder Need Owner",
            description=(
                "Creates, edits and retires the project's Stakeholder Needs and links them to the Stakeholders and "
                "Personas that have them and the Requirements they gave rise to."
            ),
            scope="project", permissions=(NEED_MANAGE_PERMISSION,),
        ),
    ),
    mcp_guidance=_MCP_GUIDANCE,
    mcp_tools=_build_mcp_tools(),
)
