"""
Module: services.templates

Implements "create a new project from an existing template project"
(C-E-05). Per the requirement's clarification, cloning copies project
groups, members of project groups (including nested org-group refs and
cross-project member-source refs), direct `UserProjectRole` grants,
project configuration (components, categories, terminology, custom field
definitions, action type definitions), and requirements — deliberately not
stages/baselines/change-request history, since a template is a starting
point for a new project's own lifecycle, not a copy of the source
project's current lifecycle state.

Direct `UserProjectRole` grants are copied as of the follow-up UX batch's
Phase C (2026-08-31, docs/decisions.md): once a project's initial manager
(and any other directly-granted role) is normally established via a direct
grant rather than group membership (`routers.projects.create_project`'s
non-template path), a template project's own directly-granted managers/
admins/stakeholders/members would otherwise silently vanish on clone for
everyone except whoever happens to be doing the cloning (who still gets a
manager role via `_ensure_project_has_a_manager`'s fallback, but nobody
else the template creator intended to carry over). This was a real,
identified gap in an earlier draft of that phase's plan, not a
pre-existing, deliberately-scoped-out behaviour.

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
    UserProjectRole,
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
        new_group = ProjectGroup(project_id=new_project.id, name=group.name, role=group.role)
        db.add(new_group)
        db.flush()
        for member in db.scalars(select(ProjectGroupMember).where(ProjectGroupMember.project_group_id == group.id)).all():
            # All three member-target kinds are copied — `source_project_id`
            # ("this group's members = that project's own direct members")
            # was a real, pre-existing gap found while reviewing this
            # function for Phase C: only `user_id`/`org_group_id` were ever
            # carried over, so a template group referencing another
            # project's roster silently lost that reference on every clone.
            # `source_project_id` itself points at the *original* project it
            # referenced (same-organisation, per `ProjectGroupMember`'s own
            # docstring) — deliberately not remapped to `new_project.id`
            # even when the reference happens to point back at the template
            # being cloned, since that's a meaningful, load-bearing
            # difference (the clone still means "the *template's* own
            # roster", not "itself"), not a bug to correct here.
            db.add(
                ProjectGroupMember(
                    project_group_id=new_group.id, user_id=member.user_id, org_group_id=member.org_group_id,
                    source_project_id=member.source_project_id,
                )
            )

    # Direct role grants (Phase C, follow-up UX batch, 2026-08-31 — see this
    # module's own docstring for why this is now needed). Copied verbatim,
    # including any `PROJECT_MANAGER` grant the template's own creator or
    # anyone else held directly — `_ensure_project_has_a_manager`
    # (`routers.projects.create_project`) only ever adds a *fallback* on top
    # of this if the copy still leaves zero effective managers.
    for role_grant in db.scalars(select(UserProjectRole).where(UserProjectRole.project_id == source.id)).all():
        db.add(UserProjectRole(project_id=new_project.id, user_id=role_grant.user_id, role=role_grant.role))

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
