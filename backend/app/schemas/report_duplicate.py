"""
Module: schemas.report_duplicate

Request and response shapes of duplicating one report layout or pack (`routers.report_duplicate`).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ReportDuplicateRequest(BaseModel):
    """What to duplicate and where the copy goes.

    Attributes:
        kind: `layout`, `pack` or a built-in `starter` layout.
        source_id: The layout or pack (required for those kinds).
        starter_key: The starter's key (required for `starter`, from `GET .../starters`).
        target: `project` (the project in the path) or `organization` (copy up; needs the organisation-level right).
        name: The copy's name; the first free "<name> (copy)" when empty.
        dry_run: Plan only: nothing is written.
    """

    kind: Literal["layout", "pack", "starter"]
    source_id: UUID | None = None
    starter_key: str | None = Field(default=None, max_length=100)
    target: Literal["project", "organization"] = "project"
    name: str | None = Field(default=None, max_length=200)
    dry_run: bool = False


class ReportDuplicateOut(BaseModel):
    """The plan of a duplicate, or its result (`new_id` set once applied)."""

    dry_run: bool
    kind: Literal["layout", "pack", "starter"]
    source_name: str
    origin: str
    name: str
    suggested_name: str
    name_taken: bool
    shadows: bool
    folder: str
    warnings: list[str]
    blocked_images: list[str]
    new_id: UUID | None = None
    target: Literal["project", "organization"]
    organization_id: UUID


class ReportStarterOut(BaseModel):
    """One built-in starter layout a person can start from."""

    key: str
    name: str
    description: str
    orientation: str
