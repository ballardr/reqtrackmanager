"""
Module: routers.report_packs

Report packs at the two tiers (`services.report_packs`, `services.report_pack_scope`) and running them
(`services.report_pack_run`):

- Organisation: `/api/v1/orgs/{organization_id}/report-packs` (list, create, read, versions, save a version,
  rename, delete).
- Project: `/api/v1/projects/{project_id}/report-packs`, the same, plus `PUT .../{id}/visibility` to hide or show an
  inherited pack and `POST .../restore` to show every hidden one.
- Running, at both tiers: `GET .../{id}/form` (the run form: variables with defaults and options),
  `POST .../{id}/preview` (record counts per entry, nothing stored) and `POST .../{id}/run` (the zip).

Access: listing needs membership; reading a definition or writing needs the same manage permissions as layouts
(`manage_org_report_layouts`, `manage_project_report_layouts`; a server administrator holds no bypass because packs
are customer content). Running needs only what reading the data needs: each entry is produced as the caller with the
report's own gates, so the zip never holds more than the caller could read.

Run and preview take their values in a POST body so a value never appears in a URL the front proxy logs, and values
are never logged. A pack that cannot produce any file answers 409 `nothing_to_run`; one over its size or time bound
answers 413.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.report_pack import ReportPack, ReportPackVariableSet, ReportPackVersion
from app.models.user import User
from app.routers.custom_reports import ASYNC_REQUIRED, ReportRunOut, guard_run
from app.routers.report_layouts import manage_org_layouts, manage_project_layouts
from app.schemas.report_pack import (
    ReportPackCreate,
    ReportPackDetailOut,
    ReportPackFormOut,
    ReportPackFormSetOut,
    ReportPackOut,
    ReportPackPreviewEntryOut,
    ReportPackPreviewOut,
    ReportPackRestore,
    ReportPackRestoreOut,
    ReportPackRunRequest,
    ReportPackSave,
    ReportPackSetCreate,
    ReportPackSetOut,
    ReportPackSetOverrideSave,
    ReportPackSetUpdate,
    ReportPackUpdate,
    ReportPackVersionOut,
    ReportPackVersionSummaryOut,
    ReportPackVisibilitySet,
)
from app.services import (
    custom_report_run,
    report_pack_run,
    report_pack_scope,
    report_pack_sets,
    report_packs,
    report_run_jobs,
)
from app.services.client_date import effective_today
from app.services.downloads import file_response
from app.services.rbac import (
    MANAGE_PROJECT_REPORT_LAYOUTS,
    get_effective_permissions,
    permission_satisfied,
    require_org_role,
    require_project_view,
    require_project_view_or_manage,
)
from app.services.report_document import load_report_template
from app.services.report_framework import ReportVariableOut
from app.services.report_pack_definition import InvalidPackError
from app.services.report_pack_scope import Origin, ScopedPack
from app.services.report_variables import VariableValueError, describe_variables

T = TypeVar("T")

org_router = APIRouter(prefix="/api/v1/orgs/{organization_id}/report-packs", tags=["report-packs"])
project_router = APIRouter(prefix="/api/v1/projects/{project_id}/report-packs", tags=["report-packs"])

NOTHING_TO_RUN = "nothing_to_run"


def _summary(db: Session, pack: ReportPack, origin: Origin, *, hidden: bool = False, editable: bool = True) -> ReportPackOut:
    version = report_packs.current_version(db, pack)
    return ReportPackOut(
        id=pack.id, organization_id=pack.organization_id, project_id=pack.project_id, name=pack.name,
        description=pack.description, current_version=pack.current_version, origin=origin, hidden=hidden,
        editable=editable, entries=len(version.definition.get("entries", [])), updated_at=pack.updated_at,
    )


def _version_out(version: ReportPackVersion) -> ReportPackVersionOut:
    return ReportPackVersionOut(
        version=version.version, schema_version=version.schema_version, definition=version.definition,
        definition_hash=version.definition_hash, comment=version.comment, created_by=version.created_by,
        created_at=version.created_at,
    )


def _detail(db: Session, pack: ReportPack, origin: Origin, *, hidden: bool = False, editable: bool = True) -> ReportPackDetailOut:
    return ReportPackDetailOut(
        **_summary(db, pack, origin, hidden=hidden, editable=editable).model_dump(),
        current=_version_out(report_packs.current_version(db, pack)),
    )


def _bad_request(exc: Exception) -> HTTPException:
    """Maps a service error to the response the author should see."""
    if isinstance(exc, InvalidPackError):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "The pack is not valid.", "errors": [{"path": e.path, "message": e.message} for e in exc.errors]},
        )
    if isinstance(exc, report_packs.PackNameTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, report_packs.PackConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, {"message": str(exc), "current_version": exc.current_version})
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


def _get_owned(db: Session, pack_id: UUID, *, organization_id: UUID, project_id: UUID | None) -> ReportPack:
    """The pack when this exact scope owns it, else 404."""
    pack = db.get(ReportPack, pack_id)
    if pack is None or pack.organization_id != organization_id or pack.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pack not found.")
    return pack


def _create(db: Session, user: User, body: ReportPackCreate, *, organization_id: UUID, project_id: UUID | None) -> ReportPack:
    try:
        saved = report_packs.create_pack(
            db, organization_id=organization_id, project_id=project_id, name=body.name, description=body.description,
            definition=body.definition, actor_id=user.id, comment=body.comment,
        )
    except (ValueError, InvalidPackError) as exc:
        db.rollback()
        raise _bad_request(exc) from exc
    db.commit()
    return saved.pack


def _save(db: Session, user: User, pack: ReportPack, body: ReportPackSave) -> ReportPack:
    try:
        report_packs.save_version(
            db, pack.id, body.definition, base_version=body.base_version, actor_id=user.id, comment=body.comment,
        )
    except (ValueError, InvalidPackError) as exc:
        db.rollback()
        raise _bad_request(exc) from exc
    db.commit()
    db.refresh(pack)
    return pack


def _update(db: Session, user: User, pack: ReportPack, body: ReportPackUpdate) -> ReportPack:
    try:
        report_packs.update_details(db, pack, name=body.name, description=body.description, actor_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise _bad_request(exc) from exc
    db.commit()
    db.refresh(pack)
    return pack


def _versions(db: Session, pack: ReportPack) -> list[ReportPackVersionSummaryOut]:
    return [
        ReportPackVersionSummaryOut(
            version=v.version, definition_hash=v.definition_hash, comment=v.comment, created_by=v.created_by,
            created_at=v.created_at,
        )
        for v in report_packs.list_versions(db, pack.id)
    ]


def _one_version(db: Session, pack: ReportPack, number: int) -> ReportPackVersionOut:
    version = report_packs.get_version(db, pack.id, number)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found.")
    return _version_out(version)


def _guard_pack(call: Callable[[], T], *, file_run: bool = False) -> T:
    """Runs `call`, translating the pack run's refusals (and a layout's, via `guard_run`) into responses.

    A file run over the synchronous bounds answers 409 `async_required` (the client then queues it); a preview answers 413.
    """
    try:
        return guard_run(call)
    except report_pack_run.UnknownSetError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except report_pack_run.NothingToRunError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": NOTHING_TO_RUN, "message": str(exc)}) from exc
    except report_pack_run.PackLimitError as exc:
        if file_run:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": ASYNC_REQUIRED,
                    "message": "This pack is too big to produce while you wait. Prepare it in the background and "
                    "you will be notified when it is ready.",
                },
            ) from exc
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc


def _preview_out(run: report_pack_run.PackRun) -> ReportPackPreviewOut:
    entries = [
        ReportPackPreviewEntryOut(
            position=e.index + 1, kind=e.kind, title=e.title, format=e.format, status=e.status,  # type: ignore[arg-type]
            reason=e.reason, records=e.records, warnings=e.warnings,
        )
        for e in run.entries
    ]
    return ReportPackPreviewOut(
        entries=entries, total_records=sum(e.records for e in run.included),
        not_available=sum(1 for e in run.entries if e.status == report_pack_run.STATUS_NOT_AVAILABLE),
        variable_set=run.set_name, warnings=run.warnings,
    )


def _respond(db: Session, user: User, run: report_pack_run.PackRun, body: ReportPackRunRequest) -> Response:
    """Zips the run, records its provenance and returns the download."""
    data = report_pack_run.build_zip(run)
    report_pack_run.record_pack_run(
        db, user, run, requested_project_ids=body.project_ids if run.project is None else None,
        include_children=body.include_children,
    )
    db.commit()
    return file_response(data, report_pack_run.zip_stem(run), "zip")


def _queue(
    db: Session, user: User, organization: Organization, project: Project | None, pack: ReportPack,
    version: ReportPackVersion, body: ReportPackRunRequest,
) -> ReportRunOut:
    """Queues a background pack run after checking its values and set now.

    Raises:
        HTTPException: 404 an unknown set, 422 `variable_values`, 400 a template of another organisation, 429 too many queued.
    """
    if body.report_template_id is not None and load_report_template(db, organization.id, body.report_template_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid report_template_id for this organisation.")
    _guard_pack(lambda: report_pack_run.check_request(db, pack, version, project, body.variables, body.variable_set_id))
    try:
        row = report_run_jobs.enqueue_pack(
            db, user, organization=organization, project=project, pack=pack, version=version,
            report_template_id=body.report_template_id, include_children=body.include_children,
            requested_project_ids=body.project_ids if project is None else None, variables=body.variables,
            variable_set_id=body.variable_set_id,
        )
    except report_run_jobs.TooManyActiveRunsError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    db.commit()
    return ReportRunOut.of(row)


# ---- organisation ----------------------------------------------------------------------------------------------


@org_router.get("", response_model=list[ReportPackOut])
def list_org_packs(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
) -> list[ReportPackOut]:
    """The organisation's own packs (summaries, no definitions)."""
    return [_summary(db, pack, "organization") for pack in report_pack_scope.list_org_packs(db, organization_id)]


@org_router.post("", response_model=ReportPackDetailOut, status_code=status.HTTP_201_CREATED)
def create_org_pack(
    organization_id: UUID, body: ReportPackCreate,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportPackDetailOut:
    """Creates an organisation pack and its version 1.

    Raises:
        HTTPException: 422 an invalid definition (with positioned errors) or field; 409 the name is taken.
    """
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return _detail(db, _create(db, current_user, body, organization_id=organization_id, project_id=None), "organization")


@org_router.get("/{pack_id}", response_model=ReportPackDetailOut)
def get_org_pack(
    organization_id: UUID, pack_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportPackDetailOut:
    """An organisation pack with its current definition."""
    return _detail(db, _get_owned(db, pack_id, organization_id=organization_id, project_id=None), "organization")


@org_router.get("/{pack_id}/versions", response_model=list[ReportPackVersionSummaryOut])
def list_org_pack_versions(
    organization_id: UUID, pack_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> list[ReportPackVersionSummaryOut]:
    """The pack's version history, newest first."""
    return _versions(db, _get_owned(db, pack_id, organization_id=organization_id, project_id=None))


@org_router.get("/{pack_id}/versions/{version}", response_model=ReportPackVersionOut)
def get_org_pack_version(
    organization_id: UUID, pack_id: UUID, version: int,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportPackVersionOut:
    """One saved version with its definition."""
    return _one_version(db, _get_owned(db, pack_id, organization_id=organization_id, project_id=None), version)


@org_router.put("/{pack_id}/definition", response_model=ReportPackDetailOut)
def save_org_pack(
    organization_id: UUID, pack_id: UUID, body: ReportPackSave,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportPackDetailOut:
    """Saves a new version of the pack (nothing is stored when the definition is unchanged).

    Raises:
        HTTPException: 422 an invalid definition; 409 the pack moved on from `base_version`.
    """
    pack = _get_owned(db, pack_id, organization_id=organization_id, project_id=None)
    return _detail(db, _save(db, current_user, pack, body), "organization")


@org_router.patch("/{pack_id}", response_model=ReportPackOut)
def update_org_pack(
    organization_id: UUID, pack_id: UUID, body: ReportPackUpdate,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportPackOut:
    """Renames or re-describes the pack."""
    pack = _get_owned(db, pack_id, organization_id=organization_id, project_id=None)
    return _summary(db, _update(db, current_user, pack, body), "organization")


@org_router.delete("/{pack_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_pack(
    organization_id: UUID, pack_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes the pack and its versions; every project that hid it forgets the tombstone."""
    pack = _get_owned(db, pack_id, organization_id=organization_id, project_id=None)
    report_packs.delete_pack(db, pack, actor_id=current_user.id)
    db.commit()


def _org_pack(db: Session, organization_id: UUID, pack_id: UUID) -> tuple[Organization, ReportPack, ReportPackVersion]:
    """An organisation pack for a run, else 404."""
    organization = db.get(Organization, organization_id)
    pack = db.get(ReportPack, pack_id)
    if organization is None or pack is None or pack.organization_id != organization_id or pack.project_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pack not found.")
    return organization, pack, report_packs.current_version(db, pack)


@org_router.get("/{pack_id}/form", response_model=ReportPackFormOut)
def org_pack_form(
    organization_id: UUID, pack_id: UUID,
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> ReportPackFormOut:
    """The run form of an organisation pack: its variables, defaults and options across the projects the caller can read."""
    organization, pack, version = _org_pack(db, organization_id, pack_id)
    readable = custom_report_run.readable_projects(db, current_user, organization=organization, root_project=None, include_children=False)
    return _form(db, pack, version, [p.id for p in readable][: custom_report_run.MAX_FANOUT_PROJECTS], None)


@org_router.post("/{pack_id}/preview", response_model=ReportPackPreviewOut)
def preview_org_pack(
    organization_id: UUID, pack_id: UUID, body: ReportPackRunRequest,
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> ReportPackPreviewOut:
    """What each report in the pack would include for the chosen values. Nothing is stored or produced."""
    organization, pack, version = _org_pack(db, organization_id, pack_id)
    run = _guard_pack(lambda: report_pack_run.run_organization_pack(
        db, current_user, organization, pack, version, body.variables, template_id=body.report_template_id,
        project_ids=body.project_ids, render=False, set_id=body.variable_set_id,
    ))
    return _preview_out(run)


@org_router.post("/{pack_id}/run")
def run_org_pack(
    organization_id: UUID, pack_id: UUID, body: ReportPackRunRequest,
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> Response:
    """Produces the pack for the whole organisation (each layout once per project the caller can read) as a zip.

    Raises:
        HTTPException: 404 the pack; 422 `variable_values`; 409 `nothing_to_run`; 413 over its bounds.
    """
    organization, pack, version = _org_pack(db, organization_id, pack_id)
    run = _guard_pack(lambda: report_pack_run.run_organization_pack(
        db, current_user, organization, pack, version, body.variables, template_id=body.report_template_id,
        project_ids=body.project_ids, set_id=body.variable_set_id,
    ), file_run=True)
    return _respond(db, current_user, run, body)


# ---- saved variable sets ---------------------------------------------------------------------------------------


def _set_error(exc: Exception) -> HTTPException:
    """Maps a set service error to a response."""
    if isinstance(exc, report_pack_sets.SetNameTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, VariableValueError):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "variable_values", "message": "Some values are not acceptable for this pack's variables.",
                "problems": [{"name": name, "message": message} for name, message in exc.problems],
            },
        )
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


def _set_out(
    db: Session, version: ReportPackVersion, item: report_pack_sets.EffectiveSet, project_ids: list[UUID], *,
    editable: bool, overridable: bool,
) -> ReportPackSetOut:
    return ReportPackSetOut(
        id=item.row.id, name=item.row.name, origin=item.origin,  # type: ignore[arg-type]
        project_id=item.row.project_id, base=item.base, override=item.own_override, overridden_by=item.overridden_by,
        effective=item.effective, editable=editable, overridable=overridable,
        warnings=report_pack_sets.stale_warnings(db, version, item.effective, project_ids),
    )


def _plain(row: ReportPackVariableSet) -> report_pack_sets.EffectiveSet:
    """A just-saved set as itself (no override applies to the saver's own change)."""
    values = dict(row.variable_values)
    return report_pack_sets.EffectiveSet(row, "pack" if row.project_id is None else "project", values, None, None, dict(values))


def _set_of(db: Session, pack: ReportPack, set_id: UUID) -> ReportPackVariableSet:
    row = report_pack_sets.get_set(db, pack, set_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Set not found.")
    return row


def _org_scope_ids(db: Session, user: User, organization: Organization) -> list[UUID]:
    readable = custom_report_run.readable_projects(db, user, organization=organization, root_project=None, include_children=False)
    return [p.id for p in readable][: custom_report_run.MAX_FANOUT_PROJECTS]


@org_router.get("/{pack_id}/sets", response_model=list[ReportPackSetOut])
def list_org_pack_sets(
    organization_id: UUID, pack_id: UUID, current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> list[ReportPackSetOut]:
    """The saved variable sets of an organisation pack (each project can override them for itself)."""
    pack = _get_owned(db, pack_id, organization_id=organization_id, project_id=None)
    version = report_packs.current_version(db, pack)
    organization = db.get(Organization, organization_id)
    assert organization is not None
    scope = _org_scope_ids(db, current_user, organization)
    return [
        _set_out(db, version, e, scope, editable=True, overridable=False)
        for e in report_pack_sets.effective_sets(db, pack, None)
    ]


@org_router.post("/{pack_id}/sets", response_model=ReportPackSetOut, status_code=status.HTTP_201_CREATED)
def create_org_pack_set(
    organization_id: UUID, pack_id: UUID, body: ReportPackSetCreate,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportPackSetOut:
    """Saves a variable set with an organisation pack.

    Raises:
        HTTPException: 422 a value that does not fit its variable (`variable_values`); 409 the name is taken.
    """
    pack = _get_owned(db, pack_id, organization_id=organization_id, project_id=None)
    version = report_packs.current_version(db, pack)
    try:
        row = report_pack_sets.create_set(
            db, pack, version, project_id=None, name=body.name, variable_values=body.values, actor_id=current_user.id,
        )
    except (ValueError, VariableValueError) as exc:
        db.rollback()
        raise _set_error(exc) from exc
    db.commit()
    item = _plain(row)
    return _set_out(db, version, item, [], editable=True, overridable=False)


@org_router.patch("/{pack_id}/sets/{set_id}", response_model=ReportPackSetOut)
def update_org_pack_set(
    organization_id: UUID, pack_id: UUID, set_id: UUID, body: ReportPackSetUpdate,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> ReportPackSetOut:
    """Renames an organisation pack's set and/or replaces its values (projects' overrides stay)."""
    pack = _get_owned(db, pack_id, organization_id=organization_id, project_id=None)
    version = report_packs.current_version(db, pack)
    row = _set_of(db, pack, set_id)
    try:
        report_pack_sets.update_set(
            db, pack, version, row, name=body.name, variable_values=body.values, actor_id=current_user.id,
        )
    except (ValueError, VariableValueError) as exc:
        db.rollback()
        raise _set_error(exc) from exc
    db.commit()
    item = _plain(row)
    return _set_out(db, version, item, [], editable=True, overridable=False)


@org_router.delete("/{pack_id}/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_pack_set(
    organization_id: UUID, pack_id: UUID, set_id: UUID,
    current_user: User = Depends(manage_org_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes a set and every project's override of it."""
    pack = _get_owned(db, pack_id, organization_id=organization_id, project_id=None)
    report_pack_sets.delete_set(db, pack, _set_of(db, pack, set_id), actor_id=current_user.id)
    db.commit()


@org_router.post("/{pack_id}/runs", response_model=ReportRunOut, status_code=status.HTTP_202_ACCEPTED)
def queue_org_pack(
    organization_id: UUID, pack_id: UUID, body: ReportPackRunRequest,
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
) -> ReportRunOut:
    """Queues an organisation pack to be produced in the background; the requester is notified when the zip is ready.

    The values and set are checked now and the access again when the job runs. The finished zip is listed and
    downloaded through `/api/v1/report-runs`.

    Raises:
        HTTPException: 404 the pack or set; 422 `variable_values`; 429 too many background runs already queued.
    """
    organization, pack, version = _org_pack(db, organization_id, pack_id)
    return _queue(db, current_user, organization, None, pack, version, body)


# ---- project ---------------------------------------------------------------------------------------------------


def _project_or_404(db: Session, project_id: UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _scoped_out(db: Session, scoped: ScopedPack) -> ReportPackOut:
    return _summary(db, scoped.pack, scoped.origin, hidden=scoped.hidden, editable=scoped.origin == "project")


def _reachable(db: Session, project: Project, pack_id: UUID) -> ScopedPack:
    """The pack as the project sees it, else 404 (another owner's, or shadowed by a nearer one)."""
    scoped = report_pack_scope.reachable_pack(db, project, pack_id)
    if scoped is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pack not found.")
    return scoped


def _own(db: Session, project: Project, pack_id: UUID) -> ReportPack:
    """The project's own pack; 403 for an inherited one (it is changed where it is owned), 404 otherwise."""
    scoped = _reachable(db, project, pack_id)
    if scoped.origin != "project":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This pack is inherited; change it where it is owned.")
    return scoped.pack


def _runnable(db: Session, project: Project, pack_id: UUID) -> tuple[ReportPack, ReportPackVersion]:
    """A pack the project can run (reachable and not hidden), else 404."""
    scoped = _reachable(db, project, pack_id)
    if scoped.hidden:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pack not found.")
    return scoped.pack, report_packs.current_version(db, scoped.pack)


def _form(
    db: Session, pack: ReportPack, version: ReportPackVersion, project_ids: list[UUID], project: Project | None,
) -> ReportPackFormOut:
    declared = describe_variables(db, version.definition.get("variables"), project_ids, today=effective_today())
    sets = [
        ReportPackFormSetOut(
            id=e.row.id, name=e.row.name, values=e.effective,
            warnings=report_pack_sets.stale_warnings(db, version, e.effective, project_ids),
        )
        for e in report_pack_sets.effective_sets(db, pack, project)
    ]
    return ReportPackFormOut(
        name=pack.name, description=pack.description, entries=len(version.definition.get("entries", [])),
        variables=[ReportVariableOut.model_validate(v) for v in declared], sets=sets,
    )


@project_router.get("", response_model=list[ReportPackOut])
def list_project_packs(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
) -> list[ReportPackOut]:
    """The packs the project can reach: its own, its ancestors' and the organisation's, with where each comes from.
    A hidden pack is listed (flagged) only for a caller who can manage the project's packs.
    """
    project = _project_or_404(db, project_id)
    held = get_effective_permissions(db, current_user.id, project_id=project_id)
    may_manage = permission_satisfied(held, MANAGE_PROJECT_REPORT_LAYOUTS)
    return [
        _scoped_out(db, s) for s in report_pack_scope.resolve_project_packs(db, project) if may_manage or not s.hidden
    ]


@project_router.post("", response_model=ReportPackDetailOut, status_code=status.HTTP_201_CREATED)
def create_project_pack(
    project_id: UUID, body: ReportPackCreate,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackDetailOut:
    """Creates a pack owned by the project (it can share a name with an inherited one and then shadows it).

    Raises:
        HTTPException: 422 an invalid definition or field; 409 the project already has a pack of that name.
    """
    project = _project_or_404(db, project_id)
    pack = _create(db, current_user, body, organization_id=project.organization_id, project_id=project.id)
    return _detail(db, pack, "project")


@project_router.post("/restore", response_model=ReportPackRestoreOut)
def restore_hidden_packs(
    project_id: UUID, body: ReportPackRestore | None = None,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackRestoreOut:
    """Shows hidden inherited packs again: the named ones, or all of them when no ids are given."""
    project = _project_or_404(db, project_id)
    ids = set(body.pack_ids) if body is not None and body.pack_ids is not None else None
    restored = report_pack_scope.restore_packs(db, project, ids, actor_id=current_user.id)
    db.commit()
    return ReportPackRestoreOut(restored=sorted(restored, key=str))


@project_router.get("/{pack_id}", response_model=ReportPackDetailOut)
def get_project_pack(
    project_id: UUID, pack_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackDetailOut:
    """A pack the project can reach, with its current definition (an inherited one is read-only here)."""
    scoped = _reachable(db, _project_or_404(db, project_id), pack_id)
    return _detail(db, scoped.pack, scoped.origin, hidden=scoped.hidden, editable=scoped.origin == "project")


@project_router.get("/{pack_id}/versions", response_model=list[ReportPackVersionSummaryOut])
def list_project_pack_versions(
    project_id: UUID, pack_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> list[ReportPackVersionSummaryOut]:
    """The version history of a pack the project can reach, newest first."""
    return _versions(db, _reachable(db, _project_or_404(db, project_id), pack_id).pack)


@project_router.get("/{pack_id}/versions/{version}", response_model=ReportPackVersionOut)
def get_project_pack_version(
    project_id: UUID, pack_id: UUID, version: int,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackVersionOut:
    """One saved version, with its definition."""
    return _one_version(db, _reachable(db, _project_or_404(db, project_id), pack_id).pack, version)


@project_router.put("/{pack_id}/definition", response_model=ReportPackDetailOut)
def save_project_pack(
    project_id: UUID, pack_id: UUID, body: ReportPackSave,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackDetailOut:
    """Saves a new version of the project's own pack.

    Raises:
        HTTPException: 403 an inherited pack; 422 an invalid definition; 409 the pack moved on from `base_version`.
    """
    pack = _own(db, _project_or_404(db, project_id), pack_id)
    return _detail(db, _save(db, current_user, pack, body), "project")


@project_router.patch("/{pack_id}", response_model=ReportPackOut)
def update_project_pack(
    project_id: UUID, pack_id: UUID, body: ReportPackUpdate,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackOut:
    """Renames or re-describes the project's own pack."""
    pack = _own(db, _project_or_404(db, project_id), pack_id)
    return _summary(db, _update(db, current_user, pack, body), "project")


@project_router.delete("/{pack_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_pack(
    project_id: UUID, pack_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes the project's own pack. An inherited one is hidden instead (`PUT .../{id}/visibility`)."""
    pack = _own(db, _project_or_404(db, project_id), pack_id)
    report_packs.delete_pack(db, pack, actor_id=current_user.id)
    db.commit()


@project_router.put("/{pack_id}/visibility", response_model=ReportPackOut)
def set_project_pack_visibility(
    project_id: UUID, pack_id: UUID, body: ReportPackVisibilitySet,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackOut:
    """Hides or shows an inherited pack in this project.

    Raises:
        HTTPException: 404 the pack is not one the project inherits (its own packs are deleted instead).
    """
    project = _project_or_404(db, project_id)
    try:
        if body.hidden:
            report_pack_scope.hide_pack(db, project, pack_id, actor_id=current_user.id)
        else:
            _reachable(db, project, pack_id)
            report_pack_scope.restore_packs(db, project, {pack_id}, actor_id=current_user.id)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pack not found.") from exc
    db.commit()
    return _scoped_out(db, _reachable(db, project, pack_id))


@project_router.get("/{pack_id}/form", response_model=ReportPackFormOut)
def project_pack_form(
    project_id: UUID, pack_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ReportPackFormOut:
    """The run form of a pack the project can reach: its variables, defaults and current options."""
    project = _project_or_404(db, project_id)
    pack, version = _runnable(db, project, pack_id)
    return _form(db, pack, version, [project.id], project)


@project_router.post("/{pack_id}/preview", response_model=ReportPackPreviewOut)
def preview_project_pack(
    project_id: UUID, pack_id: UUID, body: ReportPackRunRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ReportPackPreviewOut:
    """What each report in the pack would include for the chosen values. Nothing is stored or produced."""
    project = _project_or_404(db, project_id)
    pack, version = _runnable(db, project, pack_id)
    run = _guard_pack(lambda: report_pack_run.run_project_pack(
        db, current_user, project, pack, version, body.variables, template_id=body.report_template_id,
        include_children=body.include_children, render=False, set_id=body.variable_set_id,
    ))
    return _preview_out(run)


@project_router.post("/{pack_id}/runs", response_model=ReportRunOut, status_code=status.HTTP_202_ACCEPTED)
def queue_project_pack(
    project_id: UUID, pack_id: UUID, body: ReportPackRunRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> ReportRunOut:
    """Queues a pack the project can reach to be produced in the background for this project.

    Raises:
        HTTPException: 404 the project, pack or set; 422 `variable_values`; 429 too many background runs already queued.
    """
    project = _project_or_404(db, project_id)
    pack, version = _runnable(db, project, pack_id)
    organization = db.get(Organization, project.organization_id)
    assert organization is not None
    return _queue(db, current_user, organization, project, pack, version, body)


@project_router.post("/{pack_id}/run")
def run_project_pack(
    project_id: UUID, pack_id: UUID, body: ReportPackRunRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
) -> Response:
    """Produces the pack for this project as a zip: each report in its format, plus a manifest.

    Raises:
        HTTPException: 404 the project or pack is not reachable (or the project hid it); 422 `variable_values`; 409
            `nothing_to_run`; 413 over its bounds.
    """
    project = _project_or_404(db, project_id)
    pack, version = _runnable(db, project, pack_id)
    run = _guard_pack(lambda: report_pack_run.run_project_pack(
        db, current_user, project, pack, version, body.variables, template_id=body.report_template_id,
        include_children=body.include_children, set_id=body.variable_set_id,
    ), file_run=True)
    return _respond(db, current_user, run, body)


def _project_set_access(pack: ReportPack, project: Project, row: ReportPackVariableSet) -> tuple[bool, bool]:
    """`(editable, overridable)` of a set for `project`: its own pack's sets and sets it added are editable; an
    inherited pack's own sets are overridden instead."""
    own_pack = pack.project_id == project.id
    editable = (row.project_id is None and own_pack) or row.project_id == project.id
    overridable = row.project_id is None and not own_pack
    return editable, overridable


@project_router.get("/{pack_id}/sets", response_model=list[ReportPackSetOut])
def list_project_pack_sets(
    project_id: UUID, pack_id: UUID, current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> list[ReportPackSetOut]:
    """The saved sets of a pack as this project sees them: the pack's own with this project's overrides (and its
    ancestors') applied, and the sets this project or an ancestor added."""
    project = _project_or_404(db, project_id)
    scoped = _reachable(db, project, pack_id)
    version = report_packs.current_version(db, scoped.pack)
    out = []
    for item in report_pack_sets.effective_sets(db, scoped.pack, project):
        editable, overridable = _project_set_access(scoped.pack, project, item.row)
        out.append(_set_out(db, version, item, [project.id], editable=editable, overridable=overridable))
    return out


@project_router.post("/{pack_id}/sets", response_model=ReportPackSetOut, status_code=status.HTTP_201_CREATED)
def create_project_pack_set(
    project_id: UUID, pack_id: UUID, body: ReportPackSetCreate,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackSetOut:
    """Saves a set. For the project's own pack it is saved with the pack; for an inherited pack it is this project's
    own set, beside the pack's.

    Raises:
        HTTPException: 422 a value that does not fit its variable; 409 the name is already visible.
    """
    project = _project_or_404(db, project_id)
    scoped = _reachable(db, project, pack_id)
    version = report_packs.current_version(db, scoped.pack)
    owner = None if scoped.origin == "project" else project.id
    try:
        row = report_pack_sets.create_set(
            db, scoped.pack, version, project_id=owner, name=body.name, variable_values=body.values, actor_id=current_user.id,
        )
    except (ValueError, VariableValueError) as exc:
        db.rollback()
        raise _set_error(exc) from exc
    db.commit()
    item = _plain(row)
    editable, overridable = _project_set_access(scoped.pack, project, row)
    return _set_out(db, version, item, [project.id], editable=editable, overridable=overridable)


@project_router.patch("/{pack_id}/sets/{set_id}", response_model=ReportPackSetOut)
def update_project_pack_set(
    project_id: UUID, pack_id: UUID, set_id: UUID, body: ReportPackSetUpdate,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackSetOut:
    """Renames or changes a set this project owns (its own pack's, or one it added). An inherited pack's own set is overridden instead."""
    project = _project_or_404(db, project_id)
    scoped = _reachable(db, project, pack_id)
    row = _set_of(db, scoped.pack, set_id)
    editable, overridable = _project_set_access(scoped.pack, project, row)
    if not editable:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This set belongs to the pack; override its values for this project instead.")
    version = report_packs.current_version(db, scoped.pack)
    try:
        report_pack_sets.update_set(
            db, scoped.pack, version, row, name=body.name, variable_values=body.values, actor_id=current_user.id,
        )
    except (ValueError, VariableValueError) as exc:
        db.rollback()
        raise _set_error(exc) from exc
    db.commit()
    item = _plain(row)
    return _set_out(db, version, item, [project.id], editable=editable, overridable=overridable)


@project_router.delete("/{pack_id}/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_pack_set(
    project_id: UUID, pack_id: UUID, set_id: UUID,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> None:
    """Deletes a set this project owns."""
    project = _project_or_404(db, project_id)
    scoped = _reachable(db, project, pack_id)
    row = _set_of(db, scoped.pack, set_id)
    if not _project_set_access(scoped.pack, project, row)[0]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This set belongs to the pack; it is deleted where the pack is owned.")
    report_pack_sets.delete_set(db, scoped.pack, row, actor_id=current_user.id)
    db.commit()


@project_router.put("/{pack_id}/sets/{set_id}/override", response_model=ReportPackSetOut)
def put_project_pack_set_override(
    project_id: UUID, pack_id: UUID, set_id: UUID, body: ReportPackSetOverrideSave,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackSetOut:
    """Sets this project's values for the variables it changes in an inherited pack's set (an empty object resets it).

    Raises:
        HTTPException: 403 the set is not an inherited pack's own set; 422 a value that does not fit its variable.
    """
    project = _project_or_404(db, project_id)
    scoped = _reachable(db, project, pack_id)
    row = _set_of(db, scoped.pack, set_id)
    if not _project_set_access(scoped.pack, project, row)[1]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a set saved with an inherited pack can be overridden.")
    version = report_packs.current_version(db, scoped.pack)
    try:
        report_pack_sets.put_override(
            db, scoped.pack, version, row, project, variable_values=body.values, actor_id=current_user.id,
        )
    except (ValueError, VariableValueError) as exc:
        db.rollback()
        raise _set_error(exc) from exc
    db.commit()
    return _one_set(db, scoped.pack, version, project, set_id)


@project_router.delete("/{pack_id}/sets/{set_id}/override", response_model=ReportPackSetOut)
def reset_project_pack_set_override(
    project_id: UUID, pack_id: UUID, set_id: UUID,
    current_user: User = Depends(manage_project_layouts), db: Session = Depends(get_db),
) -> ReportPackSetOut:
    """Removes this project's override so the set's own values (or an ancestor's override) apply again."""
    project = _project_or_404(db, project_id)
    scoped = _reachable(db, project, pack_id)
    row = _set_of(db, scoped.pack, set_id)
    report_pack_sets.reset_override(db, scoped.pack, row, project, actor_id=current_user.id)
    db.commit()
    return _one_set(db, scoped.pack, report_packs.current_version(db, scoped.pack), project, set_id)


def _one_set(db: Session, pack: ReportPack, version: ReportPackVersion, project: Project, set_id: UUID) -> ReportPackSetOut:
    """One set as `project` sees it."""
    item = next(e for e in report_pack_sets.effective_sets(db, pack, project) if e.row.id == set_id)
    editable, overridable = _project_set_access(pack, project, item.row)
    return _set_out(db, version, item, [project.id], editable=editable, overridable=overridable)


__all__ = ["org_router", "project_router"]
