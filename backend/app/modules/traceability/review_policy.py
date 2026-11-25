"""
Module: modules.traceability.review_policy

The review policy of governance: how often a record type is reviewed at most, how early its reminder is sent and who is
reminded when a record has no reviewer, set by a governance profile or by a project. Registered as the `review_policies`
part's policy resolver, profile contributor and project bundle entry.

Responsibilities:
- Write a profile's or a project's settings for a record type (`set_profile_settings`, `set_project_settings`), validating
  the type and the default owner and recording one audit event each (type and setting keys, never names or people).
- Answer the core `GovernanceSeam.REVIEW` for one type in one project (`resolve_policy`).
- Describe a profile's policy and a project's effective policy with where each setting came from (`profile_policy`,
  `project_policy`), for the screens.
- Count, export and import a profile's rows (`count_rows`, `export_rows`, `import_rows`) and a project's own rows
  (`export_project_rows`, `import_project_rows`).

Design decisions:
- A policy only tightens: of several sources the shortest interval and the longest lead apply, so a profile, a project and an
  ancestor can each ask for more review and none can take away what another asked. The default owner is a single person or
  group, so the first source in precedence order that names one applies (Enforced profile, then the project's other
  profiles, then the project's own row, else the nearest ancestor's).
- Which profiles apply is `profile_resolution`'s decision; this file reads their rows. An exempt or opted-out project
  therefore does not get a profile's settings.
- A project row beats the nearest ancestor's for the same type, so a child project can follow its parent (no row) or set its
  own. A row with no setting is a deliberate "nothing here" and stops the ancestor's applying.
- A profile's default owner is a user or an organisation group: a project group belongs to one project, so only a project's
  own row may name one.
- The types a policy covers are those with a review adapter (`modules.registry.get_review_adapters`), so a type that gains
  an adapter is configurable with no change here.
- Import writes a project's rows without per-row audit events: the import itself is the recorded act.

Dependencies: `services.review_engine` (vocabulary), `profile_resolution`, `services.project_hierarchy`,
`services.principals` (owner validation, labels, bundles), `models`, `services.audit`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules import registry
from app.modules.seams import ReviewPolicy
from app.modules.traceability.models import GovernanceProfile, GovernanceReviewPolicy
from app.modules.traceability.profile_resolution import applicable_profiles
from app.schemas.principal import PrincipalRef
from app.services import lifecycles
from app.services.audit import log_event
from app.services.principals import principal_from_bundle, principal_ref, principal_to_bundle, validate_principal
from app.services.project_hierarchy import get_project_chain_ids

PROFILE_AUDIT_ENTITY_TYPE = "governance_profile"
PROJECT_AUDIT_ENTITY_TYPE = "governance_review_policy"
KIND_REVIEW = "review"
PROJECT_ROWS_KEY = "governance_review_policies"

INTERVAL_DAYS_RANGE = (1, 3650)
LEAD_DAYS_RANGE = (0, 365)


@dataclass(frozen=True)
class ReviewSettings:
    """The review settings one owner gives a record type; each is optional.

    Attributes:
        interval_days: The longest gap between reviews in days.
        lead_days: Days before the due date that the reminder is sent.
        default_owner: Who is reminded when a record has no reviewer.
    """

    interval_days: int | None = None
    lead_days: int | None = None
    default_owner: PrincipalRef | None = None

    @property
    def is_empty(self) -> bool:
        """Whether no setting is given."""
        return self.interval_days is None and self.lead_days is None and self.default_owner is None


@dataclass(frozen=True)
class ReviewType:
    """A record type that has a review schedule.

    Attributes:
        artefact_type: The registered record type.
        label: Its singular display name.
        module_key: The module that registered it, `""` for a core type.
    """

    artefact_type: str
    label: str
    module_key: str


@dataclass(frozen=True)
class EffectiveReview:
    """What applies to one type in a project, with where each setting came from.

    Attributes:
        interval_days: The shortest interval any source gives, `None` for none.
        interval_source: The first source giving it.
        lead_days: The longest lead any source gives, `None` for none.
        lead_source: The first source giving it.
        default_owner: The first default owner in precedence order, `None` for none.
        owner_source: The source giving it.
    A source is the name of a profile, `"project"` or `"parent_project"`.
    """

    interval_days: int | None
    interval_source: str | None
    lead_days: int | None
    lead_source: str | None
    default_owner: PrincipalRef | None
    owner_source: str | None


@dataclass(frozen=True)
class ProjectTypePolicy:
    """A project's review policy for one record type.

    Attributes:
        review_type: The type.
        own: The project's own settings, `None` when it has no row (it follows the nearest ancestor's).
        inherited_from: Name of the ancestor project whose row applies, `None` when the project has its own row or no
            ancestor has one.
        effective: What applies, with its sources.
    """

    review_type: ReviewType
    own: ReviewSettings | None
    inherited_from: str | None
    effective: EffectiveReview


def _settings(row: GovernanceReviewPolicy) -> ReviewSettings:
    return ReviewSettings(
        interval_days=row.interval_days, lead_days=row.lead_days,
        default_owner=principal_ref(row.default_owner_type, row.default_owner_id),
    )


def review_types(db: Session, organization_id: uuid.UUID) -> list[ReviewType]:
    """The record types with a review schedule whose module is in effect for the organisation, in type-name order."""
    return [
        ReviewType(artefact_type, registry.get_artefact_type_label(artefact_type), module_key)
        for artefact_type, (module_key, _) in sorted(registry.get_review_adapters().items())
        if lifecycles.enabled_for_organization(db, organization_id, artefact_type, module_key)
    ]


def _review_type(artefact_type: str) -> ReviewType:
    """The review type of `artefact_type`.

    Raises:
        HTTPException: 404 for a type without a review schedule.
    """
    entry = registry.get_review_adapters().get(artefact_type)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That record type has no review schedule.")
    return ReviewType(artefact_type, registry.get_artefact_type_label(artefact_type), entry[0])


def _validated(
    db: Session, settings: ReviewSettings, *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> ReviewSettings:
    """`settings` after checking the ranges and the default owner.

    Raises:
        HTTPException: 422 for a value out of range; 400 for an owner who is not of the organisation (or project).
    """
    for name, value, (low, high) in (
        ("interval_days", settings.interval_days, INTERVAL_DAYS_RANGE), ("lead_days", settings.lead_days, LEAD_DAYS_RANGE),
    ):
        if value is not None and not low <= value <= high:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} must be between {low} and {high}.")
    validate_principal(db, settings.default_owner, organization_id=organization_id, project_id=project_id, field="default_owner")
    return settings


def _write(
    db: Session, *, profile_id: uuid.UUID | None, project_id: uuid.UUID | None, artefact_type: str,
    settings: ReviewSettings | None,
) -> bool:
    """Makes the owner's policy row for a type hold exactly `settings` (`None` removes the row; flushed, not audited).

    Returns:
        Whether the stored policy changed.
    """
    query = select(GovernanceReviewPolicy).where(GovernanceReviewPolicy.artefact_type == artefact_type)
    query = query.where(
        GovernanceReviewPolicy.profile_id == profile_id if profile_id is not None
        else GovernanceReviewPolicy.project_id == project_id
    )
    row = db.scalar(query)
    if settings is None:
        if row is None:
            return False
        db.delete(row)
        db.flush()
        return True
    owner = settings.default_owner
    if row is None:
        db.add(GovernanceReviewPolicy(
            profile_id=profile_id, project_id=project_id, artefact_type=artefact_type, interval_days=settings.interval_days,
            lead_days=settings.lead_days, default_owner_type=owner.type.value if owner else None,
            default_owner_id=owner.id if owner else None,
        ))
        db.flush()
        return True
    changed = _settings(row) != settings
    row.interval_days = settings.interval_days
    row.lead_days = settings.lead_days
    row.default_owner_type = owner.type.value if owner else None
    row.default_owner_id = owner.id if owner else None
    db.flush()
    return changed


def _detail(artefact_type: str, settings: ReviewSettings | None) -> dict[str, Any]:
    """Audit detail: the type and the settings given (the owner as a type only, never a name or an id)."""
    if settings is None:
        return {"artefact_type": artefact_type, "settings": None}
    return {
        "artefact_type": artefact_type,
        "settings": {
            "interval_days": settings.interval_days, "lead_days": settings.lead_days,
            "default_owner": None if settings.default_owner is None else settings.default_owner.type.value,
        },
    }


def set_profile_settings(
    db: Session, *, profile: GovernanceProfile, artefact_type: str, settings: ReviewSettings, actor_id: uuid.UUID,
) -> None:
    """Sets the review settings a profile gives one record type.

    Args:
        db: Active session (not committed).
        profile: The profile.
        artefact_type: A registered type with a review schedule.
        settings: The settings; one with nothing set removes the profile's policy for the type.
        actor_id: The acting user.

    Raises:
        HTTPException: 404 for a type without a review schedule; 422 for a value out of range; 400 for a default owner who
            is not of the organisation or is a project group.
    """
    _review_type(artefact_type)
    valid = _validated(db, settings, organization_id=profile.organization_id, project_id=None)
    _write(db, profile_id=profile.id, project_id=None, artefact_type=artefact_type, settings=None if valid.is_empty else valid)
    log_event(
        db, entity_type=PROFILE_AUDIT_ENTITY_TYPE, entity_id=profile.id, action="review_updated", actor_id=actor_id,
        organization_id=profile.organization_id, detail=_detail(artefact_type, valid),
    )


def set_project_settings(
    db: Session, *, project: Project, artefact_type: str, settings: ReviewSettings | None, actor_id: uuid.UUID,
) -> None:
    """Sets the review settings a project gives one record type.

    Args:
        db: Active session (not committed).
        project: The project.
        artefact_type: A registered type with a review schedule.
        settings: The settings; one with nothing set is a choice of no review policy that stops the nearest ancestor's
            applying; `None` removes the row so the project follows the nearest ancestor's.
        actor_id: The acting user.

    Raises:
        HTTPException: 404 for a type without a review schedule; 422 for a value out of range; 400 for a default owner who
            is not of the organisation or a group of another project.
    """
    _review_type(artefact_type)
    valid = None if settings is None else _validated(
        db, settings, organization_id=project.organization_id, project_id=project.id,
    )
    _write(db, profile_id=None, project_id=project.id, artefact_type=artefact_type, settings=valid)
    log_event(
        db, entity_type=PROJECT_AUDIT_ENTITY_TYPE, entity_id=project.id, action="updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail=_detail(artefact_type, valid),
    )


# --- reading -------------------------------------------------------------------------------------


def profile_policy(db: Session, profile: GovernanceProfile) -> list[tuple[ReviewType, ReviewSettings]]:
    """The profile's settings for every type with a review schedule that is in effect for its organisation.

    Returns:
        `(type, settings)` in type-name order; a type the profile sets nothing for has empty settings.
    """
    by_type = {
        row.artefact_type: _settings(row)
        for row in db.scalars(select(GovernanceReviewPolicy).where(GovernanceReviewPolicy.profile_id == profile.id))
    }
    return [(t, by_type.get(t.artefact_type, ReviewSettings())) for t in review_types(db, profile.organization_id)]


def _project_rows(
    db: Session, profile_ids: Sequence[uuid.UUID], chain: Sequence[uuid.UUID], artefact_type: str | None,
) -> tuple[dict[tuple[uuid.UUID, str], ReviewSettings], dict[tuple[uuid.UUID, str], ReviewSettings]]:
    """The policy rows of the applicable profiles and of the project chain, as `(owner id, type) -> settings` (profiles
    first, projects second), read in one statement."""
    owner_filters = []
    if profile_ids:
        owner_filters.append(GovernanceReviewPolicy.profile_id.in_(profile_ids))
    if chain:
        owner_filters.append(GovernanceReviewPolicy.project_id.in_(chain))
    if not owner_filters:
        return {}, {}
    query = select(GovernanceReviewPolicy).where(or_(*owner_filters))
    if artefact_type is not None:
        query = query.where(GovernanceReviewPolicy.artefact_type == artefact_type)
    rows = list(db.scalars(query))
    by_profile = {(r.profile_id, r.artefact_type): _settings(r) for r in rows if r.profile_id is not None}
    by_project = {(r.project_id, r.artefact_type): _settings(r) for r in rows if r.project_id is not None}
    return by_profile, by_project


def _combine(given: Sequence[tuple[str, ReviewSettings]]) -> EffectiveReview:
    """The effective settings of the sources in precedence order: the shortest interval, the longest lead and the first
    default owner."""
    interval = lead = owner = None
    interval_source = lead_source = owner_source = None
    for source, settings in given:
        if settings.interval_days is not None and (interval is None or settings.interval_days < interval):
            interval, interval_source = settings.interval_days, source
        if settings.lead_days is not None and (lead is None or settings.lead_days > lead):
            lead, lead_source = settings.lead_days, source
        if settings.default_owner is not None and owner is None:
            owner, owner_source = settings.default_owner, source
    return EffectiveReview(interval, interval_source, lead, lead_source, owner, owner_source)


def _merge(
    db: Session, project_id: uuid.UUID, chain: Sequence[uuid.UUID], artefact_type: str | None,
) -> tuple[dict[str, EffectiveReview], dict[str, ReviewSettings], dict[str, uuid.UUID]]:
    """What applies to the project per type, the project's own settings, and the ancestor whose row applies. `chain` is the
    project's chain, nearest first, starting with the project itself."""
    applied = applicable_profiles(db, project_id)
    by_profile, by_project = _project_rows(db, [a.profile_id for a in applied], chain, artefact_type)
    sources: dict[str, list[tuple[str, ReviewSettings]]] = defaultdict(list)
    own: dict[str, ReviewSettings] = {}
    ancestor: dict[str, uuid.UUID] = {}
    for profile in applied:
        for (profile_id, type_key), settings in sorted(by_profile.items(), key=lambda item: item[0][1]):
            if profile_id == profile.profile_id:
                sources[type_key].append((profile.name, settings))
    for type_key in sorted({t for _, t in by_project}):
        for depth, owner in enumerate(chain):
            if (owner, type_key) in by_project:
                settings = by_project[(owner, type_key)]
                if depth == 0:
                    own[type_key] = settings
                else:
                    ancestor[type_key] = owner
                sources[type_key].append(("project" if depth == 0 else "parent_project", settings))
                break
    return {t: _combine(given) for t, given in sources.items()}, own, ancestor


def resolve_policy(db: Session, project_id: uuid.UUID, artefact_type: str) -> ReviewPolicy | None:
    """`PolicyResolver.resolve` for `GovernanceSeam.REVIEW`: the review policy of a type in the project.

    Args:
        db: Active session (read only).
        project_id: The project.
        artefact_type: The registered record type.

    Returns:
        The combined settings of the profiles that apply and of the project's own row (else the nearest ancestor's); `None`
        when there are none, so the type keeps its own schedule.
    """
    merged, _, _ = _merge(db, project_id, get_project_chain_ids(db, project_id), artefact_type)
    effective = merged.get(artefact_type)
    if effective is None:
        return None
    policy = ReviewPolicy(
        interval_days=effective.interval_days, lead_days=effective.lead_days, default_owner=effective.default_owner,
    )
    return None if policy == ReviewPolicy() else policy


def project_policy(db: Session, project: Project) -> list[ProjectTypePolicy]:
    """A project's review policy for every type with a review schedule that is in effect for its organisation.

    Args:
        db: Active session (read only).
        project: The project.

    Returns:
        One entry per type in type-name order, with the project's own settings, the ancestor whose row applies and what
        applies, with its sources.
    """
    chain = get_project_chain_ids(db, project.id)
    merged, own, ancestor = _merge(db, project.id, chain, None)
    ancestor_names = project_names(db, list(ancestor.values()))
    empty = EffectiveReview(None, None, None, None, None, None)
    return [
        ProjectTypePolicy(
            review_type=t, own=own.get(t.artefact_type),
            inherited_from=None if (owner := ancestor.get(t.artefact_type)) is None else ancestor_names.get(owner),
            effective=merged.get(t.artefact_type, empty),
        )
        for t in review_types(db, project.organization_id)
    ]


def project_names(db: Session, project_ids: Sequence[uuid.UUID]) -> Mapping[uuid.UUID, str]:
    """The names of the given projects in one read."""
    if not project_ids:
        return {}
    return dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids))).tuples().all())


# --- the profile contributor ---------------------------------------------------------------------


def count_rows(db: Session, profile_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """`ProfileContributor.count_rows`: per profile, the record types it gives review settings for."""
    return {
        profile_id: count
        for profile_id, count in db.execute(
            select(GovernanceReviewPolicy.profile_id, func.count())
            .where(GovernanceReviewPolicy.profile_id.in_(profile_ids))
            .group_by(GovernanceReviewPolicy.profile_id)
        ).tuples()
        if profile_id is not None
    }


def _export(db: Session, policies: Sequence[GovernanceReviewPolicy]) -> list[dict[str, Any]]:
    """The rows as bundle entries ordered by type; the default owner by email or group name."""
    return [
        {
            "artefact_type": row.artefact_type, "interval_days": row.interval_days, "lead_days": row.lead_days,
            "default_owner": principal_to_bundle(db, row.default_owner_type, row.default_owner_id),
        }
        for row in sorted(policies, key=lambda r: r.artefact_type)
    ]


def export_rows(db: Session, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    """`ProfileContributor.export_rows`: one `review` entry per type the profile gives settings for, ordered by type."""
    policies = list(db.scalars(select(GovernanceReviewPolicy).where(GovernanceReviewPolicy.profile_id == profile_id)))
    return [{"kind": KIND_REVIEW, **entry} for entry in _export(db, policies)]


def _import_settings(
    db: Session, entry: Mapping[str, Any], *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
    warn: Callable[[str], None], what: str,
) -> ReviewSettings:
    """The bundle entry's settings resolved in the organisation. A value out of range and an owner who cannot be found are
    reported through `warn` and left out."""
    values: dict[str, int | None] = {}
    for key, (low, high) in (("interval_days", INTERVAL_DAYS_RANGE), ("lead_days", LEAD_DAYS_RANGE)):
        raw = entry.get(key)
        if isinstance(raw, int) and not isinstance(raw, bool) and low <= raw <= high:
            values[key] = raw
        else:
            values[key] = None
            if raw is not None:
                warn(f"The {key.replace('_', ' ')} of the review policy for {what} is out of range and was left out.")
    owner = None
    if entry.get("default_owner"):
        # An optional field never falls back to the importing user, so the fallback id is not used.
        owner, warning = principal_from_bundle(
            db, entry["default_owner"], organization_id=organization_id, project_id=project_id,
            fallback_user_id=uuid.UUID(int=0), required=False, context="Review policy default owner",
        )
        if warning:
            warn(f"The default owner of the review policy for {what}: {warning}")
    return ReviewSettings(values["interval_days"], values["lead_days"], owner)


def import_rows(db: Session, profile_id: uuid.UUID, rows: Sequence[dict[str, Any]], warn: Callable[[str], None]) -> None:
    """`ProfileContributor.import_rows`: writes the bundle's `review` entries into the profile. A type that has no review
    schedule here, a value out of range, an owner who cannot be found and an unknown entry are reported through `warn`."""
    profile = db.get(GovernanceProfile, profile_id)
    if profile is None:
        return
    known = registry.get_review_adapters()
    for entry in rows:
        if entry.get("kind") != KIND_REVIEW:
            warn("A review policy entry of an unknown kind was not imported.")
            continue
        artefact_type = str(entry.get("artefact_type", ""))
        if artefact_type not in known:
            warn(f"The review policy for {artefact_type or 'an unnamed type'} was not imported: the type has no review schedule here.")
            continue
        settings = _import_settings(
            db, entry, organization_id=profile.organization_id, project_id=None, warn=warn,
            what=registry.get_artefact_type_label(artefact_type),
        )
        if not settings.is_empty:
            _write(db, profile_id=profile_id, project_id=None, artefact_type=artefact_type, settings=settings)


# --- a project's own rows in its bundle ----------------------------------------------------------


def export_project_rows(db: Session, project: Project) -> list[dict[str, Any]]:
    """The project's own policy rows as bundle entries, ordered by type (an entry with nothing set is a kept choice)."""
    return _export(db, list(db.scalars(select(GovernanceReviewPolicy).where(GovernanceReviewPolicy.project_id == project.id))))


def import_project_rows(db: Session, project: Project, rows: Sequence[dict[str, Any]], warn: Callable[[str], None]) -> None:
    """Writes the bundle's entries as the project's own rows. A type with no review schedule here, a value out of range and
    an owner who cannot be found are reported through `warn` and left out."""
    known = registry.get_review_adapters()
    for entry in rows:
        artefact_type = str(entry.get("artefact_type", ""))
        if artefact_type not in known:
            warn(f"The review policy for {artefact_type or 'an unnamed type'} was not imported: the type has no review schedule here.")
            continue
        settings = _import_settings(
            db, entry, organization_id=project.organization_id, project_id=project.id, warn=warn,
            what=registry.get_artefact_type_label(artefact_type),
        )
        _write(db, profile_id=None, project_id=project.id, artefact_type=artefact_type, settings=settings)
