"""
Module: services.report_widgets

The widget catalogue: a widget is one component of a module report (`ReportDefinition`) that a custom report
layout embeds with a `widget` block: one of the report's tables, its headline figures, or its caveat notes.
This module is the one place that says which widgets exist, what they are called, what they accept and
whether a project or organisation can use them.

Responsibilities:
- Name a widget: `<module key>.<report slug>.<part>` (`risk_management.risk-register.register`), built from the
  registry. A part is a table the report declares (`ReportDefinition.parts`) or one of the two every report
  offers, `figures` and `notes`.
- List widgets (`list_widgets`, `find_widget`), and narrow the list to the ones an organisation or project
  can use (`widgets_for_organization`, `widgets_for_project`, `widget_available`).
- Check a block's parameter values against the report's `ReportParamDefinition`s (`param_problems`) and
  turn them into the typed values a collector expects (`typed_params`).

Design decisions:
- **A widget is a component; the layout owns the words.** A widget produces a table (or the figures, or the
  caveat notes) and never a heading or a sentence of its own, so the same component can sit under any
  heading and explanation in any layout. The report's tables are declared once, on the report.
- **Nothing else is declared twice.** Title, parameters, module and sub-component gate come from the
  `ReportDefinition`; the parameters belong to the report, so every part of a report accepts the same ones.
- **The key is qualified by the module.** Slugs are unique only within a module, so a bare slug could
  become ambiguous when another module adds one and would change what a stored layout means. The module
  key, the slug and the part key are all stable.
- **Literal parameters only.** A value is a JSON literal of the declared type; there is no placeholder or
  expression in a parameter, so a layout cannot make a report read something its author did not write.
- **Validation is by registry key; availability is decided at run time.** A layout may name a widget the
  author's project has switched off (an organisation layout runs in many projects); each run checks the
  module for the project it runs in.
- This module is deliberately light (registry only, no report framework) so the layout validator can use
  it without importing the rendering stack.

Dependencies: `modules.registry` (reports, enablement).
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
    is_module_enabled,
    is_module_enabled_for_project,
    is_module_subcomponent_enabled,
    is_org_module_subcomponent_enabled,
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
    if widget.definition.subcomponent:
        return is_module_subcomponent_enabled(db, project.id, widget.module_key, widget.definition.subcomponent)
    return is_module_enabled_for_project(db, project.id, widget.module_key)


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
        if not is_module_enabled(db, organization_id, widget.module_key):
            continue
        sub = widget.definition.subcomponent
        if sub and not is_org_module_subcomponent_enabled(db, organization_id, widget.module_key, sub):
            continue
        out.append(widget)
    return out


# --- parameters -----------------------------------------------------------------------------------------------


def _value_problem(param: ReportParamDefinition, value: Any) -> str | None:
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
        problem = _value_problem(param, value)
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
    "WidgetPart", "find_widget", "list_widgets", "param_problems", "typed_params", "widget_available", "widget_key",
    "widgets_for_organization", "widgets_for_project",
]
