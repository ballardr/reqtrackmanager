"""
Module: services.report_variables

Run-time variables of a custom report layout: typed values the person supplies when running or downloading
a report, which narrow what it shows without a copy of the layout per scope.

Responsibilities:
- Define the vocabulary a layout's `variables` list is written in (`VARIABLE_TYPES`, the caps) and how a
  reference (`{"var": "<name>"}`) is told from a literal (`is_reference`).
- Say which field kinds and widget parameter types a variable of each type fits (`FIELD_KINDS`,
  `PARAM_TYPES`), so the tree validator can reject a mismatch when the layout is saved.
- Turn supplied values into checked, typed ones (`resolve_values`): defaults, the `today` default of a date,
  shape (one value or a list), type and the explicit options of an enum.
- Substitute the values into a copy of the tree (`bind_variables`) so the evaluator only ever sees literals,
  and print them for `{{var.name}}` text (`variable_text`).
- Offer a variable's options from its source field's value domain (`variable_options`) and flag a value that
  is no longer one of them (`stale_value_warnings`).

Design decisions:
- **A value is a typed literal, never markup and never an expression.** Substitution replaces a reference
  with the checked literal before evaluation; `{{var.name}}` is filled by the evaluator's single-pass
  placeholder fill like any record value, so a value that contains `{{record.title}}` or `# heading` stays text.
- **Variables narrow, they do not authorise.** Nothing here widens what the caller can read; the traversal
  layer's resolver still decides every record.
- **Options are advice, except an enum's own list.** A source field's domain only warns about a value outside
  it (a field with no domain takes free input), because the list can change between saving a set of values
  and running it; an enum variable's explicit `options` are the layout's own contract and are enforced.
- Values are configuration: they are stored with the run and are never written to a log line.

Dependencies: `services.report_fields` (value domains).
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.services.report_fields import UnknownReportFieldError, field_domain

VARIABLE_TYPES = ("text", "number", "date", "bool", "enum")
MAX_VARIABLES = 20
MAX_OPTIONS = 100
MAX_VALUE_CHARS = 200
#: Most values a list variable may hold (the same cap as an `in` list, so a bound condition stays valid).
MAX_LIST_VALUES = 20
#: The default of a date variable that means the person's own day when the report runs.
TODAY = "today"
#: The alias a `{{var.name}}` placeholder uses; an enclosing block may not take it.
PLACEHOLDER_FAMILY = "var"

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

#: The kinds of record field a variable of each type can be compared with in a condition.
FIELD_KINDS: dict[str, tuple[str, ...]] = {
    "text": ("text", "principal", "enum"),
    "enum": ("enum", "text"),
    "number": ("number",),
    "date": ("date",),
    "bool": ("bool",),
}
#: The widget parameter types a variable of each type can supply (`ReportParamDefinition.type`).
PARAM_TYPES: dict[str, tuple[str, ...]] = {
    "text": ("string",),
    "enum": ("string",),
    "number": ("integer",),
    "date": ("date",),
    "bool": ("boolean",),
}


class VariableValueError(ValueError):
    """Supplied values are not acceptable; `problems` lists `(variable name, message)` (name empty when general)."""

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        self.problems = problems
        super().__init__("; ".join(f"{name}: {message}" if name else message for name, message in problems[:5]))


def is_reference(value: Any) -> bool:
    """Whether `value` is a variable reference, `{"var": "<name>"}` (and nothing else)."""
    return isinstance(value, dict) and set(value) == {"var"} and isinstance(value["var"], str)


def value_problem(vtype: str, value: Any) -> str | None:
    """Why `value` is not a single value of variable type `vtype` (`None` when it is)."""
    if vtype in ("text", "enum"):
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_VALUE_CHARS:
            return f"Must be text of 1 to {MAX_VALUE_CHARS} characters."
    elif vtype == "number":
        if not isinstance(value, int | float) or isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
            return "Must be a number."
    elif vtype == "bool":
        if not isinstance(value, bool):
            return "Must be true or false."
    elif vtype == "date":
        try:
            ok = isinstance(value, str) and len(value) == 10 and date.fromisoformat(value) is not None
        except ValueError:
            ok = False
        if not ok:
            return "Must be a date as YYYY-MM-DD."
    else:
        return "Unsupported variable type."
    return None


def _normal(vtype: str, value: Any) -> Any:
    """A whole-valued float as an int, so a number variable can feed a whole-number parameter."""
    return int(value) if vtype == "number" and isinstance(value, float) and value.is_integer() else value


def _shape_problem(declaration: Mapping[str, Any], value: Any, today: date) -> tuple[Any, str | None]:
    """`(checked value, problem)` for one variable's value, with `today` standing in for the `today` default."""
    vtype, multiple = declaration["type"], bool(declaration.get("multiple"))
    items: list[Any]
    if multiple:
        if not isinstance(value, list) or not 0 < len(value) <= MAX_LIST_VALUES:
            return None, f"Choose 1 to {MAX_LIST_VALUES} values."
        items = value
    else:
        if isinstance(value, list):
            return None, "Takes one value, not a list."
        items = [value]
    checked: list[Any] = []
    for item in items:
        if vtype == "date" and item == TODAY:
            item = today.isoformat()
        problem = value_problem(vtype, item)
        if problem:
            return None, problem
        item = _normal(vtype, item)
        options = declaration.get("options")
        if vtype == "enum" and options is not None and item not in options:
            return None, f"Must be one of: {', '.join(options)}."
        if item not in checked:
            checked.append(item)
    return (checked if multiple else checked[0]), None


def resolve_values(
    declarations: Sequence[Mapping[str, Any]] | None, supplied: Mapping[str, Any] | None, *, today: date,
) -> dict[str, Any]:
    """The value of every declared variable for a run: what was supplied, else the default.

    Args:
        declarations: The layout's `variables` (already validated), or `None`.
        supplied: `{name: value}` from the person (a list for a list variable); `None` or empty to use defaults.
        today: The person's own day, for a date variable whose default is `today`.

    Returns:
        `{name: checked value}`; a list variable's value is a list without duplicates, a number is an int when whole.

    Raises:
        VariableValueError: A name is not declared, a variable has neither a value nor a default, or a value has
            the wrong shape or type or is not one of an enum's options. Every problem is listed.
    """
    declared = {d["name"]: d for d in declarations or []}
    given = dict(supplied or {})
    problems: list[tuple[str, str]] = [(str(n), "This layout has no such variable.") for n in given if n not in declared]
    out: dict[str, Any] = {}
    for name, declaration in declared.items():
        if name in given:
            value = given[name]
        elif "default" in declaration:
            value = declaration["default"]
        else:
            problems.append((name, "Needs a value."))
            continue
        checked, problem = _shape_problem(declaration, value, today)
        if problem:
            problems.append((name, problem))
        else:
            out[name] = checked
    if problems:
        raise VariableValueError(problems)
    return out


def bind_variables(tree: dict[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `tree` with every `{"var": name}` reference replaced by that variable's value.

    The declarations stay in the copy, so `{{var.name}}` still validates. A value is copied, never shared.

    Args:
        tree: A validated tree.
        values: The resolved values (`resolve_values`).
    """

    def walk(node: Any) -> Any:
        if is_reference(node):
            value = values[node["var"]]
            return list(value) if isinstance(value, list) else value
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return {key: item if key == "variables" else walk(item) for key, item in tree.items()}


def variable_text(declarations: Sequence[Mapping[str, Any]] | None, values: Mapping[str, Any]) -> dict[str, str]:
    """`{name: printed value}` for `{{var.name}}`: a list joined with `, `, a flag as Yes/No, a date as ISO text."""

    def printed(value: Any) -> str:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)

    out: dict[str, str] = {}
    for declaration in declarations or []:
        value = values[declaration["name"]]
        out[declaration["name"]] = ", ".join(printed(v) for v in value) if isinstance(value, list) else printed(value)
    return out


def variable_options(
    db: Session, declaration: Mapping[str, Any], project_ids: Sequence[uuid.UUID],
) -> list[str] | None:
    """The values a variable offers: its explicit `options`, else its source field's value domain.

    Args:
        db: Active session (read only).
        declaration: One entry of the layout's `variables`.
        project_ids: The projects the report is for (a project's own and its ancestors' definitions are offered).

    Returns:
        The options in display order, or `None` when the variable takes free input (no source, or a source
        field with no closed list, or a source that no longer exists).
    """
    if declaration.get("options") is not None:
        return list(declaration["options"])
    source = declaration.get("source")
    if not source:
        return None
    try:
        return field_domain(db, source["record_type"], source["field"], project_ids)
    except UnknownReportFieldError:
        return None


def describe_variables(
    db: Session, declarations: Sequence[Mapping[str, Any]] | None, project_ids: Sequence[uuid.UUID], *, today: date,
) -> list[dict[str, Any]]:
    """The run form of a layout: each variable with its label, default and current options.

    Args:
        db: Active session (read only).
        declarations: The layout's `variables`, or `None`.
        project_ids: The projects the report is for.
        today: The person's own day, which a date's `today` default becomes.

    Returns:
        One dict per variable: `name`, `type`, `label` (the name when none is set), `multiple`, `default` (`None`
        when the layout sets none), `options` (`None` for free input) and `source`.
    """
    out: list[dict[str, Any]] = []
    for declaration in declarations or []:
        default = declaration.get("default")
        if isinstance(default, list):
            default = [today.isoformat() if v == TODAY else v for v in default]
        elif default == TODAY:
            default = today.isoformat()
        out.append({
            "name": declaration["name"], "type": declaration["type"], "label": declaration.get("label") or declaration["name"],
            "multiple": bool(declaration.get("multiple")), "default": default,
            "options": variable_options(db, declaration, project_ids), "source": declaration.get("source"),
        })
    return out


def stale_value_warnings(
    db: Session, declarations: Sequence[Mapping[str, Any]] | None, values: Mapping[str, Any],
    project_ids: Sequence[uuid.UUID],
) -> list[str]:
    """One warning per variable with a value outside its source field's domain (names the variable, not the value).

    A value outside a closed list matches nothing in a condition, so the report would be quietly empty; this says why.
    """
    warnings: list[str] = []
    for declaration in declarations or []:
        if declaration.get("source") is None:
            continue
        options = variable_options(db, declaration, project_ids)
        if options is None:
            continue
        known = {o.casefold() for o in options}
        chosen = values[declaration["name"]]
        chosen = chosen if isinstance(chosen, list) else [chosen]
        if any(str(v).casefold() not in known for v in chosen):
            label = declaration.get("label") or declaration["name"]
            warnings.append(f'A value chosen for "{label}" is not one of its current options, so it may match nothing.')
    return warnings


__all__ = [
    "FIELD_KINDS", "MAX_LIST_VALUES", "MAX_OPTIONS", "MAX_VARIABLES", "NAME_RE", "PARAM_TYPES", "PLACEHOLDER_FAMILY",
    "TODAY", "VARIABLE_TYPES", "VariableValueError", "bind_variables", "describe_variables", "is_reference", "resolve_values",
    "stale_value_warnings", "value_problem", "variable_options", "variable_text",
]
