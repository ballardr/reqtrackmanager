"""
Module: services.scoring

Core, module-agnostic logic for configurable scoring matrices (Module 1 —
Context & Strategy — Phase 10). Modules register scoring schemes on
`ModuleDefinition.scoring_schemes`; this service seeds, edits, resolves and
computes against them using the scheme/axis/model *keys* only, so core
never contains module-specific code (Pain Points use it first; Risk,
Module 3, reuses it by registering its own scheme).

Responsibilities:
- Seeding each organisation's axis levels from registry defaults
  (`seed_missing_scoring_levels` on org creation/import,
  `sync_scoring_levels` at every process start, so modules installed after
  an org exists still get their levels).
- Level CRUD with the definition-table rules: ≥2 levels per axis, unique
  names and weights, and delete-with-reassignment via the scheme's own
  `count_level_usage`/`reassign_level_usage` hooks.
- Resolving the effective default model and rating bands along
  project → nearest ancestor → org → registry default, following
  `services.project_hierarchy.resolve_effective_action_types` (always on,
  independent of RBAC inheritance).
- Score maths: a model's score is the product of its axes' level weights;
  it is "not scored under this model" if any of those inputs is missing.
  Bands use the normalised score (score ÷ the model's maximum possible
  score) so they survive re-weighting.

Design decisions:
- Levels are org-only (module rows reference them by id), whereas the
  default model and bands are org defaults a project may override
  (Phase 9 Q3 and the Phase 10 sign-off, Decided by: User).
- Levels are ordered by weight, not a separate sort order (Decided by:
  Agent): the order a scorer sees and the maths can never disagree, and
  the top level (e.g. Severity "Blocker") is simply the highest weight.
- Unknown stored keys (e.g. a module dropped a model) are skipped during
  resolution rather than erroring, so a registry change degrades to the
  next tier instead of breaking reads.

All writers add to the session and audit-log via `services.audit.
log_event`; callers commit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.scoring import ScoringBand, ScoringLevel, ScoringModelDefault
from app.modules.registry import (
    RegisteredScoringScheme,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
    get_all_registered_scoring_schemes,
    validate_scoring_bands,
)
from app.services.audit import log_event
from app.services.project_hierarchy import get_ancestor_chain
from app.services.rbac import lock_organization_for_update

MIN_LEVELS_PER_AXIS = 2
# Matches the Numeric(10, 4)/Numeric(6, 4) column scale, so the value
# validated is the value stored (no silent rounding into a duplicate or 0).
_SCALE = Decimal("0.0001")


def _quantise(value: Decimal | float) -> Decimal:
    """Rounds a weight/threshold to the stored 4-decimal scale."""
    return Decimal(str(value)).quantize(_SCALE, rounding=ROUND_HALF_UP)


def _flush_or_conflict(db: Session) -> None:
    """Flushes, turning a unique-constraint race (two admins saving the
    same name/weight/default at once) into a 409 instead of a 500.

    Raises:
        HTTPException: 409 on an integrity violation.
    """
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This change conflicts with a concurrent update; reload and retry.") from exc


def _positive_weight(weight: Decimal) -> Decimal:
    """Quantises a level weight, rejecting one that rounds to ≤ 0.

    Raises:
        HTTPException: 400 if the stored weight would not be positive.
    """
    quantised = _quantise(weight)
    if quantised <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Weight must be at least 0.0001.")
    return quantised


@dataclass(frozen=True)
class BandValue:
    """One resolved rating band.

    Attributes:
        label: Display label.
        min_score: Normalised lower bound in [0, 1).
        tone: One of `SCORING_BAND_TONES`.
    """

    label: str
    min_score: float
    tone: str


@dataclass(frozen=True)
class ScoreResult:
    """A computed score under one model.

    Attributes:
        raw: Product of the model's axis level weights.
        normalised: `raw` ÷ the model's maximum possible score, in (0, 1].
        band: The matching rating band, or `None` if the model has none.
    """

    raw: Decimal
    normalised: float
    band: BandValue | None


# --- Registry lookup ---------------------------------------------------------


def get_registered_scheme(scheme_key: str) -> RegisteredScoringScheme:
    """Returns the registered scheme for `scheme_key`.

    Raises:
        HTTPException: 404 if no module registers that scheme.
    """
    registered = get_all_registered_scoring_schemes().get(scheme_key)
    if registered is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scoring scheme not found.")
    return registered


def _require_model(scheme: ScoringSchemeDefinition, model_key: str) -> ScoringModelDefinition:
    """Returns `scheme`'s model `model_key`.

    Raises:
        HTTPException: 400 if the scheme has no such model.
    """
    model = scheme.model(model_key)
    if model is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown scoring model '{model_key}'.")
    return model


# --- Seeding -----------------------------------------------------------------


def seed_missing_scoring_levels(db: Session, organization_id: UUID) -> int:
    """Adds registry-default levels for every registered axis the
    organisation has no levels for yet (not committed).

    Because an axis is never allowed below `MIN_LEVELS_PER_AXIS`, "no rows"
    always means "never seeded", never "deliberately emptied".

    Args:
        db: Active session.
        organization_id: The organisation to seed.

    Returns:
        The number of axes seeded.
    """
    existing = set(
        db.execute(
            select(ScoringLevel.scheme_key, ScoringLevel.axis_key)
            .where(ScoringLevel.organization_id == organization_id)
            .distinct()
        ).all()
    )
    seeded = 0
    for scheme_key, registered in get_all_registered_scoring_schemes().items():
        for axis in registered.scheme.axes:
            if (scheme_key, axis.key) in existing:
                continue
            for level in axis.default_levels:
                db.add(ScoringLevel(
                    organization_id=organization_id, scheme_key=scheme_key, axis_key=axis.key,
                    name=level.name, description=level.description or None, weight=Decimal(str(level.weight)),
                ))
            seeded += 1
    return seeded


def sync_scoring_levels(db: Session) -> None:
    """Seeds missing axis levels for every organisation and commits — run
    at every process start (`app.main` lifespan), the same self-healing
    pattern as `sync_module_role_definitions`, so a module installed or
    upgraded after organisations exist still gets its levels."""
    if not get_all_registered_scoring_schemes():
        return
    for organization_id in db.scalars(select(Organization.id)).all():
        seed_missing_scoring_levels(db, organization_id)
    db.commit()


# --- Levels ------------------------------------------------------------------


def list_levels(db: Session, organization_id: UUID, scheme_key: str) -> dict[str, list[ScoringLevel]]:
    """Returns an organisation's levels for a scheme, grouped by axis key
    and ordered by ascending weight."""
    rows = db.scalars(
        select(ScoringLevel)
        .where(ScoringLevel.organization_id == organization_id, ScoringLevel.scheme_key == scheme_key)
        .order_by(ScoringLevel.axis_key, ScoringLevel.weight)
    ).all()
    grouped: dict[str, list[ScoringLevel]] = {}
    for row in rows:
        grouped.setdefault(row.axis_key, []).append(row)
    return grouped


def get_level(db: Session, organization_id: UUID, scheme_key: str, level_id: UUID) -> ScoringLevel:
    """Returns a level of this organisation's scheme.

    Raises:
        HTTPException: 404 if it doesn't exist or belongs elsewhere.
    """
    level = db.get(ScoringLevel, level_id)
    if level is None or level.organization_id != organization_id or level.scheme_key != scheme_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scoring level not found.")
    return level


def _check_level_unique(
    db: Session, organization_id: UUID, scheme_key: str, axis_key: str, *,
    name: str | None, weight: Decimal | None, exclude_id: UUID | None,
) -> None:
    """Raises 400 if another level on the axis already has `name` (case-
    insensitive) or `weight`."""
    base = select(ScoringLevel.id).where(
        ScoringLevel.organization_id == organization_id, ScoringLevel.scheme_key == scheme_key,
        ScoringLevel.axis_key == axis_key,
    )
    if exclude_id is not None:
        base = base.where(ScoringLevel.id != exclude_id)
    if name is not None and db.scalar(base.where(func.lower(ScoringLevel.name) == name.lower())) is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A level with this name already exists on this axis.")
    if weight is not None and db.scalar(base.where(ScoringLevel.weight == weight)) is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A level with this weight already exists on this axis.")


def create_level(
    db: Session, organization_id: UUID, registered: RegisteredScoringScheme, axis_key: str, *,
    name: str, weight: Decimal, description: str | None, actor_id: UUID,
) -> ScoringLevel:
    """Adds a level to an axis (flushed, not committed) and audit-logs it.

    Raises:
        HTTPException: 404 for an unknown axis; 400 for a duplicate name or
            weight.
    """
    scheme = registered.scheme
    if scheme.axis(axis_key) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scoring axis not found.")
    weight = _positive_weight(weight)
    _check_level_unique(db, organization_id, scheme.key, axis_key, name=name, weight=weight, exclude_id=None)
    level = ScoringLevel(
        organization_id=organization_id, scheme_key=scheme.key, axis_key=axis_key,
        name=name, weight=weight, description=description or None,
    )
    db.add(level)
    _flush_or_conflict(db)
    log_event(db, entity_type="scoring_level", entity_id=level.id, action="created", actor_id=actor_id,
              organization_id=organization_id,
              detail={"scheme": scheme.key, "axis": axis_key, "name": name, "weight": str(weight)})
    return level


def update_level(
    db: Session, level: ScoringLevel, *, name: str | None, weight: Decimal | None,
    description: str | None, set_description: bool, actor_id: UUID,
) -> ScoringLevel:
    """Renames/re-weights/re-describes a level and audit-logs the change.
    References point at the level's id, so this never cascades; re-weighting
    changes every score computed from it, which is the intended effect.

    Raises:
        HTTPException: 400 for a duplicate name or weight (or a weight
            that rounds to ≤ 0); 409 on a concurrent conflicting save.
    """
    if weight is not None:
        weight = _positive_weight(weight)
    _check_level_unique(db, level.organization_id, level.scheme_key, level.axis_key,
                        name=name, weight=weight, exclude_id=level.id)
    changes: dict[str, str | None] = {}
    if name is not None and name != level.name:
        changes["name"] = name
        level.name = name
    if weight is not None and weight != level.weight:
        changes["weight"] = str(weight)
        level.weight = weight
    if set_description and (description or None) != level.description:
        changes["description"] = "updated"
        level.description = description or None
    _flush_or_conflict(db)
    if changes:
        log_event(db, entity_type="scoring_level", entity_id=level.id, action="updated", actor_id=actor_id,
                  organization_id=level.organization_id,
                  detail={"scheme": level.scheme_key, "axis": level.axis_key, **changes})
    return level


def delete_level(
    db: Session, level: ScoringLevel, registered: RegisteredScoringScheme, *,
    reassign_to_id: UUID | None, actor_id: UUID,
) -> None:
    """Deletes a level, reassigning module references first if needed.

    Raises:
        HTTPException: 409 if the axis would drop below
            `MIN_LEVELS_PER_AXIS`, or the level is in use and no
            `reassign_to_id` was given; 400 if `reassign_to_id` is the same
            level or on a different axis/org/scheme.
    """
    scheme = registered.scheme
    # Serialise deletes per org so two concurrent deletes can't both pass
    # the floor check and leave an axis below MIN_LEVELS_PER_AXIS.
    lock_organization_for_update(db, level.organization_id)
    siblings = db.scalar(
        select(func.count(ScoringLevel.id)).where(
            ScoringLevel.organization_id == level.organization_id, ScoringLevel.scheme_key == level.scheme_key,
            ScoringLevel.axis_key == level.axis_key,
        )
    )
    if (siblings or 0) <= MIN_LEVELS_PER_AXIS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"An axis must keep at least {MIN_LEVELS_PER_AXIS} levels.")
    in_use = scheme.count_level_usage(db, level.id) if scheme.count_level_usage else 0
    if in_use:
        if reassign_to_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"This level is used by {in_use} score(s); choose another level to move them to.",
            )
        target = db.get(ScoringLevel, reassign_to_id)
        if (
            target is None or target.id == level.id or target.organization_id != level.organization_id
            or target.scheme_key != level.scheme_key or target.axis_key != level.axis_key
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reassign to a different level on the same axis.")
        assert scheme.reassign_level_usage is not None  # guaranteed by ScoringSchemeDefinition validation
        scheme.reassign_level_usage(db, level.id, target.id)
    log_event(db, entity_type="scoring_level", entity_id=level.id, action="deleted", actor_id=actor_id,
              organization_id=level.organization_id,
              detail={"scheme": level.scheme_key, "axis": level.axis_key, "name": level.name,
                      "reassigned_to": str(reassign_to_id) if in_use else None})
    db.delete(level)


# --- Resolution (project → ancestor → org → system) -------------------------


def _project_lookup_chain(db: Session, project_id: UUID) -> list[UUID]:
    """Returns `[project_id, parent, grandparent, ...]` (cycle-safe, capped
    by `get_ancestor_chain`)."""
    return [project_id] + [p.id for p in reversed(get_ancestor_chain(db, project_id))]


def resolve_effective_model(
    db: Session, organization_id: UUID, scheme: ScoringSchemeDefinition, project_id: UUID | None = None,
) -> tuple[str, str]:
    """Resolves a scheme's default model.

    Args:
        db: Active session.
        organization_id: The owning organisation.
        scheme: The registered scheme.
        project_id: Resolve for this project (with ancestor fallback), or
            `None` for the org level.

    Returns:
        `(model_key, source)`, `source` being "project", "ancestor", "org"
        or "system".
    """
    if project_id is not None:
        chain = _project_lookup_chain(db, project_id)
        rows = {
            row.project_id: row.model_key
            for row in db.scalars(select(ScoringModelDefault).where(
                ScoringModelDefault.project_id.in_(chain), ScoringModelDefault.scheme_key == scheme.key,
            )).all()
        }
        for index, pid in enumerate(chain):
            key = rows.get(pid)
            if key is not None and scheme.model(key) is not None:
                return key, "project" if index == 0 else "ancestor"
    org_key = db.scalar(select(ScoringModelDefault.model_key).where(
        ScoringModelDefault.organization_id == organization_id, ScoringModelDefault.project_id.is_(None),
        ScoringModelDefault.scheme_key == scheme.key,
    ))
    if org_key is not None and scheme.model(org_key) is not None:
        return org_key, "org"
    return scheme.default_model_key, "system"


def _band_rows(db: Session, organization_id: UUID, project_id: UUID | None, scheme_key: str, model_key: str) -> list[ScoringBand]:
    """Returns one scope's stored band set, in order (may be empty)."""
    project_clause = ScoringBand.project_id.is_(None) if project_id is None else ScoringBand.project_id == project_id
    return list(db.scalars(
        select(ScoringBand).where(
            ScoringBand.organization_id == organization_id, project_clause,
            ScoringBand.scheme_key == scheme_key, ScoringBand.model_key == model_key,
        ).order_by(ScoringBand.sort_order)
    ).all())


def _to_band_values(rows: list[ScoringBand]) -> list[BandValue]:
    """Converts stored rows to `BandValue`s."""
    return [BandValue(label=r.label, min_score=float(r.min_score), tone=r.tone) for r in rows]


def resolve_effective_bands(
    db: Session, organization_id: UUID, scheme: ScoringSchemeDefinition, model_key: str,
    project_id: UUID | None = None,
) -> tuple[list[BandValue], str]:
    """Resolves the rating bands for one model.

    Returns:
        `(bands, source)`, `source` being "project", "ancestor", "org",
        "system" (registry defaults) or "none" (the model has no default
        bands and nothing is configured).

    Raises:
        HTTPException: 400 for an unknown model.
    """
    model = _require_model(scheme, model_key)
    if project_id is not None:
        for index, pid in enumerate(_project_lookup_chain(db, project_id)):
            rows = _band_rows(db, organization_id, pid, scheme.key, model_key)
            if rows:
                return _to_band_values(rows), "project" if index == 0 else "ancestor"
    rows = _band_rows(db, organization_id, None, scheme.key, model_key)
    if rows:
        return _to_band_values(rows), "org"
    if model.default_bands:
        return [BandValue(b.label, b.min_score, b.tone) for b in model.default_bands], "system"
    return [], "none"


# --- Default-model and band writers -----------------------------------------


def set_default_model(
    db: Session, organization_id: UUID, scheme: ScoringSchemeDefinition, model_key: str | None, *,
    project_id: UUID | None, actor_id: UUID,
) -> None:
    """Sets (or, with `model_key=None`, clears so it inherits) the org's or
    a project's default model, and audit-logs it.

    Raises:
        HTTPException: 400 for an unknown model.
    """
    if model_key is not None:
        _require_model(scheme, model_key)
    project_clause = (
        ScoringModelDefault.project_id.is_(None) if project_id is None else ScoringModelDefault.project_id == project_id
    )
    row = db.scalar(select(ScoringModelDefault).where(
        ScoringModelDefault.organization_id == organization_id, project_clause,
        ScoringModelDefault.scheme_key == scheme.key,
    ))
    if model_key is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(ScoringModelDefault(organization_id=organization_id, project_id=project_id,
                                   scheme_key=scheme.key, model_key=model_key))
    else:
        row.model_key = model_key
    _flush_or_conflict(db)
    log_event(db, entity_type="scoring_model_default", entity_id=project_id or organization_id,
              action="reset" if model_key is None else "set", actor_id=actor_id,
              organization_id=organization_id, project_id=project_id,
              detail={"scheme": scheme.key, "model": model_key})


def set_bands(
    db: Session, organization_id: UUID, scheme: ScoringSchemeDefinition, model_key: str,
    bands: list[BandValue] | None, *, project_id: UUID | None, actor_id: UUID,
) -> None:
    """Replaces (or, with `bands=None`, clears so it inherits) the org's or
    a project's band set for one model, and audit-logs it.

    Raises:
        HTTPException: 400 for an unknown model or an invalid band set
            (see `validate_scoring_bands`).
    """
    _require_model(scheme, model_key)
    if bands is not None:
        bands = [BandValue(b.label.strip(), float(_quantise(b.min_score)), b.tone) for b in bands]
        try:
            validate_scoring_bands([(b.label, b.min_score, b.tone) for b in bands])
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    project_clause = ScoringBand.project_id.is_(None) if project_id is None else ScoringBand.project_id == project_id
    db.execute(delete(ScoringBand).where(
        ScoringBand.organization_id == organization_id, project_clause,
        ScoringBand.scheme_key == scheme.key, ScoringBand.model_key == model_key,
    ))
    for index, band in enumerate(bands or []):
        db.add(ScoringBand(
            organization_id=organization_id, project_id=project_id, scheme_key=scheme.key, model_key=model_key,
            label=band.label, min_score=_quantise(band.min_score), tone=band.tone, sort_order=index,
        ))
    log_event(db, entity_type="scoring_band_set", entity_id=project_id or organization_id,
              action="reset" if bands is None else "set", actor_id=actor_id,
              organization_id=organization_id, project_id=project_id,
              detail={"scheme": scheme.key, "model": model_key,
                      "bands": [b.label for b in bands] if bands is not None else None})


# --- Score maths -------------------------------------------------------------


def band_for(normalised: float, bands: list[BandValue]) -> BandValue | None:
    """Returns the highest band whose `min_score` ≤ `normalised`, or `None`
    if `bands` is empty."""
    match: BandValue | None = None
    for band in bands:
        if normalised >= band.min_score:
            match = band
    return match


def max_axis_weights(levels_by_axis: Mapping[str, list[ScoringLevel]]) -> dict[str, Decimal]:
    """Returns each axis's top (maximum) level weight."""
    return {axis: max(level.weight for level in levels) for axis, levels in levels_by_axis.items() if levels}


def compute_score(
    model: ScoringModelDefinition, weights: Mapping[str, Decimal | None],
    max_weights: Mapping[str, Decimal], bands: list[BandValue],
) -> ScoreResult | None:
    """Scores one set of inputs under `model`.

    Args:
        model: The model to apply.
        weights: The chosen level weight per axis key (missing/`None` =
            not scored on that axis).
        max_weights: Each axis's top weight (`max_axis_weights`).
        bands: The model's resolved rating bands.

    Returns:
        The score, or `None` ("not scored under this model") if any of the
        model's axes has no input or no levels.
    """
    raw = Decimal(1)
    maximum = Decimal(1)
    for axis_key in model.axis_keys:
        weight = weights.get(axis_key)
        top = max_weights.get(axis_key)
        if weight is None or top is None:
            return None
        raw *= weight
        maximum *= top
    normalised = float(raw / maximum)
    return ScoreResult(raw=raw, normalised=normalised, band=band_for(normalised, bands))


# --- API read model -----------------------------------------------------------


def build_scheme_config(
    db: Session, organization_id: UUID, registered: RegisteredScoringScheme, project: Project | None = None,
) -> dict:
    """Builds the full effective configuration of a scheme for the org (or
    for `project`, with its overrides resolved), as returned by the API.

    Returns:
        A dict matching `schemas.scoring.ScoringSchemeOut`.
    """
    scheme = registered.scheme
    project_id = project.id if project is not None else None
    levels = list_levels(db, organization_id, scheme.key)
    model_key, model_source = resolve_effective_model(db, organization_id, scheme, project_id)
    models = []
    for model in scheme.models:
        bands, source = resolve_effective_bands(db, organization_id, scheme, model.key, project_id)
        models.append({
            "key": model.key, "label": model.label, "axis_keys": list(model.axis_keys),
            "bands": [b.__dict__ for b in bands], "bands_source": source,
        })
    return {
        "key": scheme.key, "label": scheme.label, "module_key": registered.module_key,
        "axes": [
            {
                "key": axis.key, "label": axis.label, "description": axis.description or None,
                "levels": [
                    {"id": lvl.id, "name": lvl.name, "description": lvl.description, "weight": float(lvl.weight)}
                    for lvl in levels.get(axis.key, [])
                ],
            }
            for axis in scheme.axes
        ],
        "models": models,
        "system_default_model_key": scheme.default_model_key,
        "default_model_key": model_key,
        "default_model_source": model_source,
    }
