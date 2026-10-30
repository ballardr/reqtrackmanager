"""
Module: schemas.report_file_name

Request and response shapes of the file name example endpoint (`routers.report_file_names`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FileNameExampleRequest(BaseModel):
    """A template to try.

    Attributes:
        template: The text (at most 400 characters; the saved limit is checked in the answer).
        kind: Where it will be set; decides which placeholders are allowed.
        variables: Names of the run-time variables the place declares.
        extension: The extension to show.
    """

    template: str = Field(max_length=400)
    kind: Literal["layout", "pack", "entry", "organization"] = "layout"
    variables: list[str] = Field(default_factory=list, max_length=50)
    extension: Literal["pdf", "docx", "odt", "html", "csv", "xlsx", "ods", "zip"] = "pdf"


class FileNameExampleOut(BaseModel):
    """The answer: the example file name (null when empty or invalid) and every problem."""

    example: str | None
    problems: list[str]
    #: What the template may use here, ready to insert: `{{report_title}}`, `{{var.team}}` ...
    placeholders: list[str]
