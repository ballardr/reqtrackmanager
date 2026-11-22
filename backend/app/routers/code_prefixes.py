"""
Module: routers.code_prefixes

The record code prefix an organisation, or one project, uses for each record type
(`DEC-006` or, where chosen, `ADR-006`), and how each type's effective prefix was decided.

Responsibilities:
- List a scope's types with the effective prefix and the tier that set it, leaving out the
  types of a module the scope cannot use (an administrator is not offered a switch for a
  module that is off or not entitled).
- Set and clear a scope's own prefix. Every rule (shape, uniqueness, nesting) is in
  `services.code_prefixes`; this module authorises and shapes the responses.

Design decisions:
- Reading is open to every organisation member / project member (the effective prefix is not
  sensitive); changing needs the organisation administrator, or the project manager
  (`require_project_manage`, as for components and categories).
- A change affects records created afterwards only; the response text of the UI says so.

Dependencies: `services.code_prefixes`, the module registry (type labels and availability).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    artefact_type_enabled_for_project,
    artefact_type_module,
    get_artefact_type_label,
    is_module_enabled,
    is_org_module_subcomponent_enabled,
    subcomponent_serving,
)
from app.schemas.code_prefix import CodePrefixOut, CodePrefixUpdate
from app.services import code_prefixes
from app.services.code_prefixes import PrefixRow
from app.services.lookups import project_or_404
from app.services.rbac import require_org_role, require_project_manage, require_project_view

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/code-prefixes", tags=["code-prefixes"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/code-prefixes", tags=["code-prefixes"])


def _org_or_404(db: Session, organization_id: UUID) -> Organization:
    """The organisation, or 404."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return org


def _type_available_to_organization(db: Session, organization_id: UUID, artefact_type: str) -> bool:
    """Whether the type's module (and its sub-component) is enabled for the organisation; a core type always is."""
    definition = artefact_type_module(artefact_type)
    if definition is None:
        return True
    if not is_module_enabled(db, organization_id, definition.key):
        return False
    sub = subcomponent_serving(definition, artefact_type)
    return sub is None or is_org_module_subcomponent_enabled(db, organization_id, definition.key, sub.key)


def _module_name(artefact_type: str) -> str | None:
    """The display name of the module that owns the type; `None` for a core type."""
    definition = artefact_type_module(artefact_type)
    return None if definition is None else definition.name


def _ordered(types: list[str]) -> list[str]:
    """Core types first, then each module's types (modules by name), each group by display name, so the response
    is already in the order the panel's sections are drawn."""
    return sorted(types, key=lambda t: (
        (_module_name(t) or "").lower(), get_artefact_type_label(t).lower(),
    ))


def _out(row: PrefixRow) -> CodePrefixOut:
    definition = artefact_type_module(row.artefact_type)
    return CodePrefixOut(
        artefact_type=row.artefact_type, label=row.label, module_key=None if definition is None else definition.key,
        module_name=None if definition is None else definition.name, default_prefix=row.default_prefix,
        own_prefix=row.own_prefix,
        prefix=row.effective.prefix, source=row.effective.tier, inherited_prefix=row.inherited.prefix,
        inherited_source=row.inherited.tier,
    )


@org_router.get("", response_model=list[CodePrefixOut])
def list_organization_prefixes(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists each record type's prefix in the organisation, for the types of modules it can use."""
    org = _org_or_404(db, organization_id)
    types = [t for t in code_prefixes.default_prefixes() if _type_available_to_organization(db, org.id, t)]
    return [_out(row) for row in code_prefixes.describe_scope(db, org, _ordered(types))]


@org_router.put("/{artefact_type}", response_model=CodePrefixOut)
def set_organization_prefix(
    organization_id: UUID, artefact_type: str, payload: CodePrefixUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Sets the organisation's prefix for a type. Applies to records created from now on; stored codes are unchanged."""
    org = _org_or_404(db, organization_id)
    code_prefixes.set_override(db, org, artefact_type, payload.prefix, current_user.id)
    db.commit()
    return _out(code_prefixes.describe_scope(db, org, [artefact_type])[0])


@org_router.delete("/{artefact_type}", response_model=CodePrefixOut)
def clear_organization_prefix(
    organization_id: UUID, artefact_type: str,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Removes the organisation's own prefix for a type, so it uses the built-in one again."""
    org = _org_or_404(db, organization_id)
    code_prefixes.clear_override(db, org, artefact_type, current_user.id)
    db.commit()
    return _out(code_prefixes.describe_scope(db, org, [artefact_type])[0])


@project_router.get("", response_model=list[CodePrefixOut])
def list_project_prefixes(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists each record type's prefix in the project with the tier that decided it (the project, a parent
    project, the organisation or the built-in default), for the types of modules enabled for the project."""
    project = project_or_404(db, project_id)
    types = [t for t in code_prefixes.default_prefixes() if artefact_type_enabled_for_project(db, t, project.id)]
    return [_out(row) for row in code_prefixes.describe_scope(db, project, _ordered(types))]


@project_router.put("/{artefact_type}", response_model=CodePrefixOut)
def set_project_prefix(
    artefact_type: str, payload: CodePrefixUpdate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Sets the project's prefix for a type; its nested projects follow it until they set their own. Applies to
    records created from now on."""
    code_prefixes.set_override(db, project, artefact_type, payload.prefix, current_user.id)
    db.commit()
    return _out(code_prefixes.describe_scope(db, project, [artefact_type])[0])


@project_router.delete("/{artefact_type}", response_model=CodePrefixOut)
def clear_project_prefix(
    artefact_type: str, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Removes the project's own prefix for a type, so it follows its parent project or the organisation again."""
    code_prefixes.clear_override(db, project, artefact_type, current_user.id)
    db.commit()
    return _out(code_prefixes.describe_scope(db, project, [artefact_type])[0])
