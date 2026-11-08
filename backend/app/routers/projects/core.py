"""
Module: routers.projects.core

Core project CRUD (create/import/list/tree/get/patch), favouriting,
project-scoped file listing, export, terminology, the changes-over-time
timeline, and overview metrics (U-P-05) — plus `_accessible_project_ids`,
the shared project-visibility computation every other `routers.projects`
sub-module (and `routers.orgs`'s org overview-stats endpoint) builds on.

Split out of the former flat `routers/projects.py` (now the `projects`
package) as a pure code-organization refactor — see
`routers/projects/__init__.py`'s module docstring for the package layout.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import (
    OrgRole,
    ProjectRole,
    ProjectRoleInheritanceMode,
    ProjectVisibility,
    StagePhaseKind,
)
from app.models.organization import Organization
from app.models.project import (
    FavoriteProject,
    Project,
    ProjectGroup,
    ProjectGroupMember,
    ProjectGroupRole,
    ProjectStage,
    UserProjectRole,
)
from app.models.project_status import ProjectStatusDefinition
from app.models.requirement import Requirement
from app.models.user import User
from app.modules.registry import memoize_module_state, run_on_project_created_hooks, snapshot_project_module_state
from app.schemas.changes import ChangeEntryOut
from app.schemas.file import ProjectFileOut, ProjectFileSearchIn, ProjectFileUploaderOut
from app.schemas.project import (
    ProjectAncestorOut,
    ProjectCreate,
    ProjectImportResult,
    ProjectListItemOut,
    ProjectMetricsOut,
    ProjectMyRolesOut,
    ProjectOut,
    ProjectTreeNodeOut,
    ProjectUpdate,
    RecordTypeCountOut,
    StageProgressOut,
    TerminologyUpdate,
)
from app.services import tags as tag_service
from app.services.audit import log_event
from app.services.bundle_common import bundle_size, iter_bundle_file
from app.services.changes import get_project_changes
from app.services.codes import assign_project_code, change_project_code
from app.services.definitions import get_default_project_status_id, seed_action_types
from app.services.downloads import filename_safe
from app.services.lookups import project_or_404
from app.services.org_membership import assert_account_active
from app.services.project_access import accessible_project_ids as _accessible_project_ids
from app.services.project_counts import project_counts, project_stage_progress
from app.services.project_export import build_project_bundle, import_project_bundle
from app.services.project_files import FileFilters, project_file_rows, project_uploaders, row_identity
from app.services.project_hierarchy import build_project_tree, would_create_project_cycle
from app.services.project_scope import ProjectScope
from app.services.rbac import (
    can_manage_project_settings,
    check_pat_scope,
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_roles,
    is_org_admin,
    lock_project_for_update,
    memoize_user_lookups,
    prefetch_project_roles,
    require_project_manage,
    require_project_view,
    require_project_view_or_manage,
)
from app.services.record_counts import count_records_by_type
from app.services.stage_workflows import new_stage, phase_index
from app.services.template_guard import ensure_may_publish_template
from app.services.templates import clone_project

router = APIRouter(tags=["projects-core"])

def _project_out_with_redacted_parent(db: Session, current_user: User, project: Project) -> ProjectOut:
    """Builds a `ProjectOut` with `parent_project_id`/`parent_project_name`
    redacted unless the caller has effective view access to the parent, or
    manages `project` itself — the same visibility-boundary rule
    `list_projects` already applies to `ProjectListItemOut`, extended here
    to every endpoint that returns a single `Project` directly (`GET/PATCH/
    POST .../archive/.../unarchive/.../terminology`). Without the general
    redaction, `GET /{project_id}` — gated by `require_project_view`, not
    manage — would let *any* project viewer learn a hidden parent's
    identity just by fetching the project directly, even though
    `list_projects`/`/ancestors` correctly redact it.

    The manager exemption closes a real gap found in this branch's own
    hardening pass: `ProjectAdminPage.tsx`'s settings form (frontend) has
    always assumed — per its own inline comment and docs/decisions.md's
    "Hierarchical projects" entry ("a project's own manager already holds
    the highest level of authority over this relationship and needs to see
    it to do their job") — that a project's manager sees the true parent
    here, never a redacted one. Before this fix that assumption was false:
    a manager with no independent view access to the parent (a realistic,
    common case — nothing ties managing a child to having any role on its
    parent) saw `parent_project_id: null`, the same as any other viewer.
    Combined with `saveSettings()` unconditionally resending
    `parent_project_id` on every save (not just when the field was
    actually touched), this silently detached the project from its real
    parent on the next unrelated settings save — a genuine, unannounced
    structural mutation the manager never intended. A project's own
    manager already has unilateral authority to detach or reparent this
    exact relationship via this same endpoint, so showing them the true
    value they already have the power to change is not a new disclosure.
    """
    out = ProjectOut.model_validate(project)
    if project.parent_project_id is None:
        return out
    if can_manage_project_settings(db, current_user, project) or project.parent_project_id in _accessible_project_ids(
        db, current_user.id
    ):
        parent = db.get(Project, project.parent_project_id)
        out.parent_project_name = parent.name if parent is not None else None
        return out
    out.parent_project_id = None
    return out


def _ensure_project_has_a_manager(db: Session, project: Project, fallback_user_id: UUID) -> None:
    """C-U-08 fallback: guarantees `project` has at least one effective
    manager, granting `fallback_user_id` one if it doesn't.

    Shared by both of `create_project`'s branches (2026-08-31 — previously only the template-clone branch needed this
    at all, since the non-template branch always auto-created its own
    manager-role `ProjectGroup` and added the creator to it directly).
    Prefers adding `fallback_user_id` to an existing manager-role
    `ProjectGroup` on `project` if one exists (only possible here via a
    template clone that copied a user-created manager-role group — a
    from-scratch project has zero groups at the point this is called, so
    that branch is structurally unreachable there and this always falls
    through to the direct grant); otherwise grants a direct
    `PROJECT_MANAGER` `UserProjectRole`, mirroring the guarantee
    `import_project_bundle` (`services.project_export`) gives its own
    importer for the same reason.
    """
    if get_effective_project_managers(db, project.id):
        return
    fallback_group = db.scalar(
        select(ProjectGroup)
        .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
        .where(ProjectGroup.project_id == project.id, ProjectGroupRole.role == ProjectRole.PROJECT_MANAGER)
    )
    if fallback_group is not None:
        db.add(ProjectGroupMember(project_group_id=fallback_group.id, user_id=fallback_user_id))
    else:
        db.add(UserProjectRole(user_id=fallback_user_id, project_id=project.id, role=ProjectRole.PROJECT_MANAGER))


def _require_user_in_org(db: Session, user_id: UUID, organization_id: UUID) -> None:
    """C-U-02: "All Project users, must be an organisation user." Raises 400
    if `user_id` holds no role at all in `organization_id`, so a project
    manager can't grant project-level access to someone outside the
    organisation. Shared by `routers.projects.groups` and `.roles`.
    """
    if not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The user must be a member of this project's organisation first."
        )
    assert_account_active(db, user_id)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a project within an organisation.

    Two authorization paths (hierarchical-projects decision 11 in
    docs/decisions.md):
      1. Org-level (C-U-01: project_creator/org_admin) — today's original
         behaviour, unchanged. Works with or without `parent_project_id`.
      2. Relaxed, parent-scoped — the caller lacks an org-level role but
         `parent_project_id` is set, they manage that exact parent
         (`can_manage_project_settings`), and the organisation hasn't
         turned this path off (`Organization.allow_relaxed_child_project_
         creation`, default on). This is what makes "Add sub-project" from
         a project's own page usable by an ordinary project manager. The
         resulting project is marked `parent_required=True` — see
         `Project.parent_required`'s docstring for why, and
         `update_project` below for the one behavioural consequence.
    Either path: if `parent_project_id` is set, the caller must also manage
    the target parent (not just view it) — attaching to a parent is
    authorized by *both* sides, unlike detaching (see decision 12).

    On creation, the creator is granted a direct `PROJECT_MANAGER`
    `UserProjectRole` (C-U-10) — unless a template project is used (C-E-05),
    per C-U-10's explicit "unless using a template project" clause:
    groups/members (and, 2026-08-31, direct role
    grants too) are copied from the template instead, via `clone_project`.
    If that leaves the new project with no manager at all, the creator is
    still added as a fallback (the exact same
    `get_effective_project_managers`-then-fallback-`UserProjectRole` code
    path both branches below now share) so C-U-08 (every project must have
    a manager) can never be violated. This is unconditional regardless of
    `parent_project_id`/`role_inheritance_mode` — a newly created project
    always gets its own direct, individually accountable manager, so
    creation-time C-U-08 never depends on inheritance being present or
    stable later.

    Prior to 2026-08-31 (2026-08-31), the non-template
    path instead auto-created four "standard" `ProjectGroup` rows
    (`is_default=True`) and added the creator to the manager-role one —
    see docs/decisions.md's entry on that migration for why this changed
    (in short: those four groups could never be deleted, existed on every
    project whether wanted or not, and made group membership the only path
    to a first manager even though direct grants were always the simpler,
    equally-supported mechanism for a single person).

    `organization_id` lives in the request body here (the project doesn't
    exist yet to have a path segment of its own), so — unlike every other
    org/project-scoped endpoint — it isn't covered by `require_org_role`'s
    or `require_project_*`'s built-in PAT-scope check; enforced explicitly
    here instead.
    """
    check_pat_scope(request, payload.organization_id)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")

    org_roles = get_effective_org_roles(db, current_user.id, payload.organization_id)
    has_org_level_create_rights = bool(org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR})

    parent_project: Project | None = None
    if payload.parent_project_id is not None:
        parent_project = db.get(Project, payload.parent_project_id)
        if parent_project is None or parent_project.organization_id != payload.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "parent_project_id must be a project in this organisation.")
        if not can_manage_project_settings(db, current_user, parent_project):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You must manage the parent project to create a child under it.")
        if not parent_project.can_be_parent:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This project has not been made eligible to be a parent — enable "
                "\"Allow this project to be a parent\" on it first.",
            )

    parent_required = False
    if not has_org_level_create_rights:
        if parent_project is None or not org.allow_relaxed_child_project_creation:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only org admins or project creators may create projects.")
        parent_required = True

    template_project_id = payload.template_project_id
    if template_project_id is None and payload.use_template:
        # C-E-04: fall back to the organisation's configured default template
        # when the caller didn't specify one and did not ask for none
        # (`use_template=False` creates a blank project even when a default exists).
        template_project_id = org.default_template_project_id

    project_code = assign_project_code(db, payload.organization_id, payload.name, payload.code)

    if template_project_id is not None:
        template = db.get(Project, template_project_id)
        if (
            template is None
            or template.organization_id != payload.organization_id
            or not template.is_template
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "template_project_id must be a template project in this organisation.")
        # A template is used by reading it, so the caller must be able to: a hidden template is not usable by
        # guessing its id. The organisation's default template is the exception: an organisation administrator
        # chose it to be the starting point for every new project, so its creators may use it without access.
        is_org_default = template.id == org.default_template_project_id  # an administrator's deliberate offer to creators
        if not is_org_default and not get_effective_project_roles(db, current_user.id, template.id) and not can_manage_project_settings(
            db, current_user, template,
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You cannot view that template project. Choose another template, or choose none to create a blank project.",
            )
        project = clone_project(
            db, template, name=payload.name, summary=payload.summary, creator=current_user,
            parent_project_id=payload.parent_project_id, code=project_code, report_name=payload.report_name,
        )
        db.flush()
        _ensure_project_has_a_manager(db, project, current_user.id)
    else:
        project = Project(
            organization_id=payload.organization_id, name=payload.name, summary=payload.summary, code=project_code,
            report_name=payload.report_name, status_id=get_default_project_status_id(db, payload.organization_id),
            parent_project_id=payload.parent_project_id,
        )
        db.add(project)
        db.flush()

        new_stage(db, project, "Scoping", 0, is_current=True)

        # C-U-10: the creator becomes the project's initial manager via a
        # direct grant — no group is auto-created any more (docs/decisions.md). This project
        # has zero groups at this point, so `_ensure_project_has_a_manager`'s
        # "existing manager-role group" branch is unreachable here and it
        # always takes the direct-grant path — the exact same fallback the
        # template-clone branch above uses, reused rather than duplicated.
        _ensure_project_has_a_manager(db, project, current_user.id)

        # Default action types (Review, Test) — seeded fresh for a manually-
        # created project. A template-cloned project instead *copies* the
        # template's own action types (see `clone_project`), the same
        # treatment as its custom field definitions, so an admin's
        # customisations to a template carry over rather than being
        # silently reset to defaults. A project created with a parent is
        # skipped entirely: it starts with zero of its own and immediately
        # falls back to the nearest ancestor's
        # (`services.project_hierarchy.resolve_effective_action_types`),
        # always on regardless of the RBAC inheritance settings above.
        if payload.parent_project_id is None:
            seed_action_types(db, project.id)

    # Copy the org's current module/sub-component defaults into the new
    # project (blank or template-cloned alike), so a later change to an org
    # default never flips this project (Decided by: User, 2026-10-04).
    snapshot_project_module_state(db, project.id, project.organization_id)

    ensure_may_publish_template(
        db, current_user, payload.organization_id, is_template=payload.is_template, visibility=payload.visibility,
        already_published=False,
    )
    if payload.terminology:
        project.terminology = payload.terminology
    if payload.is_template:
        project.is_template = True
    # Always explicit, never inherited from a cloned template — see
    # ProjectCreate.visibility's docstring.
    project.visibility = payload.visibility
    project.role_inheritance_mode = payload.role_inheritance_mode
    project.role_inheritance_filter_role = payload.role_inheritance_filter_role
    project.parent_required = parent_required
    project.can_be_parent = payload.can_be_parent

    log_event(
        db, entity_type="project", entity_id=project.id, action="created", actor_id=current_user.id,
        organization_id=payload.organization_id, project_id=project.id,
        detail={"template_project_id": str(template_project_id)} if template_project_id else None,
    )
    # Generic module-contributed project-creation reaction (e.g.
    # Compliance's reconciliation of `applies_to_all_projects`
    # standards) — this core router never imports a specific module; see
    # `ModuleDefinition.on_project_created`'s own docstring for why
    # project-creation time, not a module-enable hook, is where this has to
    # run.
    run_on_project_created_hooks(db, project, current_user.id)

    if payload.parent_project_id is not None:
        log_event(
            db, entity_type="project", entity_id=project.id, action="parented", actor_id=current_user.id,
            organization_id=payload.organization_id, project_id=project.id,
            detail={
                "parent_project_id": str(payload.parent_project_id),
                "parent_required": parent_required,
                "role_inheritance_mode": payload.role_inheritance_mode.value,
            },
        )
    db.commit()
    db.refresh(project)
    return _project_out_with_redacted_parent(db, current_user, project)


@router.post("/import", response_model=ProjectImportResult, status_code=status.HTTP_201_CREATED)
async def import_project(
    request: Request,
    organization_id: UUID = Form(...), name: str = Form(...), summary: str | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Creates a brand-new project in `organization_id` from an uploaded
    project export bundle (`GET /{project_id}/export` — see
    `services.project_export`'s module docstring for the full bundle
    contents: structure, custom field definitions, and full history).

    Authorization mirrors plain project creation (`POST /projects`) exactly
    — org admins or project creators of the *target* organisation — which
    is what makes cross-organisation import safe: the bundle itself carries
    no ids or org references, only names/prefixes/emails resolved fresh
    against whatever org the caller is authorized to create in.

    Registered before `GET /{project_id}` so the static "/import" path
    isn't swallowed by that dynamic route.
    """
    check_pat_scope(request, organization_id)
    org_roles = get_effective_org_roles(db, current_user.id, organization_id)
    if not org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only org admins or project creators may create projects.")

    zip_bytes = await file.read()
    # The import tags and names thousands of records in one organisation and project: each organisation role and
    # each scope's tag list is read once, not once per record.
    with memoize_user_lookups(), tag_service.reuse_offered_tags():
        project, warnings = import_project_bundle(
            db, organization_id=organization_id, name=name, summary=summary, zip_bytes=zip_bytes, current_user=current_user
        )
    return ProjectImportResult(project=ProjectOut.model_validate(project), warnings=warnings)


@router.get("/tree", response_model=list[ProjectTreeNodeOut])
def get_project_tree(
    organization_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Returns the full project hierarchy for one organisation, restricted
    to the caller's accessible set — a node whose real parent isn't
    accessible is rendered as a root, never omitted or hinting at a hidden
    parent (visibility-boundary rule, see docs/decisions.md). Registered
    before `GET /{project_id}` so the static "/tree" path isn't swallowed
    by that dynamic route (same reasoning as `POST /import`'s ordering).
    """
    accessible_ids = _accessible_project_ids(db, current_user.id)
    # Defence in depth: same-org is already enforced when parent_project_id
    # is set, but build_project_tree also re-filters by organization_id
    # itself, matching this codebase's existing pattern of re-checking a
    # write-time invariant on the read side too.
    return build_project_tree(db, organization_id, accessible_ids)


@router.get("", response_model=list[ProjectListItemOut])
def list_projects(
    response: Response,
    archived: bool = False,
    search: str | None = None,
    role: ProjectRole | None = None,
    stage_phase_kind: StagePhaseKind | None = None,
    organization_id: UUID | None = None,
    favorite_only: bool = False,
    include_templates: bool = False,
    templates_only: bool = False,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Project list view (U-E-03, U-E-04): active/archived projects the user can access.

    Template projects (`is_template`) are left out unless `include_templates` is set;
    `templates_only` returns only templates (the "New project" template picker and the
    organisation default-template setting use it), and overrides `include_templates`.

    `favorite_only` powers `FavouritesPage`, the same shape as every other
    filter here rather than a separate endpoint — a favourited-projects
    listing is otherwise identical to this one (search, org filter, and
    pagination all still make sense over it, and it needs sorted-favourites-
    first no more or less than the unfiltered list already gets below).

    Supports an optional `role` filter (only projects where the caller holds
    the given effective project role), `stage_phase_kind` filter (only projects
    whose current stage is in a phase of the given kind) for U-E-05, and
    `organization_id` (only projects in that organisation — for a user
    belonging to more than one, this replaces having to visit each
    organisation separately to see just its projects). Results are sorted
    with the caller's favourited projects (U-U-03) first, then by name.
    `limit`/`offset` (U-P-06) are optional pagination — see
    `list_requirements` for the same pattern and its rationale.

    `X-Total-Unfiltered-Count` is a second response header reporting the
    count within only the mandatory accessible-projects + default
    archived-visibility scope, before `organization_id`/`search`/`role`/
    `stage_phase_kind`/`favorite_only` narrow it further — unlike
    `X-Total-Count`, it does not change when the caller applies one of
    those filters.
    """
    # Role resolution below runs once per accessible project; cache the
    # caller's user-level lookups (org groups, org roles) for this read-only
    # request instead of re-querying them per project — see
    # `rbac.memoize_user_lookups`.
    with memoize_user_lookups():
        # No server-admin bypass here (I-M-05): project listings are "data within
        # organisations", so even server admins only see projects they hold a
        # genuine role in, same as anyone else.
        accessible_ids = _accessible_project_ids(db, current_user.id)
        projects: list[Project]
        if not accessible_ids:
            projects = []
            response.headers["X-Total-Unfiltered-Count"] = "0"
        else:
            # Joins to Organization to exclude projects belonging to a disabled
            # org (`Organization.is_active`) — a disabled org locks out its own
            # content everywhere else (`rbac._require_org_active`), and this
            # aggregate cross-org listing had been the one place that check
            # didn't reach, since it filters by project accessible-ids rather
            # than going through a per-org `require_org_role` dependency.
            #
            # `base_conditions` (no `organization_id`) is the mandatory scope
            # for the unfiltered count above — `organization_id` is itself a
            # FilterPanel filter (the "Organisation" dropdown), the same
            # relationship `category_id` has to `RequirementsPage`'s unfiltered
            # count, so it's added only to `conditions` below, after the count
            # is taken.
            base_conditions = [
                Project.id.in_(accessible_ids),
                Project.is_archived == archived,
                Organization.is_active.is_(True),
            ]
            response.headers["X-Total-Unfiltered-Count"] = str(
                db.scalar(
                    select(func.count()).select_from(
                        select(Project.id)
                        .join(Organization, Organization.id == Project.organization_id)
                        .where(*base_conditions)
                        .subquery()
                    )
                )
            )
            conditions = list(base_conditions)
            if organization_id is not None:
                conditions.append(Project.organization_id == organization_id)
            projects = list(db.scalars(
                select(Project).join(Organization, Organization.id == Project.organization_id).where(*conditions)
            ).all())

        if templates_only:
            projects = [p for p in projects if p.is_template]
        elif not include_templates:
            projects = [p for p in projects if not p.is_template]

        if search:
            needle = search.lower()
            projects = [p for p in projects if needle in p.name.lower() or needle in p.summary.lower()]

        favorite_ids = set(
            db.scalars(select(FavoriteProject.project_id).where(FavoriteProject.user_id == current_user.id)).all()
        )
        org_names = dict(
            db.execute(
                select(Organization.id, Organization.name).where(
                    Organization.id.in_({p.organization_id for p in projects})
                )
            ).tuples().all()
        )
        requirement_counts = dict(
            db.execute(
                select(Requirement.project_id, func.count(Requirement.id))
                .where(Requirement.project_id.in_({p.id for p in projects}), Requirement.is_archived.is_(False))
                .group_by(Requirement.project_id)
            ).tuples().all()
        )

        # Hierarchical projects: parent_project_name/children are populated only
        # from projects in `accessible_ids` — the caller's own accessible set,
        # already computed above — so a hidden parent/child never surfaces even
        # from a project the caller *can* see (visibility-boundary rule, see
        # docs/decisions.md), **or** from a project in an organisation the
        # caller is `org_admin` of — added as a narrow, explicit OR-condition
        # here (not a change to what `_accessible_project_ids` itself returns)
        # so an org admin sees the true hierarchy of any project in their own
        # organisation regardless of their own role on the parent/child, per
        # the "Project hierarchy on Project Overview" entry in
        # docs/decisions.md. Safe to key off each row's own `organization_id`
        # for both its parent and its children: `parent_project_id` is
        # validated same-organisation at write time (`create_project`/
        # `update_project`, "must be a project in this organisation"), so a
        # project's parent/children always share its own organisation.
        # `admin_org_ids` is computed once per distinct organisation actually
        # present in `projects`, not per row.
        admin_org_ids = {
            oid for oid in {p.organization_id for p in projects} if is_org_admin(db, current_user.id, oid)
        }
        visible_parent_ids = {p.parent_project_id for p in projects if p.parent_project_id is not None} & accessible_ids
        visible_parent_ids |= {
            p.parent_project_id
            for p in projects
            if p.parent_project_id is not None and p.organization_id in admin_org_ids
        }
        parent_names = (
            dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(visible_parent_ids))).tuples().all())
            if visible_parent_ids
            else {}
        )
        children_by_parent: dict[UUID, list[ProjectAncestorOut]] = {}
        project_ids = {p.id for p in projects}
        if project_ids:
            for child_id, child_parent_id, child_name in db.execute(
                select(Project.id, Project.parent_project_id, Project.name).where(
                    Project.parent_project_id.in_(project_ids),
                    or_(Project.id.in_(accessible_ids), Project.organization_id.in_(admin_org_ids)),
                )
            ).all():
                children_by_parent.setdefault(child_parent_id, []).append(
                    ProjectAncestorOut(id=child_id, name=child_name)
                )

        # One query for every listed project's current stage, not one per row
        # (2026-10-04 profiling: this endpoint was the hottest in the e2e suite).
        current_stages = {
            stage.project_id: stage
            for stage in db.scalars(
                select(ProjectStage).where(ProjectStage.project_id.in_(project_ids), ProjectStage.is_current.is_(True))
            ).all()
        } if project_ids else {}
        phases = phase_index(db, {s.phase_id for s in current_stages.values()})

        # Bulk-loads each listed project's role inputs into the request memo,
        # so the per-row `get_effective_project_roles` below doesn't query.
        prefetch_project_roles(db, current_user.id, project_ids)

        out = []
        for p in projects:
            stage = current_stages.get(p.id)
            phase = phases.get(stage.phase_id) if stage else None
            if stage_phase_kind is not None and (phase is None or phase.kind != stage_phase_kind):
                continue
            roles = sorted(get_effective_project_roles(db, current_user.id, p.id), key=lambda r: r.value)
            if role is not None and role not in roles:
                continue
            parent_visible = p.parent_project_id is not None and p.parent_project_id in parent_names
            out.append(
                ProjectListItemOut(
                    id=p.id, organization_id=p.organization_id, name=p.name, code=p.code, summary=p.summary,
                    report_name=p.report_name, created_at=p.created_at, updated_at=p.updated_at,
                    is_archived=p.is_archived, is_template=p.is_template,
                    allow_member_change_requests=p.allow_member_change_requests,
                    require_change_request_for_approved_links=p.require_change_request_for_approved_links,
                    exempt_from_org_link_lock=p.exempt_from_org_link_lock, allow_ai_approvals=p.allow_ai_approvals,
                    visibility=p.visibility,
                    terminology=p.terminology, status_id=p.status_id,
                    current_stage_name=stage.name if stage else None,
                    current_stage_phase_name=phase.name if phase else None,
                    current_stage_phase_kind=phase.kind if phase else None,
                    my_roles=list(roles),
                    is_favorite=p.id in favorite_ids,
                    organization_name=org_names.get(p.organization_id, ""),
                    requirement_count=requirement_counts.get(p.id, 0),
                    parent_project_id=p.parent_project_id if parent_visible else None,
                    parent_project_name=(
                        parent_names.get(p.parent_project_id) if parent_visible and p.parent_project_id else None
                    ),
                    role_inheritance_mode=p.role_inheritance_mode,
                    role_inheritance_filter_role=p.role_inheritance_filter_role,
                    can_be_parent=p.can_be_parent,
                    children=children_by_parent.get(p.id, []),
                )
            )
        if favorite_only:
            out = [item for item in out if item.is_favorite]
        out.sort(key=lambda item: (not item.is_favorite, item.name.lower()))

        response.headers["X-Total-Count"] = str(len(out))
        if limit is not None:
            out = out[offset:offset + limit]
        return out


@router.put("/{project_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def set_favorite_project(
    project_id: UUID,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Marks a project as a favourite for the current user (U-U-03)."""
    existing = db.scalar(
        select(FavoriteProject).where(FavoriteProject.user_id == current_user.id, FavoriteProject.project_id == project_id)
    )
    if existing is None:
        db.add(FavoriteProject(user_id=current_user.id, project_id=project_id))
        db.commit()


@router.delete("/{project_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def unset_favorite_project(
    project_id: UUID,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Removes a project from the current user's favourites (U-U-03)."""
    existing = db.scalar(
        select(FavoriteProject).where(FavoriteProject.user_id == current_user.id, FavoriteProject.project_id == project_id)
    )
    if existing is not None:
        db.delete(existing)
        db.commit()


@router.get("/{project_id}/my-roles", response_model=ProjectMyRolesOut)
def get_my_project_roles(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
):
    """Returns the caller's effective roles on this one project, sorted — for
    pages that hide actions the viewer can't take. Replaces reading
    `my_roles` out of the whole `GET /projects` list, which resolved roles
    for every accessible project (the e2e suite's hottest backend call,
    2026-10-04) and missed archived projects entirely. Same gate as
    `get_project`: an org admin with no project role gets `[]`.
    """
    roles = sorted(get_effective_project_roles(db, current_user.id, project_id), key=lambda r: r.value)
    return ProjectMyRolesOut(roles=roles)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db)
):
    """Returns a single project.

    Gated by `require_project_view_or_manage`, not `require_project_view`
    — an org admin of the project's organisation can already unilaterally
    change every field this returns via `PATCH` (`require_project_manage`
    has the same `can_manage_project_settings`/`is_org_admin` bypass), so
    blocking them from *reading* it first was a real, pre-existing
    inconsistency, not a deliberate narrower boundary: it silently forced
    a "manage settings you can't see" experience and, concretely, made
    `_project_out_with_redacted_parent`'s own manager/org-admin exemption
    (below) unreachable for an org admin who holds no independent role on
    `project_id` itself. Confirmed via `require_project_view_or_manage`'s
    own precedent (`list_project_groups` already uses it for the same
    "structure, not content" reasoning) and via a full grep of this
    endpoint's existing test coverage before switching it — see
    docs/decisions.md's "Project hierarchy on Project Overview" entry.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return _project_out_with_redacted_parent(db, current_user, project)


def _existing_project(db: Session, project_id: UUID) -> Project:
    """The project, or 404 (the view gate has already shown it exists; this narrows the type for the scope helpers)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _files_page(
    db: Session, response: Response, project_id: UUID, project_scope: ProjectScope, user: User,
    filters: FileFilters, limit: int | None, offset: int,
) -> list[ProjectFileOut]:
    """One page of the project's files (plus the related projects' in scope), with `X-Total-Count` set.

    Same-target-scoped resolution, not "has access somewhere": each project's rows come from joins that filter
    directly on that project's own id (`services.project_files`), so a file belonging to a different project, even
    one the caller can also view, can never appear. `project_scope` adds the related projects the caller can open
    (each row labelled `from_project_*`, see `services.project_scope`).
    """
    out = project_scope.collect(
        db, _existing_project(db, project_id), user.id, "requirement", lambda pid: project_file_rows(db, pid, filters),
        # A file may hang from several records, so a row is identified by its origin as well.
        id_of=row_identity,
    )
    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out


@router.get("/{project_id}/files", response_model=list[ProjectFileOut])
def list_project_files(
    project_id: UUID,
    response: Response,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Lists every file reachable from this project: direct requirement attachments (C-M-02, including linked
    organisation shared resources, which `RequirementFile` covers), requirement action attachments, files attached
    to a comment on one of the project's own requirements, and the pictures in the project's report image library.
    Fills the gap `ProjectMetricsOut.file_count` only anticipated as a metric (U-P-05's "number of files in project,
    if files are implemented") without ever listing them: `FileAsset` joins a project through each of the
    context-specific link tables (and, for a library picture, its own `project_id`).

    Each row carries the context needed to make sense of a flat, project-wide list (which requirement/action/comment
    it came from, uploader, upload time), see `ProjectFileOut`. Comments on a *change request's* discussion thread
    are deliberately excluded, matching `ProjectMetricsOut.file_count`'s existing scope (requirement-attached
    content only).

    `limit`/`offset` (U-P-06): same optional pagination and `X-Total-Count` header convention as
    `list_requirements`/`list_projects`. This unfiltered read is kept for callers with no filters; the page uses
    `POST .../files/search`, which can carry the file name text out of the URL.
    """
    return _files_page(db, response, project_id, project_scope, current_user, FileFilters(), limit, offset)


@router.post("/{project_id}/files/search", response_model=list[ProjectFileOut])
def search_project_files(
    project_id: UUID,
    body: ProjectFileSearchIn,
    response: Response,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """The Files page's list with its filters: file name, source, file type, uploader and upload window.

    A POST so the file name typed into the search is in the body, never in a URL the access log records; it is a
    read, changes nothing and writes no audit event. The text is used only as a bound pattern and is never logged
    or traced. Access, project scope, ordering, pagination and `X-Total-Count` are exactly those of
    `GET .../files`, applied after the filters, so the count matches what the filters leave.
    """
    filters = FileFilters(
        search=body.search, sources=frozenset(body.sources), kind=body.kind, uploaded_by=body.uploaded_by,
        uploaded_from=body.uploaded_from, uploaded_before=body.uploaded_before,
    )
    return _files_page(db, response, project_id, project_scope, current_user, filters, limit, offset)


@router.get("/{project_id}/files/uploaders", response_model=list[ProjectFileUploaderOut])
def list_project_file_uploaders(
    project_id: UUID,
    project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """The people who uploaded a file in this project (and the related projects in scope): the choices of the Files
    page's "Uploaded by" filter. Each person once, sorted by name."""

    def rows_for(pid: UUID) -> list[ProjectFileUploaderOut]:
        return [ProjectFileUploaderOut(id=uid, display_name=name) for uid, name in project_uploaders(db, pid)]

    people = project_scope.collect(db, _existing_project(db, project_id), current_user.id, "requirement", rows_for)
    return sorted(people, key=lambda p: p.display_name.lower())


@router.get("/{project_id}/export")
def export_project(project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Exports this project's full structure and history as a self-
    describing zip bundle (see `services.project_export`'s module
    docstring) — directly re-importable via `POST /projects/import`, into
    this organisation or a different one, to create a brand-new project.

    Same authorization as the other structural-admin endpoints
    (`require_project_manage`): project managers, project administrators,
    or organisation admins of this project's organisation.
    """
    # Read-only: each person or group named on many records is looked up once, not once per record.
    with memoize_module_state(), memoize_user_lookups():
        bundle = build_project_bundle(db, project, current_user)
    return StreamingResponse(
        iter_bundle_file(bundle), media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_safe(project.name, fallback="project")}-export.zip"',
            "Content-Length": str(bundle_size(bundle)),
        },
    )


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: UUID, payload: ProjectUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Updates project settings: name/summary, the member change-request
    toggle (C-U-13), the template flag (C-E-05), visibility, status, and
    hierarchical-projects settings (parent, forward RBAC inheritance mode).

    Parent/inheritance validation order (see docs/decisions.md's
    "Hierarchical projects" entry):
      1. Attaching to a new/different parent requires the caller to manage
         *both* this project and the target parent (decision 12) — same-org
         too — and the target parent must have `can_be_parent=True` (a
         project isn't eligible to be a parent until its own manager opts
         in; see `Project.can_be_parent`'s docstring).
      2. Detaching (clearing `parent_project_id` to null) is instead gated
         by `Project.parent_required` (decision 11): rejected unless it's
         `False` or the current actor holds `ORG_ADMIN`/`PROJECT_CREATOR`
         in this project's organisation.
      3. Cycle prevention (attach/reparent only).
      4. The `role_inheritance_mode`/`role_inheritance_filter_role`
         MIRROR_ROLE invariant, enforced against the fully-merged proposed
         state.
      5. C-U-08: if the change would leave zero effective managers
         (`get_effective_project_managers` with the proposed values),
         reject — inside the same row lock as the write, to close the
         TOCTOU window a separate check-then-write would leave open.
    """
    if payload.name is not None:
        project.name = payload.name
    if payload.code is not None:
        new_code = change_project_code(db, project, payload.code)
        if new_code != project.code:
            log_event(
                db, entity_type="project", entity_id=project.id, action="code_changed", actor_id=current_user.id,
                organization_id=project.organization_id, project_id=project.id,
                detail={"from": project.code, "to": new_code},
            )
            project.code = new_code
    if payload.summary is not None:
        project.summary = payload.summary
    if "report_name" in payload.model_fields_set and payload.report_name != project.report_name:
        log_event(
            db, entity_type="project", entity_id=project.id, action="report_name_changed", actor_id=current_user.id,
            organization_id=project.organization_id, project_id=project.id,
            detail={"from": project.report_name, "to": payload.report_name},
        )
        project.report_name = payload.report_name
    if payload.allow_member_change_requests is not None:
        project.allow_member_change_requests = payload.allow_member_change_requests
    if payload.require_change_request_for_approved_links is not None:
        project.require_change_request_for_approved_links = payload.require_change_request_for_approved_links
    if payload.exempt_from_org_link_lock is not None:
        project.exempt_from_org_link_lock = payload.exempt_from_org_link_lock
    if payload.allow_ai_approvals is not None:
        # AI approval via MCP (docs/decisions.md) — project half of the
        # two-level opt-in gate; see Project.allow_ai_approvals's docstring.
        # The frontend requires an explicit acknowledgment dialog before
        # ever sending `allow_ai_approvals=true`, same as the org-level
        # counterpart in update_advanced_settings.
        project.allow_ai_approvals = payload.allow_ai_approvals
    ensure_may_publish_template(
        db, current_user, project.organization_id,
        is_template=project.is_template if payload.is_template is None else payload.is_template,
        visibility=project.visibility if payload.visibility is None else payload.visibility,
        already_published=project.is_template and project.visibility == ProjectVisibility.ORG_WIDE,
    )
    if payload.is_template is not None:
        project.is_template = payload.is_template
    if payload.can_be_parent is not None:
        project.can_be_parent = payload.can_be_parent
    if payload.visibility is not None:
        project.visibility = payload.visibility
    if payload.status_id is not None:
        new_status = db.get(ProjectStatusDefinition, payload.status_id)
        if new_status is None or new_status.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "status_id must be a project status defined in this project's organisation.")
        project.status_id = payload.status_id

    parent_changing = "parent_project_id" in payload.model_fields_set and payload.parent_project_id != project.parent_project_id
    new_parent_id = payload.parent_project_id if "parent_project_id" in payload.model_fields_set else project.parent_project_id
    new_mode = payload.role_inheritance_mode if payload.role_inheritance_mode is not None else project.role_inheritance_mode
    new_filter_role = (
        payload.role_inheritance_filter_role if payload.role_inheritance_filter_role is not None
        else project.role_inheritance_filter_role
    )
    if new_mode != ProjectRoleInheritanceMode.MIRROR_ROLE:
        new_filter_role = None
    elif new_filter_role not in {ProjectRole.STAKEHOLDER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.PROJECT_MANAGER}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "role_inheritance_filter_role must be one of stakeholder, project_administrator, project_manager "
            "when role_inheritance_mode is mirror_role.",
        )
    inheritance_settings_changing = (
        new_mode != project.role_inheritance_mode or new_filter_role != project.role_inheritance_filter_role
    )

    if parent_changing:
        lock_project_for_update(db, project_id)
        if new_parent_id is not None:
            # Attach/reparent: both sides must be managed by the caller.
            target_parent = db.get(Project, new_parent_id)
            if target_parent is None or target_parent.organization_id != project.organization_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "parent_project_id must be a project in this organisation.")
            if not can_manage_project_settings(db, current_user, target_parent):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You must manage the parent project to attach this project to it.")
            if not target_parent.can_be_parent:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "This project has not been made eligible to be a parent — enable "
                    "\"Allow this project to be a parent\" on it first.",
                )
            if would_create_project_cycle(db, project_id, new_parent_id):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "This would create a cycle in the project hierarchy.")
        else:
            # Detach: gated by parent_required, not by managing the old parent.
            if project.parent_required:
                org_roles = get_effective_org_roles(db, current_user.id, project.organization_id)
                if not org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR}:
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        "This project was created without organisation-level project-creation rights and must "
                        "remain nested under a parent; only an organisation admin or project creator can make "
                        "it standalone.",
                    )

    mode_changing_from_manager_contributing = (
        project.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ALL
        or (
            project.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ROLE
            and project.role_inheritance_filter_role == ProjectRole.PROJECT_MANAGER
        )
    )
    new_mode_manager_contributing = (
        new_mode == ProjectRoleInheritanceMode.MIRROR_ALL
        or (new_mode == ProjectRoleInheritanceMode.MIRROR_ROLE and new_filter_role == ProjectRole.PROJECT_MANAGER)
    )
    if mode_changing_from_manager_contributing and (not new_mode_manager_contributing or parent_changing):
        if not parent_changing:
            # Already locked above when parent_changing is True.
            lock_project_for_update(db, project_id)
        proposed_managers = get_effective_project_managers(
            db, project_id,
            mode_override=new_mode, filter_role_override_set=True, filter_role_override=new_filter_role,
            parent_override_set=True, parent_override=new_parent_id,
        )
        if not proposed_managers:
            parent_name = None
            if project.parent_project_id is not None:
                parent = db.get(Project, project.parent_project_id)
                parent_name = parent.name if parent is not None else None
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"This project's only manager is inherited from '{parent_name}'; assign a direct project manager "
                "before disabling inheritance or changing its parent." if parent_name
                else "This project's only manager is inherited from its parent; assign a direct project manager "
                "before disabling inheritance or changing its parent.",
            )

    if parent_changing:
        project.parent_project_id = new_parent_id
    if inheritance_settings_changing:
        project.role_inheritance_mode = new_mode
        project.role_inheritance_filter_role = new_filter_role

    log_event(db, entity_type="project", entity_id=project_id, action="settings_updated",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
              detail={"visibility": payload.visibility.value} if payload.visibility is not None else None)
    if parent_changing or inheritance_settings_changing:
        log_event(
            db, entity_type="project", entity_id=project_id, action="parented", actor_id=current_user.id,
            project_id=project_id, organization_id=project.organization_id,
            detail={
                "parent_project_id": str(new_parent_id) if new_parent_id else None,
                "role_inheritance_mode": new_mode.value,
                "role_inheritance_filter_role": new_filter_role.value if new_filter_role else None,
            },
        )
    db.commit()
    db.refresh(project)
    return _project_out_with_redacted_parent(db, current_user, project)


@router.put("/{project_id}/terminology", response_model=ProjectOut)
def update_terminology(
    project_id: UUID, payload: TerminologyUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets per-project terminology overrides (C-C-03), e.g. {"stage": "Horizon"}."""
    project.terminology = payload.terminology
    log_event(db, entity_type="project", entity_id=project_id, action="terminology_updated",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id)
    db.commit()
    db.refresh(project)
    return _project_out_with_redacted_parent(db, current_user, project)


@router.get("/{project_id}/changes", response_model=list[ChangeEntryOut])
def get_project_changes_endpoint(
    project_id: UUID,
    response: Response,
    since: datetime | None = None,
    until: datetime | None = None,
    include_comments: bool = False,
    entity_type: str | None = None,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Project changes-over-time view (C-A-10): a unified timeline of
    requirement/change-request/audit events, with an optional time range
    and entity-type filter. Discussion comments are excluded unless
    `include_comments=true`.

    `limit`/`offset` (U-P-06) are optional, same contract as
    `list_requirements`: omitting both returns the full timeline unchanged
    from before pagination existed. When `limit` is given, the total match
    count (before slicing) is returned in the `X-Total-Count` response
    header. Slicing happens here rather than in `get_project_changes`
    itself, since that function has two other, unpaginated callers
    (`requirements.py`/`change_requests.py`'s per-entity activity panels)
    that need its complete merged-and-sorted result to filter down
    themselves.
    """
    entries = get_project_changes(
        db, project_id, since=since, until=until, include_comments=include_comments, entity_type=entity_type,
    )
    response.headers["X-Total-Count"] = str(len(entries))
    if limit is not None:
        entries = entries[offset:offset + limit]
    return entries


@router.get("/{project_id}/metrics", response_model=ProjectMetricsOut)
def get_project_metrics(
    project_id: UUID, project_scope: ProjectScope = Depends(),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Project overview dashboard metrics (U-P-05).

    `project_scope` sums the counts over the related projects the caller can open
    (`services.project_scope`); `scope_project_count` says how many projects that was. The stage
    progress stays this project's own: stages and baselines belong to one project.
    """
    per_project = project_scope.collect(
        db, project_or_404(db, project_id), current_user.id, "requirement", lambda pid: [project_counts(db, pid)],
    )
    own = next(c for c in per_project if c.id == project_id)
    requirement_count = sum(c.requirements for c in per_project)
    completed = sum(c.completed for c in per_project)
    percent = (completed / requirement_count * 100.0) if requirement_count else 0.0
    proposed = sum(c.proposed for c in per_project)
    approved = sum(c.approved for c in per_project)
    rejected = sum(c.rejected for c in per_project)
    file_count = sum(c.files for c in per_project)
    requirements_by_status: dict[str, int] = {}
    for c in per_project:
        for key, value in c.by_status.items():
            requirements_by_status[key] = requirements_by_status.get(key, 0) + value
    own_requirement_count = own.requirements
    # Read-only: each module tier is read once per organisation or project, not once per record type.
    with memoize_module_state():
        record_counts = count_records_by_type(db, current_user, project_or_404(db, project_id), project_scope)

    stage_progress = [
        StageProgressOut(
            stage_id=row.stage_id, name=row.name, phase_name=row.phase_name, phase_kind=row.phase_kind,
            requirement_count=row.requirement_count, completed_percent=row.completed_percent,
        )
        for row in project_stage_progress(db, project_id, own_requirement_count)
    ]

    return ProjectMetricsOut(
        requirement_count=requirement_count,
        requirement_completed_percent=round(percent, 1),
        change_requests_proposed=proposed,
        change_requests_approved=approved,
        change_requests_rejected=rejected,
        file_count=file_count,
        requirements_by_status=requirements_by_status,
        stage_progress=stage_progress,
        scope_project_count=len(per_project),
        records_by_type=[RecordTypeCountOut(type=c.type, label=c.label, count=c.count) for c in record_counts],
        record_total=sum(c.count for c in record_counts),
    )
