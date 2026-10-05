"""
Module: modules.stakeholders.enums

Enums for the Stakeholders & Personas module (docs/plans/module-02-
stakeholders-and-personas-plan.md).

Persona and Stakeholder each have their own scope/status enums rather than
reusing another artefact's: each artefact owns its vocabulary so a change to
one lifecycle never silently changes another's (the same reasoning Context &
Strategy's per-artefact enums follow).
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


class StakeholderScope(str, enum.Enum):
    """Which level a `Stakeholder` row belongs to — exactly one of
    `organization_id`/`project_id` is set (Phase 0 resolution 2)."""

    ORGANIZATION = "organization"
    PROJECT = "project"


class StakeholderStatus(str, enum.Enum):
    """Stakeholder lifecycle (Phase 0 resolution 6): `Draft -> Active ->
    Retired`, no approval gate; `RETIRED -> ACTIVE` is allowed (see
    `service.STAKEHOLDER_ALLOWED_TRANSITIONS`)."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class TargetCadence(str, enum.Enum):
    """How often we aim to engage a stakeholder (Phase 0 addendum 2,
    resolution 18). `ONE_OFF` is a value, not a flag (resolution 19); `ONE_OFF`
    and `AD_HOC` have no interval, so S4 staleness skips them (resolution 19).
    The values are the label keys of `types.ts`'s `TARGET_CADENCE_LABEL`."""

    ONE_OFF = "one_off"
    AD_HOC = "ad_hoc"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
