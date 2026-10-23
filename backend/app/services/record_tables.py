"""
Module: services.record_tables

The engine behind every record list's **Export** and **Import**: one file format both ways, for every
registered artefact type that has a `RecordTableProvider`.

Responsibilities:
- Authorise a table request (record type enabled for the project, `view` permission; the type's own create /
  update check for an import) and resolve which columns may leave or enter (`resolve_export_columns`).
- Build the table of a list (`build_table`): the provider's filtered rows, the project scope (`parents`,
  `children`, `both`) and tag filter applied generically, cells written for a spreadsheet.
- Run an import (`run_import`): parse the CSV, match each row to a record by its `code`, and create or update
  it **through the type's own create/update path**, as a preview (rolled back) or an apply (committed).
- Do the same for the records an **organisation** owns (`org_provider_for`, `build_org_table`, `run_org_import`),
  through the provider's `OrganizationRecordTable`: one import body serves both tiers, so a rule added to it
  reaches the organisation lists too.
- Serve the **bulk edit grid** of a project list (`build_grid`, `update_row`): the same rows, filters, scope and
  column policy as the export, with the editable columns as cells, saved one record at a time through the type's
  own update path.
- Audit an export or an apply as one event each; counts and keys only, never cell values.

Design decisions:
- The CSV an export writes is the CSV an import reads. A row with a `code` updates that record, a blank `code`
  creates one, a code that is unknown, or belongs to another project or organisation, is a row error and says
  the same thing for all three so it cannot be used to probe other projects.
- A preview is the apply run inside a transaction that is rolled back, so what it reports is what the type's
  own validation, version lock and approval gate say, not a second implementation of them. Each row runs in a
  savepoint: a refused row leaves nothing behind and the rest still apply.
- Update changes only the columns that differ from the exported value, so re-importing an unchanged export
  reports no change and writes no new version.
- Spreadsheet safety: a cell starting with `=`, `+`, `-`, `@`, tab or CR is written with a leading `'`
  (`services.csv_safety`); the importer strips exactly that one prefix again so the round trip is lossless.
- A provider never commits and never skips an authorisation the type's own endpoint makes; this engine only
  decides who may use the table at all.
- The organisation tier matches only the organisation's own records (a code of a project's record is a row error,
  as is a code of another organisation) and applies the organisation-level personal-data grant, since there is no
  project to hold a project grant. Its codes are always qualified by the organisation code (`ACME-PER-001`); the
  bare form is accepted on the way in.
- A grid save is one record per request (so one failure never blocks the others) and is audited by the type's own
  update path, with no second event. It changes only the cells that differ from the value the person loaded
  (`expected`): a cell someone else changed meanwhile is refused with the current value instead of being
  overwritten, which is the version lock for types whose update path has none.
  Only closed-value columns (`GRID_KINDS`) are edited in the grid; free text is edited in the record's form.
- Personal-data columns: every column carries a sensitivity tag set by the provider. `resolve_export_columns`
  is the single place that decides which are kept, and every route (export, import, the record-list report, the
  grid) goes through it, so the rule cannot be bypassed on one of them. A tagged column needs the organisation's
  policy (`services.record_policy`) to allow its tag and the person to hold `export_personal_data`; otherwise it
  is left out and the response says so.

Dependencies: `modules.registry` (the provider shapes), `services.rbac` and `services.permissions` (access),
`services.project_scope` and `services.tags` (the shared list filters), `services.codes`, `services.audit`.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import PrincipalType
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    OrganizationRecordTable,
    RecordCellError,
    RecordColumn,
    RecordFilters,
    RecordImportContext,
    RecordTableProvider,
    artefact_type_enabled_for_project,
    artefact_type_module,
    get_not_importable_types,
    get_record_table_providers,
    is_org_module_subcomponent_enabled,
)
from app.schemas.principal import PrincipalRef
from app.services import pubsub
from app.services.audit import log_event
from app.services.codes import display_code
from app.services.csv_safety import csv_safe
from app.services.permissions import encode_permission
from app.services.principals import group_ref_from_text, principal_labels, principal_text, validate_principal
from app.services.project_scope import ProjectScope, gate_open
from app.services.rbac import get_effective_org_roles, get_effective_permissions, permission_satisfied
from app.services.record_policy import REASON_PERMISSION, tag_decisions
from app.services.tags import TagFilter

logger = logging.getLogger(__name__)

MAX_IMPORT_ROWS = 5000
MAX_IMPORT_BYTES = 5 * 1024 * 1024
CODE_COLUMN = "code"
PROJECT_COLUMN = "project"
#: Query parameters every table request takes; a provider declares the rest in `filter_params`.
GENERIC_PARAMS = frozenset({"format", "project_scope", "tag", "tag_mode"})
#: Further query parameters the record-list report takes (its own, never a provider's filter).
REPORT_PARAMS = frozenset({"record_type", "report_template_id"})
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
#: The column kinds the bulk edit grid edits (a closed set of values or a single value); free text is not.
GRID_KINDS = frozenset({"enum", "number", "date", "bool"})
#: The most rows the grid loads; a longer list says so and asks for a narrower filter.
MAX_GRID_ROWS = 500


# --- access ----------------------------------------------------------------------------------------


def provider_for(db: Session, project: Project, artefact_type: str) -> RecordTableProvider:
    """The provider for `artefact_type` when its module is on for `project`.

    Args:
        db: Active session (read only).
        project: The request project.
        artefact_type: The record type from the URL.

    Raises:
        HTTPException: 404 when the type has no table, or its module (or the sub-component its list needs, the
            provider's `gate`) is off for the project (answered the same, so a disabled module's types cannot be
            listed by probing).
    """
    provider = get_record_table_providers().get(artefact_type)
    if provider is None or not artefact_type_enabled_for_project(db, artefact_type, project.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record type not found.")
    if provider.gate is not None and not gate_open(db, project.id, provider.gate):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record type not found.")
    return provider


def require_view(db: Session, user: User, project: Project, artefact_type: str) -> None:
    """Raises 403 unless `user` holds the record type's `view` permission in the project (the gate of its list)."""
    held = get_effective_permissions(db, user.id, project_id=project.id)
    if not permission_satisfied(held, encode_permission(artefact_type, "view")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to view these records.")


def _may(provider_check: Any, db: Session, user: User, project: Project, artefact_type: str, level: str) -> bool:
    """Whether `user` may create/update: the type's own check, else the fine-grained `level` permission."""
    if provider_check is not None:
        return bool(provider_check(db, user, project.id))
    held = get_effective_permissions(db, user.id, project_id=project.id)
    return permission_satisfied(held, encode_permission(artefact_type, level))


def import_capability(provider: RecordTableProvider, artefact_type: str, *, organization: bool = False) -> str | None:
    """Why `artefact_type` cannot be imported, or `None` when it can.

    A type is importable when its table can create or update. The reason a module gave in `not_importable`
    wins, so the message says what the module intended. `organization` asks about the organisation tier.
    """
    reason = get_not_importable_types().get(artefact_type)
    if reason:
        return reason
    table: RecordTableProvider | OrganizationRecordTable | None = provider.organization if organization else provider
    if table is None or (table.create is None and table.update is None):
        return "This record type cannot be imported."
    return None


def import_rights(
    db: Session, user: User, project: Project, artefact_type: str, provider: RecordTableProvider
) -> tuple[bool, bool]:
    """Whether `user` may create and whether they may update this type's records through an import.

    Args:
        db: Active session (read only).
        user: The person asking.
        project: The request project.
        artefact_type: The record type.
        provider: The type's table.

    Returns:
        `(may create, may update)`: each needs the provider to offer the operation and the user to hold its permission.
    """
    may_create = provider.create is not None and _may(provider.can_create, db, user, project, artefact_type, "propose_create")
    may_update = provider.update is not None and _may(provider.can_update, db, user, project, artefact_type, "manage")
    return may_create, may_update


def may_import(db: Session, user: User, project: Project, artefact_type: str, provider: RecordTableProvider) -> bool:
    """Whether `user` may create or update this type's records, the permission an import needs."""
    return any(import_rights(db, user, project, artefact_type, provider))


def org_import_rights(
    db: Session, user: User, organization: Organization, artefact_type: str, tier: OrganizationRecordTable
) -> tuple[bool, bool]:
    """`import_rights` for the organisation's own records: `(may create, may update)`.

    The type's own organisation-endpoint check wins; without one the fine-grained `propose_create` / `manage`
    permission at the organisation decides.
    """

    def may(check: Any, level: str) -> bool:
        if check is not None:
            return bool(check(db, user, organization.id))
        held = get_effective_permissions(db, user.id, organization_id=organization.id)
        return permission_satisfied(held, encode_permission(artefact_type, level))

    return (
        tier.create is not None and may(tier.can_create, "propose_create"),
        tier.update is not None and may(tier.can_update, "manage"),
    )


def org_may_import(db: Session, user: User, organization: Organization, artefact_type: str, tier: OrganizationRecordTable) -> bool:
    """Whether `user` may create or update the organisation's own records of this type through an import."""
    return any(org_import_rights(db, user, organization, artefact_type, tier))


def org_provider_for(db: Session, organization: Organization, artefact_type: str) -> RecordTableProvider:
    """The provider for `artefact_type` when it can be owned by `organization` and its module is on there.

    Args:
        db: Active session (read only).
        organization: The request organisation.
        artefact_type: The record type from the URL.

    Raises:
        HTTPException: 404 when the type has no organisation tier, or its module (or the sub-component the
            organisation list needs) is off for the organisation (answered the same, so a disabled module's
            types cannot be listed by probing).
    """
    provider = get_record_table_providers().get(artefact_type)
    if provider is None or provider.organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record type not found.")
    definition = artefact_type_module(artefact_type)
    if (
        definition is not None and provider.organization.subcomponent is not None
        and not is_org_module_subcomponent_enabled(db, organization.id, definition.key, provider.organization.subcomponent)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record type not found.")
    return provider


def require_org_member(db: Session, user: User, organization: Organization) -> None:
    """Raises 404 unless `user` holds a role in `organization` (the gate of the organisation lists; answered as
    absent so a stranger cannot tell the organisation exists)."""
    if not get_effective_org_roles(db, user.id, organization.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


def _org_tier(provider: RecordTableProvider) -> OrganizationRecordTable:
    """The provider's organisation tier (callers have already resolved it through `org_provider_for`)."""
    if provider.organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record type not found.")
    return provider.organization


def resolve_export_columns(
    db: Session, user: User, columns: Sequence[RecordColumn], *, organization_id: uuid.UUID, project_id: uuid.UUID | None = None,
    purpose: str,
) -> tuple[list[RecordColumn], list[str]]:
    """Which columns may be exported or imported, and which sensitivity tags were left out.

    The one function every route uses. A column tagged with a sensitivity (`personal`, `contact`,
    `free_text_people`) is kept only when the organisation's policy allows the tag (its override, else the
    server default, else excluded) **and** the person holds `export_personal_data` in the project, or in the
    organisation for its own lists (`services.record_policy.tag_decisions`), so a fresh install lets no
    personal data leave through a file; an untagged column is always kept.

    Args:
        db: Active session (read only).
        user: The person asking.
        columns: The provider's columns.
        organization_id: The organisation whose policy applies.
        project_id: The request project, or `None` for the organisation's own lists.
        purpose: `"export"` or `"import"` (an import ignores an excluded column the same way an export omits it).

    Returns:
        `(kept columns, sorted tags that caused an omission)`.
    """
    decisions = tag_decisions(db, user, organization_id, project_id)
    kept: list[RecordColumn] = []
    omitted: set[str] = set()
    for column in columns:
        if column.sensitivity == "none" or decisions[column.sensitivity].allowed:
            kept.append(column)
        else:
            omitted.add(column.sensitivity)
    return kept, sorted(omitted)


# --- cells -----------------------------------------------------------------------------------------


def write_cell(value: Any) -> str:
    """A cell as written to the file: text, with the formula guard applied."""
    return csv_safe("" if value is None else str(value))


def read_cell(raw: str) -> str:
    """A cell as read from the file: trimmed, with the one guard `'` removed again.

    Only a `'` followed by a formula trigger character is the guard; a person's own apostrophe stays.
    """
    text = (raw or "").strip()
    if len(text) > 1 and text[0] == "'" and text[1] in _FORMULA_TRIGGERS:
        return text[1:]
    return text


def _same(before: str, after: str) -> bool:
    """Whether two cell texts mean the same (line endings differ between a spreadsheet and the app)."""
    return before.replace("\r\n", "\n").strip() == after.replace("\r\n", "\n").strip()


@dataclass
class PrincipalCells:
    """Batch lookup for a person column: an email for a user, `Name (Org group)` for a group.

    Load once per export (`load`), then ask per row (`text`), so a long list costs a fixed number of queries.
    """

    labels: dict[tuple[str, uuid.UUID], Any] = field(default_factory=dict)
    emails: dict[uuid.UUID, str] = field(default_factory=dict)

    @classmethod
    def load(cls, db: Session, refs: Sequence[PrincipalRef | None]) -> PrincipalCells:
        """Resolves every principal in `refs` (empty ones are skipped)."""
        labels = principal_labels(db, [r for r in refs if r is not None])
        user_ids = {i for (t, i) in labels if t == PrincipalType.USER.value}
        emails = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
        return cls(labels=labels, emails=emails)

    def text(self, type_value: str | None, principal_id: uuid.UUID | None) -> str:
        """The cell for one principal; empty for none."""
        if principal_id is None or type_value is None:
            return ""
        if type_value == PrincipalType.USER.value:
            return self.emails.get(principal_id, "")
        found = self.labels.get((type_value, principal_id))
        return principal_text(found) if found is not None else ""


def parse_principal_cell(ctx: RecordImportContext, text: str, *, field_name: str) -> PrincipalRef | None:
    """The person a cell names: an email (a user of the organisation) or a group (`Name (Org group)`).

    Args:
        ctx: The import context (organisation, project, per-import cache).
        text: The cell text; empty means nobody.
        field_name: The field's name, for the message.

    Returns:
        The principal, or `None` for an empty cell.

    Raises:
        RecordCellError: The user or group is unknown, or may not be named here (another organisation).
    """
    if not text:
        return None
    if "@" in text:
        key = f"user:{text.lower()}"
        if key not in ctx.cache:
            ctx.cache[key] = ctx.db.scalar(select(User).where(User.email == text.lower()))
        user = ctx.cache[key]
        if user is None:
            raise RecordCellError(f"Unknown {field_name} '{text}'.")
        ref: PrincipalRef | None = PrincipalRef(type=PrincipalType.USER, id=user.id)
    else:
        ref, problem = group_ref_from_text(
            ctx.db, text, organization_id=ctx.organization_id, project_id=ctx.project_id
        )
        if ref is None:
            raise RecordCellError(problem or f"Unknown {field_name} '{text}'.")
    try:
        validate_principal(
            ctx.db, ref, organization_id=ctx.organization_id, project_id=ctx.project_id, field=field_name
        )
    except HTTPException as exc:
        if "@" in text:
            # A user of another organisation reads exactly like an unknown email: the file must not reveal who exists elsewhere.
            raise RecordCellError(f"Unknown {field_name} '{text}'.") from None
        raise RecordCellError(str(exc.detail)) from None
    return ref


# --- export ----------------------------------------------------------------------------------------


@dataclass
class RecordTable:
    """A list as a table, before it becomes a file.

    Attributes:
        columns: The columns written, `code` first (and `project` last when the scope was widened).
        rows: One list of cell texts per record, in column order, **before** the formula guard (`write_cell`).
        omitted: Sensitivity tags whose columns were left out by the policy.
        filter_keys: The names of the filters that were applied (for the audit event; never their values).
        included: Sensitivity tags whose columns were written (for the audit event).
        tones: Cell-text-to-tone map by column key, for the columns that colour their cells in a report.
        kept: The provider's columns that survived the personal-data policy, in `columns` order after `code`.
        ids: Each row's record id (the grid addresses and opens a record by it).
        project_ids: Each row's owning project id (a related project's row differs from the request project), or
            `None` for a record the organisation owns.
        read_only: Each row's reason the grid shows it read-only (another project's or the organisation's record, or
            the provider's `read_only_reason`), or `None` when it can be edited.
        cell_locks: Per row, the reason each single cell cannot be edited (`RecordColumn.cell_lock`), by column key.
    """

    columns: list[tuple[str, str]]
    rows: list[list[str]]
    omitted: list[str]
    filter_keys: list[str]
    included: list[str] = field(default_factory=list)
    tones: dict[str, Mapping[str, str]] = field(default_factory=dict)
    kept: list[RecordColumn] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    project_ids: list[str | None] = field(default_factory=list)
    read_only: list[str | None] = field(default_factory=list)
    cell_locks: list[dict[str, str]] = field(default_factory=list)


def split_params(
    provider: RecordTableProvider, query: Sequence[tuple[str, str]], *, also: frozenset[str] = frozenset(),
) -> RecordFilters:
    """The provider's filters out of a request's query string.

    Args:
        provider: The record type's table.
        query: The request's query parameters as pairs.
        also: Further parameter names the caller itself takes (not filters).

    Raises:
        HTTPException: 422 for a parameter neither generic nor declared by the provider, so a filter the
            export cannot honour is refused instead of silently dropped (a filtered-looking screen must not
            download an unfiltered file).
    """
    allowed = GENERIC_PARAMS | provider.filter_params | also
    unknown = sorted({k for k, _ in query if k not in allowed})
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"This list cannot be exported with the filter(s): {', '.join(unknown)}."
        )
    values: dict[str, list[str]] = {}
    for key, value in query:
        if key in provider.filter_params:
            values.setdefault(key, []).append(value)
    return RecordFilters(values=values)


def _qualified(
    project: Project, organization: Organization | None, unique_code: str, owner: Project, *, organization_owned: bool = False,
) -> str:
    """The code as an export writes it: bare in this project, qualified elsewhere or when the organisation enforces it,
    and always qualified by the organisation's code for a record the organisation owns."""
    if organization_owned and organization is not None:
        return display_code(unique_code, organization.code, organization_owned=True)
    return display_code(
        unique_code, owner.code, own_project_code=project.code,
        enforced=bool(organization and organization.enforce_code_everywhere),
    )


def build_table(
    db: Session, user: User, project: Project, artefact_type: str, provider: RecordTableProvider, *,
    filters: RecordFilters, tag_filter: TagFilter, project_scope: ProjectScope,
) -> RecordTable:
    """Builds the table of `artefact_type` with the page's filters, tag filter and project scope.

    Args:
        db: Active session (read only).
        user: The caller (authorised by the route).
        project: The request project.
        artefact_type: The record type.
        provider: Its provider.
        filters: The provider's own filters.
        tag_filter: The shared tag filter.
        project_scope: The shared nested-project scope.

    Returns:
        The `RecordTable`; rows from a related project are labelled in a trailing `project` column.
    """
    columns, omitted = resolve_export_columns(
        db, user, provider.columns(db, project), organization_id=project.organization_id, project_id=project.id, purpose="export",
    )

    def rows_for(project_id: uuid.UUID) -> list[Any]:
        found = provider.list_records(db, user, project_id, filters)
        return tag_filter.keep(db, project_id, artefact_type, found, id_of=provider.id_of)

    records = project_scope.collect(db, project, user.id, artefact_type, rows_for, gate=provider.gate, id_of=provider.id_of)
    prepared = provider.prepare(db, project, records) if provider.prepare is not None else None
    organization = db.get(Organization, project.organization_id)
    owners: dict[uuid.UUID, Project] = {project.id: project}
    header = [(CODE_COLUMN, "Code"), *((c.key, c.label) for c in columns)]
    if project_scope.widened:
        header.append((PROJECT_COLUMN, "Project"))
    rows: list[list[str]] = []
    ids: list[str] = []
    project_ids: list[str | None] = []
    read_only: list[str | None] = []
    cell_locks: list[dict[str, str]] = []
    lockable = [c for c in columns if c.cell_lock is not None]
    for record in records:
        owner_id = getattr(record, "from_project_id", None) or project.id
        if owner_id not in owners:
            owners[owner_id] = db.get(Project, owner_id) or project
        owner = owners[owner_id]
        owned_by_organization = provider.organization_owned is not None and provider.organization_owned(record)
        row = [_qualified(project, organization, provider.code_of(record), owner, organization_owned=owned_by_organization)]
        row += [column.get(prepared, record) for column in columns]
        if project_scope.widened:
            row.append("" if owned_by_organization else owner.code)
        rows.append(row)
        ids.append(str(provider.id_of(record)))
        project_ids.append(None if owned_by_organization else str(owner.id))
        read_only.append(_read_only_reason(provider, prepared, record, owner, project, owned_by_organization))
        cell_locks.append({c.key: reason for c in lockable if (reason := c.cell_lock(prepared, record))})
    keys = _applied_filter_keys(filters)
    if tag_filter.active:
        keys.append("tag")
    if project_scope.widened:
        keys.append("project_scope")
    return RecordTable(
        columns=header, rows=rows, omitted=omitted, filter_keys=sorted(keys), included=_sensitivity_tags(columns),
        tones={c.key: c.tones for c in columns if c.tones}, kept=list(columns), ids=ids, project_ids=project_ids, read_only=read_only,
        cell_locks=cell_locks,
    )


def _read_only_reason(
    provider: RecordTableProvider, prepared: Any, record: Any, owner: Project, project: Project, owned_by_organization: bool,
) -> str | None:
    """Why the grid shows `record` read-only, or `None`: it belongs to the organisation or to another project (the
    widened scope lists related projects' rows read-only), or the provider says its state forbids an edit."""
    if owned_by_organization:
        return "This record belongs to the organisation; edit it in the organisation's settings."
    if owner.id != project.id:
        return f"This record belongs to project {owner.code}; open it there to edit it."
    return provider.read_only_reason(prepared, record) if provider.read_only_reason is not None else None


def split_org_params(provider: RecordTableProvider, query: Sequence[tuple[str, str]]) -> RecordFilters:
    """`split_params` for the organisation lists: the organisation tier's filters only (no project scope or tags).

    Raises:
        HTTPException: 422 for a parameter the organisation list cannot honour.
    """
    tier = _org_tier(provider)
    allowed = {"format"} | tier.filter_params
    unknown = sorted({k for k, _ in query if k not in allowed})
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"This list cannot be exported with the filter(s): {', '.join(unknown)}."
        )
    values: dict[str, list[str]] = {}
    for key, value in query:
        if key in tier.filter_params:
            values.setdefault(key, []).append(value)
    return RecordFilters(values=values)


def build_org_table(
    db: Session, user: User, organization: Organization, provider: RecordTableProvider, *, filters: RecordFilters,
) -> RecordTable:
    """Builds the table of the organisation's own records of one type with the organisation list's filters.

    Args:
        db: Active session (read only).
        user: The caller (authorised by the route).
        organization: The request organisation.
        provider: The type's provider (it has an organisation tier).
        filters: The organisation tier's filters.

    Returns:
        The `RecordTable`; every code is qualified by the organisation's code, as the organisation's records are
        always cited.
    """
    tier = _org_tier(provider)
    columns, omitted = resolve_export_columns(
        db, user, tier.columns(db, organization), organization_id=organization.id, purpose="export",
    )
    records = tier.list_records(db, user, organization, filters)
    prepared = tier.prepare(db, organization, records) if tier.prepare is not None else None
    header = [(CODE_COLUMN, "Code"), *((c.key, c.label) for c in columns)]
    rows = [
        [display_code(provider.code_of(record), organization.code, organization_owned=True), *(c.get(prepared, record) for c in columns)]
        for record in records
    ]
    return RecordTable(
        columns=header, rows=rows, omitted=omitted, filter_keys=_applied_filter_keys(filters), included=_sensitivity_tags(columns),
        tones={c.key: c.tones for c in columns if c.tones},
    )


def _applied_filter_keys(filters: RecordFilters) -> list[str]:
    """The names of the provider filters that carry a value (for the audit event; never the values)."""
    return sorted(k for k, values in filters.values.items() if any(v.strip() for v in values))


def _sensitivity_tags(columns: Sequence[RecordColumn]) -> list[str]:
    """The sorted sensitivity tags carried by `columns` (untagged columns carry none)."""
    return sorted({c.sensitivity for c in columns if c.sensitivity != "none"})


def table_csv(table: RecordTable) -> bytes:
    """The table as UTF-8 CSV (with a byte-order mark, so a spreadsheet reads the encoding), formula-guarded."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([write_cell(key) for key, _ in table.columns])
    for row in table.rows:
        writer.writerow([write_cell(cell) for cell in row])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def _audit_owner(owner: Project | Organization) -> dict[str, Any]:
    """The audit-event fields that name where an export or import happened: a project, or an organisation's own lists."""
    if isinstance(owner, Organization):
        return {"entity_type": "organization", "entity_id": owner.id, "organization_id": owner.id}
    return {"entity_type": "project", "entity_id": owner.id, "project_id": owner.id, "organization_id": owner.organization_id}


def audit_export(db: Session, user: User, owner: Project | Organization, artefact_type: str, table: RecordTable, fmt: str) -> None:
    """Records one `records_exported` event (counts and filter keys only) and commits it.

    `owner` is the project exported from, or the organisation for its own lists.
    """
    log_event(
        db, action="records_exported", actor_id=user.id, **_audit_owner(owner),
        detail={
            "record_type": artefact_type, "format": fmt, "rows": len(table.rows),
            "columns": len(table.columns), "filters": table.filter_keys, "omitted_sensitivity": table.omitted,
            "included_sensitivity": table.included,
        },
    )
    db.commit()


# --- bulk edit grid --------------------------------------------------------------------------------


def grid_editable(column: RecordColumn) -> bool:
    """Whether the bulk edit grid edits `column`: the provider marked it editable, an import can write it, and it is
    a closed-value kind (`GRID_KINDS`)."""
    return column.editable and column.importable and column.kind in GRID_KINDS


@dataclass
class GridRow:
    """One record of the grid.

    Attributes:
        id: The record's id (to open it).
        code: The code as an export writes it.
        cells: Cell text by column key (unprefixed; the grid is not a spreadsheet, so no formula guard).
        read_only: Why the row cannot be edited, or `None`.
        locks: Why a single cell cannot be edited, by column key (only the locked cells).
        project_id: The project that owns the record, or `None` for one the organisation owns.
    """

    id: str
    code: str
    cells: dict[str, str]
    read_only: str | None = None
    locks: dict[str, str] = field(default_factory=dict)
    project_id: str | None = None


@dataclass
class RecordGrid:
    """A list prepared for the bulk edit grid.

    Attributes:
        columns: The columns the policy lets through, in the provider's order (the page decides which to show).
        rows: At most `MAX_GRID_ROWS` rows.
        total: How many rows the filters matched.
        omitted: Sensitivity tags whose columns the policy left out.
        can_edit: Whether the caller may update this type's records at all.
    """

    columns: list[RecordColumn]
    rows: list[GridRow]
    total: int
    omitted: list[str]
    can_edit: bool

    @property
    def truncated(self) -> bool:
        """Whether more rows matched than the grid loaded."""
        return self.total > len(self.rows)


def build_grid(
    db: Session, user: User, project: Project, artefact_type: str, provider: RecordTableProvider, *,
    filters: RecordFilters, tag_filter: TagFilter, project_scope: ProjectScope,
) -> RecordGrid:
    """The rows and columns of the grid for a list, narrowed exactly as its export is.

    Args:
        db: Active session (read only).
        user: The caller (authorised to view by the route).
        project: The request project.
        artefact_type: The record type.
        provider: Its provider.
        filters: The provider's own filters.
        tag_filter: The shared tag filter.
        project_scope: The shared nested-project scope.

    Returns:
        The `RecordGrid`; `can_edit` is false (and the page offers no grid) for a type the caller cannot update or
        that has no grid-editable column.
    """
    table = build_table(
        db, user, project, artefact_type, provider, filters=filters, tag_filter=tag_filter, project_scope=project_scope,
    )
    keys = [c.key for c in table.kept]
    rows = [
        GridRow(id=table.ids[i], code=cells[0], cells=dict(zip(keys, cells[1:1 + len(keys)], strict=True)),
            read_only=table.read_only[i], locks=table.cell_locks[i], project_id=table.project_ids[i],
        )
        for i, cells in enumerate(table.rows[:MAX_GRID_ROWS])
    ]
    _, may_update = import_rights(db, user, project, artefact_type, provider)
    can_edit = import_capability(provider, artefact_type) is None and may_update and any(grid_editable(c) for c in table.kept)
    return RecordGrid(columns=table.kept, rows=rows, total=len(table.rows), omitted=table.omitted, can_edit=can_edit)


def update_row(
    db: Session, user: User, project: Project, artefact_type: str, provider: RecordTableProvider, code: str,
    cells: Mapping[str, str], expected: Mapping[str, str],
) -> GridRow:
    """Saves the changed cells of one record through the type's own update path and returns the refreshed row.

    Args:
        db: Active session. Committed on success, rolled back on any failure.
        user: The editor (authorised to view by the route; update rights are checked here).
        project: The request project (a record of any other project is never matched).
        artefact_type: The record type.
        provider: Its provider.
        code: The record's code.
        cells: The new cell text by column key (only grid-editable columns).
        expected: The text each cell had when the grid loaded it; a cell that has changed since is refused.

    Returns:
        The record as the grid shows it after the save.

    Raises:
        HTTPException: 422 when the type cannot be edited, a column is not grid-editable or a value is refused;
            403 without the update right; 404 for an unknown code; 409 when a cell changed since it was loaded or
            the type's own path refuses (a locked record).
    """
    reason = import_capability(provider, artefact_type)
    if reason is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, reason)
    _, may_update = import_rights(db, user, project, artefact_type, provider)
    if not may_update:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to update these records.")
    available, _ = resolve_export_columns(
        db, user, provider.columns(db, project), organization_id=project.organization_id, project_id=project.id, purpose="import",
    )
    by_key = {c.key: c for c in available}
    for key in cells:
        column = by_key.get(key)
        if column is None or not grid_editable(column):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That column cannot be edited here.")
    record = _find_record(db, project, provider, code)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No record with the code {code} in this project.")
    prepared = provider.prepare(db, project, [record]) if provider.prepare is not None else None
    blocked = provider.read_only_reason(prepared, record) if provider.read_only_reason is not None else None
    if blocked:
        raise HTTPException(status.HTTP_409_CONFLICT, blocked)

    ctx = RecordImportContext(db=db, project=project, user=user, organization=db.get(Organization, project.organization_id))
    values: dict[str, Any] = {}
    try:
        for key, raw in cells.items():
            column = by_key[key]
            text = read_cell(raw)
            locked = column.cell_lock(prepared, record) if column.cell_lock is not None else None
            if locked:
                raise HTTPException(status.HTTP_409_CONFLICT, locked)
            before = column.get(prepared, record)
            if key in expected and not _same(before, read_cell(expected[key])):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"{column.label} was changed by someone else (now '{before}'); reload before editing it again.",
                )
            if _same(before, text):
                continue
            if column.required and not text:
                raise RecordCellError(f"{column.label} is required.")
            values[key] = column.parse(ctx, text)
        if values:
            with db.begin_nested():
                provider.update(ctx, record, values)
                db.flush()
            db.commit()
            pubsub.notify(project.id, {"type": artefact_type, "action": "updated"})
    except RecordCellError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except HTTPException:
        db.rollback()
        raise
    except DataError:
        db.rollback()
        logger.warning("Grid edit of %s has a value the database cannot store", artefact_type)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A value is too long or not storable.") from None
    except IntegrityError:
        db.rollback()
        logger.warning("Grid edit of %s refused by the database", artefact_type)
        raise HTTPException(status.HTTP_409_CONFLICT, "This change conflicts with an existing record.") from None

    db.refresh(record)
    prepared = provider.prepare(db, project, [record]) if provider.prepare is not None else None
    return GridRow(
        id=str(provider.id_of(record)), code=provider.code_of(record), project_id=str(project.id),
        cells={c.key: c.get(prepared, record) for c in available},
        read_only=provider.read_only_reason(prepared, record) if provider.read_only_reason is not None else None,
        locks={c.key: reason for c in available if c.cell_lock is not None and (reason := c.cell_lock(prepared, record))},
    )


# --- import ----------------------------------------------------------------------------------------


@dataclass
class ColumnChange:
    """One cell an update would change: the exported value and the file's."""

    column: str
    label: str
    before: str
    after: str


@dataclass
class RowResult:
    """What happened (or, in a preview, would happen) to one row of the file.

    Attributes:
        row: The row's line number in the file (the header is row 1).
        action: `create`, `update`, `unchanged` or `error`.
        code: The record's code for an update or unchanged row; the code in the file for an error.
        changes: For an update, the cells that change.
        message: For an error, what was wrong.
    """

    row: int
    action: str
    code: str = ""
    changes: list[ColumnChange] = field(default_factory=list)
    message: str = ""


@dataclass
class ImportResult:
    """The outcome of `run_import`.

    Attributes:
        applied: `True` after an apply, `False` for a preview (nothing was written).
        rows: One `RowResult` per data row.
        ignored_columns: `{header: reason}` for file columns that were not used.
        omitted: Sensitivity tags whose columns the policy excluded.
        included: Sensitivity tags of the file columns that were used (for the audit event).
        error_csv: The failed rows with an `error` column, ready to fix and re-upload; empty without errors.
    """

    applied: bool
    rows: list[RowResult]
    ignored_columns: dict[str, str]
    omitted: list[str]
    included: list[str] = field(default_factory=list)
    error_csv: str = ""

    def count(self, action: str) -> int:
        """How many rows have `action`."""
        return sum(1 for r in self.rows if r.action == action)


def _read_rows(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Parses the upload into its header and data rows, enforcing the size and row caps.

    Raises:
        HTTPException: 413 over the byte or row cap; 422 for a file that is not UTF-8 CSV or has a
            duplicate or blank header.
    """
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"The file is too large (limit {MAX_IMPORT_BYTES // (1024 * 1024)} MB).")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file must be a UTF-8 CSV.") from None
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.") from None
    except csv.Error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is not a valid CSV.") from None
    header = [h.strip() for h in header]
    if not any(header):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The first row must be the column headers.")
    duplicates = sorted(h for h, n in Counter(h for h in header if h).items() if n > 1)
    if duplicates:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Repeated column(s): {', '.join(duplicates)}.")
    rows: list[dict[str, str]] = []
    try:
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue
            if len(rows) >= MAX_IMPORT_ROWS:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE, f"The file has more than {MAX_IMPORT_ROWS} rows; split it into smaller files."
                )
            rows.append({h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header) if h})
    except csv.Error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is not a valid CSV.") from None
    return header, rows


def _find_record(db: Session, project: Project, provider: RecordTableProvider, code: str) -> Any | None:
    """The record in **this project** for a code as exported: bare, or qualified with this project's code."""
    found = provider.find(db, project, code)
    if found is None and project.code and code.upper().startswith(f"{project.code.upper()}-"):
        found = provider.find(db, project, code[len(project.code) + 1:])
    return found


def _find_org_record(db: Session, organization: Organization, tier: OrganizationRecordTable, code: str) -> Any | None:
    """The record among **this organisation's own** for a code as exported: qualified with the organisation code, or bare."""
    found = tier.find(db, organization, code)
    if found is None and organization.code and code.upper().startswith(f"{organization.code.upper()}-"):
        found = tier.find(db, organization, code[len(organization.code) + 1:])
    return found


def _error_csv(header: list[str], failed: list[tuple[dict[str, str], str]]) -> str:
    """The failed rows, as uploaded, plus the reason, so the file can be fixed and uploaded again."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([write_cell(h) for h in header if h] + ["error"])
    for row, message in failed:
        writer.writerow([write_cell(row.get(h, "")) for h in header if h] + [write_cell(message)])
    return buffer.getvalue()


@dataclass(frozen=True)
class _ImportTarget:
    """Where an import reads and writes: a project's records, or the organisation's own.

    The two tiers differ only in what is listed here, so `_import_rows` is written once.

    Attributes:
        organization: The organisation (its policy applies to both tiers).
        project: The project, or `None` at the organisation tier.
        columns: The provider's columns for this tier.
        find: Finds a record of this tier by the code in the file.
        prepare: Batch lookups for the "before" cells, or `None`.
        create / update: The provider's write paths, already `None` where the caller lacks the right.
        code_of / id_of: Read a record's code and id.
        place: How the tier reads in a message ("project" / "organisation").
    """

    organization: Organization
    project: Project | None
    columns: Sequence[RecordColumn]
    find: Callable[[str], Any | None]
    prepare: Callable[[list[Any]], Any] | None
    create: Callable[[RecordImportContext, Mapping[str, Any]], Any] | None
    update: Callable[[RecordImportContext, Any, Mapping[str, Any]], None] | None
    code_of: Callable[[Any], str]
    id_of: Callable[[Any], Any]
    place: str

    @property
    def owner(self) -> Project | Organization:
        return self.project if self.project is not None else self.organization


def run_import(
    db: Session, user: User, project: Project, artefact_type: str, provider: RecordTableProvider, data: bytes, *, apply: bool
) -> ImportResult:
    """Creates and updates a project's records from an exported CSV.

    Each row runs through the provider's own create or update in a savepoint, so a refused row leaves nothing
    behind. A preview (`apply=False`) rolls the whole transaction back at the end; an apply commits the valid
    rows and records one `records_imported` audit event.

    Args:
        db: Active session. The engine commits on apply and rolls back on preview.
        user: The importer (authorised by the route to see the type; create/update rights are checked here).
        project: The request project (records of any other project are never matched).
        artefact_type: The record type.
        provider: Its provider.
        data: The uploaded bytes.
        apply: Write the changes (`True`) or only report them (`False`).

    Returns:
        The per-row outcomes, ignored columns, policy omissions and an error CSV.

    Raises:
        HTTPException: 422 when the type cannot be imported or the file is malformed, 403 when the caller may
            neither create nor update, 413 for a file over the byte or row cap.
    """
    reason = import_capability(provider, artefact_type)
    if reason is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, reason)
    may_create, may_update = import_rights(db, user, project, artefact_type, provider)
    if not may_create and not may_update:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to import these records.")
    target = _ImportTarget(
        organization=db.get(Organization, project.organization_id), project=project, columns=list(provider.columns(db, project)),
        find=lambda code: _find_record(db, project, provider, code),
        prepare=(lambda records: provider.prepare(db, project, records)) if provider.prepare is not None else None,
        create=provider.create if may_create else None, update=provider.update if may_update else None,
        code_of=provider.code_of, id_of=provider.id_of, place="project",
    )
    return _import_rows(db, user, target, artefact_type, data, apply=apply)


def run_org_import(
    db: Session, user: User, organization: Organization, artefact_type: str, provider: RecordTableProvider, data: bytes, *,
    apply: bool,
) -> ImportResult:
    """`run_import` for the records the **organisation** owns (its Strategies, Personas, ...).

    Only the organisation's own records are matched: a code of a project's record, or of another organisation, is
    a row error. Create and update need what the organisation endpoints need (`OrganizationRecordTable.can_*`).

    Raises:
        HTTPException: As `run_import`.
    """
    tier = _org_tier(provider)
    reason = import_capability(provider, artefact_type, organization=True)
    if reason is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, reason)
    may_create, may_update = org_import_rights(db, user, organization, artefact_type, tier)
    if not may_create and not may_update:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to import these records.")
    target = _ImportTarget(
        organization=organization, project=None, columns=list(tier.columns(db, organization)),
        find=lambda code: _find_org_record(db, organization, tier, code),
        prepare=(lambda records: tier.prepare(db, organization, records)) if tier.prepare is not None else None,
        create=tier.create if may_create else None, update=tier.update if may_update else None,
        code_of=provider.code_of, id_of=provider.id_of, place="organisation",
    )
    return _import_rows(db, user, target, artefact_type, data, apply=apply)


def _import_rows(
    db: Session, user: User, target: _ImportTarget, artefact_type: str, data: bytes, *, apply: bool
) -> ImportResult:
    """The import body shared by both tiers: parse, match each row by code, create or update, report.

    A preview rolls the transaction back at the end; an apply commits and records one `records_imported` event.
    """
    organization = target.organization
    header, file_rows = _read_rows(data)
    project_id = target.project.id if target.project is not None else None
    available, omitted = resolve_export_columns(
        db, user, target.columns, organization_id=organization.id, project_id=project_id, purpose="import",
    )
    by_key = {c.key: c for c in available}
    all_keys = {c.key: c for c in target.columns}
    ignored: dict[str, str] = {}
    decisions = tag_decisions(db, user, organization.id, project_id)
    for name in header:
        if not name or name == CODE_COLUMN:
            continue
        column = by_key.get(name)
        if column is None:
            ignored[name] = (
                _omission_reason(decisions[all_keys[name].sensitivity].reason) if name in all_keys
                else "Calculated from other data." if name == PROJECT_COLUMN else "Not a column of this record type."
            )
        elif not column.importable:
            ignored[name] = "Calculated or controlled elsewhere; not imported."
    in_file = [by_key[n] for n in header if n in by_key and by_key[n].importable]
    parsers = {c.key: c.parse for c in in_file if c.parse is not None}
    create_fn, update_fn = target.create, target.update
    has_code_column = CODE_COLUMN in header

    ctx = RecordImportContext(db=db, project=target.project, user=user, organization=organization)
    prepared_cache: dict[str, Any] = {}
    results: list[RowResult] = []
    failed: list[tuple[dict[str, str], str]] = []
    seen_codes: set[str] = set()

    for line, row in enumerate(file_rows, start=2):
        raw_code = read_cell(row.get(CODE_COLUMN, "")) if has_code_column else ""
        result = RowResult(row=line, action="error", code=raw_code)

        def fail(message: str, result: RowResult = result, row: dict[str, str] = row) -> None:
            result.action, result.message = "error", message
            failed.append((row, message))

        record = None
        if raw_code:
            if raw_code.upper() in seen_codes:
                fail(f"The code {raw_code} appears more than once in the file.")
                results.append(result)
                continue
            seen_codes.add(raw_code.upper())
            record = target.find(raw_code)
            if record is None:
                fail(f"No record with the code {raw_code} in this {target.place}.")
                results.append(result)
                continue
            if update_fn is None:
                fail("You do not have permission to update these records.")
                results.append(result)
                continue
        elif create_fn is None:
            fail("You do not have permission to create these records.")
            results.append(result)
            continue

        cells = {c.key: read_cell(row.get(c.key, "")) for c in in_file}
        problem = _validate_required(available, in_file, cells, creating=record is None)
        if problem:
            fail(problem)
            results.append(result)
            continue
        try:
            if record is None:
                values = {key: parse(ctx, cells[key]) for key, parse in parsers.items()}
                with db.begin_nested():
                    create_fn(ctx, values)
                    db.flush()
                result.action = "create"
                result.code = ""
            else:
                prepared = prepared_cache.get(str(target.id_of(record)))
                if prepared is None and target.prepare is not None:
                    prepared = target.prepare([record])
                    prepared_cache[str(target.id_of(record))] = prepared
                changes = []
                for column in in_file:
                    before = column.get(prepared, record)
                    if not _same(before, cells[column.key]):
                        changes.append(ColumnChange(column.key, column.label, before, cells[column.key]))
                result.code = target.code_of(record)
                if not changes:
                    result.action = "unchanged"
                else:
                    values = {c.column: parsers[c.column](ctx, c.after) for c in changes}
                    with db.begin_nested():
                        update_fn(ctx, record, values)
                        db.flush()
                    result.action = "update"
                    result.changes = changes
        except RecordCellError as exc:
            fail(str(exc))
        except HTTPException as exc:
            fail(str(exc.detail))
        except DataError:
            # A value the column cannot hold (too long); the message would quote it, so it is not logged.
            logger.warning("Import row %s of %s has a value the database cannot store", line, artefact_type)
            fail("A value in this row is too long or not storable.")
        except IntegrityError:
            # No traceback: a database error message quotes the row's values, and cell values are never logged.
            logger.warning("Import row %s of %s refused by the database", line, artefact_type)
            fail("This row conflicts with an existing record.")
        results.append(result)

    result_set = ImportResult(
        applied=apply, rows=results, ignored_columns=ignored, omitted=omitted,
        included=_sensitivity_tags(in_file), error_csv=_error_csv(header, failed) if failed else "",
    )
    if not apply:
        db.rollback()
        return result_set

    created_n, updated_n = result_set.count("create"), result_set.count("update")
    log_event(
        db, action="records_imported", actor_id=user.id, **_audit_owner(target.owner),
        detail={
            "record_type": artefact_type, "created": created_n, "updated": updated_n,
            "unchanged": result_set.count("unchanged"), "failed": result_set.count("error"),
            "omitted_sensitivity": omitted, "included_sensitivity": result_set.included,
        },
    )
    db.commit()
    if (created_n or updated_n) and target.project is not None:
        pubsub.notify(target.project.id, {"type": artefact_type, "action": "imported"})
    return result_set


def _omission_reason(reason: str | None) -> str:
    """The row-level wording for a file column that the personal-data rule left out."""
    if reason == REASON_PERMISSION:
        return "Excluded: you do not have permission to import personal data."
    return "Excluded by your organisation's policy."


def _validate_required(
    available: Sequence[RecordColumn], in_file: Sequence[RecordColumn], cells: Mapping[str, str], *, creating: bool
) -> str | None:
    """A message when a required column is missing from a create, or blank wherever it is present."""
    present = {c.key for c in in_file}
    if creating:
        missing = [c.label for c in available if c.required and c.importable and c.key not in present]
        if missing:
            return f"The file has no {', '.join(missing)} column; a new record needs it."
    for column in in_file:
        if column.required and not cells[column.key]:
            return f"{column.label} is required."
    return None
