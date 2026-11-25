"""
Module: modules.traceability.profile_resolution

Works out what each governance profile of an organisation does for a project: whether it reaches the project, binds it,
applies by default, is opted out of, is opted in to or is merely offered.

Responsibilities:
- `outcome_for`: the one rule turning a profile, its targets, exemptions and the project's choice into a
  `ProfileOutcome`.
- `applicable_profiles`: the profiles whose policy applies to a project, in precedence order (Enforced, then Default,
  then opted-in), for the policy resolvers of the later parts to read.
- `project_profile_states`: every profile of the project's organisation with its outcome, for the project's view.
- `profile_impact`: one profile's outcome for every project of the organisation, for the organisation's view.

Design decisions:
- Policy resolution order (Enforced profiles, then the project's own Default and opted-in profiles, then its own rows,
  then the nearest ancestor project's, then the built-in default) is applied by each policy kind's resolver; this file
  gives the first two tiers and the order within them. Within a tier profiles are ordered by name and then id, so the
  order is stable; where two profiles set the same policy the kind states its own merge rule.
- Reach down the project tree is the target's or exemption's `include_children`; a project's choice never covers its
  children (see `models`).
- Reads load a profile's rows in bulk, never per project or per row, so an organisation-wide view costs a fixed number
  of statements. A single project's resolution reads only the rows that mention the project or its ancestors.
- A profile whose stored mode no longer matches an old choice or exemption ignores the stale row.

Dependencies: `modules.traceability.models`, `services.project_hierarchy` (ancestor chain).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.traceability.enums import ProfileMode, ProfileOutcome, ProfileTargetKind
from app.modules.traceability.models import (
    GovernanceProfile,
    GovernanceProfileChoice,
    GovernanceProfileExemption,
    GovernanceProfileTarget,
)
from app.services.project_hierarchy import get_project_chain_ids

_TIER = {ProfileOutcome.ENFORCED: 0, ProfileOutcome.DEFAULT: 1, ProfileOutcome.OPTED_IN: 2}
_ANCESTOR_WALK_CAP = 5000


@dataclass(frozen=True)
class ProfileState:
    """One profile's effect on one project.

    Attributes:
        profile: The profile.
        outcome: What it does for the project.
        choice: The project's stored choice (`opted_in`), or `None` when it has none.
    """

    profile: GovernanceProfile
    outcome: ProfileOutcome
    choice: bool | None


@dataclass(frozen=True)
class AppliedProfile:
    """A profile whose policy applies to a project.

    Attributes:
        profile_id: The profile.
        name: Its name, for naming the winning source in the UI.
        mode: Its `ProfileMode` value.
        outcome: `enforced`, `default` or `opted_in`.
    """

    profile_id: uuid.UUID
    name: str
    mode: str
    outcome: ProfileOutcome


class ProfileRows:
    """The targets, exemptions and choices of a set of profiles, indexed for `outcome_for`.

    Attributes:
        profiles: The profiles, ordered by name.
        targets: Each profile's targets.
        exemptions: Each profile's exemptions.
        choices: Each `(profile, project)` choice (`opted_in`).
    """

    def __init__(
        self, profiles: Sequence[GovernanceProfile], targets: Sequence[GovernanceProfileTarget],
        exemptions: Sequence[GovernanceProfileExemption], choices: Sequence[GovernanceProfileChoice],
    ) -> None:
        self.profiles = list(profiles)
        self.targets: dict[uuid.UUID, list[GovernanceProfileTarget]] = defaultdict(list)
        self.exemptions: dict[uuid.UUID, list[GovernanceProfileExemption]] = defaultdict(list)
        self.choices: dict[tuple[uuid.UUID, uuid.UUID], bool] = {}
        for target in targets:
            self.targets[target.profile_id].append(target)
        for exemption in exemptions:
            self.exemptions[exemption.profile_id].append(exemption)
        for choice in choices:
            self.choices[(choice.profile_id, choice.project_id)] = choice.opted_in


def _covers(
    rows: Sequence[GovernanceProfileTarget] | Sequence[GovernanceProfileExemption], project_id: uuid.UUID,
    ancestors: Collection[uuid.UUID],
) -> bool:
    """Whether a row names the project, or names an ancestor and reaches its children."""
    return any(row.project_id == project_id or (row.include_children and row.project_id in ancestors) for row in rows)


def outcome_for(rows: ProfileRows, profile: GovernanceProfile, project_id: uuid.UUID, ancestors: Collection[uuid.UUID]) -> ProfileOutcome:
    """What `profile` does for the project.

    Args:
        rows: The loaded rows of the profile (and others).
        profile: The profile.
        project_id: The project.
        ancestors: The project's ancestors (not the project itself).

    Returns:
        `NOT_TARGETED` when the profile does not reach the project; for an Enforced profile `EXEMPT` or `ENFORCED`; for a
        Default profile `OPTED_OUT` or `DEFAULT`; for an Opt-in profile `OPTED_IN` or `AVAILABLE`.
    """
    if profile.target_kind != ProfileTargetKind.ALL_PROJECTS.value and not _covers(
        rows.targets.get(profile.id, ()), project_id, ancestors
    ):
        return ProfileOutcome.NOT_TARGETED
    if profile.mode == ProfileMode.ENFORCED.value:
        return ProfileOutcome.EXEMPT if _covers(rows.exemptions.get(profile.id, ()), project_id, ancestors) else ProfileOutcome.ENFORCED
    choice = rows.choices.get((profile.id, project_id))
    if profile.mode == ProfileMode.DEFAULT.value:
        return ProfileOutcome.OPTED_OUT if choice is False else ProfileOutcome.DEFAULT
    return ProfileOutcome.OPTED_IN if choice is True else ProfileOutcome.AVAILABLE


def _load_rows(
    db: Session, organization_id: uuid.UUID, *, profile_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None,
    chain: Sequence[uuid.UUID] = (),
) -> ProfileRows:
    """Loads the organisation's profiles with their rows, narrowed to one profile or to the rows that mention one
    project (its own and, for targets and exemptions, its ancestors')."""
    profile_query = select(GovernanceProfile).where(GovernanceProfile.organization_id == organization_id)
    if profile_id is not None:
        profile_query = profile_query.where(GovernanceProfile.id == profile_id)
    profiles = list(db.scalars(profile_query.order_by(GovernanceProfile.name, GovernanceProfile.id)))
    if not profiles:
        return ProfileRows([], [], [], [])
    ids = [p.id for p in profiles]
    target_query = select(GovernanceProfileTarget).where(GovernanceProfileTarget.profile_id.in_(ids))
    exemption_query = select(GovernanceProfileExemption).where(GovernanceProfileExemption.profile_id.in_(ids))
    choice_query = select(GovernanceProfileChoice).where(GovernanceProfileChoice.profile_id.in_(ids))
    if project_id is not None:
        target_query = target_query.where(GovernanceProfileTarget.project_id.in_(chain))
        exemption_query = exemption_query.where(GovernanceProfileExemption.project_id.in_(chain))
        choice_query = choice_query.where(GovernanceProfileChoice.project_id == project_id)
    return ProfileRows(profiles, list(db.scalars(target_query)), list(db.scalars(exemption_query)), list(db.scalars(choice_query)))


def rows_for_project(db: Session, project: Project) -> tuple[ProfileRows, list[uuid.UUID]]:
    """The profiles with the rows that mention one project or its ancestors, and those ancestors (nearest first, without
    the project itself)."""
    chain = get_project_chain_ids(db, project.id)
    return _load_rows(db, project.organization_id, project_id=project.id, chain=chain), chain[1:]


def project_profile_states(db: Session, project: Project) -> list[ProfileState]:
    """Every profile of the project's organisation with what it does for the project.

    Args:
        db: An active session.
        project: The project.

    Returns:
        One `ProfileState` per profile, ordered by profile name. Profiles that do not reach the project are included
        (`NOT_TARGETED`) so a caller decides whether to show them.
    """
    rows, ancestors = rows_for_project(db, project)
    return [
        ProfileState(
            profile=p, outcome=outcome_for(rows, p, project.id, ancestors), choice=rows.choices.get((p.id, project.id)),
        )
        for p in rows.profiles
    ]


def applicable_profiles(db: Session, project_id: uuid.UUID) -> list[AppliedProfile]:
    """The profiles whose policy applies to the project, in precedence order.

    Args:
        db: An active session.
        project_id: The project.

    Returns:
        Enforced profiles first, then Default profiles the project has not opted out of, then Opt-in profiles it chose,
        each tier ordered by name. Empty when the project does not exist or no profile applies.
    """
    project = db.get(Project, project_id)
    if project is None:
        return []
    rows, ancestors = rows_for_project(db, project)
    applied = [
        AppliedProfile(profile_id=p.id, name=p.name, mode=p.mode, outcome=outcome)
        for p in rows.profiles
        if (outcome := outcome_for(rows, p, project.id, ancestors)).applies
    ]
    return sorted(applied, key=lambda a: (_TIER[a.outcome], a.name.casefold(), str(a.profile_id)))


def _ancestors_by_project(db: Session, organization_id: uuid.UUID) -> tuple[dict[uuid.UUID, Project], dict[uuid.UUID, frozenset[uuid.UUID]]]:
    """Every project of the organisation with each one's ancestors, from one read of the tree (cycle-safe)."""
    projects = {p.id: p for p in db.scalars(select(Project).where(Project.organization_id == organization_id))}
    ancestors: dict[uuid.UUID, frozenset[uuid.UUID]] = {}
    for project_id in projects:
        seen: list[uuid.UUID] = []
        parent = projects[project_id].parent_project_id
        while parent is not None and parent in projects and parent not in seen and len(seen) < _ANCESTOR_WALK_CAP:
            seen.append(parent)
            parent = projects[parent].parent_project_id
        ancestors[project_id] = frozenset(seen)
    return projects, ancestors


def profile_impact(db: Session, profile: GovernanceProfile) -> list[tuple[Project, ProfileOutcome, bool | None]]:
    """What one profile does for every project of its organisation.

    Args:
        db: An active session.
        profile: The profile.

    Returns:
        `(project, outcome, choice)` for each project, ordered by project name; `NOT_TARGETED` projects are included.
    """
    rows = _load_rows(db, profile.organization_id, profile_id=profile.id)
    projects, ancestors = _ancestors_by_project(db, profile.organization_id)
    own = next((p for p in rows.profiles if p.id == profile.id), profile)
    return [
        (project, outcome_for(rows, own, project.id, ancestors[project.id]), rows.choices.get((profile.id, project.id)))
        for project in sorted(projects.values(), key=lambda p: (p.name.casefold(), str(p.id)))
    ]


def rows_for_profiles(db: Session, organization_id: uuid.UUID) -> ProfileRows:
    """The organisation's profiles with their targets and exemptions (choices omitted), for the organisation's list."""
    rows = _load_rows(db, organization_id)
    return ProfileRows(rows.profiles, [t for ts in rows.targets.values() for t in ts], [e for es in rows.exemptions.values() for e in es], [])


def project_names(db: Session, project_ids: Collection[uuid.UUID]) -> Mapping[uuid.UUID, str]:
    """The names of the given projects in one read."""
    if not project_ids:
        return {}
    return dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids))).tuples().all())
