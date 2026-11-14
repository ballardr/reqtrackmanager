"""
Module: modules.architecture.allocation_export

How a project bundle carries the dismissed allocation suggestions (`allocation`): which requirement and which element
a person decided not to allocate. Kept apart from `export` so that file does not grow with every table.

Design decisions (Decided by: Agent):
- A dismissal is named by the requirement's code and the element's code, both information from the source project; an
  entry whose requirement or element did not import is dropped with a warning.
- The dismissal's time is not carried: an import writes it afresh, after the elements and their places, so the
  dismissal still applies to the element that stayed in the component (`allocation.dismissal_applies`).
- A template never copies dismissals (`TEMPLATE_REASON`): the codes an import numbers afresh would let a decision
  attach to a different pair.

Dependencies: this module's models, `models.requirement` and the bundle helpers `UserResolver`, `BundleImportWarnings`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.requirement import Requirement
from app.models.user import User
from app.modules.architecture.models import ArchitectureAllocationDismissal, ArchitectureElement
from app.services.bundle_common import BundleImportWarnings, UserResolver

DISMISSALS_KEY = "architecture_allocation_dismissals"
TEMPLATE_REASON = (
    "A dismissal names a requirement and an element by codes that a new project numbers afresh, so a copied decision "
    "could attach to a different pair; each project decides for itself."
)


def export_dismissals(db: Session, project: Project, emails: dict[UUID, str]) -> list[dict[str, Any]]:
    """The project's dismissals as `{requirement_code, element_code, dismissed_by_email}`, in code order, in three
    statements however many there are.

    Args:
        db: Active session (read only).
        project: The project exported.
        emails: `{user id: email}` of the people the bundle names; a dismisser missing from it is exported with none.
    """
    rows = list(db.scalars(select(ArchitectureAllocationDismissal).where(ArchitectureAllocationDismissal.project_id == project.id)))
    if not rows:
        return []
    requirement_rows = db.execute(
        select(Requirement.id, Requirement.unique_code).where(Requirement.id.in_({r.requirement_id for r in rows}))
    ).tuples()
    element_rows = db.execute(
        select(ArchitectureElement.id, ArchitectureElement.unique_code).where(ArchitectureElement.id.in_({r.element_id for r in rows}))
    ).tuples()
    requirements = {rid: code for rid, code in requirement_rows}
    elements = {eid: code for eid, code in element_rows}
    return sorted(
        (
            {
                "requirement_code": requirements[r.requirement_id], "element_code": elements[r.element_id],
                "dismissed_by_email": emails.get(r.dismissed_by) if r.dismissed_by else None,
            }
            for r in rows if r.requirement_id in requirements and r.element_id in elements
        ),
        key=lambda e: (e["requirement_code"], e["element_code"]),
    )


def import_dismissals(
    db: Session, project: Project, entries: list[dict[str, Any]], elements: dict[str, UUID], current_user: User,
    users: UserResolver, warnings: BundleImportWarnings,
) -> None:
    """Recreates the dismissals against the new requirements and elements.

    Args:
        db: Active session; rows are flushed, not committed.
        project: The importing project.
        entries: `export_dismissals` output.
        elements: `{element code in the bundle: new element id}`.
        current_user: The importing user (the dismisser when the original cannot be matched).
        users: The import's user resolver.
        warnings: Collects each entry that could not be recreated.
    """
    if not entries:
        return
    requirements = {
        code: rid for rid, code in db.execute(select(Requirement.id, Requirement.unique_code).where(Requirement.project_id == project.id)).tuples()
    }
    seen: set[tuple[UUID, UUID]] = set()
    for entry in entries:
        requirement_id, element_id = requirements.get(entry.get("requirement_code", "")), elements.get(entry.get("element_code", ""))
        if requirement_id is None or element_id is None:
            warnings.add(
                f"System Architecture: dismissed allocation {entry.get('requirement_code')} -> {entry.get('element_code')} skipped — "
                "the requirement or the element is not in this project."
            )
            continue
        if (requirement_id, element_id) in seen:
            continue
        seen.add((requirement_id, element_id))
        who = users.resolve(entry.get("dismissed_by_email"), required=False, context="System Architecture allocation dismisser")
        db.add(ArchitectureAllocationDismissal(
            project_id=project.id, requirement_id=requirement_id, element_id=element_id, dismissed_by=who or current_user.id,
        ))
    db.flush()
