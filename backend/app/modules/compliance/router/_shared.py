"""
Module: modules.compliance.router._shared

Internal helpers shared by three or more bucket modules of the organisation-scoped router package (a helper used by one
or two stays local to its bucket): the module-role and module-enabled dependency factories (`_require_manage`,
`_require_view`), the standard-scoped role gates (`_require_standard_manage`, `_require_standard_contribute`,
`_require_standard_manage_or_contribute`), the cross-organisation ownership-chain lookups (`_get_standard_or_404`,
`_get_version_or_404`, `_get_requirement_or_404`) and the draft-version guard (`_require_draft_version`). It declares no
routes.
"""

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user_or_module_frame
from app.models.user import User
from app.modules.compliance.enums import ComplianceStandardVersionStatus
from app.modules.compliance.models import ComplianceRequirement, ComplianceStandard, ComplianceStandardVersion
from app.services.rbac import require_module_role, require_org_module_enabled

# Dependency factories are called once, at router-definition time, not per request.
_require_manage = require_module_role("compliance", "compliance_manager")
_require_view = require_org_module_enabled("compliance")

# Standard-scoped gates use the same `require_module_role` factory with the `scope="standard"` roles: the standard id is
# read from the path and its organisation resolved through `resolve_entity_organization_id`
# (`service.resolve_standard_organization_id`), not a separate `organization_id` segment. `is_server_admin`,
# `OrgRole.ORG_ADMIN` and the org-scoped `compliance_manager` (via `overridden_by`) satisfy them with no per-standard
# grant. They are not built on `_require_view`, which also requires organisation membership: `_require_manage`'s bypass
# does not.
_require_standard_manage = require_module_role("compliance", "standards_manager")
_require_standard_contribute = require_module_role("compliance", "standards_contributor")


def _require_standard_manage_or_contribute(
    request: Request,
    current_user: User = Depends(get_current_user_or_module_frame("compliance")),
    db: Session = Depends(get_db),
) -> User:
    """Manager-**or**-contributor, standard-scoped gate — for
    the draft-only requirement/required-action content mutations a
    `standards_contributor` may also make; `_require_draft_version` still
    separately enforces the "only while the version is still a draft"
    restriction this dependency does not know about. Tries `_require_
    standard_manage` first, falling back to `_require_standard_contribute`
    on a 403 (never on a 404 — module-disabled/entity-absent should
    propagate immediately, not be masked by trying the second check)."""
    try:
        return _require_standard_manage(request=request, current_user=current_user, db=db)
    except HTTPException as manage_exc:
        if manage_exc.status_code != status.HTTP_403_FORBIDDEN:
            raise
        try:
            return _require_standard_contribute(request=request, current_user=current_user, db=db)
        except HTTPException as contribute_exc:
            if contribute_exc.status_code != status.HTTP_403_FORBIDDEN:
                raise
            raise manage_exc from contribute_exc


# --- Cross-org ownership-chain lookups (404, not 403, on a mismatch) --------
#
# A wrong-organisation reference is indistinguishable from a nonexistent one to a caller with no access to the owning
# organisation (as `routers.action_types` does).


def _get_standard_or_404(db: Session, organization_id: UUID, standard_id: UUID) -> ComplianceStandard:
    standard = db.get(ComplianceStandard, standard_id)
    if standard is None or standard.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance standard not found.")
    return standard


def _get_version_or_404(
    db: Session, organization_id: UUID, standard_id: UUID, version_id: UUID
) -> tuple[ComplianceStandard, ComplianceStandardVersion]:
    standard = _get_standard_or_404(db, organization_id, standard_id)
    version = db.get(ComplianceStandardVersion, version_id)
    if version is None or version.standard_id != standard.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance standard version not found.")
    return standard, version


def _get_requirement_or_404(
    db: Session, organization_id: UUID, standard_id: UUID, version_id: UUID, requirement_id: UUID
) -> tuple[ComplianceStandard, ComplianceStandardVersion, ComplianceRequirement]:
    standard, version = _get_version_or_404(db, organization_id, standard_id, version_id)
    requirement = db.get(ComplianceRequirement, requirement_id)
    if requirement is None or requirement.standard_version_id != version.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance requirement not found.")
    return standard, version, requirement


def _require_draft_version(version: ComplianceStandardVersion) -> None:
    """Enforces §4's "a published version's requirements become immutable":
    creating, editing, deleting, or reordering a requirement or required
    action under a non-draft version 409s. Applied uniformly to *every*
    content mutation under a version (create/update/delete/move alike) —
 notes for why `move` is
    included even though the spec text only explicitly names create/
    update/delete: reordering is still a mutation of the version's content,
    and letting it slip through would silently alter what a published
    version presents even though no single requirement's own fields
    changed."""
    if version.status != ComplianceStandardVersionStatus.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This standard version is no longer a draft; its requirements and required actions are immutable. "
            "Create a new version to make changes.",
        )
