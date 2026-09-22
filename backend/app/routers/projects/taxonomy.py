"""
Module: routers.projects.taxonomy

The component/category tree requirements attach to (C-G-07), with
manual display ordering for each (C-E-01/C-E-02). A category is always
nested under one component; a requirement's `category_id` always implies
a matching `component_id` (enforced here and on category reassignment).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement
from app.models.user import User
from app.schemas.project import CategoryCreate, CategoryOut, CategoryUpdate, ComponentCreate, ComponentOut, ComponentUpdate, MoveDirection
from app.services.audit import log_event
from app.services.ordering import move_ordered
from app.services.rbac import require_project_manage, require_project_view

router = APIRouter(tags=["projects-taxonomy"])


@router.post("/{project_id}/components", response_model=ComponentOut, status_code=status.HTTP_201_CREATED)
def create_component(
    payload: ComponentCreate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    count = len(db.scalars(select(ProjectComponent.id).where(ProjectComponent.project_id == project.id)).all())
    component = ProjectComponent(project_id=project.id, name=payload.name, prefix=payload.prefix, sort_order=count)
    db.add(component)
    db.flush()
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
    existing = db.scalar(
        select(ProjectComponent.id).where(
            ProjectComponent.project_id == project.id, ProjectComponent.prefix == payload.prefix,
            ProjectComponent.id != component_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A component with this prefix already exists.")
    component.name = payload.name
    component.prefix = payload.prefix
    log_event(db, entity_type="project_component", entity_id=component.id, action="renamed",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    db.commit()
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
    requirements too, making this a simple, unconditional delete rather
    than needing its own reassignment step."""
    component = db.get(ProjectComponent, component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found.")
    has_categories = db.scalar(select(ProjectCategory.id).where(ProjectCategory.component_id == component_id)) is not None
    if has_categories:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This component still has categories — delete or reassign them first."
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
    existing = db.scalar(
        select(ProjectCategory.id).where(
            ProjectCategory.component_id == payload.component_id, ProjectCategory.prefix == payload.prefix
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        )
    count = len(db.scalars(select(ProjectCategory.id).where(ProjectCategory.component_id == payload.component_id)).all())
    category = ProjectCategory(
        project_id=project.id, component_id=payload.component_id, name=payload.name, prefix=payload.prefix,
        sort_order=count,
    )
    db.add(category)
    db.flush()
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
    existing = db.scalar(
        select(ProjectCategory.id).where(
            ProjectCategory.component_id == category.component_id, ProjectCategory.prefix == payload.prefix,
            ProjectCategory.id != category_id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        )
    category.name = payload.name
    category.prefix = payload.prefix
    log_event(db, entity_type="project_category", entity_id=category.id, action="renamed",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{project_id}/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    project_id: UUID, category_id: UUID, reassign_to: UUID,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a category, reassigning every requirement that belonged to it
    to `reassign_to` — which may be a category under a *different*
    component (unlike moving a category's display position, which stays
    within one component). Crossing components on reassignment also moves
    the affected requirements' `component_id` to match, preserving the
    invariant that a requirement's component always matches its category's
    component. `reassign_to` must be a different, existing category in the
    same project — if this is the project's only remaining category, no
    valid target exists and deletion is refused.
    """
    category = db.get(ProjectCategory, category_id)
    if category is None or category.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    if reassign_to == category_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be a different category.")
    target = db.get(ProjectCategory, reassign_to)
    if target is None or target.project_id != project.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be an existing category in this project.")
    db.execute(
        Requirement.__table__.update()
        .where(Requirement.category_id == category_id)
        .values(category_id=reassign_to, component_id=target.component_id)
    )
    log_event(db, entity_type="project_category", entity_id=category_id, action="deleted",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"reassigned_to": str(reassign_to)})
    db.delete(category)
    db.commit()
