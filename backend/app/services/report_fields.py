"""
Module: services.report_fields

The field registry behind custom report layouts: what a layout may print, filter or group by
for each registered artefact type, and the batch loader that reads those values.

Responsibilities:
- Offer the builders a type's `ReportFieldProvider` is written with (`from_search`, `text_field`,
  `enum_field`, `date_field`, `principal_field`, `name_lookup_field`).
- Describe the fields of a type for a field picker (`field_catalogue`).
- Load records by id in one query per type (`load_records`), with enum values as labels,
  principals as names, tags as text and the reserved `code`/`title`/`status`/`tags` fields.
- Format a loaded value as report text (`format_value`).

Design decisions:
- Fields are opt-in per type. A column that is not declared cannot be reached from a layout, so a
  Restricted or consent-sensitive column is excluded by omission, exactly as for search.
- The loader **does not authorise**. It is only ever given ids the link graph's `ArtefactResolver`
  already showed the caller (`services.report_traversal`), so there is one authorisation point;
  a caller that skips the resolver is a defect, and the engine's public entry points take
  resolver-approved records only.
- A provider reuses the type's search declaration for its joins, current-version filter and
  identity columns (`from_search`), so a versioned type is joined once and kept in one place; the
  search's vetted text fields come across by default and a type lists its typed fields on top.
- Values are returned typed (`date`, `datetime`, `bool`, numbers) and formatted at the edge
  (`format_value`), so a renderer can sort and compare before it prints. A past instant stays UTC;
  a calendar date is a plain `date` and means the person's own day.
- A person field shows the user's name or `Name (Org group)` for a group (`principal_text`), never
  an email address.

Dependencies: `modules.registry` (provider shapes and merge), `services.principals` (names),
`services.tags` (tag text).
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.modules.registry import (
    REPORT_FIELD_KINDS,
    ArtefactSearchProvider,
    ReportField,
    ReportFieldProvider,
    get_report_field_providers,
)
from app.services.principals import principal_labels, principal_ref, principal_text
from app.services.project_hierarchy import get_project_chain_ids
from app.services.tags import tag_names_for_records

#: Keys the engine builds from the provider's identity columns; a provider's own field may not use them.
RESERVED_FIELD_KEYS = ("code", "title", "status", "tags")

#: Ids per `IN (...)` query, so a large traversal never builds an unbounded statement.
_CHUNK = 2000


class UnknownReportFieldError(KeyError):
    """A layout named a field the record type does not declare (or an unregistered type)."""


@dataclass(frozen=True)
class FieldInfo:
    """A field as a picker shows it.

    Attributes:
        key / label / kind: As on `ReportField`; `reserved` fields are the engine's own.
        choices: For an `enum`, the display labels a value can take, else empty.
        math: Whether the field may hold equations, which a layout's text block then draws.
    """

    key: str
    label: str
    kind: str
    reserved: bool = False
    choices: tuple[str, ...] = ()
    math: bool = False


@dataclass
class ReportRecord:
    """One loaded record: identity, the engine's reserved fields and the requested field values.

    Attributes:
        artefact_type / id: The record.
        project_id: Owning project, `None` for an organisation-owned record.
        organization_id: Owning organisation for a type that can be organisation-owned.
        unique_code: The bare stored code; a report names it through `ReportContext.code`/`org_code`.
        title: Display title.
        status: Status display label, empty for a type without a lifecycle.
        is_archived: Archived flag.
        updated_at: Last change (UTC).
        version: The current version number for a versioned type, else `None`.
        tags: Comma-separated tag text, empty when none (filled only when asked for).
        values: `{field key: typed value}` for the requested fields; `None` for an empty field.
            An `enum` is its label, a `principal` its text.
    """

    artefact_type: str
    id: uuid.UUID
    project_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    unique_code: str
    title: str
    status: str
    is_archived: bool
    updated_at: datetime | None
    tags: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    version: int | None = None


# --- builders ------------------------------------------------------------------------------------


def text_field(key: str, label: str, column: Any, *, math: bool = False) -> ReportField:
    """A free-text field; `math` marks one in which people write equations."""
    return ReportField(key, label, column, "text", math=math)


def date_field(key: str, label: str, column: Any) -> ReportField:
    """A calendar date (a plain `date`, the person's own day)."""
    return ReportField(key, label, column, "date")


def bool_field(key: str, label: str, column: Any) -> ReportField:
    """A yes/no flag."""
    return ReportField(key, label, column, "bool")


def number_field(key: str, label: str, column: Any) -> ReportField:
    """A number."""
    return ReportField(key, label, column, "number")


def instant_field(key: str, label: str, column: Any) -> ReportField:
    """A past instant, stored and returned in UTC."""
    return ReportField(key, label, column, "instant")


def enum_field(key: str, label: str, column: Any, enum_class: type[enum.Enum] | Mapping[str, str]) -> ReportField:
    """A closed-value field shown by its label.

    Args:
        key / label / column: As on `ReportField`.
        enum_class: The enum (labels are the value with underscores as spaces, first letter capitalised)
            or an explicit `{value: label}` map.
    """
    labels = (
        dict(enum_class) if isinstance(enum_class, Mapping)
        else {str(m.value): str(m.value).replace("_", " ").capitalize() for m in enum_class}
    )
    return ReportField(key, label, column, "enum", labels=labels)


def principal_field(key: str, label: str, type_column: Any, id_column: Any) -> ReportField:
    """A user-or-group field, from its `<name>_type` / `<name>_id` column pair."""
    return ReportField(key, label, type_column, "principal", id_column=id_column)


def name_lookup_field(
    key: str, label: str, name_column: Any, id_column: Any, foreign_key: Any, scope_column: Any,
) -> ReportField:
    """A text field that is the name of the row a foreign key points at (a requirement's component).

    A correlated scalar subquery, so it needs no extra join in the provider's `from_clause`. Its `domain` is the
    names the project defines (or inherits from an ancestor), so a run-time variable can offer them.

    Args:
        key / label: As on `ReportField`.
        name_column: The looked-up table's name column (`ProjectComponent.name`).
        id_column: That table's id column.
        foreign_key: The record's column holding the id.
        scope_column: The looked-up table's `project_id` column.
    """

    def domain(db: Session, project_ids: Sequence[uuid.UUID]) -> list[str]:
        scope: set[uuid.UUID] = set()
        for project_id in project_ids:
            scope.update(get_project_chain_ids(db, project_id))
        if not scope:
            return []
        names = db.scalars(select(distinct(name_column)).where(scope_column.in_(scope))).all()
        return sorted(names, key=str.casefold)

    return ReportField(
        key, label, select(name_column).where(id_column == foreign_key).scalar_subquery(), "text", domain=domain,
    )


def from_search(
    search: ArtefactSearchProvider, *fields: ReportField, search_fields: bool = True, math_fields: Iterable[str] = (),
) -> ReportFieldProvider:
    """A `ReportFieldProvider` over a type's search declaration.

    The joins, the current-version filter, the identity columns and the status labels come from the
    search provider, so they are written once. The search's text fields (already an opt-in, vetted
    list) are included unless `search_fields` is false.

    Args:
        search: The type's `ArtefactSearchProvider`.
        *fields: The typed fields on top (dates, enums, people, lookups).
        search_fields: Whether to include the search provider's own text fields.
        math_fields: Keys of those text fields people write equations in (`ReportField.math`).

    Returns:
        The provider.
    """
    math_keys = frozenset(math_fields)
    from_search_fields = (
        tuple(text_field(f.key, f.label, f.column, math=f.key in math_keys) for f in search.fields) if search_fields else ()
    )
    seen = {f.key for f in from_search_fields}
    extra = tuple(f for f in fields if f.key not in seen)
    return ReportFieldProvider(
        from_clause=search.from_clause,
        columns=search.columns,
        fields=from_search_fields + extra,
        where=search.where,
        status_labels=search.status_labels,
    )


def validate_provider(artefact_type: str, provider: ReportFieldProvider) -> list[str]:
    """Problems with a provider's declaration (empty when valid); used by the coverage test.

    Args:
        artefact_type: The type the provider is registered for.
        provider: The provider.

    Returns:
        Human-readable problems: a reserved or duplicate key, an unknown kind, a principal without
        its id column, an enum without labels.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for f in provider.fields:
        if f.key in RESERVED_FIELD_KEYS:
            problems.append(f"{artefact_type}.{f.key}: reserved key")
        if f.key in seen:
            problems.append(f"{artefact_type}.{f.key}: declared twice")
        seen.add(f.key)
        if f.kind not in REPORT_FIELD_KINDS:
            problems.append(f"{artefact_type}.{f.key}: unknown kind {f.kind!r}")
        if f.kind == "principal" and f.id_column is None:
            problems.append(f"{artefact_type}.{f.key}: principal field without id_column")
        if f.math and f.kind != "text":
            problems.append(f"{artefact_type}.{f.key}: only a text field can be math-capable")
        if f.kind == "enum" and not f.labels:
            problems.append(f"{artefact_type}.{f.key}: enum field without labels")
    return problems


# --- registry views ------------------------------------------------------------------------------


def provider_for(artefact_type: str) -> ReportFieldProvider:
    """The registered provider of `artefact_type`.

    Raises:
        UnknownReportFieldError: The type is not reportable (unregistered, or declared `not_reportable`).
    """
    provider = get_report_field_providers().get(artefact_type)
    if provider is None:
        raise UnknownReportFieldError(artefact_type)
    return provider


def field_catalogue(artefact_type: str) -> list[FieldInfo]:
    """The fields of a type for a picker: the reserved ones first, then the provider's own.

    Raises:
        UnknownReportFieldError: The type is not reportable.
    """
    provider = provider_for(artefact_type)
    reserved = [
        FieldInfo("code", "Code", "text", reserved=True),
        FieldInfo("title", "Title", "text", reserved=True),
        FieldInfo("status", "Status", "enum", reserved=True, choices=tuple(provider.status_labels.values())),
        FieldInfo("tags", "Tags", "text", reserved=True),
    ]
    own = [
        FieldInfo(f.key, f.label, f.kind, choices=tuple(f.labels.values()) if f.kind == "enum" else (), math=f.math)
        for f in provider.fields
    ]
    return reserved + own


def field_domain(db: Session, artefact_type: str, key: str, project_ids: Sequence[uuid.UUID]) -> list[str] | None:
    """The values a field can take, for a run-time variable's options.

    Args:
        db: Active session (read only).
        artefact_type: A reportable type.
        key: One of its fields (a reserved key too: `status` offers its labels).
        project_ids: The projects the report is for.

    Returns:
        The values in display form, or `None` when the field has no closed list (free text, a number, a date, a
        person), which then takes free input.

    Raises:
        UnknownReportFieldError: The type is not reportable, or `key` is not one of its fields.
    """
    provider = provider_for(artefact_type)
    if key == "status":
        return list(provider.status_labels.values())
    if key in RESERVED_FIELD_KEYS:  # code, title, tags: free text
        return None
    by_key = {f.key: f for f in provider.fields}
    if key not in by_key:
        raise UnknownReportFieldError(f"{artefact_type}.{key}")
    report_field = by_key[key]
    if report_field.kind == "enum":
        return list(report_field.labels.values())
    return report_field.domain(db, project_ids) if report_field.domain is not None else None


# --- loading and formatting ----------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """An enum member as its stored value; anything else unchanged."""
    return value.value if isinstance(value, enum.Enum) else value


def _label(labels: Mapping[str, str], value: Any) -> str:
    """The display label of a stored value; an unmapped value is humanised, never shown raw."""
    value = _plain(value)
    if value is None or value == "":
        return ""
    text = str(value)
    return labels.get(text, text.replace("_", " ").capitalize())


def _as_utc(value: datetime | None) -> datetime | None:
    """A naive datetime read as UTC, an aware one converted to it."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def load_records(
    db: Session,
    artefact_type: str,
    ids: Iterable[uuid.UUID],
    field_keys: Sequence[str] = (),
    *,
    with_tags: bool = False,
) -> dict[uuid.UUID, ReportRecord]:
    """Loads records of one type by id: one query for the records plus one each for people and tags.

    This does not authorise. Pass only ids the link graph's resolver showed the caller
    (`services.report_traversal`); an id that does not exist, or fails the provider's `where`, is
    simply absent from the result.

    Args:
        db: Active session (read only).
        artefact_type: A registered, reportable type.
        ids: The record ids.
        field_keys: The provider fields to read; reserved keys (`code`, `title`, `status`, `tags`)
            are always on the record and are ignored here.
        with_tags: Whether to fill `ReportRecord.tags`.

    Returns:
        `{id: ReportRecord}` for the records found.

    Raises:
        UnknownReportFieldError: The type is not reportable, or a key is not one of its fields.
    """
    provider = provider_for(artefact_type)
    by_key = {f.key: f for f in provider.fields}
    wanted: list[ReportField] = []
    for key in dict.fromkeys(k for k in field_keys if k not in RESERVED_FIELD_KEYS):
        if key not in by_key:
            raise UnknownReportFieldError(f"{artefact_type}.{key}")
        wanted.append(by_key[key])

    cols = provider.columns
    selected: list[Any] = [
        cols.id.label("_id"), cols.project_id.label("_project_id"), cols.code.label("_code"),
        cols.title.label("_title"), cols.status.label("_status"), cols.is_archived.label("_archived"),
        cols.updated_at.label("_updated"),
    ]
    if cols.organization_id is not None:
        selected.append(cols.organization_id.label("_org"))
    if cols.version is not None:
        selected.append(cols.version.label("_version"))
    for i, f in enumerate(wanted):
        selected.append(f.column.label(f"f{i}"))
        if f.id_column is not None:
            selected.append(f.id_column.label(f"f{i}_id"))

    id_list = list(dict.fromkeys(ids))
    rows: list[Any] = []
    for start in range(0, len(id_list), _CHUNK):
        chunk = id_list[start:start + _CHUNK]
        rows.extend(db.execute(
            select(*selected).select_from(provider.from_clause).where(cols.id.in_(chunk), *provider.where)
        ).all())

    people = principal_labels(db, [
        principal_ref(_plain(getattr(row, f"f{i}")), getattr(row, f"f{i}_id"))
        for row in rows for i, f in enumerate(wanted) if f.kind == "principal"
    ])

    out: dict[uuid.UUID, ReportRecord] = {}
    for row in rows:
        record = ReportRecord(
            artefact_type=artefact_type, id=row._id, project_id=row._project_id,
            organization_id=row._org if cols.organization_id is not None else None,
            unique_code=row._code or "", title=row._title or "",
            status=_label(provider.status_labels, row._status), is_archived=bool(row._archived),
            updated_at=_as_utc(row._updated), version=row._version if cols.version is not None else None,
        )
        for i, f in enumerate(wanted):
            raw = getattr(row, f"f{i}")
            if f.kind == "principal":
                ref = principal_ref(_plain(raw), getattr(row, f"f{i}_id"))
                record.values[f.key] = principal_text(people.get((ref.type.value, ref.id))) if ref else ""
            elif f.kind == "enum":
                record.values[f.key] = _label(f.labels, raw)
            elif f.kind == "instant":
                record.values[f.key] = _as_utc(raw)
            else:
                record.values[f.key] = _plain(raw)
        out[record.id] = record

    if with_tags and out:
        for rid, names in tag_names_for_records(db, artefact_type, list(out)).items():
            if rid in out:
                out[rid].tags = ", ".join(names)
    return out


def format_value(kind: str, value: Any) -> str:
    """A loaded value as report text.

    Args:
        kind: The field's kind.
        value: The value from `ReportRecord.values` (or a reserved field).

    Returns:
        Text: ISO `YYYY-MM-DD` for a date, ISO 8601 with `Z` for an instant, `Yes`/`No` for a flag, a
        number without a trailing `.0`; an empty field is the empty string.
    """
    if value is None or value == "":
        return ""
    if kind == "date" and isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if kind == "instant" and isinstance(value, datetime):
        utc = _as_utc(value)
        return "" if utc is None else utc.isoformat(timespec="seconds").replace("+00:00", "Z")
    if kind == "bool":
        return "Yes" if value else "No"
    if kind == "number" and isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


__all__ = [
    "RESERVED_FIELD_KEYS", "FieldInfo", "ReportRecord", "UnknownReportFieldError", "bool_field", "date_field",
    "enum_field", "field_catalogue", "field_domain", "format_value", "from_search", "instant_field", "load_records",
    "name_lookup_field", "number_field", "principal_field", "provider_for", "text_field", "validate_provider",
]
