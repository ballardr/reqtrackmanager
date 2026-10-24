"""
Module: schemas.record_policy

Request and response shapes for the personal-data policy of record export and import
(`services.record_policy`): the server default per sensitivity tag and the organisation's override.
"""

from __future__ import annotations

from pydantic import BaseModel


class ServerSensitivityOut(BaseModel):
    """The server default for one sensitivity tag.

    Attributes:
        tag: A sensitivity tag (`personal`, `contact` or `free_text_people`).
        allowed: Whether columns with the tag may leave and enter by default (`False` until an administrator opts in).
    """

    tag: str
    allowed: bool


class ServerSensitivityUpdate(BaseModel):
    """Sets the server default for a tag.

    Attributes:
        allowed: The new default.
    """

    allowed: bool


class OrgSensitivityOut(BaseModel):
    """One tag as an organisation sees it.

    Attributes:
        tag: A sensitivity tag.
        server_allowed: The server default the organisation inherits.
        override: The organisation's own decision, or `None` when it follows the server.
        effective: What applies in the organisation.
    """

    tag: str
    server_allowed: bool
    override: bool | None
    effective: bool


class OrgSensitivityUpdate(BaseModel):
    """Sets or clears the organisation's override for a tag.

    Attributes:
        allowed: The override, or `None` to follow the server default again.
    """

    allowed: bool | None
