"""
Module: schemas.report_exchange

Request and response shapes of exporting and importing report layouts and packs as a file (`routers.report_exchange`).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ReportFileExportRequest(BaseModel):
    """What goes into the file.

    Attributes:
        layout_ids / pack_ids: Layouts and packs the tier can reach (at least one of either).
        include_history: Every published version instead of the current one.
        include_pack_layouts: Also export the layouts the chosen packs name.
    """

    layout_ids: list[UUID] = Field(default_factory=list, max_length=100)
    pack_ids: list[UUID] = Field(default_factory=list, max_length=100)
    include_history: bool = False
    include_pack_layouts: bool = True


class ReportFileItemOut(BaseModel):
    """One layout or pack in the file and what the import does (or did) with it."""

    kind: Literal["layout", "pack"]
    name: str
    new_name: str
    action: Literal["create", "rename", "skip", "left_out"]
    versions: int
    warnings: list[str]
    new_id: UUID | None = None


class ReportFileImportOut(BaseModel):
    """The preview (`dry_run`) or the result of an import."""

    dry_run: bool
    items: list[ReportFileItemOut]
    pictures: int
    warnings: list[str]
