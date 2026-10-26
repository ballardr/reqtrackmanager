"""
Module: models.report_content

Per-report-type introduction, chapters and appendices .

One table holds the content of every tier (report template, project,
organisation) so there is a single store and a single resolution path instead
of three sets of columns. `scope_id` is polymorphic (a template, project or
organisation id) with no foreign key, the trade-off `ArtefactLink` already
accepts: the owners of the rows delete them explicitly
(`services.report_content.delete_content_for_scopes`, called from template
deletion and `services.org_deletion`).

`report_key` is a plain validated string, not an enum: `"requirements"`,
`"<module_key>.<report_key>"` from the module registry (checked at write time
against `services.report_content.valid_report_keys`, so a module that declares
a report gains per-type content with no core edit), or `"custom.<layout id>"` for a
custom report layout (checked against the layouts the scope can reach). `ALL_REPORTS_KEY` (`"*"`)
is the "every report that has no row of its own" entry. It is a sentinel
rather than NULL so the `(scope_type, scope_id, report_key)` unique constraint
works (NULLs are distinct in a unique index).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin

SCOPE_TEMPLATE = "template"
SCOPE_PROJECT = "project"
SCOPE_ORGANIZATION = "organization"
SCOPE_TYPES: tuple[str, ...] = (SCOPE_TEMPLATE, SCOPE_PROJECT, SCOPE_ORGANIZATION)

REQUIREMENTS_REPORT_KEY = "requirements"
ALL_REPORTS_KEY = "*"
CUSTOM_REPORT_KEY_PREFIX = "custom."
"""A custom report layout's content key is `custom.<layout id>`."""
PORTABLE_CUSTOM_KEY_PREFIX = "custom:"
"""In an export bundle the same key is `custom:<layout name>`: a layout id means nothing in the target installation."""


class ReportContent(UUIDPKMixin, TimestampMixin, Base):
    """The intro, chapters and appendices one scope holds for one report type.

    Attributes:
        scope_type: `template`, `project` or `organization`.
        scope_id: The owning template, project or organisation id (no FK).
        report_key: `REQUIREMENTS_REPORT_KEY`, a `"<module_key>.<report_key>"`
            module report, a `"custom.<layout id>"` layout, or `ALL_REPORTS_KEY`.
        intro: Markdown printed before the chapters.
        chapters: Ordered `{title, body}` chapters printed after the intro.
        appendices: Ordered `{title, body}` chapters printed after the report.
    """

    __tablename__ = "report_contents"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id", "report_key", name="uq_report_contents_scope_key"),)

    scope_type: Mapped[str] = mapped_column(String(20))
    scope_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    report_key: Mapped[str] = mapped_column(String(100))
    intro: Mapped[str] = mapped_column(Text, default="")
    chapters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    appendices: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
