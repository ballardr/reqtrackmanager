"""
Module: services.report_org_values

The organisation's report look, as a custom layout may read it.

Responsibilities:
- `ORG_VALUES`: the closed set a layout reads as `{{org.<key>}}` or `org.<key>` in an `if`, with each kind, so the tree
  validator, text format and evaluator agree; `report_org_values` (one organisation's values); `report_accent_hex`;
  `ORG_LOGO_FILE` (the reserved image `file` for the logo).

Design decisions:
- These are core organisation settings, so the keys are a fixed set, not a registry; any other key is a save-time problem.
- A layout is never forced to print any of this; built-in reports apply the values automatically
  (`report_document.resolve_branding`).
- A value is text or a boolean and never becomes markup (the placeholder rule in `report_layout_eval`).

Dependencies: `services.branding`, `models.organization`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization, ServerSettings
from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.report_colours import entries_of

#: The `file` an image block or a header/footer logo names to mean the organisation's logo.
ORG_LOGO_FILE = "org_logo"

#: The placeholder family and condition alias a layout reads these under.
ORG_FAMILY = "org"


@dataclass(frozen=True)
class OrgValue:
    """One value of the organisation's report look.

    Attributes:
        key: The name after `org.`.
        kind: `text` or `bool` (the condition operators of that kind apply).
        help: What it is, for the designer and the docs.
    """

    key: str
    kind: str
    help: str


ORG_VALUES: tuple[OrgValue, ...] = (
    OrgValue("footer_text", "text", "The organisation's default footer text (empty when none is set)."),
    OrgValue("include_cover_page", "bool", "Whether the organisation wants a cover page on its reports."),
    OrgValue("include_logo", "bool", "Whether the organisation wants its logo on its reports."),
    OrgValue("chapters_per_component", "bool", "Whether the organisation wants one chapter per component."),
    OrgValue("report_accent", "text", "The organisation's report accent colour, as #rrggbb."),
)

ORG_VALUE_KEYS: tuple[str, ...] = tuple(value.key for value in ORG_VALUES)


def org_value_kind(key: str) -> str | None:
    """The kind (`text` or `bool`) of an organisation value, or `None` when the key is not one."""
    return next((value.kind for value in ORG_VALUES if value.key == key), None)


def report_accent_hex(db: Session, organization: Organization) -> str:
    """The accent colour reports use: the report accent, else the organisation's UI accent, else the platform's.

    Args:
        db: Database session (read only).
        organization: The organisation.

    Returns:
        A `#rrggbb` colour.
    """
    if organization.report_accent_color_hex:
        return organization.report_accent_color_hex
    if organization.accent_color_hex:
        return organization.accent_color_hex
    platform = db.scalar(select(ServerSettings.accent_color_hex))
    return platform or DEFAULT_ACCENT_COLOR_HEX


def organization_colour_names(organization: Organization) -> list[str]:
    """The names in the organisation's report colour scheme (empty when none is set)."""
    return list(entries_of(organization.report_colour_scheme))


def report_org_values(db: Session, organization: Organization) -> dict[str, Any]:
    """The values a layout may read for `organization`, keyed by `ORG_VALUE_KEYS`.

    Args:
        db: Database session (read only).
        organization: The organisation the report runs for.

    Returns:
        `{key: text or bool}`. Text is `""`, never `None`, when unset.
    """
    return {
        "footer_text": organization.report_footer_text or "",
        "include_cover_page": bool(organization.report_include_cover_page),
        "include_logo": bool(organization.report_include_logo),
        "chapters_per_component": bool(organization.report_chapters_per_component),
        "report_accent": report_accent_hex(db, organization),
    }


__all__ = [
    "ORG_FAMILY", "ORG_LOGO_FILE", "ORG_VALUES", "ORG_VALUE_KEYS", "OrgValue", "org_value_kind", "organization_colour_names",
    "report_accent_hex", "report_org_values",
]
