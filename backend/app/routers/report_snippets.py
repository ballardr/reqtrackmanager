"""
Module: routers.report_snippets

Author-saved report snippets at the two tiers (`services.report_snippet_store`, `services.report_snippet_scope`):

- Organisation: `/api/v1/orgs/{organization_id}/report-snippets` (list, check a selection, save, rename, delete, copy).
- Project: `/api/v1/projects/{project_id}/report-snippets`, the same, plus `PUT .../{id}/visibility` to hide or show an
  inherited snippet and `POST .../restore` to show every hidden one. A copy can go to the project or up to the organisation.

Inserting a snippet is in `routers.report_layouts` (`GET .../snippets`, `POST .../snippets/{key}/apply`): saved snippets
are listed there beside the built-in set.

Access: the layout-management permissions (`manage_org_report_layouts`, `manage_project_report_layouts`; groups count and
a server administrator holds no bypass, because a snippet is customer content). Copying up also needs the organisation
permission. A snippet of another organisation, or one the project does not reach, is a 404; an inherited one is changed
where it is owned (403). The blocks and their text are never logged or audited.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_snippet import SavedReportSnippet
from app.models.user import User
from app.routers.report_layouts import manage_org_layouts, manage_project_layouts
from app.schemas.report_snippet_saved import (
    ReportSnippetCheck,
    ReportSnippetCheckOut,
    ReportSnippetCopy,
    ReportSnippetRestore,
    ReportSnippetRestoreOut,
    ReportSnippetSave,
    ReportSnippetUpdate,
    ReportSnippetVisibilitySet,
    SavedReportSnippetDetailOut,
    SavedReportSnippetOut,
)
from app.services import report_snippet_scope, report_snippet_store
from app.services.rbac import MANAGE_ORG_REPORT_LAYOUTS, get_effective_permissions, permission_satisfied
from app.services.report_layout_tree import TreeError
from app.services.report_snippet_scope import Origin, ScopedSnippet
from app.services.report_snippets import snippet_key

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-snippets", tags=["report-snippets"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-snippets", tags=["report-snippets"])


def _count_blocks(nodes: object) -> int:
    """How many blocks `nodes` holds, counting those inside containers."""
    if not isinstance(nodes, list):
        return 0
    return sum(1 + _count_blocks(n.get("children")) + _count_blocks(n.get("else_children")) for n in nodes if isinstance(n, dict))


def _names(root: dict, key: str) -> list[str]:
    return [str(item.get("name")) for item in root.get(key) or [] if isinstance(item, dict) and item.get("name")]


def _out(row: SavedReportSnippet, origin: Origin, *, hidden: bool = False, editable: bool = True) -> SavedReportSnippetOut:
    """A saved snippet as one scope sees it."""
    return SavedReportSnippetOut(
        id=row.id, key=snippet_key(row.id), organization_id=row.organization_id, project_id=row.project_id, name=row.name,
        description=row.description, category=row.category, family=row.family, origin=origin, hidden=hidden, editable=editable,
        blocks=_count_blocks(row.blocks), page_styles=_names(row.root, "page_styles"), variables=_names(row.root, "variables"),
        updated_at=row.updated_at,
    )


def _detail(row: SavedReportSnippet, origin: Origin, *, hidden: bool = False, editable: bool = True) -> SavedReportSnippetDetailOut:
    """A saved snippet with its fragment."""
    return SavedReportSnippetDetailOut(**_out(row, origin, hidden=hidden, editable=editable).model_dump(), nodes=row.blocks, root=row.root)


def _scoped_out(scoped: ScopedSnippet) -> SavedReportSnippetOut:
    return _out(scoped.snippet, scoped.origin, hidden=scoped.hidden, editable=scoped.origin == "project")


def _errors(errors: list[TreeError]) -> list[dict[str, str]]:
    return [{"path": e.path, "message": e.message} for e in errors]


def _refused(exc: Exception) -> HTTPException:
    """Maps a service refusal to the response the author should see."""
    if isinstance(exc, report_snippet_store.SnippetNameTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, report_snippet_store.SnippetSaveError):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"message": "The snippet cannot be saved.", "errors": _errors(exc.errors)},
        )
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


def _family(tree: dict) -> str:
    family = tree.get("family")
    if family not in ("document", "table"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The layout's family must be document or table.")
    return str(family)


def _check(
    db: Session, body: ReportSnippetCheck, organization_id: UUID, project_id: UUID | None,
) -> tuple[ReportSnippetCheckOut, report_snippet_store.Fragment | None]:
    """What saving the selection would store at the tier (nothing is stored)."""
    family = _family(body.tree)
    try:
        fragment = report_snippet_store.fragment_from_selection(
            body.tree, body.selection.container, body.selection.start, body.selection.count,
        )
    except report_snippet_store.SnippetSaveError as exc:
        return ReportSnippetCheckOut(ok=False, errors=_errors(exc.errors)), None
    errors = report_snippet_store.validate_fragment(db, organization_id, project_id, family, fragment.blocks, fragment.root)
    return ReportSnippetCheckOut(
        ok=not errors, errors=_errors(errors), blocks=_count_blocks(fragment.blocks),
        page_styles=_names(fragment.root, "page_styles"), variables=_names(fragment.root, "variables"),
    ), fragment


def _save(
    db: Session, user: User, body: ReportSnippetSave, organization_id: UUID, project_id: UUID | None,
) -> SavedReportSnippetOut:
    """Saves the selection at the tier; commits.

    Raises:
        HTTPException: 422 a selection or detail that cannot be stored; 409 the owner already has that name.
    """
    family = _family(body.tree)
    try:
        fragment = report_snippet_store.fragment_from_selection(
            body.tree, body.selection.container, body.selection.start, body.selection.count,
        )
        row = report_snippet_store.create_snippet(
            db, organization_id=organization_id, project_id=project_id, name=body.name, description=body.description,
            category=body.category, family=family, blocks=fragment.blocks, root=fragment.root, actor_id=user.id,
        )
    except (report_snippet_store.SnippetSaveError, report_snippet_store.SnippetNameTakenError) as exc:
        db.rollback()
        raise _refused(exc) from exc
    db.commit()
    return _out(row, "project" if project_id else "organization")


def _update(db: Session, user: User, row: SavedReportSnippet, body: ReportSnippetUpdate) -> SavedReportSnippet:
    """Changes the details and, when a tree is sent, replaces the blocks with all of that tree's; commits.

    Raises:
        HTTPException: 422 a detail or blocks that cannot be stored, or a tree of the other family; 409 a taken name.
    """
    try:
        fragment = None
        if body.tree is not None:
            if _family(body.tree) != row.family:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The blocks must be of the snippet's own kind (document or table).")
            nodes = body.tree.get("nodes")
            fragment = report_snippet_store.fragment_from_selection(
                body.tree, "nodes", 0, len(nodes) if isinstance(nodes, list) else 0,
            )
        report_snippet_store.update_snippet(
            db, row, name=body.name, description=body.description, category=body.category, actor_id=user.id, fragment=fragment,
        )
    except (report_snippet_store.SnippetSaveError, report_snippet_store.SnippetNameTakenError) as exc:
        db.rollback()
        raise _refused(exc) from exc
    db.commit()
    return row


# ---- organisation ---------------------------------------------------------------------------------------------


def _get_owned(db: Session, snippet_id: UUID, *, organization_id: UUID, project_id: UUID | None) -> SavedReportSnippet:
    """The snippet when this exact scope owns it, else 404."""
    row = db.get(SavedReportSnippet, snippet_id)
    if row is None or row.organization_id != organization_id or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snippet not found.")
    return row


@org_router.get("", response_model=list[SavedReportSnippetOut])
def list_org_saved_snippets(
    organization_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> list[SavedReportSnippetOut]:
    """The organisation's saved snippets, by name."""
    return [_out(row, "organization") for row in report_snippet_scope.list_org_snippets(db, organization_id)]


@org_router.get("/{snippet_id}", response_model=SavedReportSnippetDetailOut)
def get_org_snippet(
    organization_id: UUID, snippet_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> SavedReportSnippetDetailOut:
    """One of the organisation's saved snippets with its blocks."""
    return _detail(_get_owned(db, snippet_id, organization_id=organization_id, project_id=None), "organization")


@org_router.post("/check", response_model=ReportSnippetCheckOut)
def check_org_snippet(
    organization_id: UUID, body: ReportSnippetCheck, current_user: User = Depends(manage_org_layouts),
    db: Session = Depends(get_db),
) -> ReportSnippetCheckOut:
    """What saving a selection at organisation level would store (its page styles and variables), or why it cannot; stores nothing."""
    return _check(db, body, organization_id, None)[0]


@org_router.post("", response_model=SavedReportSnippetOut, status_code=status.HTTP_201_CREATED)
def save_org_snippet(
    organization_id: UUID, body: ReportSnippetSave, current_user: User = Depends(manage_org_layouts),
    db: Session = Depends(get_db),
) -> SavedReportSnippetOut:
    """Saves a selection of a draft as an organisation snippet. A project picture is refused (organisation layouts cannot use it)."""
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return _save(db, current_user, body, organization_id, None)


@org_router.patch("/{snippet_id}", response_model=SavedReportSnippetOut)
def update_org_snippet(
    organization_id: UUID, snippet_id: UUID, body: ReportSnippetUpdate, current_user: User = Depends(manage_org_layouts),
    db: Session = Depends(get_db),
) -> SavedReportSnippetOut:
    """Renames or re-describes the snippet, and replaces its blocks when a tree is sent."""
    row = _get_owned(db, snippet_id, organization_id=organization_id, project_id=None)
    return _out(_update(db, current_user, row, body), "organization")


@org_router.delete("/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_snippet(
    organization_id: UUID, snippet_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes the snippet; every project that hid it forgets the tombstone. Layouts built from it are unchanged."""
    row = _get_owned(db, snippet_id, organization_id=organization_id, project_id=None)
    report_snippet_store.delete_snippet(db, row, actor_id=current_user.id)
    db.commit()


@org_router.post("/{snippet_id}/copy", response_model=SavedReportSnippetOut, status_code=status.HTTP_201_CREATED)
def copy_org_snippet(
    organization_id: UUID, snippet_id: UUID, body: ReportSnippetCopy | None = None,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> SavedReportSnippetOut:
    """Copies an organisation snippet to a new one of its own in the organisation (a basis for a variation)."""
    row = _get_owned(db, snippet_id, organization_id=organization_id, project_id=None)
    return _copy(db, current_user, row, organization_id=organization_id, project_id=None, name=body.name if body else None)


def _copy(
    db: Session, user: User, source: SavedReportSnippet, *, organization_id: UUID, project_id: UUID | None, name: str | None,
) -> SavedReportSnippetOut:
    try:
        row = report_snippet_store.copy_snippet(
            db, source, organization_id=organization_id, project_id=project_id, name=name, actor_id=user.id,
        )
    except (report_snippet_store.SnippetSaveError, report_snippet_store.SnippetNameTakenError) as exc:
        db.rollback()
        raise _refused(exc) from exc
    db.commit()
    return _out(row, "project" if project_id else "organization")


# ---- project --------------------------------------------------------------------------------------------------


def _project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _reachable(db: Session, project: Project, snippet_id: UUID) -> ScopedSnippet:
    """The snippet as the project sees it, else 404 (another owner's, or shadowed by a nearer one)."""
    scoped = report_snippet_scope.reachable_snippet(db, project, snippet_id)
    if scoped is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snippet not found.")
    return scoped


def _own(db: Session, project: Project, snippet_id: UUID) -> SavedReportSnippet:
    """The project's own snippet; 403 for an inherited one (it is changed where it is owned), 404 otherwise."""
    scoped = _reachable(db, project, snippet_id)
    if scoped.origin != "project":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This snippet is inherited; change it where it is owned.")
    return scoped.snippet


@project_router.get("", response_model=list[SavedReportSnippetOut])
def list_project_saved_snippets(
    project_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> list[SavedReportSnippetOut]:
    """The saved snippets the project can reach: its own, its ancestors' and the organisation's, hidden ones flagged."""
    return [_scoped_out(s) for s in report_snippet_scope.resolve_project_snippets(db, _project_or_404(db, project_id))]


@project_router.get("/{snippet_id}", response_model=SavedReportSnippetDetailOut)
def get_project_snippet(
    project_id: UUID, snippet_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> SavedReportSnippetDetailOut:
    """A saved snippet the project can reach, with its blocks (an inherited one is read-only here)."""
    scoped = _reachable(db, _project_or_404(db, project_id), snippet_id)
    return _detail(scoped.snippet, scoped.origin, hidden=scoped.hidden, editable=scoped.origin == "project")


@project_router.post("/check", response_model=ReportSnippetCheckOut)
def check_project_snippet(
    project_id: UUID, body: ReportSnippetCheck, current_user: User = Depends(manage_project_layouts),
    db: Session = Depends(get_db),
) -> ReportSnippetCheckOut:
    """What saving a selection at project level would store, or why it cannot; stores nothing."""
    project = _project_or_404(db, project_id)
    return _check(db, body, project.organization_id, project.id)[0]


@project_router.post("/check-organization", response_model=ReportSnippetCheckOut)
def check_project_snippet_for_organization(
    project_id: UUID, body: ReportSnippetCheck, current_user: User = Depends(manage_project_layouts),
    db: Session = Depends(get_db),
) -> ReportSnippetCheckOut:
    """What saving a selection of a project draft at organisation level would store, or why it cannot (a project picture
    blocks it, and is named); stores nothing."""
    project = _project_or_404(db, project_id)
    return _check(db, body, project.organization_id, None)[0]


@project_router.post("", response_model=SavedReportSnippetOut, status_code=status.HTTP_201_CREATED)
def save_project_snippet(
    project_id: UUID, body: ReportSnippetSave, current_user: User = Depends(manage_project_layouts),
    db: Session = Depends(get_db),
) -> SavedReportSnippetOut:
    """Saves a selection of a draft as a snippet owned by the project."""
    project = _project_or_404(db, project_id)
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "The project is archived.")
    return _save(db, current_user, body, project.organization_id, project.id)


@project_router.post("/organization", response_model=SavedReportSnippetOut, status_code=status.HTTP_201_CREATED)
def save_project_snippet_to_organization(
    project_id: UUID, body: ReportSnippetSave, current_user: User = Depends(manage_project_layouts),
    db: Session = Depends(get_db),
) -> SavedReportSnippetOut:
    """Saves a selection of a project draft as an organisation snippet (needs the organisation permission).

    Raises:
        HTTPException: 403 without the organisation permission; 422 a project picture (it is named).
    """
    project = _project_or_404(db, project_id)
    if not permission_satisfied(
        get_effective_permissions(db, current_user.id, organization_id=project.organization_id), MANAGE_ORG_REPORT_LAYOUTS,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions in the organisation.")
    return _save(db, current_user, body, project.organization_id, None)


@project_router.post("/restore", response_model=ReportSnippetRestoreOut)
def restore_hidden_snippets(
    project_id: UUID, body: ReportSnippetRestore | None = None,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportSnippetRestoreOut:
    """Shows hidden inherited snippets again: the named ones, or all of them when no ids are given."""
    project = _project_or_404(db, project_id)
    ids = set(body.snippet_ids) if body is not None and body.snippet_ids is not None else None
    restored = report_snippet_scope.restore_snippets(db, project, ids, actor_id=current_user.id)
    db.commit()
    return ReportSnippetRestoreOut(restored=sorted(restored, key=str))


@project_router.patch("/{snippet_id}", response_model=SavedReportSnippetOut)
def update_project_snippet(
    project_id: UUID, snippet_id: UUID, body: ReportSnippetUpdate, current_user: User = Depends(manage_project_layouts),
    db: Session = Depends(get_db),
) -> SavedReportSnippetOut:
    """Renames or re-describes the project's own snippet, and replaces its blocks when a tree is sent."""
    row = _own(db, _project_or_404(db, project_id), snippet_id)
    return _out(_update(db, current_user, row, body), "project")


@project_router.delete("/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_snippet(
    project_id: UUID, snippet_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes the project's own snippet. An inherited one is hidden instead (`PUT .../{id}/visibility`)."""
    row = _own(db, _project_or_404(db, project_id), snippet_id)
    report_snippet_store.delete_snippet(db, row, actor_id=current_user.id)
    db.commit()


@project_router.put("/{snippet_id}/visibility", response_model=SavedReportSnippetOut)
def set_project_snippet_visibility(
    project_id: UUID, snippet_id: UUID, body: ReportSnippetVisibilitySet,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> SavedReportSnippetOut:
    """Hides or shows an inherited snippet in this project.

    Raises:
        HTTPException: 404 the snippet is not one the project inherits (its own snippets are deleted instead).
    """
    project = _project_or_404(db, project_id)
    try:
        if body.hidden:
            report_snippet_scope.hide_snippet(db, project, snippet_id, actor_id=current_user.id)
        else:
            _reachable(db, project, snippet_id)
            report_snippet_scope.restore_snippets(db, project, {snippet_id}, actor_id=current_user.id)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snippet not found.") from exc
    db.commit()
    return _scoped_out(_reachable(db, project, snippet_id))


@project_router.post("/{snippet_id}/copy", response_model=SavedReportSnippetOut, status_code=status.HTTP_201_CREATED)
def copy_project_snippet(
    project_id: UUID, snippet_id: UUID, body: ReportSnippetCopy | None = None,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> SavedReportSnippetOut:
    """Copies a snippet the project can reach into the project, or up to the organisation (`target: organization`).

    Raises:
        HTTPException: 403 a copy up without the organisation permission; 409 an archived project or a name the
            destination owns; 422 a project picture that blocks a copy up (it is named).
    """
    project = _project_or_404(db, project_id)
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "The project is archived.")
    target = body.target if body else "project"
    if target == "organization" and not permission_satisfied(
        get_effective_permissions(db, current_user.id, organization_id=project.organization_id), MANAGE_ORG_REPORT_LAYOUTS,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions in the organisation.")
    source = _reachable(db, project, snippet_id).snippet
    return _copy(
        db, current_user, source, organization_id=project.organization_id,
        project_id=None if target == "organization" else project.id, name=body.name if body else None,
    )


__all__ = ["org_router", "project_router"]
