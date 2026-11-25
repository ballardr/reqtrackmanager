"""
Module: services.code_prefixes

The prefix new records of each type are numbered with (`DEC-006`, or `ADR-006` where an organisation or
project chose `ADR`), and the rules for choosing it.

Responsibilities:
- Know each type's built-in default prefix (core types here, module types from
  `ModuleDefinition.default_code_prefixes`).
- Resolve the effective prefix for an owner: the project, its nearest ancestor project that sets one, the
  organisation, then the default (`effective_prefix`, called by `services.sequences.generate_unique_code`).
- Validate and store an override (`set_override`, `clear_override`), describe a scope (`describe_scope`), and
  carry overrides in the bundles and into template projects (`export_overrides`, `import_overrides`,
  `copy_overrides`).

Design decisions:
- Resolution is per type over a sparse override map, so a child project inherits (the nested-project rule); an
  organisation-owned record resolves from the organisation's overrides only.
- An override affects records created afterwards; a stored code never changes and the counter is never reused.
- Effective prefixes are unique within a scope. A write is checked against every scope it changes, for the type
  being changed only, so an existing collision (a later module default) cannot block an unrelated edit.
- A prefix may not equal the organisation's code or a project code in an affected scope: a qualified code is
  split on its first hyphen and must stay readable.
- Requirement codes use component and category prefixes and are outside this mechanism.
- Reads are memoised on the session (`db.info`) and dropped on commit or rollback, so a bulk import resolves once.

Dependencies: `app.code_rules`, `app.modules.registry`, `services.audit`, `services.project_hierarchy`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.code_rules import normalise_code, record_prefix_error
from app.models.code_prefix import OrganizationCodePrefix, ProjectCodePrefix
from app.models.organization import Organization
from app.models.project import Project
from app.modules.registry import get_artefact_type_label, get_default_code_prefixes
from app.services.audit import log_event
from app.services.project_hierarchy import get_project_chain_ids

logger = logging.getLogger(__name__)

Tier = Literal["project", "parent_project", "organization", "default"]

REQUIREMENT_TYPE = "requirement"
_CACHE_KEY = "code_prefix_overrides"


def core_default_prefixes() -> dict[str, str]:
    """The built-in prefixes of the core types that have a `PREFIX-nnn` code (a requirement does not)."""
    from app.services.actions import ACTION_CODE_PREFIX
    from app.services.change_request_summary import CHANGE_REQUEST_CODE_PREFIX

    return {"change_request": CHANGE_REQUEST_CODE_PREFIX, "requirement_action": ACTION_CODE_PREFIX}


def core_types_without_prefix() -> dict[str, str]:
    """`{core type: reason}` for a core type outside this mechanism."""
    return {
        REQUIREMENT_TYPE: "A requirement's code is built from its component and category prefixes (C-G-07), not from this setting.",
    }


def default_prefixes() -> dict[str, str]:
    """`{artefact type: built-in prefix}` for every registered type whose records can be numbered with a prefix."""
    return {**core_default_prefixes(), **get_default_code_prefixes()}


@dataclass(frozen=True)
class PrefixChoice:
    """A prefix and the tier that set it.

    Attributes:
        prefix: The prefix.
        tier: `project` (the scope's own), `parent_project` (an ancestor's), `organization` or `default`.
        project_id: The project that set it, for `project` and `parent_project`.
    """

    prefix: str
    tier: Tier
    project_id: uuid.UUID | None = None


@dataclass(frozen=True)
class PrefixRow:
    """One record type's line in a scope's prefix list.

    Attributes:
        artefact_type: The registered type.
        label: The type's singular display name.
        default_prefix: The built-in prefix.
        own_prefix: The prefix this scope itself set, or `None` when it follows the next tier.
        effective: What a record created in this scope is numbered with, and which tier decided it.
        inherited: What the scope would use if it set none of its own (what clearing its prefix returns to).
    """

    artefact_type: str
    label: str
    default_prefix: str
    own_prefix: str | None
    effective: PrefixChoice
    inherited: PrefixChoice


def _drop_cache(session: Session) -> None:
    """Forgets this session's memoised overrides (after a commit or rollback, or a write here)."""
    session.info.pop(_CACHE_KEY, None)


event.listen(Session, "after_commit", _drop_cache)
event.listen(Session, "after_rollback", _drop_cache)


def _organization_overrides(db: Session, organization_id: uuid.UUID) -> dict[str, str]:
    """The organisation's own overrides, `{artefact type: prefix}`."""
    rows = db.execute(
        select(OrganizationCodePrefix.artefact_type, OrganizationCodePrefix.prefix).where(
            OrganizationCodePrefix.organization_id == organization_id
        )
    ).all()
    return {artefact_type: prefix for artefact_type, prefix in rows}


def _project_chain_overrides(db: Session, project_id: uuid.UUID) -> list[tuple[uuid.UUID, dict[str, str]]]:
    """Each project of the chain (the project, its parent, ... the root) with its own overrides, nearest first."""
    chain = get_project_chain_ids(db, project_id)
    by_project: dict[uuid.UUID, dict[str, str]] = {pid: {} for pid in chain}
    rows = db.execute(
        select(ProjectCodePrefix.project_id, ProjectCodePrefix.artefact_type, ProjectCodePrefix.prefix).where(
            ProjectCodePrefix.project_id.in_(chain)
        )
    ).all()
    for pid, artefact_type, prefix in rows:
        by_project[pid][artefact_type] = prefix
    return [(pid, by_project[pid]) for pid in chain]


def _overrides_for(db: Session, owner: Project | Organization) -> dict[str, PrefixChoice]:
    """Every override that applies to `owner`, `{artefact type: choice}`, nearest tier winning; memoised on the session."""
    cache: dict[tuple[str, uuid.UUID], dict[str, PrefixChoice]] = db.info.setdefault(_CACHE_KEY, {})
    key = ("organization" if isinstance(owner, Organization) else "project", owner.id)
    found = cache.get(key)
    if found is not None:
        return found
    choices: dict[str, PrefixChoice] = {}
    if isinstance(owner, Organization):
        for artefact_type, prefix in _organization_overrides(db, owner.id).items():
            choices[artefact_type] = PrefixChoice(prefix, "organization")
    else:
        for artefact_type, prefix in _organization_overrides(db, owner.organization_id).items():
            choices[artefact_type] = PrefixChoice(prefix, "organization")
        for pid, own in reversed(_project_chain_overrides(db, owner.id)):  # the root first, so the nearest wins
            tier: Tier = "project" if pid == owner.id else "parent_project"
            for artefact_type, prefix in own.items():
                choices[artefact_type] = PrefixChoice(prefix, tier, pid)
    cache[key] = choices
    return choices


def effective_prefix(db: Session, owner: Project | Organization, artefact_type: str, default: str) -> str:
    """The prefix a new record of `artefact_type` owned by `owner` is numbered with.

    Args:
        db: An active session.
        owner: The project (or the organisation, for an organisation-owned record) the record belongs to.
        artefact_type: The registered type.
        default: The caller's built-in prefix, used when no tier sets one.

    Returns:
        The nearest project override, else the organisation's, else `default`.
    """
    choice = _overrides_for(db, owner).get(artefact_type)
    return choice.prefix if choice is not None else default


def resolve_choice(db: Session, owner: Project | Organization, artefact_type: str) -> PrefixChoice:
    """The effective prefix of one type for `owner` with the tier that decided it (`default` when none did)."""
    choice = _overrides_for(db, owner).get(artefact_type)
    return choice if choice is not None else PrefixChoice(default_prefixes()[artefact_type], "default")


def describe_scope(db: Session, scope: Project | Organization, artefact_types: list[str]) -> list[PrefixRow]:
    """The prefix rows of `scope` for `artefact_types`, in the order given.

    Args:
        db: An active session.
        scope: The organisation or the project being described.
        artefact_types: The types to list (the caller has already dropped those the scope may not use).
    """
    defaults = default_prefixes()
    parents: list[tuple[uuid.UUID, dict[str, str]]] = []
    if isinstance(scope, Organization):
        own = _organization_overrides(db, scope.id)
        organization_own: dict[str, str] = {}
    else:
        chain = _project_chain_overrides(db, scope.id)
        own, parents = dict(chain[0][1]), chain[1:]
        organization_own = _organization_overrides(db, scope.organization_id)

    def inherited(artefact_type: str) -> PrefixChoice:
        for pid, overrides in parents:
            if artefact_type in overrides:
                return PrefixChoice(overrides[artefact_type], "parent_project", pid)
        if artefact_type in organization_own:
            return PrefixChoice(organization_own[artefact_type], "organization")
        return PrefixChoice(defaults[artefact_type], "default")

    return [
        PrefixRow(
            artefact_type=t, label=get_artefact_type_label(t), default_prefix=defaults[t], own_prefix=own.get(t),
            effective=resolve_choice(db, scope, t), inherited=inherited(t),
        )
        for t in artefact_types if t in defaults
    ]


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)


@dataclass
class _Snapshot:
    """The organisation's overrides and project tree held in memory so a write can be checked in every scope it changes."""

    organization: Organization
    org_overrides: dict[str, str]
    project_overrides: dict[uuid.UUID, dict[str, str]]
    parent: dict[uuid.UUID, uuid.UUID | None]
    code: dict[uuid.UUID, str]

    def effective(self, scope: uuid.UUID | None, defaults: dict[str, str]) -> dict[str, str]:
        """Every type's effective prefix in the organisation (`scope` None) or in a project."""
        merged = {**defaults, **self.org_overrides}
        if scope is None:
            return merged
        chain: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        current: uuid.UUID | None = scope
        while current is not None and current not in seen:
            seen.add(current)
            chain.append(current)
            current = self.parent.get(current)
        for pid in reversed(chain):
            merged.update(self.project_overrides.get(pid, {}))
        return merged

    def descendants(self, project_id: uuid.UUID) -> set[uuid.UUID]:
        """Every project nested under `project_id` (transitively)."""
        found: set[uuid.UUID] = set()
        frontier = {project_id}
        while frontier:
            frontier = {p for p, parent in self.parent.items() if parent in frontier and p not in found and p != project_id}
            found |= frontier
        return found


def _snapshot(db: Session, organization: Organization) -> _Snapshot:
    """Loads the organisation's overrides, every project's overrides, parents and codes."""
    projects = db.execute(
        select(Project.id, Project.parent_project_id, Project.code).where(Project.organization_id == organization.id)
    ).all()
    project_overrides: dict[uuid.UUID, dict[str, str]] = {}
    for pid, artefact_type, prefix in db.execute(
        select(ProjectCodePrefix.project_id, ProjectCodePrefix.artefact_type, ProjectCodePrefix.prefix)
        .join(Project, Project.id == ProjectCodePrefix.project_id).where(Project.organization_id == organization.id)
    ).all():
        project_overrides.setdefault(pid, {})[artefact_type] = prefix
    return _Snapshot(
        organization=organization, org_overrides=_organization_overrides(db, organization.id),
        project_overrides=project_overrides, parent={pid: parent for pid, parent, _code in projects},
        code={pid: code.upper() for pid, _parent, code in projects},
    )


def _collision_message(
    snapshot: _Snapshot, artefact_type: str, scope_project: uuid.UUID | None, affected_projects: list[uuid.UUID | None],
    before: dict[uuid.UUID | None, str],
) -> str | None:
    """Why the change in `snapshot` (already applied) gives two types one prefix somewhere, or `None`."""
    defaults = default_prefixes()
    for scope in affected_projects:
        effective = snapshot.effective(scope, defaults)
        if effective[artefact_type] == before[scope]:
            continue  # this scope's value did not change, so any sharing there already existed
        new = effective[artefact_type]
        names = {
            other for other, prefix in effective.items() if other != artefact_type and prefix == new
        }
        if names:
            where = "the organisation" if scope is None else "this project" if scope == scope_project else "a nested project"
            return f"{new} is already the prefix of {get_artefact_type_label(sorted(names)[0]).lower()} records in {where}."
        if new == snapshot.organization.code.upper():
            return f"{new} is the organisation's code and cannot also be a record prefix."
        if scope is not None and new == snapshot.code.get(scope):
            return f"{new} is a project's code and cannot also be a record prefix."
    return None


def _affected(snapshot: _Snapshot, scope: Project | Organization) -> list[uuid.UUID | None]:
    """The scopes a write at `scope` can change: for the organisation itself and every project, for a project it and its descendants."""
    if isinstance(scope, Organization):
        return [None, *snapshot.parent]
    return [scope.id, *snapshot.descendants(scope.id)]


def _organization_of(db: Session, scope: Project | Organization) -> Organization:
    """The organisation `scope` belongs to (itself, or the project's)."""
    if isinstance(scope, Organization):
        return scope
    organization = db.get(Organization, scope.organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return organization


def _lock_organization(db: Session, organization: Organization) -> None:
    """Serialises prefix writes of one organisation until the transaction ends.

    The collision check reads every override of the organisation and the write follows it, so two concurrent writes
    could each pass the check and together give two types one prefix; the row lock makes the second wait and see
    the first.
    """
    db.execute(select(Organization.id).where(Organization.id == organization.id).with_for_update())


def _apply(snapshot: _Snapshot, scope: Project | Organization, artefact_type: str, prefix: str | None) -> None:
    """Applies (or, for `None`, removes) the override to the in-memory snapshot only."""
    target = snapshot.org_overrides if isinstance(scope, Organization) else snapshot.project_overrides.setdefault(scope.id, {})
    if prefix is None:
        target.pop(artefact_type, None)
    else:
        target[artefact_type] = prefix


def _stored(db: Session, scope: Project | Organization, artefact_type: str) -> OrganizationCodePrefix | ProjectCodePrefix | None:
    """The scope's own override row for `artefact_type`, if any."""
    if isinstance(scope, Organization):
        return db.scalar(
            select(OrganizationCodePrefix).where(
                OrganizationCodePrefix.organization_id == scope.id, OrganizationCodePrefix.artefact_type == artefact_type
            )
        )
    return db.scalar(
        select(ProjectCodePrefix).where(ProjectCodePrefix.project_id == scope.id, ProjectCodePrefix.artefact_type == artefact_type)
    )


def _check_type(artefact_type: str) -> None:
    """Raises 400 unless `artefact_type` is a registered type whose records have a prefix."""
    if artefact_type not in default_prefixes():
        raise _bad_request(f"{artefact_type!r} is not a record type with a configurable code prefix.")


def _audit(db: Session, scope: Project | Organization, actor_id: uuid.UUID | None, action: str, detail: dict[str, str | None]) -> None:
    """Writes the audit event for a prefix change (type and prefixes only)."""
    if isinstance(scope, Organization):
        log_event(
            db, entity_type="organization", entity_id=scope.id, action=action, actor_id=actor_id,
            organization_id=scope.id, detail=detail,
        )
    else:
        log_event(
            db, entity_type="project", entity_id=scope.id, action=action, actor_id=actor_id,
            organization_id=scope.organization_id, project_id=scope.id, detail=detail,
        )


def set_override(
    db: Session, scope: Project | Organization, artefact_type: str, raw_prefix: str, actor_id: uuid.UUID | None,
) -> str:
    """Stores `raw_prefix` as `scope`'s prefix for `artefact_type`, replacing any earlier one.

    Applies to records created from now on; stored codes and counters are untouched. Not committed.

    Args:
        db: An active session.
        scope: The organisation or project choosing the prefix.
        artefact_type: The registered type.
        raw_prefix: The prefix as typed (case and surrounding spaces are normalised).
        actor_id: The acting user for the audit event, or `None` for a system action.

    Returns:
        The normalised prefix.

    Raises:
        HTTPException: 400 if the type has no configurable prefix, the prefix breaks the shape rule, equals an
            organisation or project code, or would give two types one prefix in this scope or one nested in it.
    """
    _check_type(artefact_type)
    prefix = normalise_code(raw_prefix)
    message = record_prefix_error(prefix)
    if message is not None:
        raise _bad_request(message)
    organization = _organization_of(db, scope)
    _lock_organization(db, organization)
    snapshot = _snapshot(db, organization)
    affected = _affected(snapshot, scope)
    defaults = default_prefixes()
    before = {s: snapshot.effective(s, defaults)[artefact_type] for s in affected}
    _apply(snapshot, scope, artefact_type, prefix)
    scope_project = None if isinstance(scope, Organization) else scope.id
    message = _collision_message(snapshot, artefact_type, scope_project, affected, before)
    if message is not None:
        raise _bad_request(message)
    row = _stored(db, scope, artefact_type)
    previous = row.prefix if row is not None else None
    if row is not None:
        row.prefix = prefix
    elif isinstance(scope, Organization):
        db.add(OrganizationCodePrefix(organization_id=scope.id, artefact_type=artefact_type, prefix=prefix))
    else:
        db.add(ProjectCodePrefix(project_id=scope.id, artefact_type=artefact_type, prefix=prefix))
    db.flush()
    _drop_cache(db)
    _audit(db, scope, actor_id, "code_prefix_set", {"artefact_type": artefact_type, "prefix": prefix, "previous": previous})
    return prefix


def clear_override(db: Session, scope: Project | Organization, artefact_type: str, actor_id: uuid.UUID | None) -> bool:
    """Removes `scope`'s own prefix for `artefact_type` so it follows the next tier again. Not committed.

    Returns:
        Whether an override existed.

    Raises:
        HTTPException: 400 if the type has no configurable prefix, or following the next tier would give two types
            one prefix in this scope or one nested in it.
    """
    _check_type(artefact_type)
    row = _stored(db, scope, artefact_type)
    if row is None:
        return False
    organization = _organization_of(db, scope)
    _lock_organization(db, organization)
    snapshot = _snapshot(db, organization)
    affected = _affected(snapshot, scope)
    defaults = default_prefixes()
    before = {s: snapshot.effective(s, defaults)[artefact_type] for s in affected}
    _apply(snapshot, scope, artefact_type, None)
    scope_project = None if isinstance(scope, Organization) else scope.id
    message = _collision_message(snapshot, artefact_type, scope_project, affected, before)
    if message is not None:
        raise _bad_request(message)
    previous = row.prefix
    db.delete(row)
    db.flush()
    _drop_cache(db)
    _audit(db, scope, actor_id, "code_prefix_cleared", {"artefact_type": artefact_type, "previous": previous})
    return True


def export_overrides(db: Session, scope: Project | Organization) -> list[dict[str, str]]:
    """The scope's own overrides as bundle entries, `[{"artefact_type", "prefix"}]`, ordered by type."""
    if isinstance(scope, Organization):
        own = _organization_overrides(db, scope.id)
    else:
        own = dict(next(iter(_project_chain_overrides(db, scope.id)))[1])
    return [{"artefact_type": t, "prefix": own[t]} for t in sorted(own)]


def import_overrides(
    db: Session, scope: Project | Organization, entries: list[dict[str, Any]] | None, actor_id: uuid.UUID | None,
    warn: Callable[[str], None],
) -> None:
    """Applies bundle `entries` to `scope`, each through `set_override`; one that is not valid here (a type no longer
    registered, a prefix now equal to a project code or another type's prefix) is reported through `warn` and skipped,
    so a bundle never fails as a whole over a prefix. Not committed."""
    for entry in entries or []:
        artefact_type = str(entry.get("artefact_type", ""))
        try:
            set_override(db, scope, artefact_type, str(entry.get("prefix", "")), actor_id)
        except HTTPException as error:
            warn(f"The record code prefix for {artefact_type or 'an unnamed type'} was not imported: {error.detail}")


def copy_overrides(db: Session, source: Project, target: Project, actor_id: uuid.UUID | None) -> None:
    """Copies `source`'s own overrides to `target` (a project made from a template). One that no longer fits the
    target's place in the project tree is logged and left out. Not committed."""
    for entry in export_overrides(db, source):
        try:
            set_override(db, target, entry["artefact_type"], entry["prefix"], actor_id)
        except HTTPException as error:
            logger.warning("Template record code prefix %s not copied: %s", entry["artefact_type"], error.detail)
