"""
Module: services.report_snippets

Report snippets: list the ones a scope can use and apply one to a draft layout tree.

Responsibilities:
- `visible_snippets`: the snippets whose module is on for the scope, each with the choices its parameters offer there, then the
  author-saved ones the scope reaches (`services.report_snippet_store`; they have no parameters and insert like any other).
- `apply_snippet`: build the tree a snippet produces when inserted into a draft, and say what changed. Nothing is stored.

Design decisions:
- **A snippet is copied in, never linked.** The result is an ordinary tree; a later change to a snippet never alters a
  layout, and the designer decides whether to keep the result.
- **Nothing is stored or logged.** The designer holds the draft; the server only builds the tree and validates it, the
  posture of the validate endpoint. Parameter values and text are never logged.
- **Parameters fill named paths, not text tokens**: the fragment is a valid tree from the start, and a value cannot land
  in a field it was not declared for. A picture is checked against the layout owner's library (an organisation layout
  cannot take a project's picture, whoever authored the snippet) and a record type against what the scope can report.
- **The layout's other problems are not the snippet's.** A draft is often mid-edit; only problems inside what the
  snippet added, or that it caused (the page-style or block cap), refuse the insertion. The count of the layout's own
  problems is returned so the designer can say so.
- **Root additions reuse, rename or refuse, never overwrite.** A page style identical to one the layout has is reused;
  a different one with the same name is renamed (`Cover 2`) and the inserted sections follow; a clashing variable is
  refused, because the text that reads it cannot be rewritten safely.
- **The blocks go where the designer's Add block puts them**: a list of blocks (`nodes`, or a container's `children` /
  `else_children`) and an index in it.

Dependencies: `modules.registry` (snippets, modules), `services.report_layout_tree` (validation),
`services.report_layout_designer` (record types a scope can report), `services.report_images` (library rule).
"""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.file import FileAsset
from app.models.project import Project
from app.models.report_snippet import SavedReportSnippet
from app.modules.registry import (
    ReportSnippet,
    ReportSnippetParameter,
    get_record_attachment_providers,
    get_report_snippets,
    is_module_enabled,
    is_module_enabled_for_project,
)
from app.services import report_images, report_layout_designer, report_snippet_scope
from app.services.report_layout_tree import MAX_NODES, TreeError, validate_tree
from app.services.report_page_styles import MAX_STYLE_NAME_CHARS

#: The keys of a layout a snippet's `root` may add to.
ROOT_KEYS = ("page_styles", "variables")
#: The keys that hold a list of blocks, which a target list path is made of.
BLOCK_LIST_KEYS = ("nodes", "children", "else_children")
SAVED_KEY_PREFIX = "saved-"
_TOKEN = re.compile(r"([a-z_]+)|\[(\d+)\]")


@dataclass(frozen=True)
class ParameterChoice:
    """One value a `record_type` parameter can take in a scope: the type's key and its display name."""

    value: str
    label: str


@dataclass(frozen=True)
class VisibleParameter:
    """A parameter as one scope offers it: the declaration and, for a record type, the types to choose from."""

    parameter: ReportSnippetParameter
    choices: tuple[ParameterChoice, ...] = ()


@dataclass(frozen=True)
class SavedOrigin:
    """Where an author-saved snippet comes from: its row id and `project`, `ancestor` or `organization`."""

    id: uuid.UUID
    origin: str


@dataclass(frozen=True)
class VisibleSnippet:
    """A snippet a scope can use: the declaration, the module that contributed it (`None`: the platform) and its parameters.

    `saved` is set for an author-saved snippet (and then `module_key` is `None` and there are no parameters).
    """

    snippet: ReportSnippet
    module_key: str | None
    parameters: tuple[VisibleParameter, ...]
    saved: SavedOrigin | None = None


@dataclass
class SnippetOutcome:
    """The result of applying a snippet.

    Attributes:
        tree: The new tree, or `None` when the insertion was refused.
        changes: What was done, in words ("Added page style Cover").
        errors: Why it was refused (paths are in the resulting tree, or `parameters.<key>` / `target`), else empty.
        inserted_at: The path of the first inserted block (`nodes[3]`), when applied.
        count: How many blocks were inserted.
        problems_elsewhere: How many problems the layout already had, which the insertion left alone.
    """

    tree: dict[str, Any] | None = None
    changes: list[str] = field(default_factory=list)
    errors: list[TreeError] = field(default_factory=list)
    inserted_at: str | None = None
    count: int = 0
    problems_elsewhere: int = 0


def snippet_key(snippet_id: uuid.UUID) -> str:
    """The key an author-saved snippet is offered and applied under; it cannot clash with a built-in or module key."""
    return f"{SAVED_KEY_PREFIX}{snippet_id}"


def saved_report_snippet(row: SavedReportSnippet) -> ReportSnippet:
    """A stored row as the snippet the apply service inserts (no parameters; true in every format)."""
    return ReportSnippet(
        key=snippet_key(row.id), name=row.name, description=row.description, category=row.category,
        blocks=tuple(copy.deepcopy(row.blocks)), family=row.family, root=copy.deepcopy(row.root),
    )


# --- listing -------------------------------------------------------------------------------------------------------


def scope_record_types(db: Session, organization_id: uuid.UUID, project: Project | None) -> list[ParameterChoice]:
    """The reportable record types the scope's layouts can name, by display name.

    Args:
        db: Active session (read only).
        organization_id: The organisation.
        project: The project for a project layout, `None` for an organisation layout.

    Returns:
        One choice per type whose module is on for the scope.
    """
    catalogue = (
        report_layout_designer.catalogue_for_project(db, project) if project is not None
        else report_layout_designer.catalogue_for_organization(db, organization_id)
    )
    return [ParameterChoice(entry.type, entry.label) for entry in catalogue.types]


def visible_snippets(db: Session, organization_id: uuid.UUID, project: Project | None) -> list[VisibleSnippet]:
    """The snippets a scope can use.

    A snippet contributed by a module is offered only where that module is on (for the organisation, or for the project),
    so an author is never offered one about records they cannot report.

    Args:
        db: Active session (read only).
        organization_id: The organisation.
        project: The project for a project layout, `None` for an organisation layout.

    Returns:
        Platform snippets first, then each module's, in registration order, then the author-saved ones the scope can reach
        (an organisation's own; for a project its own, its ancestors' and the organisation's, less those it hides).
    """
    types = scope_record_types(db, organization_id, project)
    attachable = set(get_record_attachment_providers())
    found: list[VisibleSnippet] = []
    for module_key, snippet in get_report_snippets():
        if module_key is not None:
            enabled = (
                is_module_enabled_for_project(db, project.id, module_key) if project is not None
                else is_module_enabled(db, organization_id, module_key)
            )
            if not enabled:
                continue
        parameters = tuple(
            VisibleParameter(
                parameter,
                tuple(c for c in types if parameter.record_types == "reportable" or c.value in attachable)
                if parameter.kind == "record_type" else (),
            )
            for parameter in snippet.parameters
        )
        found.append(VisibleSnippet(snippet, module_key, parameters))
    if project is None:
        saved = [(row, "organization") for row in report_snippet_scope.list_org_snippets(db, organization_id)]
    else:
        saved = [(s.snippet, s.origin) for s in report_snippet_scope.resolve_project_snippets(db, project) if not s.hidden]
    found += [VisibleSnippet(saved_report_snippet(row), None, (), SavedOrigin(row.id, origin)) for row, origin in saved]
    return found


# --- paths ---------------------------------------------------------------------------------------------------------


def _tokens(path: str) -> list[str | int]:
    """Splits `nodes[2].children[0].source` into `["nodes", 2, "children", 0, "source"]` (`ValueError` when malformed)."""
    tokens: list[str | int] = []
    position = 0
    for match in _TOKEN.finditer(path):
        gap = path[position:match.start()]
        if gap not in ("", "."):
            raise ValueError(path)
        tokens.append(match.group(1) if match.group(1) else int(match.group(2)))
        position = match.end()
    if position != len(path) or not tokens:
        raise ValueError(path)
    return tokens


def _walk(root: Any, tokens: list[str | int]) -> Any:
    """The value at `tokens` below `root` (`KeyError` / `IndexError` / `TypeError` when it is not there)."""
    value = root
    for token in tokens:
        value = value[token]
    return value


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    """Sets the existing key at `path` (a declared target) to `value`.

    Raises:
        ValueError: The path is malformed.
        KeyError: The path does not exist in the fragment (a defect in the snippet's declaration).
    """
    tokens = _tokens(path)
    holder = _walk(root, tokens[:-1])
    last = tokens[-1]
    if isinstance(last, str) and last not in holder:
        raise KeyError(path)
    holder[last] = value


def block_list(tree: dict[str, Any], path: str) -> list[Any]:
    """The list of blocks at a target list path (`nodes`, `nodes[2].children`, `nodes[2].else_children`).

    Raises:
        ValueError: The path is not a list of blocks of the tree.
    """
    try:
        tokens = _tokens(path)
        keys = [t for t in tokens if isinstance(t, str)]
        found = _walk(tree, tokens)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError(path) from exc
    if tokens[0] != "nodes" or not isinstance(tokens[-1], str) or any(k not in BLOCK_LIST_KEYS for k in keys) or not isinstance(found, list):
        raise ValueError(path)
    return found


# --- values --------------------------------------------------------------------------------------------------------


def _resolve_values(
    db: Session, snippet: VisibleSnippet, given: Mapping[str, Any], organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> tuple[dict[str, str], list[TreeError]]:
    """Checks the parameter values and fills defaults.

    Returns:
        The values by key, and the problems (`parameters.<key>`) with them.
    """
    errors: list[TreeError] = []
    values: dict[str, str] = {}
    declared = {p.parameter.key for p in snippet.parameters}
    errors += [TreeError(f"parameters.{key}", "This snippet has no such parameter.") for key in given if key not in declared]
    for visible in snippet.parameters:
        parameter = visible.parameter
        path = f"parameters.{parameter.key}"
        raw = given.get(parameter.key)
        value = raw.strip() if isinstance(raw, str) else ""
        if raw is not None and not isinstance(raw, str):
            errors.append(TreeError(path, "Must be text."))
            continue
        if not value and parameter.default is not None:
            value = parameter.default
        if not value:
            errors.append(TreeError(path, f"{parameter.label}: choose one." if parameter.kind != "text" else f"{parameter.label}: write something."))
            continue
        problem = _value_problem(db, visible, value, organization_id, project_id)
        if problem:
            errors.append(TreeError(path, problem))
            continue
        values[parameter.key] = value
    return values, errors


def _value_problem(
    db: Session, visible: VisibleParameter, value: str, organization_id: uuid.UUID, project_id: uuid.UUID | None,
) -> str | None:
    """Why `value` is not acceptable for the parameter, else `None`."""
    parameter = visible.parameter
    if parameter.kind == "text":
        return f"Too long (at most {parameter.max_length} characters)." if len(value) > parameter.max_length else None
    if parameter.kind == "record_type":
        return None if value in {c.value for c in visible.choices} else "Not a kind of record this scope can use here."
    if parameter.kind == "image":
        try:
            file_id = uuid.UUID(value)
        except ValueError:
            return "Pick an image from the library."
        asset = db.get(FileAsset, file_id)
        if asset is None:
            return "This image no longer exists in the library. Pick another."
        if not report_images.usable_by_layout(asset, organization_id, project_id):
            where = "the organisation's library" if project_id is None else "this project's or the organisation's library"
            return f'"{asset.filename}" is not in {where}. An organisation layout can only use organisation images.'
        return None
    return f"Unknown parameter kind {parameter.kind!r}."


# --- applying ------------------------------------------------------------------------------------------------------


def _free_style_name(name: str, taken: set[str]) -> str:
    """`name` with the least number after it that no page style uses (`Cover 2`), within the name length limit."""
    number = 2
    while True:
        suffix = f" {number}"
        candidate = f"{name[:MAX_STYLE_NAME_CHARS - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        number += 1


def _rename_style_uses(nodes: list[Any], old: str, new: str) -> None:
    """Points every `section` in `nodes` (and below) that uses page style `old` at `new`."""
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "section" and node.get("page_style") == old:
            node["page_style"] = new
        for key in ("children", "else_children"):
            if isinstance(node.get(key), list):
                _rename_style_uses(node[key], old, new)


def _merge_root(result: dict[str, Any], fragment: dict[str, Any], outcome: SnippetOutcome) -> tuple[list[int], bool]:
    """Adds the fragment's page styles and variables to `result`, reusing identical ones and renaming a clashing style.

    Returns:
        The indices in `result["page_styles"]` of the styles added, and whether anything was refused.
    """
    added: list[int] = []
    styles = fragment.get("page_styles") or []
    if styles:
        existing = result.setdefault("page_styles", [])
        if not isinstance(existing, list):
            outcome.errors.append(TreeError("page_styles", "The layout's page styles are not a list; fix them first."))
            return added, True
        for style in styles:
            by_name: dict[str, dict[str, Any]] = {s["name"]: s for s in existing if isinstance(s, dict) and isinstance(s.get("name"), str)}
            name = style["name"]
            if name not in by_name:
                existing.append(style)
                added.append(len(existing) - 1)
                outcome.changes.append(f'Added page style "{name}".')
            elif by_name[name] == style:
                outcome.changes.append(f'Used the layout\'s existing page style "{name}".')
            else:
                new = _free_style_name(name, set(by_name))
                renamed = {**style, "name": new}
                _rename_style_uses(fragment["nodes"], name, new)
                existing.append(renamed)
                added.append(len(existing) - 1)
                outcome.changes.append(f'Added page style "{new}": the layout already has a different "{name}".')
    for variable in fragment.get("variables") or []:
        existing_vars = result.setdefault("variables", [])
        if not isinstance(existing_vars, list):
            outcome.errors.append(TreeError("variables", "The layout's variables are not a list; fix them first."))
            return added, True
        match = next((v for v in existing_vars if isinstance(v, dict) and v.get("name") == variable["name"]), None)
        if match is None:
            existing_vars.append(variable)
            outcome.changes.append(f'Added variable "{variable["name"]}".')
        elif match == variable:
            outcome.changes.append(f'Used the layout\'s existing variable "{variable["name"]}".')
        else:
            outcome.errors.append(TreeError(
                "variables", f'The layout already has a different variable called "{variable["name"]}". Rename or remove it first.',
            ))
            return added, True
    return added, False


def _image_aspect(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None) -> Callable[[str], float | None]:
    """A function giving a library image's width over height by file id, or `None` when it cannot be known."""

    def aspect(file_id: str) -> float | None:
        try:
            parsed = uuid.UUID(file_id)
        except ValueError:
            return None
        image, _reason = report_images.load_image(db, organization_id, project_id, parsed)
        if image is None or not image.width_px or not image.height_px:
            return None
        return image.width_px / image.height_px

    return aspect


def _unshift(path: str, list_path: str, index: int, count: int) -> str:
    """Maps an error path in the new tree back to the old one: blocks after the inserted ones move up by `count`."""
    match = re.match(rf"^{re.escape(list_path)}\[(\d+)\]", path)
    if match and int(match.group(1)) >= index + count:
        return f"{list_path}[{int(match.group(1)) - count}]{path[match.end():]}"
    return path


def _under(path: str, prefix: str) -> bool:
    """Whether `path` is `prefix` or inside it."""
    return path == prefix or path.startswith((f"{prefix}.", f"{prefix}["))


def apply_snippet(
    db: Session,
    visible: VisibleSnippet,
    tree: dict[str, Any],
    values: Mapping[str, Any],
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    list_path: str = "nodes",
    index: int | None = None,
) -> SnippetOutcome:
    """Builds the tree a snippet gives when inserted into `tree`; stores nothing.

    Args:
        db: Active session (read only).
        visible: The snippet as the scope offers it (`visible_snippets`).
        tree: The draft layout tree (it is not changed).
        values: The parameter values by key.
        organization_id: The layout's organisation.
        project_id: The layout's own project, or `None` for an organisation layout.
        list_path: The list of blocks to insert into: `nodes`, or `nodes[2].children` / `.else_children`.
        index: Where in that list (0 is first); `None` for the end.

    Returns:
        The outcome: the new tree and what changed, or the reasons it was refused.
    """
    snippet = visible.snippet
    outcome = SnippetOutcome()
    if not isinstance(tree, dict) or tree.get("family") != snippet.family:
        actual = tree.get("family") if isinstance(tree, dict) else "different"
        outcome.errors.append(TreeError("", f'"{snippet.name}" is for a {snippet.family} layout; this one is a {actual} layout.'))
        return outcome
    resolved, outcome.errors = _resolve_values(db, visible, values, organization_id, project_id)
    result = copy.deepcopy(tree)
    try:
        target = block_list(result, list_path)
    except ValueError:
        outcome.errors.append(TreeError("target", "That is not a list of blocks in this layout."))
        return outcome
    at = len(target) if index is None else index
    if not 0 <= at <= len(target):
        outcome.errors.append(TreeError("target", f"The position must be from 0 to {len(target)}."))
    if outcome.errors:
        return outcome

    fragment: dict[str, Any] = {"nodes": copy.deepcopy(list(snippet.blocks)), **copy.deepcopy({k: list(v) for k, v in snippet.root.items()})}
    if snippet.layout_aware is not None:
        snippet.layout_aware(fragment, resolved, tree, _image_aspect(db, organization_id, project_id))
    for visible_parameter in visible.parameters:
        for path in visible_parameter.parameter.targets:
            _set_path(fragment, path, resolved[visible_parameter.parameter.key])

    baseline = validate_tree(tree, family=snippet.family)
    added_styles, refused = _merge_root(result, fragment, outcome)
    if refused:
        return outcome
    target[at:at] = fragment["nodes"]
    count = len(fragment["nodes"])
    outcome.changes.insert(0, f"Inserted {count} block{'s' if count != 1 else ''} at {list_path}[{at}].")

    analysis = validate_tree(result, family=snippet.family)
    found = list(analysis.errors)
    if not found:
        found += report_images.image_problems(db, organization_id, project_id, result)
    old = {(e.path, e.message) for e in baseline.errors}
    inserted = [f"{list_path}[{at + k}]" for k in range(count)] + [f"page_styles[{i}]" for i in added_styles]
    for error in found:
        within = any(_under(error.path, prefix) for prefix in inserted)
        if within or (_unshift(error.path, list_path, at, count), error.message) not in old:
            outcome.errors.append(error)
    if analysis.node_count > MAX_NODES >= baseline.node_count and not any("too many blocks" in e.message for e in outcome.errors):
        outcome.errors.append(TreeError(list_path, f"Inserting this would make the layout too big (the limit is {MAX_NODES} blocks)."))
    if outcome.errors:
        outcome.changes = []
        return outcome
    outcome.tree, outcome.inserted_at, outcome.count = result, f"{list_path}[{at}]", count
    outcome.problems_elsewhere = len(found)
    return outcome


__all__ = [
    "ParameterChoice", "SavedOrigin", "SnippetOutcome", "VisibleParameter", "VisibleSnippet", "apply_snippet", "block_list",
    "saved_report_snippet", "scope_record_types", "snippet_key", "visible_snippets",
]
