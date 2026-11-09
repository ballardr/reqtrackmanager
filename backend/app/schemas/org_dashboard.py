"""Request and response shapes for organisation dashboards (`routers.org_dashboards`)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.overview_widgets import OverviewWidget
from app.schemas.principal import PrincipalOut, PrincipalRef
from app.services.org_dashboards import MAX_VIEWERS


class DashboardOut(BaseModel):
    """One dashboard page.

    Attributes:
        id: The page id, or `overview` for the built-in page that has not been stored yet.
        name: The page name.
        is_default: True for the built-in Overview page, which cannot be renamed or deleted.
        restricted: True when the page is limited to its viewers.
        viewers: Who the page is limited to (an administrator's view only; empty for everyone else).
        can_manage: Whether the caller may change the page.
    """

    id: str
    name: str
    is_default: bool
    restricted: bool
    viewers: list[PrincipalOut] = []
    can_manage: bool = False


class DashboardLayoutOut(BaseModel):
    """A page with the layout in force."""

    dashboard: DashboardOut
    scope: str = "this"
    widgets: list[OverviewWidget]
    built_in: bool = False


class DashboardCreate(BaseModel):
    """A new page: its name and, optionally, who it is limited to."""

    name: str = Field(max_length=200)
    viewers: list[PrincipalRef] = Field(default_factory=list, max_length=MAX_VIEWERS)


class DashboardCopy(BaseModel):
    """Copies a page; without a name the copy is "Copy of <name>"."""

    name: str | None = Field(default=None, max_length=200)


class DashboardUpdate(BaseModel):
    """Renames a page and/or replaces its viewers (a key left out is unchanged; an empty list shows it to every member)."""

    name: str | None = Field(default=None, max_length=200)
    viewers: list[PrincipalRef] | None = Field(default=None, max_length=MAX_VIEWERS)


class DashboardOrder(BaseModel):
    """Every page after the built-in one, in the order to show them."""

    ids: list[str] = Field(max_length=100)
