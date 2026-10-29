"""
Module: schemas.report_folder

Request and response shapes of the report folder endpoints (`routers.report_folders`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReportFolderOut(BaseModel):
    """One folder a scope can file a report under. `own` is true when this scope can rename or delete it."""

    path: str
    own: bool


class ReportFolderAdd(BaseModel):
    """Adds a folder (a path of up to three levels, written `A/B`)."""

    path: str = Field(min_length=1, max_length=160)


class ReportFolderRename(BaseModel):
    """Renames the last level of `path` to `name`."""

    path: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=80)


class ReportFolderChangeOut(BaseModel):
    """The folders after a change, and what it moved (`path` is the renamed folder's new path, `null` for a delete)."""

    folders: list[ReportFolderOut]
    path: str | None = None
    layouts: int = 0
    packs: int = 0
    placements: int = 0
