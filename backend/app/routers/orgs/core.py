"""
Module: routers.orgs.core

Organisation lifecycle: creation, import/export/merge of an organisation's
full bundle, the server-admin self-join escalation, disable/enable/delete,
listing/getting/renaming, and the overview-stats/projects-summary read
endpoints. Also home for the shared `_now()` helper (used by this bucket's
`disable_organization`/`enable_organization` and by
`routers.orgs.membership.deactivate_org_user`).

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

import json
from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole
from app.models.file import FileAsset, RequirementActionFile, RequirementFile
from app.models.organization import Organization, UserOrgRole
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.modules.registry import get_org_creation_choices, run_on_org_created_hooks

# `_accessible_project_ids` (Phase 19's overview-stats endpoint reuses the
# exact same project-visibility computation `GET /projects` already uses,
# rather than duplicating it here) — this codebase already has precedent
# for importing an underscore-prefixed helper across a module boundary
# (`routers/projects.py` itself imports `_direct_project_member_ids_base`/
# `_descendant_org_group_ids` from `services/rbac.py`); `docs/compliance-
# module-plan.md` Phase 19's own spec offers "move it to a shared service
# (or import it)" as the two options and this repo has no existing
# convention of one router importing from another, but moving ~150 lines of
# heavily-documented, actively-relied-on RBAC logic out of `projects.py`
# for one new read-only endpoint is a disproportionate risk for this
# change — importing it is the lower-risk option the plan explicitly
# sanctions.
from app.routers.projects.core import _accessible_project_ids
from app.schemas.org import (
    MergeConflictOut,
    OrganizationCreate,
    OrganizationDeleteConfirm,
    OrganizationOut,
    OrganizationRename,
    OrgCreationChoiceOut,
    OrgImportResult,
    OrgMergePreviewResult,
    OrgMergeResult,
    OrgOverviewStatsOut,
    OrgProjectSummaryOut,
)
from app.services.audit import log_event
from app.services.definitions import seed_link_types, seed_project_statuses
from app.services.downloads import filename_safe
from app.services.org_deletion import delete_organization_cascade
from app.services.org_export import build_org_bundle, detect_merge_conflicts, import_org_bundle, merge_org_bundle
from app.services.rbac import get_effective_org_roles, require_org_role, require_server_admin

router = APIRouter(tags=["organizations-core"])


def _now():
    """Returns the current UTC time."""
    from datetime import datetime

    return datetime.now(UTC)


@router.get("/creation-choices", response_model=list[OrgCreationChoiceOut])
def list_org_creation_choices(current_user: User = Depends(require_server_admin)):
    """Lists every registered module's optional org-creation seeding
    choices (`ModuleDefinition.org_creation_choices`, e.g. Decision
    Management's ADR template packs) for the org-creation form to render
    generically — this core router never imports a specific module's own
    choice list. Server-admin only, matching `POST /orgs` (only a server
    admin ever creates an organisation)."""
    return get_org_creation_choices()


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Creates a new organisation. Server-admin only (I-M-05)."""
    org = Organization(name=payload.name)
    db.add(org)
    db.flush()
    seed_project_statuses(db, org.id)
    seed_link_types(db, org.id)
    # Generic module-contributed org-creation seeding (e.g. Compliance's
    # `seed_compliance_action_types`, or a module's opt-in `org_creation_
    # choices`, e.g. Decision Management's ADR template packs) — this core
    # router never imports a specific module; see `ModuleDefinition.
    # on_org_created`'s own docstring for why org-creation time, not a
    # module-enable hook, is where this has to run. `module_choice_keys`
    # of `None` (the field's default) falls back to every module's
    # `default_selected` choice — see `run_on_org_created_hooks`'s own
    # docstring.
    selected_keys = None if payload.module_choice_keys is None else frozenset(payload.module_choice_keys)
    run_on_org_created_hooks(db, org.id, selected_keys)
    log_event(db, entity_type="organization", entity_id=org.id, action="created", actor_id=current_user.id)
    db.commit()
    db.refresh(org)
    return org


@router.post("/import", response_model=OrgImportResult, status_code=status.HTTP_201_CREATED)
async def import_organization(
    name: str | None = Form(None), file: UploadFile = File(...),
    current_user: User = Depends(require_server_admin), db: Session = Depends(get_db),
):
    """Creates a brand-new organisation from an uploaded organisation export
    bundle (`GET /{organization_id}/export` — see `services.org_export`'s
    module docstring for the full bundle contents and the security
    decisions behind what is/isn't carried over: secrets are never
    included, and SSO is always left disabled post-import).

    Server-admin only, matching plain organisation creation (`POST /orgs`)
    — creating an organisation is a platform-level action either way.

    Registered before `POST /{organization_id}/join-as-admin` (in this file's
    declaration order) purely for readability grouping with `POST ""`; it
    doesn't need static-route-ordering protection like `/import` in
    `routers/projects.py` does, since no bare `POST /{organization_id}`
    route exists here to collide with.
    """
    zip_bytes = await file.read()
    org, warnings = import_org_bundle(db, name=name, zip_bytes=zip_bytes, current_user=current_user)
    return OrgImportResult(organization=OrganizationOut.model_validate(org), warnings=warnings)


@router.get("/{organization_id}/export")
def export_organization(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Exports this organisation's full settings, membership, report
    templates, and every project's structure/history as a self-describing
    zip bundle (see `services.org_export`'s module docstring) — directly
    re-importable via `POST /orgs/import` to stand up a brand-new
    organisation, for backup, offboarding, or migration to a different
    deployment.

    `require_org_role(ORG_ADMIN)` — deliberately no server-admin bypass
    (I-M-05: org-scoped content isn't accessible just by being server
    admin). An operator who needs to back up an org they don't belong to
    uses the existing `POST /{organization_id}/join-as-admin` self-service
    escalation first, rather than this endpoint adding a new bypass.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    zip_bytes = build_org_bundle(db, org, current_user)
    return Response(
        content=zip_bytes, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename_safe(org.name, fallback="organization")}-export.zip"'},
    )


@router.post("/{organization_id}/import/preview", response_model=OrgMergePreviewResult)
async def preview_organization_merge(
    organization_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Previews merging an uploaded organisation export bundle into this
    *existing* organisation — the first step of `POST
    .../import/merge` (see `services.org_export.merge_org_bundle`'s
    docstring for how this differs from `POST /orgs/import`, which always
    creates a brand-new organisation instead). Reports every project/report
    template in the bundle that collides by name with something this
    organisation already has, without writing anything; an empty list means
    the bundle can be merged in with no resolutions needed.

    `require_org_role(ORG_ADMIN)` — same bar as `export_organization`
    above, deliberately no server-admin bypass (I-M-05): merging into an
    existing organisation's real, live data is exactly the kind of
    org-scoped content access that carve-out doesn't extend to.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    zip_bytes = await file.read()
    conflicts = detect_merge_conflicts(db, org, zip_bytes)
    return OrgMergePreviewResult(conflicts=[MergeConflictOut(**c) for c in conflicts])


@router.post("/{organization_id}/import/merge", response_model=OrgMergeResult)
async def merge_organization_bundle(
    organization_id: UUID, file: UploadFile = File(...), resolutions: str = Form("{}"),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Merges an uploaded organisation export bundle's users, groups,
    projects, and report templates into this *existing* organisation (see
    `services.org_export.merge_org_bundle`'s docstring for exactly what is
    and isn't touched, and why). `resolutions` is a JSON object mapping
    each conflict `POST .../import/preview` reported to how it should be
    handled — see `services.org_export.detect_merge_conflicts`'s and
    `merge_org_bundle`'s docstrings for the exact id/value shapes.

    Same `ORG_ADMIN`-only, no-server-admin-bypass authorization as
    `preview_organization_merge` above.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    try:
        parsed_resolutions = json.loads(resolutions)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "resolutions must be a JSON object.") from None
    if not isinstance(parsed_resolutions, dict) or not all(isinstance(v, str) for v in parsed_resolutions.values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "resolutions must be a JSON object mapping conflict ids to string values.")
    zip_bytes = await file.read()
    warnings, summary = merge_org_bundle(
        db, target_org=org, zip_bytes=zip_bytes, resolutions=parsed_resolutions, current_user=current_user,
    )
    return OrgMergeResult(warnings=warnings, **summary)


@router.post("/{organization_id}/join-as-admin", status_code=status.HTTP_204_NO_CONTENT)
def join_organization_as_admin(
    organization_id: UUID,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Lets a server admin grant *themselves* `org_admin` in an organisation
    they don't currently belong to (I-M-05's carve-out, made a general,
    repeatable in-app action rather than only a one-time deployment-startup
    behaviour — see `server_admin_create_org`/`services/bootstrap.py`).

    Needed for self-hosting deployments where the server admin *is* the
    only person running the system and also wants to use their own single
    organisation, not just stand up other people's — `assign_org_role`
    can't help here since it itself requires the caller to already be an
    org admin of the target org, which is exactly the chicken-and-egg this
    closes.

    Deliberately narrow: self-targeting only, and always the `ORG_ADMIN`
    role. This is not a general "server admin can grant any role to any
    user in any organisation" capability (which would meaningfully broaden
    I-M-05's carve-out beyond what's needed) — it only ever lets the
    platform's single most-trusted actor take on ordinary membership in one
    specific org, for themselves.

    Raises:
        HTTPException: 404 if the organisation doesn't exist; 400 if the
            caller is already an admin of it.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    existing = db.scalar(
        select(UserOrgRole).where(
            UserOrgRole.user_id == current_user.id,
            UserOrgRole.organization_id == organization_id,
            UserOrgRole.role == OrgRole.ORG_ADMIN,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You are already an admin of this organisation.")
    db.add(UserOrgRole(user_id=current_user.id, organization_id=organization_id, role=OrgRole.ORG_ADMIN))
    log_event(
        db,
        entity_type="user_org_role",
        entity_id=current_user.id,
        action="granted",
        actor_id=current_user.id,
        organization_id=organization_id,
        detail={"role": OrgRole.ORG_ADMIN.value, "self_granted_by_server_admin": True},
    )
    db.commit()


@router.post("/{organization_id}/disable", response_model=OrganizationOut)
def disable_organization(
    organization_id: UUID,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Suspends an organisation (e.g. non-payment): every org/project-scoped
    request against it is rejected (`services.rbac._require_org_active`),
    for every user including this org's own admins, until re-enabled. No
    data is touched or removed — the reversible alternative to
    `delete_organization` below. Server-admin only; this is tenancy
    management, not organisation content access (I-M-05).
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if not org.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This organisation is already disabled.")
    org.is_active = False
    org.disabled_at = _now()
    org.disabled_by = current_user.id
    log_event(db, entity_type="organization", entity_id=org.id, action="disabled", actor_id=current_user.id)
    db.commit()
    db.refresh(org)
    return org


@router.post("/{organization_id}/enable", response_model=OrganizationOut)
def enable_organization(
    organization_id: UUID,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Reverses `disable_organization`, restoring normal access immediately."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if org.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This organisation is not disabled.")
    org.is_active = True
    org.disabled_at = None
    org.disabled_by = None
    log_event(db, entity_type="organization", entity_id=org.id, action="enabled", actor_id=current_user.id)
    db.commit()
    db.refresh(org)
    return org


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    organization_id: UUID,
    payload: OrganizationDeleteConfirm,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Permanently deletes an organisation and everything it owns: every
    project, requirement (with full version history), change request,
    group, report template, custom field definition, uploaded file (removed
    from actual storage, not just its database row), and any Personal
    Access Token's reach into this org. Irreversible — unlike
    `disable_organization` above, there is no archive/undo. Server-admin
    only (I-M-05: tenancy management, not organisation content access).

    Requires `payload.confirm_name` to exactly match the organisation's
    current name — the same "type the name to confirm" pattern used for
    other irreversible actions elsewhere, so a stray click alone is never
    enough to trigger something this destructive.

    Users who were members lose their role in this org (and become
    "orphaned" if this was their only one, per the existing access-review
    tooling) but are never themselves deleted — deletion only ever removes
    what this organisation *owns*, never accounts. The audit trail survives
    too: matching `AuditEvent` rows lose their `organization_id` link
    (`ondelete="SET NULL"`) but the rows themselves, including this
    deletion's own log entry, are kept.

    Raises:
        HTTPException: 404 if the organisation doesn't exist; 400 if
            `confirm_name` doesn't match.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if payload.confirm_name != org.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirmation name does not match this organisation's name.")

    log_event(
        db, entity_type="organization", entity_id=organization_id, action="deleted",
        actor_id=current_user.id, detail={"name": org.name},
    )
    delete_organization_cascade(db, organization_id)
    db.delete(org)
    db.commit()


@router.get("", response_model=list[OrganizationOut])
def list_organizations(
    mine: bool = False, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Lists organisations. Server admins see all; other users see only orgs they belong to.

    This one server-admin bypass is kept deliberately (unlike every other
    org-scoped endpoint, see I-M-05 in rbac.py): `OrganizationOut` is thin
    directory metadata (id/name/logo/created_at), not "data within the
    organisation", and the server admin needs to see an org exists at all in
    order to complete the one capability I-M-05 actually grants them —
    creating that organisation's initial user.

    `mine=true` opts out of that bypass and always returns only the
    caller's own memberships, regardless of server-admin status — for a
    caller that needs "organisations I can actually act within" (e.g. the
    project list's org filter and its "new project" org picker), where the
    full server-wide directory would let a server admin with no real
    membership anywhere pick an organisation they hold no role in at all.
    """
    if current_user.is_server_admin and not mine:
        return db.scalars(select(Organization).order_by(Organization.name)).all()
    org_ids = db.scalars(
        select(UserOrgRole.organization_id).where(UserOrgRole.user_id == current_user.id)
    ).all()
    if not org_ids:
        return []
    return db.scalars(
        select(Organization).where(Organization.id.in_(org_ids)).order_by(Organization.name)
    ).all()


@router.get("/{organization_id}", response_model=OrganizationOut)
def get_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    if not current_user.is_server_admin and not get_effective_org_roles(db, current_user.id, organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organisation.")
    return org


@router.put("/{organization_id}/name", response_model=OrganizationOut)
def rename_organization(
    organization_id: UUID, payload: OrganizationRename,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Renames an organisation (C-U-01: "Organisational Admins can manage
    properties of the organisation"). Org-admin only, no server-admin
    bypass — same I-M-05 scoping as every other org-property endpoint
    (`update_org_branding`, `update_advanced_settings`, ...); a server admin
    who needs to rename an org they don't belong to uses the existing
    `POST /{organization_id}/join-as-admin` self-service escalation first.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    old_name = org.name
    org.name = payload.name
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="renamed",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"old_name": old_name, "new_name": org.name},
    )
    db.commit()
    db.refresh(org)
    return org


@router.get("/{organization_id}/overview-stats", response_model=OrgOverviewStatsOut)
def get_org_overview_stats(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """The "Organisation Overview" page's stats header (compliance-module-
    plan.md Phase 19): project count, requirement count, org member count,
    and total uploaded file size.

    Gated the same way `list_org_users` is (`ORG_ADMIN`/`PROJECT_CREATOR`/
    `MEMBER` — i.e. any real role in this org) rather than
    `require_org_admin_or_server_admin`: I-M-05 is explicit that the server
    admin role "does not give access to data within organisations," and
    `require_org_admin_or_server_admin`'s own docstring restricts that
    dependency to the one documented carve-out (creating an org's initial
    user) — a server admin with no genuine role in this org still gets 403
    here, same as anyone else. `is_full_org_total` below only ever applies
    *after* that gate has already been passed.

    Per `docs/decisions.md`'s "Compliance module, human review follow-ups"
    entry ("a user can't see the number of all projects if they themselves
    can't see them all... an org admin is the exception and should see the
    raw proper totals"): an org admin, or a server admin who already holds
    some role in this org, sees the organisation's real, unfiltered totals;
    everyone else sees counts scoped to `_accessible_project_ids` (the same
    visibility computation `GET /projects` uses — direct/group/org-wide
    roles plus hierarchical inheritance). Member count is never scoped —
    `list_org_users`'s own permission already lets any caller who reaches
    this endpoint at all see the full member directory, so scoping it
    further here would only invent a restriction nothing else enforces.
    """
    org_roles = get_effective_org_roles(db, current_user.id, organization_id)
    sees_full_totals = current_user.is_server_admin or OrgRole.ORG_ADMIN in org_roles

    member_count = db.scalar(
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .join(UserOrgRole, UserOrgRole.user_id == User.id)
        .where(UserOrgRole.organization_id == organization_id, User.is_archived.is_(False))
    ) or 0

    if sees_full_totals:
        project_count = db.scalar(
            select(func.count()).select_from(Project).where(Project.organization_id == organization_id)
        ) or 0
        requirement_count = db.scalar(
            select(func.count())
            .select_from(Requirement)
            .join(Project, Project.id == Requirement.project_id)
            .where(Project.organization_id == organization_id)
        ) or 0
        total_file_size_bytes = db.scalar(
            select(func.coalesce(func.sum(FileAsset.size_bytes), 0)).where(
                FileAsset.organization_id == organization_id
            )
        ) or 0
    else:
        accessible_ids = _accessible_project_ids(db, current_user.id)
        org_project_ids = set(
            db.scalars(
                select(Project.id).where(
                    Project.organization_id == organization_id, Project.id.in_(accessible_ids)
                )
            ).all()
        ) if accessible_ids else set()
        project_count = len(org_project_ids)
        requirement_count = (
            db.scalar(select(func.count()).select_from(Requirement).where(Requirement.project_id.in_(org_project_ids)))
            if org_project_ids
            else 0
        ) or 0

        # Distinct files this member can account for: this org's own shared
        # resources (`is_org_resource`, visible to any member regardless of
        # per-project access — same as `GET /{organization_id}/resources`)
        # plus files attached to a requirement/action within their
        # accessible-project set. A file could match both a requirement
        # attachment and (if it's also an org resource) the first clause —
        # `union()` de-duplicates by file id so it's never double-counted.
        #
        # Known, deliberate gap: `CommentFile` (a file attached to a
        # `ReviewComment`, C-M-02's discussion-thread attachment path) is
        # NOT included here. `ReviewComment.target_id` is polymorphic
        # (`ReviewTargetType.REQUIREMENT`/`ACTION`/`CHANGE_REQUEST`, no FK),
        # so resolving it back to a project id for scoping would need a
        # three-way branch per target type — a disproportionate amount of
        # complexity for what these comment-thread attachments actually
        # weigh, versus the admin branch above (a plain per-org sum, which
        # *does* include every `CommentFile`'s underlying `FileAsset`
        # regardless of type). This makes a scoped member's own total a
        # strict undercount, never an over-exposure — the safe direction
        # for a visibility boundary — but it is a real, known accuracy gap:
        # revisit if comment attachments turn out to matter for this figure.
        org_resource_file_ids = select(FileAsset.id.label("file_id")).where(
            FileAsset.organization_id == organization_id, FileAsset.is_org_resource.is_(True)
        )
        if org_project_ids:
            requirement_ids = select(Requirement.id).where(Requirement.project_id.in_(org_project_ids))
            action_ids = select(RequirementAction.id).where(RequirementAction.project_id.in_(org_project_ids))
            file_ids_via_requirement = select(RequirementFile.file_id).where(
                RequirementFile.requirement_id.in_(requirement_ids)
            )
            file_ids_via_action = select(RequirementActionFile.file_id).where(
                RequirementActionFile.action_id.in_(action_ids)
            )
            distinct_file_ids = org_resource_file_ids.union(file_ids_via_requirement, file_ids_via_action).subquery()
        else:
            distinct_file_ids = org_resource_file_ids.subquery()
        total_file_size_bytes = db.scalar(
            select(func.coalesce(func.sum(FileAsset.size_bytes), 0)).where(
                FileAsset.id.in_(select(distinct_file_ids.c.file_id))
            )
        ) or 0

    return OrgOverviewStatsOut(
        project_count=project_count,
        requirement_count=requirement_count,
        member_count=member_count,
        total_file_size_bytes=total_file_size_bytes,
        is_full_org_total=sees_full_totals,
    )


@router.get("/{organization_id}/projects", response_model=list[OrgProjectSummaryOut])
def list_org_projects(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Lists every project in this organisation, regardless of whether the
    calling org admin holds a role in it (unlike `GET /projects`, which
    only ever returns projects the caller has a genuine role in). Exists so
    an org admin can find and manage the users/roles on a project they
    otherwise can't open — see `require_project_view_or_manage` — without
    granting general content access as a side effect of just being able to
    see that the project exists.
    """
    return db.scalars(select(Project).where(Project.organization_id == organization_id)).all()

