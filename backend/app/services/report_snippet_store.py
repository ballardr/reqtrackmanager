"""
Module: services.report_snippet_store

Author-saved report snippets: save a selection of a layout's blocks, change its details, delete it, copy it to another
tier, and offer it to the designer next to the built-in set.

Responsibilities:
- `fragment_from_selection`: the blocks of a draft layout an author selected, with the page styles and variables they use.
- `validate_fragment`: the one check every way in (save, copy, bundle import, MCP) applies to a fragment.
- `create_snippet` / `update_snippet` / `delete_snippet` / `copy_snippet`: the stored row and its audit events.

Design decisions:
- **A saved snippet is the blocks exactly as saved**, with no parameters; the author edits after inserting. Its blocks
  change by saving a whole edited tree over them (`update_snippet(fragment=...)`), checked as a new snippet is.
- **Checked as a whole layout would be.** The fragment is wrapped in a minimal tree and validated by the tree validator,
  so no unknown block, no raw HTML, no field the registry does not know and no reference to something defined outside the
  selection (an alias of an enclosing `each`) can be stored. A rejected selection says why, with paths in the fragment.
- **Pictures obey the library rule at the tier.** A fragment naming a project's picture can be saved only at that
  project's level and is refused at the organisation level, and copying it up is refused the same way, with the picture
  named; publishing a project's picture to the whole organisation is the person's decision, not a side effect. Copying
  down keeps organisation pictures by reference; a project picture is usable by the project it lives in only.
- **Nothing is logged but keys and counts**: the audit events carry the tier, family and block count, never block text.

Dependencies: `models.report_snippet`, `services.report_layout_tree` (validation), `services.report_images` (library rule),
`services.report_snippet_scope`, `services.report_snippets` (insertion; offers the saved rows).
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.report_snippet import SavedReportSnippet
from app.services import definition_suppression, report_images
from app.services.audit import log_event
from app.services.report_layout_tree import TREE_SCHEMA_VERSION, TreeError, validate_tree
from app.services.report_snippet_scope import SNIPPET_KIND
from app.services.report_snippets import block_list

MAX_NAME_CHARS = 200
MAX_CATEGORY_CHARS = 60
MAX_DESCRIPTION_CHARS = 500
DEFAULT_CATEGORY = "Saved"
ROOT_KEYS = ("page_styles", "variables")


class SnippetNameTakenError(ValueError):
    """Another saved snippet of the same owner already has this name."""


class SnippetSaveError(ValueError):
    """The fragment cannot be stored; `errors` say why (paths are in the fragment, or `name` / `category` / `selection`)."""

    def __init__(self, errors: list[TreeError]) -> None:
        super().__init__("; ".join(e.message for e in errors))
        self.errors = errors


@dataclass(frozen=True)
class Fragment:
    """What a selection becomes: the blocks and the root things they use."""

    blocks: list[dict[str, Any]]
    root: dict[str, Any]


# --- the fragment --------------------------------------------------------------------------------------------------


def _section_styles(nodes: list[Any]) -> set[str]:
    """The page style names the `section` blocks in `nodes` (and below) use."""
    names: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "section" and isinstance(node.get("page_style"), str):
            names.add(node["page_style"])
        for key in ("children", "else_children"):
            if isinstance(node.get(key), list):
                names |= _section_styles(node[key])
    return names


def _uses_variable(blocks_json: str, name: str) -> bool:
    """Whether the blocks read variable `name` (`{"var": name}` or the placeholder `{{var.name}}`)."""
    return f'"var": {json.dumps(name)}' in blocks_json or re.search(rf"\{{\{{\s*var\.{re.escape(name)}\b", blocks_json) is not None


def fragment_from_selection(tree: dict[str, Any], container: str, start: int, count: int) -> Fragment:
    """The blocks `start` to `start + count` of the block list `container` in a draft, with what they use from the root.

    A container block is taken with everything inside it. The page styles its sections use and the variables its blocks read
    are carried, so the snippet works in a layout that has neither.

    Args:
        tree: The draft layout tree (it is not changed).
        container: The list of blocks: `nodes`, or `nodes[2].children` / `nodes[2].else_children`.
        start: Index of the first selected block.
        count: How many blocks, from 1.

    Returns:
        The fragment (deep copies).

    Raises:
        SnippetSaveError: The selection is not a run of blocks of the tree.
    """
    if not isinstance(tree, dict):
        raise SnippetSaveError([TreeError("selection", "The layout is not a tree.")])
    try:
        holder = block_list(tree, container)
    except ValueError as exc:
        raise SnippetSaveError([TreeError("selection", "That is not a list of blocks in this layout.")]) from exc
    if count < 1 or start < 0 or start + count > len(holder):
        raise SnippetSaveError([TreeError("selection", "Select at least one block of the layout.")])
    blocks = copy.deepcopy(holder[start:start + count])
    root: dict[str, Any] = {}
    wanted = _section_styles(blocks)
    styles = [s for s in tree.get("page_styles") or [] if isinstance(s, dict) and s.get("name") in wanted]
    if styles:
        root["page_styles"] = copy.deepcopy(styles)
    blocks_json = json.dumps(blocks)
    variables = [v for v in tree.get("variables") or [] if isinstance(v, dict) and _uses_variable(blocks_json, str(v.get("name")))]
    if variables:
        root["variables"] = copy.deepcopy(variables)
    return Fragment(blocks, root)


def validate_fragment(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, family: str, blocks: Any, root: Any,
) -> list[TreeError]:
    """Everything wrong with a fragment as stored at an owner's tier, else an empty list.

    Args:
        db: Active session (read only).
        organization_id: The owning organisation.
        project_id: The owning project, or `None` for an organisation-level snippet.
        family: `document` or `table`.
        blocks: The blocks.
        root: The root things (`page_styles`, `variables`).

    Returns:
        Structural problems (paths in the fragment, `nodes[...]`) and, when it is sound, any picture the tier may not use.
    """
    if not isinstance(blocks, list) or not blocks:
        return [TreeError("nodes", "A snippet needs at least one block.")]
    if not isinstance(root, dict) or any(key not in ROOT_KEYS for key in root):
        return [TreeError("root", f"May hold only: {', '.join(ROOT_KEYS)}.")]
    tree: dict[str, Any] = {"schema_version": TREE_SCHEMA_VERSION, "family": family, "nodes": copy.deepcopy(blocks)}
    tree.update(copy.deepcopy(root))
    analysis = validate_tree(tree, family=family)
    if analysis.errors:
        return list(analysis.errors)
    return report_images.image_problems(db, organization_id, project_id, tree)


# --- names ---------------------------------------------------------------------------------------------------------


def _clean_details(name: str, description: str, category: str) -> tuple[str, str, str]:
    """The trimmed name, description and category.

    Raises:
        SnippetSaveError: A field is empty or too long.
    """
    name, description, category = name.strip(), description.strip(), (category.strip() or DEFAULT_CATEGORY)
    errors: list[TreeError] = []
    if not name or len(name) > MAX_NAME_CHARS:
        errors.append(TreeError("name", f"A name of 1 to {MAX_NAME_CHARS} characters is needed."))
    if len(category) > MAX_CATEGORY_CHARS:
        errors.append(TreeError("category", f"At most {MAX_CATEGORY_CHARS} characters."))
    if len(description) > MAX_DESCRIPTION_CHARS:
        errors.append(TreeError("description", f"At most {MAX_DESCRIPTION_CHARS} characters."))
    if errors:
        raise SnippetSaveError(errors)
    return name, description, category


def _owner_clause(organization_id: uuid.UUID, project_id: uuid.UUID | None) -> list[Any]:
    return [
        SavedReportSnippet.organization_id == organization_id,
        SavedReportSnippet.project_id.is_(None) if project_id is None else SavedReportSnippet.project_id == project_id,
    ]


def _assert_name_free(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str, *, except_id: uuid.UUID | None = None,
) -> None:
    """Raises `SnippetNameTakenError` when the owner already has a saved snippet called `name` (case-insensitive)."""
    for existing_id, existing_name in db.execute(
        select(SavedReportSnippet.id, SavedReportSnippet.name).where(*_owner_clause(organization_id, project_id))
    ):
        if existing_name.casefold() == name.casefold() and existing_id != except_id:
            raise SnippetNameTakenError(f'A saved snippet called "{name}" already exists here.')


def suggest_name(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str) -> str:
    """The first free `<name> (copy)`, `(copy 2)` ... among the owner's saved snippets."""
    taken = {n.casefold() for n in db.scalars(select(SavedReportSnippet.name).where(*_owner_clause(organization_id, project_id)))}
    base = name[: MAX_NAME_CHARS - 10]
    for number in range(1, 1000):
        candidate = f"{base} (copy)" if number == 1 else f"{base} (copy {number})"
        if candidate.casefold() not in taken:
            return candidate
    return f"{base} (copy {uuid.uuid4().hex[:6]})"


# --- storing -------------------------------------------------------------------------------------------------------


def create_snippet(
    db: Session,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    name: str,
    description: str,
    category: str,
    family: str,
    blocks: list[dict[str, Any]],
    root: dict[str, Any],
    actor_id: uuid.UUID | None,
) -> SavedReportSnippet:
    """Stores a fragment as a saved snippet of the organisation or project.

    Args:
        db: Active session (the caller commits).
        organization_id: The owning organisation.
        project_id: The owning project, or `None` for the organisation.
        name: Display name, unique among the owner's saved snippets.
        description: One sentence about what it adds.
        category: The picker group (`""` = `Saved`).
        family: `document` or `table`.
        blocks: The blocks.
        root: The page styles and variables the blocks use.
        actor_id: The author.

    Returns:
        The new row.

    Raises:
        SnippetSaveError: A detail is invalid or the fragment is not (the errors say where).
        SnippetNameTakenError: The owner already has a saved snippet of that name.
    """
    name, description, category = _clean_details(name, description, category)
    errors = validate_fragment(db, organization_id, project_id, family, blocks, root)
    if errors:
        raise SnippetSaveError(errors)
    _assert_name_free(db, organization_id, project_id, name)
    row = SavedReportSnippet(
        organization_id=organization_id, project_id=project_id, name=name, description=description, category=category,
        family=family, blocks=blocks, root=root, created_by=actor_id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:  # a concurrent save of the same name slipped past the check
        db.rollback()
        raise SnippetNameTakenError(f'A saved snippet called "{name}" already exists here.') from exc
    log_event(
        db, entity_type="report_snippet", entity_id=row.id, action="created", actor_id=actor_id,
        organization_id=organization_id, project_id=project_id, detail={"family": family, "blocks": len(blocks)},
    )
    return row


def update_snippet(
    db: Session, row: SavedReportSnippet, *, name: str | None, description: str | None, category: str | None,
    actor_id: uuid.UUID | None, fragment: Fragment | None = None,
) -> SavedReportSnippet:
    """Changes a saved snippet's name, description, category or blocks.

    Args:
        db: Active session (the caller commits).
        row: The snippet (the caller has checked the right to change it).
        name: The new name, or `None` to keep it.
        description: The new description, or `None` to keep it.
        category: The new category, or `None` to keep it.
        actor_id: The author of the change.
        fragment: The blocks (and what they use from the root) that replace the snippet's, or `None` to keep them.

    Raises:
        SnippetSaveError: A detail is invalid or the new fragment is not usable at the snippet's tier.
        SnippetNameTakenError: The owner already has another saved snippet of that name.
    """
    new_name, new_description, new_category = _clean_details(
        row.name if name is None else name, row.description if description is None else description,
        row.category if category is None else category,
    )
    changed = [
        key for key, old, new in (
            ("name", row.name, new_name), ("description", row.description, new_description), ("category", row.category, new_category),
        ) if old != new
    ]
    if fragment is not None:
        errors = validate_fragment(db, row.organization_id, row.project_id, row.family, fragment.blocks, fragment.root)
        if errors:
            raise SnippetSaveError(errors)
        if fragment.blocks != row.blocks or fragment.root != row.root:
            changed.append("blocks")
    if not changed:
        return row
    if "name" in changed:
        _assert_name_free(db, row.organization_id, row.project_id, new_name, except_id=row.id)
    row.name, row.description, row.category = new_name, new_description, new_category
    if "blocks" in changed and fragment is not None:
        row.blocks, row.root = fragment.blocks, fragment.root
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise SnippetNameTakenError(f'A saved snippet called "{new_name}" already exists here.') from exc
    log_event(
        db, entity_type="report_snippet", entity_id=row.id, action="updated", actor_id=actor_id,
        organization_id=row.organization_id, project_id=row.project_id, detail={"fields": changed, "blocks": len(row.blocks)},
    )
    return row


def delete_snippet(db: Session, row: SavedReportSnippet, *, actor_id: uuid.UUID | None) -> None:
    """Deletes a saved snippet and every project's tombstone that hid it (layouts already built from it are unchanged)."""
    log_event(
        db, entity_type="report_snippet", entity_id=row.id, action="deleted", actor_id=actor_id,
        organization_id=row.organization_id, project_id=row.project_id, detail={"family": row.family, "blocks": len(row.blocks)},
    )
    definition_suppression.forget_definition(db, SNIPPET_KIND, row.id)  # no foreign key holds a project's tombstone
    db.delete(row)
    db.flush()


def copy_snippet(
    db: Session, source: SavedReportSnippet, *, organization_id: uuid.UUID, project_id: uuid.UUID | None, name: str | None,
    actor_id: uuid.UUID | None,
) -> SavedReportSnippet:
    """Copies a saved snippet to the organisation (`project_id` None) or to a project, as a snippet of its own.

    Args:
        db: Active session (the caller commits).
        source: The snippet to copy (the caller has checked the right to read it).
        organization_id: The destination organisation (the source's).
        project_id: The destination project, or `None` for the organisation.
        name: The new name, or `None` for the first free `<name> (copy)` at the destination.
        actor_id: The author of the copy.

    Raises:
        SnippetSaveError: The fragment is not usable at the destination, for instance a project picture copied up.
        SnippetNameTakenError: The destination owns a snippet of that name.
    """
    return create_snippet(
        db, organization_id=organization_id, project_id=project_id,
        name=name if name else suggest_name(db, organization_id, project_id, source.name),
        description=source.description, category=source.category, family=source.family,
        blocks=copy.deepcopy(source.blocks), root=copy.deepcopy(source.root), actor_id=actor_id,
    )


__all__ = [
    "DEFAULT_CATEGORY", "Fragment", "SnippetNameTakenError", "SnippetSaveError", "copy_snippet", "create_snippet",
    "delete_snippet", "fragment_from_selection", "suggest_name", "update_snippet", "validate_fragment",
]
