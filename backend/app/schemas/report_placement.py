"""
Module: schemas.report_placement

Request and response shapes of the report placement endpoints (`routers.report_placements`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReportPlacementSet(BaseModel):
    """Sets one scope's placement of a report. A field left out is unchanged; one sent as `null` clears this scope's
    override of it (both cleared removes the placement)."""

    report_key: str = Field(min_length=1, max_length=120)
    folder: str | None = Field(default=None, max_length=120)
    hidden: bool | None = None


class ReportPlacementOut(BaseModel):
    """One report a scope can place.

    Attributes:
        report_key: Its stable key.
        title / description / kind / group: What it is (`group` is its module, "Custom reports" or "Report packs").
        default_folder: Where it files with no placement.
        folder: Where it files now (this scope's override, else a parent's, else the default).
        folder_from: The tier that set the override, or `None` when the default applies.
        own_folder: This scope's own override (`None` = none; `""` = the top level).
        hidden / hidden_from / own_hidden: Whether it is left out of the picker, which tier said so, and this scope's own say.
        can_hide: Whether a placement may hide it (module and platform reports only).
    """

    report_key: str
    title: str
    description: str
    kind: Literal["report", "sheet", "pack"]
    group: str
    default_folder: str
    folder: str
    folder_from: Literal["project", "ancestor", "organization"] | None
    own_folder: str | None
    hidden: bool
    hidden_from: Literal["project", "ancestor", "organization"] | None
    own_hidden: bool | None
    can_hide: bool


class ReportPlacementResolvedOut(BaseModel):
    """The effective placement of one report in a scope (only reports with a placement are listed)."""

    report_key: str
    folder: str | None
    hidden: bool
