"""
Module: modules.context_strategy.export

This module's contribution to the core org/project bundle export/import
(`app.services.org_export`/`project_export`), registered through
`ModuleOrgBundleHooks`/`ModuleProjectBundleHooks` on `MODULE_DEFINITION` rather
than those core files importing this module.

- Org level: the Pain Point type vocabulary (with definitions) and the
  organisation-scoped Strategies, Future States and Guiding Principles.
- Project level: the project's Pain Point type overrides, local types and hidden
  organisation defaults; its Strategies, Future States and Guiding Principles;
  Pain Points with their scores; Open Questions; and the links between those
  records and to Requirements.

Design decisions (all Decided by: Agent):
- A record travels as its *current* content and status only (Strategy, Future
  State and Guiding Principle as their current version). Version history,
  comments and comment attachments are not carried: a bundle is a migration
  artefact, and the imported record starts at version 1 attributed to the
  importer where the author cannot be matched. This is how the Risk and
  Stakeholders bundles already treat their records.
- Status is imported as exported, exactly as the core Requirement and Risk
  sections do: the bundle is a restore, and importing a project is itself a
  privileged action. A bundle never carries the identity of an approver, so no
  approval is attributed to anyone who did not give it.
- Codes are information only: an import numbers records afresh (in their original
  order). Within the bundle a record is addressed by its exported code (`ref`).
- Cross-references use portable keys: type names, scoring level axis+name,
  persona labels, user emails; an owner is `{type, email | name}`.
- Pain Point scores are imported in `import_late`, after the Stakeholders module
  has recreated the Personas a score can target. A score against a persona the
  target project cannot list (the module is off, or the persona is missing) is
  skipped with a warning. Scoring configuration (levels, bands, models) is not
  part of a bundle; a level the target lacks leaves that axis unscored, with a
  warning, rather than silently re-rating.
- Links travel only between this module's own project records and Requirements
  (`services.bundle_links`). Links to organisation-level records, other modules'
  records or other projects are dropped: those records are not in the bundle.
- Organisation-level files cannot travel (the org hook receives no bytes), so
  org-scoped records import without their attachments. Merging into an
  organisation skips a type, Strategy, Future State or Guiding Principle whose
  name the organisation already has, so a re-import is idempotent.

Dependencies: `app.services.bundle_common`, `app.services.bundle_links`,
`app.services.principals`, `app.services.tags`, this module's models and service.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.context_strategy.enums import (
    FutureStateScope,
    FutureStateStatus,
    GuidingPrinciplePriority,
    GuidingPrincipleScope,
    GuidingPrincipleStatus,
    OpenQuestionPriority,
    OpenQuestionStatus,
    PainPointPriority,
    PainPointStatus,
    StrategyPriority,
    StrategyScope,
    StrategyStatus,
    StrategyTimeHorizon,
)
from app.modules.context_strategy.models import (
    FutureState,
    FutureStateFile,
    FutureStateVersion,
    GuidingPrinciple,
    GuidingPrincipleFile,
    GuidingPrincipleVersion,
    OpenQuestion,
    OpenQuestionFile,
    PainPoint,
    PainPointFile,
    PainPointScore,
    PainPointTypeDefinition,
    ProjectPainPointType,
    Strategy,
    StrategyFile,
    StrategyVersion,
)
from app.modules.context_strategy.pain_point_scores import PERSONA_TARGET_TYPE
from app.modules.context_strategy.scoring import PAIN_POINT_SCORING_SCHEME_KEY
from app.modules.context_strategy.service import (
    FUTURE_STATE_ARTEFACT_TYPE,
    FUTURE_STATE_CODE_PREFIX,
    GUIDING_PRINCIPLE_ARTEFACT_TYPE,
    GUIDING_PRINCIPLE_CODE_PREFIX,
    OPEN_QUESTION_ARTEFACT_TYPE,
    OPEN_QUESTION_CODE_PREFIX,
    PAIN_POINT_ARTEFACT_TYPE,
    PAIN_POINT_CODE_PREFIX,
    PAIN_POINT_TYPE_KIND,
    STRATEGY_ARTEFACT_TYPE,
    STRATEGY_CODE_PREFIX,
    clean_type_definition,
    get_or_create_project_pain_point_type,
    list_hidden_pain_point_types,
)
from app.modules.registry import get_scoring_targets
from app.services import definition_suppression
from app.services.bundle_common import BundleImportWarnings, UserResolver, export_file_links, import_file_links
from app.services.bundle_links import export_artefact_links, import_artefact_links
from app.services.principals import principal_columns_from_bundle, principal_to_bundle
from app.services.scoring import list_levels, seed_missing_scoring_levels
from app.services.sequences import generate_unique_code
from app.services.tags import record_tag_names, restore_record_tags

_SCORE_AXES = {"severity": "severity_level_id", "frequency": "frequency_level_id", "confidence": "confidence_level_id"}
_LINKS_KEY = "context_strategy_links"
_PENDING_SCORES = "context_strategy_pending_scores"


def _j(value: datetime | date | None) -> str | None:
    """ISO 8601 text for a date or instant, or None."""
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    """Parses an exported instant, or None."""
    return datetime.fromisoformat(value) if value else None


def _date(value: str | None) -> date | None:
    """Parses an exported plain date, or None."""
    return date.fromisoformat(value) if value else None


def _emails(db: Session, user_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """`{user id: email}` for the given ids (None ignored)."""
    ids = {u for u in user_ids if u is not None}
    return {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


@dataclass(frozen=True)
class _VersionedSpec:
    """How one identity+version artefact (Strategy, Future State, Guiding Principle) maps to a bundle.

    Attributes:
        key: Bundle key for the list of records.
        artefact_type / prefix: For tags, links and the code generator.
        identity / version / file_model: The three tables.
        fk / file_fk: The version's and the file link's foreign key attribute names.
        scope_enum: The `scope` enum of the identity row.
        title_field: The version column that names the record.
        text_fields: Plain text/str columns carried as-is.
        enum_fields: Enum columns, by value.
        date_fields: Plain `date` columns.
        status_enum: The status enum (also in `enum_fields`).
        owner: Whether the version has a principal `owner`.
    """

    key: str
    artefact_type: str
    prefix: str
    identity: type
    version: type
    file_model: type
    fk: str
    file_fk: str
    scope_enum: type[enum.Enum]
    title_field: str
    text_fields: tuple[str, ...]
    enum_fields: dict[str, type[enum.Enum]]
    date_fields: tuple[str, ...] = ()
    owner: bool = False


_SPECS: tuple[_VersionedSpec, ...] = (
    _VersionedSpec(
        key="strategies", artefact_type=STRATEGY_ARTEFACT_TYPE, prefix=STRATEGY_CODE_PREFIX,
        identity=Strategy, version=StrategyVersion, file_model=StrategyFile, fk="strategy_id", file_fk="strategy_id",
        scope_enum=StrategyScope, title_field="title",
        text_fields=(
            "title", "objective", "current_state", "desired_future_state", "rationale", "expected_outcomes",
            "constraints", "measures_of_success",
        ),
        enum_fields={"priority": StrategyPriority, "time_horizon": StrategyTimeHorizon, "status": StrategyStatus},
    ),
    _VersionedSpec(
        key="future_states", artefact_type=FUTURE_STATE_ARTEFACT_TYPE, prefix=FUTURE_STATE_CODE_PREFIX,
        identity=FutureState, version=FutureStateVersion, file_model=FutureStateFile, fk="future_state_id",
        file_fk="future_state_id", scope_enum=FutureStateScope, title_field="title",
        text_fields=("title", "current_state", "desired_state", "outcomes", "success_measures", "constraints", "assumptions"),
        enum_fields={"status": FutureStateStatus}, date_fields=("target_date",),
    ),
    _VersionedSpec(
        key="guiding_principles", artefact_type=GUIDING_PRINCIPLE_ARTEFACT_TYPE, prefix=GUIDING_PRINCIPLE_CODE_PREFIX,
        identity=GuidingPrinciple, version=GuidingPrincipleVersion, file_model=GuidingPrincipleFile,
        fk="guiding_principle_id", file_fk="guiding_principle_id", scope_enum=GuidingPrincipleScope,
        title_field="name", text_fields=("name", "principle_statement", "rationale"),
        enum_fields={"priority": GuidingPrinciplePriority, "status": GuidingPrincipleStatus}, owner=True,
    ),
)


# --- shared pieces -----------------------------------------------------------


def _current_version(db: Session, spec: _VersionedSpec, record_id: uuid.UUID):
    """The open (current) version row of an identity+version record."""
    return db.scalar(
        select(spec.version).where(getattr(spec.version, spec.fk) == record_id, spec.version.valid_to.is_(None))
    )


def _versioned_json(
    db: Session, spec: _VersionedSpec, record, version, emails: dict[uuid.UUID, str], assets: dict[uuid.UUID, FileAsset] | None,
) -> dict[str, Any]:
    """One identity+version record as a bundle entry (attachments only when `assets` is given)."""
    entry: dict[str, Any] = {
        "ref": record.unique_code,
        **{f: getattr(version, f) for f in spec.text_fields},
        **{f: getattr(version, f).value for f in spec.enum_fields},
        **{f: _j(getattr(version, f)) for f in spec.date_fields},
        "created_by_email": emails.get(record.creator_id), "created_at": _j(record.created_at),
        "is_archived": record.is_archived, "archived_at": _j(record.archived_at),
        "archived_by_email": emails.get(record.archived_by),
        "tags": record_tag_names(db, spec.artefact_type, record.id),
    }
    if spec.owner:
        entry["owner"] = principal_to_bundle(db, version.owner_type, version.owner_id)
    if assets is not None:
        entry["attachments"] = export_file_links(db, spec.file_model, spec.file_fk, record.id, assets)
    return entry


def _create_versioned(
    db: Session, spec: _VersionedSpec, entry: dict[str, Any], *, owner_row: Project | Organization, scope,
    organization_id: uuid.UUID, project_id: uuid.UUID | None, users: UserResolver, warnings: BundleImportWarnings,
    context: str,
):
    """Creates one identity+version record (version 1, current) from a bundle entry and applies its tags."""
    creator_id = users.resolve(entry.get("created_by_email"), required=True, context=f"{context} creator")
    archived = bool(entry.get("is_archived"))
    archiver = users.resolve(entry.get("archived_by_email"), required=False, context=f"{context} archiver")
    record = spec.identity(
        scope=scope, organization_id=organization_id if project_id is None else None, project_id=project_id,
        unique_code=generate_unique_code(db, owner_row, spec.artefact_type, spec.prefix), creator_id=creator_id,
        is_archived=archived, archived_at=_dt(entry.get("archived_at")), archived_by=(archiver or creator_id) if archived else None,
    )
    db.add(record)
    db.flush()
    now = datetime.now(UTC)
    values: dict[str, Any] = {f: entry.get(f, "") for f in spec.text_fields}
    values.update({f: enum_cls(entry[f]) for f, enum_cls in spec.enum_fields.items() if entry.get(f)})
    values.update({f: _date(entry.get(f)) for f in spec.date_fields})
    if spec.owner:
        values.update(principal_columns_from_bundle(
            db, entry, "owner", organization_id=organization_id, project_id=project_id, users=users, warnings=warnings,
            context=f"{context} owner", required=False,
        ))
    db.add(spec.version(
        **{spec.fk: record.id}, version_number=1, valid_from=now, valid_to=None, change_note="Imported from bundle.",
        created_by=creator_id, created_at=now, **values,
    ))
    db.flush()
    restore_record_tags(
        db, organization_id=organization_id, record_project_id=project_id, actor_id=creator_id,
        artefact_type=spec.artefact_type, artefact_id=record.id, names=entry.get("tags"),
    )
    return record


# --- Org level ---------------------------------------------------------------


def export_org_data(db: Session, org: Organization) -> dict[str, Any]:
    """`ModuleOrgBundleHooks.export`: the organisation's Pain Point types and its
    organisation-scoped Strategies, Future States and Guiding Principles (archived
    included — a bundle is a backup, readers filter)."""
    types = db.scalars(
        select(PainPointTypeDefinition).where(PainPointTypeDefinition.organization_id == org.id)
        .order_by(PainPointTypeDefinition.sort_order)
    ).all()
    out: dict[str, Any] = {
        "pain_point_types": [
            {"name": t.name, "sort_order": t.sort_order, "is_active": t.is_active, "definition": t.definition} for t in types
        ],
    }
    for spec in _SPECS:
        records = list(db.scalars(
            select(spec.identity).where(spec.identity.organization_id == org.id, spec.identity.scope == spec.scope_enum.ORGANIZATION)
            .order_by(spec.identity.created_at)
        ).all())
        emails = _emails(db, {r.creator_id for r in records} | {r.archived_by for r in records})
        out[spec.key] = [
            _versioned_json(db, spec, r, _current_version(db, spec, r.id), emails, None) for r in records
        ]
    return out


def import_org_data(
    db: Session, org: Organization, data: dict[str, Any], users: UserResolver, warnings: BundleImportWarnings,
    resolutions: dict[str, str] | None,
) -> None:
    """`ModuleOrgBundleHooks.import_`: recreates Pain Point types and the
    organisation-scoped Strategies, Future States and Guiding Principles, skipping a
    type or record whose name the organisation already has."""
    existing = {t.name for t in db.scalars(select(PainPointTypeDefinition).where(PainPointTypeDefinition.organization_id == org.id))}
    for t in data.get("pain_point_types", []):
        if t["name"] in existing:
            continue
        db.add(PainPointTypeDefinition(
            organization_id=org.id, name=t["name"], sort_order=t.get("sort_order", len(existing)),
            is_active=t.get("is_active", True), definition=clean_type_definition(t.get("definition")),
        ))
        existing.add(t["name"])
    db.flush()

    for spec in _SPECS:
        entries = data.get(spec.key, [])
        if not entries:
            continue
        have = {
            getattr(_current_version(db, spec, r.id), spec.title_field)
            for r in db.scalars(select(spec.identity).where(
                spec.identity.organization_id == org.id, spec.identity.scope == spec.scope_enum.ORGANIZATION,
            ))
        }
        for entry in entries:
            name = entry[spec.title_field]
            if name in have:
                warnings.add(f"Organisation {spec.key.replace('_', ' ')} {name!r} skipped — the organisation already has one with that name.")
                continue
            _create_versioned(
                db, spec, entry, owner_row=org, scope=spec.scope_enum.ORGANIZATION, organization_id=org.id, project_id=None,
                users=users, warnings=warnings, context=f"{spec.key.replace('_', ' ').title()} {name!r}",
            )
            have.add(name)
            if entry.get("attachments"):
                warnings.add(f"Attachments of organisation record {name!r} were not imported — organisation-level files cannot travel.")
    db.flush()


# --- Project level: export ---------------------------------------------------


def _level_refs(db: Session, project: Project) -> dict[uuid.UUID, str]:
    """`{level id: name}` for the organisation's Pain Point scoring levels."""
    return {
        level.id: level.name
        for levels in list_levels(db, project.organization_id, PAIN_POINT_SCORING_SCHEME_KEY).values() for level in levels
    }


def _type_name(db: Session, row: ProjectPainPointType) -> tuple[str | None, bool]:
    """`(effective name, is project-local)` of a project Pain Point type row."""
    if row.org_type_id is None:
        return row.name_override, True
    org_type = db.get(PainPointTypeDefinition, row.org_type_id)
    return (row.name_override or (org_type.name if org_type else None)), False


def _pain_point_json(
    db: Session, project: Project, pp: PainPoint, emails: dict[uuid.UUID, str], assets: dict[uuid.UUID, FileAsset],
    levels: dict[uuid.UUID, str], persona_labels: dict[uuid.UUID, str],
) -> dict[str, Any]:
    """One Pain Point with its type, scores and attachments."""
    type_row = db.get(ProjectPainPointType, pp.pain_point_type_id)
    type_name, type_is_local = _type_name(db, type_row)
    org_type_name = None
    if type_row.org_type_id is not None:
        org_type = db.get(PainPointTypeDefinition, type_row.org_type_id)
        org_type_name = org_type.name if org_type else None
    scores = []
    for score in db.scalars(select(PainPointScore).where(PainPointScore.pain_point_id == pp.id).order_by(PainPointScore.created_at)):
        target = None
        if score.target_id is not None:
            label = persona_labels.get(score.target_id) if score.target_type == PERSONA_TARGET_TYPE else None
            if label is None:
                continue  # a target the module no longer lists has no portable key
            target = {"type": score.target_type, "label": label}
        scores.append({
            "target": target,
            **{axis: levels.get(getattr(score, column)) for axis, column in _SCORE_AXES.items()},
            "scored_by_email": emails.get(score.scored_by),
        })
    return {
        "ref": pp.unique_code, "title": pp.title, "description": pp.description, "source": pp.source, "impact": pp.impact,
        "evidence": pp.evidence, "priority": pp.priority.value, "status": pp.status.value,
        "type_name": type_name, "type_org_name": org_type_name, "type_is_project_local": type_is_local,
        "owner": principal_to_bundle(db, pp.owner_type, pp.owner_id), "date_identified": _j(pp.date_identified),
        "is_intentional": pp.is_intentional, "created_by_email": emails.get(pp.creator_id), "created_at": _j(pp.created_at),
        "is_archived": pp.is_archived, "archived_at": _j(pp.archived_at), "archived_by_email": emails.get(pp.archived_by),
        "tags": record_tag_names(db, PAIN_POINT_ARTEFACT_TYPE, pp.id),
        "attachments": export_file_links(db, PainPointFile, "pain_point_id", pp.id, assets),
        "scores": scores,
    }


def export_project_data(db: Session, project: Project) -> tuple[dict[str, Any], dict[uuid.UUID, FileAsset]]:
    """`ModuleProjectBundleHooks.export`: the project's Pain Point types, Strategies, Future
    States, Guiding Principles, Pain Points (with scores), Open Questions, attachments and
    the links between them and to Requirements (archived records included)."""
    assets: dict[uuid.UUID, FileAsset] = {}
    out: dict[str, Any] = {}
    refs: dict[str, dict[uuid.UUID, str]] = {}

    type_rows = []
    for row in db.scalars(select(ProjectPainPointType).where(ProjectPainPointType.project_id == project.id)):
        org_type = db.get(PainPointTypeDefinition, row.org_type_id) if row.org_type_id else None
        type_rows.append({
            "org_type_name": org_type.name if org_type else None, "name_override": row.name_override,
            "display_order_override": row.display_order_override, "is_enabled": row.is_enabled,
            "definition_override": row.definition_override,
        })
    out["pain_point_project_types"] = type_rows
    out["pain_point_hidden_org_types"] = [
        t.name for t in list_hidden_pain_point_types(db, project.id, project.organization_id)
    ]

    for spec in _SPECS:
        records = list(db.scalars(
            select(spec.identity).where(spec.identity.project_id == project.id, spec.identity.scope == spec.scope_enum.PROJECT)
            .order_by(spec.identity.unique_code)
        ).all())
        emails = _emails(db, {r.creator_id for r in records} | {r.archived_by for r in records})
        out[spec.key] = [
            _versioned_json(db, spec, r, _current_version(db, spec, r.id), emails, assets) for r in records
        ]
        refs[spec.artefact_type] = {r.id: r.unique_code for r in records}

    levels = _level_refs(db, project)
    persona_labels = {t.id: t.label for t in get_scoring_targets(db, project.id, PERSONA_TARGET_TYPE)}
    pain_points = list(db.scalars(select(PainPoint).where(PainPoint.project_id == project.id).order_by(PainPoint.unique_code)))
    emails = _emails(db, {p.creator_id for p in pain_points} | {p.archived_by for p in pain_points})
    scorer_ids = {
        s.scored_by for s in db.scalars(select(PainPointScore).where(PainPointScore.pain_point_id.in_([p.id for p in pain_points])))
    } if pain_points else set()
    emails.update(_emails(db, scorer_ids))
    out["pain_points"] = [_pain_point_json(db, project, p, emails, assets, levels, persona_labels) for p in pain_points]
    refs[PAIN_POINT_ARTEFACT_TYPE] = {p.id: p.unique_code for p in pain_points}

    questions = list(db.scalars(select(OpenQuestion).where(OpenQuestion.project_id == project.id).order_by(OpenQuestion.unique_code)))
    emails = _emails(db, {q.creator_id for q in questions} | {q.archived_by for q in questions})
    out["open_questions"] = [
        {
            "ref": q.unique_code, "question": q.question, "context": q.context, "evidence": q.evidence,
            "priority": q.priority.value, "status": q.status.value, "owner": principal_to_bundle(db, q.owner_type, q.owner_id),
            "due_date": _j(q.due_date), "created_by_email": emails.get(q.creator_id), "created_at": _j(q.created_at),
            "is_archived": q.is_archived, "archived_at": _j(q.archived_at), "archived_by_email": emails.get(q.archived_by),
            "tags": record_tag_names(db, OPEN_QUESTION_ARTEFACT_TYPE, q.id),
            "attachments": export_file_links(db, OpenQuestionFile, "open_question_id", q.id, assets),
        }
        for q in questions
    ]
    refs[OPEN_QUESTION_ARTEFACT_TYPE] = {q.id: q.unique_code for q in questions}

    out[_LINKS_KEY] = export_artefact_links(db, project, refs)
    return out, assets


# --- Project level: import ---------------------------------------------------


def _import_types(db: Session, project: Project, data: dict[str, Any], warnings: BundleImportWarnings) -> dict[str, ProjectPainPointType]:
    """Recreates the project's type rows; returns the rows by effective name."""
    org_types = {
        t.name: t for t in db.scalars(
            select(PainPointTypeDefinition).where(PainPointTypeDefinition.organization_id == project.organization_id)
        )
    }
    rows: dict[str, ProjectPainPointType] = {}
    for t in data.get("pain_point_project_types", []):
        if t.get("org_type_name"):
            org_type = org_types.get(t["org_type_name"])
            if org_type is None:
                warnings.add(f"Pain Point type override for {t['org_type_name']!r} skipped — the organisation has no such type.")
                continue
            row = ProjectPainPointType(
                project_id=project.id, org_type_id=org_type.id, name_override=t.get("name_override"),
                display_order_override=t.get("display_order_override"), is_enabled=t.get("is_enabled", True),
                definition_override=clean_type_definition(t.get("definition_override")),
            )
            rows[t.get("name_override") or org_type.name] = row
        else:
            row = ProjectPainPointType(
                project_id=project.id, org_type_id=None, name_override=t["name_override"],
                display_order_override=t.get("display_order_override"), is_enabled=t.get("is_enabled", True),
                definition_override=clean_type_definition(t.get("definition_override")),
            )
            rows[t["name_override"]] = row
        db.add(row)
    db.flush()
    return rows


def _type_row_for(
    db: Session, project: Project, entry: dict[str, Any], rows: dict[str, ProjectPainPointType],
    org_types: dict[str, PainPointTypeDefinition], warnings: BundleImportWarnings, context: str,
) -> ProjectPainPointType:
    """The project type row a Pain Point should use: one imported above, else a passthrough of
    the organisation type, else a new project-local type (with a warning)."""
    name = entry.get("type_name")
    if name in rows:
        return rows[name]
    org_type = org_types.get(entry.get("type_org_name") or name)
    if org_type is not None and org_type.is_active:
        return get_or_create_project_pain_point_type(db, project.id, project.organization_id, org_type.id)
    warnings.add(f"{context}: type {name!r} not found — created as a project-local type.")
    row = ProjectPainPointType(project_id=project.id, org_type_id=None, name_override=name or "Imported", is_enabled=True)
    db.add(row)
    db.flush()
    rows[row.name_override] = row
    return row


def import_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_`: recreates the project's Pain Point types, Strategies, Future
    States, Guiding Principles, Pain Points, Open Questions and links. Anything that cannot be matched
    in the target (a type, a user, a group) is left unset or created locally with a warning, never guessed.
    Scores are imported later, by `import_late`."""
    if not any(data.get(k) for k in (
        "pain_point_project_types", "pain_point_hidden_org_types", "pain_points", "open_questions",
        *(spec.key for spec in _SPECS),
    )):
        return
    organization_id = project.organization_id
    refs: dict[str, dict[str, uuid.UUID]] = {}

    for spec in _SPECS:
        by_ref: dict[str, uuid.UUID] = {}
        for entry in data.get(spec.key, []):
            record = _create_versioned(
                db, spec, entry, owner_row=project, scope=spec.scope_enum.PROJECT, organization_id=organization_id,
                project_id=project.id, users=users, warnings=warnings,
                context=f"{spec.key.replace('_', ' ').title()} {entry[spec.title_field]!r}",
            )
            by_ref[entry["ref"]] = record.id
            import_file_links(
                db, organization_id=organization_id, file_model=spec.file_model, fk=spec.file_fk, record_id=record.id,
                entries=entry.get("attachments", []), file_bytes_by_ref=file_bytes_by_ref, current_user=current_user,
                users=users, context=f"{spec.artefact_type} {entry['ref']}",
            )
        refs[spec.artefact_type] = by_ref

    rows = _import_types(db, project, data, warnings)
    org_types = {t.name: t for t in db.scalars(select(PainPointTypeDefinition).where(PainPointTypeDefinition.organization_id == organization_id))}
    pain_points: dict[str, uuid.UUID] = {}
    for entry in data.get("pain_points", []):
        context = f"Pain Point {entry['ref']}"
        creator_id = users.resolve(entry.get("created_by_email"), required=True, context=f"{context} creator")
        archived = bool(entry.get("is_archived"))
        archiver = users.resolve(entry.get("archived_by_email"), required=False, context=f"{context} archiver")
        type_row = _type_row_for(db, project, entry, rows, org_types, warnings, context)
        pp = PainPoint(
            project_id=project.id, pain_point_type_id=type_row.id, creator_id=creator_id,
            unique_code=generate_unique_code(db, project, PAIN_POINT_ARTEFACT_TYPE, PAIN_POINT_CODE_PREFIX),
            title=entry["title"], description=entry.get("description", ""), source=entry.get("source", ""),
            impact=entry.get("impact", ""), evidence=entry.get("evidence", ""),
            priority=PainPointPriority(entry.get("priority", "medium")), status=PainPointStatus(entry.get("status", "submitted")),
            date_identified=_date(entry.get("date_identified")) or date.today(), is_intentional=bool(entry.get("is_intentional")),
            is_archived=archived, archived_at=_dt(entry.get("archived_at")), archived_by=(archiver or creator_id) if archived else None,
            **principal_columns_from_bundle(
                db, entry, "owner", organization_id=organization_id, project_id=project.id, users=users, warnings=warnings,
                context=f"{context} owner", required=False,
            ),
        )
        db.add(pp)
        db.flush()
        pain_points[entry["ref"]] = pp.id
        restore_record_tags(
            db, organization_id=organization_id, record_project_id=project.id, actor_id=creator_id,
            artefact_type=PAIN_POINT_ARTEFACT_TYPE, artefact_id=pp.id, names=entry.get("tags"),
        )
        import_file_links(
            db, organization_id=organization_id, file_model=PainPointFile, fk="pain_point_id", record_id=pp.id,
            entries=entry.get("attachments", []), file_bytes_by_ref=file_bytes_by_ref, current_user=current_user,
            users=users, context=context,
        )
    refs[PAIN_POINT_ARTEFACT_TYPE] = pain_points
    db.info[(_PENDING_SCORES, project.id)] = pain_points

    questions: dict[str, uuid.UUID] = {}
    for entry in data.get("open_questions", []):
        context = f"Open Question {entry['ref']}"
        creator_id = users.resolve(entry.get("created_by_email"), required=True, context=f"{context} creator")
        archived = bool(entry.get("is_archived"))
        archiver = users.resolve(entry.get("archived_by_email"), required=False, context=f"{context} archiver")
        oq = OpenQuestion(
            project_id=project.id, creator_id=creator_id,
            unique_code=generate_unique_code(db, project, OPEN_QUESTION_ARTEFACT_TYPE, OPEN_QUESTION_CODE_PREFIX),
            question=entry["question"], context=entry.get("context", ""), evidence=entry.get("evidence", ""),
            priority=OpenQuestionPriority(entry.get("priority", "medium")), status=OpenQuestionStatus(entry.get("status", "open")),
            due_date=_date(entry.get("due_date")),
            is_archived=archived, archived_at=_dt(entry.get("archived_at")), archived_by=(archiver or creator_id) if archived else None,
            **principal_columns_from_bundle(
                db, entry, "owner", organization_id=organization_id, project_id=project.id, users=users, warnings=warnings,
                context=f"{context} owner", required=False,
            ),
        )
        db.add(oq)
        db.flush()
        questions[entry["ref"]] = oq.id
        restore_record_tags(
            db, organization_id=organization_id, record_project_id=project.id, actor_id=creator_id,
            artefact_type=OPEN_QUESTION_ARTEFACT_TYPE, artefact_id=oq.id, names=entry.get("tags"),
        )
        import_file_links(
            db, organization_id=organization_id, file_model=OpenQuestionFile, fk="open_question_id", record_id=oq.id,
            entries=entry.get("attachments", []), file_bytes_by_ref=file_bytes_by_ref, current_user=current_user,
            users=users, context=context,
        )
    refs[OPEN_QUESTION_ARTEFACT_TYPE] = questions

    # Hidden last: a Pain Point above may use a type the project hides, which needs its row created first.
    hidden = set(data.get("pain_point_hidden_org_types", []))
    for name in sorted(hidden):
        org_type = org_types.get(name)
        if org_type is None:
            warnings.add(f"Hidden Pain Point type {name!r} skipped — the organisation has no such type.")
            continue
        definition_suppression.hide_definition(db, project.id, PAIN_POINT_TYPE_KIND, org_type.id)

    import_artefact_links(
        db, project, data.get(_LINKS_KEY, []), refs, current_user, users, warnings, context="Context & Strategy",
    )
    db.flush()


def import_late_project_data(
    db: Session, project: Project, data: dict[str, Any], file_bytes_by_ref: dict[str, bytes], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """`ModuleProjectBundleHooks.import_late`: recreates the Pain Point scores, once the Personas they
    target exist. A persona the project cannot list, or a level the organisation lacks, is skipped with a warning."""
    pain_points: dict[str, uuid.UUID] | None = db.info.pop((_PENDING_SCORES, project.id), None)
    if not pain_points:
        return
    seed_missing_scoring_levels(db, project.organization_id)
    level_ids = {
        (axis, level.name): level.id
        for axis, levels in list_levels(db, project.organization_id, PAIN_POINT_SCORING_SCHEME_KEY).items() for level in levels
    }
    by_label: dict[str, list[uuid.UUID]] = {}
    for target in get_scoring_targets(db, project.id, PERSONA_TARGET_TYPE):
        by_label.setdefault(target.label, []).append(target.id)
    for entry in data.get("pain_points", []):
        pain_point_id = pain_points.get(entry["ref"])
        if pain_point_id is None:
            continue
        for score in entry.get("scores", []):
            context = f"Pain Point {entry['ref']} score"
            target_type = target_id = None
            if score.get("target"):
                matches = by_label.get(score["target"]["label"], [])
                if len(matches) != 1:
                    warnings.add(f"{context}: persona {score['target']['label']!r} not found or ambiguous — skipped.")
                    continue
                target_type, target_id = score["target"]["type"], matches[0]
            levels: dict[str, uuid.UUID | None] = {}
            for axis, column in _SCORE_AXES.items():
                name = score.get(axis)
                level_id = level_ids.get((axis, name)) if name else None
                if name and level_id is None:
                    warnings.add(f"{context}: {axis} level {name!r} not found — left unscored.")
                levels[column] = level_id
            db.add(PainPointScore(
                pain_point_id=pain_point_id, target_type=target_type, target_id=target_id, **levels,
                scored_by=users.resolve(score.get("scored_by_email"), required=False, context=f"{context} scorer"),
            ))
    db.flush()
