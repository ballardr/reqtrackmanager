"""
Module: schemas.nav_labels

Request and response shapes for navigation names (`routers.nav_labels`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.nav_labels import MAX_LABEL_LENGTH


class NavLabelItemOut(BaseModel):
    """One navigation entry with the names that apply to it.

    Attributes:
        key: Stable navigation key.
        label: Built-in name in English (a core entry that follows terminology is named by the client).
        path: The entry's route for the project; `None` in the organisation view.
        module_key: Owning module, `None` for a core entry.
        own: This project's (or this organisation's) own name.
        inherited: The name the entry would have without its own: the nearest ancestor's, else the organisation's.
        inherited_from: `ancestor` or `organisation` when `inherited` is set.
        effective: The name that applies (`own`, else `inherited`); `None` means the built-in name.
    """

    key: str
    label: str
    path: str | None = None
    module_key: str | None = None
    own: str | None = None
    inherited: str | None = None
    inherited_from: str | None = None
    effective: str | None = None


class NavLabelsOut(BaseModel):
    """The entries a project's navigation can show (or an organisation can name), in navigation order."""

    items: list[NavLabelItemOut]


class NavLabelsSet(BaseModel):
    """The complete set of own names, by navigation key; a key left out follows what it inherits."""

    names: dict[str, str] = Field(default_factory=dict, description=f"Plain text of at most {MAX_LABEL_LENGTH} characters each.")
