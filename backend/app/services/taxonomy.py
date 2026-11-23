"""
Module: services.taxonomy

The rules of a project's component and category tree that more than one caller needs, so the screen, API, imports and MCP
agree.

Responsibilities:
- `suggest_prefix` (a free identifier prefix from a name); `move_category` (under another component, carrying everything
  that records its component); `structure_counts` (for the Structure page and delete checks).

Design decisions: a suggestion reads sibling prefixes and reserves nothing, so the create-time duplicate check stays
authoritative. A requirement's code keeps the prefix it was created under, so a category move changes only the codes of
requirements created afterwards; the project-wide sequence keeps codes unique.

Dependencies: the project, requirement, alias, placement and change request models.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.change_request import ChangeRequestVersion
from app.models.placement import ArtefactPlacement
from app.models.project import ProjectCategory, ProjectComponent
from app.models.requirement import Requirement
from app.models.requirement_alias import RequirementAlias
from app.services.lookups import affected_rows

# The column width of `ProjectComponent.prefix` and `ProjectCategory.prefix`.
MAX_PREFIX_LENGTH = 20
# A suggestion is short enough to read in a code (`SW-PERF-014`) and well inside the column.
SUGGESTED_PREFIX_LENGTH = 6
# The column width of both names.
MAX_NAME_LENGTH = 255


def clean_prefix(value: str) -> str:
    """Trims a typed prefix.

    Args:
        value: The prefix as received.

    Returns:
        The trimmed prefix.

    Raises:
        ValueError: If it is blank or longer than `MAX_PREFIX_LENGTH` (the column would refuse it).
    """
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("A prefix must not be blank.")
    if len(cleaned) > MAX_PREFIX_LENGTH:
        raise ValueError(f"A prefix is at most {MAX_PREFIX_LENGTH} characters.")
    return cleaned


def clean_name(value: str) -> str:
    """Trims a component or category name.

    Raises:
        ValueError: If it is blank or longer than `MAX_NAME_LENGTH`.
    """
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("A name must not be blank.")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValueError(f"A name is at most {MAX_NAME_LENGTH} characters.")
    return cleaned


def _ascii_words(name: str) -> list[str]:
    """The name's words folded to upper-case ASCII letters and digits (accents removed, punctuation a separator)."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return [word for word in re.split(r"[^A-Za-z0-9]+", folded.upper()) if word]


def base_prefix(name: str) -> str:
    """The prefix a name suggests before any collision is resolved.

    Several words give the initial of each; one word gives its first letters. A name with no letter or digit gives
    an empty string.
    """
    words = _ascii_words(name)
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:SUGGESTED_PREFIX_LENGTH]
    return "".join(word[0] for word in words)[:SUGGESTED_PREFIX_LENGTH]


def free_prefix(candidate: str, used: set[str]) -> str:
    """`candidate`, or `candidate` with the smallest free number appended (`SW`, `SW2`, `SW3`).

    The comparison ignores case, the way a person reads a prefix. The number is appended inside `MAX_PREFIX_LENGTH`.
    """
    if not candidate:
        return ""
    taken = {u.upper() for u in used}
    if candidate.upper() not in taken:
        return candidate
    number = 2
    while True:
        suffix = str(number)
        attempt = candidate[: MAX_PREFIX_LENGTH - len(suffix)] + suffix
        if attempt.upper() not in taken:
            return attempt
        number += 1


def suggest_prefix(
    db: Session, project_id: uuid.UUID, name: str, component_id: uuid.UUID | None = None,
    *, ignore: uuid.UUID | None = None,
) -> str:
    """Suggests a free prefix for a new component, or for a new category under `component_id`.

    Args:
        db: Active session (read only).
        project_id: The project.
        name: The name being typed.
        component_id: The component a category is created under; `None` suggests for a component.
        ignore: A component or category being renamed, whose own prefix is not a collision.

    Returns:
        The suggestion, or an empty string when the name has no letter or digit (the field then stays empty and
        required).
    """
    if component_id is None:
        rows = select(ProjectComponent.id, ProjectComponent.prefix).where(ProjectComponent.project_id == project_id)
    else:
        rows = select(ProjectCategory.id, ProjectCategory.prefix).where(
            ProjectCategory.project_id == project_id, ProjectCategory.component_id == component_id
        )
    used = {prefix for row_id, prefix in db.execute(rows).all() if row_id != ignore}
    return free_prefix(base_prefix(name), used)


@dataclass(frozen=True)
class StructureCounts:
    """What sits in each component and category.

    Attributes:
        category_count: Categories per component id.
        requirements_in_component: Active requirements whose own component is the key.
        requirements_in_category: Active requirements whose own category is the key.
    """

    category_count: dict[uuid.UUID, int]
    requirements_in_component: dict[uuid.UUID, int]
    requirements_in_category: dict[uuid.UUID, int]


def structure_counts(db: Session, project_id: uuid.UUID) -> StructureCounts:
    """Counts the categories of each component and the requirements of each component and category, in three
    queries whatever the size of the tree."""
    categories = {
        cid: n for cid, n in db.execute(
            select(ProjectCategory.component_id, func.count()).where(ProjectCategory.project_id == project_id)
            .group_by(ProjectCategory.component_id)
        ).tuples()
    }
    active = (Requirement.project_id == project_id, Requirement.is_archived.is_(False))
    in_component = {
        cid: n for cid, n in db.execute(
            select(Requirement.component_id, func.count()).where(*active).group_by(Requirement.component_id)
        ).tuples()
    }
    in_category = {
        cid: n for cid, n in db.execute(
            select(Requirement.category_id, func.count()).where(*active).group_by(Requirement.category_id)
        ).tuples()
    }
    return StructureCounts(categories, in_component, in_category)


def move_category(db: Session, category: ProjectCategory, target: ProjectComponent) -> int:
    """Moves `category` under `target`, last among its categories, with everything that names the pair.

    Requirements whose own category it is, their aliases, other records placed in it and the pair a change request
    proposes all take the target component, so the invariant that a category's component matches every record in it
    holds. Existing requirement codes keep the component prefix they were created with.

    Args:
        db: Active session; the caller commits.
        category: The category to move.
        target: The component to move it under (a different component of the same project).

    Returns:
        How many records changed component.

    Raises:
        HTTPException: 400 if the target is the category's own component or another project's, or already has a
            category with the same prefix.
    """
    if target.project_id != category.project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "component_id must belong to this project.")
    if target.id == category.component_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The category is already under this component.")
    clash = db.scalar(
        select(ProjectCategory.id).where(ProjectCategory.component_id == target.id, ProjectCategory.prefix == category.prefix)
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        )
    moved = 0
    for model in (Requirement, ArtefactPlacement, RequirementAlias):
        moved += affected_rows(db.execute(
            update(model).where(model.category_id == category.id).values(component_id=target.id)
        ))
    db.execute(
        update(ChangeRequestVersion).where(ChangeRequestVersion.proposed_category_id == category.id)
        .values(proposed_component_id=target.id)
    )
    last = db.scalar(select(func.count()).select_from(ProjectCategory).where(ProjectCategory.component_id == target.id)) or 0
    category.component_id = target.id
    category.sort_order = last
    db.flush()
    return moved
