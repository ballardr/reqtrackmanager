"""
Module: schemas.search

Request and response shapes of the global search (`routers.search`).

The request is a POST body, not a query string, so the text searched for never appears in a
reverse-proxy access log (which is shipped to Loki).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequestIn(BaseModel):
    """A search.

    Attributes:
        q: Text to find (2 to 200 characters).
        scope: `"project"` (needs `project_id`), `"all"`, or `"<module>:<scope>:<ref id>"`.
        project_id: The project searched by `scope="project"`.
        organization_ids / project_ids: Narrow the projects searched.
        types: Narrow to record types (`"project"` is one).
        statuses: Narrow to status values.
        fields: Field keys to match; omitted uses the user's default search fields.
        match: `contains` (every word, any order) or `phrase`.
        include_archived: Include archived and retired records.
        updated_from / updated_to: Bounds on the last change (timezone-aware instants).
        sort: `relevance` or `updated`.
        include_organization_records: Whether a search of one project also covers its organisation's records
            (a shared Strategy). Omitted uses the person's preference, on unless they turned it off.
        limit / offset: The page; `offset + limit` may not exceed 500.
        counts: Compute per-type counts and the total (the live dropdown turns this off).
    """

    q: str = Field(max_length=400)
    scope: str = Field("all", max_length=120)
    project_id: UUID | None = None
    organization_ids: list[UUID] | None = Field(None, max_length=50)
    project_ids: list[UUID] | None = Field(None, max_length=500)
    types: list[str] | None = Field(None, max_length=60)
    statuses: list[str] | None = Field(None, max_length=60)
    fields: list[str] | None = Field(None, max_length=60)
    match: Literal["contains", "phrase"] = "contains"
    include_archived: bool = False
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    sort: Literal["relevance", "updated"] = "relevance"
    include_organization_records: bool | None = None
    limit: int = Field(25, ge=1, le=50)
    offset: int = Field(0, ge=0, le=500)
    counts: bool = True


class SearchSnippetOut(BaseModel):
    """The first matching field of a hit: windowed text and the `[start, end)` ranges to highlight."""

    field_key: str
    field_label: str
    text: str
    ranges: list[tuple[int, int]]


class SearchHitOut(BaseModel):
    """One result.

    Attributes:
        type / type_label: The artefact type (or `"project"`) and its display name.
        code: The record's own code (qualify it with `project_code` / `organization_code` for display).
        status / status_label: The status value and its display label.
        project_id / project_name / project_code: The owning project; `None` for an organisation-owned record.
        organization_id / organization_code: The owning organisation.
        open_type / open_id / open_project_id: The record whose page opens (a finding opens its
            engagement) and the project to open it in (for an organisation-owned record, the project
            it was found through).
        snippet: The first matching non-title field.
    """

    type: str
    type_label: str
    id: UUID
    code: str
    title: str
    status: str | None
    status_label: str | None
    is_archived: bool
    updated_at: datetime | None
    project_id: UUID | None
    project_name: str | None
    project_code: str | None
    organization_id: UUID | None
    organization_code: str | None
    open_type: str
    open_id: UUID
    open_project_id: UUID | None
    snippet: SearchSnippetOut | None


class SearchTypeCountOut(BaseModel):
    """Matches of one record type (`capped` when there are more than the depth limit)."""

    type: str
    label: str
    count: int
    capped: bool


class SearchNamedOut(BaseModel):
    """A type or status the response says was not searched, or can filter by."""

    key: str
    label: str


class SearchOrganizationOut(BaseModel):
    """An organisation the caller belongs to (the organisation filter shows only for more than one)."""

    id: UUID
    name: str
    code: str


class SearchResultOut(BaseModel):
    """A page of results and what the filters need.

    Attributes:
        total: Matches across the selected types, capped at 500; `None` when counts were not asked for.
        total_capped: More than 500 matched.
        type_counts: Matches per type before the type filter.
        fields_used: The field keys matched (echoed so the field picker shows what ran).
        not_searched: Types left out because they declare none of the selected fields.
        statuses: Status values and labels of the types searched.
        organizations: The caller's organisations.
        projects_truncated: The caller can open more projects than one search covers.
    """

    hits: list[SearchHitOut]
    total: int | None
    total_capped: bool
    type_counts: list[SearchTypeCountOut]
    fields_used: list[str]
    not_searched: list[SearchNamedOut]
    statuses: list[SearchNamedOut]
    organizations: list[SearchOrganizationOut]
    projects_truncated: bool


class SearchFieldOut(BaseModel):
    """A field the search can match: its key, label and the record types that carry it.

    `default_allowed` is false for a field that can be chosen for one search but never saved as a default
    (comments).
    """

    key: str
    label: str
    types: list[str]
    default_allowed: bool = True
