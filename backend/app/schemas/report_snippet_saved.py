"""
Module: schemas.report_snippet_saved

Request and response models for author-saved report snippets (`routers.report_snippets`): saving a selection of a draft
layout, listing and managing the saved ones, copying, and hiding an inherited one. The insert flow (`GET .../snippets`,
`POST .../snippets/{key}/apply`) is in `schemas.report_snippet`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ReportSnippetSelection(BaseModel):
    """A run of blocks in a draft: `count` blocks from index `start` of the list `container` (`nodes`, `nodes[2].children`)."""

    container: str = Field(default="nodes", max_length=200)
    start: int = Field(ge=0)
    count: int = Field(default=1, ge=1)


class ReportSnippetCheck(BaseModel):
    """The draft tree and the selection to save, without the details."""

    tree: dict[str, Any]
    selection: ReportSnippetSelection


class ReportSnippetSave(ReportSnippetCheck):
    """Saves the selection as a snippet of the tier the route names."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=60)


class ReportSnippetCheckOut(BaseModel):
    """What saving the selection would store, or why it cannot be saved.

    Attributes:
        ok: Whether the selection can be saved at this tier.
        errors: The reasons it cannot (paths in the fragment, or `selection`).
        blocks: How many blocks (counting those inside containers) it holds.
        page_styles: The page styles it carries.
        variables: The variables it carries.
    """

    ok: bool
    errors: list[dict[str, str]] = Field(default_factory=list)
    blocks: int = 0
    page_styles: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)


class ReportSnippetUpdate(BaseModel):
    """Changes a saved snippet's details; a key left out is unchanged. Its blocks are saved again from a layout instead."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=60)


class ReportSnippetCopy(BaseModel):
    """Copies a saved snippet to this project (`project`) or up to the organisation (`organization`); `name` defaults to `<name> (copy)`."""

    target: Literal["project", "organization"] = "project"
    name: str | None = Field(default=None, min_length=1, max_length=200)


class ReportSnippetVisibilitySet(BaseModel):
    """Hides (`true`) or shows (`false`) an inherited saved snippet in a project."""

    hidden: bool


class ReportSnippetRestore(BaseModel):
    """Restores the named hidden snippets, or every one when `snippet_ids` is left out."""

    snippet_ids: list[UUID] | None = None


class ReportSnippetRestoreOut(BaseModel):
    """The snippets a restore showed again."""

    restored: list[UUID]


class SavedReportSnippetOut(BaseModel):
    """A saved snippet as one scope sees it.

    Attributes:
        key: The key it is inserted under (`GET .../snippets`).
        origin: `project`, `ancestor` or `organization`, from the asking scope.
        hidden: Hidden in the project asking (never for its own).
        editable: Whether the asking scope owns it (it can rename and delete it).
        blocks: How many blocks it inserts (counting those inside containers).
        page_styles: The page styles it adds to a layout.
        variables: The variables it adds to a layout.
    """

    id: UUID
    key: str
    organization_id: UUID
    project_id: UUID | None
    name: str
    description: str
    category: str
    family: str
    origin: Literal["project", "ancestor", "organization"]
    hidden: bool = False
    editable: bool = True
    blocks: int
    page_styles: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    updated_at: datetime


class SavedReportSnippetDetailOut(SavedReportSnippetOut):
    """A saved snippet with its fragment: `nodes` (the blocks it inserts) and `root` (the page styles and variables)."""

    nodes: list[dict[str, Any]]
    root: dict[str, Any]
