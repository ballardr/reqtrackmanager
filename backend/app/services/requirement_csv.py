"""
Module: services.requirement_csv

Full-fidelity CSV export for a project's requirements — every field the
data model carries (not just the fixed report-table subset `services.reports`
produces for R-F-02), including per-project custom field values (keyed by
column name `cf_<definition name>`) and the target stage. Designed so the
exact file this module produces is re-importable via
`routers.requirements.import_requirements` without hand-editing: `unique_code`,
`status`, `links`, and `attachments` are included for reference but ignored
on import (see that endpoint's docstring for the full column contract).
"""

from __future__ import annotations

import csv
import io
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.custom_field import CustomFieldDefinition, CustomFieldEntityKind
from app.models.file import FileAsset, RequirementFile
from app.models.project import Project, ProjectCategory, ProjectComponent, ProjectStage
from app.models.requirement import Requirement, RequirementKeyword, RequirementLink, RequirementVersion
from app.models.user import User
from app.services.csv_safety import csv_safe

CUSTOM_FIELD_COLUMN_PREFIX = "cf_"

STATIC_COLUMNS = [
    "unique_code", "name", "reasoning", "clarification", "description",
    "component_prefix", "category_prefix", "level", "target_version",
    "owner_email", "keywords", "review_date", "review_lead_days", "reviewer_email",
]
# Present in an export for reference/round-trip convenience but never read
# back on import: `status` has its own workflow-transition rules (import
# always creates rows as draft, matching the pre-existing importer's
# behaviour), and `links`/`attachments` reference other rows/binary data
# that a flat per-row CSV import can't safely reconstruct (see
# routers.requirements.import_requirements's docstring).
EXPORT_ONLY_COLUMNS = ["status", "links", "attachments"]


def _cell(value) -> str:
    if value is None:
        return ""
    return csv_safe(str(value))


def custom_field_definitions_for_export(db: Session, project_id: UUID) -> list[CustomFieldDefinition]:
    """Returns the project's requirement custom field definitions, ordered
    the same way the export/import column layout uses (`sort_order`)."""
    return list(
        db.scalars(
            select(CustomFieldDefinition)
            .where(
                CustomFieldDefinition.project_id == project_id,
                CustomFieldDefinition.entity_kind == CustomFieldEntityKind.REQUIREMENT,
            )
            .order_by(CustomFieldDefinition.sort_order)
        ).all()
    )


def export_requirements_csv(db: Session, project: Project, *, include_archived: bool = False) -> bytes:
    """Builds a full-fidelity CSV of every (non-archived, by default)
    requirement in `project`, including custom field values and a denormalized
    target stage/component/category so the file is human-editable and
    directly re-importable.

    Args:
        db: An active database session.
        project: The project whose requirements to export.
        include_archived: Whether to include archived requirements.

    Returns:
        The generated CSV file content as bytes.
    """
    query = select(Requirement).where(Requirement.project_id == project.id)
    if not include_archived:
        query = query.where(Requirement.is_archived.is_(False))
    requirements = list(db.scalars(query.order_by(Requirement.unique_code)).all())
    req_ids = [r.id for r in requirements]

    components = {c.id: c for c in db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == project.id)).all()}
    categories = {c.id: c for c in db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == project.id)).all()}
    stages = {s.id: s for s in db.scalars(select(ProjectStage).where(ProjectStage.project_id == project.id)).all()}
    definitions = custom_field_definitions_for_export(db, project.id)

    versions: dict[UUID, RequirementVersion] = {}
    if req_ids:
        versions = {
            v.requirement_id: v
            for v in db.scalars(
                select(RequirementVersion).where(
                    RequirementVersion.requirement_id.in_(req_ids), RequirementVersion.valid_to.is_(None)
                )
            ).all()
        }

    user_ids = {v.owner_id for v in versions.values()} | {v.reviewer_id for v in versions.values() if v.reviewer_id}
    users = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}

    keywords_by_req: dict[UUID, list[str]] = {}
    if req_ids:
        for req_id, keyword in db.execute(
            select(RequirementKeyword.requirement_id, RequirementKeyword.keyword).where(
                RequirementKeyword.requirement_id.in_(req_ids)
            )
        ).all():
            keywords_by_req.setdefault(req_id, []).append(keyword)

    code_by_id = {r.id: r.unique_code for r in requirements}
    links_by_req: dict[UUID, list[str]] = {}
    if req_ids:
        link_rows = list(db.scalars(select(RequirementLink).where(RequirementLink.source_requirement_id.in_(req_ids))).all())
        missing_target_ids = {link.target_requirement_id for link in link_rows} - set(code_by_id)
        if missing_target_ids:
            for r in db.scalars(select(Requirement).where(Requirement.id.in_(missing_target_ids))).all():
                code_by_id[r.id] = r.unique_code
        for link in link_rows:
            target_code = code_by_id.get(link.target_requirement_id, "?")
            links_by_req.setdefault(link.source_requirement_id, []).append(f"{link.link_type.value}:{target_code}")

    attachments_by_req: dict[UUID, list[str]] = {}
    if req_ids:
        for req_id, filename in db.execute(
            select(RequirementFile.requirement_id, FileAsset.filename)
            .join(FileAsset, FileAsset.id == RequirementFile.file_id)
            .where(RequirementFile.requirement_id.in_(req_ids))
        ).all():
            attachments_by_req.setdefault(req_id, []).append(filename)

    header = (
        STATIC_COLUMNS + [f"{CUSTOM_FIELD_COLUMN_PREFIX}{d.name}" for d in definitions] + EXPORT_ONLY_COLUMNS
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for req in requirements:
        version = versions.get(req.id)
        if version is None:
            continue
        component = components.get(req.component_id)
        category = categories.get(req.category_id)
        stage = stages.get(version.target_stage_id)
        row = [
            _cell(req.unique_code), _cell(version.name), _cell(version.reasoning),
            _cell(version.clarification), _cell(version.description),
            _cell(component.prefix if component else ""), _cell(category.prefix if category else ""),
            _cell(version.level.value), _cell(stage.name if stage else ""),
            _cell(users.get(version.owner_id, "")), _cell(";".join(keywords_by_req.get(req.id, []))),
            _cell(version.review_date.isoformat() if version.review_date else ""),
            _cell(version.review_lead_days), _cell(users.get(version.reviewer_id, "") if version.reviewer_id else ""),
        ]
        for definition in definitions:
            row.append(_cell(version.custom_fields.get(str(definition.id), "")))
        row.append(_cell(version.status.value))
        row.append(_cell(";".join(links_by_req.get(req.id, []))))
        row.append(_cell(";".join(attachments_by_req.get(req.id, []))))
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")
