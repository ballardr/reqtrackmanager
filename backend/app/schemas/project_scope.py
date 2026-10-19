"""
Module: schemas.project_scope

The response mixin every project-scoped list row carries so a list widened to related
projects (`services.project_scope`) can say which project a row came from.

The three fields are set only on a row that comes from a project other than the one the
request was made for, so a plain single-project list is byte-for-byte what it was and a
client builds a row's link as `from_project_id ?? <request project>`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ProjectScopedRow(BaseModel):
    """List-row mixin: where a row from another project of the scope came from.

    Attributes:
        from_project_id: The row's own project, set only when it is not the request project.
        from_project_name: That project's name.
        from_project_code: That project's code (qualifies the row's record code).
    """

    from_project_id: UUID | None = None
    from_project_name: str | None = None
    from_project_code: str | None = None


class ProjectScopeOptionsOut(BaseModel):
    """Which scope choices a project offers its viewer.

    Attributes:
        has_parents: At least one ancestor project the viewer can open.
        has_children: At least one descendant project the viewer can open.
        truncated: The related-project cap cut the set short.
    """

    has_parents: bool
    has_children: bool
    truncated: bool = False
