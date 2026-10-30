"""
Module: schemas.report_snippet

Request and response models for report snippets (`routers.report_layouts`, `services.report_snippets`): the list a
designer offers and the result of inserting one into a draft tree. Nothing here is stored.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReportSnippetChoiceOut(BaseModel):
    """One value a record-type parameter can take: its key and what it is called."""

    value: str
    label: str


class ReportSnippetParameterOut(BaseModel):
    """A choice the person makes on insert. `kind` is `image`, `record_type` or `text`; `choices` lists the record types."""

    key: str
    label: str
    kind: str
    help: str
    required: bool
    default: str | None = None
    max_length: int | None = None
    choices: list[ReportSnippetChoiceOut] = Field(default_factory=list)


class ReportSnippetOut(BaseModel):
    """A snippet a scope can use. `module_key` is `None` for a platform snippet; `formats` are where the result is true."""

    key: str
    name: str
    description: str
    category: str
    family: str
    formats: list[str]
    module_key: str | None = None
    parameters: list[ReportSnippetParameterOut]
    blocks: list[dict[str, Any]]


class ReportSnippetTarget(BaseModel):
    """Where to insert: a list of blocks (`nodes`, or `nodes[2].children`, `nodes[2].else_children`) and an index in it."""

    container: str = Field(default="nodes", max_length=200)
    index: int | None = Field(default=None, ge=0)


class ReportSnippetApply(BaseModel):
    """The draft tree, the parameter values by key and where to insert."""

    tree: dict[str, Any]
    parameters: dict[str, Any] = Field(default_factory=dict)
    target: ReportSnippetTarget = Field(default_factory=ReportSnippetTarget)


class ReportSnippetErrorOut(BaseModel):
    """Why an insertion was refused: `path` is in the resulting tree, or `parameters.<key>` / `target`."""

    path: str
    message: str


class ReportSnippetApplyOut(BaseModel):
    """The result of an insertion: the new tree (when `ok`), what changed, or the reasons it was refused."""

    ok: bool
    tree: dict[str, Any] | None = None
    changes: list[str] = Field(default_factory=list)
    errors: list[ReportSnippetErrorOut] = Field(default_factory=list)
    inserted_at: str | None = None
    count: int = 0
    problems_elsewhere: int = 0
