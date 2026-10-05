"""
Module: modules.stakeholders.enums

Enums for the Stakeholders & Personas module (docs/plans/module-02-
stakeholders-and-personas-plan.md).

Persona has its own scope/status enums rather than reusing another
module's: each artefact owns its vocabulary so a change to one lifecycle
never silently changes another's (the same reasoning Context & Strategy's
per-artefact enums follow).
"""

from __future__ import annotations

import enum


class PersonaScope(str, enum.Enum):
    """Which level a `Persona` row belongs to — exactly one of
    `organization_id`/`project_id` is set (Phase 0 resolution 2)."""

    ORGANIZATION = "organization"
    PROJECT = "project"


class PersonaStatus(str, enum.Enum):
    """Persona lifecycle (Phase 0 resolution 6): `Draft -> Active ->
    Retired`, with no approval gate because the source overview names no
    approver. `RETIRED -> ACTIVE` is allowed so a persona can be brought
    back without losing its history or scoring weight; see
    `service.PERSONA_ALLOWED_TRANSITIONS`."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"
