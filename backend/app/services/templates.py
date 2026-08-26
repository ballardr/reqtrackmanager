"""
Module: services.templates

Implements "create a new project from an existing template project"
(C-E-05). Per the requirement's clarification, cloning copies project
groups, members of project groups, project configuration (components,
categories, terminology, custom field definitions, action type
definitions), and requirements — deliberately not stages/baselines/change-
request history, since a template is a starting point for a new project's
own lifecycle, not a copy of the source project's current lifecycle state.

The new project's `status_id` is deliberately *not* copied from the
template's current status: a template project sitting at, say, "Completed"
doesn't mean every project cloned from it should start there too (unlike
its structural configuration, a status is lifecycle state, closer in spirit
to the stages/baselines this function already excludes) — the new project
starts at its organisation's default status instead, same as a project
created from scratch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_type import ActionTypeDefinition
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
from app.services.definitions import get_default_project_status_id
from app.services.requirements import get_current_version


def clone_project(
    db: Session, source: Project, *, name: str, summary: str, creator: User, parent_project_id: UUID | None = None
) -> Project:
    """Creates a new project by copying a template project's configuration.

    Args:
        db: An active database session (changes are flushed but not
            committed; the caller commits).
        source: The template project to copy from.
        name: The new project's name.
        summary: The new project's summary.
        creator: The user creating the new project.
        parent_project_id: Optional parent for the new project
            (hierarchical projects) — orthogonal to cloning from a
            template: a project can be both cloned from a template *and*
            parented under another project. Validation (same-org, caller
            manages the parent) is the caller's responsibility
            (`routers.projects.create_project`), same as every other field
            here.

    Returns:
        The newly created Project.
    """
    new_project = Project(
        organization_id=source.organization_id, name=name, summary=summary,
        allow_member_change_requests=source.allow_member_change_requests,
        terminology=dict(source.terminology),
        status_id=get_default_project_status_id(db, source.organization_id),
        parent_project_id=parent_project_id,
    )
    db.add(new_project)
    db.flush()

    new_scoping_stage = ProjectStage(
        project_id=new_project.id, name="Scoping", status=StageStatus.SCOPING, sort_order=0, is_current=True
    )
    db.add(new_scoping_stage)
    db.flush()

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

    for action_type in db.scalars(select(ActionTypeDefinition).where(ActionTypeDefinition.project_id == source.id)).all():
        db.add(
            ActionTypeDefinition(
                project_id=new_project.id, name=action_type.name, sort_order=action_type.sort_order
            )
        )

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
                clarification=current_version.clarification, description=current_version.description,
                status=RequirementStatus.DRAFT,
                # The source's own target_stage_id belongs to the *template*
                # project's stages, which are never copied (see this
                # module's docstring) — every cloned requirement targets
                # the new project's own single starting stage instead;
                # level, unlike target, has no such cross-project ambiguity
                # and copies straight across.
                target_stage_id=new_scoping_stage.id, level=current_version.level,
                owner_id=current_version.owner_id, sort_order=current_version.sort_order,
                created_by=creator.id, created_at=now, change_note=f"Copied from template project '{source.name}'.",
                custom_fields=remapped_custom_fields,
            )
        )
        keywords = db.scalars(select(RequirementKeyword.keyword).where(RequirementKeyword.requirement_id == requirement.id)).all()
        for keyword in keywords:
            db.add(RequirementKeyword(requirement_id=new_requirement.id, keyword=keyword))

    return new_project
