"""
Module: services.scoring_config

Carries a project's own scoring configuration in the project bundle and into a project created from a template.

Covers, for every registered scoring scheme, the rows a project overrides: its default model, the models it offers,
its rating bands, its thresholds for a derived axis's levels and its explicit cell ratings. The organisation's
levels are one shared vocabulary and are not carried; a project's custom axes, custom models and hidden criteria are
carried by each module's own bundle hooks (`services.scoring_custom.export_definitions`), which import first.

Design decisions:
- A level is named by scheme, axis key and level name (unique per organisation), never by id, so a bundle moves
  between organisations: a level the target organisation does not have is skipped with a warning, so a score is
  never re-rated against a different level.
- A custom model or axis is created afresh with a new key when it is imported (the key follows its label), so the
  bundle also carries the label of a custom (`m_`/`c_` prefixed) key and the import finds the project's own
  criterion by that label.
- Nothing here names a module: the schemes come from the registry (`get_all_registered_scoring_schemes`).

External dependencies: the scoring models and the module registry.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.scoring import (
    ScoringBand,
    ScoringCellRating,
    ScoringCustomAxis,
    ScoringCustomModel,
    ScoringEnabledModel,
    ScoringLevel,
    ScoringLevelThreshold,
    ScoringModelDefault,
)
from app.modules.registry import get_all_registered_scoring_schemes
from app.services.bundle_common import BundleImportWarnings

#: The bundle key holding the configuration.
BUNDLE_KEY = "scoring_configuration"
#: Prefix of the key a custom model or axis gets (see `services.scoring_custom`).
_CUSTOM_MODEL_PREFIX = "m_"
_CUSTOM_AXIS_PREFIX = "c_"


def _custom_labels(db: Session, project: Project) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    """The labels of the organisation's custom models and axes, keyed by `(scheme key, criterion key)`.

    Args:
        db: An active database session.
        project: The project whose organisation is read.

    Returns:
        `(model labels, axis labels)`.
    """
    models = {
        (row.scheme_key, row.key): row.label
        for row in db.scalars(select(ScoringCustomModel).where(ScoringCustomModel.organization_id == project.organization_id))
    }
    axes = {
        (row.scheme_key, row.key): row.label
        for row in db.scalars(select(ScoringCustomAxis).where(ScoringCustomAxis.organization_id == project.organization_id))
    }
    return models, axes


def _model_ref(scheme_key: str, key: str, labels: dict[tuple[str, str], str]) -> dict[str, Any]:
    """A portable reference to a model: its key, and its label when the key is a custom model's."""
    ref: dict[str, Any] = {"scheme": scheme_key, "model": key}
    if key.startswith(_CUSTOM_MODEL_PREFIX) and (scheme_key, key) in labels:
        ref["model_label"] = labels[(scheme_key, key)]
    return ref


def _level_ref(level: ScoringLevel, axis_labels: dict[tuple[str, str], str]) -> dict[str, Any]:
    """A portable reference to a level: its axis (with the axis label when the axis is a custom one) and its name."""
    ref: dict[str, Any] = {"axis": level.axis_key, "level": level.name}
    if level.axis_key.startswith(_CUSTOM_AXIS_PREFIX) and (level.scheme_key, level.axis_key) in axis_labels:
        ref["axis_label"] = axis_labels[(level.scheme_key, level.axis_key)]
    return ref


def export_project_scoring(db: Session, project: Project) -> dict[str, Any]:
    """The project's own scoring configuration as bundle data.

    Args:
        db: An active database session.
        project: The project to export.

    Returns:
        `{"scoring_configuration": {...}}`; each list is empty when the project overrides nothing of that kind.
    """
    model_labels, axis_labels = _custom_labels(db, project)

    def scoped(model: Any) -> list[Any]:
        return list(db.scalars(select(model).where(model.project_id == project.id).order_by(model.created_at, model.id)))

    threshold_rows = scoped(ScoringLevelThreshold)
    level_ids = {row.level_id for row in threshold_rows}
    cells = scoped(ScoringCellRating)
    for cell in cells:
        level_ids.update((cell.first_level_id, cell.second_level_id))
    levels = {
        level.id: level for level in db.scalars(select(ScoringLevel).where(ScoringLevel.id.in_(level_ids)))
    } if level_ids else {}

    thresholds = [
        {"scheme": levels[row.level_id].scheme_key, **_level_ref(levels[row.level_id], axis_labels), "threshold": str(row.threshold)}
        for row in threshold_rows if row.level_id in levels
    ]
    cell_ratings = [
        {
            **_model_ref(cell.scheme_key, cell.model_key, model_labels),
            "first": _level_ref(levels[cell.first_level_id], axis_labels),
            "second": _level_ref(levels[cell.second_level_id], axis_labels),
            "band_label": cell.band_label,
        }
        for cell in cells if cell.first_level_id in levels and cell.second_level_id in levels
    ]
    return {BUNDLE_KEY: {
        "default_models": [_model_ref(row.scheme_key, row.model_key, model_labels) for row in scoped(ScoringModelDefault)],
        "enabled_models": [_model_ref(row.scheme_key, row.model_key, model_labels) for row in scoped(ScoringEnabledModel)],
        "bands": [
            {
                **_model_ref(row.scheme_key, row.model_key, model_labels), "label": row.label, "min_score": str(row.min_score),
                "tone": row.tone, "sort_order": row.sort_order,
            }
            for row in scoped(ScoringBand)
        ],
        "level_thresholds": thresholds,
        "cell_ratings": cell_ratings,
    }}


class _Resolver:
    """Finds, in the importing project's organisation, the model key and level id an exported reference names."""

    def __init__(self, db: Session, project: Project, warnings: BundleImportWarnings) -> None:
        """Loads what a reference can name.

        Args:
            db: An active database session.
            project: The project being imported into.
            warnings: Collects every reference that could not be matched.
        """
        self.warnings = warnings
        self.schemes = get_all_registered_scoring_schemes()
        self.models: dict[tuple[str, str], str] = {}
        self.axes: dict[tuple[str, str], str] = {}
        for model_row in db.scalars(select(ScoringCustomModel).where(
            ScoringCustomModel.organization_id == project.organization_id,
            (ScoringCustomModel.project_id.is_(None)) | (ScoringCustomModel.project_id == project.id),
        )):
            self.models[(model_row.scheme_key, f"label:{model_row.label}")] = model_row.key
            self.models[(model_row.scheme_key, model_row.key)] = model_row.key
        for axis_row in db.scalars(select(ScoringCustomAxis).where(
            ScoringCustomAxis.organization_id == project.organization_id,
            (ScoringCustomAxis.project_id.is_(None)) | (ScoringCustomAxis.project_id == project.id),
        )):
            self.axes[(axis_row.scheme_key, f"label:{axis_row.label}")] = axis_row.key
            self.axes[(axis_row.scheme_key, axis_row.key)] = axis_row.key
        self.levels: dict[tuple[str, str, str], uuid.UUID] = {
            (level.scheme_key, level.axis_key, level.name): level.id
            for level in db.scalars(select(ScoringLevel).where(
                ScoringLevel.organization_id == project.organization_id,
                (ScoringLevel.project_id.is_(None)) | (ScoringLevel.project_id == project.id),
            ))
        }

    def model(self, ref: dict[str, Any]) -> tuple[str, str] | None:
        """The `(scheme key, model key)` here for an exported model reference, or `None` (with a warning)."""
        scheme_key, key = ref.get("scheme"), ref.get("model")
        registered = self.schemes.get(scheme_key) if isinstance(scheme_key, str) else None
        if registered is None or not isinstance(key, str):
            self.warnings.add(f"Scoring configuration for the unknown scheme {scheme_key!r} was not imported.")
            return None
        if key.startswith(_CUSTOM_MODEL_PREFIX):
            by_label = self.models.get((registered.scheme.key, f"label:{ref.get('model_label')}"))
            found = by_label or self.models.get((registered.scheme.key, key))
            if found is None:
                name = ref.get("model_label") or key
                self.warnings.add(f"Scoring configuration for the model {name!r} was not imported: the model does not exist here.")
                return None
            return registered.scheme.key, found
        if registered.scheme.model(key) is None:
            self.warnings.add(f"Scoring configuration for the unknown model {key!r} was not imported.")
            return None
        return registered.scheme.key, key

    def level(self, scheme_key: str, ref: dict[str, Any]) -> uuid.UUID | None:
        """The level id here for an exported level reference, or `None` (with a warning)."""
        axis = ref.get("axis")
        if isinstance(axis, str) and axis.startswith(_CUSTOM_AXIS_PREFIX):
            axis = self.axes.get((scheme_key, f"label:{ref.get('axis_label')}")) or self.axes.get((scheme_key, axis))
        found = self.levels.get((scheme_key, str(axis), str(ref.get("level"))))
        if found is None:
            name = ref.get("axis_label") or ref.get("axis")
            self.warnings.add(f"Scoring level {ref.get('level')!r} of {name!r} does not exist here and was not imported.")
        return found


def import_project_scoring(db: Session, project: Project, data: dict[str, Any], warnings: BundleImportWarnings) -> None:
    """Recreates exported scoring configuration on the project.

    Run after the modules' own bundle import, so the project's custom models and axes exist. A reference that does
    not match anything here is skipped with a warning.

    Args:
        db: An active database session; rows are flushed by the caller's commit.
        project: The project being imported into (it has no scoring configuration of its own yet).
        data: The bundle's `project.json` (or a template's export); a bundle without the key imports nothing.
        warnings: Collects every reference that could not be matched.
    """
    config = data.get(BUNDLE_KEY)
    if not isinstance(config, dict):
        return
    resolver = _Resolver(db, project, warnings)
    organization_id = project.organization_id
    for entry in config.get("default_models") or []:
        if (resolved := resolver.model(entry)) is not None:
            db.add(ScoringModelDefault(organization_id=organization_id, project_id=project.id, scheme_key=resolved[0], model_key=resolved[1]))
    for entry in config.get("enabled_models") or []:
        if (resolved := resolver.model(entry)) is not None:
            db.add(ScoringEnabledModel(organization_id=organization_id, project_id=project.id, scheme_key=resolved[0], model_key=resolved[1]))
    for entry in config.get("bands") or []:
        if (resolved := resolver.model(entry)) is not None:
            db.add(ScoringBand(
                organization_id=organization_id, project_id=project.id, scheme_key=resolved[0], model_key=resolved[1],
                label=str(entry["label"]), min_score=Decimal(str(entry["min_score"])), tone=str(entry["tone"]),
                sort_order=int(entry.get("sort_order") or 0),
            ))
    for entry in config.get("level_thresholds") or []:
        scheme_key = str(entry.get("scheme"))
        if (level_id := resolver.level(scheme_key, entry)) is not None:
            db.add(ScoringLevelThreshold(project_id=project.id, level_id=level_id, threshold=Decimal(str(entry["threshold"]))))
    for entry in config.get("cell_ratings") or []:
        resolved = resolver.model(entry)
        if resolved is None:
            continue
        first, second = resolver.level(resolved[0], entry.get("first") or {}), resolver.level(resolved[0], entry.get("second") or {})
        if first is not None and second is not None:
            db.add(ScoringCellRating(
                organization_id=organization_id, project_id=project.id, scheme_key=resolved[0], model_key=resolved[1],
                first_level_id=first, second_level_id=second, band_label=str(entry["band_label"]),
            ))
    db.flush()
