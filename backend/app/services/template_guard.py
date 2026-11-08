"""
Module: services.template_guard

Makes a template project read-only for everyone below project administrator.

A project marked `is_template` is the starting point other projects are created from, and an organisation-wide
visibility setting gives every organisation member the baseline Member role on it. Without a guard an org-wide
template would be editable by anyone who can see it, and a module's "any member may submit" setting (Pain
Points, Product Feedback and the like) would still let members add records. So while a project is a template,
only a project manager, a project administrator or an organisation administrator may change it, whatever the
project's own configuration and whatever module or fine-grained role the caller holds.

Design decisions:
- One application-wide dependency decides, from the request's method and its `project_id` path parameter, so a
  new module or endpoint is covered without declaring anything; it fails closed. A POST that only reads
  (search, previews, report runs) is listed in `READ_ONLY_ROUTES`; every other mutating route is refused.
- A person's own preferences (favouriting the project, watching a record) are not changes to the project and
  stay available.
- The caller is resolved the way the route resolves them (session, personal access token or module frame token);
  a credential that does not resolve is left for the route's own authentication to refuse.

External dependencies: `services.rbac` (manager resolution), `deps` (credential resolution).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from app.database import get_db
from app.deps import _resolve_user_from_token
from app.models.enums import ProjectVisibility
from app.models.project import Project
from app.models.user import User
from app.security import PAT_PREFIX, decode_module_frame_token
from app.services.rbac import can_manage_project_settings, get_effective_permissions, permission_satisfied

PUBLISH_ORGANIZATION_TEMPLATES = "publish_organization_templates"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Mutating-method routes (matched on the route's path template) that do not change the project: reading with a
#: request body, running a report, and a person's own preferences.
READ_ONLY_ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("PUT", "/api/v1/projects/{project_id}/favorite"),
    ("DELETE", "/api/v1/projects/{project_id}/favorite"),
    ("POST", "/api/v1/projects/{project_id}/files/search"),
    ("POST", "/api/v1/projects/{project_id}/modules/product_feedback/score-preview"),
    ("POST", "/api/v1/projects/{project_id}/report-file/export"),
    ("POST", "/api/v1/projects/{project_id}/report-layouts/preview"),
    ("POST", "/api/v1/projects/{project_id}/report-layouts/preview/download"),
    ("POST", "/api/v1/projects/{project_id}/report-layouts/validate"),
    ("POST", "/api/v1/projects/{project_id}/report-snippets/check"),
    ("POST", "/api/v1/projects/{project_id}/report-snippets/check-organization"),
    ("POST", "/api/v1/projects/{project_id}/report-packs/{pack_id}/preview"),
    ("POST", "/api/v1/projects/{project_id}/report-packs/{pack_id}/run"),
    ("POST", "/api/v1/projects/{project_id}/report-packs/{pack_id}/runs"),
    ("POST", "/api/v1/projects/{project_id}/custom-reports/{layout_id}/runs"),
    ("POST", "/api/v1/projects/{project_id}/change-requests/{cr_id}/watchers"),
    ("DELETE", "/api/v1/projects/{project_id}/change-requests/{cr_id}/watchers/{group_type}/{group_id}"),
    ("POST", "/api/v1/projects/{project_id}/requirements/{requirement_id}/watchers"),
    ("DELETE", "/api/v1/projects/{project_id}/requirements/{requirement_id}/watchers/{group_type}/{group_id}"),
})


def _caller(request: Request, token: str | None, db: Session) -> User | None:
    """The user a request's credential names, or `None` when it names nobody (the route then refuses it)."""
    try:
        if token and not token.startswith(PAT_PREFIX):
            claims = decode_module_frame_token(token)
            if claims is not None:
                return db.get(User, UUID(claims["user_id"]))
        return _resolve_user_from_token(token, db, request)
    except (HTTPException, ValueError, KeyError):
        return None


def enforce_template_read_only(connection: HTTPConnection, db: Session = Depends(get_db)) -> None:
    """Application-wide dependency: refuses a change to a template project by anyone who cannot manage it.

    Takes the connection rather than a request so that it can sit on every route: a WebSocket has no method
    and changes nothing, so it passes straight through.

    Args:
        connection: The incoming connection (method, path parameters, headers and matched route).
        db: The request's database session.

    Raises:
        HTTPException: 403 when the request changes a template project and the caller is neither a project
            manager, a project administrator nor an administrator of the project's organisation.
    """
    if connection.scope["type"] != "http":
        return
    request = Request(connection.scope)
    if request.method in SAFE_METHODS:
        return
    raw_project_id = request.path_params.get("project_id")
    if raw_project_id is None:
        return
    route = request.scope.get("route")
    if route is not None and (request.method, route.path) in READ_ONLY_ROUTES:
        return
    try:
        project = db.get(Project, UUID(str(raw_project_id)))
    except ValueError:
        return
    if project is None or not project.is_template:
        return
    _scheme, token = get_authorization_scheme_param(request.headers.get("Authorization"))
    user = _caller(request, token or None, db)
    if user is None or can_manage_project_settings(db, user, project):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "This project is a template. Only project managers and project administrators can change it.",
    )


def ensure_may_publish_template(
    db: Session, user: User, organization_id: UUID, *, is_template: bool, visibility: ProjectVisibility, already_published: bool,
) -> None:
    """Refuses creating the combination of a template and organisation-wide visibility without permission.

    A template that every organisation member can see is the starting point for every new project, and an
    organisation-wide project gives each member a baseline role on it, so publishing one needs the
    organisation-level `publish_organization_templates` permission rather than only the project's own
    management. Either setting alone needs nothing more. A project that already has both is not blocked from
    keeping them (so existing ones carry on), and removing either is always allowed.

    Args:
        db: The request's database session.
        user: The person making the change.
        organization_id: The project's organisation.
        is_template: Whether the project will be a template afterwards.
        visibility: The project's visibility afterwards.
        already_published: Whether the project is both a template and organisation-wide now.

    Raises:
        HTTPException: 403 when the result is the combination, it is new, and the caller lacks the permission
            (a server administrator has no bypass).
    """
    if already_published or not (is_template and visibility == ProjectVisibility.ORG_WIDE):
        return
    held = get_effective_permissions(db, user.id, organization_id=organization_id)
    if not permission_satisfied(held, PUBLISH_ORGANIZATION_TEMPLATES):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Making a template visible to the whole organisation needs the permission to publish organisation templates.",
        )
