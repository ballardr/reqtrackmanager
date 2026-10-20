"""
Module: modules.stakeholders.enums

Enums for the Stakeholders & Personas module.

Persona, Stakeholder and Stakeholder Need each have their own status enums rather than
reusing another artefact's: each artefact owns its vocabulary so a change to
one lifecycle never silently changes another's (the same reasoning Context &
Strategy's per-artefact enums follow).
"""

from __future__ import annotations

import enum


class PersonaScope(str, enum.Enum):
    """Which level a `Persona` row belongs to — exactly one of
    `organization_id`/`project_id` is set."""

    ORGANIZATION = "organization"
    PROJECT = "project"


class PersonaStatus(str, enum.Enum):
    """Persona lifecycle: `Draft -> Active ->
    Retired`, with no approval gate because the requirement names no
    approver. `RETIRED -> ACTIVE` is allowed so a persona can be brought
    back without losing its history or scoring weight; see
    `service.PERSONA_ALLOWED_TRANSITIONS`."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class StakeholderScope(str, enum.Enum):
    """Which level a `Stakeholder` row belongs to — exactly one of
    `organization_id`/`project_id` is set."""

    ORGANIZATION = "organization"
    PROJECT = "project"


class StakeholderStatus(str, enum.Enum):
    """Stakeholder lifecycle: `Draft -> Active ->
    Retired`, no approval gate; `RETIRED -> ACTIVE` is allowed (see
    `service.STAKEHOLDER_ALLOWED_TRANSITIONS`)."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class TargetCadence(str, enum.Enum):
    """How often we aim to engage a stakeholder `ONE_OFF` is a value, not a flag; `ONE_OFF`
    and `AD_HOC` have no interval, so S4 staleness skips them.
    The values are the label keys of `types.ts`'s `TARGET_CADENCE_LABEL`."""

    ONE_OFF = "one_off"
    AD_HOC = "ad_hoc"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class NeedStatus(str, enum.Enum):
    """Stakeholder Need lifecycle: `Draft -> Active -> Retired`, no
    approval gate; `RETIRED -> ACTIVE` is allowed (see
    `service.NEED_ALLOWED_TRANSITIONS`). A Need has no scope enum: it is always
    project-scoped (see `models.StakeholderNeed`)."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class EngagementChannel(str, enum.Enum):
    """How an Engagement took place The
    values are the label keys of `types.ts`'s `ENGAGEMENT_CHANNEL_LABEL`."""

    EMAIL = "email"
    CALL = "call"
    MEETING = "meeting"
    WORKSHOP = "workshop"
    INTERVIEW = "interview"
    FOCUS_GROUP = "focus_group"
    USABILITY_TEST = "usability_test"
    SURVEY = "survey"
