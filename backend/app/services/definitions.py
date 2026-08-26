"""
Module: services.definitions

Shared logic for the three "named row that other rows point to by FK"
definition tables introduced alongside project statuses, typed requirement
links, and requirement actions: `ProjectStatusDefinition` (org-scoped),
`RequirementLinkTypeDefinition` (org-scoped), and `ActionTypeDefinition`
(project-scoped).

All three share one design for rename/delete/reassignment rather than three
ad-hoc implementations:
    - Rename is a plain name update — every reference points at the row's
      id, never its name, so renaming never cascades.
    - A scope (organisation, for statuses/link-types; project, for
      action-types) must always retain at least one definition row, since
      the referencing FK (`Project.status_id`, `RequirementAction.
      action_type_id`) is NOT NULL — every creation flow needs at least one
      option to default to or offer in its picker.
    - Deleting a definition that's currently referenced requires an
      explicit `reassign_to_id` (validated to exist, belong to the same
      scope, and differ from the row being deleted) rather than a flat
      block — see `delete_definition_with_reassignment`'s docstring for the
      exact 404/409/400 behaviour.

`delete_definition_with_reassignment` is deliberately more elaborate than
`routers.projects.delete_component`'s flat "409 and stop" pattern: a
status/link-type/action-type has an obvious "reassign every referencing row
to a sibling" semantic a component/category doesn't, so blocking outright
would be a worse admin experience for no safety benefit.

This module also holds the three definition tables' seeded-default content
(`DEFAULT_PROJECT_STATUSES`, `DEFAULT_LINK_TYPES`, `DEFAULT_ACTION_TYPES`)
and the seeding helpers that write them — called from organisation creation
(statuses, link types) and project creation (action types), and reused by
migration 0012's backfill for every pre-existing organisation/project.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.action_type import ActionTypeDefinition
from app.models.project_status import ProjectStatusDefinition
from app.models.requirement_link_type import RequirementLinkTypeDefinition
from app.services.audit import log_event

# --- Seeded defaults (Section 2) --------------------------------------------

DEFAULT_PROJECT_STATUSES: list[str] = ["Proposed", "Active", "Abandoned", "Completed"]

# (forward_name, reverse_name) pairs. A symmetric relationship repeats the
# same name in both positions (e.g. "Related to").
DEFAULT_LINK_TYPES: list[tuple[str, str]] = [
    ("Related to", "Related to"),
    ("Derives from", "Is the source of"),
    ("Satisfies", "Is satisfied by"),
    ("Refines", "Is refined by"),
    ("Depends on", "Is a dependency of"),
    ("Conflicts with", "Conflicts with"),
    ("Implements", "Is implemented by"),
    ("Allocated to", "Has allocated"),
    ("Verified by", "Verifies"),
    ("Validated by", "Validates"),
    ("Mitigates", "Is mitigated by"),
    ("Equivalent to", "Equivalent to"),
]

DEFAULT_ACTION_TYPES: list[str] = ["Review", "Test"]


def seed_project_statuses(db: Session, organization_id: UUID) -> None:
    """Adds the 4 default `ProjectStatusDefinition` rows for a newly created
    organisation (not committed/flushed — caller owns the transaction)."""
    for i, name in enumerate(DEFAULT_PROJECT_STATUSES):
        db.add(ProjectStatusDefinition(organization_id=organization_id, name=name, sort_order=i))


def seed_link_types(db: Session, organization_id: UUID) -> None:
    """Adds the 12 default `RequirementLinkTypeDefinition` rows for a newly
    created organisation (not committed/flushed — caller owns the
    transaction)."""
    for i, (forward, reverse) in enumerate(DEFAULT_LINK_TYPES):
        db.add(
            RequirementLinkTypeDefinition(
                organization_id=organization_id, forward_name=forward, reverse_name=reverse, sort_order=i
            )
        )


def seed_action_types(db: Session, project_id: UUID) -> None:
    """Adds the 2 default `ActionTypeDefinition` rows (Review, Test) for a
    newly created project (not committed/flushed — caller owns the
    transaction). Mirrors how default `ProjectGroup`s are seeded per
    project today (C-U-10)."""
    for i, name in enumerate(DEFAULT_ACTION_TYPES):
        db.add(ActionTypeDefinition(project_id=project_id, name=name, sort_order=i))


def get_default_project_status_id(db: Session, organization_id: UUID) -> UUID:
    """Returns the id of the organisation's "first" project status (lowest
    `sort_order`) — used as the default `Project.status_id` for a newly
    created project. Every organisation is guaranteed at least one status
    (seeded at creation, backfilled by migration 0012, and never allowed to
    reach zero — see this module's docstring), so a missing result here
    indicates a genuinely broken state rather than an expected empty case.

    Raises:
        HTTPException: 500 if the organisation somehow has no statuses at all.
    """
    status_id = db.scalar(
        select(ProjectStatusDefinition.id)
        .where(ProjectStatusDefinition.organization_id == organization_id)
        .order_by(ProjectStatusDefinition.sort_order.asc())
    )
    if status_id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "This organisation has no project statuses configured."
        )
    return status_id


# --- Shared rename/delete/reassign rules (Section 4.0) ----------------------


def delete_definition_with_reassignment(
    db: Session,
    *,
    definition_model: type,
    scope_column: Any,
    scope_id: UUID,
    item_id: UUID,
    reassign_to_id: UUID | None,
    referencing_model: type,
    referencing_fk_column: Any,
    referencing_fk_name: str,
    entity_type: str,
    noun: str,
    plural_noun: str,
    reassign_verb: str,
    min_count_message: str,
    actor_id: UUID,
    organization_id: UUID | None,
    project_id: UUID | None,
    name_attr: str = "name",
    allow_empty: bool = False,
) -> None:
    """Deletes a definition row, applying the shared rename/delete/reassign
    rules described in this module's docstring. Writes are added to `db`
    but not committed — the caller commits once, so the reassignment bulk
    update and the delete happen in a single transaction.

    Args:
        db: Active database session.
        definition_model: The definition ORM class (e.g.
            `ProjectStatusDefinition`).
        scope_column: The definition model's scope column (e.g.
            `ProjectStatusDefinition.organization_id`).
        scope_id: The scope value (org id or project id) the row must
            belong to.
        item_id: The definition row being deleted.
        reassign_to_id: Optional replacement definition id for any row
            currently referencing `item_id`.
        referencing_model: The ORM class holding the FK that points at this
            definition (e.g. `Project`).
        referencing_fk_column: That FK column (e.g. `Project.status_id`).
        referencing_fk_name: The FK column's attribute name as a string,
            for the bulk `UPDATE ... SET <name> = ...` (e.g. `"status_id"`).
        entity_type: Audit log entity type string (e.g.
            `"project_status_definition"`).
        noun: Singular display noun for error messages (e.g. `"status"`).
        plural_noun: Plural display noun with count placeholder context
            (e.g. `"project(s)"`).
        reassign_verb: Verb used in the in-use error message (`"move"` for
            statuses/action-types, `"convert"` for link types, since
            reassigning a link changes its asserted meaning rather than
            just relocating it).
        min_count_message: 409 message when deleting would leave the scope
            with zero definitions.
        actor_id: Acting user, for audit logging.
        organization_id: Owning organisation, for audit logging.
        project_id: Owning project, for audit logging (None for org-scoped
            definitions).
        name_attr: Attribute name to read for the audit log's "name"
            detail (`"name"` for statuses/action-types, `"forward_name"`
            for link types, which have no single `name` column).
        allow_empty: Skips the "scope must retain at least one definition"
            floor check below. Only `action_types.py::delete_action_type`
            passes `True` today, and only for a project with a parent
            (hierarchical projects) — such a project can always fall back
            to its nearest ancestor's action types
            (`services.project_hierarchy.resolve_effective_action_types`),
            non-empty by induction since a root project's own floor is
            still unconditionally enforced. Statuses and link types have no
            equivalent fallback, so they never pass this.

    Raises:
        HTTPException: 404 if `item_id` isn't found in `scope_id`; 409 if
            deleting would leave the scope with zero definitions (unless
            `allow_empty`), or if the row is in use and no `reassign_to_id`
            was given; 400 if `reassign_to_id` equals `item_id` or doesn't
            resolve to an existing row in the same scope.
    """
    item = db.get(definition_model, item_id)
    if item is None or getattr(item, scope_column.key) != scope_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{noun.capitalize()} not found.")

    if not allow_empty:
        total_in_scope = db.scalar(
            select(func.count()).select_from(definition_model).where(scope_column == scope_id)
        ) or 0
        if total_in_scope <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, min_count_message)

    in_use_count = db.scalar(
        select(func.count()).select_from(referencing_model).where(referencing_fk_column == item_id)
    ) or 0

    if in_use_count == 0:
        # Not referenced anywhere: a plain delete. Any reassign_to_id the
        # caller passed is simply irrelevant here, per Section 4.0.
        log_event(
            db, entity_type=entity_type, entity_id=item.id, action="deleted", actor_id=actor_id,
            organization_id=organization_id, project_id=project_id, detail={"name": getattr(item, name_attr)},
        )
        db.delete(item)
        return

    if reassign_to_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This {noun} is used by {in_use_count} {plural_noun}. Pass reassign_to_id to {reassign_verb} "
            f"them to another {noun} before deleting.",
        )
    if reassign_to_id == item_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to_id must be different from the item being deleted.")
    target = db.get(definition_model, reassign_to_id)
    if target is None or getattr(target, scope_column.key) != scope_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"reassign_to_id must be an existing {noun} in the same scope.")

    db.execute(
        update(referencing_model).where(referencing_fk_column == item_id).values(**{referencing_fk_name: reassign_to_id})
    )
    log_event(
        db, entity_type=entity_type, entity_id=item.id, action="reassigned", actor_id=actor_id,
        organization_id=organization_id, project_id=project_id,
        detail={"reassigned_to": str(reassign_to_id), "count": in_use_count},
    )
    log_event(
        db, entity_type=entity_type, entity_id=item.id, action="deleted", actor_id=actor_id,
        organization_id=organization_id, project_id=project_id, detail={"name": getattr(item, name_attr)},
    )
    db.delete(item)
