"""
Module: services.templates

Implements "create a new project from an existing template project"
(C-E-05). Per the requirement's clarification, cloning copies project
groups, members of project groups, project configuration (components,
categories, terminology, custom field definitions), and requirements —
deliberately not stages/baselines/change-request history, since a template
is a starting point for a new project's own lifecycle, not a copy of the
source project's current lifecycle state.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.custom_field import CustomFieldDefinition
from app.models.enums import RequirementStatus, StageStatus
from app.models.project import (
    Project,
    ProjectCategory,
    ProjectComponent,
    ProjectGroup,
    ProjectGroupMember,
    ProjectStage,
)
from app.models.requirement import Requirement, RequirementKeyword, RequirementVersion
from app.models.user import User
from app.services.requirements import get_current_version


def clone_project(db: Session, source: Project, *, name: str, summary: str, creator: User) -> Project:
    """Creates a new project by copying a template project's configuration.

    Args:
        db: An active database session (changes are flushed but not
            committed; the caller commits).
        source: The template project to copy from.
        name: The new project's name.
        summary: The new project's summary.
        creator: The user creating the new project.

    Returns:
        The newly created Project.
    """
    new_project = Project(
        organization_id=source.organization_id, name=name, summary=summary,
        allow_member_change_requests=source.allow_member_change_requests,
        terminology=dict(source.terminology),
    )
    db.add(new_project)
    db.flush()

    db.add(ProjectStage(project_id=new_project.id, name="Scoping", status=StageStatus.SCOPING, sort_order=0, is_current=True))

    component_id_map = {}
    for component in db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == source.id)).all():
        new_component = ProjectComponent(
            project_id=new_project.id, name=component.name, prefix=component.prefix, sort_order=component.sort_order
        )
        db.add(new_component)
        db.flush()
        component_id_map[component.id] = new_component.id

    category_id_map = {}
    for category in db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == source.id)).all():
        new_category = ProjectCategory(
            project_id=new_project.id, component_id=component_id_map[category.component_id],
            name=category.name, prefix=category.prefix, sort_order=category.sort_order,
        )
        db.add(new_category)
        db.flush()
        category_id_map[category.id] = new_category.id

    field_id_map = {}
    for definition in db.scalars(select(CustomFieldDefinition).where(CustomFieldDefinition.project_id == source.id)).all():
        new_definition = CustomFieldDefinition(
            project_id=new_project.id, entity_kind=definition.entity_kind, name=definition.name,
            field_type=definition.field_type, options=definition.options, required=definition.required,
            sort_order=definition.sort_order,
        )
        db.add(new_definition)
        db.flush()
        field_id_map[str(definition.id)] = str(new_definition.id)

    for group in db.scalars(select(ProjectGroup).where(ProjectGroup.project_id == source.id)).all():
        new_group = ProjectGroup(project_id=new_project.id, name=group.name, role=group.role, is_default=group.is_default)
        db.add(new_group)
        db.flush()
        for member in db.scalars(select(ProjectGroupMember).where(ProjectGroupMember.project_group_id == group.id)).all():
            db.add(
                ProjectGroupMember(
                    project_group_id=new_group.id, user_id=member.user_id, org_group_id=member.org_group_id
                )
            )

    requirements = db.scalars(
        select(Requirement).where(Requirement.project_id == source.id, Requirement.is_archived.is_(False))
    ).all()
    for requirement in requirements:
        current_version = get_current_version(db, requirement.id)
        new_component_id = component_id_map.get(requirement.component_id)
        new_category_id = category_id_map.get(requirement.category_id)
        if new_component_id is None or new_category_id is None:
            continue

        seq = new_project.next_requirement_seq
        new_project.next_requirement_seq = seq + 1
        component = db.get(ProjectComponent, new_component_id)
        category = db.get(ProjectCategory, new_category_id)
        unique_code = f"{component.prefix}-{category.prefix}-{seq:03d}"

        new_requirement = Requirement(
            project_id=new_project.id, component_id=new_component_id, category_id=new_category_id,
            unique_code=unique_code, creator_id=creator.id,
        )
        db.add(new_requirement)
        db.flush()

        remapped_custom_fields = {
            field_id_map[k]: v for k, v in current_version.custom_fields.items() if k in field_id_map
        }
        now = datetime.now(UTC)
        db.add(
            RequirementVersion(
                requirement_id=new_requirement.id, version_number=1, valid_from=now, valid_to=None,
                name=current_version.name, reasoning=current_version.reasoning,
                clarification=current_version.clarification, status=RequirementStatus.DRAFT,
                owner_id=current_version.owner_id, sort_order=current_version.sort_order,
                created_by=creator.id, created_at=now, change_note=f"Copied from template project '{source.name}'.",
                custom_fields=remapped_custom_fields,
            )
        )
        keywords = db.scalars(select(RequirementKeyword.keyword).where(RequirementKeyword.requirement_id == requirement.id)).all()
        for keyword in keywords:
            db.add(RequirementKeyword(requirement_id=new_requirement.id, keyword=keyword))

    return new_project
