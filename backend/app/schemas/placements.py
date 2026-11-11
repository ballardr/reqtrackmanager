"""
Module: schemas.placements

Request and response models for the placement API (`routers.placements`): where one record sits in the
project's component/category tree.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.services.placements import MAX_PLACEMENTS_PER_RECORD


class PlacementIn(BaseModel):
    """One wanted placement: a component and, optionally, a category under it."""

    component_id: uuid.UUID
    category_id: uuid.UUID | None = None


class PlacementOut(PlacementIn):
    """A placement with the names to show."""

    component_name: str
    category_name: str | None = None


class RecordPlacementsOut(BaseModel):
    """One record's placements plus whether the caller may change them."""

    placements: list[PlacementOut]
    can_edit: bool
    managed_on_record: bool = Field(
        False, description="True when the record keeps its own component and category (a requirement), so a page shows them itself."
    )


class RecordPlacementsSet(BaseModel):
    """Replaces a record's placements with these."""

    placements: list[PlacementIn] = Field(max_length=MAX_PLACEMENTS_PER_RECORD)


class PagePlacementsOut(BaseModel):
    """The places of a page of records of one type, for a list's Components column."""

    placements: dict[uuid.UUID, list[PlacementOut]] = Field(
        description="`{record id: places}`; a record placed nowhere, or not visible to the caller, is absent."
    )
