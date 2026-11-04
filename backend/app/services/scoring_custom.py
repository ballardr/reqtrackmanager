"""
Module: services.scoring_custom

Organisation- and project-defined scoring criteria, on top of the registered ones (`services.scoring`).

A scheme that sets `ScoringSchemeDefinition.allow_custom_criteria` has registered axes and models (the module's
own) and may also have axes and models an organisation, or one project, defined for itself. This module resolves
which of them apply where, and writes them.

Responsibilities:
- `resolve_criteria` / `effective_scheme`: the scheme as it applies to an organisation or a project, as a plain
  `ScoringSchemeDefinition` with the custom axes and models added and the hidden ones left out, so every other
  function in `services.scoring` (levels, bands, enabled models, score maths) works on it unchanged.
- Create, edit and delete a custom axis (with its levels) and a custom model (a product with divisors and
  exponents, or a weighted sum), at either tier.
- Hide and restore a registered or inherited criterion.
- Carry the definitions in a bundle (`export_definitions` / `import_definitions`).

Design decisions:
- A project's criteria are an additive layer, not a replacement: the effective set is the registered criteria, the
  organisation's, then those of every project down the chain to the one asked about, minus what is hidden. A
  project that adds one axis keeps the rest (**Decided by: User**).
- A registered criterion can be hidden (by the organisation for itself, by a project with a
  `ProjectDefinitionSuppression` tombstone) but never edited away or deleted; a custom one is fully editable
  (**Decided by: User**). A hidden criterion stops being offered; scores already stored on it are kept and ignored.
  A tombstone applies to its own project only, like every other hidden default.
- Keys are generated (`c_...`, `m_...`) and unique per organisation and scheme across every tier, so a stored
  level, band or score names a criterion without saying which project owns it.
- A model is available only where every axis it uses is. Hiding or deleting an axis a model needs is refused for a
  deletion and quietly drops the model for a hide.
- Deleting an axis that scores use needs `clear_scores`: levels cannot be reassigned to a different axis, so the
  choice is to drop those levels' scores (**Decided by: Agent**).
- Levels of a custom axis are ordinary `ScoringLevel` rows; a project-owned axis's levels carry the project so
  they go with it.

All writers add to the session and audit-log via `services.audit.log_event`; callers commit.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.scoring import (
    ScoringBand,
    ScoringCellRating,
    ScoringCustomAxis,
    ScoringCustomModel,
    ScoringEnabledModel,
    ScoringHiddenCriterion,
    ScoringLevel,
    ScoringModelDefault,
)
from app.modules.registry import (
    RegisteredScoringScheme,
    ScoringAxisDefinition,
    ScoringBandDefault,
    ScoringLevelDefault,
    ScoringModelDefinition,
    ScoringSchemeDefinition,
    validate_scoring_model_maths,
)
from app.services import definition_suppression as suppression
from app.services.audit import log_event
from app.services.scoring import _flush_or_conflict, _positive_weight, list_levels  # shared level rules
from app.services.scoring import _project_lookup_chain as project_chain

AXIS = "axis"
MODEL = "model"
MAX_CUSTOM_LEVELS = 12
_AXIS_PREFIX, _MODEL_PREFIX = "c_", "m_"
_ID_NAMESPACE = uuid.UUID("5f3a3c1e-7a0b-4c5e-9c7e-2f6d8e1a4b90")

#: Bands a custom model starts with (an organisation or project may replace them like any other set).
CUSTOM_MODEL_BANDS = (
    ScoringBandDefault("Low", 0.0, "muted"),
    ScoringBandDefault("Medium", 0.34, "info"),
    ScoringBandDefault("High", 0.67, "accent"),
)


@dataclass(frozen=True)
class ModelAxisSpec:
    """How a model uses one axis.

    Attributes:
        axis_key: The axis.
        role: `"multiply"` or `"divide"` in a product; `"sum"` in a weighted sum.
        exponent: Product only: the importance exponent (1 = plain).
        importance: Weighted sum only: the percentage this axis carries (all total 100).
        lower_is_better: Weighted sum only: a lower level scores higher (the counterpart of a divisor).
    """

    axis_key: str
    role: str
    exponent: float = 1.0
    importance: float | None = None
    lower_is_better: bool = False


@dataclass(frozen=True)
class LevelSpec:
    """A level supplied when creating an axis."""

    name: str
    weight: float
    description: str | None = None


@dataclass
class Criteria:
    """The criteria in force for one tier.

    Attributes:
        scheme: The effective scheme (registered + custom, minus hidden).
        axis_origin / model_origin: `key -> (origin, owner project id)`, origin being `"built_in"`, `"org"` or
            `"project"`.
        hidden: What this tier hid and can restore: `{"kind", "key", "label"}` entries.
        degraded: True when hiding left no model, so the registered scheme is returned unchanged rather than one
            that cannot score; a write that would cause this is refused.
    """

    scheme: ScoringSchemeDefinition
    axis_origin: dict[str, tuple[str, uuid.UUID | None]] = field(default_factory=dict)
    model_origin: dict[str, tuple[str, uuid.UUID | None]] = field(default_factory=dict)
    hidden: list[dict[str, str]] = field(default_factory=list)
    degraded: bool = False


# --- Identity of registered criteria for tombstones -------------------------------------------------------------------


def definition_kind(scheme_key: str, kind: str) -> str:
    """The `ProjectDefinitionSuppression` kind for a scheme's axes or models (registered on first use)."""
    name = f"scoring_{kind}:{scheme_key}"
    suppression.register_definition_kind(name)
    return name


def registered_criterion_id(scheme_key: str, kind: str, key: str) -> uuid.UUID:
    """A stable id for a registered axis or model, so a tombstone can name it like it names a stored row."""
    return uuid.uuid5(_ID_NAMESPACE, f"{scheme_key}:{kind}:{key}")


# --- Loading and resolving ------------------------------------------------------------------------------------------


def _model_from_row(row: ScoringCustomModel) -> ScoringModelDefinition:
    """Builds the runtime model definition from a stored custom model."""
    axes = row.definition["axes"]
    multiplied = tuple(a["axis_key"] for a in axes if a["role"] in ("multiply", "sum"))
    divided = tuple(a["axis_key"] for a in axes if a["role"] == "divide")
    return ScoringModelDefinition(
        key=row.key, label=row.label, axis_keys=multiplied, divisor_axis_keys=divided,
        default_bands=CUSTOM_MODEL_BANDS, combination=row.definition["combination"],
        exponents=tuple(
            (a["axis_key"], float(a["exponent"])) for a in axes if a["role"] in ("multiply", "divide") and float(a["exponent"]) != 1
        ),
        importance=tuple((a["axis_key"], float(a["importance"])) for a in axes if a["role"] == "sum"),
        inverted_axis_keys=tuple(a["axis_key"] for a in axes if a["role"] == "sum" and a.get("lower_is_better")),
    )


def _axis_from_row(row: ScoringCustomAxis, levels: list[ScoringLevel]) -> ScoringAxisDefinition | None:
    """Builds the runtime axis definition from a stored axis and its levels (`None` while it has fewer than two)."""
    if len(levels) < 2:
        return None
    return ScoringAxisDefinition(
        key=row.key, label=row.label, description=row.description or "",
        default_levels=tuple(ScoringLevelDefault(lvl.name, float(lvl.weight), lvl.description or "") for lvl in levels),
    )


def resolve_criteria(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, project_id: uuid.UUID | None = None,
) -> Criteria:
    """Resolves the criteria in force for the organisation, or for a project (with its ancestors').

    Args:
        db: Active session (read only).
        organization_id: The owning organisation.
        scheme: The registered scheme.
        project_id: The project asked about, or `None` for the organisation.

    Returns:
        The effective scheme and where each criterion came from. A scheme that does not allow custom criteria is
        returned as registered.
    """
    criteria = Criteria(
        scheme=scheme,
        axis_origin={a.key: ("built_in", None) for a in scheme.axes},
        model_origin={m.key: ("built_in", None) for m in scheme.models},
    )
    if not scheme.allow_custom_criteria:
        return criteria
    chain = list(reversed(project_chain(db, project_id))) if project_id is not None else []
    tiers: list[uuid.UUID | None] = [None, *chain]
    axis_rows = [
        r for r in db.scalars(select(ScoringCustomAxis).where(
            ScoringCustomAxis.organization_id == organization_id, ScoringCustomAxis.scheme_key == scheme.key,
        ).order_by(ScoringCustomAxis.created_at, ScoringCustomAxis.key)) if r.project_id in tiers
    ]
    model_rows = [
        r for r in db.scalars(select(ScoringCustomModel).where(
            ScoringCustomModel.organization_id == organization_id, ScoringCustomModel.scheme_key == scheme.key,
        ).order_by(ScoringCustomModel.created_at, ScoringCustomModel.key)) if r.project_id in tiers
    ]
    org_hidden = {
        (r.kind, r.key) for r in db.scalars(select(ScoringHiddenCriterion).where(
            ScoringHiddenCriterion.organization_id == organization_id, ScoringHiddenCriterion.scheme_key == scheme.key,
        ))
    }
    project_hidden = {
        kind: suppression.get_suppressed_ids(db, project_id, definition_kind(scheme.key, kind)) if project_id else set()
        for kind in (AXIS, MODEL)
    }
    levels_by_axis = list_levels(db, organization_id, scheme.key)

    def hidden_here(kind: str, key: str, row_id: uuid.UUID | None) -> bool:
        stored_id = row_id or registered_criterion_id(scheme.key, kind, key)
        return (kind, key) in org_hidden or stored_id in project_hidden[kind]

    axes = [a for a in scheme.axes if not hidden_here(AXIS, a.key, None)]
    models = [m for m in scheme.models if not hidden_here(MODEL, m.key, None)]
    for row in axis_rows:
        axis = _axis_from_row(row, levels_by_axis.get(row.key, []))
        if axis is not None and row.key not in {a.key for a in axes} and not hidden_here(AXIS, row.key, row.id):
            axes.append(axis)
            criteria.axis_origin[row.key] = ("org" if row.project_id is None else "project", row.project_id)
    axis_keys = {a.key for a in axes}
    for model_row in model_rows:
        model = _model_from_row(model_row)
        if (
            {*model.axis_keys, *model.divisor_axis_keys} <= axis_keys and model_row.key not in {m.key for m in models}
            and not hidden_here(MODEL, model_row.key, model_row.id)
        ):
            models.append(model)
            criteria.model_origin[model_row.key] = ("org" if model_row.project_id is None else "project", model_row.project_id)
    models = [m for m in models if {*m.axis_keys, *m.divisor_axis_keys} <= axis_keys]
    if models:
        default_key = scheme.default_model_key if any(m.key == scheme.default_model_key for m in models) else models[0].key
        criteria.scheme = replace(scheme, axes=tuple(axes), models=tuple(models), default_model_key=default_key)
    else:
        criteria.degraded = True
    criteria.axis_origin = {k: v for k, v in criteria.axis_origin.items() if k in {a.key for a in criteria.scheme.axes}}
    criteria.model_origin = {k: v for k, v in criteria.model_origin.items() if k in {m.key for m in criteria.scheme.models}}
    labels = {
        (AXIS, a.key): a.label for a in scheme.axes
    } | {(MODEL, m.key): m.label for m in scheme.models} | {(AXIS, r.key): r.label for r in axis_rows} | {
        (MODEL, r.key): r.label for r in model_rows
    }
    if project_id is None:
        criteria.hidden = [{"kind": k, "key": key, "label": labels.get((k, key), key)} for k, key in sorted(org_hidden)]
    else:
        ids = {registered_criterion_id(scheme.key, k, key): (k, key) for (k, key) in labels if not key.startswith(("c_", "m_"))}
        ids |= {r.id: (AXIS, r.key) for r in axis_rows} | {r.id: (MODEL, r.key) for r in model_rows}
        for kind in (AXIS, MODEL):
            for hidden_id in project_hidden[kind]:
                found = ids.get(hidden_id)
                if found is not None and found[0] == kind:
                    criteria.hidden.append({"kind": kind, "key": found[1], "label": labels[found]})
    return criteria


def effective_scheme(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, project_id: uuid.UUID | None = None,
) -> ScoringSchemeDefinition:
    """`resolve_criteria(...).scheme`: the scheme as it applies to the organisation or project."""
    return resolve_criteria(db, organization_id, scheme, project_id).scheme


def effective_registered(
    db: Session, organization_id: uuid.UUID, registered: RegisteredScoringScheme, project_id: uuid.UUID | None = None,
) -> RegisteredScoringScheme:
    """`registered` with its scheme replaced by the effective one, for the functions that take a registered scheme."""
    return replace(registered, scheme=effective_scheme(db, organization_id, registered.scheme, project_id))


# --- Ownership ------------------------------------------------------------------------------------------------------


def _require_custom_allowed(scheme: ScoringSchemeDefinition) -> None:
    if not scheme.allow_custom_criteria:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This scoring scheme does not take custom criteria.")


def _custom_axis(db: Session, organization_id: uuid.UUID, scheme_key: str, key: str) -> ScoringCustomAxis | None:
    return db.scalar(select(ScoringCustomAxis).where(
        ScoringCustomAxis.organization_id == organization_id, ScoringCustomAxis.scheme_key == scheme_key,
        ScoringCustomAxis.key == key,
    ))


def _custom_model(db: Session, organization_id: uuid.UUID, scheme_key: str, key: str) -> ScoringCustomModel | None:
    return db.scalar(select(ScoringCustomModel).where(
        ScoringCustomModel.organization_id == organization_id, ScoringCustomModel.scheme_key == scheme_key,
        ScoringCustomModel.key == key,
    ))


def require_axis_editable(
    db: Session, organization_id: uuid.UUID, scheme_key: str, axis_key: str, project_id: uuid.UUID | None,
) -> None:
    """Raises 403 unless the tier (`project_id`, or the organisation) may edit the levels of `axis_key`: a
    registered axis is the organisation's to edit, a custom one belongs to the tier that defined it.

    Raises:
        HTTPException: 403 for an axis owned by another tier.
    """
    row = _custom_axis(db, organization_id, scheme_key, axis_key)
    owner = row.project_id if row is not None else None
    if owner != project_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This criterion belongs to another tier; change it there.")


def axis_owner(db: Session, organization_id: uuid.UUID, scheme_key: str, axis_key: str) -> uuid.UUID | None:
    """The project that owns `axis_key` (its custom axis's project), or `None` for a registered or organisation axis."""
    row = _custom_axis(db, organization_id, scheme_key, axis_key)
    return row.project_id if row is not None else None


# --- Keys and validation --------------------------------------------------------------------------------------------


def _unique_key(db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, prefix: str, label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "x"
    taken = (
        {a.key for a in scheme.axes} | set(db.scalars(select(ScoringCustomAxis.key).where(
            ScoringCustomAxis.organization_id == organization_id, ScoringCustomAxis.scheme_key == scheme.key)))
        if prefix == _AXIS_PREFIX else
        {m.key for m in scheme.models} | set(db.scalars(select(ScoringCustomModel.key).where(
            ScoringCustomModel.organization_id == organization_id, ScoringCustomModel.scheme_key == scheme.key)))
    )
    key, number = f"{prefix}{slug}", 1
    while key in taken:
        number += 1
        key = f"{prefix}{slug}_{number}"
    return key


def _clean_label(label: str) -> str:
    cleaned = label.strip()
    if not cleaned or len(cleaned) > 100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A name is required (up to 100 characters).")
    return cleaned


def _check_levels(levels: list[LevelSpec]) -> list[tuple[str, Any, str | None]]:
    """Validates the levels of a new axis, returning `(name, quantised weight, description)`."""
    if not 2 <= len(levels) <= MAX_CUSTOM_LEVELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"An axis needs between 2 and {MAX_CUSTOM_LEVELS} levels.")
    out = [(_clean_label(lvl.name), _positive_weight(_decimal(lvl.weight)), lvl.description) for lvl in levels]
    if len({name.lower() for name, _, _ in out}) != len(out) or len({w for _, w, _ in out}) != len(out):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Level names and weights must each be unique on an axis.")
    return out


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _model_definition(visible: ScoringSchemeDefinition, combination: str, axes: list[ModelAxisSpec]) -> dict:
    """Validates a model's axes against what the tier can see and returns the stored `definition`.

    Raises:
        HTTPException: 400 for an unknown or repeated axis, a role that does not suit the combination, no
            multiplied axis, or invalid exponents or importances.
    """
    keys = [a.axis_key for a in axes]
    if len(set(keys)) != len(keys) or not axes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A model needs at least one axis, each used once.")
    unknown = [k for k in keys if visible.axis(k) is None]
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown or unavailable axis: {', '.join(unknown)}.")
    allowed = {"multiply", "divide"} if combination == "product" else {"sum"}
    if combination not in ("product", "weighted_sum") or any(a.role not in allowed for a in axes):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The roles do not suit the combination.")
    if combination == "product" and not any(a.role == "multiply" for a in axes):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A product needs at least one multiplied axis.")
    definition = {"combination": combination, "axes": [
        {
            "axis_key": a.axis_key, "role": a.role, "exponent": a.exponent if combination == "product" else 1.0,
            "importance": a.importance if combination == "weighted_sum" else None,
            "lower_is_better": bool(a.lower_is_better) if combination == "weighted_sum" else False,
        }
        for a in axes
    ]}
    probe = ScoringCustomModel(key="m_probe", label="probe", definition=definition)
    try:
        validate_scoring_model_maths(_model_from_row(probe))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return definition


# --- Axes -----------------------------------------------------------------------------------------------------------


def create_axis(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, *, project_id: uuid.UUID | None,
    label: str, description: str | None, levels: list[LevelSpec], actor_id: uuid.UUID | None,
) -> ScoringCustomAxis:
    """Defines a new axis with its levels for the organisation or a project (flushed, not committed).

    Raises:
        HTTPException: 400 if the scheme takes no custom criteria, the name repeats a visible axis, or the levels
            are invalid.
    """
    _require_custom_allowed(scheme)
    label = _clean_label(label)
    visible = effective_scheme(db, organization_id, scheme, project_id)
    if label.lower() in {a.label.lower() for a in visible.axes}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An axis with this name already exists here.")
    checked = _check_levels(levels)
    row = ScoringCustomAxis(
        organization_id=organization_id, project_id=project_id, scheme_key=scheme.key,
        key=_unique_key(db, organization_id, scheme, _AXIS_PREFIX, label), label=label, description=description or None,
    )
    db.add(row)
    for name, weight, text in checked:
        db.add(ScoringLevel(
            organization_id=organization_id, project_id=project_id, scheme_key=scheme.key, axis_key=row.key,
            name=name, weight=weight, description=text or None,
        ))
    _flush_or_conflict(db)
    log_event(db, entity_type="scoring_axis", entity_id=row.id, action="created", actor_id=actor_id,
              organization_id=organization_id, project_id=project_id,
              detail={"scheme": scheme.key, "axis": row.key, "label": label, "levels": len(checked)})
    return row


def update_axis(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, axis_key: str, *,
    project_id: uuid.UUID | None, label: str | None, description: str | None, set_description: bool, actor_id: uuid.UUID,
) -> ScoringCustomAxis:
    """Renames or re-describes a custom axis owned by this tier.

    Raises:
        HTTPException: 404 for an unknown axis or one another tier owns; 400 for a name a visible axis has.
    """
    row = _owned_axis(db, organization_id, scheme.key, axis_key, project_id)
    changes: dict[str, str] = {}
    if label is not None and _clean_label(label) != row.label:
        label = _clean_label(label)
        visible = effective_scheme(db, organization_id, scheme, project_id)
        if label.lower() in {a.label.lower() for a in visible.axes if a.key != row.key}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "An axis with this name already exists here.")
        row.label = label
        changes["label"] = label
    if set_description and (description or None) != row.description:
        row.description = description or None
        changes["description"] = "updated"
    _flush_or_conflict(db)
    if changes:
        log_event(db, entity_type="scoring_axis", entity_id=row.id, action="updated", actor_id=actor_id,
                  organization_id=organization_id, project_id=project_id,
                  detail={"scheme": scheme.key, "axis": row.key, **changes})
    return row


def _owned_axis(db: Session, organization_id: uuid.UUID, scheme_key: str, axis_key: str, project_id: uuid.UUID | None) -> ScoringCustomAxis:
    row = _custom_axis(db, organization_id, scheme_key, axis_key)
    if row is None or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scoring axis not found.")
    return row


def delete_axis(
    db: Session, organization_id: uuid.UUID, registered: RegisteredScoringScheme, axis_key: str, *,
    project_id: uuid.UUID | None, clear_scores: bool, actor_id: uuid.UUID,
) -> None:
    """Deletes a custom axis owned by this tier, with its levels.

    Raises:
        HTTPException: 404 for an unknown axis or one another tier owns; 409 if a model still uses it, or scores
            use it and `clear_scores` was not given.
    """
    scheme = registered.scheme
    row = _owned_axis(db, organization_id, scheme.key, axis_key, project_id)
    users = [
        m.label for m in db.scalars(select(ScoringCustomModel).where(
            ScoringCustomModel.organization_id == organization_id, ScoringCustomModel.scheme_key == scheme.key))
        if axis_key in {a["axis_key"] for a in m.definition["axes"]}
    ]
    if users:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Model(s) still use this axis: {', '.join(sorted(users))}.")
    levels = list_levels(db, organization_id, scheme.key).get(axis_key, [])
    in_use = sum(scheme.count_level_usage(db, lvl.id) for lvl in levels) if scheme.count_level_usage else 0
    if in_use and not clear_scores:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{in_use} score(s) use this axis; delete it with clear_scores to drop them.",
        )
    for level in levels:
        db.delete(level)
    suppression.forget_definition(db, definition_kind(scheme.key, AXIS), row.id)
    log_event(db, entity_type="scoring_axis", entity_id=row.id, action="deleted", actor_id=actor_id,
              organization_id=organization_id, project_id=project_id,
              detail={"scheme": scheme.key, "axis": row.key, "label": row.label, "scores_cleared": in_use})
    db.delete(row)
    db.flush()


# --- Models ---------------------------------------------------------------------------------------------------------


def create_model(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, *, project_id: uuid.UUID | None,
    label: str, combination: str, axes: list[ModelAxisSpec], actor_id: uuid.UUID | None,
) -> ScoringCustomModel:
    """Defines a new model for the organisation or a project (flushed, not committed).

    Raises:
        HTTPException: 400 for a name a visible model has, or invalid axes, roles, exponents or importances.
    """
    _require_custom_allowed(scheme)
    label = _clean_label(label)
    visible = effective_scheme(db, organization_id, scheme, project_id)
    if label.lower() in {m.label.lower() for m in visible.models}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A model with this name already exists here.")
    row = ScoringCustomModel(
        organization_id=organization_id, project_id=project_id, scheme_key=scheme.key,
        key=_unique_key(db, organization_id, scheme, _MODEL_PREFIX, label), label=label,
        definition=_model_definition(visible, combination, axes),
    )
    db.add(row)
    _flush_or_conflict(db)
    log_event(db, entity_type="scoring_model", entity_id=row.id, action="created", actor_id=actor_id,
              organization_id=organization_id, project_id=project_id,
              detail={"scheme": scheme.key, "model": row.key, "label": label, "combination": combination})
    return row


def update_model(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, model_key: str, *,
    project_id: uuid.UUID | None, label: str | None, combination: str | None, axes: list[ModelAxisSpec] | None,
    actor_id: uuid.UUID,
) -> ScoringCustomModel:
    """Renames a custom model owned by this tier and/or replaces how it combines its axes. A change to its axes
    drops its per-cell ratings (they name levels of the old axes); bands are kept (they are normalised).

    Raises:
        HTTPException: 404 for an unknown model or one another tier owns; 400 for invalid axes or a repeated name.
    """
    row = _owned_model(db, organization_id, scheme.key, model_key, project_id)
    visible = effective_scheme(db, organization_id, scheme, project_id)
    changes: dict[str, Any] = {}
    if label is not None and _clean_label(label) != row.label:
        label = _clean_label(label)
        if label.lower() in {m.label.lower() for m in visible.models if m.key != row.key}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A model with this name already exists here.")
        row.label = label
        changes["label"] = label
    if axes is not None:
        definition = _model_definition(visible, combination or row.definition["combination"], axes)
        if definition != row.definition:
            row.definition = definition
            changes["definition"] = "updated"
            db.execute(delete(ScoringCellRating).where(
                ScoringCellRating.organization_id == organization_id, ScoringCellRating.scheme_key == scheme.key,
                ScoringCellRating.model_key == row.key,
            ))
    _flush_or_conflict(db)
    if changes:
        log_event(db, entity_type="scoring_model", entity_id=row.id, action="updated", actor_id=actor_id,
                  organization_id=organization_id, project_id=project_id,
                  detail={"scheme": scheme.key, "model": row.key, **changes})
    return row


def _owned_model(db: Session, organization_id: uuid.UUID, scheme_key: str, model_key: str, project_id: uuid.UUID | None) -> ScoringCustomModel:
    row = _custom_model(db, organization_id, scheme_key, model_key)
    if row is None or row.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scoring model not found.")
    return row


def delete_model(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, model_key: str, *,
    project_id: uuid.UUID | None, actor_id: uuid.UUID,
) -> None:
    """Deletes a custom model owned by this tier, with its bands, cell ratings, default and enabled rows, wherever
    set (no record names a model, so nothing needs reassigning).

    Raises:
        HTTPException: 404 for an unknown model or one another tier owns; 409 if it is the only model left.
    """
    row = _owned_model(db, organization_id, scheme.key, model_key, project_id)
    if len(effective_scheme(db, organization_id, scheme, project_id).models) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A scheme needs at least one model.")
    for table in (ScoringBand, ScoringCellRating, ScoringModelDefault, ScoringEnabledModel):
        db.execute(delete(table).where(
            table.organization_id == organization_id, table.scheme_key == scheme.key, table.model_key == row.key,
        ))
    suppression.forget_definition(db, definition_kind(scheme.key, MODEL), row.id)
    log_event(db, entity_type="scoring_model", entity_id=row.id, action="deleted", actor_id=actor_id,
              organization_id=organization_id, project_id=project_id,
              detail={"scheme": scheme.key, "model": row.key, "label": row.label})
    db.delete(row)
    db.flush()


# --- Hiding ---------------------------------------------------------------------------------------------------------


def hide_criterion(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, kind: str, key: str, *,
    project_id: uuid.UUID | None, actor_id: uuid.UUID | None,
) -> None:
    """Hides a criterion this tier did not define: the organisation hides registered ones, a project hides any it
    sees from above (idempotent). It stays hidden until restored; stored scores are kept.

    Raises:
        HTTPException: 400 for a bad kind or a criterion the tier cannot hide; 409 if nothing would be left to score
            with.
    """
    _require_custom_allowed(scheme)
    if kind not in (AXIS, MODEL):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hide an axis or a model.")
    visible = resolve_criteria(db, organization_id, scheme, project_id)
    origins = visible.axis_origin if kind == AXIS else visible.model_origin
    origin = origins.get(key)
    if origin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scoring criterion not found.")
    if origin[0] != "built_in" and origin[1] == project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Delete a criterion this tier defined instead of hiding it.")
    if project_id is None:
        exists = db.scalar(select(ScoringHiddenCriterion.id).where(
            ScoringHiddenCriterion.organization_id == organization_id, ScoringHiddenCriterion.scheme_key == scheme.key,
            ScoringHiddenCriterion.kind == kind, ScoringHiddenCriterion.key == key))
        if exists is None:
            db.add(ScoringHiddenCriterion(organization_id=organization_id, scheme_key=scheme.key, kind=kind, key=key))
    else:
        suppression.hide_definition(
            db, project_id, definition_kind(scheme.key, kind), _row_id(db, organization_id, scheme.key, kind, key),
        )
    db.flush()
    if resolve_criteria(db, organization_id, scheme, project_id).degraded:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hiding this would leave no model to score with.")
    log_event(db, entity_type=f"scoring_{kind}_hidden", entity_id=project_id or organization_id, action="hidden",
              actor_id=actor_id, organization_id=organization_id, project_id=project_id,
              detail={"scheme": scheme.key, kind: key})


def _row_id(db: Session, organization_id: uuid.UUID, scheme_key: str, kind: str, key: str) -> uuid.UUID:
    """The id a tombstone uses for a criterion: its stored row, or the stable id of a registered one."""
    row = _custom_axis(db, organization_id, scheme_key, key) if kind == AXIS else _custom_model(db, organization_id, scheme_key, key)
    return row.id if row is not None else registered_criterion_id(scheme_key, kind, key)


def restore_criterion(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, kind: str, key: str, *,
    project_id: uuid.UUID | None, actor_id: uuid.UUID,
) -> bool:
    """Makes a criterion this tier hid visible again.

    Returns:
        Whether anything was hidden.
    """
    if kind not in (AXIS, MODEL):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Restore an axis or a model.")
    if project_id is None:
        result = db.execute(delete(ScoringHiddenCriterion).where(
            ScoringHiddenCriterion.organization_id == organization_id, ScoringHiddenCriterion.scheme_key == scheme.key,
            ScoringHiddenCriterion.kind == kind, ScoringHiddenCriterion.key == key))
        restored = bool(result.rowcount)
    else:
        restored = bool(suppression.restore_definitions(
            db, project_id, definition_kind(scheme.key, kind), {_row_id(db, organization_id, scheme.key, kind, key)},
        ))
    if restored:
        log_event(db, entity_type=f"scoring_{kind}_hidden", entity_id=project_id or organization_id, action="restored",
                  actor_id=actor_id, organization_id=organization_id, project_id=project_id,
                  detail={"scheme": scheme.key, kind: key})
    return restored


# --- Bundles --------------------------------------------------------------------------------------------------------


def export_definitions(db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, project_id: uuid.UUID | None) -> dict[str, Any]:
    """The custom axes (with levels), custom models and hidden registered criteria this tier owns, as bundle data.
    Bands, defaults, enabled models and the registered axes' levels are scoring configuration, which a bundle does
    not carry."""
    if not scheme.allow_custom_criteria:
        return {}
    levels = list_levels(db, organization_id, scheme.key)
    axes = db.scalars(select(ScoringCustomAxis).where(
        ScoringCustomAxis.organization_id == organization_id, ScoringCustomAxis.scheme_key == scheme.key,
        ScoringCustomAxis.project_id.is_(None) if project_id is None else ScoringCustomAxis.project_id == project_id,
    ).order_by(ScoringCustomAxis.created_at, ScoringCustomAxis.key)).all()
    models = db.scalars(select(ScoringCustomModel).where(
        ScoringCustomModel.organization_id == organization_id, ScoringCustomModel.scheme_key == scheme.key,
        ScoringCustomModel.project_id.is_(None) if project_id is None else ScoringCustomModel.project_id == project_id,
    ).order_by(ScoringCustomModel.created_at, ScoringCustomModel.key)).all()
    hidden = [h for h in resolve_criteria(db, organization_id, scheme, project_id).hidden if not h["key"].startswith(("c_", "m_"))]
    return {
        "axes": [
            {"key": a.key, "label": a.label, "description": a.description,
             "levels": [{"name": lvl.name, "weight": float(lvl.weight), "description": lvl.description} for lvl in levels.get(a.key, [])]}
            for a in axes
        ],
        "models": [{"key": m.key, "label": m.label, "definition": m.definition} for m in models],
        "hidden": [{"kind": h["kind"], "key": h["key"]} for h in hidden],
    }


def import_definitions(
    db: Session, organization_id: uuid.UUID, scheme: ScoringSchemeDefinition, project_id: uuid.UUID | None,
    data: dict[str, Any], actor_id: uuid.UUID | None, warnings: list[str],
) -> dict[str, str]:
    """Recreates exported custom axes, models and hidden registered criteria for the tier.

    An axis whose key the organisation already uses for a different axis is created under a fresh key, and the
    returned map (`exported key -> key here`) lets the caller point imported scores at it; a model is re-pointed
    the same way. One that cannot be created is skipped with a warning.

    Returns:
        `{exported axis key: axis key in this organisation}`.
    """
    mapping: dict[str, str] = {}
    if not scheme.allow_custom_criteria or not data:
        return mapping
    for entry in data.get("axes", []):
        existing = _custom_axis(db, organization_id, scheme.key, entry["key"])
        if existing is not None and existing.label == entry["label"] and existing.project_id == project_id:
            mapping[entry["key"]] = existing.key
            continue
        try:
            with db.begin_nested():
                row = create_axis(
                    db, organization_id, scheme, project_id=project_id, label=entry["label"],
                    description=entry.get("description"), actor_id=actor_id,
                    levels=[LevelSpec(lvl["name"], lvl["weight"], lvl.get("description")) for lvl in entry["levels"]],
                )
            mapping[entry["key"]] = row.key
        except HTTPException as exc:
            warnings.append(f"Scoring axis {entry['label']!r} skipped — {exc.detail}")
    for entry in data.get("models", []):
        axes = [
            ModelAxisSpec(
                mapping.get(a["axis_key"], a["axis_key"]), a["role"], float(a.get("exponent") or 1.0),
                a.get("importance"), bool(a.get("lower_is_better")),
            )
            for a in entry["definition"]["axes"]
        ]
        try:
            with db.begin_nested():
                create_model(
                    db, organization_id, scheme, project_id=project_id, label=entry["label"],
                    combination=entry["definition"]["combination"], axes=axes, actor_id=actor_id,
                )
        except HTTPException as exc:
            warnings.append(f"Scoring model {entry['label']!r} skipped — {exc.detail}")
    for entry in data.get("hidden", []):
        try:
            with db.begin_nested():
                hide_criterion(db, organization_id, scheme, entry["kind"], entry["key"], project_id=project_id, actor_id=actor_id)
        except HTTPException as exc:
            warnings.append(f"Hidden scoring {entry['kind']} {entry['key']!r} skipped — {exc.detail}")
    return mapping
