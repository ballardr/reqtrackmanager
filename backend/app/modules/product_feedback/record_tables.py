"""
Module: modules.product_feedback.record_tables

The `RecordTableProvider` of Product Feedback's one record type, the enhancement request: the list as a table, so
it exports to CSV, PDF and Word and imports from the same CSV (a row with a code updates, a blank code creates).
The organisation's inbox is the provider's `OrganizationRecordTable`.

Responsibilities:
- Declare the columns (title, description, owner, external reference, tags) and the status and decline reason as
  export-only cells.
- Share the create and edit logic with the endpoints (`_shared.stage_request` / `stage_request_update`), so the
  owner validation, the version history and the audit event are the ones the screen applies.

Design decisions:
- `status` and `decline_reason` are export-only: a request moves through its lifecycle only by the transition
  endpoint, whose rules (a reason to decline, no direct move to duplicate) a file must not bypass. A created
  request starts `New`, as the create endpoint starts it.
- Updating needs the triager role (the edit endpoint's gate); creating follows the endpoint's gate (any member,
  unless the project restricted submission to triagers).

Dependencies: `_shared` (stage functions, gates), `service`, `services.record_tables_core`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.product_feedback import _shared as sh
from app.modules.product_feedback.enums import EnhancementRequestScope, EnhancementRequestStatus
from app.modules.product_feedback.labels import REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE
from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestVersion
from app.modules.product_feedback.schemas import RequestCreate, RequestUpdate
from app.modules.product_feedback.service import (
    ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
    PRODUCT_FEEDBACK_MODULE_KEY,
    REQUEST_ARTEFACT_TYPE,
    REQUEST_SUBCOMPONENT_KEY,
    RecordOwner,
    filter_requests,
    list_organization_requests,
    list_project_requests,
)
from app.modules.registry import (
    OrganizationRecordTable,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
)
from app.services import tags as tag_service
from app.services.principals import principal_ref
from app.services.record_tables import PrincipalCells, find_many_by_code
from app.services.record_tables_core import count_rows, enum_filter, list_cell, person_parser, text_parser

IMPORT_NOTE = "Edited by record import."

#: The list's own filters, by the names its export takes.
REQUEST_FILTERS = frozenset({"include_archived", "status", "open_only", "search"})


class _Prepared:
    """Lookups handed to every column's `get`: current versions, owner cells and tags."""

    def __init__(self, db: Session, records: list[Any]) -> None:
        ids = [r.id for r in records]
        self.versions: dict[uuid.UUID, EnhancementRequestVersion] = {
            v.request_id: v
            for v in db.scalars(select(EnhancementRequestVersion).where(
                EnhancementRequestVersion.request_id.in_(ids), EnhancementRequestVersion.valid_to.is_(None),
            ))
        } if ids else {}
        self.people = PrincipalCells.load(db, [principal_ref(v.owner_type, v.owner_id) for v in self.versions.values()])
        self.tags = tag_service.tag_names_for_records(db, REQUEST_ARTEFACT_TYPE, ids) if ids else {}


def _filtered(db: Session, requests: list[EnhancementRequest], filters: RecordFilters) -> list[EnhancementRequest]:
    """The requests the list's filters keep (the same rules the list endpoints apply)."""
    return filter_requests(
        db, requests, status=enum_filter(filters, "status", EnhancementRequestStatus),
        open_only=bool(filters.flag("open_only")), search=filters.one("search"),
    )


def _list_project(db: Session, user: User, project_id: uuid.UUID, filters: RecordFilters) -> list[EnhancementRequest]:
    return _filtered(db, list_project_requests(db, project_id, include_archived=bool(filters.flag("include_archived"))), filters)


def _list_organization(
    db: Session, user: User, organization: Organization, filters: RecordFilters
) -> list[EnhancementRequest]:
    return _filtered(
        db, list_organization_requests(db, organization.id, include_archived=bool(filters.flag("include_archived"))),
        filters,
    )


def _text(key: str, label: str, *, required: bool = False) -> RecordColumn:
    return RecordColumn(
        key, label, lambda t, r: getattr(t.versions[r.id], key) or "", text_parser, editable=True, required=required,
    )


def _columns(db: Session, owner: Any) -> list[RecordColumn]:
    return [
        _text("title", "Title", required=True),
        _text("description", "Description"),
        RecordColumn(
            "owner", "Owner", lambda t, r: t.people.text(t.versions[r.id].owner_type, t.versions[r.id].owner_id),
            person_parser("owner"), kind="principal",
        ),
        _text("external_ref_url", "External reference URL"),
        _text("external_ref_key", "External reference key"),
        RecordColumn("tags", "Tags", lambda t, r: list_cell(t.tags.get(r.id, [])), kind="list"),
        RecordColumn(
            "status", "Status", lambda t, r: REQUEST_STATUS_LABEL[t.versions[r.id].status.value], kind="enum",
            tones={REQUEST_STATUS_LABEL[value]: tone for value, tone in REQUEST_STATUS_TONE.items()},
        ),
        RecordColumn("decline_reason", "Decline reason", lambda t, r: t.versions[r.id].decline_reason or ""),
    ]


def _fields(values: Mapping[str, Any]) -> dict[str, Any]:
    """The `RequestCreate` / `RequestUpdate` keyword arguments for the cells in `values`."""
    return {
        key: values[key]
        for key in ("title", "description", "owner", "external_ref_url", "external_ref_key") if key in values
    }


def _holder(ctx: RecordImportContext) -> RecordOwner:
    """The tier the import writes into: the project, or (without one) the organisation's inbox."""
    return RecordOwner.of_project(ctx.project) if ctx.project is not None else RecordOwner(ctx.organization.id)


def _create(ctx: RecordImportContext, values: Mapping[str, Any]) -> EnhancementRequest:
    return sh.stage_request(ctx.db, _holder(ctx), RequestCreate(**_fields(values)), ctx.user)


def _update(ctx: RecordImportContext, request: EnhancementRequest, values: Mapping[str, Any]) -> None:
    sh.stage_request_update(
        ctx.db, _holder(ctx), request, RequestUpdate(**_fields(values), change_note=IMPORT_NOTE), ctx.user,
    )


def _may_manage_project(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """The edit endpoint's gate: the Feedback Triager role or the `(enhancement_request, manage)` grant."""
    project = db.get(Project, project_id)
    return project is not None and sh.can_manage(db, user, RecordOwner.of_project(project))


def _may_create_project(db: Session, user: User, project_id: uuid.UUID) -> bool:
    """The create endpoint's gate: any member, unless the project restricted submission to triagers."""
    project = db.get(Project, project_id)
    if project is None:
        return False
    try:
        sh.require_request_submit(db, user, RecordOwner.of_project(project))
    except HTTPException:
        return False
    return True


def _may_manage_organization(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    return sh.can_manage(db, user, RecordOwner(organization_id))


def _may_create_organization(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    """Any organisation member may submit to the inbox (the organisation create endpoint's gate)."""
    return True


def _find_project(db: Session, project: Project, code: str) -> EnhancementRequest | None:
    return db.scalar(select(EnhancementRequest).where(
        EnhancementRequest.project_id == project.id, EnhancementRequest.unique_code == code.upper(),
    ))


def _find_organization(db: Session, organization: Organization, code: str) -> EnhancementRequest | None:
    return db.scalar(select(EnhancementRequest).where(
        EnhancementRequest.organization_id == organization.id,
        EnhancementRequest.scope == EnhancementRequestScope.ORGANIZATION,
        EnhancementRequest.unique_code == code.upper(),
    ))


REQUEST_TABLE = RecordTableProvider(
    label="Enhancement requests",
    columns=_columns,
    list_records=_list_project,
    find=_find_project,
    find_many=find_many_by_code(EnhancementRequest, "project_id", EnhancementRequest.scope == EnhancementRequestScope.PROJECT),
    prepare=lambda db, project, records: _Prepared(db, records),
    create=_create,
    update=_update,
    filter_params=REQUEST_FILTERS,
    gate=(PRODUCT_FEEDBACK_MODULE_KEY, REQUEST_SUBCOMPONENT_KEY),
    can_create=_may_create_project,
    can_update=_may_manage_project,
    organization=OrganizationRecordTable(
        subcomponent=ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
        columns=lambda db, organization: _columns(db, organization),
        list_records=_list_organization,
        find=_find_organization,
        find_many=find_many_by_code(
            EnhancementRequest, "organization_id", EnhancementRequest.scope == EnhancementRequestScope.ORGANIZATION,
        ),
        prepare=lambda db, organization, records: _Prepared(db, records),
        create=_create,
        update=_update,
        filter_params=REQUEST_FILTERS,
        can_create=_may_create_organization,
        can_update=_may_manage_organization,
    ),
    count=lambda db, user, project_id: count_rows(db, EnhancementRequest, project_id, live_only=True),
)

RECORD_TABLES: dict[str, RecordTableProvider] = {REQUEST_ARTEFACT_TYPE: REQUEST_TABLE}
