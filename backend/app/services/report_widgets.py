"""
Module: services.report_widgets

The widget catalogue: a widget is one component of a module report (`ReportDefinition`) that a layout embeds with a
`widget` block (one of its tables, its headline figures or its caveat notes).

Responsibilities:
- Name a widget `<module key>.<report slug>.<part>` from the registry; a part is a declared table
  (`ReportDefinition.parts`) or `figures` or `notes`.
- `list_widgets`, `find_widget`, `widgets_for_organization`, `widgets_for_project`, `widget_available`.
- `param_problems` and `typed_params`: check parameter values against the report's `ReportParamDefinition`s.

Design decisions:
- A widget is a component and the layout owns the words, so a component sits under any heading in any layout.
- Nothing is declared twice: title, parameters, module and sub-component gate come from the `ReportDefinition`.
- The key is qualified by the module because slugs are unique only within one, which keeps stored layouts unambiguous.
- Parameters are JSON literals of the declared type, never placeholders or expressions.
- Validation is by registry key; availability is decided per run for the project it runs in (an organisation layout runs
  in many projects).
- The module is light (registry only) so the layout validator can use it without importing the rendering stack.

Dependencies: `modules.registry`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.project import Project
from app.modules.registry import (
    ReportDefinition,
    ReportParamDefinition,
    get_all_reports,
    get_module,
    report_enabled_for_organization,
    report_enabled_for_project,
)

#: `<module key>.<slug>.<part>`: the module key and the part are lower-case words joined by `_`, the slug by `-`.
WIDGET_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9-]*\.[a-z][a-z0-9_]*$")
KIND_SECTION = "section"
KIND_FIGURES = "figures"
KIND_NOTES = "notes"
#: Longest text parameter an author may write.
MAX_PARAM_TEXT = 200


@dataclass(frozen=True)
class WidgetPart:
    """The component of a report a widget produces.

    Attributes:
        key: The `ReportSection.key` of a declared table, or `figures` / `notes`.
        title: Short name for the designer's list.
        description: Optional one line.
        kind: `section`, `figures` or `notes`.
    """

    key: str
    title: str
    description: str
    kind: str


BUILT_IN_PARTS: tuple[WidgetPart, ...] = (
    WidgetPart("figures", "Headline figures", "The report's headline figures as a Measure / Value table.", KIND_FIGURES),
    WidgetPart("notes", "Notes", "The caveats the report prints at the top (scope, model, reserved features).", KIND_NOTES),
)


@dataclass(frozen=True)
class WidgetInfo:
    """One embeddable component of a report.

    Attributes:
        key: `<module key>.<report slug>.<part>`, what a `widget` block names.
        module_key: The declaring module.
        module_name: The module's display name.
        definition: The report's declaration (title, parameters, collector, gates).
        part: The component of the report this widget produces.
    """

    key: str
    module_key: str
    module_name: str
    definition: ReportDefinition
    part: WidgetPart

    @property
    def report_key(self) -> str:
        """`<module key>.<report slug>`: the report all its widgets share (its result is collected once per run)."""
        return f"{self.module_key}.{self.definition.slug}"

    @property
    def title(self) -> str:
        """The component's display title."""
        return self.part.title

    @property
    def report_title(self) -> str:
        """The report's display title."""
        return self.definition.title

    @property
    def params(self) -> tuple[ReportParamDefinition, ...]:
        """The parameters a block may set (the report's)."""
        return self.definition.params


def widget_key(module_key: str, definition: ReportDefinition, part_key: str) -> str:
    """The widget key of one component of a report (`<module key>.<slug>.<part>`)."""
    return f"{module_key}.{definition.slug}.{part_key}"


def list_widgets() -> list[WidgetInfo]:
    """Every component of every valid report in the registry, in registry then declaration order.

    A report's declared tables come first, then `figures` and `notes`.
    """
    out: list[WidgetInfo] = []
    for module_key, definition in get_all_reports():
        module = get_module(module_key)
        name = module.name if module else module_key
        parts = [WidgetPart(p.key, p.title, p.description, KIND_SECTION) for p in definition.parts] + list(BUILT_IN_PARTS)
        out.extend(WidgetInfo(widget_key(module_key, definition, part.key), module_key, name, definition, part) for part in parts)
    return out


def find_widget(key: str) -> WidgetInfo | None:
    """The widget called `key`, or `None` (also for a key that is not shaped like one)."""
    if not isinstance(key, str) or not WIDGET_KEY_RE.match(key):
        return None
    return next((w for w in list_widgets() if w.key == key), None)


def widget_available(db: Session, project: Project, widget: WidgetInfo) -> bool:
    """Whether `widget`'s module (and sub-component, if it declares one) is enabled for `project`.

    This is the gate the report's own project route applies, so a widget never runs where the standalone
    report would answer 404.
    """
    return report_enabled_for_project(db, project.id, widget.module_key, widget.definition)


def widgets_for_project(db: Session, project: Project) -> list[WidgetInfo]:
    """The widgets whose module is enabled for `project`: what its layout authors are offered."""
    return [w for w in list_widgets() if widget_available(db, project, w)]


def widgets_for_organization(db: Session, organization_id: uuid.UUID) -> list[WidgetInfo]:
    """The widgets whose module the organisation is entitled to and has enabled: what its layout authors are offered.

    A sub-component the organisation has switched off is left out too. A project may still have the module
    off, which each run checks (`widget_available`).
    """
    out = []
    for widget in list_widgets():
        if report_enabled_for_organization(db, organization_id, widget.module_key, widget.definition):
            out.append(widget)
    return out


# --- parameters -----------------------------------------------------------------------------------------------


def param_value_problem(param: ReportParamDefinition, value: Any) -> str | None:
    """Why `value` is not a literal of the parameter's declared type (`None` when it is)."""
    kind = param.type
    if kind == "string":
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_PARAM_TEXT:
            return f"Must be text of 1 to {MAX_PARAM_TEXT} characters."
    elif kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return "Must be a whole number."
        if param.minimum is not None and value < param.minimum:
            return f"Must be at least {param.minimum}."
        if param.maximum is not None and value > param.maximum:
            return f"Must be at most {param.maximum}."
    elif kind == "boolean":
        if not isinstance(value, bool):
            return "Must be true or false."
    elif kind == "date":
        try:
            ok = isinstance(value, str) and len(value) == 10 and date.fromisoformat(value) is not None
        except ValueError:
            ok = False
        if not ok:
            return "Must be a date as YYYY-MM-DD."
    elif kind == "uuid":
        try:
            ok = isinstance(value, str) and str(uuid.UUID(value)) == value
        except ValueError:
            ok = False
        if not ok:
            return "Must be an id such as 3f2b8c1e-9d4a-4c55-8f0e-2a6d7b1c9e40."
    if param.choices is not None and value not in param.choices:
        return f"Must be one of: {', '.join(str(c) for c in param.choices)}."
    return None


def param_problems(widget: WidgetInfo, params: Any) -> list[tuple[str, str]]:
    """Everything wrong with a block's `params`.

    Args:
        widget: The widget the block names.
        params: The block's `params` value (an object of `{parameter: literal}`).

    Returns:
        `(parameter name, message)` pairs; the name is empty when the problem is with `params` itself.
    """
    if not isinstance(params, dict):
        return [("", "Must be an object of parameter values.")]
    if not params:
        return [("", "Leave params out when no parameter is set.")]
    declared = {p.name: p for p in widget.params}
    problems: list[tuple[str, str]] = []
    for name, value in params.items():
        param = declared.get(name)
        if param is None:
            known = ", ".join(declared) if declared else "none"
            problems.append((str(name), f"This report has no parameter {name!r}. Its parameters: {known}."))
            continue
        problem = param_value_problem(param, value)
        if problem:
            problems.append((name, problem))
    return problems


def typed_params(widget: WidgetInfo, params: dict[str, Any] | None) -> dict[str, Any]:
    """The values a collector receives: every declared parameter, with the declared default when unset.

    Args:
        widget: The widget being run.
        params: A validated block's `params` (`None` when the block sets none).

    Returns:
        `{name: value}` for each declared parameter; dates are `date`, ids `UUID`, the rest as written, as
        the report's own route would pass them.
    """
    given = params or {}
    out: dict[str, Any] = {}
    for param in widget.params:
        value = given.get(param.name)
        if value is None:
            value = param.default
        elif param.type == "date":
            value = date.fromisoformat(value)
        elif param.type == "uuid":
            value = uuid.UUID(value)
        out[param.name] = value
    return out


__all__ = [
    "BUILT_IN_PARTS", "KIND_FIGURES", "KIND_NOTES", "KIND_SECTION", "MAX_PARAM_TEXT", "WIDGET_KEY_RE", "WidgetInfo",
    "WidgetPart", "find_widget", "list_widgets", "param_problems", "param_value_problem", "typed_params", "widget_available", "widget_key",
    "widgets_for_organization", "widgets_for_project",
]
