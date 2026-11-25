"""
Module: routers.lifecycles

Lifecycle configuration: which optional states of a record type a project uses, which an organisation requires and
which projects it exempts (`services.lifecycles`).

Responsibilities:
- Project: read every lifecycle of the project's enabled modules with its effective path and legal moves (any
  project member, because the record pages draw their track from it), set the project's own choice for one type and
  switch on skipping steps.
- Organisation: read the types with their required states and exemptions, set the required states of a type, add or
  remove an exempt project, and forbid skipping steps with its own exempt projects.

Design decisions:
- Changing needs a fine-grained permission (`manage_project_lifecycles`, held by project administrators, or
  `manage_org_lifecycles`), with no server-administrator bypass: the setting belongs to the customer's process.
- A module a project or organisation cannot use is left out of the response, so nobody is offered a switch that does
  nothing.
- A project's response is the same for every member; the organisation's requirement is stated, never hidden.

Dependencies: `services.lifecycles`, the module registry (labels and availability).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import LifecycleDefinition, artefact_type_module
from app.schemas.lifecycle import (
    ExemptionOut,
    ExemptionSet,
    LifecycleStateOut,
    OrgLifecycleOut,
    OrgLifecycleSet,
    OrgSkipOut,
    OrgSkipSet,
    ProjectLifecycleOut,
    ProjectLifecycleSet,
    ProjectLifecyclesOut,
    ProjectSkipOut,
    ProjectSkipSet,
)
from app.services import lifecycles
from app.services.lifecycles import ResolvedLifecycle
from app.services.lookups import project_or_404
from app.services.rbac import (
    MANAGE_ORG_LIFECYCLES,
    MANAGE_PROJECT_LIFECYCLES,
    get_effective_permissions,
    permission_satisfied,
    require_permission,
    require_project_view,
)

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/lifecycles", tags=["lifecycles"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/lifecycles", tags=["lifecycles"])

_manage_project = require_permission(MANAGE_PROJECT_LIFECYCLES, server_admin_bypass=False)
_manage_org = require_permission(MANAGE_ORG_LIFECYCLES, server_admin_bypass=False)


def _module_name(artefact_type: str) -> str:
    """The display name of the module that owns the type (an empty string for a core type)."""
    module = artefact_type_module(artefact_type)
    return "" if module is None else module.name


def _states(definition: LifecycleDefinition, keys: tuple[str, ...]) -> list[LifecycleStateOut]:
    """`keys` as state descriptions, with the type's optional and gated flags."""
    return [
        LifecycleStateOut(
            key=k, label=definition.labels.get(k, k), optional=k in definition.optional, gated=k in definition.gated
        )
        for k in keys
    ]


def _off_path(definition: LifecycleDefinition) -> tuple[str, ...]:
    """The states a type has outside its main path, in name order."""
    every = set(definition.transitions) | {n for ns in definition.transitions.values() for n in ns}
    return tuple(sorted(every - set(definition.path)))


def _project_out(resolved: ResolvedLifecycle, skip_allowed: bool) -> ProjectLifecycleOut:
    """One resolved lifecycle as the API shape; the skip moves are listed only when the project allows skipping."""
    definition = resolved.definition
    return ProjectLifecycleOut(
        artefact_type=resolved.artefact_type, label=definition.label, module_key=resolved.module_key,
        module_name=_module_name(resolved.artefact_type), path=_states(definition, definition.path),
        off_path=_states(definition, _off_path(definition)),
        own_disabled=None if resolved.own is None else [s for s in definition.optional if s in resolved.own],
        disabled=[s for s in definition.optional if s in resolved.disabled],
        required=[s for s in definition.optional if s in resolved.enforced], exempt=resolved.exempt,
        required_by_profiles={s: list(resolved.profile_required[s]) for s in definition.optional if s in resolved.profile_required},
        source=resolved.source, transitions=lifecycles.effective_transitions(resolved),
        skip_transitions=lifecycles.effective_skip_transitions(resolved) if skip_allowed else {},
    )


def _project_response(db: Session, project: Project, user: User) -> ProjectLifecyclesOut:
    """Every lifecycle of the project's enabled modules and the caller's right to change them."""
    from app.modules.registry import artefact_type_enabled_for_project

    resolved = lifecycles.resolve_project_lifecycles(db, project)
    policy = lifecycles.resolve_skip_policy(db, project)
    held = get_effective_permissions(db, user.id, project_id=project.id)
    return ProjectLifecyclesOut(
        can_manage=permission_satisfied(held, MANAGE_PROJECT_LIFECYCLES),
        has_parent=project.parent_project_id is not None,
        skip=ProjectSkipOut(
            allowed=policy.allowed, own=policy.own, chosen=policy.chosen, source=policy.source,
            forbidden=policy.enforced, exempt=policy.forbidden and policy.exempt and not policy.profile_forbidden_by,
            forbidden_by_profiles=list(policy.profile_forbidden_by),
        ),
        lifecycles=[
            _project_out(r, policy.allowed) for _, r in sorted(resolved.items())
            if artefact_type_enabled_for_project(db, r.artefact_type, project.id)
        ],
    )


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    """The organisation, or 404."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _org_response(db: Session, org: Organization) -> list[OrgLifecycleOut]:
    """The organisation's lifecycle types with their required states and exemptions."""
    rows = lifecycles.organization_lifecycles(db, org)
    project_ids = {pid for row in rows for pid, _ in row["exemptions"]}
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids)).all()} if project_ids else {}
    out: list[OrgLifecycleOut] = []
    for row in rows:
        definition: LifecycleDefinition = row["definition"]
        out.append(OrgLifecycleOut(
            artefact_type=row["artefact_type"], label=definition.label, module_key=row["module_key"],
            module_name=_module_name(row["artefact_type"]), states=_states(definition, definition.optional),
            required=row["required"],
            exemptions=[
                ExemptionOut(
                    project_id=pid, project_name=projects[pid].name, project_code=projects[pid].code,
                    include_children=include_children,
                )
                for pid, include_children in row["exemptions"] if pid in projects
            ],
        ))
    return out


# --- project ----------------------------------------------------------------------------------


@project_router.get("", response_model=ProjectLifecyclesOut)
def get_project_lifecycles(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ProjectLifecyclesOut:
    """Every lifecycle of the project's enabled modules, with the effective path and legal moves of each."""
    return _project_response(db, project_or_404(db, project_id), current_user)


@project_router.put("/skip", response_model=ProjectLifecyclesOut)
def set_project_skip(
    project_id: UUID, body: ProjectSkipSet,
    current_user: User = Depends(_manage_project), db: Session = Depends(get_db),
) -> ProjectLifecyclesOut:
    """Sets whether the project lets a record skip steps (`null` follows the nearest ancestor project, else off)."""
    project = project_or_404(db, project_id)
    lifecycles.set_project_skip(db, project=project, allowed=body.allowed, actor_id=current_user.id)
    db.commit()
    return _project_response(db, project, current_user)


@project_router.put("/{artefact_type}", response_model=ProjectLifecyclesOut)
def set_project_lifecycle(
    project_id: UUID, artefact_type: str, body: ProjectLifecycleSet,
    current_user: User = Depends(_manage_project), db: Session = Depends(get_db),
) -> ProjectLifecyclesOut:
    """Sets the project's own turned-off states for one type (`null` follows the nearest ancestor project)."""
    project = project_or_404(db, project_id)
    lifecycles.set_project_disabled(
        db, project=project, artefact_type=artefact_type, disabled=body.disabled_states, actor_id=current_user.id,
    )
    db.commit()
    return _project_response(db, project, current_user)


# --- organisation -----------------------------------------------------------------------------


@org_router.get("", response_model=list[OrgLifecycleOut])
def get_org_lifecycles(
    organization_id: UUID, current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> list[OrgLifecycleOut]:
    """The organisation's lifecycle types with their required states and exempt projects."""
    return _org_response(db, _org_or_404(db, organization_id))


def _org_skip_response(db: Session, org: Organization) -> OrgSkipOut:
    """The organisation's rule on skipping steps with its exempt projects."""
    skip = lifecycles.organization_skip(db, org)
    project_ids = {pid for pid, _ in skip["exemptions"]}
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids)).all()} if project_ids else {}
    return OrgSkipOut(
        forbidden=skip["forbidden"],
        exemptions=[
            ExemptionOut(
                project_id=pid, project_name=projects[pid].name, project_code=projects[pid].code,
                include_children=include_children,
            )
            for pid, include_children in skip["exemptions"] if pid in projects
        ],
    )


@org_router.get("/skip", response_model=OrgSkipOut)
def get_org_skip(
    organization_id: UUID, current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> OrgSkipOut:
    """Whether the organisation forbids skipping steps, and the projects exempt from the ban."""
    return _org_skip_response(db, _org_or_404(db, organization_id))


@org_router.put("/skip", response_model=OrgSkipOut)
def set_org_skip(
    organization_id: UUID, body: OrgSkipSet,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> OrgSkipOut:
    """Sets whether the organisation forbids skipping steps."""
    org = _org_or_404(db, organization_id)
    lifecycles.set_org_skip_forbidden(db, organization=org, forbidden=body.forbidden, actor_id=current_user.id)
    db.commit()
    return _org_skip_response(db, org)


@org_router.post("/skip/exemptions", response_model=OrgSkipOut)
def add_org_skip_exemption(
    organization_id: UUID, body: ExemptionSet,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> OrgSkipOut:
    """Exempts a project (optionally with its nested children) from the organisation's ban on skipping steps."""
    org = _org_or_404(db, organization_id)
    project = db.get(Project, body.project_id)
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    lifecycles.add_skip_exemption(
        db, organization=org, project=project, include_children=body.include_children, actor_id=current_user.id,
    )
    db.commit()
    return _org_skip_response(db, org)


@org_router.delete("/skip/exemptions/{project_id}", response_model=OrgSkipOut)
def remove_org_skip_exemption(
    organization_id: UUID, project_id: UUID,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> OrgSkipOut:
    """Removes a project's exemption from the ban on skipping steps."""
    org = _org_or_404(db, organization_id)
    lifecycles.remove_skip_exemption(db, organization=org, project_id=project_id, actor_id=current_user.id)
    db.commit()
    return _org_skip_response(db, org)


@org_router.put("/{artefact_type}", response_model=list[OrgLifecycleOut])
def set_org_lifecycle(
    organization_id: UUID, artefact_type: str, body: OrgLifecycleSet,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> list[OrgLifecycleOut]:
    """Sets the states the organisation requires for one type."""
    org = _org_or_404(db, organization_id)
    lifecycles.set_org_required(
        db, organization=org, artefact_type=artefact_type, required=body.required_states, actor_id=current_user.id,
    )
    db.commit()
    return _org_response(db, org)


@org_router.post("/{artefact_type}/exemptions", response_model=list[OrgLifecycleOut])
def add_org_exemption(
    organization_id: UUID, artefact_type: str, body: ExemptionSet,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> list[OrgLifecycleOut]:
    """Exempts a project (optionally with its nested children) from the organisation's required states of a type."""
    org = _org_or_404(db, organization_id)
    project = db.get(Project, body.project_id)
    if project is None or project.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    lifecycles.add_exemption(
        db, organization=org, artefact_type=artefact_type, project=project, include_children=body.include_children,
        actor_id=current_user.id,
    )
    db.commit()
    return _org_response(db, org)


@org_router.delete("/{artefact_type}/exemptions/{project_id}", response_model=list[OrgLifecycleOut])
def remove_org_exemption(
    organization_id: UUID, artefact_type: str, project_id: UUID,
    current_user: User = Depends(_manage_org), db: Session = Depends(get_db),
) -> list[OrgLifecycleOut]:
    """Removes a project's exemption."""
    org = _org_or_404(db, organization_id)
    lifecycles.remove_exemption(
        db, organization=org, artefact_type=artefact_type, project_id=project_id, actor_id=current_user.id,
    )
    db.commit()
    return _org_response(db, org)
