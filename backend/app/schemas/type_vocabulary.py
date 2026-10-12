"""
Module: schemas.type_vocabulary

Response/request schemas for a project's view of a two-tier type vocabulary
(`services.type_vocabulary.TypeVocabulary`), shared by every typed module
artefact's routers (Persona, Stakeholder, Risk): the org-level type CRUD, and a
project's merged effective list, creating a project-local type and overriding
an org type there.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class OrgTypeCreate(BaseModel):
    """Create payload for an org type."""
    name: str = Field(min_length=1, max_length=100)


class OrgTypeUpdate(BaseModel):
    """Partial update of an org type: rename and/or (de)activate."""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class OrgTypeOut(BaseModel):
    """An org-scoped org type definition (e.g. `PersonaTypeDefinition`) row."""

    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    name: str
    sort_order: int
    is_active: bool


class EffectiveTypeOut(BaseModel):
    """One row of a project's merged type list (`type_vocabulary.EffectiveType`)."""

    model_config = {"from_attributes": True}

    id: UUID
    name: str
    display_order: int
    is_enabled: bool
    source: str


class ProjectTypeCreate(BaseModel):
    """Create payload for a project-local type."""
    name: str = Field(min_length=1, max_length=100)
    display_order: int | None = None


class ProjectTypeOverrideUpdate(BaseModel):
    """Partial override of a type in one project: rename, reorder and/or enable/disable."""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    display_order: int | None = None
    is_enabled: bool | None = None


class ProjectTypeOut(BaseModel):
    """A raw project type row (override or project-local)."""

    model_config = {"from_attributes": True}

    id: UUID
    project_id: UUID
    org_type_id: UUID | None
    name_override: str | None
    display_order_override: int | None
    is_enabled: bool
