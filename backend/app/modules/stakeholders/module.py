"""
Module: modules.stakeholders.module

Registers the Stakeholders & Personas module into the modular feature
system's registry via `MODULE_DEFINITION`. It delivers the Persona, Stakeholder and
Stakeholder Need artefacts, the Engagement contact log and the research extras.

Registered contributions:
- Roles (not additions to core enums): `persona_owner` (project) and
  `org_persona_owner` (org) gate create/edit/archive/retire; only the project
  role carries the FGAC `(persona, manage)` atom, since an org-level role's
  atoms would apply to every project; `persona_type_admin` (org) gates the org
  Persona type vocabulary. There is no approver role because Personas have no
  approval gate.
- The same trio for Stakeholders: `stakeholder_owner` (project, carries the FGAC
  `(stakeholder, manage)` atom), `org_stakeholder_owner` (org, no atom) and
  `stakeholder_type_admin` (org; also administers the `stakeholder` scoring
  scheme's levels and bands).
- `stakeholder_need_owner` (project; carries the FGAC `(stakeholder_need, manage)`
  atom) for Stakeholder Needs, which are project-scoped only so have no org role.
- `engagement_owner` (project; carries the FGAC `(engagement, manage)` atom) for
  Engagements, which are project-scoped only so have no org role.
- `artefact_types=("persona", "stakeholder", "stakeholder_need", "stakeholder_group",
  "engagement", "research_finding")` so all six are valid `ArtefactLink` endpoints and
  get FGAC atoms. Groups have no role of their own: they are managed with
  the Stakeholder gate.
- `scoring_schemes`: the Influence × Interest `stakeholder` scheme (`scoring.py`).
- `scoring_target_providers["persona"]`: the generic hook Context & Strategy's
  per-persona Pain Point scoring reads, so Context &
  Strategy never imports this module.
- `on_org_created` seeds each new organisation's default Persona and
  Stakeholder types; the migrations backfill existing organisations.
- Org and project bundle hooks (`export.py` for Personas,
  `stakeholder_export.py` for Stakeholders, composed here — Personas first,
  since Stakeholders link to them) so both travel with an organisation/project
  export.
- Four sub-components, `persona`, `stakeholder`, `stakeholder_need` and
  `research_extras` (session prompts, anonymous participants and findings; off by
  default), so a project can switch any off without disabling the whole module. The
  Engagement log itself is always on with the module.
- Nav: one "People" entry (Personas, Stakeholders, Needs and Groups on one page, shown while any of the
  three sub-components is on, `nav_sub_components_any`) and "Engagements".
- `reports`: five project-level reports (`reports.py`: S1 power/interest grid,
  S2 Persona validation, S3 Need coverage, S4 Engagement staleness, S5 Engagement &
  research yield); the framework generates their routes, catalogue entries and
  `get_<slug>_report` MCP tools.

`default_enabled=False`: an organisation opts in explicitly, matching the
other new modules.
"""

from __future__ import annotations

from functools import cache
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
    PrincipalReference,
)
from app.modules.stakeholders import engagement_export, need_export, relationship_export, stakeholder_export
from app.modules.stakeholders import export as persona_export
from app.modules.stakeholders._engagement_shared import ENGAGEMENT_MANAGE_PERMISSION
from app.modules.stakeholders._need_shared import NEED_MANAGE_PERMISSION
from app.modules.stakeholders._shared import PERSONA_MANAGE_PERMISSION
from app.modules.stakeholders._stakeholder_shared import STAKEHOLDER_MANAGE_PERMISSION
from app.modules.stakeholders.engagements import ENGAGEMENT_ARTEFACT_TYPE, FINDING_ARTEFACT_TYPE, RESEARCH_SUBCOMPONENT
from app.modules.stakeholders.groups import GROUP_ARTEFACT_TYPE
from app.modules.stakeholders.models import (
    Engagement,
    EngagementFacilitator,
    PersonaVersion,
    StakeholderNeedVersion,
    StakeholderVersion,
)
from app.modules.stakeholders.record_tables import RECORD_TABLES
from app.modules.stakeholders.relationships import LINK_TYPE_SEEDS
from app.modules.stakeholders.report_fields import REPORT_FIELDS
from app.modules.stakeholders.report_starters import REPORT_STARTER_SECTIONS
from app.modules.stakeholders.reports import REPORT_DEFINITIONS, REPORT_ROUTERS
from app.modules.stakeholders.scoring import STAKEHOLDER_SCORING_SCHEME
from app.modules.stakeholders.search import SEARCH_PROVIDERS
from app.modules.stakeholders.service import (
    NEED_ARTEFACT_TYPE,
    PERSONA_ARTEFACT_TYPE,
    PERSONA_TYPES,
    STAKEHOLDER_ARTEFACT_TYPE,
    STAKEHOLDER_TYPES,
    STAKEHOLDERS_MODULE_KEY,
    persona_scoring_targets,
)
from app.modules.stakeholders.summaries import ARTEFACT_SUMMARY_PROVIDERS, ARTEFACT_TYPE_LABELS
from app.services.report_framework import report_mcp_tools

_PROJECT_ROUTER_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}"


def _principal_references() -> tuple[PrincipalReference, ...]:
    """The owner, champion and facilitator fields, which may name a user or a group (`services.principals`).
    They live on the version rows, so only the current version of each record is counted or
    reassigned (`live_filter`); the audit event is about the record (`record_id_field`)."""
    def current(model):
        return lambda: model.valid_to.is_(None)

    return (
        PrincipalReference(
            model=PersonaVersion, field="owner", label="persona owners", audit_entity_type=PERSONA_ARTEFACT_TYPE,
            live_filter=current(PersonaVersion), record_id_field="persona_id",
        ),
        PrincipalReference(
            model=PersonaVersion, field="champion", label="persona champions",
            audit_entity_type=PERSONA_ARTEFACT_TYPE, live_filter=current(PersonaVersion),
            record_id_field="persona_id",
        ),
        PrincipalReference(
            model=StakeholderVersion, field="owner", label="stakeholder owners",
            audit_entity_type=STAKEHOLDER_ARTEFACT_TYPE, live_filter=current(StakeholderVersion),
            record_id_field="stakeholder_id",
        ),
        PrincipalReference(
            model=StakeholderNeedVersion, field="owner", label="stakeholder need owners",
            audit_entity_type=NEED_ARTEFACT_TYPE, live_filter=current(StakeholderNeedVersion),
            record_id_field="need_id",
        ),
        PrincipalReference(
            model=EngagementFacilitator, field="facilitator", label="engagement facilitators",
            audit_entity_type=ENGAGEMENT_ARTEFACT_TYPE, record_id_field="engagement_id", multi_valued=True,
        ),
    )


@cache
def get_router() -> APIRouter | None:
    """The org-scoped router (Persona + Stakeholder routes); imported lazily
    to avoid import cycles with this module's own registration. Built once:
    combining the sub-routers re-creates every route's validation model, and
    callers (the report catalogue, route listings) ask on every request."""
    from app.modules.stakeholders.group_router import router as group_router
    from app.modules.stakeholders.router import router
    from app.modules.stakeholders.stakeholder_router import router as stakeholder_router

    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(stakeholder_router)
    combined.include_router(group_router)
    return combined


@cache
def get_project_router() -> APIRouter | None:
    """The project-scoped router (Persona + Stakeholder routes); imported
    lazily like `get_router`, and built once for the same reason (about three
    seconds per build, which made every Reports page load wait that long)."""
    from app.modules.stakeholders.engagement_project_router import router as engagement_router
    from app.modules.stakeholders.group_project_router import router as group_router
    from app.modules.stakeholders.need_project_router import router as need_router
    from app.modules.stakeholders.project_router import router
    from app.modules.stakeholders.relationship_project_router import router as relationship_router
    from app.modules.stakeholders.research_project_router import router as research_router
    from app.modules.stakeholders.stakeholder_project_router import router as stakeholder_router

    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(stakeholder_router)
    combined.include_router(need_router)
    combined.include_router(relationship_router)
    combined.include_router(group_router)
    combined.include_router(engagement_router)
    combined.include_router(research_router)
    combined.include_router(REPORT_ROUTERS.project, prefix=_PROJECT_ROUTER_PREFIX)
    return combined


def resolve_file_owner_project_id(db: Session, file_id: UUID) -> UUID | None:
    """`ModuleDefinition.resolve_file_owner_project_id`: the project owning a
    file attached to a project-scoped persona, stakeholder, need or engagement (or its
    comment), else `None`."""
    from app.modules.stakeholders.engagements import resolve_engagement_file_project_id
    from app.modules.stakeholders.service import (
        resolve_need_file_project_id,
        resolve_persona_file_project_id,
        resolve_stakeholder_file_project_id,
    )

    return (
        resolve_persona_file_project_id(db, file_id) or resolve_stakeholder_file_project_id(db, file_id)
        or resolve_need_file_project_id(db, file_id) or resolve_engagement_file_project_id(db, file_id)
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
    engagement_data, engagement_assets = engagement_export.export_project_data(db, project)
    return (
        {**persona_data, **stakeholder_data, **need_data, **relationship_data, **engagement_data},
        {**persona_assets, **stakeholder_assets, **need_assets, **engagement_assets},
    )


def _import_project(db, project, data, file_bytes_by_ref, current_user, users, warnings) -> None:
    """Project bundle import: Personas, then Stakeholders (which link to them),
    then Needs (which link to both), then the §10.5 relationships (which need
    all of those plus other modules' Pain Points and Decisions), then Engagements
    (which link to Stakeholders, Personas, groups, Needs and other modules' Pain Points)."""
    persona_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)
    stakeholder_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)
    need_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)
    relationship_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)
    engagement_export.import_project_data(db, project, data, file_bytes_by_ref, current_user, users, warnings)


def _artefact_ids_in_organization(db: Session, organization_id: UUID) -> set[UUID]:
    """`ModuleDefinition.artefact_ids_in_organization`: every persona,
    stakeholder, need, group, engagement and finding in the organisation, org-scoped or in one of its
    projects, for org deletion's polymorphic cleanup."""
    from app.models.project import Project
    from app.modules.stakeholders.models import (
        Persona,
        ResearchFinding,
        Stakeholder,
        StakeholderGroup,
        StakeholderNeed,
    )

    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    ids: set[UUID] = set()
    for model in (Persona, Stakeholder):
        ids |= set(db.scalars(select(model.id).where(
            or_(model.organization_id == organization_id, model.project_id.in_(project_ids))
        )).all())
    ids |= set(db.scalars(select(StakeholderNeed.id).where(StakeholderNeed.project_id.in_(project_ids))).all())
    ids |= set(db.scalars(select(Engagement.id).where(Engagement.project_id.in_(project_ids))).all())
    ids |= set(db.scalars(select(ResearchFinding.id).where(ResearchFinding.project_id.in_(project_ids))).all())
    ids |= set(db.scalars(select(StakeholderGroup.id).where(
        or_(StakeholderGroup.organization_id == organization_id, StakeholderGroup.project_id.in_(project_ids))
    )).all())
    return ids


_PROJECT_ID_PARAM = {
    "name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The owning project.",
}
_PERSONA_ID_PARAM = {
    "name": "persona_id", "type": "uuid", "required": True, "in": "path", "description": "The Persona.",
}


def _body(name: str, type_: str, description: str, *, required: bool = False) -> dict:
    return {"name": name, "type": type_, "required": required, "in": "body", "description": description}


def _principal_description(what: str) -> str:
    """Tool-parameter text for a principal field: `{"type": "user" | "org_group" | "project_group", "id": uuid}`."""
    return (
        f"Who {what}: {{\"type\": \"user\" | \"org_group\" | \"project_group\", \"id\": uuid}}. A project group is only "
        "valid on a project-scoped record; null clears it."
    )


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
    _body("owner", "object", _principal_description("owns this record")),
    _body("champion", "object", _principal_description("is accountable for keeping this persona accurate")),
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
    _body("owner", "object", _principal_description("owns this record")),
    _body("user_id", "uuid", "The platform user this stakeholder is, if any."),
]


_NEED_ID_PARAM = {
    "name": "need_id", "type": "uuid", "required": True, "in": "path", "description": "The Stakeholder Need.",
}

_NEED_FIELD_PARAMS = [
    _body("description", "string", "The need in the stakeholder's own words."),
    _body("rationale", "string", "Why it matters, its source or evidence."),
    _body("owner", "object", _principal_description("owns this record")),
]


def _path(name: str, description: str) -> dict:
    return {"name": name, "type": "uuid", "required": True, "in": "path", "description": description}


def _query(name: str, type_: str, description: str) -> dict:
    return {"name": name, "type": type_, "required": True, "in": "query", "description": description}


def _build_link_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """Link tools: the §10.5 relationships, "represents Persona", "has
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


def _build_group_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """Stakeholder group tools. Writes act on this project's own groups; the organisation's
    groups are read-only here (an org admin edits them in the UI). Deleting a group keeps its
    Stakeholders and moves its child groups up."""
    base = f"{_PROJECT_ROUTER_PREFIX}/stakeholder-groups"
    group_param = _path("group_id", "The Stakeholder group.")
    return (
        McpToolDefinition(
            name="list_stakeholder_groups", method="GET", path_template=base,
            description=(
                "Lists the Stakeholder groups this project can see (the organisation's and its own), flat, with "
                "parent_group_id for the tree, exclusive_children and direct member counts."
            ),
            params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="create_stakeholder_group", method="POST", path_template=base,
            description="Creates a project Stakeholder group, optionally under an organisation group or one of this project's.",
            params=[_PROJECT_ID_PARAM, _body("name", "string", "Group name, unique among its siblings.", required=True),
                    _body("description", "string", "Free-text description."),
                    _body("parent_group_id", "uuid", "The parent group; omit for a top-level group."),
                    _body("exclusive_children", "boolean", "A Stakeholder may sit in at most one direct child branch.")],
        ),
        McpToolDefinition(
            name="update_stakeholder_group", method="PATCH", path_template=f"{base}/{{group_id}}",
            description="Renames, re-describes, re-flags or moves one of this project's Stakeholder groups; only supplied fields change.",
            params=[_PROJECT_ID_PARAM, group_param, _body("name", "string", "New name."),
                    _body("description", "string", "New description."),
                    _body("parent_group_id", "uuid", "New parent; null moves it to the top level."),
                    _body("exclusive_children", "boolean", "Whether children are mutually exclusive.")],
        ),
        McpToolDefinition(
            name="delete_stakeholder_group", method="DELETE", path_template=f"{base}/{{group_id}}",
            description="Deletes one of this project's Stakeholder groups. Memberships go, Stakeholders stay, child groups move up.",
            params=[_PROJECT_ID_PARAM, group_param],
        ),
        McpToolDefinition(
            name="add_stakeholder_to_group", method="POST", path_template=f"{base}/{{group_id}}/members",
            description=(
                "Adds a Stakeholder to one of this project's groups (409 if already in it, or if an exclusive "
                "parent already holds them in another branch)."
            ),
            params=[_PROJECT_ID_PARAM, group_param, _body("stakeholder_id", "uuid", "The Stakeholder.", required=True)],
        ),
        McpToolDefinition(
            name="remove_stakeholder_from_group", method="DELETE", path_template=f"{base}/{{group_id}}/members/{{stakeholder_id}}",
            description="Removes a Stakeholder from one of this project's groups (the membership only).",
            params=[_PROJECT_ID_PARAM, group_param, _STAKEHOLDER_ID_PARAM],
        ),
    )


def _build_engagement_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """Engagement log and research-extras tools. Writes need the same Engagement Owner role as the REST
    endpoints. There is deliberately no tool to delete an engagement, finding, prompt or anonymous participant:
    irreversible deletion of possible personal data stays a human action in the UI. Removing a link removes only
    the link."""
    prefix = _PROJECT_ROUTER_PREFIX
    base = f"{prefix}/engagements"
    one = f"{base}/{{engagement_id}}"
    engagement = _path("engagement_id", "The Engagement.")
    finding = _path("finding_id", "The research finding.")
    optional_query = lambda name, type_, description: {  # noqa: E731
        "name": name, "type": type_, "required": False, "in": "query", "description": description,
    }
    fields = [
        _body("channel", "string", "email, call, meeting, workshop, interview, focus_group, usability_test or survey."),
        _body("engagement_date", "string", "When it took place, ISO date (YYYY-MM-DD)."),
        _body(
            "facilitators", "array",
            "Everyone who ran it: a list of {\"type\": \"user\" | \"org_group\" | \"project_group\", \"id\": uuid}. "
            "On update the list replaces the current one ([] or null removes everyone), so send everyone who should remain.",
        ),
        _body("purpose", "string", "What it was for / the topics in scope."),
        _body("summary", "string", "A short outcome."),
        _body("notes", "string", "Notes. May quote participants: Confidential personal data."),
        _body("consent_recorded", "boolean", "Whether participants consented to the record being kept."),
        _body("retain_until", "string", "ISO date after which the record is due for disposal; null clears it."),
    ]
    create_fields = [
        _body("title", "string", "Short title.", required=True),
        {**fields[0], "required": True}, {**fields[1], "required": True}, *fields[2:],
        _body("stakeholder_ids", "array", "Stakeholder ids to add as participants."),
        _body("persona_ids", "array", "Persona ids the engagement covered."),
        _body("group_ids", "array", "Stakeholder group ids it was aimed at; each is expanded to its current members."),
    ]
    outcome_body = [
        _body("kind", "string", "raised (Pain Point, Need or Open Question) or answered (Open Question).", required=True),
        _body("target_type", "string", "pain_point, stakeholder_need or open_question.", required=True),
        _body("target_id", "uuid", "The record's id (it must belong to this project).", required=True),
    ]
    tools: list[McpToolDefinition] = [
        McpToolDefinition(
            name="list_engagements", method="GET", path_template=base,
            description="Lists a project's Engagements (the contact log), most recent first, with the filters given.",
            params=[
                _PROJECT_ID_PARAM, optional_query("channel", "string", "Only this channel."),
                optional_query("stakeholder_id", "uuid", "Only engagements this Stakeholder took part in."),
                optional_query("persona_id", "uuid", "Only engagements that covered this Persona."),
                optional_query("date_from", "string", "Only on or after this ISO date."),
                optional_query("date_to", "string", "Only on or before this ISO date."),
                optional_query("retention_due", "boolean", "true: only those whose retain-until date has been reached."),
            ],
        ),
        McpToolDefinition(
            name="get_engagement", method="GET", path_template=one, description="Fetches a single Engagement.",
            params=[_PROJECT_ID_PARAM, engagement],
        ),
        McpToolDefinition(
            name="create_engagement", method="POST", path_template=base,
            description=(
                "Logs an Engagement (a contact with stakeholders or personas), optionally with its participants, "
                "covered personas and audience groups in one call."
            ),
            params=[_PROJECT_ID_PARAM, *create_fields],
        ),
        McpToolDefinition(
            name="update_engagement", method="PUT", path_template=one,
            description="Updates an Engagement; only the fields supplied change.",
            params=[_PROJECT_ID_PARAM, engagement, _body("title", "string", "Short title."), *fields],
        ),
        McpToolDefinition(
            name="list_stakeholder_engagements", method="GET",
            path_template=f"{prefix}/stakeholders/{{stakeholder_id}}/engagements",
            description="Lists this project's Engagements a Stakeholder took part in, most recent first (their timeline).",
            params=[_PROJECT_ID_PARAM, _STAKEHOLDER_ID_PARAM],
        ),
    ]
    for noun, plural, label in (
        ("participant", "participants", "Stakeholders who took part"),
        ("persona", "personas", "Personas the engagement covered"),
        ("audience", "audiences", "Stakeholder groups the engagement was aimed at"),
    ):
        key, key_label = {
            "participant": ("stakeholder_id", "The Stakeholder."), "persona": ("persona_id", "The Persona."),
            "audience": ("group_id", "The Stakeholder group."),
        }[noun]
        extra = (
            " Adding a group also adds its current members as participants (a snapshot)." if noun == "audience" else ""
        )
        tools += [
            McpToolDefinition(
                name=f"list_engagement_{plural}", method="GET", path_template=f"{one}/{plural}",
                description=f"Lists the {label}.", params=[_PROJECT_ID_PARAM, engagement],
            ),
            McpToolDefinition(
                name=f"add_engagement_{noun}", method="POST", path_template=f"{one}/{plural}",
                description=f"Adds one of the {label}.{extra}",
                params=[_PROJECT_ID_PARAM, engagement, _body(key, "uuid", key_label, required=True)],
            ),
            McpToolDefinition(
                name=f"remove_engagement_{noun}", method="DELETE", path_template=f"{one}/{plural}/{{{key}}}",
                description=f"Removes one of the {label} (the link only{'; participants it added stay' if noun == 'audience' else ''}).",
                params=[_PROJECT_ID_PARAM, engagement, _path(key, key_label)],
            ),
        ]
    tools += [
        McpToolDefinition(
            name="list_engagement_outcomes", method="GET", path_template=f"{one}/outcomes",
            description="Lists the Pain Points, Needs and Open Questions an Engagement raised or answered.",
            params=[_PROJECT_ID_PARAM, engagement],
        ),
        McpToolDefinition(
            name="add_engagement_outcome", method="POST", path_template=f"{one}/outcomes",
            description="Records that an Engagement raised or answered a record of this project.",
            params=[_PROJECT_ID_PARAM, engagement, *outcome_body],
        ),
        McpToolDefinition(
            name="remove_engagement_outcome", method="DELETE", path_template=f"{one}/outcomes/{{link_id}}",
            description="Removes a raised/answered link (the link only).",
            params=[_PROJECT_ID_PARAM, engagement, _path("link_id", "The outcome's link id (from the list tool).")],
        ),
        # Research extras (the `research_extras` sub-component).
        McpToolDefinition(
            name="list_engagement_prompts", method="GET", path_template=f"{one}/prompts",
            description="Lists an Engagement's session prompts in order (research extras).",
            params=[_PROJECT_ID_PARAM, engagement],
        ),
        McpToolDefinition(
            name="add_engagement_prompt", method="POST", path_template=f"{one}/prompts",
            description="Appends a session prompt with optional response notes (research extras).",
            params=[_PROJECT_ID_PARAM, engagement, _body("prompt", "string", "The question or topic.", required=True),
                    _body("response_notes", "string", "What was said in response.")],
        ),
        McpToolDefinition(
            name="update_engagement_prompt", method="PATCH", path_template=f"{one}/prompts/{{prompt_id}}",
            description="Edits a session prompt or its response notes; only fields supplied change (research extras).",
            params=[_PROJECT_ID_PARAM, engagement, _path("prompt_id", "The prompt."),
                    _body("prompt", "string", "The question or topic."), _body("response_notes", "string", "Response notes.")],
        ),
        McpToolDefinition(
            name="list_anonymous_participants", method="GET", path_template=f"{one}/anonymous-participants",
            description="Lists an Engagement's anonymous participants (research extras).",
            params=[_PROJECT_ID_PARAM, engagement],
        ),
        McpToolDefinition(
            name="add_anonymous_participant", method="POST", path_template=f"{one}/anonymous-participants",
            description=(
                "Adds a participant who has no Stakeholder record: a label (e.g. 'Participant 3') and, optionally, "
                "the Persona they represent (research extras). Do not put names or contact details in the label."
            ),
            params=[_PROJECT_ID_PARAM, engagement, _body("label", "string", "Anonymous label.", required=True),
                    _body("persona_id", "uuid", "The Persona they represent.")],
        ),
        McpToolDefinition(
            name="list_research_findings", method="GET", path_template=f"{prefix}/findings",
            description="Lists every research finding in a project, newest first (research extras).",
            params=[_PROJECT_ID_PARAM],
        ),
        McpToolDefinition(
            name="list_engagement_findings", method="GET", path_template=f"{one}/findings",
            description="Lists the findings of one Engagement (research extras).", params=[_PROJECT_ID_PARAM, engagement],
        ),
        McpToolDefinition(
            name="create_research_finding", method="POST", path_template=f"{one}/findings",
            description="Records a finding from an Engagement (research extras).",
            params=[_PROJECT_ID_PARAM, engagement, _body("title", "string", "Short statement of the finding.", required=True),
                    _body("description", "string", "Evidence and detail.")],
        ),
        McpToolDefinition(
            name="update_research_finding", method="PUT", path_template=f"{prefix}/findings/{{finding_id}}",
            description="Updates a research finding; only the fields supplied change.",
            params=[_PROJECT_ID_PARAM, finding, _body("title", "string", "Short statement of the finding."),
                    _body("description", "string", "Evidence and detail.")],
        ),
        McpToolDefinition(
            name="list_finding_outcomes", method="GET", path_template=f"{prefix}/findings/{{finding_id}}/outcomes",
            description="Lists the Pain Points, Needs and Open Questions a finding raised or answered.",
            params=[_PROJECT_ID_PARAM, finding],
        ),
        McpToolDefinition(
            name="add_finding_outcome", method="POST", path_template=f"{prefix}/findings/{{finding_id}}/outcomes",
            description="Records that a finding raised or answered a record of this project.",
            params=[_PROJECT_ID_PARAM, finding, *outcome_body],
        ),
        McpToolDefinition(
            name="remove_finding_outcome", method="DELETE",
            path_template=f"{prefix}/findings/{{finding_id}}/outcomes/{{link_id}}",
            description="Removes a finding's raised/answered link (the link only).",
            params=[_PROJECT_ID_PARAM, finding, _path("link_id", "The outcome's link id (from the list tool).")],
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
    return _build_link_mcp_tools() + _build_group_mcp_tools() + _build_engagement_mcp_tools() + report_mcp_tools(
        REPORT_DEFINITIONS, project_router_prefix=_PROJECT_ROUTER_PREFIX,
    ) + (
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
            }, {
                "name": "group_id", "type": "uuid", "required": False, "in": "query",
                "description": "Only Stakeholders in this Stakeholder group or any group beneath it (see list_stakeholder_groups).",
            }, {
                "name": "direct_only", "type": "boolean", "required": False, "in": "query",
                "description": "With group_id: only Stakeholders directly in that group, not in groups beneath it.",
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
        "Requirements it gave rise to. Engagements log each contact with them, with who took part and what it "
        "raised, and optional research extras add session prompts, anonymous participants and findings."
    ),
    version="0.6.0",
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
        nav_label="People",
        nav_path=f"/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}/people",
        nav_icon="users",
        # One page lists Personas, Stakeholders, Needs and Groups: it stays while any of them is enabled.
        nav_sub_components_any=("persona", "stakeholder", "stakeholder_need"),
        additional_nav_entries=(
            ModuleNavEntry(
                nav_label="Engagements",
                nav_path=f"/projects/{{project_id}}/modules/{STAKEHOLDERS_MODULE_KEY}/engagements",
                nav_icon="messages-square",
            ),
        ),
    ),
    artefact_types=(
        PERSONA_ARTEFACT_TYPE, STAKEHOLDER_ARTEFACT_TYPE, NEED_ARTEFACT_TYPE, GROUP_ARTEFACT_TYPE,
        ENGAGEMENT_ARTEFACT_TYPE, FINDING_ARTEFACT_TYPE,
    ),
    artefact_summary_providers=ARTEFACT_SUMMARY_PROVIDERS,
    search_providers=SEARCH_PROVIDERS,
    report_fields=REPORT_FIELDS,
    report_starter_sections=REPORT_STARTER_SECTIONS,
    record_tables=RECORD_TABLES,
    artefact_type_labels=ARTEFACT_TYPE_LABELS,
    link_type_seeds=LINK_TYPE_SEEDS,
    artefact_ids_in_organization=_artefact_ids_in_organization,
    sub_components=(
        ModuleSubComponentDefinition(key="persona", name="Personas", default_enabled=True),
        ModuleSubComponentDefinition(key="stakeholder", name="Stakeholders", default_enabled=True),
        ModuleSubComponentDefinition(key="stakeholder_need", name="Stakeholder Needs", default_enabled=True),
        # Off by default: the engagement log is enough for most projects, and the extras (session prompts,
        # anonymous participants, findings) are for projects that run research sessions.
        ModuleSubComponentDefinition(key=RESEARCH_SUBCOMPONENT, name="Research extras", default_enabled=False),
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
        ModuleRoleDefinition(
            role_key="engagement_owner", name="Engagement Owner",
            description=(
                "Logs, edits and permanently deletes the project's Engagements, manages their participants, "
                "covered Personas, audience groups and attachments, and (with the research extras on) their "
                "session prompts, anonymous participants and findings."
            ),
            scope="project", permissions=(ENGAGEMENT_MANAGE_PERMISSION,),
        ),
    ),
    principal_references=_principal_references(),
    reports=REPORT_DEFINITIONS,
    mcp_guidance=_MCP_GUIDANCE,
    mcp_tools=_build_mcp_tools(),
)
