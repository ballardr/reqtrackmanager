"""
Module: schemas.overview_widgets

Request and response shapes for the project overview widgets (`routers.overview_widgets`): the layout, the editor's
catalogue and the batched metric values.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.overview_metrics import MAX_METRICS_PER_REQUEST, ScopeName
from app.services.overview_widgets import MAX_COLUMNS, MAX_ROWS, MAX_TITLE_LENGTH, MAX_WIDGETS


class OverviewWidget(BaseModel):
    """One widget instance of a layout.

    Attributes:
        id: Unique within the layout (letters, digits, hyphens, underscores).
        type: Widget type key (`gauge`, or `<module_key>:<key>`).
        title: Optional heading that replaces the metric's name.
        width: Columns of the 12-column grid, 1 to 12.
        height: Rows, 1 to 12; a minimum, because a row grows with its content.
        scope: The widget's own project scope (`this`, `parents`, `children`, `both`), or `None` to follow the overview's.
        visible: Whether the widget is shown (a hidden widget requests no data).
        config: The type's settings, checked server-side.
    """

    id: str = Field(max_length=40)
    type: str = Field(max_length=100)
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH * 2)
    width: int = Field(default=3, strict=True, le=MAX_COLUMNS)
    height: int = Field(default=2, strict=True, le=MAX_ROWS)
    scope: str | None = None
    visible: bool = Field(default=True, strict=True)
    config: dict[str, Any] = Field(default_factory=dict)


class OverviewLayoutSet(BaseModel):
    """The complete layout to store: the overview's project scope and its widgets."""

    scope: str = "this"
    widgets: list[OverviewWidget] = Field(max_length=MAX_WIDGETS)


class OverviewLayoutOut(BaseModel):
    """The layout in force.

    Attributes:
        scope: The overview's project scope; a widget with no scope of its own follows it.
        widgets: The widgets, in order.
        source: `own`, `ancestor`, `organisation` or `default`.
        inherited_source: Where the layout would come from if the project's own were removed (project view only).
        can_customise: Whether the caller may change the layout (the same check as the write endpoint), so the page
            shows its "Customise" control only to those who can use it.
    """

    scope: str = "this"
    widgets: list[OverviewWidget]
    source: str
    inherited_source: str | None = None
    can_customise: bool = False


class WidgetTypeOut(BaseModel):
    """A widget type the editor offers."""

    key: str
    label: str
    description: str
    module_key: str | None = None
    width: int = 4
    height: int = 4


class MetricOut(BaseModel):
    """A metric the editor offers, with what a widget may draw from it."""

    key: str
    label: str
    unit: str
    scalar: bool
    breakdown: bool
    params: list[str]
    module_key: str | None = None


class RecordTypeOptionOut(BaseModel):
    """A record type a record count may use, with its own list filters."""

    type: str
    label: str
    filter_params: list[str]


class OverviewCatalogueOut(BaseModel):
    """Everything the widget editor offers for this project (or organisation)."""

    widget_types: list[WidgetTypeOut]
    metrics: list[MetricOut]
    record_types: list[RecordTypeOptionOut]
    max_widgets: int = MAX_WIDGETS


class MetricSpecIn(BaseModel):
    """One requested figure: the caller's id for it, the catalogue key, the settings and the project scope."""

    id: str = Field(max_length=40)
    metric: str = Field(max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)
    scope: ScopeName = "this"


class OverviewMetricsRequest(BaseModel):
    """The figures the visible widgets need, in one call."""

    metrics: list[MetricSpecIn] = Field(max_length=MAX_METRICS_PER_REQUEST)


class BreakdownRowOut(BaseModel):
    """One row of a breakdown."""

    key: str
    label: str
    value: float
    detail: str | None = None


class MetricResultOut(BaseModel):
    """One figure's outcome.

    Attributes:
        state: `ok`, `unavailable`, `timeout` or `error`; only `ok` carries data.
        unit: `count` or `percent`.
        label: The metric's name (the counted type's plural name for a record count), the default widget title.
        projects: How many projects the figure covers (1 unless its scope was widened).
        value: The single figure, when the metric has one.
        breakdown: The rows, when the metric has them.
    """

    state: str
    unit: str | None = None
    label: str | None = None
    projects: int = 1
    value: float | None = None
    breakdown: list[BreakdownRowOut] | None = None


class OverviewMetricsOut(BaseModel):
    """The figures by the caller's ids."""

    results: dict[str, MetricResultOut]
