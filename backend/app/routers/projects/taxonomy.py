"""
Module: routers.projects.taxonomy

The component/category tree requirements attach to (C-G-07), with
manual display ordering for each (C-E-01/C-E-02). A category is always
nested under one component; a requirement's `category_id` always implies
a matching `component_id` (enforced here and on category reassignment and
move). A prefix left out of a create is suggested from the name by
`services.taxonomy.suggest_prefix`, the same rule the screen asks for.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement
from app.models.user import User
from app.schemas.project import (
    CategoryCreate,
    CategoryMoveTo,
    CategoryOut,
    CategoryUpdate,
    ComponentCreate,
    ComponentOut,
    ComponentUpdate,
    MoveDirection,
    PrefixSuggestion,
    StructureComponentCounts,
    StructureCountsOut,
)
from app.services import taxonomy
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.placements import category_placement_count, component_placement_count
from app.services.placements import reassign_category as reassign_category_placements
from app.services.rbac import require_project_manage, require_project_view

router = APIRouter(tags=["projects-taxonomy"])


def _component_prefix_taken(db: Session, project_id: UUID, prefix: str, ignore: UUID | None = None) -> bool:
    """Whether another component of the project already has `prefix` (`ignore`: the one being renamed)."""
    found = db.scalar(select(ProjectComponent.id).where(
        ProjectComponent.project_id == project_id, ProjectComponent.prefix == prefix, ProjectComponent.id != ignore,
    ))
    return found is not None


def _category_prefix_taken(db: Session, component_id: UUID, prefix: str, ignore: UUID | None = None) -> bool:
    """Whether another category of the component already has `prefix` (`ignore`: the one being renamed)."""
    found = db.scalar(select(ProjectCategory.id).where(
        ProjectCategory.component_id == component_id, ProjectCategory.prefix == prefix, ProjectCategory.id != ignore,
    ))
    return found is not None


@router.get("/{project_id}/components/suggest-prefix", response_model=PrefixSuggestion)
def suggest_component_prefix(
    name: str, ignore: UUID | None = None,
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db),
):
    """Suggests a free prefix for a component named `name` (`ignore`: the component being renamed). The name is
    only read, never logged."""
    return PrefixSuggestion(prefix=taxonomy.suggest_prefix(db, project.id, name, ignore=ignore))


@router.get("/{project_id}/categories/suggest-prefix", response_model=PrefixSuggestion)
def suggest_category_prefix(
    name: str, component_id: UUID, ignore: UUID | None = None,
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db),
):
    """Suggests a free prefix for a category named `name` among the categories of `component_id` (`ignore`: the
    category being renamed). The name is only read, never logged."""
    component = db.get(ProjectComponent, component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found.")
    return PrefixSuggestion(prefix=taxonomy.suggest_prefix(db, project.id, name, component_id, ignore=ignore))


@router.get("/{project_id}/structure-counts", response_model=StructureCountsOut)
def structure_counts(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    """The categories of each component and the active requirements of each component and category, for the
    Structure page's counts."""
    counts = taxonomy.structure_counts(db, project_id)
    component_ids = db.scalars(select(ProjectComponent.id).where(ProjectComponent.project_id == project_id)).all()
    return StructureCountsOut(
        components={
            cid: StructureComponentCounts(
                categories=counts.category_count.get(cid, 0), requirements=counts.requirements_in_component.get(cid, 0)
            )
            for cid in component_ids
        },
        categories={cat_id: n for cat_id, n in counts.requirements_in_category.items()},
    )


@router.post("/{project_id}/components", response_model=ComponentOut, status_code=status.HTTP_201_CREATED)
def create_component(
    payload: ComponentCreate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Creates a component at the end of the list; an omitted prefix is suggested from the name."""
    prefix = payload.prefix or taxonomy.suggest_prefix(db, project.id, payload.name)
    if not prefix:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A prefix is required: the name has no letter or digit to suggest one from.")
    # Same duplicate-prefix check as `rename_component` (and `create_category` per component); without it a
    # repeated prefix would hit the unique constraint and surface as a 500.
    if _component_prefix_taken(db, project.id, prefix):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A component with this prefix already exists.")
    count = len(db.scalars(select(ProjectComponent.id).where(ProjectComponent.project_id == project.id)).all())
    component = ProjectComponent(project_id=project.id, name=payload.name, prefix=prefix, sort_order=count)
    try:
        with db.begin_nested():
            db.add(component)
            db.flush()
    except IntegrityError:
        # A concurrent create took the prefix between the check and the insert: the same answer as the check.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A component with this prefix already exists.") from None
    log_event(db, entity_type="project_component", entity_id=component.id, action="created",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"name": component.name})
    db.commit()
    db.refresh(component)
    return component


@router.get("/{project_id}/components", response_model=list[ComponentOut])
def list_components(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProjectComponent).where(ProjectComponent.project_id == project_id).order_by(ProjectComponent.sort_order)
    ).all()


@router.post("/{project_id}/components/{component_id}/move", response_model=ComponentOut)
def move_component(
    project_id: UUID, component_id: UUID, payload: MoveDirection,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Moves a component up/down in display order (C-E-01)."""
    result = move_ordered(db, ProjectComponent, [ProjectComponent.project_id == project.id], component_id, payload.direction)
    log_event(db, entity_type="project_component", entity_id=component_id, action="reordered",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{project_id}/components/{component_id}", response_model=ComponentOut)
def rename_component(
    project_id: UUID, component_id: UUID, payload: ComponentUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames a component and/or changes its prefix. Existing requirements'
    `unique_code` values (e.g. `SW-PERF-014`) are generated once at creation
    and never retroactively rewritten (see `Requirement.unique_code`'s
    docstring) — a prefix change only affects codes assigned to requirements
    created after the change."""
    component = db.get(ProjectComponent, component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found.")
    prefix = payload.prefix or component.prefix
    if _component_prefix_taken(db, project.id, prefix, ignore=component_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A component with this prefix already exists.")
    component.name = payload.name
    component.prefix = prefix
    log_event(db, entity_type="project_component", entity_id=component.id, action="renamed",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A component with this prefix already exists.") from None
    db.refresh(component)
    return component


@router.delete("/{project_id}/components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_component(
    project_id: UUID, component_id: UUID,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a component. Only possible once it has no categories left —
    a category is where requirements actually attach (every
    `Requirement.category_id` implies a matching `component_id`, enforced
    at creation), so emptying a component of its categories first (deleting
    or reassigning each one via `delete_category`, which can target a
    category under a *different* component) always empties it of
    requirements too. Records of other types placed in the component (with
    or without a category) are not moved anywhere, so they block the delete
    until their placements are removed."""
    component = db.get(ProjectComponent, component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found.")
    has_categories = db.scalar(select(ProjectCategory.id).where(ProjectCategory.component_id == component_id)) is not None
    if has_categories:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This component still has categories — delete or reassign them first."
        )
    if component_placement_count(db, component_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Records are still placed in this component — remove their placements first."
        )
    log_event(db, entity_type="project_component", entity_id=component_id, action="deleted",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    db.delete(component)
    db.commit()


@router.post("/{project_id}/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Creates a category nested under `payload.component_id` (the
    component/category tree — C-G-07)."""
    component = db.get(ProjectComponent, payload.component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "component_id must belong to this project.")
    prefix = payload.prefix or taxonomy.suggest_prefix(db, project.id, payload.name, payload.component_id)
    if not prefix:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A prefix is required: the name has no letter or digit to suggest one from.")
    if _category_prefix_taken(db, payload.component_id, prefix):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        )
    count = len(db.scalars(select(ProjectCategory.id).where(ProjectCategory.component_id == payload.component_id)).all())
    category = ProjectCategory(
        project_id=project.id, component_id=payload.component_id, name=payload.name, prefix=prefix,
        sort_order=count,
    )
    try:
        with db.begin_nested():
            db.add(category)
            db.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        ) from None
    log_event(db, entity_type="project_category", entity_id=category.id, action="created",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"name": category.name})
    db.commit()
    db.refresh(category)
    return category


@router.get("/{project_id}/categories", response_model=list[CategoryOut])
def list_categories(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProjectCategory).where(ProjectCategory.project_id == project_id).order_by(ProjectCategory.sort_order)
    ).all()


@router.post("/{project_id}/categories/{category_id}/move", response_model=CategoryOut)
def move_category(
    project_id: UUID, category_id: UUID, payload: MoveDirection,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Moves a category up/down in display order among its siblings under
    the same parent component (C-E-02) — never reorders across components."""
    category = db.get(ProjectCategory, category_id)
    if category is None or category.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    result = move_ordered(db, ProjectCategory, [ProjectCategory.component_id == category.component_id], category_id, payload.direction)
    log_event(db, entity_type="project_category", entity_id=category_id, action="reordered",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{project_id}/categories/{category_id}", response_model=CategoryOut)
def rename_category(
    project_id: UUID, category_id: UUID, payload: CategoryUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames a category and/or changes its prefix (see `rename_component`'s
    docstring on why existing `unique_code`s are unaffected)."""
    category = db.get(ProjectCategory, category_id)
    if category is None or category.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    prefix = payload.prefix or category.prefix
    if _category_prefix_taken(db, category.component_id, prefix, ignore=category_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        )
    category.name = payload.name
    category.prefix = prefix
    log_event(db, entity_type="project_category", entity_id=category.id, action="renamed",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        ) from None
    db.refresh(category)
    return category


@router.post("/{project_id}/categories/{category_id}/move-to", response_model=CategoryOut)
def move_category_to_component(
    project_id: UUID, category_id: UUID, payload: CategoryMoveTo,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Moves a category under another component, last among its categories.

    Every requirement in the category, its aliases, other placed records and a proposed change follow it to the new
    component. Existing requirement codes keep the component prefix they were created with; requirements created
    afterwards take the new one (`services.taxonomy.move_category`). The category row is locked first so a concurrent
    delete or move waits.
    """
    category = db.scalar(select(ProjectCategory).where(ProjectCategory.id == category_id).with_for_update())
    if category is None or category.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    target = db.get(ProjectComponent, payload.component_id)
    if target is None or target.project_id != project.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "component_id must belong to this project.")
    source_id = category.component_id
    moved = taxonomy.move_category(db, category, target)
    log_event(db, entity_type="project_category", entity_id=category.id, action="moved",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"from_component_id": str(source_id), "to_component_id": str(target.id), "records_moved": str(moved)})
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{project_id}/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    project_id: UUID, category_id: UUID, reassign_to: UUID | None = None,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a category.

    Without `reassign_to` the delete succeeds only while nothing is attached: no requirement and no placed
    record of another type. Otherwise it is refused with 409 naming the counts, so a caller can offer a
    replacement. The category row is locked before the counts are read, so a requirement or placement added at
    the same moment either is counted or waits and then fails its foreign key. A project's only category, once
    empty, can be deleted.

    With `reassign_to`, every requirement in the category moves to it, which may be under a different component
    (unlike a display-position move, which stays within one component); the affected requirements'
    `component_id` moves to match, preserving the invariant that a requirement's component matches its
    category's component. `reassign_to` must be a different, existing category in the same project. Placements
    of other record types in the category move to `reassign_to` the same way.
    """
    category = db.scalar(
        select(ProjectCategory).where(ProjectCategory.id == category_id).with_for_update()
    )
    if category is None or category.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    if reassign_to is None:
        requirement_count = db.scalar(
            select(func.count()).select_from(Requirement).where(Requirement.category_id == category_id)
        ) or 0
        placement_count = category_placement_count(db, category_id)
        if requirement_count or placement_count:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"This category is still in use (requirements: {requirement_count}, placed records: {placement_count}) "
                "— move them to another category first, or delete it with a replacement.",
            )
        detail: dict[str, str] | None = None
    else:
        if reassign_to == category_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be a different category.")
        target = db.get(ProjectCategory, reassign_to)
        if target is None or target.project_id != project.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be an existing category in this project.")
        db.execute(
            update(Requirement)
            .where(Requirement.category_id == category_id)
            .values(category_id=reassign_to, component_id=target.component_id)
        )
        reassign_category_placements(db, category_id, target)
        detail = {"reassigned_to": str(reassign_to)}
    log_event(db, entity_type="project_category", entity_id=category_id, action="deleted",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail=detail)
    db.delete(category)
    db.commit()
