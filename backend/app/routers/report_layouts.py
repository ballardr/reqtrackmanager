"""
Module: routers.report_layouts

Custom report layouts at the two tiers (`services.report_layouts`, `services.report_layout_scope`):

- Organisation: `/api/v1/orgs/{organization_id}/report-layouts` (list, create, read, versions, save a
  version, rename, delete).
- Project: `/api/v1/projects/{project_id}/report-layouts`, the same, plus `PUT .../{id}/visibility` to hide
  or show an inherited layout and `POST .../restore` to show every hidden one.

Access: listing needs membership (an organisation role, or the project's view); everything that reads a
tree or writes needs the matching manage permission (`manage_org_report_layouts`,
`manage_project_report_layouts`; `services.rbac`). A project's list is its *effective* set (own, ancestors',
organisation's, de-duplicated by name); an inherited layout can be read by a project manager but only
changed where it is owned. Running a layout is a later endpoint and needs neither permission.

`POST .../text/parse` and `.../text/format` convert between a tree and its text view
(`services.report_layout_text`) for the designer; they store nothing, need the manage permission and never
log the text.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import ReportLayout, ReportLayoutVersion
from app.models.user import User
from app.schemas.report_layout import (
    ReportLayoutCreate,
    ReportLayoutDetailOut,
    ReportLayoutOut,
    ReportLayoutRestore,
    ReportLayoutRestoreOut,
    ReportLayoutSave,
    ReportLayoutTextError,
    ReportLayoutTextFormat,
    ReportLayoutTextOut,
    ReportLayoutTextParse,
    ReportLayoutTextParseOut,
    ReportLayoutUpdate,
    ReportLayoutVersionOut,
    ReportLayoutVersionSummaryOut,
    ReportLayoutVisibilitySet,
)
from app.services import report_layout_scope, report_layout_text, report_layouts
from app.services.rbac import (
    MANAGE_ORG_REPORT_LAYOUTS,
    MANAGE_PROJECT_REPORT_LAYOUTS,
    get_effective_permissions,
    permission_satisfied,
    require_org_role,
    require_permission,
    require_project_view_or_manage,
)
from app.services.report_layout_scope import Origin, ScopedLayout
from app.services.report_layout_tree import InvalidLayoutError

manage_org_layouts = require_permission(MANAGE_ORG_REPORT_LAYOUTS, server_admin_bypass=False)
manage_project_layouts = require_permission(MANAGE_PROJECT_REPORT_LAYOUTS, server_admin_bypass=False)
"""Layouts are customer content: a server administrator holds no data access inside an organisation, so neither gate bypasses for them."""

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-layouts", tags=["report-layouts"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-layouts", tags=["report-layouts"])


def _summary(layout: ReportLayout, origin: Origin, *, hidden: bool = False, editable: bool = True) -> ReportLayoutOut:
    """A layout's summary as one scope sees it."""
    return ReportLayoutOut(
        id=layout.id, organization_id=layout.organization_id, project_id=layout.project_id, name=layout.name,
        description=layout.description, family=layout.family, current_version=layout.current_version,
        origin=origin, hidden=hidden, editable=editable, updated_at=layout.updated_at,
    )


def _version_out(version: ReportLayoutVersion) -> ReportLayoutVersionOut:
    return ReportLayoutVersionOut(
        version=version.version, schema_version=version.schema_version, tree=version.tree, tree_hash=version.tree_hash,
        comment=version.comment, created_by=version.created_by, created_at=version.created_at,
    )


def _detail(db: Session, layout: ReportLayout, origin: Origin, *, hidden: bool = False, editable: bool = True) -> ReportLayoutDetailOut:
    current = report_layouts.get_version(db, layout.id, layout.current_version)
    assert current is not None  # a layout always has its current version
    return ReportLayoutDetailOut(**_summary(layout, origin, hidden=hidden, editable=editable).model_dump(), current=_version_out(current))


def _bad_request(exc: Exception) -> HTTPException:
    """Maps a service error to the response the author should see."""
    if isinstance(exc, InvalidLayoutError):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "The layout is not valid.", "errors": [{"path": e.path, "message": e.message} for e in exc.errors]},
        )
    if isinstance(exc, report_layouts.LayoutNameTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, report_layouts.LayoutConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, {"message": str(exc), "current_version": exc.current_version})
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


def _parse_text(body: ReportLayoutTextParse) -> ReportLayoutTextParseOut:
    """Reads the text view; the text is never logged or audited (it is customer content)."""
    result = report_layout_text.parse_text(body.text)
    return ReportLayoutTextParseOut(
        ok=result.ok, tree=result.tree, errors=[ReportLayoutTextError(line=e.line, column=e.column, message=e.message) for e in result.errors],
    )


def _format_text(body: ReportLayoutTextFormat) -> ReportLayoutTextOut:
    """Writes a tree as text.

    Raises:
        HTTPException: 422 with the positioned errors when the tree is not valid.
    """
    try:
        return ReportLayoutTextOut(text=report_layout_text.format_tree(body.tree))
    except InvalidLayoutError as exc:
        raise _bad_request(exc) from exc


def _get_owned(db: Session, layout_id: UUID, *, organization_id: UUID, project_id: UUID | None) -> ReportLayout:
    """The layout when this exact scope owns it, else 404."""
    layout = db.get(ReportLayout, layout_id)
    if layout is None or layout.organization_id != organization_id or layout.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    return layout


def _create(db: Session, user: User, body: ReportLayoutCreate, *, organization_id: UUID, project_id: UUID | None) -> ReportLayout:
    try:
        saved = report_layouts.create_layout(
            db, organization_id=organization_id, project_id=project_id, name=body.name, description=body.description,
            family=body.family, tree=body.tree, actor_id=user.id, comment=body.comment,
        )
    except (ValueError, InvalidLayoutError) as exc:
        db.rollback()
        raise _bad_request(exc) from exc
    db.commit()
    return saved.layout


def _save(db: Session, user: User, layout: ReportLayout, body: ReportLayoutSave) -> ReportLayout:
    try:
        report_layouts.save_version(db, layout.id, body.tree, base_version=body.base_version, actor_id=user.id, comment=body.comment)
    except (ValueError, InvalidLayoutError) as exc:
        db.rollback()
        raise _bad_request(exc) from exc
    db.commit()
    db.refresh(layout)
    return layout


def _update(db: Session, user: User, layout: ReportLayout, body: ReportLayoutUpdate) -> ReportLayout:
    try:
        report_layouts.update_details(db, layout, name=body.name, description=body.description, actor_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise _bad_request(exc) from exc
    db.commit()
    db.refresh(layout)
    return layout


def _versions(db: Session, layout: ReportLayout) -> list[ReportLayoutVersionSummaryOut]:
    return [
        ReportLayoutVersionSummaryOut(
            version=v.version, tree_hash=v.tree_hash, comment=v.comment, created_by=v.created_by, created_at=v.created_at,
        )
        for v in report_layouts.list_versions(db, layout.id)
    ]


def _one_version(db: Session, layout: ReportLayout, number: int) -> ReportLayoutVersionOut:
    version = report_layouts.get_version(db, layout.id, number)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found.")
    return _version_out(version)


# ---- organisation ----------------------------------------------------------------------------------------------


@org_router.get("", response_model=list[ReportLayoutOut])
def list_org_layouts(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
) -> list[ReportLayoutOut]:
    """The organisation's own layouts (summaries, no trees)."""
    return [_summary(layout, "organization") for layout in report_layout_scope.list_org_layouts(db, organization_id)]


@org_router.post("", response_model=ReportLayoutDetailOut, status_code=status.HTTP_201_CREATED)
def create_org_layout(
    organization_id: UUID, body: ReportLayoutCreate,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportLayoutDetailOut:
    """Creates an organisation layout and its version 1.

    Raises:
        HTTPException: 422 an invalid tree (with positioned errors) or field; 409 the name is taken.
    """
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    layout = _create(db, current_user, body, organization_id=organization_id, project_id=None)
    return _detail(db, layout, "organization")


@org_router.post("/text/parse", response_model=ReportLayoutTextParseOut)
def parse_org_layout_text(body: ReportLayoutTextParse, current_user: User = Depends(manage_org_layouts)) -> ReportLayoutTextParseOut:
    """Reads a layout's text view into a tree, with positioned errors; stores nothing."""
    return _parse_text(body)


@org_router.post("/text/format", response_model=ReportLayoutTextOut)
def format_org_layout_text(body: ReportLayoutTextFormat, current_user: User = Depends(manage_org_layouts)) -> ReportLayoutTextOut:
    """Writes a valid tree as its text view; stores nothing."""
    return _format_text(body)


@org_router.get("/{layout_id}", response_model=ReportLayoutDetailOut)
def get_org_layout(
    organization_id: UUID, layout_id: UUID,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportLayoutDetailOut:
    """An organisation layout with its current tree."""
    return _detail(db, _get_owned(db, layout_id, organization_id=organization_id, project_id=None), "organization")


@org_router.get("/{layout_id}/versions", response_model=list[ReportLayoutVersionSummaryOut])
def list_org_layout_versions(
    organization_id: UUID, layout_id: UUID,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> list[ReportLayoutVersionSummaryOut]:
    """The layout's version history, newest first."""
    return _versions(db, _get_owned(db, layout_id, organization_id=organization_id, project_id=None))


@org_router.get("/{layout_id}/versions/{version}", response_model=ReportLayoutVersionOut)
def get_org_layout_version(
    organization_id: UUID, layout_id: UUID, version: int,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportLayoutVersionOut:
    """One saved version with its tree."""
    return _one_version(db, _get_owned(db, layout_id, organization_id=organization_id, project_id=None), version)


@org_router.put("/{layout_id}/tree", response_model=ReportLayoutDetailOut)
def save_org_layout(
    organization_id: UUID, layout_id: UUID, body: ReportLayoutSave,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportLayoutDetailOut:
    """Saves a new version of the layout (nothing is stored when the tree is unchanged).

    Raises:
        HTTPException: 422 an invalid tree; 409 the layout moved on from `base_version`.
    """
    layout = _get_owned(db, layout_id, organization_id=organization_id, project_id=None)
    return _detail(db, _save(db, current_user, layout, body), "organization")


@org_router.patch("/{layout_id}", response_model=ReportLayoutOut)
def update_org_layout(
    organization_id: UUID, layout_id: UUID, body: ReportLayoutUpdate,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportLayoutOut:
    """Renames or re-describes the layout."""
    layout = _get_owned(db, layout_id, organization_id=organization_id, project_id=None)
    return _summary(_update(db, current_user, layout, body), "organization")


@org_router.delete("/{layout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_layout(
    organization_id: UUID, layout_id: UUID,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes the layout and its versions; every project that hid it forgets the tombstone."""
    layout = _get_owned(db, layout_id, organization_id=organization_id, project_id=None)
    report_layouts.delete_layout(db, layout, actor_id=current_user.id)
    db.commit()


# ---- project ---------------------------------------------------------------------------------------------------


def _project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _scoped_out(scoped: ScopedLayout) -> ReportLayoutOut:
    return _summary(scoped.layout, scoped.origin, hidden=scoped.hidden, editable=scoped.origin == "project")


def _reachable(db: Session, project: Project, layout_id: UUID) -> ScopedLayout:
    """The layout as the project sees it, else 404 (another owner's, or shadowed by a nearer one)."""
    scoped = report_layout_scope.reachable_layout(db, project, layout_id)
    if scoped is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.")
    return scoped


def _own(db: Session, project: Project, layout_id: UUID) -> ReportLayout:
    """The project's own layout; 403 for an inherited one (it is changed where it is owned), 404 otherwise."""
    scoped = _reachable(db, project, layout_id)
    if scoped.origin != "project":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This layout is inherited; change it where it is owned.")
    return scoped.layout


@project_router.get("", response_model=list[ReportLayoutOut])
def list_project_layouts(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
) -> list[ReportLayoutOut]:
    """The layouts the project can reach: its own, its ancestors' and the organisation's, with where each
    comes from. A hidden layout is listed (flagged) only for a caller who can manage the project's layouts.
    """
    project = _project_or_404(db, project_id)
    held = get_effective_permissions(db, current_user.id, project_id=project_id)
    may_manage = permission_satisfied(held, MANAGE_PROJECT_REPORT_LAYOUTS)
    return [
        _scoped_out(s) for s in report_layout_scope.resolve_project_layouts(db, project) if may_manage or not s.hidden
    ]


@project_router.post("", response_model=ReportLayoutDetailOut, status_code=status.HTTP_201_CREATED)
def create_project_layout(
    project_id: UUID, body: ReportLayoutCreate,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutDetailOut:
    """Creates a layout owned by the project (it can share a name with an inherited one and then shadows it).

    Raises:
        HTTPException: 422 an invalid tree or field; 409 the project already has a layout of that name.
    """
    project = _project_or_404(db, project_id)
    layout = _create(db, current_user, body, organization_id=project.organization_id, project_id=project.id)
    return _detail(db, layout, "project")


@project_router.post("/restore", response_model=ReportLayoutRestoreOut)
def restore_hidden_layouts(
    project_id: UUID, body: ReportLayoutRestore | None = None,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutRestoreOut:
    """Shows hidden inherited layouts again: the named ones, or all of them when no ids are given."""
    project = _project_or_404(db, project_id)
    ids = set(body.layout_ids) if body is not None and body.layout_ids is not None else None
    restored = report_layout_scope.restore_layouts(db, project, ids, actor_id=current_user.id)
    db.commit()
    return ReportLayoutRestoreOut(restored=sorted(restored, key=str))


@project_router.post("/text/parse", response_model=ReportLayoutTextParseOut)
def parse_project_layout_text(
    project_id: UUID, body: ReportLayoutTextParse, current_user: User = Depends(manage_project_layouts),
) -> ReportLayoutTextParseOut:
    """Reads a layout's text view into a tree, with positioned errors; stores nothing."""
    return _parse_text(body)


@project_router.post("/text/format", response_model=ReportLayoutTextOut)
def format_project_layout_text(
    project_id: UUID, body: ReportLayoutTextFormat, current_user: User = Depends(manage_project_layouts),
) -> ReportLayoutTextOut:
    """Writes a valid tree as its text view; stores nothing."""
    return _format_text(body)


@project_router.get("/{layout_id}", response_model=ReportLayoutDetailOut)
def get_project_layout(
    project_id: UUID, layout_id: UUID,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutDetailOut:
    """A layout the project can reach, with its current tree (an inherited one is read-only here)."""
    scoped = _reachable(db, _project_or_404(db, project_id), layout_id)
    return _detail(db, scoped.layout, scoped.origin, hidden=scoped.hidden, editable=scoped.origin == "project")


@project_router.get("/{layout_id}/versions", response_model=list[ReportLayoutVersionSummaryOut])
def list_project_layout_versions(
    project_id: UUID, layout_id: UUID,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> list[ReportLayoutVersionSummaryOut]:
    """The version history of a layout the project can reach, newest first."""
    return _versions(db, _reachable(db, _project_or_404(db, project_id), layout_id).layout)


@project_router.get("/{layout_id}/versions/{version}", response_model=ReportLayoutVersionOut)
def get_project_layout_version(
    project_id: UUID, layout_id: UUID, version: int,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutVersionOut:
    """One saved version, with its tree."""
    return _one_version(db, _reachable(db, _project_or_404(db, project_id), layout_id).layout, version)


@project_router.put("/{layout_id}/tree", response_model=ReportLayoutDetailOut)
def save_project_layout(
    project_id: UUID, layout_id: UUID, body: ReportLayoutSave,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutDetailOut:
    """Saves a new version of the project's own layout.

    Raises:
        HTTPException: 403 an inherited layout; 422 an invalid tree; 409 the layout moved on from `base_version`.
    """
    layout = _own(db, _project_or_404(db, project_id), layout_id)
    return _detail(db, _save(db, current_user, layout, body), "project")


@project_router.patch("/{layout_id}", response_model=ReportLayoutOut)
def update_project_layout(
    project_id: UUID, layout_id: UUID, body: ReportLayoutUpdate,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutOut:
    """Renames or re-describes the project's own layout."""
    layout = _own(db, _project_or_404(db, project_id), layout_id)
    return _summary(_update(db, current_user, layout, body), "project")


@project_router.delete("/{layout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_layout(
    project_id: UUID, layout_id: UUID,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes the project's own layout. An inherited one is hidden instead (`PUT .../{id}/visibility`)."""
    layout = _own(db, _project_or_404(db, project_id), layout_id)
    report_layouts.delete_layout(db, layout, actor_id=current_user.id)
    db.commit()


@project_router.put("/{layout_id}/visibility", response_model=ReportLayoutOut)
def set_project_layout_visibility(
    project_id: UUID, layout_id: UUID, body: ReportLayoutVisibilitySet,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutOut:
    """Hides or shows an inherited layout in this project.

    Raises:
        HTTPException: 404 the layout is not one the project inherits (its own layouts are deleted instead).
    """
    project = _project_or_404(db, project_id)
    try:
        if body.hidden:
            report_layout_scope.hide_layout(db, project, layout_id, actor_id=current_user.id)
        else:
            _reachable(db, project, layout_id)
            report_layout_scope.restore_layouts(db, project, {layout_id}, actor_id=current_user.id)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Layout not found.") from exc
    db.commit()
    return _scoped_out(_reachable(db, project, layout_id))


__all__ = ["org_router", "project_router"]
