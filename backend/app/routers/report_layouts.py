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

`GET .../blocks` lists the block types the visual designer can add with the form each needs
(`services.report_layout_block_schema`), and `POST .../validate` checks a draft tree and answers every problem with its path;
neither stores anything and the tree is never logged.

`GET .../snippets` lists the report snippets the scope can insert and `POST .../snippets/{key}/apply` returns the draft tree with one
inserted (`services.report_snippets`); neither stores anything, both need the manage permission, and the tree and parameter
values are never logged.

`GET .../widgets` lists the report components a `widget` block can embed (`services.report_widgets`), narrowed to the
modules the organisation (or project) can use, for the designer's widget picker.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_layout import ReportLayout, ReportLayoutVersion
from app.models.user import User
from app.routers.custom_reports import guard_run
from app.schemas.report_layout import (
    ReportBlockCatalogueOut,
    ReportBlockContainerOut,
    ReportBlockFieldOut,
    ReportBlockOut,
    ReportBlockProvidesOut,
    ReportFieldCatalogueOut,
    ReportFieldOut,
    ReportFieldTypeOut,
    ReportLayoutCreate,
    ReportLayoutDetailOut,
    ReportLayoutDraftVariablesOut,
    ReportLayoutOut,
    ReportLayoutPreviewOut,
    ReportLayoutPreviewRequest,
    ReportLayoutPreviewSheetOut,
    ReportLayoutRestore,
    ReportLayoutRestoreOut,
    ReportLayoutSave,
    ReportLayoutStartersOut,
    ReportLayoutTextError,
    ReportLayoutTextFormat,
    ReportLayoutTextOut,
    ReportLayoutTextParse,
    ReportLayoutTextParseOut,
    ReportLayoutTreeErrorOut,
    ReportLayoutUpdate,
    ReportLayoutValidateOut,
    ReportLayoutValidateRequest,
    ReportLayoutVariablesRequest,
    ReportLayoutVersionOut,
    ReportLayoutVersionSummaryOut,
    ReportLayoutVisibilitySet,
    ReportVariableOut,
    ReportWidgetOut,
)
from app.schemas.report_snippet import (
    ReportSnippetApply,
    ReportSnippetApplyOut,
    ReportSnippetChoiceOut,
    ReportSnippetErrorOut,
    ReportSnippetOut,
    ReportSnippetParameterOut,
)
from app.services import (
    custom_report_run,
    report_images,
    report_layout_designer,
    report_layout_scope,
    report_layout_text,
    report_layouts,
    report_snippets,
    report_starters,
)
from app.services.client_date import effective_today
from app.services.rbac import (
    MANAGE_ORG_REPORT_LAYOUTS,
    MANAGE_PROJECT_REPORT_LAYOUTS,
    get_effective_permissions,
    permission_satisfied,
    require_org_role,
    require_permission,
    require_project_view_or_manage,
)
from app.services.report_framework import param_out
from app.services.report_layout_block_schema import BlockField
from app.services.report_layout_scope import Origin, ScopedLayout
from app.services.report_layout_tree import InvalidLayoutError
from app.services.report_variables import describe_variables
from app.services.report_widgets import WidgetInfo, widgets_for_organization, widgets_for_project

manage_org_layouts = require_permission(MANAGE_ORG_REPORT_LAYOUTS, server_admin_bypass=False)
manage_project_layouts = require_permission(MANAGE_PROJECT_REPORT_LAYOUTS, server_admin_bypass=False)
"""Layouts are customer content: a server administrator holds no data access inside an organisation, so neither gate bypasses for them."""

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-layouts", tags=["report-layouts"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-layouts", tags=["report-layouts"])


def _summary(layout: ReportLayout, origin: Origin, *, hidden: bool = False, editable: bool = True) -> ReportLayoutOut:
    """A layout's summary as one scope sees it."""
    return ReportLayoutOut(
        id=layout.id, organization_id=layout.organization_id, project_id=layout.project_id, name=layout.name,
        description=layout.description, folder=layout.folder, report_template_id=layout.report_template_id,
        family=layout.family, current_version=layout.current_version,
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
        block_lines=result.block_lines,
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


def _widgets_out(widgets: list[WidgetInfo]) -> list[ReportWidgetOut]:
    """The widget list as the designer shows it, in registry order."""
    return [
        ReportWidgetOut(
            key=w.key, title=w.title, description=w.part.description, kind=w.part.kind, report_title=w.report_title,
            module_key=w.module_key, module_name=w.module_name, params=[param_out(p) for p in w.params],
        )
        for w in widgets
    ]


def _catalogue_out(catalogue: report_layout_designer.FieldCatalogue) -> ReportFieldCatalogueOut:
    """The field catalogue as the designer's picker reads it."""
    return ReportFieldCatalogueOut(
        types=[
            ReportFieldTypeOut(
                type=t.type, label=t.label,
                fields=[
                    ReportFieldOut(key=f.key, label=f.label, kind=f.kind, reserved=f.reserved, choices=list(f.choices), math=f.math)
                    for f in t.fields
                ],
            )
            for t in catalogue.types
        ],
        placeholders=list(catalogue.placeholders), group_fields=catalogue.group_fields, schema_version=catalogue.schema_version,
    )


def _block_field_out(f: BlockField) -> ReportBlockFieldOut:
    """One block or layout field as the designer reads it."""
    return ReportBlockFieldOut(
        key=f.key, label=f.label, kind=f.kind, required=f.required, help=f.help, max_length=f.max_length,
        minimum=f.minimum, maximum=f.maximum, default=f.default, choices=list(f.choices), features=list(f.features),
        depends_on=f.depends_on, families=list(f.families),
    )


def _blocks_out(catalogue: report_layout_designer.BlockCatalogue) -> ReportBlockCatalogueOut:
    """The block catalogue as the designer reads it."""
    return ReportBlockCatalogueOut(
        blocks=[
            ReportBlockOut(
                type=b.key, label=b.schema.label, description=b.schema.description, families=list(b.families),
                fields=[_block_field_out(f) for f in b.schema.fields],
                containers=[ReportBlockContainerOut(key=c.key, label=c.label) for c in b.schema.containers],
                provides=ReportBlockProvidesOut(key=b.schema.provides.key, kind=b.schema.provides.kind, default=b.schema.provides.default)
                if b.schema.provides else None,
                template=b.schema.template, described=b.described,
            )
            for b in catalogue.blocks
        ],
        layout_fields=[_block_field_out(f) for f in catalogue.layout_fields],
        image_column_fields=[_block_field_out(f) for f in catalogue.image_column_fields],
        field_kinds=list(catalogue.field_kinds), operators={k: list(v) for k, v in catalogue.operators.items()},
        valueless_operators=list(catalogue.valueless_operators), list_operators=list(catalogue.list_operators),
        schema_version=catalogue.schema_version,
    )


def _validate_tree(
    body: ReportLayoutValidateRequest, db: Session, organization_id: UUID, project_id: UUID | None,
) -> ReportLayoutValidateOut:
    """Checks a draft tree; every problem comes back with its path.

    Besides the tree's own rules, an image block must name a picture in a library the layout's owner may use.
    """
    analysis = report_layout_designer.check_tree(body.tree)
    errors = list(analysis.errors)
    if analysis.ok:
        errors += report_images.image_problems(db, organization_id, project_id, body.tree)
    return ReportLayoutValidateOut(
        ok=not errors, errors=[ReportLayoutTreeErrorOut(path=e.path, message=e.message) for e in errors],
        node_count=analysis.node_count,
    )


def _snippets_out(visible: list[report_snippets.VisibleSnippet]) -> list[ReportSnippetOut]:
    """The snippets a scope can use, with each parameter's choices."""
    return [
        ReportSnippetOut(
            key=v.snippet.key, name=v.snippet.name, description=v.snippet.description, category=v.snippet.category,
            family=v.snippet.family, formats=list(v.snippet.formats), module_key=v.module_key, blocks=list(v.snippet.blocks),
            saved_id=v.saved.id if v.saved else None, origin=v.saved.origin if v.saved else None,
            parameters=[
                ReportSnippetParameterOut(
                    key=p.parameter.key, label=p.parameter.label, kind=p.parameter.kind, help=p.parameter.help,
                    required=p.parameter.default is None, default=p.parameter.default,
                    max_length=p.parameter.max_length if p.parameter.kind == "text" else None,
                    choices=[ReportSnippetChoiceOut(value=c.value, label=c.label) for c in p.choices],
                )
                for p in v.parameters
            ],
        )
        for v in visible
    ]


def _apply_snippet(
    db: Session, key: str, body: ReportSnippetApply, organization_id: UUID, project: Project | None,
) -> ReportSnippetApplyOut:
    """Builds the tree a snippet gives in a draft (200 either way; a refusal lists why); stores and logs nothing.

    Raises:
        HTTPException: 404 when no snippet of that key is available to the scope.
    """
    visible = next((v for v in report_snippets.visible_snippets(db, organization_id, project) if v.snippet.key == key), None)
    if visible is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snippet not found.")
    outcome = report_snippets.apply_snippet(
        db, visible, body.tree, body.parameters, organization_id=organization_id,
        project_id=project.id if project is not None else None, list_path=body.target.container, index=body.target.index,
    )
    return ReportSnippetApplyOut(
        ok=outcome.tree is not None, tree=outcome.tree, changes=outcome.changes,
        errors=[ReportSnippetErrorOut(path=e.path, message=e.message) for e in outcome.errors],
        inserted_at=outcome.inserted_at, count=outcome.count, problems_elsewhere=outcome.problems_elsewhere,
    )


def _draft(body: ReportLayoutPreviewRequest) -> tuple[dict[str, Any] | None, ReportLayoutPreviewOut | None]:
    """The tree to preview: the given one, or the text's. A draft with problems answers `(None, <not ok outcome>)`.

    Raises:
        HTTPException: 422 a given tree that is not valid.
    """
    if body.tree is not None:
        return body.tree, None
    assert body.text is not None
    parsed = _parse_text(ReportLayoutTextParse(text=body.text))
    if not parsed.ok or parsed.tree is None:
        return None, ReportLayoutPreviewOut(ok=False, errors=parsed.errors)
    return parsed.tree, None


def _preview_out(preview: report_layout_designer.Preview) -> ReportLayoutPreviewOut:
    """A finished preview as the response."""
    return ReportLayoutPreviewOut(
        ok=True, family=preview.family, html=preview.html,
        sheets=[
            ReportLayoutPreviewSheetOut(name=s.name, columns=s.columns, rows=s.rows, total_rows=s.total_rows)
            for s in preview.sheets
        ],
        warnings=preview.warnings, records_read=preview.records_read, duration_ms=preview.duration_ms, projects=preview.projects,
    )


def _draft_variables(
    db: Session, body: ReportLayoutVariablesRequest, project_ids: list[UUID],
) -> ReportLayoutDraftVariablesOut:
    """The run form of a draft over the given projects (its variables, defaults and current options)."""
    tree, failed = _draft(body)  # type: ignore[arg-type]  # only .text and .tree are read
    if failed is not None or tree is None:
        assert failed is not None
        return ReportLayoutDraftVariablesOut(ok=False, errors=failed.errors)
    errors = report_layout_designer.validation_errors(tree)
    if errors:
        raise _bad_request(InvalidLayoutError(errors))
    declared = describe_variables(db, tree.get("variables"), project_ids, today=effective_today())
    return ReportLayoutDraftVariablesOut(ok=True, variables=[ReportVariableOut.model_validate(v) for v in declared])


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
            folder=body.folder, report_template_id=body.report_template_id, family=body.family, tree=body.tree,
            actor_id=user.id, comment=body.comment,
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
        report_layouts.update_details(
            db, layout, name=body.name, description=body.description, folder=body.folder, actor_id=user.id,
            report_template_id=body.report_template_id if "report_template_id" in body.model_fields_set else report_layouts.UNCHANGED,
        )
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


@org_router.post("/starters", response_model=ReportLayoutStartersOut)
def add_org_starter_layouts(
    organization_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportLayoutStartersOut:
    """Adds the starter layouts (Business Requirements Document, Engineering Specification, Review Package) the
    organisation does not have yet. A starter whose name is already used is left as it is, so this is safe to repeat.

    Raises:
        HTTPException: 404 the organisation does not exist.
    """
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    added = report_starters.add_starter_layouts(db, organization_id, actor_id=current_user.id)
    db.commit()
    return ReportLayoutStartersOut(added=added)


@org_router.post("/text/parse", response_model=ReportLayoutTextParseOut)
def parse_org_layout_text(body: ReportLayoutTextParse, current_user: User = Depends(manage_org_layouts)) -> ReportLayoutTextParseOut:
    """Reads a layout's text view into a tree, with positioned errors; stores nothing."""
    return _parse_text(body)


@org_router.post("/text/format", response_model=ReportLayoutTextOut)
def format_org_layout_text(body: ReportLayoutTextFormat, current_user: User = Depends(manage_org_layouts)) -> ReportLayoutTextOut:
    """Writes a valid tree as its text view; stores nothing."""
    return _format_text(body)


@org_router.get("/blocks", response_model=ReportBlockCatalogueOut)
def list_org_blocks(current_user: User = Depends(manage_org_layouts)) -> ReportBlockCatalogueOut:
    """The block types the visual designer can add, with the form each needs; the same for every organisation."""
    return _blocks_out(report_layout_designer.block_catalogue())


@org_router.post("/validate", response_model=ReportLayoutValidateOut)
def validate_org_layout_tree(
    organization_id: UUID, body: ReportLayoutValidateRequest, current_user: User = Depends(manage_org_layouts),
    db: Session = Depends(get_db),
) -> ReportLayoutValidateOut:
    """Checks a draft tree and answers every problem with its path (200 either way); stores and logs nothing."""
    return _validate_tree(body, db, organization_id, None)


@org_router.get("/fields", response_model=ReportFieldCatalogueOut)
def list_org_fields(
    organization_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportFieldCatalogueOut:
    """The record types and fields an organisation layout may name: those of modules the organisation has enabled."""
    return _catalogue_out(report_layout_designer.catalogue_for_organization(db, organization_id))


@org_router.post("/preview", response_model=ReportLayoutPreviewOut)
def preview_org_layout(
    organization_id: UUID, body: ReportLayoutPreviewRequest,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportLayoutPreviewOut:
    """Evaluates an unsaved draft as an organisation-wide run would (once per project the caller can read, merged).

    Stores, audits and logs nothing. A draft with text problems answers 200 with `ok` false and the positioned errors.

    Raises:
        HTTPException: 404 the organisation, or no project to run for; 422 an invalid tree or oversized selection;
            413/408 a run over its limits.
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    tree, failed = _draft(body)
    if failed is not None or tree is None:
        assert failed is not None
        return failed
    try:
        preview = guard_run(lambda: report_layout_designer.preview_for_organization(
            db, current_user, organization, tree=tree, name=body.name, project_ids=body.project_ids,
            variables=body.variables,
        ))
    except InvalidLayoutError as exc:
        raise _bad_request(exc) from exc
    return _preview_out(preview)


@org_router.post("/variables", response_model=ReportLayoutDraftVariablesOut)
def draft_org_variables(
    organization_id: UUID, body: ReportLayoutVariablesRequest,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportLayoutDraftVariablesOut:
    """The run form of an unsaved organisation draft: its variables, defaults and options across the projects the caller can read."""
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    readable = custom_report_run.readable_projects(
        db, current_user, organization=organization, root_project=None, include_children=False,
    )
    scope = [p.id for p in readable]
    if body.project_ids is not None:
        scope = [pid for pid in scope if pid in set(body.project_ids)]
    return _draft_variables(db, body, scope[: custom_report_run.MAX_FANOUT_PROJECTS])


@org_router.get("/widgets", response_model=list[ReportWidgetOut])
def list_org_widgets(
    organization_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> list[ReportWidgetOut]:
    """The report components an organisation layout can embed: those of modules the organisation is entitled to and has enabled."""
    return _widgets_out(widgets_for_organization(db, organization_id))


@org_router.get("/snippets", response_model=list[ReportSnippetOut])
def list_org_snippets(
    organization_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> list[ReportSnippetOut]:
    """The report snippets an organisation layout can insert: the platform's, and those of modules the organisation has on."""
    return _snippets_out(report_snippets.visible_snippets(db, organization_id, None))


@org_router.post("/snippets/{key}/apply", response_model=ReportSnippetApplyOut)
def apply_org_snippet(
    organization_id: UUID, key: str, body: ReportSnippetApply, current_user: User = Depends(manage_org_layouts),
    db: Session = Depends(get_db),
) -> ReportSnippetApplyOut:
    """Inserts a snippet into a draft tree and returns the new tree (200 either way); stores and logs nothing."""
    return _apply_snippet(db, key, body, organization_id, None)


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


@project_router.get("/blocks", response_model=ReportBlockCatalogueOut)
def list_project_blocks(project_id: UUID, current_user: User = Depends(manage_project_layouts)) -> ReportBlockCatalogueOut:
    """The block types the visual designer can add, with the form each needs; the same for every project."""
    return _blocks_out(report_layout_designer.block_catalogue())


@project_router.post("/validate", response_model=ReportLayoutValidateOut)
def validate_project_layout_tree(
    project_id: UUID, body: ReportLayoutValidateRequest, current_user: User = Depends(manage_project_layouts),
    db: Session = Depends(get_db),
) -> ReportLayoutValidateOut:
    """Checks a draft tree and answers every problem with its path (200 either way); stores and logs nothing."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return _validate_tree(body, db, project.organization_id, project_id)


@project_router.get("/fields", response_model=ReportFieldCatalogueOut)
def list_project_fields(
    project_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportFieldCatalogueOut:
    """The record types and fields a project layout may name: those of modules enabled for the project."""
    return _catalogue_out(report_layout_designer.catalogue_for_project(db, _project_or_404(db, project_id)))


@project_router.post("/preview", response_model=ReportLayoutPreviewOut)
def preview_project_layout(
    project_id: UUID, body: ReportLayoutPreviewRequest,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutPreviewOut:
    """Evaluates an unsaved draft for this project as a run would, with the caller's own read access.

    Stores, audits and logs nothing. A draft with text problems answers 200 with `ok` false and the positioned errors.

    Raises:
        HTTPException: 404 the project; 422 an invalid tree; 413/408 a run over its limits.
    """
    project = _project_or_404(db, project_id)
    tree, failed = _draft(body)
    if failed is not None or tree is None:
        assert failed is not None
        return failed
    try:
        preview = guard_run(lambda: report_layout_designer.preview_for_project(
            db, current_user, project, tree=tree, name=body.name, include_children=body.include_children,
            variables=body.variables,
        ))
    except InvalidLayoutError as exc:
        raise _bad_request(exc) from exc
    return _preview_out(preview)


@project_router.post("/variables", response_model=ReportLayoutDraftVariablesOut)
def draft_project_variables(
    project_id: UUID, body: ReportLayoutVariablesRequest,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportLayoutDraftVariablesOut:
    """The run form of an unsaved draft for this project: its variables, defaults and current options. Stores nothing."""
    project = _project_or_404(db, project_id)
    return _draft_variables(db, body, [project.id])


@project_router.get("/widgets", response_model=list[ReportWidgetOut])
def list_project_widgets(
    project_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> list[ReportWidgetOut]:
    """The report components a project layout can embed: those of modules enabled for the project."""
    return _widgets_out(widgets_for_project(db, _project_or_404(db, project_id)))


@project_router.get("/snippets", response_model=list[ReportSnippetOut])
def list_project_snippets(
    project_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> list[ReportSnippetOut]:
    """The report snippets a project layout can insert: the platform's, and those of modules enabled for the project."""
    project = _project_or_404(db, project_id)
    return _snippets_out(report_snippets.visible_snippets(db, project.organization_id, project))


@project_router.post("/snippets/{key}/apply", response_model=ReportSnippetApplyOut)
def apply_project_snippet(
    project_id: UUID, key: str, body: ReportSnippetApply, current_user: User = Depends(manage_project_layouts),
    db: Session = Depends(get_db),
) -> ReportSnippetApplyOut:
    """Inserts a snippet into a draft tree and returns the new tree (200 either way); stores and logs nothing."""
    project = _project_or_404(db, project_id)
    return _apply_snippet(db, key, body, project.organization_id, project)


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
