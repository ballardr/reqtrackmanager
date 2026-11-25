"""
Module: modules.traceability.lifecycle_policy

The lifecycle policy of governance profiles: which optional states a profile requires every project it applies to to keep
on, and whether it forbids skipping steps. Registered as the `lifecycle_policies` part's policy resolver and profile
contributor.

Responsibilities:
- Write a profile's policy (`set_required`, `set_skip_forbidden`), validating against the registered lifecycles and
  recording one audit event each (type and state keys only).
- Read it for the organisation's profile screens (`profile_policy`).
- Answer the core `GovernanceSeam.LIFECYCLE` for one project (`resolve_project_policy`): the union of what every profile
  that applies to the project requires, with the names of the profiles, for `services.lifecycles` to bind.
- Count, export and import a profile's rows for the profile list and the organisation bundle (`count_rows`,
  `export_rows`, `import_rows`).

Design decisions:
- Which profiles apply to a project (Enforced, Default not opted out, opted-in; exempt projects skipped) is decided by
  `profile_resolution`; this file only reads the rows of those profiles.
- Merge rule: requirements are united and any one profile may forbid skipping, so a profile can only add to what binds a
  project, never relax what another binds. A project's own turned-off states and the organisation's requirement are
  merged the same way in `services.lifecycles`.
- A profile requires only optional states of a registered type (`services.lifecycles.validated_states`): a gated or
  path-end state is never optional, so no profile can turn off an approval.
- Rows for a type or state that is no longer registered are kept and ignored by the core resolver, so a module being
  switched off or upgraded never loses them.
- Import writes the rows without a per-row audit event: the profile's own `created` event and the bundle import record it,
  and no row is a change a person made in the screen.

Dependencies: `services.lifecycles` (validation, availability), `profile_resolution`, `models`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.modules.registry import LifecycleDefinition, get_lifecycles
from app.modules.seams import LifecyclePolicy
from app.modules.traceability.models import (
    GovernanceLifecycleRequirement,
    GovernanceLifecycleSkipPolicy,
    GovernanceProfile,
)
from app.modules.traceability.profile_resolution import applicable_profiles
from app.services import lifecycles
from app.services.audit import log_event

AUDIT_ENTITY_TYPE = "governance_profile"
KIND_REQUIRED = "required_states"
KIND_SKIP = "skip"


@dataclass(frozen=True)
class TypePolicy:
    """A profile's requirement for one record type, with the type's optional states for the screen.

    Attributes:
        artefact_type: The registered record type.
        module_key: The module that owns the type, empty for a core type.
        definition: The type's lifecycle definition.
        required: The optional states the profile requires, in path order.
    """

    artefact_type: str
    module_key: str
    definition: LifecycleDefinition
    required: list[str]


@dataclass(frozen=True)
class ProfileLifecyclePolicy:
    """A profile's lifecycle policy as the organisation sees it.

    Attributes:
        types: One entry per lifecycle with optional states that is in effect for the organisation, in type-name order.
        skip_forbidden: Whether the profile forbids skipping steps.
    """

    types: list[TypePolicy]
    skip_forbidden: bool


def _required_rows(db: Session, profile_id: uuid.UUID) -> dict[str, set[str]]:
    """The profile's required states by type."""
    out: dict[str, set[str]] = defaultdict(set)
    for row in db.scalars(select(GovernanceLifecycleRequirement).where(GovernanceLifecycleRequirement.profile_id == profile_id)):
        out[row.artefact_type].add(row.state)
    return out


def profile_policy(db: Session, organization: Organization, profile: GovernanceProfile) -> ProfileLifecyclePolicy:
    """The profile's lifecycle policy over the types the organisation can use.

    Args:
        db: Active session (read only).
        organization: The profile's organisation.
        profile: The profile.

    Returns:
        Every lifecycle with optional states whose module is in effect for the organisation (a core type always is), with
        the states the profile requires of it.
    """
    required = _required_rows(db, profile.id)
    types = [
        TypePolicy(
            artefact_type=artefact_type, module_key=module_key, definition=definition,
            required=[s for s in definition.optional if s in required.get(artefact_type, ())],
        )
        for artefact_type, (module_key, definition) in sorted(get_lifecycles().items())
        if definition.optional and lifecycles.enabled_for_organization(db, organization.id, artefact_type, module_key)
    ]
    forbidden = db.scalar(
        select(GovernanceLifecycleSkipPolicy.forbidden).where(GovernanceLifecycleSkipPolicy.profile_id == profile.id)
    )
    return ProfileLifecyclePolicy(types=types, skip_forbidden=bool(forbidden))


def _write_required(db: Session, profile_id: uuid.UUID, artefact_type: str, states: Sequence[str]) -> None:
    """Makes the profile's rows for one type equal `states` (flushed, not audited)."""
    rows = {
        row.state: row for row in db.scalars(
            select(GovernanceLifecycleRequirement).where(
                GovernanceLifecycleRequirement.profile_id == profile_id,
                GovernanceLifecycleRequirement.artefact_type == artefact_type,
            )
        )
    }
    for state, row in rows.items():
        if state not in states:
            db.delete(row)
    for state in states:
        if state not in rows:
            db.add(GovernanceLifecycleRequirement(profile_id=profile_id, artefact_type=artefact_type, state=state))
    db.flush()


def set_required(
    db: Session, *, profile: GovernanceProfile, artefact_type: str, required: Iterable[str], actor_id: uuid.UUID,
) -> None:
    """Sets the states a profile requires of one record type.

    Args:
        db: Active session (not committed).
        profile: The profile.
        artefact_type: The registered record type.
        required: The optional states to require; an empty list removes the profile's requirement for the type.
        actor_id: The acting user.

    Raises:
        HTTPException: 404 for an unknown record type; 422 for a state that is not an optional state of the type.
    """
    _, definition = lifecycles.validated_type(artefact_type)
    states = lifecycles.validated_states(definition, required)
    _write_required(db, profile.id, artefact_type, states)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="lifecycle_updated", actor_id=actor_id,
        organization_id=profile.organization_id, detail={"artefact_type": artefact_type, "required_states": states},
    )


def _write_skip(db: Session, profile_id: uuid.UUID, forbidden: bool) -> None:
    """Sets the profile's skip policy row (flushed, not audited)."""
    row = db.scalar(select(GovernanceLifecycleSkipPolicy).where(GovernanceLifecycleSkipPolicy.profile_id == profile_id))
    if row is None:
        db.add(GovernanceLifecycleSkipPolicy(profile_id=profile_id, forbidden=forbidden))
    else:
        row.forbidden = forbidden
    db.flush()


def set_skip_forbidden(db: Session, *, profile: GovernanceProfile, forbidden: bool, actor_id: uuid.UUID) -> None:
    """Sets whether a profile forbids skipping steps in the projects it applies to."""
    _write_skip(db, profile.id, forbidden)
    log_event(
        db, entity_type=AUDIT_ENTITY_TYPE, entity_id=profile.id, action="lifecycle_skip_updated", actor_id=actor_id,
        organization_id=profile.organization_id, detail={"forbidden": forbidden},
    )


# --- the seam ------------------------------------------------------------------------------------


def resolve_project_policy(db: Session, project_id: uuid.UUID) -> LifecyclePolicy | None:
    """`PolicyResolver.resolve_project` for `GovernanceSeam.LIFECYCLE`: what the profiles that apply to the project add.

    Args:
        db: Active session (read only).
        project_id: The project.

    Returns:
        The states required and the profiles forbidding skipping, each source named in precedence order (Enforced,
        then Default, then opted-in, each by name); `None` when no applicable profile has lifecycle policy.
    """
    applied = applicable_profiles(db, project_id)
    if not applied:
        return None
    position = {a.profile_id: i for i, a in enumerate(applied)}
    names = {a.profile_id: a.name for a in applied}
    rows = sorted(
        db.scalars(select(GovernanceLifecycleRequirement).where(GovernanceLifecycleRequirement.profile_id.in_(position))),
        key=lambda r: (position[r.profile_id], r.artefact_type, r.state),
    )
    required: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        required[row.artefact_type][row.state].append(names[row.profile_id])
    forbidding = sorted(
        db.scalars(
            select(GovernanceLifecycleSkipPolicy.profile_id).where(
                GovernanceLifecycleSkipPolicy.profile_id.in_(position), GovernanceLifecycleSkipPolicy.forbidden.is_(True)
            )
        ),
        key=position.__getitem__,
    )
    if not required and not forbidding:
        return None
    return LifecyclePolicy(
        required={t: {s: tuple(n) for s, n in states.items()} for t, states in required.items()},
        skip_forbidden_by=tuple(names[p] for p in forbidding),
    )


# --- the profile contributor ---------------------------------------------------------------------


def count_rows(db: Session, profile_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """`ProfileContributor.count_rows`: per profile, the record types it requires states of, plus one when it forbids
    skipping steps."""
    counts: dict[uuid.UUID, int] = defaultdict(int)
    for profile_id, types in db.execute(
        select(GovernanceLifecycleRequirement.profile_id, func.count(func.distinct(GovernanceLifecycleRequirement.artefact_type)))
        .where(GovernanceLifecycleRequirement.profile_id.in_(profile_ids))
        .group_by(GovernanceLifecycleRequirement.profile_id)
    ).tuples():
        counts[profile_id] += types
    for profile_id in db.scalars(
        select(GovernanceLifecycleSkipPolicy.profile_id).where(
            GovernanceLifecycleSkipPolicy.profile_id.in_(profile_ids), GovernanceLifecycleSkipPolicy.forbidden.is_(True)
        )
    ):
        counts[profile_id] += 1
    return dict(counts)


def export_rows(db: Session, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    """`ProfileContributor.export_rows`: one entry per type with required states (`kind` `required_states`, ordered by
    type) and one `skip` entry when the profile forbids skipping steps."""
    required = _required_rows(db, profile_id)
    rows: list[dict[str, Any]] = [
        {"kind": KIND_REQUIRED, "artefact_type": artefact_type, "states": sorted(required[artefact_type])}
        for artefact_type in sorted(required)
    ]
    if db.scalar(
        select(GovernanceLifecycleSkipPolicy.forbidden).where(GovernanceLifecycleSkipPolicy.profile_id == profile_id)
    ):
        rows.append({"kind": KIND_SKIP, "forbidden": True})
    return rows


def import_rows(db: Session, profile_id: uuid.UUID, rows: Sequence[dict[str, Any]], warn: Callable[[str], None]) -> None:
    """`ProfileContributor.import_rows`: writes bundle entries into the profile. A type that is no longer registered, a
    state a type does not let a project turn off and an unknown entry are reported through `warn` and skipped."""
    for entry in rows:
        kind = entry.get("kind")
        if kind == KIND_REQUIRED:
            artefact_type = str(entry.get("artefact_type", ""))
            try:
                _, definition = lifecycles.validated_type(artefact_type)
                states = lifecycles.validated_states(definition, [str(s) for s in entry.get("states") or []])
            except HTTPException as error:
                warn(f"The required lifecycle states for {artefact_type or 'an unnamed type'} were not imported: {error.detail}")
                continue
            _write_required(db, profile_id, artefact_type, states)
        elif kind == KIND_SKIP:
            _write_skip(db, profile_id, bool(entry.get("forbidden")))
        else:
            warn("A lifecycle policy entry of an unknown kind was not imported.")

