"""
Module: routers.orgs

Organisation management: creating organisations and organisation users
(I-M-05, server-admin only), organisation role assignment, user
deactivation/archival (C-U-04, C-U-05), and organisation groups (C-U-08,
C-U-12).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.enums import ExternalUserPolicy, OrgRole
from app.models.file import FileAsset, RequirementFile
from app.models.notification import NotificationType
from app.models.organization import Organization, OrgGroup, OrgGroupMember, ReportTemplate, UserOrgRole
from app.models.pat import PersonalAccessToken
from app.models.project import Project, ProjectGroup, ProjectGroupMember, UserProjectRole
from app.models.project_status import ProjectStatusDefinition
from app.models.requirement import RequirementLink
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.models.user import User
from app.schemas.email import TestEmailRequest
from app.schemas.file import FileAssetOut
from app.schemas.link_type import LinkTypeCreate, LinkTypeOut, LinkTypeUpdate
from app.schemas.org import (
    DefaultTemplateUpdate,
    DisplayNameLockUpdate,
    ExternalUserMatch,
    MergeConflictOut,
    OrgAdvancedSettingsOut,
    OrgAdvancedSettingsUpdate,
    OrganizationCreate,
    OrganizationDeleteConfirm,
    OrganizationOut,
    OrganizationRename,
    OrgBrandingUpdate,
    OrgGroupCreate,
    OrgGroupMemberAdd,
    OrgGroupOut,
    OrgGroupUpdate,
    OrgImportResult,
    OrgLoginInfoOut,
    OrgMergePreviewResult,
    OrgMergeResult,
    OrgProjectSummaryOut,
    OrgRoleAssign,
    OrgSsoConfigOut,
    OrgSsoConfigUpdate,
    OrgUserCreate,
    OrgUserOut,
    OrgUserSearchResult,
    OutsideDomainUserOut,
    ReportTemplateCreate,
    ReportTemplateOut,
    ScimTokenCreatedOut,
    ScimTokenStatusOut,
    UserAccessGroupRef,
    UserAccessOut,
    UserAccessProject,
)
from app.schemas.pat import BulkRevokeResult, OrgPersonalAccessTokenOut
from app.schemas.project import MoveDirection
from app.schemas.project_status import ProjectStatusCreate, ProjectStatusOut, ProjectStatusUpdate
from app.schemas.report import OrgReportDefaults
from app.security import generate_scim_token, hash_password
from app.services import engagement
from app.services.audit import log_event
from app.services.definitions import (
    delete_definition_with_reassignment,
    seed_link_types,
    seed_project_statuses,
)
from app.services.downloads import filename_safe
from app.services.email import SmtpOverride, send_email
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_email
from app.services.files import delete_file, upload_file
from app.services.notifications import notify
from app.services.ordering import move_ordered
from app.services.org_deletion import delete_organization_cascade
from app.services.org_export import build_org_bundle, detect_merge_conflicts, import_org_bundle, merge_org_bundle
from app.services.pats import effective_expiry, revoke_matching
from app.services.rbac import (
    can_manage_project_settings,
    get_effective_org_roles,
    get_effective_project_roles,
    get_project_managers,
    require_org_admin_or_server_admin,
    require_org_role,
    require_server_admin,
    would_create_org_group_cycle,
)

router = APIRouter(prefix="/api/v1/orgs", tags=["organizations"])
settings = get_settings()


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
        return db.scalars(select(Organization)).all()
    org_ids = db.scalars(
        select(UserOrgRole.organization_id).where(UserOrgRole.user_id == current_user.id)
    ).all()
    if not org_ids:
        return []
    return db.scalars(select(Organization).where(Organization.id.in_(org_ids))).all()


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


@router.post("/{organization_id}/users", response_model=OrgUserOut, status_code=status.HTTP_201_CREATED)
def create_org_user(
    organization_id: UUID,
    payload: OrgUserCreate,
    current_user: User = Depends(require_org_admin_or_server_admin),
    db: Session = Depends(get_db),
):
    """Creates a new user directly within an organisation (I-M-05 clarification).

    Server admins may call this even with no role of their own in the target
    organisation — this is the one documented carve-out (creating the
    initial user of a newly created org). Every other org-scoped endpoint
    requires a genuine org role.
    """
    if db.scalar(select(User).where(User.email == payload.email.lower())) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if org.sso_only:
        # A brand-new native-credentialed account whose only org membership
        # is sso_only could never log in (NativeAuthBackend rejects native
        # login when every one of a user's orgs requires SSO) — same guard
        # as self-signup's allow_self_signup/sso_only mutual exclusion.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This organisation is SSO-only; native accounts cannot be created for it directly.",
        )
    user = User(
        email=payload.email.lower(),
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        auth_backend="native",
    )
    db.add(user)
    db.flush()
    db.add(UserOrgRole(user_id=user.id, organization_id=organization_id, role=payload.role))
    log_event(
        db,
        entity_type="user",
        entity_id=user.id,
        action="created",
        actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()
    return OrgUserOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_archived=user.is_archived,
        roles=[payload.role],
    )


@router.get("/{organization_id}/users", response_model=list[OrgUserOut])
def list_org_users(
    organization_id: UUID,
    response: Response,
    stale_since_days: int | None = Query(None, ge=0),
    never_logged_in: bool | None = None,
    has_2fa: bool | None = None,
    org_role: OrgRole | None = None,
    has_project_access: bool | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    sort: str | None = Query(None, pattern="^(display_name|email|last_login_at)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists users belonging to an organisation with their org roles.

    Archived users are excluded (C-U-05: an archived user "no longer
    show[s] as users", though their past contributions stay attributed to
    them elsewhere via the unaffected `creator_id`/`actor_id` foreign keys).

    The access-review filters (C-A-13) — `stale_since_days`,
    `never_logged_in`, `has_2fa`, `org_role`, `has_project_access`,
    `is_active` — are org-admin only; a plain member/project-creator can
    still call this endpoint unfiltered for the general member directory
    (existing behavior), but supplying any filter requires org-admin,
    scoped to *this* organisation via `organization_id` (not "an org admin
    somewhere else" — same pattern as every other org-scoped admin check).

    `search` (name/email substring, case-insensitive) and `limit`/`offset`
    (U-P-06, 2026-08 UX audit "Directories at scale") are open to any
    caller who can already reach this endpoint at all — they narrow the
    same directory a plain member can browse, not an access-review signal,
    so they don't require org-admin the way the filters above do. As with
    `list_requirements`, omitting `limit` returns every match unpaginated
    (unchanged from before pagination existed); when given, the total
    match count before slicing is returned via `X-Total-Count`.

    `sort` (2026-08 UX audit roadmap, "Column-header sorting on data
    tables") optionally overrides the default `display_name` sort with
    `email` or `last_login_at`; `order` picks `asc` (default) or `desc`.
    `last_login_at` is nullable (a user who's never logged in) — those
    rows sort last regardless of `order`, so "sort by last login,
    descending" surfaces the most-recently-active users first without
    "never logged in" accounts jumping to the top.
    """
    filters_requested = any(
        v is not None for v in (stale_since_days, never_logged_in, has_2fa, org_role, has_project_access, is_active)
    )
    is_admin = OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
    if filters_requested and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organisation admin may use access-review filters.")

    rows = db.execute(
        select(User, UserOrgRole.role).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
            UserOrgRole.organization_id == organization_id, User.is_archived.is_(False)
        )
    ).all()
    by_user: dict[UUID, OrgUserOut] = {}
    for user, role in rows:
        if user.id not in by_user:
            by_user[user.id] = OrgUserOut(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                is_archived=user.is_archived,
                roles=[],
                display_name_locked=user.display_name_locked,
                # C-A-13 access-review data: real values only for org admins
                # (matching the filter gate above) — a plain member calling
                # this same endpoint for the general directory must not
                # receive other members' account-security posture.
                last_login_at=user.last_login_at if is_admin else None,
                is_2fa_enabled=user.is_2fa_enabled if is_admin else False,
            )
        by_user[user.id].roles.append(role)

    results = list(by_user.values())
    if is_active is not None:
        results = [r for r in results if r.is_active == is_active]
    if has_2fa is not None:
        results = [r for r in results if r.is_2fa_enabled == has_2fa]
    if org_role is not None:
        results = [r for r in results if org_role in r.roles]
    if never_logged_in:
        results = [r for r in results if r.last_login_at is None]
    if stale_since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=stale_since_days)
        results = [r for r in results if r.last_login_at is None or r.last_login_at < cutoff]
    if has_project_access is not None:
        access_ids = _org_users_with_project_access(db, organization_id)
        results = [r for r in results if (r.user_id in access_ids) == has_project_access]
    if search:
        needle = search.lower()
        results = [r for r in results if needle in r.display_name.lower() or needle in r.email.lower()]

    if sort and sort != "display_name":
        def _sort_value(item: OrgUserOut):
            value = getattr(item, sort)
            if sort == "last_login_at":
                # Nulls (never logged in) always sort last, in either
                # direction — see docstring.
                return (value is None, value)
            return value.lower()
        results.sort(key=_sort_value, reverse=(order == "desc"))
    else:
        results.sort(key=lambda r: r.display_name.lower(), reverse=(sort == "display_name" and order == "desc"))

    response.headers["X-Total-Count"] = str(len(results))
    if limit is not None:
        results = results[offset:offset + limit]
    return results


@router.get("/{organization_id}/users/{user_id}/access", response_model=UserAccessOut)
def get_user_access(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """One user's access within this organisation (2026-08 UX audit, sixth
    pass: "No way to view a user's access") — every project in the org
    where the user holds at least one effective role, that role set, which
    of the project's own groups they're a direct member of, and which org
    groups they directly belong to.

    Computed server-side via the existing `get_effective_project_roles`
    (direct assignment, direct/nested project-group membership, or
    org-wide project visibility — the same resolution every permission
    check in the app already relies on) rather than re-derived per project
    on the frontend, both for correctness (one algorithm, not two) and to
    avoid an N-project fan-out of round trips from the client.
    """
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    org_group_rows = db.execute(
        select(OrgGroup.id, OrgGroup.name)
        .join(OrgGroupMember, OrgGroupMember.org_group_id == OrgGroup.id)
        .where(OrgGroup.organization_id == organization_id, OrgGroupMember.user_id == user_id)
        .order_by(OrgGroup.name)
    ).all()
    org_groups = [UserAccessGroupRef(id=row.id, name=row.name) for row in org_group_rows]

    projects: list[UserAccessProject] = []
    for project in db.scalars(
        select(Project).where(Project.organization_id == organization_id).order_by(Project.name)
    ).all():
        roles = get_effective_project_roles(db, user_id, project.id)
        if not roles:
            continue
        project_group_rows = db.execute(
            select(ProjectGroup.id, ProjectGroup.name)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .where(ProjectGroup.project_id == project.id, ProjectGroupMember.user_id == user_id)
            .order_by(ProjectGroup.name)
        ).all()
        projects.append(UserAccessProject(
            project_id=project.id, project_name=project.name,
            roles=sorted(roles, key=lambda r: r.value),
            project_groups=[UserAccessGroupRef(id=row.id, name=row.name) for row in project_group_rows],
        ))

    return UserAccessOut(org_groups=org_groups, projects=projects)


_EMAIL_LIKE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/{organization_id}/users/search", response_model=OrgUserSearchResult)
def search_org_users(
    organization_id: UUID,
    q: str = Query(..., min_length=1),
    project_id: UUID | None = Query(None),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Server-backed search for the project user picker: org members
    matching `q` by name/email, plus — only when `q` is a full email
    address not already among the org's members and
    `Organization.external_user_policy` allows it — a synthetic "external"
    result the caller can then add via
    `routers/projects.py::assign_project_role_by_email`.

    Whether `q` matches an *existing* account elsewhere in the system is
    itself a cross-tenant fact (a one-bit "this exact email has an account
    somewhere" signal) — unlike "no account, would need an invite," which
    reveals nothing about any real account and is always safe to return.
    This endpoint is open to any org member (matching `list_org_users`'
    existing directory precedent), but that's a materially lower bar than
    `assign_project_role_by_email`'s own `require_project_manage` gate, so
    the `exists=True` case is withheld from a caller who couldn't actually
    act on it: an org admin, or a member who passes `project_id` for a
    project in this org they have manage rights on. Below that bar, a
    match that would resolve to `exists=True` is omitted entirely rather
    than downgraded to a misleading `exists=False`.
    """
    needle = q.strip().lower()
    rows = db.execute(
        select(User, UserOrgRole.role).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
            UserOrgRole.organization_id == organization_id, User.is_archived.is_(False)
        )
    ).all()
    by_user: dict[UUID, OrgUserOut] = {}
    for user, role in rows:
        if needle not in user.display_name.lower() and needle not in user.email.lower():
            continue
        if user.id not in by_user:
            by_user[user.id] = OrgUserOut(
                user_id=user.id, email=user.email, display_name=user.display_name,
                is_active=user.is_active, is_archived=user.is_archived, roles=[],
                display_name_locked=user.display_name_locked,
            )
        by_user[user.id].roles.append(role)
    members = list(by_user.values())[:8]

    external: ExternalUserMatch | None = None
    if _EMAIL_LIKE.match(needle) and not any(m.email.lower() == needle for m in members):
        org = db.get(Organization, organization_id)
        policy = org.external_user_policy if org else ExternalUserPolicy.DISABLED
        if policy != ExternalUserPolicy.DISABLED:
            existing = db.scalar(select(User).where(User.email == needle))
            if existing is not None:
                may_see_existing = OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
                if not may_see_existing and project_id is not None:
                    project = db.get(Project, project_id)
                    if project is not None and project.organization_id == organization_id:
                        may_see_existing = can_manage_project_settings(db, current_user, project)
                if may_see_existing:
                    external = ExternalUserMatch(email=needle, exists=True)
            else:
                domain = needle.rsplit("@", 1)[-1]
                domain_ok = policy == ExternalUserPolicy.ANYONE or (
                    policy == ExternalUserPolicy.ORG_DOMAIN_ONLY
                    and org is not None
                    and org.auto_accept_email_domain
                    and org.auto_accept_email_domain.lower() == domain
                )
                if domain_ok:
                    external = ExternalUserMatch(email=needle, exists=False)
    return OrgUserSearchResult(members=members, external=external)


@router.get("/{organization_id}/users/outside-domain", response_model=list[OutsideDomainUserOut])
def list_outside_domain_users(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Lists existing users (system-wide, not archived) whose email domain
    matches this org's configured `auto_accept_email_domain` but who are
    not currently members — lets an org admin see who's eligible to be
    invited once a domain has been configured (bullet 5 of the
    self-signup/external-user feature set)."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if not org.auto_accept_email_domain:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This organisation has no email domain configured.")
    member_ids = set(
        db.scalars(select(UserOrgRole.user_id).where(UserOrgRole.organization_id == organization_id)).all()
    )
    domain_suffix = f"@{org.auto_accept_email_domain.lower()}"
    candidates = db.scalars(select(User).where(User.is_archived.is_(False))).all()
    return [
        OutsideDomainUserOut(user_id=u.id, email=u.email, display_name=u.display_name)
        for u in candidates
        if u.id not in member_ids and u.email.lower().endswith(domain_suffix)
    ]


def _org_users_with_project_access(db: Session, organization_id: UUID) -> set[UUID]:
    """User ids with at least one direct project role or direct project-group
    membership on any project in this organisation (used by the
    `has_project_access` access-review filter, C-A-13). Direct resolution
    only, not nested org groups — matches the same scope already used by
    `get_project_managers` for similar bulk/administrative queries."""
    direct_role_ids = set(
        db.scalars(
            select(UserProjectRole.user_id)
            .join(Project, Project.id == UserProjectRole.project_id)
            .where(Project.organization_id == organization_id)
        ).all()
    )
    direct_group_ids = set(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .join(Project, Project.id == ProjectGroup.project_id)
            .where(Project.organization_id == organization_id, ProjectGroupMember.user_id.is_not(None))
        ).all()
    )
    return direct_role_ids | direct_group_ids


@router.put("/{organization_id}/users/{user_id}/display-name-lock", status_code=status.HTTP_204_NO_CONTENT)
def set_display_name_lock(
    organization_id: UUID,
    user_id: UUID,
    payload: DisplayNameLockUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Locks or unlocks a user's ability to change their own display name (C-U-16)."""
    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    user.display_name_locked = payload.display_name_locked
    log_event(
        db,
        entity_type="user",
        entity_id=user_id,
        action="display_name_lock_changed",
        actor_id=current_user.id,
        organization_id=organization_id,
        detail={"display_name_locked": payload.display_name_locked},
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_org_role(
    organization_id: UUID,
    user_id: UUID,
    payload: OrgRoleAssign,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Grants an organisation role to a user (C-U-01).

    The affected user is always the `{user_id}` path parameter, not
    `payload.user_id` — the request body's `role` field is the only part of
    the payload actually used; a mismatched body `user_id` is ignored rather
    than trusted, so the URL a caller is authorized against (and what ends
    up in the audit trail) can never diverge from who is actually affected.
    """
    target = db.get(User, user_id)
    if target is not None and target.is_banned:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This user has been banned by a server admin and cannot be granted a role."
        )
    existing = db.scalar(
        select(UserOrgRole).where(
            UserOrgRole.user_id == user_id,
            UserOrgRole.organization_id == organization_id,
            UserOrgRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(UserOrgRole(user_id=user_id, organization_id=organization_id, role=payload.role))
        log_event(
            db,
            entity_type="user_org_role",
            entity_id=user_id,
            action="granted",
            actor_id=current_user.id,
            organization_id=organization_id,
            detail={"role": payload.role.value},
        )
        granted_user = db.get(User, user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PERMISSION_GRANTED,
                title="Organisation permission granted",
                body=f"You were granted the '{payload.role.value}' role in an organisation.",
                actor_id=current_user.id,
            )
        db.commit()


@router.delete("/{organization_id}/membership", status_code=status.HTTP_204_NO_CONTENT)
def leave_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service: the caller removes their own membership in an organisation.

    Previously there was no way for a user to leave an org at all — see
    docs/e2e-workflows.md's "product gaps found" section, which this closes.

    Refuses (409) rather than silently reassigning anyone else's roles if
    leaving would strip the organisation of its last org_admin, or leave any
    of its projects with zero managers. Unlike `deactivate_org_user`'s C-U-09
    fallback (which reassigns the *acting admin* as a project's new manager
    when removing someone else), there is no natural recipient for that
    reassignment here — the caller is the one leaving — so this endpoint
    asks the caller to reassign those roles first instead of guessing who
    should inherit them.

    Also removes the caller's `OrgGroupMember` rows for this organisation's
    groups, not just their direct project roles/memberships — project access
    can be granted through an org group nested into a project group (C-U-12),
    and `get_project_managers` (used for the sole-manager guard below)
    deliberately only resolves *direct* managers, not nested-group-derived
    ones (see its own docstring). Leaving that cleanup out would let a user
    "leave" an org while silently retaining full project access through a
    still-active session — this endpoint checks both direct and
    nested-group-derived manager status precisely because of that gap.

    Locks the organisation row for the duration of this transaction
    (`lock_organization_for_update`) before doing anything else, and each
    project row in turn before checking its manager count
    (`lock_project_for_update`) — without this, two concurrent leavers (e.g.
    an org's last two admins, or a project's last two managers, each leaving
    at once) could each see the other as still-present backup and both
    proceed, since neither transaction's check would see the other's
    not-yet-committed removal.
    """
    from app.services.rbac import lock_organization_for_update, lock_project_for_update

    lock_organization_for_update(db, organization_id)

    roles = get_effective_org_roles(db, current_user.id, organization_id)
    if not roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not a member of this organisation.")

    if OrgRole.ORG_ADMIN in roles:
        other_admins = db.scalars(
            select(UserOrgRole.user_id).where(
                UserOrgRole.organization_id == organization_id,
                UserOrgRole.role == OrgRole.ORG_ADMIN,
                UserOrgRole.user_id != current_user.id,
            )
        ).all()
        if not other_admins:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You are this organisation's only admin. Assign another admin before leaving.",
            )

    from app.models.enums import ProjectRole  # local import matching this module's existing convention
    from app.models.project import Project, ProjectGroup  # local import to avoid cycle at module load
    from app.services.rbac import get_effective_project_roles

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    blocking_projects = []
    for p in projects:
        lock_project_for_update(db, p.id)
        concrete_managers = get_project_managers(db, p.id)
        # Fold in nested-org-group-derived PM status too: get_project_managers
        # only resolves direct assignments/direct group membership, so a
        # manager role held solely via a nested org group would otherwise be
        # invisible here, letting this guard miss a soon-to-be-orphaned
        # project (its only "manager" isn't a *concrete* manager per
        # get_project_managers' own definition, but removing this user's
        # nested-group access below would still leave nobody with the role).
        i_am_manager = current_user.id in concrete_managers or ProjectRole.PROJECT_MANAGER in get_effective_project_roles(
            db, current_user.id, p.id
        )
        if i_am_manager and not (concrete_managers - {current_user.id}):
            blocking_projects.append(p.name)
    if blocking_projects:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You are the sole manager of: " + ", ".join(blocking_projects) + ". Assign another manager first.",
        )

    project_ids = [p.id for p in projects]
    if project_ids:
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.user_id == current_user.id, UserProjectRole.project_id.in_(project_ids)
            )
        )
        db.execute(
            ProjectGroupMember.__table__.delete().where(
                ProjectGroupMember.user_id == current_user.id,
                ProjectGroupMember.project_group_id.in_(
                    select(ProjectGroup.id).where(ProjectGroup.project_id.in_(project_ids))
                ),
            )
        )
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.user_id == current_user.id,
            OrgGroupMember.org_group_id.in_(
                select(OrgGroup.id).where(OrgGroup.organization_id == organization_id)
            ),
        )
    )
    engagement.remove_subscriptions_and_favorites_for_projects(db, current_user.id, project_ids)

    db.execute(
        UserOrgRole.__table__.delete().where(
            UserOrgRole.user_id == current_user.id, UserOrgRole.organization_id == organization_id
        )
    )
    log_event(
        db, entity_type="user_org_role", entity_id=current_user.id, action="left_organization",
        actor_id=current_user.id, organization_id=organization_id,
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_org_user(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Deactivates a user (C-U-04).

    Applies the C-U-09 fallback: for any project where this removal leaves
    no remaining project manager, the acting admin is assigned as manager so
    the project is never left without one (C-U-08). Each project is row-
    locked (`lock_project_for_update`) before its manager count is checked,
    so this can't race a concurrent removal (another deactivation, a role
    revocation, or someone leaving the org) on the same project — see
    `lock_project_for_update`'s docstring for the exact race this closes.

    The target user must actually be a member of `organization_id` — an org
    admin's authority to deactivate accounts is scoped to their own
    organisation's members, same as every other org-scoped action, not to
    every account in the deployment (SOC 2 access-control hardening pass).

    Guard added by a later hardening review: refuses to let a caller
    target their own account. This endpoint had no protection at all
    against ending an organisation's last active admin, unlike the
    conceptually similar `leave_organization` — but the actual fix is
    simpler than mirroring that endpoint's own "are there other admins"
    check would suggest: since this endpoint requires the *caller* to
    already hold `org_admin` on this exact organisation (`require_org_role`
    above) and org_admin is never derived indirectly (unlike project
    roles, which can come from a group), the calling admin's own role
    necessarily survives any deactivation they perform on someone *else* —
    so once self-targeting is blocked, an organisation can never reach zero
    active admins through this endpoint at all, by construction, with
    nothing further to check. Unlike `leave_organization` (which only ends
    *this org's* membership), deactivation here sets `is_active=False` on
    the whole account, locking the caller out of every organisation, not
    just this one — an org-scoped admin action is not the place for that
    scale of self-inflicted, cross-org lockout to happen with no
    confirmation step, which is the concrete harm this guard closes.
    """
    from app.services.rbac import lock_project_for_update

    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use the leave-organisation action to remove your own membership.")

    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    user.is_active = False
    user.deactivated_at = _now()

    from app.models.project import Project  # local import to avoid cycle at module load

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    for project in projects:
        lock_project_for_update(db, project.id)
        managers_before = get_project_managers(db, project.id)
        if user_id not in managers_before:
            continue
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.user_id == user_id, UserProjectRole.project_id == project.id
            )
        )
        db.execute(
            ProjectGroupMember.__table__.delete().where(ProjectGroupMember.user_id == user_id)
        )
        remaining = get_project_managers(db, project.id) - {user_id}
        if not remaining:
            from app.models.enums import ProjectRole

            db.add(UserProjectRole(user_id=current_user.id, project_id=project.id, role=ProjectRole.PROJECT_MANAGER))
            log_event(
                db,
                entity_type="project",
                entity_id=project.id,
                action="manager_fallback_assigned",
                actor_id=current_user.id,
                project_id=project.id,
                detail={"assigned_to": str(current_user.id), "reason": "last_manager_deactivated"},
            )

    log_event(
        db,
        entity_type="user",
        entity_id=user_id,
        action="deactivated",
        actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_org_user(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Archives a deactivated user, hiding them from user lists while
    preserving attribution of their past contributions (C-U-05).

    Scoped to members of `organization_id`, same as `deactivate_org_user`."""
    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    if user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User must be deactivated before archiving.")
    user.is_archived = True
    log_event(
        db, entity_type="user", entity_id=user_id, action="archived", actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()


@router.post("/{organization_id}/groups", response_model=OrgGroupOut, status_code=status.HTTP_201_CREATED)
def create_org_group(
    organization_id: UUID,
    payload: OrgGroupCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Creates an organisation group (C-U-08), optionally marking it as
    IdP-synced from creation (`payload.idp_synced_group_name`) and/or
    granting an org role to anyone synced into it (`payload.
    granted_org_role`, 2026-08 UX audit roadmap item 522)."""
    if payload.idp_synced_group_name:
        _require_idp_synced_name_available(db, organization_id, payload.idp_synced_group_name)
    _require_granted_role_has_sync_target(payload.granted_org_role, payload.idp_synced_group_name)
    group = OrgGroup(
        organization_id=organization_id, name=payload.name, idp_synced_group_name=payload.idp_synced_group_name,
        granted_org_role=payload.granted_org_role,
    )
    db.add(group)
    db.flush()
    log_event(
        db, entity_type="org_group", entity_id=group.id, action="created", actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()
    return OrgGroupOut(
        id=group.id, name=group.name, member_user_ids=[], member_org_group_ids=[],
        idp_synced_group_name=group.idp_synced_group_name, granted_org_role=group.granted_org_role,
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


@router.get("/{organization_id}/groups", response_model=list[OrgGroupOut])
def list_org_groups(
    organization_id: UUID,
    response: Response,
    search: str | None = None,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's groups, each with its resolved member/nested-
    group id lists.

    `search` (name substring, case-insensitive) and `limit`/`offset`
    (U-P-06, 2026-08 UX audit "Directories at scale") are optional — same
    contract as `list_org_users`/`list_requirements`: omitting `limit`
    returns every group unpaginated (existing callers, e.g. Project Admin's
    own org-group nesting picker, rely on exactly this to keep working
    unchanged), and when given, the pre-slice total is returned via
    `X-Total-Count`.

    `granted_org_role` (item 522) is masked to `None` for a non-admin
    caller — this endpoint is deliberately open to any org member (a
    `MEMBER`/`PROJECT_CREATOR` needs group names/ids for the nesting
    picker above), but which group auto-grants which `OrgRole` via SSO
    sync is exactly the kind of privilege-configuration detail
    `sso_group_mappings` used to keep behind the `ORG_ADMIN`-only
    `GET .../advanced-settings` before this field existed — hardening-pass
    finding: it must not become member-readable recon just because it
    moved onto an already-broadly-readable endpoint.
    """
    is_admin = OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
    query = select(OrgGroup).where(OrgGroup.organization_id == organization_id)
    if search:
        query = query.where(OrgGroup.name.ilike(f"%{search}%"))
    groups = db.scalars(query.order_by(OrgGroup.name)).all()

    response.headers["X-Total-Count"] = str(len(groups))
    if limit is not None:
        groups = groups[offset:offset + limit]

    out = []
    for g in groups:
        member_ids = db.scalars(
            select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == g.id, OrgGroupMember.user_id.is_not(None))
        ).all()
        nested_group_ids = db.scalars(
            select(OrgGroupMember.member_org_group_id).where(
                OrgGroupMember.org_group_id == g.id, OrgGroupMember.member_org_group_id.is_not(None)
            )
        ).all()
        out.append(
            OrgGroupOut(
                id=g.id, name=g.name, member_user_ids=list(member_ids), member_org_group_ids=list(nested_group_ids),
                idp_synced_group_name=g.idp_synced_group_name,
                granted_org_role=g.granted_org_role if is_admin else None,
            )
        )
    return out


def _require_granted_role_has_sync_target(granted_org_role, idp_synced_group_name: str | None) -> None:
    """Rejects with 400 if `granted_org_role` is set without a resolved
    `idp_synced_group_name` — granting a role via SSO group membership is
    meaningless without an IdP claim to trigger it on (`OrgGroup.
    granted_org_role`'s model docstring). `idp_synced_group_name` is passed
    already resolved (payload value if provided, otherwise the group's
    existing one) so this same check works for both create and update."""
    if granted_org_role is not None and not idp_synced_group_name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "granted_org_role requires idp_synced_group_name to also be set — a role can only be granted via a "
            "matching IdP group claim.",
        )


def _require_idp_synced_name_available(db: Session, organization_id: UUID, name: str, *, exclude_group_id: UUID | None = None) -> None:
    """Rejects with 400 if another `OrgGroup` in this org already claims
    `name` as its IdP-sync target — enforced here (in addition to the
    partial unique index, the real guarantee under concurrent writes) so a
    routine admin mistake gets a clear error instead of a raw
    `IntegrityError`."""
    conflict_query = select(OrgGroup).where(
        OrgGroup.organization_id == organization_id, OrgGroup.idp_synced_group_name == name
    )
    if exclude_group_id is not None:
        conflict_query = conflict_query.where(OrgGroup.id != exclude_group_id)
    if db.scalar(conflict_query) is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Another group is already synced from IdP group '{name}'."
        )


@router.patch("/{organization_id}/groups/{group_id}", response_model=OrgGroupOut)
def update_org_group(
    organization_id: UUID,
    group_id: UUID,
    payload: OrgGroupUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sets or clears an org group's IdP-sync target
    (`OrgGroup.idp_synced_group_name`) and the org role it grants
    (`OrgGroup.granted_org_role`, 2026-08 UX audit roadmap item 522) — the
    only mutable fields an org group has today (no rename endpoint exists
    for this or `ProjectGroup`). Both are always set wholesale from the
    payload (not merged), matching this endpoint's existing "set or clear"
    semantics for `idp_synced_group_name` from before `granted_org_role`
    existed.
    """
    group = _get_org_group_in_org(db, organization_id, group_id)
    if payload.idp_synced_group_name:
        _require_idp_synced_name_available(db, organization_id, payload.idp_synced_group_name, exclude_group_id=group_id)
    _require_granted_role_has_sync_target(payload.granted_org_role, payload.idp_synced_group_name)
    group.idp_synced_group_name = payload.idp_synced_group_name
    group.granted_org_role = payload.granted_org_role
    log_event(
        db, entity_type="org_group", entity_id=group_id, action="idp_sync_updated", actor_id=current_user.id,
        organization_id=organization_id,
        detail={
            "idp_synced_group_name": payload.idp_synced_group_name,
            "granted_org_role": payload.granted_org_role.value if payload.granted_org_role else None,
        },
    )
    db.commit()
    db.refresh(group)
    member_ids = db.scalars(
        select(OrgGroupMember.user_id).where(OrgGroupMember.org_group_id == group.id, OrgGroupMember.user_id.is_not(None))
    ).all()
    nested_group_ids = db.scalars(
        select(OrgGroupMember.member_org_group_id).where(
            OrgGroupMember.org_group_id == group.id, OrgGroupMember.member_org_group_id.is_not(None)
        )
    ).all()
    return OrgGroupOut(
        id=group.id, name=group.name, member_user_ids=list(member_ids), member_org_group_ids=list(nested_group_ids),
        idp_synced_group_name=group.idp_synced_group_name, granted_org_role=group.granted_org_role,
    )


def _get_org_group_in_org(db: Session, organization_id: UUID, group_id: UUID) -> OrgGroup:
    """Loads an org group and 404s unless it belongs to `organization_id`.

    Without this check, an org_admin of organization A — validated only
    against the `organization_id` path param — could add/remove members of
    an org group belonging to a *different* organisation by supplying its
    id, a cross-tenant IDOR.
    """
    group = db.get(OrgGroup, group_id)
    if group is None or group.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Org group not found.")
    return group


@router.post("/{organization_id}/groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_org_group_member(
    organization_id: UUID,
    group_id: UUID,
    payload: OrgGroupMemberAdd,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Adds a member to an organisation group: either a user, or another
    org group nested inside it (exactly one of `payload.user_id`/
    `payload.member_org_group_id`, same convention as
    `add_project_group_member`).

    Hardening-review finding (user branch): this endpoint checked that
    `group_id` belongs to `organization_id`, but never that
    `payload.user_id` itself holds any role in that organisation — unlike
    the structurally parallel `add_project_group_member`
    (`routers/projects.py`), which explicitly enforces C-U-02 ("All Project
    users must be an organisation user") via `_require_user_in_org`.
    Because `get_effective_project_roles` resolves project access through
    org groups nested into project groups purely from `OrgGroupMember` rows
    (re-checking only that the *group's* org matches the project's, never
    that the *member* actually belongs to that org), an org admin adding an
    arbitrary user id here — anyone in the system, with zero relationship
    to this organisation — would have silently handed that user full
    project access the moment this group is (routinely, legitimately)
    nested into any project group. A genuine cross-tenant privilege
    escalation, not merely a data-integrity nit.
    """
    if not payload.user_id and not payload.member_org_group_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide user_id or member_org_group_id.")
    _get_org_group_in_org(db, organization_id, group_id)

    if payload.user_id is not None:
        if not get_effective_org_roles(db, payload.user_id, organization_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "The user must be a member of this organisation first."
            )
        existing = db.scalar(
            select(OrgGroupMember).where(
                OrgGroupMember.org_group_id == group_id, OrgGroupMember.user_id == payload.user_id
            )
        )
        if existing is None:
            db.add(OrgGroupMember(org_group_id=group_id, user_id=payload.user_id))
            log_event(
                db, entity_type="org_group", entity_id=group_id, action="member_added", actor_id=current_user.id,
                organization_id=organization_id, detail={"user_id": str(payload.user_id)},
            )
            db.commit()
    else:
        # Nesting a group belonging to a different organisation would let
        # its members inherit membership here, crossing the tenant boundary
        # — same reasoning as `add_project_group_member`'s org_group_id
        # branch, one level up.
        child_group = _get_org_group_in_org(db, organization_id, payload.member_org_group_id)
        if child_group.id == group_id or would_create_org_group_cycle(db, group_id, child_group.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This would create a cycle of nested groups.")
        existing = db.scalar(
            select(OrgGroupMember).where(
                OrgGroupMember.org_group_id == group_id, OrgGroupMember.member_org_group_id == child_group.id
            )
        )
        if existing is None:
            db.add(OrgGroupMember(org_group_id=group_id, member_org_group_id=child_group.id))
            log_event(
                db, entity_type="org_group", entity_id=group_id, action="nested_group_added", actor_id=current_user.id,
                organization_id=organization_id, detail={"member_org_group_id": str(child_group.id)},
            )
            db.commit()


@router.delete("/{organization_id}/groups/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_group_member(
    organization_id: UUID,
    group_id: UUID,
    member_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Removes a member from an organisation group — `member_id` is matched
    against either a user member or a nested-group member (whichever it
    is), same generic-id convention as `remove_project_group_member`."""
    _get_org_group_in_org(db, organization_id, group_id)
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.org_group_id == group_id,
            (OrgGroupMember.user_id == member_id) | (OrgGroupMember.member_org_group_id == member_id),
        )
    )
    log_event(
        db, entity_type="org_group", entity_id=group_id, action="member_removed", actor_id=current_user.id,
        organization_id=organization_id, detail={"member_id": str(member_id)},
    )
    db.commit()


def _now():
    """Returns the current UTC time."""
    from datetime import datetime

    return datetime.now(UTC)


# --- Shared resources (C-M-03), org logo (U-C-02), default template (C-E-04) ---


@router.post("/{organization_id}/resources", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_org_resource(
    organization_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Uploads a file as an organisation shared resource (C-M-03)."""
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "file", content_type=file.content_type or "application/octet-stream",
        data=data, is_org_resource=True,
    )
    log_event(db, entity_type="file_asset", entity_id=asset.id, action="uploaded",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{organization_id}/resources", response_model=list[FileAssetOut])
def list_org_resources(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(FileAsset).where(FileAsset.organization_id == organization_id, FileAsset.is_org_resource.is_(True))
    ).all()


@router.delete("/{organization_id}/resources/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_resource(
    organization_id: UUID, file_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    asset = db.get(FileAsset, file_id)
    if asset is None or asset.organization_id != organization_id or not asset.is_org_resource:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found.")
    db.execute(RequirementFile.__table__.delete().where(RequirementFile.file_id == file_id))
    delete_file(db, asset)
    log_event(db, entity_type="file_asset", entity_id=file_id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()


@router.post("/{organization_id}/logo", response_model=OrganizationOut)
async def upload_org_logo(
    organization_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Uploads an organisation logo, shown in the UI (U-C-02)."""
    org = db.get(Organization, organization_id)
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "logo", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    org.logo_file_id = asset.id
    log_event(db, entity_type="organization", entity_id=organization_id, action="logo_updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(org)
    return org


@router.delete("/{organization_id}/logo", response_model=OrganizationOut)
def delete_org_logo(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Reverts this organisation's logo back to the platform default by
    clearing the override (U-C-02's missing revert path). A no-op, not a
    404, when there's nothing set — this is a "make sure it's unset" action,
    not a delete of a specific known record."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if org.logo_file_id is not None:
        asset = db.get(FileAsset, org.logo_file_id)
        org.logo_file_id = None
        db.flush()
        if asset is not None:
            delete_file(db, asset)
        log_event(db, entity_type="organization", entity_id=organization_id, action="logo_removed",
                  actor_id=current_user.id, organization_id=organization_id)
        db.commit()
        db.refresh(org)
    return org


@router.delete("/{organization_id}/login-background", response_model=OrganizationOut)
def delete_org_login_background(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Reverts this organisation's login-page background image back to the
    platform default (E-P-03's missing revert path), same shape as
    `delete_org_logo`."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if org.login_background_file_id is not None:
        asset = db.get(FileAsset, org.login_background_file_id)
        org.login_background_file_id = None
        db.flush()
        if asset is not None:
            delete_file(db, asset)
        log_event(db, entity_type="organization", entity_id=organization_id, action="login_background_removed",
                  actor_id=current_user.id, organization_id=organization_id)
        db.commit()
        db.refresh(org)
    return org


@router.put("/{organization_id}/branding", response_model=OrganizationOut)
def update_org_branding(
    organization_id: UUID, payload: OrgBrandingUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sets (or clears, with null values) this organisation's UI accent
    colour, header wordmark override (U-C-01 override), and outgoing-email
    footer identity. All fall back to the platform default
    (`GET /system/branding`) when null — this endpoint never needs to know
    what that default is, it just clears its own override."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    org.accent_color_hex = payload.accent_color_hex
    org.header_title = payload.header_title
    org.email_footer_company_name = payload.email_footer_company_name
    org.email_footer_website = payload.email_footer_website
    org.email_footer_address = payload.email_footer_address
    log_event(db, entity_type="organization", entity_id=organization_id, action="branding_updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(org)
    return org


@router.put("/{organization_id}/default-template", response_model=OrganizationOut)
def set_default_template(
    organization_id: UUID, payload: DefaultTemplateUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sets (or clears, with `project_id: null`) the default template project used
    when creating a new project in this organisation (C-E-04)."""
    from app.models.project import Project

    org = db.get(Organization, organization_id)
    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if project is None or project.organization_id != organization_id or not project.is_template:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_id must be a template project in this organisation.")
    org.default_template_project_id = payload.project_id
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="default_template_updated",
        actor_id=current_user.id, organization_id=organization_id,
        detail={"project_id": str(payload.project_id) if payload.project_id else None},
    )
    db.commit()
    db.refresh(org)
    return org


@router.get("/{organization_id}/advanced-settings", response_model=OrgAdvancedSettingsOut)
def get_advanced_settings(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Per-organisation SMTP override and security/self-signup settings.

    `smtp_*` remain storage-only (see `Organization` model docstring). The
    stored `smtp_password` is never echoed back (write-only), matching how
    the bootstrap/native-auth password is handled elsewhere. SSO group→role
    mapping used to live here (`sso_group_mappings`) — it's now managed per
    `OrgGroup` instead (`GET .../groups`, item 522).
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgAdvancedSettingsOut(
        smtp_host=org.smtp_host, smtp_port=org.smtp_port, smtp_username=org.smtp_username,
        smtp_use_tls=org.smtp_use_tls,
        pat_max_lifetime_days=org.pat_max_lifetime_days, require_2fa=org.require_2fa,
        allow_self_signup=org.allow_self_signup, auto_accept_email_domain=org.auto_accept_email_domain,
        external_user_policy=org.external_user_policy,
    )


@router.put("/{organization_id}/advanced-settings", response_model=OrgAdvancedSettingsOut)
def update_advanced_settings(
    organization_id: UUID, payload: OrgAdvancedSettingsUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if payload.allow_self_signup and org.sso_only:
        # Self-signup is anonymous and un-gated by an admin, unlike every
        # other native-account-creation path (create_org_user, an admin-
        # sent invite) — letting it hand out a native password credential
        # to an sso_only org would create an account that can never log in
        # (NativeAuthBackend rejects native login when every one of a
        # user's orgs is sso_only). See docs/decisions.md.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Self-signup cannot be enabled for an SSO-only organisation."
        )
    org.smtp_host = payload.smtp_host
    org.smtp_port = payload.smtp_port
    org.smtp_username = payload.smtp_username
    if payload.smtp_password:
        # Blank means "leave unchanged" — the field is never returned by GET,
        # so a client re-submitting the form has no value to send back.
        org.smtp_password = payload.smtp_password
    org.smtp_use_tls = payload.smtp_use_tls
    org.pat_max_lifetime_days = payload.pat_max_lifetime_days
    org.require_2fa = payload.require_2fa
    org.allow_self_signup = payload.allow_self_signup
    org.auto_accept_email_domain = payload.auto_accept_email_domain.lower() if payload.auto_accept_email_domain else None
    org.external_user_policy = payload.external_user_policy
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="advanced_settings_updated",
        actor_id=current_user.id, organization_id=organization_id,
    )
    db.commit()
    db.refresh(org)
    return OrgAdvancedSettingsOut(
        smtp_host=org.smtp_host, smtp_port=org.smtp_port, smtp_username=org.smtp_username,
        smtp_use_tls=org.smtp_use_tls,
        pat_max_lifetime_days=org.pat_max_lifetime_days, require_2fa=org.require_2fa,
        allow_self_signup=org.allow_self_signup, auto_accept_email_domain=org.auto_accept_email_domain,
        external_user_policy=org.external_user_policy,
    )


@router.post("/{organization_id}/test-email", status_code=status.HTTP_204_NO_CONTENT)
def send_org_test_email(
    organization_id: UUID, payload: TestEmailRequest,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Sends a test email through this organisation's own configured SMTP
    relay (`Organization.smtp_*`, set via `update_advanced_settings` above)
    rather than the deployment-wide one, so an org admin can confirm their
    override actually works before relying on it — this is currently the
    only thing that reads `Organization.smtp_*` at all; see
    `services/email.py`'s module docstring and docs/decisions.md's "SMTP/SSO
    organisation settings are a storage-only seam" entry for why ordinary
    notification email still doesn't.

    Raises:
        HTTPException: 404 if the organisation doesn't exist; 400 if it has
            no SMTP host configured yet; 502 if the send itself fails (bad
            credentials, unreachable host, ...) — surfaced with the
            underlying error so the admin knows what to fix, since
            confirming deliverability is the entire point of this action.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if not org.smtp_host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This organisation has no SMTP host configured.")
    to_email = payload.to_email or current_user.email
    branding = resolve_email_branding(db, organization_id=organization_id)
    html_body, text_body = render_email(
        "test_email", branding=branding, source_description=f"{org.name}'s configured SMTP settings",
        cta_url=settings.frontend_base_url,
    )
    inline_images = {"brand_logo": (branding.logo_bytes, branding.logo_content_type)} if branding.logo_bytes else None
    try:
        send_email(
            to_email, f"Test email from {org.name}", text_body, html_body=html_body, inline_images=inline_images,
            smtp_override=SmtpOverride(
                host=org.smtp_host, port=org.smtp_port, username=org.smtp_username,
                password=org.smtp_password, use_tls=org.smtp_use_tls,
            ),
        )
    except Exception as err:  # noqa: BLE001 - surfacing the underlying SMTP failure is the entire point of a test-email action
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to send test email: {err}") from err
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="test_email_sent",
        actor_id=current_user.id, organization_id=organization_id, detail={"to": to_email},
    )
    db.commit()


# --- SSO / branded login page (E-U-01, E-P-03) ------------------------------


@router.get("/by-slug/{slug}/login-info", response_model=OrgLoginInfoOut)
def get_org_login_info(slug: str, db: Session = Depends(get_db)):
    """Public, unauthenticated lookup used by the org-branded login page
    (`/login/{slug}` in the frontend) to render branding and decide whether
    to show a "Sign in with SSO" button. Returns no secrets."""
    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgLoginInfoOut(
        name=org.name, slug=org.slug, logo_file_id=org.logo_file_id,
        login_background_file_id=org.login_background_file_id,
        sso_enabled=org.sso_enabled, sso_only=org.sso_only,
    )


@router.get("/{organization_id}/sso-config", response_model=OrgSsoConfigOut)
def get_sso_config(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgSsoConfigOut(
        slug=org.slug, sso_enabled=org.sso_enabled, sso_only=org.sso_only,
        oidc_issuer_url=org.oidc_issuer_url, oidc_client_id=org.oidc_client_id,
        oidc_required_group=org.oidc_required_group,
    )


@router.put("/{organization_id}/sso-config", response_model=OrgSsoConfigOut)
def update_sso_config(
    organization_id: UUID, payload: OrgSsoConfigUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Configures an organisation's OIDC SSO login (E-U-01) and its
    slug-resolved branded login page (E-P-03).

    `oidc_client_secret` is encrypted at rest at the application layer
    (`EncryptedString`, SOC 2 hardening pass) — see `models.organization`
    for details.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if payload.slug is not None:
        existing = db.scalar(select(Organization).where(Organization.slug == payload.slug))
        if existing is not None and existing.id != org.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "This slug is already in use.")
        org.slug = payload.slug
    if payload.sso_enabled and not org.slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set a slug before enabling SSO (needed for the login page URL).")
    if payload.sso_only and not payload.sso_enabled:
        # sso_only now has real backend teeth (NativeAuthBackend blocks
        # native login for a user whose every org is sso_only) — allowing it
        # to be set without sso_enabled would be a self-inflicted lockout
        # with no way to sign in at all.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enable SSO before making it the only sign-in method.")
    if payload.sso_only and org.allow_self_signup:
        # Same mutual-exclusion as update_advanced_settings, enforced from
        # this side too since either endpoint can flip the two flags.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Disable self-signup before making this organisation SSO-only."
        )
    org.sso_enabled = payload.sso_enabled
    org.sso_only = payload.sso_only
    org.oidc_issuer_url = payload.oidc_issuer_url
    org.oidc_client_id = payload.oidc_client_id
    if payload.oidc_client_secret:
        # Blank means "leave unchanged" — same pattern as smtp_password above.
        org.oidc_client_secret = payload.oidc_client_secret
    org.oidc_required_group = payload.oidc_required_group
    log_event(db, entity_type="organization", entity_id=organization_id, action="sso_config_updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(org)
    return OrgSsoConfigOut(
        slug=org.slug, sso_enabled=org.sso_enabled, sso_only=org.sso_only,
        oidc_issuer_url=org.oidc_issuer_url, oidc_client_id=org.oidc_client_id,
        oidc_required_group=org.oidc_required_group,
    )


@router.get("/{organization_id}/scim-token", response_model=ScimTokenStatusOut)
def get_scim_token_status(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Whether SCIM 2.0 provisioning (`routers/scim.py`) is enabled for
    this org, and its current token's non-secret prefix — never the token
    itself, which is only ever shown once, at (re)generation."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return ScimTokenStatusOut(enabled=org.scim_token_hash is not None, token_prefix=org.scim_token_prefix)


@router.post("/{organization_id}/scim-token", response_model=ScimTokenCreatedOut)
def regenerate_scim_token(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """(Re)generates this org's SCIM bearer token — immediately invalidates
    any previous one (a single active token per org, same as this codebase's
    Personal Access Tokens are per-user-per-token rather than allowing
    silent parallel validity). The raw secret is returned exactly once."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    raw_token, token_hash, token_prefix = generate_scim_token()
    org.scim_token_hash = token_hash
    org.scim_token_prefix = token_prefix
    log_event(db, entity_type="organization", entity_id=organization_id, action="scim_token_regenerated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return ScimTokenCreatedOut(token=raw_token, token_prefix=token_prefix)


@router.delete("/{organization_id}/scim-token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_scim_token(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Disables SCIM provisioning for this org by clearing its token —
    every subsequent SCIM request against this org 401s immediately."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    org.scim_token_hash = None
    org.scim_token_prefix = None
    log_event(db, entity_type="organization", entity_id=organization_id, action="scim_token_revoked",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()


@router.post("/{organization_id}/login-background", response_model=OrganizationOut)
async def upload_login_background(
    organization_id: UUID, file: UploadFile = File(...),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Uploads a custom background image for this organisation's branded
    login page (E-P-03), same upload pattern as the org logo."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=organization_id, uploaded_by=current_user.id,
        filename=file.filename or "login-background", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    org.login_background_file_id = asset.id
    log_event(db, entity_type="organization", entity_id=organization_id, action="login_background_updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(org)
    return org


# --- Report templates (R-G-05) -----------------------------------------------


@router.post("/{organization_id}/report-templates", response_model=ReportTemplateOut, status_code=status.HTTP_201_CREATED)
def create_report_template(
    organization_id: UUID, payload: ReportTemplateCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates a named PDF report branding preset for this organisation (R-G-05)."""
    template = ReportTemplate(
        organization_id=organization_id, name=payload.name, accent_color_hex=payload.accent_color_hex,
        include_cover_page=payload.include_cover_page, include_logo=payload.include_logo,
        footer_text=payload.footer_text, created_by=current_user.id,
        intro=payload.intro, chapters=[c.model_dump() for c in payload.chapters],
        appendices=[c.model_dump() for c in payload.appendices],
        chapters_per_component=payload.chapters_per_component,
    )
    db.add(template)
    db.flush()
    log_event(db, entity_type="report_template", entity_id=template.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template


@router.get("/{organization_id}/report-templates", response_model=list[ReportTemplateOut])
def list_report_templates(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's report templates — any org member may select
    one when generating a report, so listing isn't admin-only (only
    create/edit/delete are)."""
    return db.scalars(select(ReportTemplate).where(ReportTemplate.organization_id == organization_id)).all()


@router.put("/{organization_id}/report-templates/{template_id}", response_model=ReportTemplateOut)
def update_report_template(
    organization_id: UUID, template_id: UUID, payload: ReportTemplateCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    template = db.get(ReportTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report template not found.")
    template.name = payload.name
    template.accent_color_hex = payload.accent_color_hex
    template.include_cover_page = payload.include_cover_page
    template.include_logo = payload.include_logo
    template.footer_text = payload.footer_text
    template.intro = payload.intro
    template.chapters = [c.model_dump() for c in payload.chapters]
    template.appendices = [c.model_dump() for c in payload.appendices]
    template.chapters_per_component = payload.chapters_per_component
    log_event(db, entity_type="report_template", entity_id=template.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{organization_id}/report-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report_template(
    organization_id: UUID, template_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    template = db.get(ReportTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report template not found.")
    log_event(db, entity_type="report_template", entity_id=template.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.delete(template)
    db.commit()


@router.get("/{organization_id}/report-defaults", response_model=OrgReportDefaults)
def get_org_report_defaults(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Returns this organisation's default report intro/chapters/appendices
    (UI/UX pass) — the content a project falls back to per-field when it
    hasn't set its own (`services.reports.resolve_report_config`)."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgReportDefaults(
        intro=org.default_report_intro or "",
        chapters=org.default_report_chapters or [],
        appendices=org.default_report_appendices or [],
    )


@router.put("/{organization_id}/report-defaults", response_model=OrgReportDefaults)
def update_org_report_defaults(
    organization_id: UUID, payload: OrgReportDefaults,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Saves this organisation's default report content. Saved as `None`
    rather than an empty string/list when blank, so a project with genuinely
    no content of its own falls through cleanly to "no default either"
    instead of storing a meaningless empty-vs-empty distinction."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    org.default_report_intro = payload.intro or None
    org.default_report_chapters = [c.model_dump() for c in payload.chapters] or None
    org.default_report_appendices = [c.model_dump() for c in payload.appendices] or None
    log_event(db, entity_type="organization", entity_id=organization_id, action="report_defaults_updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(org)
    return OrgReportDefaults(
        intro=org.default_report_intro or "",
        chapters=org.default_report_chapters or [],
        appendices=org.default_report_appendices or [],
    )


# --- Personal Access Tokens (org-admin incident-response actions) -----------
#
# Self-service creation/listing/revocation lives in routers/pats.py under
# /api/v1/me/pats. These are the org-admin-side actions: see any non-revoked
# token touching this org (across every member), revoke or descope one
# specific token, or revoke every token touching this org in one action —
# see docs/decisions.md's "Personal Access Tokens" section for the full
# design, in particular why the per-token view only ever reveals *how many*
# other orgs a multi-org token also reaches, never which ones.


def _get_org_pat_or_404(db: Session, organization_id: UUID, pat_id: UUID) -> PersonalAccessToken:
    # Row-locked (not a plain db.get): descope_org_pat below does a
    # read-modify-write on allowed_organization_ids (read the current list,
    # remove one org, write it back) — without a lock, two concurrent
    # descope calls on the same multi-org token (e.g. org A's admin and org
    # B's admin both reacting to the same incident at once, exactly the
    # scenario this feature exists for) would each read the same
    # pre-removal list and whichever commits last would silently overwrite
    # the other's removal, leaving that org's admin believing their
    # descope succeeded (204, a real audit-log row) when the token in fact
    # remained scoped to their org. The lock makes the second call block
    # until the first commits, then read the already-updated list.
    pat = db.scalar(select(PersonalAccessToken).where(PersonalAccessToken.id == pat_id).with_for_update())
    if pat is None or str(organization_id) not in pat.allowed_organization_ids:
        # 404, not 403: this org's admin must not be able to distinguish
        # "no such token" from "a real token that just isn't scoped here."
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personal access token not found.")
    return pat


@router.get("/{organization_id}/pats", response_model=list[OrgPersonalAccessTokenOut])
def list_org_pats(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    pats = db.scalars(
        select(PersonalAccessToken)
        .where(
            PersonalAccessToken.revoked_at.is_(None),
            PersonalAccessToken.allowed_organization_ids.contains([str(organization_id)]),
        )
        .order_by(PersonalAccessToken.created_at.desc())
    ).all()
    owners = {u.id: u for u in db.scalars(select(User).where(User.id.in_({p.user_id for p in pats}))).all()}
    return [
        OrgPersonalAccessTokenOut(
            id=p.id, user_id=p.user_id,
            user_email=owners[p.user_id].email, user_display_name=owners[p.user_id].display_name,
            name=p.name, token_prefix=p.token_prefix, expires_at=effective_expiry(db, p),
            other_org_count=len(p.allowed_organization_ids) - 1,
            last_used_at=p.last_used_at, created_at=p.created_at,
        )
        for p in pats
    ]


@router.post("/{organization_id}/pats/{pat_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_org_pat(
    organization_id: UUID, pat_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Revokes one specific token outright — e.g. a member who has left
    this org, whose token isn't (or shouldn't remain) usable anywhere."""
    pat = _get_org_pat_or_404(db, organization_id, pat_id)
    pat.revoked_at = datetime.now(UTC)
    log_event(
        db, entity_type="personal_access_token", entity_id=pat.id, action="org_pat_revoked",
        actor_id=current_user.id, organization_id=organization_id, detail={"pat_owner_id": str(pat.user_id)},
    )
    db.commit()


@router.post("/{organization_id}/pats/{pat_id}/descope", status_code=status.HTTP_204_NO_CONTENT)
def descope_org_pat(
    organization_id: UUID, pat_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Removes this org from a token's scope, leaving it valid for the
    member's other orgs — the softer alternative to `revoke_org_pat` when a
    multi-org token shouldn't reach this org anymore but its owner still
    legitimately needs it elsewhere. Auto-revokes if this was the token's
    only remaining org (a token scoped to nothing can never authenticate
    anything anyway)."""
    pat = _get_org_pat_or_404(db, organization_id, pat_id)
    pat.allowed_organization_ids = [oid for oid in pat.allowed_organization_ids if oid != str(organization_id)]
    if not pat.allowed_organization_ids:
        pat.revoked_at = datetime.now(UTC)
    log_event(
        db, entity_type="personal_access_token", entity_id=pat.id, action="org_pat_descoped",
        actor_id=current_user.id, organization_id=organization_id, detail={"pat_owner_id": str(pat.user_id)},
    )
    db.commit()


@router.post("/{organization_id}/pats/revoke-all", response_model=BulkRevokeResult)
def revoke_all_org_pats(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Revokes every non-revoked token touching this org, across every
    member, in one incident-response action. Fully kills each matching
    token — including any other orgs it's also scoped to — rather than
    just descoping this org from it; see docs/decisions.md for why."""
    count = revoke_matching(db, PersonalAccessToken.allowed_organization_ids.contains([str(organization_id)]))
    log_event(
        db, entity_type="organization", entity_id=organization_id, action="org_pats_bulk_revoked",
        actor_id=current_user.id, organization_id=organization_id, detail={"count": count},
    )
    db.commit()
    return BulkRevokeResult(revoked_count=count)


# --- Project statuses (org-definable, C-G-04-style admin list) --------------
#
# Shared rename/reorder/delete-with-reassignment rules described in
# `services.definitions`' module docstring — identical contract to the
# link-types section below and to `routers.action_types`, just scoped to an
# organisation instead of a project.


@router.post("/{organization_id}/project-statuses", response_model=ProjectStatusOut, status_code=status.HTTP_201_CREATED)
def create_project_status(
    organization_id: UUID, payload: ProjectStatusCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates a new project status for this organisation."""
    existing = db.scalar(
        select(ProjectStatusDefinition.id).where(
            ProjectStatusDefinition.organization_id == organization_id, ProjectStatusDefinition.name == payload.name
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project status with this name already exists.")
    count = len(
        db.scalars(select(ProjectStatusDefinition.id).where(ProjectStatusDefinition.organization_id == organization_id)).all()
    )
    project_status = ProjectStatusDefinition(organization_id=organization_id, name=payload.name, sort_order=count)
    db.add(project_status)
    db.flush()
    log_event(db, entity_type="project_status_definition", entity_id=project_status.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": project_status.name})
    db.commit()
    db.refresh(project_status)
    return project_status


@router.get("/{organization_id}/project-statuses", response_model=list[ProjectStatusOut])
def list_project_statuses(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's project statuses — any org member may need
    this to populate a project's status picker, so listing isn't admin-only
    (only create/rename/move/delete are), mirroring `list_report_templates`."""
    return db.scalars(
        select(ProjectStatusDefinition).where(ProjectStatusDefinition.organization_id == organization_id)
        .order_by(ProjectStatusDefinition.sort_order)
    ).all()


@router.post("/{organization_id}/project-statuses/{status_id}/move", response_model=ProjectStatusOut)
def move_project_status(
    organization_id: UUID, status_id: UUID, payload: MoveDirection,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Moves a project status up/down in display order."""
    result = move_ordered(
        db, ProjectStatusDefinition, [ProjectStatusDefinition.organization_id == organization_id], status_id, payload.direction
    )
    log_event(db, entity_type="project_status_definition", entity_id=status_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{organization_id}/project-statuses/{status_id}", response_model=ProjectStatusOut)
def rename_project_status(
    organization_id: UUID, status_id: UUID, payload: ProjectStatusUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Renames a project status. Every `Project.status_id` reference points
    at this row's id, never its name, so renaming has zero effect on any
    project currently on this status — see `services.definitions`' module
    docstring."""
    project_status = db.get(ProjectStatusDefinition, status_id)
    if project_status is None or project_status.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project status not found.")
    existing = db.scalar(
        select(ProjectStatusDefinition.id).where(
            ProjectStatusDefinition.organization_id == organization_id, ProjectStatusDefinition.name == payload.name,
            ProjectStatusDefinition.id != status_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project status with this name already exists.")
    project_status.name = payload.name
    log_event(db, entity_type="project_status_definition", entity_id=project_status.id, action="renamed",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(project_status)
    return project_status


@router.delete("/{organization_id}/project-statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_status(
    organization_id: UUID, status_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Deletes a project status, applying the shared rename/delete/reassign
    rules (§4.0): refuses to leave the organisation with zero statuses
    (409), and requires an explicit `reassign_to_id` to delete a status
    that's currently in use by any `Project` (409 naming the count if
    omitted; bulk-reassigns then deletes if provided) — see
    `services.definitions.delete_definition_with_reassignment`'s docstring
    for the exact behaviour.
    """
    delete_definition_with_reassignment(
        db, definition_model=ProjectStatusDefinition, scope_column=ProjectStatusDefinition.organization_id,
        scope_id=organization_id, item_id=status_id, reassign_to_id=reassign_to_id,
        referencing_model=Project, referencing_fk_column=Project.status_id, referencing_fk_name="status_id",
        entity_type="project_status_definition", noun="status", plural_noun="project(s)", reassign_verb="move",
        min_count_message="An organisation must always have at least one project status.",
        actor_id=current_user.id, organization_id=organization_id, project_id=None,
    )
    db.commit()


# --- Requirement link types (org-definable, bidirectional, C-G-09) ----------
#
# Same shared rename/reorder/delete-with-reassignment rules as the project
# statuses section above, with one addition: `PATCH` renames *both*
# directional names at once (`forward_name`/`reverse_name`), since a link
# type has no single `name` column.


@router.post("/{organization_id}/link-types", response_model=LinkTypeOut, status_code=status.HTTP_201_CREATED)
def create_link_type(
    organization_id: UUID, payload: LinkTypeCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates a new requirement link type for this organisation (C-G-09)."""
    existing = db.scalar(
        select(RequirementLinkTypeDefinition.id).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == payload.forward_name,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A link type with this forward name already exists.")
    count = len(
        db.scalars(
            select(RequirementLinkTypeDefinition.id).where(RequirementLinkTypeDefinition.organization_id == organization_id)
        ).all()
    )
    link_type = RequirementLinkTypeDefinition(
        organization_id=organization_id, forward_name=payload.forward_name, reverse_name=payload.reverse_name,
        sort_order=count,
    )
    db.add(link_type)
    db.flush()
    log_event(db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="created",
              actor_id=current_user.id, organization_id=organization_id,
              detail={"forward_name": link_type.forward_name, "reverse_name": link_type.reverse_name})
    db.commit()
    db.refresh(link_type)
    return link_type


@router.get("/{organization_id}/link-types", response_model=list[LinkTypeOut])
def list_link_types(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's requirement link types — any org member may
    need this to populate a requirement's "add link" form, so listing isn't
    admin-only (only create/rename/move/delete are)."""
    return db.scalars(
        select(RequirementLinkTypeDefinition).where(RequirementLinkTypeDefinition.organization_id == organization_id)
        .order_by(RequirementLinkTypeDefinition.sort_order)
    ).all()


@router.post("/{organization_id}/link-types/{link_type_id}/move", response_model=LinkTypeOut)
def move_link_type(
    organization_id: UUID, link_type_id: UUID, payload: MoveDirection,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Moves a link type up/down in display order."""
    result = move_ordered(
        db, RequirementLinkTypeDefinition, [RequirementLinkTypeDefinition.organization_id == organization_id],
        link_type_id, payload.direction,
    )
    log_event(db, entity_type="requirement_link_type_definition", entity_id=link_type_id, action="reordered",
              actor_id=current_user.id, organization_id=organization_id, detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{organization_id}/link-types/{link_type_id}", response_model=LinkTypeOut)
def rename_link_type(
    organization_id: UUID, link_type_id: UUID, payload: LinkTypeUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Renames both directional names of a link type at once. Every
    `RequirementLink.link_type_id` reference points at this row's id,
    never its names, so renaming has zero effect on any existing link
    using this type — see `services.definitions`' module docstring."""
    link_type = db.get(RequirementLinkTypeDefinition, link_type_id)
    if link_type is None or link_type.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link type not found.")
    existing = db.scalar(
        select(RequirementLinkTypeDefinition.id).where(
            RequirementLinkTypeDefinition.organization_id == organization_id,
            RequirementLinkTypeDefinition.forward_name == payload.forward_name,
            RequirementLinkTypeDefinition.id != link_type_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A link type with this forward name already exists.")
    link_type.forward_name = payload.forward_name
    link_type.reverse_name = payload.reverse_name
    log_event(db, entity_type="requirement_link_type_definition", entity_id=link_type.id, action="renamed",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(link_type)
    return link_type


@router.delete("/{organization_id}/link-types/{link_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link_type(
    organization_id: UUID, link_type_id: UUID, reassign_to_id: UUID | None = Query(None),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Deletes a link type, applying the shared rename/delete/reassign
    rules (§4.0): refuses to leave the organisation with zero link types
    (409), and requires an explicit `reassign_to_id` to delete a type
    that's currently in use by any `RequirementLink` (409 naming the count
    if omitted; bulk-reassigns then deletes if provided). Reassignment here
    changes each affected link's asserted meaning, which is exactly why
    it's the admin's explicit choice rather than an automatic cascade or
    silent delete — see `services.definitions.delete_definition_with_reassignment`'s
    docstring for the exact behaviour.
    """
    delete_definition_with_reassignment(
        db, definition_model=RequirementLinkTypeDefinition, scope_column=RequirementLinkTypeDefinition.organization_id,
        scope_id=organization_id, item_id=link_type_id, reassign_to_id=reassign_to_id,
        referencing_model=RequirementLink, referencing_fk_column=RequirementLink.link_type_id,
        referencing_fk_name="link_type_id", entity_type="requirement_link_type_definition", noun="link type",
        plural_noun="link(s)", reassign_verb="convert",
        min_count_message="An organisation must always have at least one requirement link type.",
        actor_id=current_user.id, organization_id=organization_id, project_id=None, name_attr="forward_name",
    )
    db.commit()
