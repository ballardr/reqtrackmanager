"""
Module: schemas.tags

Request and response models for the tag API (`routers.tags`): a vocabulary, a record's tags, the
usage tables and bulk reclassification.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TagChipOut(BaseModel):
    """A tag as shown on a record."""

    id: uuid.UUID
    name: str
    colour: str | None = None


class TagOut(TagChipOut):
    """A vocabulary entry. `usage_count` is how many records carry it; `editable` is false for a
    tag the project only inherits from an ancestor."""

    usage_count: int = 0
    editable: bool = True


class VocabularyOut(BaseModel):
    """The tags a project (or the organisation) offers and how new names are treated."""

    mode: str = Field(description="`free` or `restricted`.")
    mode_inherited: bool = Field(description="True when the mode comes from an ancestor project, not this one.")
    inherited: bool = Field(description="True when the tags belong to an ancestor project.")
    has_parent: bool = Field(False, description="True when the project is nested under another (it may follow that project).")
    own_mode: str | None = Field(None, description="This project's own setting (`null` = inherit).")
    tags: list[TagOut]


class RecordTagsOut(BaseModel):
    """One record's tags plus what its tag picker needs."""

    tags: list[TagChipOut]
    can_edit: bool
    restricted: bool = Field(description="True when only listed tags can be applied.")
    suggestions: list[TagChipOut] = Field(description="The vocabulary the record's tags are chosen from.")


class RecordTagsSet(BaseModel):
    """Replaces a record's tags with these names."""

    tags: list[str] = Field(max_length=50)


class RecordTagAdd(BaseModel):
    """Adds one tag by name."""

    name: str


class TagCreate(BaseModel):
    """Adds a tag to the vocabulary."""

    name: str
    colour: str | None = None


class TagUpdate(BaseModel):
    """Renames a tag and/or sets its colour (`clear_colour` removes it)."""

    name: str | None = None
    colour: str | None = None
    clear_colour: bool = False


class TagMerge(BaseModel):
    """Merges the tag in the path into `into_tag_id`."""

    into_tag_id: uuid.UUID


class TagMergeOut(BaseModel):
    """How many records moved to the target tag."""

    records_moved: int


class TagDeleteOut(BaseModel):
    """How many records lost the deleted tag."""

    records_untagged: int


class TagModeSet(BaseModel):
    """`null` makes a project follow its nearest ancestor (an organisation must choose)."""

    mode: str | None = None


class UsageRowOut(BaseModel):
    """One tag's use on one kind of record."""

    tag_id: uuid.UUID
    name: str
    colour: str | None = None
    count: int
    last_used: datetime | None = None


class TypeUsageOut(BaseModel):
    """The tags used on one kind of record."""

    artefact_type: str
    label: str
    rows: list[UsageRowOut]


class TagUsageOut(BaseModel):
    """Tag x record-type usage; `unused` lists vocabulary tags nothing carries."""

    tables: list[TypeUsageOut]
    unused: list[TagChipOut]


class ReclassifyRecord(BaseModel):
    """One record chosen for a bulk tag change."""

    artefact_type: str
    artefact_id: uuid.UUID


class ReclassifyIn(BaseModel):
    """Which records to change and how. Choose records either by `from_tag_id` (every record
    carrying it, optionally only `artefact_types`) or by listing `records`."""

    from_tag_id: uuid.UUID | None = None
    artefact_types: list[str] | None = None
    records: list[ReclassifyRecord] | None = None
    add: list[uuid.UUID] = []
    remove: list[uuid.UUID] = []
    dry_run: bool = True


class ReclassifyOut(BaseModel):
    """What a reclassify did, or (when `dry_run`) would do."""

    matched: int
    added: int
    removed: int
    dry_run: bool


class TaggedRecordOut(BaseModel):
    """A record found by tag."""

    artefact_type: str
    type_label: str
    id: uuid.UUID
    label: str
    status: str | None = None
    is_archived: bool = False
    project_id: uuid.UUID | None = None
    # The owning project's name and code, for a record found in a related project of a widened scope.
    project_name: str | None = None
    project_code: str | None = None


class TaggedRecordsOut(BaseModel):
    """Records carrying the tags; `truncated` when more matched than were returned."""

    records: list[TaggedRecordOut]
    truncated: bool
