"""
Module: schemas.requirement_type

Request and response bodies of the requirement type endpoints (`routers.requirement_types`): the generic typed-vocabulary
schemas (`schemas.type_vocabulary`) extended with the optional `rank`, the type's priority (a whole number from 1,
lower is higher; null is unranked, and on a project's override null follows the organisation's).
"""

from __future__ import annotations

from pydantic import Field

from app.schemas.type_vocabulary import (
    EffectiveTypeOut,
    OrgTypeCreate,
    OrgTypeOut,
    OrgTypeUpdate,
    ProjectTypeCreate,
    ProjectTypeOut,
    ProjectTypeOverrideUpdate,
)
from app.services.requirement_types import MAX_RANK


class RequirementTypeOrgCreate(OrgTypeCreate):
    """A new organisation type: its name and optional rank."""

    rank: int | None = Field(default=None, ge=1, le=MAX_RANK)


class RequirementTypeOrgUpdate(OrgTypeUpdate):
    """Partial change of an organisation type; `rank` null makes it unranked."""

    rank: int | None = Field(default=None, ge=1, le=MAX_RANK)


class RequirementTypeOrgOut(OrgTypeOut):
    """An organisation type."""

    rank: int | None = None


class RequirementTypeEffectiveOut(EffectiveTypeOut):
    """One type of a project's effective list; `rank` is the rank in effect here."""

    rank: int | None = None


class RequirementTypeProjectCreate(ProjectTypeCreate):
    """A type of a project's own."""

    rank: int | None = Field(default=None, ge=1, le=MAX_RANK)


class RequirementTypeProjectOverride(ProjectTypeOverrideUpdate):
    """Partial override of a type in one project; `rank` null follows the organisation's rank."""

    rank: int | None = Field(default=None, ge=1, le=MAX_RANK)


class RequirementTypeProjectOut(ProjectTypeOut):
    """A raw project type row (override or project-local)."""

    rank: int | None = None
