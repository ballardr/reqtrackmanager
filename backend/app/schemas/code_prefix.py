"""
Module: schemas.code_prefix

Request and response bodies of the record code prefix endpoints (`routers.code_prefixes`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CodePrefixSource = Literal["project", "parent_project", "organization", "default"]


class CodePrefixOut(BaseModel):
    """One record type's prefix in an organisation or a project.

    Attributes:
        artefact_type: The registered type string.
        label: The type's singular display name.
        default_prefix: The built-in prefix.
        own_prefix: The prefix this scope itself set; `None` when it follows the next tier.
        prefix: The prefix new records of the type are numbered with here.
        source: The tier that decided `prefix` (a parent project is named by tier only, so a child's
            administrator learns nothing about a project they may not see).
        inherited_prefix: The prefix this scope would use if it set none of its own (what clearing returns to).
        inherited_source: The tier that decides `inherited_prefix`.
    """

    artefact_type: str
    label: str
    default_prefix: str
    own_prefix: str | None
    prefix: str
    source: CodePrefixSource
    inherited_prefix: str
    inherited_source: CodePrefixSource


class CodePrefixUpdate(BaseModel):
    """Body of `PUT .../code-prefixes/{artefact_type}`. The shape rule is checked by the service, so a bad
    value gets its explanatory message rather than a generic length error."""

    model_config = ConfigDict(extra="forbid")

    prefix: str = Field(max_length=32)
