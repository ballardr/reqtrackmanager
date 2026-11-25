"""
Module: modules.traceability.profiles

Changes to governance profiles: an organisation's profiles, the projects each reaches, the projects exempt from an
Enforced profile and each project's opt-in or opt-out.

Responsibilities:
- Create, rename, change the mode of and delete a profile; replace its targets; add and remove exemptions
  (organisation scope).
- Record a project's choice about a profile (project scope).
- List the kinds of policy a profile owns through the registered `ProfileContributor`s, with their row counts.
- Validate every input against the organisation and the profile's mode, and write one audit event per change (keys,
  modes and counts, never policy content).

Design decisions:
- Functions flush and never commit; the router commits so a request is one transaction.
- An Enforced profile takes no choices and a Default or Opt-in profile takes no exemptions: the stricter reading of "who
  may lift it" is stated in one place, so no path lets a project relax what the organisation enforces. Rows left from
  an earlier mode are kept and ignored (`profile_resolution`).
- A profile is deleted by deleting its row; its targets, exemptions, choices and policy rows go with it through
  `ON DELETE CASCADE`.
- Names are unique within an organisation ignoring case, so the project's and the bundle's lookup by name is unambiguous.

Dependencies: `modules.traceability.models`, `modules.registry` (contributors and availability), `services.audit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.modules import registry
from app.modules.seams import ProfileContributor
from app.modules.traceability.enums import ProfileMode, ProfileOutcome, ProfileTargetKind
from app.modules.traceability.models import (
    EXEMPTION_REASON_MAX_LENGTH,
    PROFILE_DESCRIPTION_MAX_LENGTH,
    PROFILE_NAME_MAX_LENGTH,
    GovernanceProfile,
    GovernanceProfileChoice,
    GovernanceProfileExemption,
    GovernanceProfileTarget,
)
from app.modules.traceability.profile_resolution import outcome_for, rows_for_project
from app.services.audit import log_event

AUDIT_ENTITY_TYPE = "governance_profile"


@dataclass(frozen=True)
class TargetSpec:
    """One project a `selected_projects` profile reaches.

    Attributes:
        project_id: The targeted project.
        include_children: Whether its nested child projects are reached too.
    """

    project_id: uuid.UUID
    include_children: bool = False


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _clean_name(name: str) -> str:
    """The trimmed name.

    Raises:
        HTTPException: 422 when it is empty or longer than the limit.
    """
    cleaned = name.strip()
    if not cleaned or len(cleaned) > PROFILE_NAME_MAX_LENGTH:
        raise _unprocessable(f"A profile name needs between 1 and {PROFILE_NAME_MAX_LENGTH} characters.")
    return cleaned


def _clean_description(description: str) -> str:
    """The trimmed description.

    Raises:
        HTTPException: 422 when it is longer than the limit.
    """
    cleaned = description.strip()
    if len(cleaned) > PROFILE_DESCRIPTION_MAX_LENGTH:
        raise _unprocessable(f"A description has at most {PROFILE_DESCRIPTION_MAX_LENGTH} characters.")
    return cleaned


def _require_unique_name(db: Session, organization_id: uuid.UUID, name: str, *, except_id: uuid.UUID | None = None) -> None:
    """Raises 409 when another profile of the organisation has the name, ignoring case."""
    query = select(GovernanceProfile.id).where(
        GovernanceProfile.organization_id == organization_id, func.lower(GovernanceProfile.name) == name.lower()
    )
    if except_id is not None:
        query = query.where(GovernanceProfile.id != except_id)
    if db.scalar(query) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A profile with this name already exists.")


def _project_in_org(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    """The project, when it belongs to the organisation.

    Raises:
        HTTPException: 422 when it does not exist or belongs to another organisation.
    """
    project = db.get(Project, project_id)
    if project is None or project.organization_id != organization_id:
        raise _unprocessable("The project does not belong to this organisation.")
    return project


def _mode(value: str) -> ProfileMode:
    try:
        return ProfileMode(value)
    except ValueError:
        raise _unprocessable("The mode must be enforced, default or opt_in.") from None


def _target_kind(value: str) -> ProfileTargetKind:
    try:
        return ProfileTargetKind(value)
    except ValueError:
        raise _unprocessable("The target must be all_projects or selected_projects.") from None


def create_profile(
    db: Session, *, organization: Organization, name: str, description: str, mode: str, target_kind: str,
    targets: Sequence[TargetSpec], actor_id: uuid.UUID,
) -> GovernanceProfile:
    """Creates a profile.

    Args:
        db: Active session (not committed).
        organization: The owning organisation.
        name: Unique within the organisation, ignoring case.
        description: A short summary.
        mode: A `ProfileMode` value.
        target_kind: A `ProfileTargetKind` value.
        targets: The reached projects of a `selected_projects` profile; ignored for `all_projects`.
        actor_id: The acting user.

    Returns:
        The new profile.

    Raises:
        HTTPException: 409 duplicate name; 422 an invalid name, description, mode or target, or a project of another
            organisation.
    """
    cleaned = _clean_name(name)
    _require_unique_name(db, organization.id, cleaned)
    profile = GovernanceProfile(
        organization_id=organization.id, name=cleaned, description=_clean_description(description),
        mode=_mode(mode).value, target_kind=_target_kind(target_kind).value,
    )
    db.add(profile)
    db.flush()
    _replace_targets(db, profile, targets)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="created", actor_id=actor_id,
        organization_id=organization.id,
        detail={"name": profile.name, "mode": profile.mode, "target_kind": profile.target_kind},
    )
    return profile


def update_profile(
    db: Session, *, profile: GovernanceProfile, name: str | None, description: str | None, mode: str | None,
    actor_id: uuid.UUID,
) -> GovernanceProfile:
    """Renames a profile, changes its description or changes its mode; `None` leaves a field as it is.

    A mode change keeps the exemptions and choices already recorded: those that no longer apply to the new mode are
    ignored until the mode changes back.

    Raises:
        HTTPException: 409 duplicate name; 422 an invalid value.
    """
    changed: dict[str, str] = {}
    if name is not None and name.strip() != profile.name:
        cleaned = _clean_name(name)
        _require_unique_name(db, profile.organization_id, cleaned, except_id=profile.id)
        changed["name"] = cleaned
        profile.name = cleaned
    if description is not None and description.strip() != profile.description:
        profile.description = _clean_description(description)
        changed["description"] = "changed"
    if mode is not None and mode != profile.mode:
        changed["mode_from"] = profile.mode
        profile.mode = _mode(mode).value
        changed["mode_to"] = profile.mode
    if changed:
        db.flush()
        log_event(
            db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="updated", actor_id=actor_id,
            organization_id=profile.organization_id, detail=changed,
        )
    return profile


def _replace_targets(db: Session, profile: GovernanceProfile, targets: Sequence[TargetSpec]) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Makes the profile's target rows equal `targets` (none for `all_projects`); returns the project ids added and
    removed. A repeated project keeps its last entry."""
    wanted: dict[uuid.UUID, bool] = {}
    if profile.target_kind == ProfileTargetKind.SELECTED_PROJECTS.value:
        for spec in targets:
            _project_in_org(db, profile.organization_id, spec.project_id)
            wanted[spec.project_id] = spec.include_children
    existing = {t.project_id: t for t in db.scalars(select(GovernanceProfileTarget).where(GovernanceProfileTarget.profile_id == profile.id))}
    for project_id, row in existing.items():
        if project_id not in wanted:
            db.delete(row)
        else:
            row.include_children = wanted[project_id]
    for project_id, include_children in wanted.items():
        if project_id not in existing:
            db.add(GovernanceProfileTarget(profile_id=profile.id, project_id=project_id, include_children=include_children))
    db.flush()
    return set(wanted) - set(existing), set(existing) - set(wanted)


def set_targets(
    db: Session, *, profile: GovernanceProfile, target_kind: str, targets: Sequence[TargetSpec], actor_id: uuid.UUID,
) -> None:
    """Replaces the projects a profile reaches.

    Args:
        db: Active session (not committed).
        profile: The profile.
        target_kind: A `ProfileTargetKind` value; `all_projects` removes the listed targets.
        targets: The projects of a `selected_projects` profile (each optionally with its children).
        actor_id: The acting user.

    Raises:
        HTTPException: 422 an invalid target kind or a project of another organisation.
    """
    profile.target_kind = _target_kind(target_kind).value
    added, removed = _replace_targets(db, profile, targets)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="targets_set", actor_id=actor_id,
        organization_id=profile.organization_id,
        detail={
            "target_kind": profile.target_kind, "added_project_ids": sorted(str(i) for i in added),
            "removed_project_ids": sorted(str(i) for i in removed),
        },
    )


def delete_profile(db: Session, *, profile: GovernanceProfile, actor_id: uuid.UUID) -> None:
    """Deletes a profile with its targets, exemptions, choices and policy rows."""
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="deleted", actor_id=actor_id,
        organization_id=profile.organization_id, detail={"name": profile.name, "mode": profile.mode},
    )
    db.delete(profile)
    db.flush()


def add_exemption(
    db: Session, *, profile: GovernanceProfile, project_id: uuid.UUID, include_children: bool, reason: str,
    actor_id: uuid.UUID,
) -> GovernanceProfileExemption:
    """Exempts a project (optionally with its nested children) from an Enforced profile, or updates the exemption.

    Raises:
        HTTPException: 409 when the profile is not Enforced; 422 a project of another organisation or a reason longer
            than the limit.
    """
    if profile.mode != ProfileMode.ENFORCED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an Enforced profile has exemptions.")
    project = _project_in_org(db, profile.organization_id, project_id)
    cleaned = reason.strip()
    if len(cleaned) > EXEMPTION_REASON_MAX_LENGTH:
        raise _unprocessable(f"A reason has at most {EXEMPTION_REASON_MAX_LENGTH} characters.")
    row = db.scalar(
        select(GovernanceProfileExemption).where(
            GovernanceProfileExemption.profile_id == profile.id, GovernanceProfileExemption.project_id == project.id
        )
    )
    if row is None:
        row = GovernanceProfileExemption(
            profile_id=profile.id, project_id=project.id, include_children=include_children, reason=cleaned
        )
        db.add(row)
    else:
        row.include_children = include_children
        row.reason = cleaned
    db.flush()
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="exemption_added", actor_id=actor_id,
        organization_id=profile.organization_id, project_id=project.id, detail={"include_children": include_children},
    )
    return row


def remove_exemption(db: Session, *, profile: GovernanceProfile, project_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Removes a project's exemption from a profile.

    Raises:
        HTTPException: 404 when the project has no exemption from the profile.
    """
    row = db.scalar(
        select(GovernanceProfileExemption).where(
            GovernanceProfileExemption.profile_id == profile.id, GovernanceProfileExemption.project_id == project_id
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That project has no exemption from this profile.")
    db.delete(row)
    db.flush()
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="exemption_removed", actor_id=actor_id,
        organization_id=profile.organization_id, project_id=project_id, detail={},
    )


def set_choice(
    db: Session, *, profile: GovernanceProfile, project: Project, opted_in: bool | None, actor_id: uuid.UUID,
    require_reach: bool = True,
) -> None:
    """Records a project's choice about a profile, or clears it.

    A Default profile takes an opt-out (`False`) and an Opt-in profile takes an opt-in (`True`); `None` clears the
    project's choice and returns it to the profile's own behaviour.

    Args:
        db: Active session (not committed).
        profile: The profile.
        project: The choosing project.
        opted_in: The choice, or `None` to clear it.
        actor_id: The acting user.
        require_reach: Whether the profile must already reach the project. A bundle import passes `False` because the
            targets of a profile are written after the projects exist; a choice for a project the profile does not reach
            is ignored when policy is resolved.

    Raises:
        HTTPException: 409 when the profile is Enforced or (with `require_reach`) does not reach the project; 422 a
            project of another organisation or a choice the profile's mode does not take.
    """
    if project.organization_id != profile.organization_id:
        raise _unprocessable("The project does not belong to this organisation.")
    if profile.mode == ProfileMode.ENFORCED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An Enforced profile applies to every project it reaches. An organisation administrator can exempt a project.",
        )
    if require_reach:
        rows, ancestors = rows_for_project(db, project)
        if outcome_for(rows, profile, project.id, ancestors) is ProfileOutcome.NOT_TARGETED:
            raise HTTPException(status.HTTP_409_CONFLICT, "This profile does not reach the project.")
    row = db.scalar(
        select(GovernanceProfileChoice).where(
            GovernanceProfileChoice.profile_id == profile.id, GovernanceProfileChoice.project_id == project.id
        )
    )
    if opted_in is None:
        if row is not None:
            db.delete(row)
            db.flush()
        action = "choice_cleared"
    else:
        expected = profile.mode == ProfileMode.OPT_IN.value
        if opted_in != expected:
            raise _unprocessable(
                "An Opt-in profile takes an opt-in." if expected else "A Default profile takes an opt-out."
            )
        if row is None:
            db.add(GovernanceProfileChoice(profile_id=profile.id, project_id=project.id, opted_in=opted_in))
        else:
            row.opted_in = opted_in
        db.flush()
        action = "choice_set"
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action=action, actor_id=actor_id,
        organization_id=profile.organization_id, project_id=project.id, detail={"opted_in": opted_in},
    )


def contributors_for_organization(db: Session, organization_id: uuid.UUID) -> list[tuple[str, ProfileContributor]]:
    """The policy kinds profiles can own that are in effect for the organisation, as `("<module_key>:<key>",
    contributor)` in registry order. A kind whose sub-component is off is left out of the screens; its rows are kept."""
    return [
        (f"{module_key}:{contributor.key}", contributor)
        for module_key, contributor in registry.get_profile_contributors()
        if (
            registry.is_module_enabled(db, organization_id, module_key)
            if contributor.sub_component is None
            else registry.is_org_module_subcomponent_enabled(db, organization_id, module_key, contributor.sub_component)
        )
    ]


def contribution_counts(db: Session, organization_id: uuid.UUID, profile_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[tuple[str, str, int]]]:
    """For each profile, `(namespaced key, name, row count)` of every policy kind in effect for the organisation."""
    out: dict[uuid.UUID, list[tuple[str, str, int]]] = {pid: [] for pid in profile_ids}
    if not profile_ids:
        return out
    for key, contributor in contributors_for_organization(db, organization_id):
        counts = contributor.count_rows(db, profile_ids)
        for pid in profile_ids:
            out[pid].append((key, contributor.name, counts.get(pid, 0)))
    return out


def find_profile_by_name(db: Session, organization_id: uuid.UUID, name: str) -> GovernanceProfile | None:
    """The organisation's profile with this name, ignoring case, or `None`."""
    return db.scalar(
        select(GovernanceProfile).where(
            GovernanceProfile.organization_id == organization_id, func.lower(GovernanceProfile.name) == name.strip().lower()
        )
    )

