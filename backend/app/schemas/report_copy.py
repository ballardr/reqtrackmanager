"""
Module: schemas.report_copy

Request and response shapes of copying reports between projects (`routers.report_copy`).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ReportCopyRequest(BaseModel):
    """What to copy into the project in the path.

    Attributes:
        source_project_id: The project copied from (same organisation).
        layout_ids / pack_ids: Layouts and packs the source project can reach.
        folders: Folder paths; those the source project added as folders are copied, any other name is ignored.
        placement_keys: Module or platform report keys (`report:<module>.<key>`) the source project places.
        favourites: Carry the caller's own favourites of the copied layouts and packs.
        on_conflict: `rename` ("Name (copy)") or `skip` for a name the target already owns; there is no replace.
        dry_run: Preview only: nothing is written.
    """

    source_project_id: UUID
    layout_ids: list[UUID] = Field(default_factory=list, max_length=100)
    pack_ids: list[UUID] = Field(default_factory=list, max_length=100)
    folders: list[str] = Field(default_factory=list, max_length=100)
    placement_keys: list[str] = Field(default_factory=list, max_length=100)
    favourites: bool = True
    on_conflict: Literal["rename", "skip"] = "rename"
    dry_run: bool = False


class ReportCopyItemOut(BaseModel):
    """One selected item and what the copy does (or did) with it."""

    kind: Literal["layout", "pack", "folder", "placement"]
    source_id: str
    name: str
    origin: str
    action: Literal["create", "rename", "skip", "exists", "left_out"]
    new_name: str
    warnings: list[str]
    new_id: UUID | None = None


class ReportCopyOut(BaseModel):
    """The plan (a dry run) or the result of a copy."""

    dry_run: bool
    target_project_id: UUID
    items: list[ReportCopyItemOut]
    warnings: list[str]
    favourites_carried: int


class ReportCopyTargetOut(BaseModel):
    """A project the caller may copy reports into."""

    id: UUID
    name: str
    parent_project_id: UUID | None = None
