"""
Module: services.overview_widgets

The project overview's widget layout: an ordered list of widget instances a project manager arranges, with an
organisation default and a built-in list.

Responsibilities:
- Define the core widget types and merge those a module contributes (`ModuleDefinition.overview_widgets`).
- Validate a layout (its scope, then each widget's type, size, scope override, per-type configuration, metric
  references and the 24-widget cap) and return it cleaned, so only a known shape is ever stored.
- Resolve the layout a project shows: its own, else the nearest ancestor's, else the organisation's, else the
  built-in list, and say which one applied.
- Set or clear the project's or the organisation's own layout (audited with counts and types, never titles), and
  carry the layout in the project and organisation bundles and the template clone.

Design decisions:
- A layout is a JSON object `{scope, widgets}` on the project and on the organisation (`NULL` inherits), not a table:
  it is always read and written whole, and an instance has no identity outside its list. This is the shape
  `nav_label_overrides` uses. `scope` is the overview's project scope (this project, with parents, with children or
  both); a widget may override it. A stored bare list (an earlier shape) is read as a layout with scope `this`.
- A widget has a width in columns of a 12-column grid and a height in rows (a minimum: a row grows with its
  content). The grid is a flow, not absolute positions, so it collapses for a narrow screen without a second layout.
- The nested-project rule is the `resolve_effective_action_types` one: own rows if any, else the nearest
  ancestor's, else the organisation's, else the built-in list. A layout is state, so an empty list is a layout
  (an overview with every widget removed) and does not fall through.
- Widget configuration names metrics by catalogue key and components by prefix (`services.overview_metrics`), so a
  layout needs no id remapping in a bundle, a template clone or a child project that inherits it.
- A module widget's configuration is opaque to the core (a bounded JSON object); only its type key is checked.
- A text widget holds markdown the viewers see; it is plain text here and rendered without raw HTML or images.
- No module is named here: module widget types come from the registry.

External dependencies: `modules.registry`, `services.overview_metrics`, `services.project_hierarchy`,
`services.audit`.
"""

from __future__ import annotations

import copy
import json
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.modules.registry import get_overview_widget_types, is_module_enabled, is_module_enabled_for_project
from app.services.audit import log_event
from app.services.bundle_common import BundleImportWarnings
from app.services.overview_metrics import all_metrics, validate_reference
from app.services.project_hierarchy import get_project_chain_ids

#: Most widgets one layout may hold.
MAX_WIDGETS = 24

#: A widget's width in columns of the 12-column grid, and its height in rows (the row unit is set by the page).
MAX_COLUMNS = 12
MAX_ROWS = 12

#: The project scopes a layout and a widget may name.
SCOPES = ("this", "parents", "children", "both")

#: Longest widget title and largest module widget configuration (serialised bytes).
MAX_TITLE_LENGTH = 80
MAX_MODULE_CONFIG_BYTES = 4096

#: Longest text a text widget may hold.
MAX_TEXT_LENGTH = 4000

#: Most activity entries an activity widget may show.
MAX_ACTIVITY_LIMIT = 25
DEFAULT_ACTIVITY_LIMIT = 8

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

#: Section of `project.json` and of the organisation bundle that carries the layout.
BUNDLE_KEY = "overview_widgets"


@dataclass(frozen=True)
class WidgetTypeInfo:
    """A widget type as the editor lists it.

    Attributes:
        key: Type key (`gauge`, or `<module_key>:<key>` for a module's).
        label: Name in the "Add widget" list.
        description: One sentence on what it shows.
        module_key: Owning module, `None` for a core type.
        width: Columns (of 12) a new widget starts with.
        height: Rows a new widget starts with.
        in_default_layout: Whether the built-in overview includes one while the module is enabled.
    """

    key: str
    label: str
    description: str
    module_key: str | None = None
    width: int = 4
    height: int = 4
    in_default_layout: bool = False


CORE_WIDGET_TYPES: tuple[WidgetTypeInfo, ...] = (
    WidgetTypeInfo("metric_tile", "Metric tile", "One figure from the metric catalogue, linked to the list it summarises."),
    WidgetTypeInfo("gauge", "Gauge", "One figure on a dial between a minimum and a maximum, with optional warning and critical levels."),
    WidgetTypeInfo("status_chart", "Chart", "A breakdown from the metric catalogue as a pie or a bar chart."),
    WidgetTypeInfo("stage_progress", "Stage progress", "How complete each project stage is."),
    WidgetTypeInfo("record_totals", "Record totals", "How many records of each type the project holds."),
    WidgetTypeInfo("activity", "Activity", "The most recent changes in the project."),
    WidgetTypeInfo("text", "Text", "Notes for the people who open the overview, written in markdown."),
)

_CORE_TYPE_KEYS = frozenset(info.key for info in CORE_WIDGET_TYPES)
_NO_CONFIG_TYPES = frozenset({"stage_progress", "record_totals"})

#: Core types that always read this project only, so a scope override means nothing for them.
_UNSCOPED_TYPES = frozenset({"stage_progress", "activity", "text"})


def _refuse(message: str) -> HTTPException:
    """A 422 with `message`."""
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def widget_types_for_project(db: Session, project: Project) -> list[WidgetTypeInfo]:
    """The widget types the project can add: the core types and those of each module enabled for the project."""
    found = list(CORE_WIDGET_TYPES)
    for key, (module_key, widget) in get_overview_widget_types().items():
        if is_module_enabled_for_project(db, project.id, module_key):
            found.append(WidgetTypeInfo(key, widget.label, widget.description, module_key, widget.width, widget.height, widget.in_default_layout))
    return found


def widget_types_for_organization(db: Session, organization_id: uuid.UUID) -> list[WidgetTypeInfo]:
    """The widget types an organisation default can add: the core types and those of each module the organisation enables."""
    found = list(CORE_WIDGET_TYPES)
    for key, (module_key, widget) in get_overview_widget_types().items():
        if is_module_enabled(db, organization_id, module_key):
            found.append(WidgetTypeInfo(key, widget.label, widget.description, module_key, widget.width, widget.height, widget.in_default_layout))
    return found


# --- validation --------------------------------------------------------------------------------------


def _number(raw: Any, name: str) -> float:
    """`raw` as a finite number.

    Raises:
        HTTPException: 422 when it is not one (a boolean is not).
    """
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        raise _refuse(f"The gauge {name} must be a number.")
    return float(raw)


def _metric_config(raw: dict[str, Any], *, need: str) -> dict[str, Any]:
    """The `metric` and `params` part of a configuration, checked against the catalogue.

    Args:
        raw: The widget's configuration.
        need: `scalar` or `breakdown`: what the widget draws, so a metric without it is refused.

    Raises:
        HTTPException: 422 for an unknown metric, invalid params, or a metric that cannot supply `need`.
    """
    metric_key, params = validate_reference(raw.get("metric"), raw.get("params"))
    metric = all_metrics()[metric_key]
    if (need == "scalar" and not metric.scalar) or (need == "breakdown" and not metric.breakdown):
        raise _refuse("This metric cannot be shown by this kind of widget.")
    cleaned: dict[str, Any] = {"metric": metric_key}
    if params:
        cleaned["params"] = params
    return cleaned


def _clean_config(widget_type: str, raw: Any) -> dict[str, Any]:
    """A widget's configuration checked for its type and returned cleaned (unknown keys refused).

    Raises:
        HTTPException: 422 for a configuration the type does not accept.
    """
    if not isinstance(raw, dict):
        raise _refuse("The widget settings must be a set of named values.")
    if widget_type in _NO_CONFIG_TYPES:
        if raw:
            raise _refuse("This widget has no settings.")
        return {}
    if widget_type == "activity":
        unknown = sorted(set(raw) - {"limit"})
        limit = raw.get("limit", DEFAULT_ACTIVITY_LIMIT)
        if unknown or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_ACTIVITY_LIMIT:
            raise _refuse(f"The activity widget shows between 1 and {MAX_ACTIVITY_LIMIT} entries.")
        return {"limit": limit}
    if widget_type == "text":
        text = raw.get("markdown", "")
        if set(raw) - {"markdown"} or not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
            raise _refuse(f"A text widget holds at most {MAX_TEXT_LENGTH} characters of text.")
        if any(not (ch.isprintable() or ch in "\n\t") for ch in text):
            raise _refuse("A text widget must be plain text.")
        return {"markdown": text}
    if widget_type == "metric_tile":
        unknown = sorted(set(raw) - {"metric", "params"})
        if unknown:
            raise _refuse(f"The widget does not accept: {', '.join(unknown)}.")
        return _metric_config(raw, need="scalar")
    if widget_type == "status_chart":
        unknown = sorted(set(raw) - {"metric", "params", "chart"})
        chart = raw.get("chart", "pie")
        if unknown or chart not in ("pie", "bar"):
            raise _refuse("A chart is a pie or a bar chart and has no other settings.")
        return {**_metric_config(raw, need="breakdown"), "chart": chart}
    if widget_type == "gauge":
        allowed = {"metric", "params", "minimum", "maximum", "warning", "critical", "direction"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise _refuse(f"The widget does not accept: {', '.join(unknown)}.")
        cleaned = _metric_config(raw, need="scalar")
        minimum = _number(raw["minimum"], "minimum") if "minimum" in raw else 0.0
        maximum = _number(raw["maximum"], "maximum") if "maximum" in raw else 100.0
        if not minimum < maximum:
            raise _refuse("The gauge minimum must be below its maximum.")
        cleaned.update(minimum=minimum, maximum=maximum)
        for level in ("warning", "critical"):
            if raw.get(level) is not None:
                cleaned[level] = _number(raw[level], level)
        direction = raw.get("direction", "above")
        if direction not in ("above", "below"):
            raise _refuse("The gauge direction must be 'above' or 'below'.")
        cleaned["direction"] = direction
        return cleaned
    if len(json.dumps(raw, default=str)) > MAX_MODULE_CONFIG_BYTES:
        raise _refuse("The widget settings are too large.")
    return dict(raw)


def _scope(raw: Any, *, allow_none: bool) -> str | None:
    """A scope name, or `None` where allowed (a widget that follows the overview).

    Raises:
        HTTPException: 422 for anything else.
    """
    if raw is None and allow_none:
        return None
    if raw not in SCOPES:
        raise _refuse("The scope must be this project, with parents, with children, or both.")
    return str(raw)


def _size(raw: Any, name: str, limit: int, default: int) -> int:
    """A width or height: a whole number from 1 to `limit`.

    Raises:
        HTTPException: 422 for anything else (a boolean is not a number here).
    """
    value = default if raw is None else raw
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limit:
        raise _refuse(f"A widget's {name} is a whole number from 1 to {limit}.")
    return value


def validate_widgets(raw: Any) -> list[dict[str, Any]]:
    """Checks a list of widgets and returns it cleaned, in order.

    Args:
        raw: The widgets as sent or stored: `{id, type, title, width, height, scope, visible, config}` objects.

    Returns:
        The cleaned list (title trimmed, defaults filled, configuration normalised).

    Raises:
        HTTPException: 422 for more than `MAX_WIDGETS` widgets, a repeated or malformed id, an unknown type, a size
            out of range, a scope override on a widget that has none, a title that is too long or not plain text,
            or a configuration the type refuses.
    """
    if not isinstance(raw, list):
        raise _refuse("The overview layout must be a list of widgets.")
    if len(raw) > MAX_WIDGETS:
        raise _refuse(f"An overview may hold at most {MAX_WIDGETS} widgets.")
    module_types = get_overview_widget_types()
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise _refuse("Each widget must be a set of named values.")
        widget_id = item.get("id")
        if not isinstance(widget_id, str) or not _ID_PATTERN.match(widget_id) or widget_id in seen:
            raise _refuse("Each widget needs its own id of letters, digits, hyphens and underscores.")
        seen.add(widget_id)
        widget_type = item.get("type")
        if not isinstance(widget_type, str) or (widget_type not in _CORE_TYPE_KEYS and widget_type not in module_types):
            raise _refuse("Choose a widget type from the list.")
        scope = _scope(item.get("scope"), allow_none=True)
        if scope is not None and widget_type in _UNSCOPED_TYPES:
            raise _refuse("This widget always shows this project only.")
        title = item.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise _refuse("A widget title must be text.")
            title = " ".join(title.split())
            if len(title) > MAX_TITLE_LENGTH or any(not ch.isprintable() for ch in title):
                raise _refuse(f"A widget title may have at most {MAX_TITLE_LENGTH} plain characters.")
        visible = item.get("visible", True)
        if not isinstance(visible, bool):
            raise _refuse("A widget is shown or hidden.")
        cleaned.append({
            "id": widget_id, "type": widget_type, "title": title or None,
            "width": _size(item.get("width"), "width", MAX_COLUMNS, 3), "height": _size(item.get("height"), "height", MAX_ROWS, 2),
            "scope": scope, "visible": visible, "config": _clean_config(widget_type, item.get("config", {})),
        })
    return cleaned


def validate_layout(raw: Any) -> dict[str, Any]:
    """Checks a layout and returns it cleaned.

    Args:
        raw: `{scope, widgets}` as sent or stored. A bare list of widgets (the earlier stored shape) is accepted as
            a layout with scope `this`.

    Raises:
        HTTPException: 422 for a scope that is not offered or any fault `validate_widgets` names.
    """
    if isinstance(raw, list):
        raw = {"scope": "this", "widgets": raw}
    if not isinstance(raw, dict) or set(raw) - {"scope", "widgets"}:
        raise _refuse("The overview layout is a scope and a list of widgets.")
    return {"scope": _scope(raw.get("scope", "this"), allow_none=False), "widgets": validate_widgets(raw.get("widgets", []))}


# --- built-in layout and resolution ------------------------------------------------------------------


def _widget(widget_id: str, widget_type: str, width: int, height: int, config: dict[str, Any]) -> dict[str, Any]:
    """A built-in widget."""
    return {
        "id": widget_id, "type": widget_type, "title": None, "width": width, "height": height, "scope": None, "visible": True,
        "config": config,
    }


def default_layout(module_widgets: list[WidgetTypeInfo] | None = None) -> dict[str, Any]:
    """The built-in layout: the key figures in one row, then the widgets the enabled modules ask to be in it, the charts and
    the activity feed.

    Args:
        module_widgets: The widget types the project (or organisation) can add; those a module marked `in_default_layout`
            are placed after the key tiles, in registry order. None means no module contributes.
    """
    contributed = [
        _widget(info.key.replace(":", "-"), info.key, info.width, info.height, {})
        for info in module_widgets or [] if info.module_key is not None and info.in_default_layout
    ]
    return {"scope": "this", "widgets": [
        _widget("percent-complete", "metric_tile", 3, 2, {"metric": "requirement_completed_percent"}),
        _widget("file-count", "metric_tile", 3, 2, {"metric": "file_count"}),
        _widget("cr-proposed", "metric_tile", 2, 2, {"metric": "change_requests_proposed"}),
        _widget("cr-approved", "metric_tile", 2, 2, {"metric": "change_requests_approved"}),
        _widget("cr-rejected", "metric_tile", 2, 2, {"metric": "change_requests_rejected"}),
        *contributed,
        _widget("record-totals", "record_totals", 3, 6, {}),
        _widget("requirements-by-status", "status_chart", 3, 6, {"metric": "requirements_by_status", "chart": "pie"}),
        _widget("change-requests", "status_chart", 3, 6, {"metric": "change_requests_by_outcome", "chart": "pie"}),
        _widget("stage-progress", "stage_progress", 3, 6, {}),
        _widget("activity", "activity", 12, 6, {"limit": DEFAULT_ACTIVITY_LIMIT}),
    ]}


@dataclass(frozen=True)
class ResolvedLayout:
    """The layout that applies and where it comes from.

    Attributes:
        layout: The cleaned layout, `{scope, widgets}`.
        source: `own`, `ancestor`, `organisation` or `default` (the built-in layout).
    """

    layout: dict[str, Any]
    source: str


def stored_layout(raw: Any) -> dict[str, Any]:
    """A stored layout as the current shape: a bare list (the earlier shape, widths of 1 to 4 on a four-column grid) becomes
    a layout with scope `this` and each width scaled to the 12-column grid."""
    if isinstance(raw, list):
        return {"scope": "this", "widgets": [
            {"height": 2, "scope": None, **w, "width": w["width"] * 3 if w.get("width", 1) <= 4 else w["width"]} for w in copy.deepcopy(raw)
        ]}
    return copy.deepcopy(raw)


def inherited_layout(db: Session, project: Project) -> ResolvedLayout:
    """The layout the project would show without its own: the nearest ancestor's, else the organisation's, else built-in."""
    for ancestor_id in get_project_chain_ids(db, project.id)[1:]:
        layout = db.scalar(select(Project.overview_widgets).where(Project.id == ancestor_id))
        if layout is not None:
            return ResolvedLayout(stored_layout(layout), "ancestor")
    organization = db.get(Organization, project.organization_id)
    if organization is not None and organization.overview_widgets is not None:
        return ResolvedLayout(stored_layout(organization.overview_widgets), "organisation")
    return ResolvedLayout(default_layout(widget_types_for_project(db, project)), "default")


def resolve_layout(db: Session, project: Project) -> ResolvedLayout:
    """The layout the project's overview shows: its own, else `inherited_layout`."""
    if project.overview_widgets is not None:
        return ResolvedLayout(stored_layout(project.overview_widgets), "own")
    return inherited_layout(db, project)


def _audit_detail(layout: dict[str, Any] | None) -> dict[str, Any]:
    """Audit detail: counts, types and scope only, never a title, a filter value or text."""
    if layout is None:
        return {"count": 0, "restored": True}
    widgets = layout["widgets"]
    return {"count": len(widgets), "types": sorted({str(w["type"]) for w in widgets}), "scope": layout["scope"]}


def set_project_layout(db: Session, project: Project, layout: dict[str, Any] | None, actor_id: uuid.UUID) -> None:
    """Sets the project's own layout, or clears it (`None`: follow the ancestor, organisation or built-in layout); audited, not committed.

    Raises:
        HTTPException: 422 when `validate_layout` refuses the layout.
    """
    project.overview_widgets = None if layout is None else validate_layout(layout)
    log_event(
        db, entity_type="overview_layout", entity_id=project.id, action="updated", actor_id=actor_id,
        organization_id=project.organization_id, project_id=project.id, detail=_audit_detail(project.overview_widgets),
    )


def set_organization_layout(db: Session, organization: Organization, layout: dict[str, Any] | None, actor_id: uuid.UUID) -> None:
    """Sets the organisation's default layout, or clears it; audited, not committed.

    Raises:
        HTTPException: 422 when `validate_layout` refuses the layout.
    """
    organization.overview_widgets = None if layout is None else validate_layout(layout)
    log_event(
        db, entity_type="overview_layout", entity_id=organization.id, action="updated", actor_id=actor_id,
        organization_id=organization.id, detail=_audit_detail(organization.overview_widgets),
    )


# --- bundles -----------------------------------------------------------------------------------------


def export_layout(layout: dict[str, Any] | None) -> dict[str, Any]:
    """A project's or organisation's own layout as a bundle section (`None` when it has none, so an import inherits)."""
    return {BUNDLE_KEY: copy.deepcopy(layout)}


def import_layout(data: dict[str, Any], warnings: BundleImportWarnings) -> dict[str, Any] | None:
    """The layout an import stores: the bundle's, or `None` when it has none or it is not valid here.

    A layout naming a metric or widget type this installation does not have (a module that is not installed) is
    skipped with a warning, so the project follows what it inherits rather than carrying a broken overview.
    """
    raw = data.get(BUNDLE_KEY)
    if raw is None:
        return None
    try:
        return validate_layout(raw)
    except HTTPException:
        warnings.add("The overview layout in the bundle was not imported because it names a widget or metric that is not available here.")
        return None
