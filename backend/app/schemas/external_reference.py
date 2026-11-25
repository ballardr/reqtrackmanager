"""
Module: schemas.external_reference

Request and response bodies of the external system and external reference endpoints
(`routers.external_systems`, `routers.external_references`).

The system schemas extend the generic typed-vocabulary ones (`schemas.type_vocabulary`) with the optional
`url_template`; every link and template is checked as http(s) here and again in the service.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.external_reference import ExternalReferenceRole
from app.schemas.type_vocabulary import (
    EffectiveTypeOut,
    OrgTypeCreate,
    OrgTypeOut,
    OrgTypeUpdate,
    ProjectTypeCreate,
    ProjectTypeOut,
    ProjectTypeOverrideUpdate,
)
from app.services.external_references import (
    MAX_KEY_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_URL_LENGTH,
    ExternalReferenceOut,
    check_url_template,
    check_web_url,
)


class ExternalSystemOrgCreate(OrgTypeCreate):
    """A new organisation system: its name and optional link template (`https://tracker.example/browse/{key}`)."""

    url_template: str | None = Field(default=None, max_length=MAX_URL_LENGTH)

    _check_template = field_validator("url_template")(check_url_template)


class ExternalSystemOrgUpdate(OrgTypeUpdate):
    """Partial change of an organisation system; `url_template` null clears the template."""

    url_template: str | None = Field(default=None, max_length=MAX_URL_LENGTH)

    _check_template = field_validator("url_template")(check_url_template)


class ExternalSystemOrgOut(OrgTypeOut):
    """An organisation system."""

    url_template: str | None = None


class ExternalSystemEffectiveOut(EffectiveTypeOut):
    """One system of a project's effective list; `url_template` is the effective template."""

    url_template: str | None = None


class ExternalSystemProjectCreate(ProjectTypeCreate):
    """A system of a project's own."""

    url_template: str | None = Field(default=None, max_length=MAX_URL_LENGTH)

    _check_template = field_validator("url_template")(check_url_template)


class ExternalSystemProjectOverride(ProjectTypeOverrideUpdate):
    """Partial override of a system in one project; `url_template` null follows the organisation's template."""

    url_template: str | None = Field(default=None, max_length=MAX_URL_LENGTH)

    _check_template = field_validator("url_template")(check_url_template)


class ExternalSystemProjectOut(ProjectTypeOut):
    """A raw project system row (override or project-local)."""

    url_template: str | None = None


class ExternalReferenceIn(BaseModel):
    """A new reference: the system (an id from the record's tier's system list), the item's key and/or link, an
    optional note and role."""

    system_id: UUID
    key: str = Field(default="", max_length=MAX_KEY_LENGTH)
    url: str | None = Field(default=None, max_length=MAX_URL_LENGTH)
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH)
    role: ExternalReferenceRole | None = None

    _check_url = field_validator("url")(check_web_url)

    @model_validator(mode="after")
    def _needs_key_or_url(self) -> ExternalReferenceIn:
        if not self.key.strip() and not self.url:
            raise ValueError("A reference needs a key or a link.")
        return self


class ExternalReferenceUpdate(BaseModel):
    """Partial change of a reference: only fields present change (`url` or `role` null clears it)."""

    system_id: UUID | None = None
    key: str | None = Field(default=None, max_length=MAX_KEY_LENGTH)
    url: str | None = Field(default=None, max_length=MAX_URL_LENGTH)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    role: ExternalReferenceRole | None = None

    _check_url = field_validator("url")(check_web_url)


class SystemChoiceOut(BaseModel):
    """One system a record of this tier can be given a reference in."""

    id: UUID
    name: str
    url_template: str | None = None


class RecordReferencesOut(BaseModel):
    """A record's references with the picker data: whether the caller may change them and the systems to choose from."""

    references: list[ExternalReferenceOut]
    can_edit: bool
    systems: list[SystemChoiceOut]


class PageReferencesOut(BaseModel):
    """The references of the records a list page shows, by record id (records with none are absent)."""

    references: dict[UUID, list[ExternalReferenceOut]]


class ReferencedRecordOut(BaseModel):
    """A record found by an outside key, with the reference that matched."""

    artefact_type: str
    type_label: str
    id: UUID
    label: str
    status: str | None = None
    is_archived: bool = False
    project_id: UUID | None = None
    project_name: str | None = None
    project_code: str | None = None
    reference: ExternalReferenceOut


class ReferencedRecordsOut(BaseModel):
    """Records carrying the outside key; `truncated` when more matched than were returned."""

    records: list[ReferencedRecordOut]
    truncated: bool
