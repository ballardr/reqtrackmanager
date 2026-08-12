"""
Module: server

A Model Context Protocol (MCP) server exposing ReqTrackManager's
requirements to an AI assistant to call directly, instead of a human
copy-pasting requirement text into a chat window. Read-only by default;
an opt-in write mode (`MCP_WRITES_ENABLED`) additionally exposes
`create_requirement`/`update_requirement` so requirement *content* can be
authored by AI. See docs/mcp-server.md for the full design writeup, the
"Write mode" section, and client setup guides (Claude Code, VS Code
Copilot Chat, Microsoft Copilot Studio, and generic HTTP clients).

Responsibilities:
- Exposes a small set of tools (list/get organisations, projects, and
  requirements; when write mode is on, create/edit requirement content
  too) backed entirely by the existing REST API — this module contains no
  direct database access and no business logic of its own.
- Enforces authentication and authorization by *forwarding* the caller's
  own ReqTrackManager bearer token to the backend on every call, rather
  than authenticating as some shared service account. This is the module's
  one deliberate design decision, not incidental: the backend's existing,
  already-tested RBAC does 100% of the access-control work, so a caller
  using this server can never see or change anything they couldn't already
  see or change through the normal UI/API — there is no second, parallel
  permission model to get wrong here. See `_forward_auth_header` and
  docs/mcp-server.md's "Authentication model" section.
- Never exposes an approval-type action, in either mode. There is no tool
  to approve/decide a change request, approve a requirement, record a
  review outcome, or mark a requirement completed — and, structurally, no
  way to request one: `update_requirement` has no `status` parameter at
  all, so a `status` transition can never be sent through this server
  regardless of what the calling account's own role could do directly via
  the API. This is a deliberate product decision, not merely an oversight
  left for later: ReqTrackManager's approval workflow is only meaningful if
  every approval is a deliberate human action taken with real accountability
  in the UI, so this server keeps that boundary bright-line rather than
  relying on the backend's RBAC (which *would* correctly allow a
  PM-privileged caller to approve something) to enforce a product policy
  it was never meant to express. See docs/decisions.md's "MCP server write
  mode" entry.

Design decision — pass-through auth, not a service account: an earlier
design considered giving this server its own fixed backend credential
(logging in once as a dedicated "integration" user). Rejected because it
would mean every caller of this MCP server sees exactly what that one
service account can see, project-by-project access from real project
memberships and RBAC — the opposite of this project's whole multi-tenant,
per-user access model, and a much larger blast radius if the MCP server's
own credential ever leaked (rather than one caller's own already-scoped
token).

External dependencies: `fastmcp` (the MCP server framework), `httpx` (the
same async HTTP client used to talk to the backend API that the rest of
this project already uses in its seed scripts).
"""

from __future__ import annotations

import html
import json
import os
import uuid
from urllib.parse import quote

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse

REQTRACK_API_URL = os.environ.get("REQTRACK_API_URL", "http://backend:8000").rstrip("/")
# Distinct from REQTRACK_API_URL above: that one is this server's own
# server-to-server address for the backend (typically a Compose-internal
# hostname like http://backend:8000, unreachable from a user's own
# browser). This one is what gets embedded into HTML/JS actually sent to a
# browser (the SSO button's target) — it must be the backend's
# externally-reachable address, matching the backend's own
# PUBLIC_BACKEND_URL setting.
REQTRACK_PUBLIC_API_URL = os.environ.get("REQTRACK_PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
_HTTP_TIMEOUT = 30.0


def _env_flag(name: str, *, default: bool = False) -> bool:
    """Parses a boolean-ish environment variable the same permissive way
    Docker Compose/`.env` files are typically written (`true`/`1`/`yes`/`on`,
    case-insensitive) rather than requiring an exact literal."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Off by default: a deployment operator must explicitly opt in before this
# server can change any data at all — see docs/mcp-server.md's "Write mode"
# section and docs/decisions.md's "MCP server write mode" entry for why this
# is a deliberate, narrow capability (requirement content only, never an
# approval-type action) rather than a general write API.
MCP_WRITES_ENABLED = _env_flag("MCP_WRITES_ENABLED")

_READ_ONLY_INSTRUCTIONS = (
    "Access to ReqTrackManager requirements, change requests, notifications, and review schedules. "
    "Every tool call requires the caller's own ReqTrackManager access token, supplied as an "
    "'Authorization: Bearer <token>' HTTP header on the MCP connection itself — this server never "
    "authenticates as its own account (no token? visit this server's own /login page in a browser "
    "to get one). Start with list_organizations or list_projects to find the project_id a "
    "requirement or change request lives in, then list_requirements / get_requirement or "
    "list_change_requests / get_change_request. A change request's discussion, tasks, and advisory "
    "stakeholder votes are separate tools (list_change_request_comments/_tasks/_votes) from its "
    "core detail."
)
_WRITE_MODE_INSTRUCTIONS = (
    " Write mode is enabled on this server: create_requirement and update_requirement let you "
    "author and edit requirement *content*. Neither tool, nor any other tool here, can approve or "
    "decide anything — there is no way to approve a requirement or a change request, record a "
    "review outcome, or mark a requirement completed through this server, regardless of the "
    "calling account's own role. Those are deliberately human-only actions taken in the "
    "ReqTrackManager UI. update_requirement also refuses to touch a requirement that's already "
    "approved/locked — at that point a change request is required instead, and this server has no "
    "tool for creating or deciding one."
)

mcp = FastMCP(
    name="ReqTrackManager",
    instructions=_READ_ONLY_INSTRUCTIONS + (_WRITE_MODE_INSTRUCTIONS if MCP_WRITES_ENABLED else ""),
)


class AuthenticationRequiredError(Exception):
    """Raised when a tool is called without a valid Authorization header on
    the MCP connection. Surfaced to the caller as a tool error, not a
    silent empty result — a missing token should never look like "no
    requirements exist"."""


def _forward_auth_header() -> dict[str, str]:
    """Reads the incoming MCP request's `Authorization` header and returns
    it as a dict ready to merge into an outgoing httpx request's headers.

    This is the entire authentication mechanism for this server: it never
    issues, stores, or validates a token itself — it only relays whatever
    the caller already presented, letting the backend's own auth/RBAC be
    the single source of truth. Deliberately does not log the header value
    (or any part of it) anywhere, including in error messages — see
    `_call_backend`'s error handling below.

    Raises:
        AuthenticationRequiredError: if the connection has no Authorization
            header at all. A present-but-invalid/expired token is NOT
            checked here — that's indistinguishable from "valid" without
            calling the backend, so it's left to `_call_backend` to surface
            the backend's own 401 response instead of duplicating that check.
    """
    # include_all=True is required: get_http_headers() excludes
    # Authorization (and a few other sensitive headers) by default, on the
    # reasonable assumption that most tools shouldn't see it — but relaying
    # it onward is this server's entire purpose, so it's deliberately opted
    # back in here, in this one function, rather than everywhere.
    headers = get_http_headers(include_all=True)
    auth_header = headers.get("authorization")
    if not auth_header:
        raise AuthenticationRequiredError(
            "No Authorization header was presented on this MCP connection. Configure your MCP "
            "client with 'Authorization: Bearer <your ReqTrackManager access token>' — see "
            "docs/mcp-server.md for how to obtain one and configure it per client."
        )
    return {"Authorization": auth_header}


def _require_uuid(value: str, field_name: str) -> str:
    """Validates that `value` is a syntactically well-formed UUID before
    it's interpolated into a backend URL path, rejecting anything else with
    a clear tool error rather than forwarding it as-is. Not a security
    boundary the backend doesn't already enforce (FastAPI's own UUID path
    parameters would 422 on malformed input too) — but validating here, at
    this server's own boundary, means a malformed value can never influence
    what URL gets constructed in the first place, closing off any path-
    confusion class of issue before it's even a question. Returns the
    canonical string form (normalises case/formatting) for use in the URL.
    """
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field_name!r} must be a valid UUID, got {value!r}.") from exc


def _detail(response: httpx.Response) -> str:
    """Extracts FastAPI's `{"detail": "..."}` error body shape into a plain
    string when present, falling back to the raw response text otherwise —
    used so a validation/conflict error (e.g. "this requirement is approved;
    changes must be made via a change request") reaches the AI assistant as
    a clean sentence rather than a raw JSON blob."""
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return body["detail"]
    return response.text


async def _call_backend(
    method: str, path: str, *, params: dict | None = None, json: dict | None = None
) -> httpx.Response:
    """Makes one authenticated request to the ReqTrackManager backend,
    forwarding the caller's own token, and translates common failure modes
    into clear tool errors.

    Args:
        method: HTTP method, e.g. "GET", "POST", "PUT".
        path: Backend path starting with `/api/v1/...`.
        params: Optional query string parameters; `None` values are
            dropped so optional tool arguments don't get forwarded as the
            literal string "None".
        json: Optional JSON request body, for write tools (`POST`/`PUT`).
            Unused by every read tool.

    Returns:
        The successful `httpx.Response`.

    Raises:
        AuthenticationRequiredError: no Authorization header was presented.
        PermissionError: the backend rejected the token (401) or the
            caller's own account lacks access to the requested resource (403).
        LookupError: the backend returned 404 for the requested resource.
        ValueError: the backend rejected the request as invalid or
            conflicting with the resource's current state (400/409/422) —
            e.g. an unknown component_id, or editing a locked requirement.
        RuntimeError: any other non-2xx backend response, or a network-level
            failure reaching the backend at all.
    """
    headers = _forward_auth_header()
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    url = f"{REQTRACK_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.request(method, url, headers=headers, params=clean_params, json=json)
    except httpx.HTTPError as exc:
        # Never include `headers` (or anything derived from it) in an
        # exception message — this is the one place in the module that
        # would otherwise be tempting, since httpx exceptions sometimes
        # echo request details.
        raise RuntimeError(f"Could not reach the ReqTrackManager backend at {REQTRACK_API_URL}: {exc}") from exc

    if response.status_code == 401:
        raise PermissionError(
            "ReqTrackManager rejected the presented access token (401) — it may be expired, "
            "revoked, or malformed. Obtain a fresh token and reconfigure your MCP client."
        )
    if response.status_code == 403:
        raise PermissionError(
            "Your ReqTrackManager account does not have access to this resource (403) — this "
            "mirrors exactly what you'd see calling the API directly with the same account; this "
            "server has no broader access than your own account does."
        )
    if response.status_code == 404:
        raise LookupError("The requested resource does not exist, or you don't have access to it.")
    if response.status_code in (400, 409, 422):
        raise ValueError(f"ReqTrackManager rejected this request ({response.status_code}): {_detail(response)}")
    if response.is_error:
        raise RuntimeError(f"ReqTrackManager returned an unexpected error ({response.status_code}): {_detail(response)}")
    return response


@mcp.tool
async def list_organizations() -> list[dict]:
    """Lists the organisations the caller's ReqTrackManager account belongs to or administers.

    Returns:
        A list of organisations, each with at least `id` and `name` — use
        an organisation's `id` to filter `list_projects`, or just browse
        `list_projects` directly since project listing already spans every
        organisation the caller can see.
    """
    response = await _call_backend("GET", "/api/v1/orgs")
    return response.json()


@mcp.tool
async def list_projects(organization_id: str | None = None, search: str | None = None, include_archived: bool = False) -> list[dict]:
    """Lists projects the caller's ReqTrackManager account has a role on, across every organisation.

    Args:
        organization_id: Optional UUID to restrict results to one organisation
            (matched client-side against each project's own `organization_id`
            — the backend's own listing already spans every org the caller
            can see, there's no separate per-org listing endpoint).
        search: Optional case-insensitive substring match against project
            name or summary.
        include_archived: Whether to include archived projects (excluded by default).

    Returns:
        A list of projects, each with `id`, `organization_id`, `name`, `summary`, and status flags.
    """
    org_filter = _require_uuid(organization_id, "organization_id") if organization_id else None
    response = await _call_backend(
        "GET", "/api/v1/projects", params={"search": search, "archived": include_archived}
    )
    projects = response.json()
    if org_filter:
        projects = [p for p in projects if p.get("organization_id") == org_filter]
    return projects


@mcp.tool
async def get_project(project_id: str) -> dict:
    """Gets a single project's details by id.

    Args:
        project_id: The project's UUID (from `list_projects`).

    Returns:
        The project's `id`, `organization_id`, `name`, `summary`, and status flags.
    """
    pid = _require_uuid(project_id, "project_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}")
    return response.json()


@mcp.tool
async def list_requirements(
    project_id: str,
    status: str | None = None,
    search: str | None = None,
    keyword: str | None = None,
    component_id: str | None = None,
    category_id: str | None = None,
    include_archived: bool = False,
) -> list[dict]:
    """Lists requirements in a project, with the same filters the Requirements page's filter panel offers.

    Args:
        project_id: The project's UUID (from `list_projects`).
        status: Optional exact status filter — one of "draft", "reviewed",
            "approved", "completed", "archived".
        search: Optional case-insensitive substring match against a
            requirement's name or its unique code (e.g. "SW-PERF-014") —
            use this to find a specific requirement by code.
        keyword: Optional exact match against a requirement's assigned keywords.
        component_id: Optional UUID to filter to one component.
        category_id: Optional UUID to filter to one category.
        include_archived: Whether to include archived requirements (excluded by default).

    Returns:
        A list of requirements, each including `id`, `unique_code`, `name`,
        `reasoning`, `status`, `is_locked`, and more — use a result's `id`
        with `get_requirement` for the full record, or `get_requirement_history`
        for its change log.
    """
    pid = _require_uuid(project_id, "project_id")
    comp = _require_uuid(component_id, "component_id") if component_id else None
    cat = _require_uuid(category_id, "category_id") if category_id else None
    response = await _call_backend(
        "GET", f"/api/v1/projects/{pid}/requirements",
        params={
            "status": status, "search": search, "keyword": keyword,
            "component_id": comp, "category_id": cat, "include_archived": include_archived,
        },
    )
    return response.json()


@mcp.tool
async def get_requirement(project_id: str, requirement_id: str) -> dict:
    """Gets a single requirement's full current detail.

    Args:
        project_id: The project's UUID (from `list_projects`).
        requirement_id: The requirement's UUID (from `list_requirements`
            — not its human-readable unique code; use `list_requirements`
            with `search=<code>` first if you only have the code).

    Returns:
        The requirement's full detail: `unique_code`, `name`, `reasoning`,
        `clarification`, `status`, `is_locked`, `component_id`,
        `category_id`, `keywords`, `custom_fields`, and more.
    """
    pid = _require_uuid(project_id, "project_id")
    rid = _require_uuid(requirement_id, "requirement_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/requirements/{rid}")
    return response.json()


@mcp.tool
async def get_requirement_history(project_id: str, requirement_id: str) -> list[dict]:
    """Gets a requirement's full version history — every prior state it has been in.

    Useful for answering "why does this requirement say X" or "what did
    this look like before the last change" — each entry records what
    changed, who changed it, and the change note explaining why (C-A-09).

    Args:
        project_id: The project's UUID (from `list_projects`).
        requirement_id: The requirement's UUID (from `list_requirements`).

    Returns:
        A list of historical versions, oldest first, each with
        `version_number`, `name`, `reasoning`, `status`, `change_note`,
        `created_by`, and `created_at`.
    """
    pid = _require_uuid(project_id, "project_id")
    rid = _require_uuid(requirement_id, "requirement_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/requirements/{rid}/history")
    return response.json()


@mcp.tool
async def list_change_requests(project_id: str, status: str | None = None) -> list[dict]:
    """Lists change requests in a project.

    Args:
        project_id: The project's UUID (from `list_projects`).
        status: Optional exact status filter — one of "draft", "submitted",
            "in_review", "approved", "rejected", "withdrawn".

    Returns:
        A list of change requests, each including `id`, `kind`
        ("new_requirement" or "modify_requirement"), `proposed_name`,
        `proposed_reasoning`, `reason`, `status`, and the `requirement_id`
        it targets (`None` for a "new_requirement" proposal).
    """
    pid = _require_uuid(project_id, "project_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/change-requests", params={"cr_status": status})
    return response.json()


@mcp.tool
async def get_change_request(project_id: str, change_request_id: str) -> dict:
    """Gets a single change request's full current detail.

    Args:
        project_id: The project's UUID (from `list_projects`).
        change_request_id: The change request's UUID (from `list_change_requests`).

    Returns:
        The change request's full detail: `kind`, `proposed_name`,
        `proposed_reasoning`, `proposed_clarification`, `reason`, `status`,
        the requirement it targets, and more.
    """
    pid = _require_uuid(project_id, "project_id")
    cid = _require_uuid(change_request_id, "change_request_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/change-requests/{cid}")
    return response.json()


@mcp.tool
async def list_change_request_votes(project_id: str, change_request_id: str) -> dict:
    """Gets a change request's advisory stakeholder vote tally and individual votes.

    Advisory only — a project manager's actual approve/reject decision
    (see `get_change_request`'s `status`) is a separate, authoritative
    action these votes never determine on their own (C-R-03).

    Args:
        project_id: The project's UUID (from `list_projects`).
        change_request_id: The change request's UUID (from `list_change_requests`).

    Returns:
        `{"votes": [...], "approve_count": int, "reject_count": int}` —
        each vote includes `user_id`, `vote` ("approve"/"reject"), an
        optional `comment`, and `voted_at`.
    """
    pid = _require_uuid(project_id, "project_id")
    cid = _require_uuid(change_request_id, "change_request_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/change-requests/{cid}/votes")
    return response.json()


@mcp.tool
async def list_change_request_tasks(project_id: str, change_request_id: str) -> list[dict]:
    """Lists the follow-up tasks tracked against a change request (C-R-02, C-R-04).

    Args:
        project_id: The project's UUID (from `list_projects`).
        change_request_id: The change request's UUID (from `list_change_requests`).

    Returns:
        A list of tasks, each including `description`, `assignee_id`,
        `due_date`, and `is_done`.
    """
    pid = _require_uuid(project_id, "project_id")
    cid = _require_uuid(change_request_id, "change_request_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/change-requests/{cid}/tasks")
    return response.json()


@mcp.tool
async def list_change_request_comments(project_id: str, change_request_id: str) -> list[dict]:
    """Lists the discussion thread on a change request.

    Args:
        project_id: The project's UUID (from `list_projects`).
        change_request_id: The change request's UUID (from `list_change_requests`).

    Returns:
        A list of comments, each including `author_id`, `body`, and `created_at`.
    """
    pid = _require_uuid(project_id, "project_id")
    cid = _require_uuid(change_request_id, "change_request_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/change-requests/{cid}/comments")
    return response.json()


@mcp.tool
async def list_requirement_comments(project_id: str, requirement_id: str) -> list[dict]:
    """Lists the discussion thread on a requirement.

    Args:
        project_id: The project's UUID (from `list_projects`).
        requirement_id: The requirement's UUID (from `list_requirements`).

    Returns:
        A list of comments, each including `author_id`, `body`, and `created_at`.
    """
    pid = _require_uuid(project_id, "project_id")
    rid = _require_uuid(requirement_id, "requirement_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/requirements/{rid}/comments")
    return response.json()


@mcp.tool
async def list_notifications(unread_only: bool = False) -> list[dict]:
    """Lists the caller's own in-app notifications (project joins, stage
    transitions, change-request activity, permission grants, and more).

    Args:
        unread_only: Whether to return only unread notifications (all by default).

    Returns:
        A list of notifications, each including `notification_type`,
        `title`, `body`, `read_at` (`None` if unread), and `created_at`.
    """
    response = await _call_backend("GET", "/api/v1/notifications", params={"unread_only": unread_only})
    return response.json()


@mcp.tool
async def list_my_reviews_due() -> list[dict]:
    """Lists requirements assigned to the caller with a scheduled review date that has now passed, across every project they have access to.

    Returns:
        A list of requirements due for review, each including `id`,
        `unique_code`, `name`, `project_id`, and `review_date`.
    """
    response = await _call_backend("GET", "/api/v1/me/reviews/due")
    return response.json()


@mcp.tool
async def list_project_reviews_due(project_id: str) -> list[dict]:
    """Lists every requirement in a project with a scheduled review date that has now passed, regardless of which reviewer it's assigned to.

    Args:
        project_id: The project's UUID (from `list_projects`).

    Returns:
        A list of requirements due for review, each including `id`,
        `unique_code`, `name`, `reviewer_id`, and `review_date`.
    """
    pid = _require_uuid(project_id, "project_id")
    response = await _call_backend("GET", f"/api/v1/projects/{pid}/requirements/reviews/due")
    return response.json()


# --- Write mode (MCP_WRITES_ENABLED) ----------------------------------------
#
# Registered only when the deployment operator has explicitly opted in.
# When write mode is off, these tools don't exist at all — an MCP client
# never even sees them listed, rather than seeing them fail at call time.
# Deliberately narrow: requirement *content* only. Neither tool has a
# `status` parameter, so an approval/completion transition can never be
# requested through this server, regardless of the calling account's own
# role — see this module's docstring and docs/decisions.md's "MCP server
# write mode" entry for the reasoning.

if MCP_WRITES_ENABLED:

    @mcp.tool
    async def create_requirement(
        project_id: str,
        name: str,
        component_id: str,
        category_id: str,
        reasoning: str = "",
        clarification: str = "",
        description: str = "",
        owner_id: str | None = None,
        target_stage_id: str | None = None,
        level: str = "requirement",
        keywords: list[str] | None = None,
        custom_fields: dict | None = None,
        review_date: str | None = None,
        review_lead_days: int | None = None,
        reviewer_id: str | None = None,
    ) -> dict:
        """Creates a new requirement. Always starts in "draft" status —
        there is no way to create one pre-approved, and no tool here can
        approve it afterward either; use the ReqTrackManager UI for that.

        The caller's own account still needs a requirement-editing project
        role (stakeholder, administrator, or manager) for this to succeed —
        same RBAC the UI enforces, nothing looser.

        Args:
            project_id: The project's UUID (from `list_projects`).
            name: The requirement's title.
            component_id: UUID of an existing component in this project.
            category_id: UUID of an existing category nested under that component.
            reasoning: Why this requirement exists.
            clarification: Additional clarifying detail.
            description: Free-form long-form description.
            owner_id: UUID of the user who owns this requirement; defaults
                to the caller's own account if omitted.
            target_stage_id: UUID of the project stage this requirement
                targets; defaults to the project's earliest stage if omitted.
            level: "requirement", "recommended", or "optional".
            keywords: Optional list of search keywords (C-M-01).
            custom_fields: Optional map of this project's custom field ids
                to values — check an existing requirement in this project
                (`get_requirement`) for the shape if this project has any defined.
            review_date: Optional ISO date (YYYY-MM-DD) this requirement is next due for review.
            review_lead_days: Optional override of how many days before
                review_date a reminder notification fires.
            reviewer_id: Optional UUID of the user responsible for that review.

        Returns:
            The newly created requirement's full detail, same shape as `get_requirement`.
        """
        pid = _require_uuid(project_id, "project_id")
        body = {
            "name": name,
            "reasoning": reasoning,
            "clarification": clarification,
            "description": description,
            "component_id": _require_uuid(component_id, "component_id"),
            "category_id": _require_uuid(category_id, "category_id"),
            "owner_id": _require_uuid(owner_id, "owner_id") if owner_id else None,
            "target_stage_id": _require_uuid(target_stage_id, "target_stage_id") if target_stage_id else None,
            "level": level,
            "keywords": keywords or [],
            "custom_fields": custom_fields or {},
            "review_date": review_date,
            "review_lead_days": review_lead_days,
            "reviewer_id": _require_uuid(reviewer_id, "reviewer_id") if reviewer_id else None,
        }
        response = await _call_backend("POST", f"/api/v1/projects/{pid}/requirements", json=body)
        return response.json()

    @mcp.tool
    async def update_requirement(
        project_id: str,
        requirement_id: str,
        name: str | None = None,
        reasoning: str | None = None,
        clarification: str | None = None,
        description: str | None = None,
        component_id: str | None = None,
        category_id: str | None = None,
        owner_id: str | None = None,
        target_stage_id: str | None = None,
        level: str | None = None,
        keywords: list[str] | None = None,
        custom_fields: dict | None = None,
        review_date: str | None = None,
        review_lead_days: int | None = None,
        reviewer_id: str | None = None,
        change_note: str = "",
    ) -> dict:
        """Edits an unlocked requirement's content in place.

        A partial update: this tool fetches the requirement's current
        detail first and only overwrites the fields you actually pass —
        any argument left as `None` keeps its current value unchanged. The
        exception is `keywords`/`custom_fields`, which fully replace the
        current set when given (not merged) — omit them to leave the
        current set untouched.

        This tool has no `status` parameter and can never approve, complete,
        or otherwise transition a requirement's workflow state — see this
        module's docstring for why. It also can't distinguish "clear
        review_date/review_lead_days/reviewer_id entirely" from "I didn't
        mention it" (both look like a missing argument); use the
        ReqTrackManager UI if you need to genuinely blank one of those out.

        Rejected with a clear error if the requirement is locked (status
        "approved" or "completed") — at that point ReqTrackManager requires
        an approved change request instead, and this server has no tool to
        create or decide one; use the UI.

        Args:
            project_id: The project's UUID (from `list_projects`).
            requirement_id: The requirement's UUID (from `list_requirements`).
            name / reasoning / clarification / description: Content fields; omit any you're not changing.
            component_id / category_id: Move the requirement to a different
                component/category; omit to leave it where it is.
            owner_id: Reassign the requirement's owner; omit to leave unchanged.
            target_stage_id: Retarget which project stage this requirement is for; omit to leave unchanged.
            level: "requirement", "recommended", or "optional"; omit to leave unchanged.
            keywords: Replaces the full keyword set if given; omit to leave the current keywords unchanged.
            custom_fields: Replaces the full custom field value map if given; omit to leave unchanged.
            review_date / review_lead_days / reviewer_id: Review scheduling fields; omit any you're not changing.
            change_note: Optional note explaining why this edit was made,
                recorded in the requirement's version history (C-A-09).

        Returns:
            The requirement's new current detail, same shape as `get_requirement`.
        """
        pid = _require_uuid(project_id, "project_id")
        rid = _require_uuid(requirement_id, "requirement_id")
        current = (await _call_backend("GET", f"/api/v1/projects/{pid}/requirements/{rid}")).json()

        body = {
            "name": name if name is not None else current["name"],
            "reasoning": reasoning if reasoning is not None else current["reasoning"],
            "clarification": clarification if clarification is not None else current["clarification"],
            "description": description if description is not None else current["description"],
            "component_id": _require_uuid(component_id, "component_id") if component_id else current["component_id"],
            "category_id": _require_uuid(category_id, "category_id") if category_id else current["category_id"],
            "owner_id": _require_uuid(owner_id, "owner_id") if owner_id else current["owner_id"],
            "target_stage_id": (
                _require_uuid(target_stage_id, "target_stage_id") if target_stage_id else current["target_stage_id"]
            ),
            "level": level if level is not None else current["level"],
            "keywords": keywords if keywords is not None else current["keywords"],
            "custom_fields": custom_fields if custom_fields is not None else current["custom_fields"],
            "change_note": change_note,
            "review_date": review_date if review_date is not None else current["review_date"],
            "review_lead_days": review_lead_days if review_lead_days is not None else current["review_lead_days"],
            "reviewer_id": (
                _require_uuid(reviewer_id, "reviewer_id") if reviewer_id else current["reviewer_id"]
            ),
            # Deliberately no "status" key — see this tool's own docstring
            # and the module docstring: this server never sends a status
            # transition, by construction, regardless of what the caller's
            # account could do directly via the API.
        }
        response = await _call_backend("PUT", f"/api/v1/projects/{pid}/requirements/{rid}", json=body)
        return response.json()


_PAGE_STYLE = """
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           max-width: 34rem; margin: 3rem auto; padding: 0 1.25rem; color: #1a1a2e; }
    h1 { font-size: 1.3rem; }
    p.lead { color: #555; }
    label { display: block; margin-top: 1rem; font-weight: 600; font-size: 0.9rem; }
    input[type=email], input[type=password], input[type=text] {
        width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box;
        border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }
    button { margin-top: 1.25rem; padding: 0.55rem 1.1rem; border: none; border-radius: 4px;
             background: #2b6cb0; color: #fff; font-size: 1rem; cursor: pointer; }
    button:hover { background: #245a94; }
    .error { background: #fdecea; border: 1px solid #f5c2c0; color: #7a1f1a;
              padding: 0.6rem 0.8rem; border-radius: 4px; margin-top: 1rem; font-size: 0.9rem; }
    .token-box { word-break: break-all; background: #f4f4f8; border: 1px solid #ddd;
                 border-radius: 4px; padding: 0.75rem; font-family: ui-monospace, monospace;
                 font-size: 0.85rem; margin-top: 0.5rem; }
    pre { background: #1a1a2e; color: #e6e6f0; padding: 0.9rem; border-radius: 4px;
          overflow-x: auto; font-size: 0.8rem; }
    .hint { color: #666; font-size: 0.85rem; }
"""


def _page(title: str, body: str) -> str:
    """Wraps `body` (already-safe HTML) in a minimal standalone page shell."""
    head = f"<meta charset='utf-8'><title>{html.escape(title)}</title><style>{_PAGE_STYLE}</style>"
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


def _login_form_html(error: str | None = None, sso: dict | None = None) -> str:
    """Renders the credentials form for `GET /login` and for re-display
    after a failed `POST /login`. `error` is always a fixed, non-user-
    supplied message — this function does no escaping of it — and this
    route never echoes the submitted email back into the page, so there's
    nothing else here that needs escaping except values already escaped by
    the caller (an org name/slug from `sso`, sourced from the backend's own
    public login-info lookup, not directly from the request).

    `sso`: the backend's `OrgLoginInfoOut` dict (`name`, `slug`,
    `sso_enabled`, `sso_only`, ...) for the org named in `?org=<slug>`, if
    one was given and found with SSO enabled — adds a "Sign in with SSO"
    button (see `_get_org_login_info`), and hides the native form entirely
    when `sso_only` is set.
    """
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""

    sso_html = ""
    if sso:
        org_name = html.escape(sso["name"])
        org_slug = html.escape(sso["slug"])
        sso_html = f"""
        <button type="button" id="sso-btn" data-org-slug="{org_slug}">Sign in with {org_name} via SSO</button>
        <script>
        document.getElementById('sso-btn').addEventListener('click', function () {{
            var nonce = crypto.randomUUID();
            sessionStorage.setItem('reqtrack_mcp_oidc_nonce', nonce);
            var slug = this.dataset.orgSlug;
            window.location.href = {json.dumps(REQTRACK_PUBLIC_API_URL)} + '/api/v1/auth/oidc/'
                + encodeURIComponent(slug) + '/login?client_nonce=' + encodeURIComponent(nonce) + '&client=mcp';
        }});
        </script>
        """

    native_html = ""
    if not (sso and sso.get("sso_only")):
        divider = '<p class="hint">or sign in with a native account:</p>' if sso else ""
        org_field = f'<input type="hidden" name="org" value="{html.escape(sso["slug"])}">' if sso else ""
        org_hint = "" if sso else (
            '<p class="hint">If your organisation uses SSO, add <code>?org=&lt;your-org-slug&gt;</code> '
            "to this page's URL.</p>"
        )
        native_html = f"""
        {divider}
        <form method="post" action="/login">
            {org_field}
            <label for="email">Email</label>
            <input type="email" id="email" name="email" required autofocus>
            <label for="password">Password</label>
            <input type="password" id="password" name="password" required>
            <button type="submit">Sign in</button>
        </form>
        {org_hint}
        """

    return _page(
        "ReqTrackManager MCP — Sign in",
        f"""
        <h1>ReqTrackManager MCP server</h1>
        <p class="lead">Sign in with your ReqTrackManager account to get an access token
        for this MCP server. Your password is sent once to the ReqTrackManager API to
        authenticate you and is never stored by this page.</p>
        {error_html}
        {sso_html}
        {native_html}
        """,
    )


def _totp_form_html(challenge_token: str, error: str | None = None) -> str:
    """Renders the second-step TOTP code form. `challenge_token` is carried
    as a hidden field rather than server-side session state — this route
    holds no session of any kind, matching the rest of this server's
    stateless design; the token is short-lived and meaningless without a
    correct code, so passing it through the client is not a secrecy
    concern.
    """
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    return _page(
        "ReqTrackManager MCP — Two-factor code",
        f"""
        <h1>Two-factor authentication</h1>
        <p class="lead">Enter the current 6-digit code from your authenticator app.</p>
        {error_html}
        <form method="post" action="/login/2fa">
            <input type="hidden" name="challenge_token" value="{html.escape(challenge_token)}">
            <label for="code">Authentication code</label>
            <input type="text" id="code" name="code" inputmode="numeric" pattern="[0-9]{{6}}"
                   maxlength="6" required autofocus>
            <button type="submit">Verify</button>
        </form>
        """,
    )


def _success_html(token: str, mcp_url: str) -> str:
    """Renders the post-login page: the raw access token plus ready-to-paste
    config snippets for the client setups documented in docs/mcp-server.md.
    `token` is only ever placed in the response *body* (never a URL/query
    string), consistent with this project's established rule that bearer
    tokens must not end up in places that get logged or cached (see the SSO
    login-CSRF fix in docs/decisions.md) — the caller of this route also
    sends `Cache-Control: no-store` for the same reason.
    """
    escaped_token = html.escape(token)
    escaped_url = html.escape(mcp_url)
    claude_snippet = f"claude mcp add --transport http reqtrackmanager {mcp_url} --header \"Authorization: Bearer {token}\""
    vscode_snippet = (
        "{\n"
        '  "servers": {\n'
        '    "reqtrackmanager": {\n'
        '      "type": "http",\n'
        f'      "url": "{mcp_url}",\n'
        '      "headers": { "Authorization": "Bearer ' + token + '" }\n'
        "    }\n"
        "  }\n"
        "}"
    )
    return _page(
        "ReqTrackManager MCP — Signed in",
        f"""
        <h1>Signed in</h1>
        <p class="lead">This token is a normal ReqTrackManager access token — it expires
        the same way a browser session would (see docs/mcp-server.md) and grants exactly
        what your account can already see, nothing more. Copy it into your MCP client's
        config now; this page won't show it again.</p>
        <label>Access token</label>
        <div class="token-box" id="token">{escaped_token}</div>
        <label>MCP endpoint</label>
        <div class="token-box">{escaped_url}</div>
        <label>Claude Code</label>
        <pre>{html.escape(claude_snippet)}</pre>
        <label>VS Code (.vscode/mcp.json)</label>
        <pre>{html.escape(vscode_snippet)}</pre>
        <p class="hint">Generic HTTP clients (e.g. Copilot Studio): connect to the MCP
        endpoint above with header <code>Authorization: Bearer &lt;token&gt;</code>. Full
        details in docs/mcp-server.md.</p>
        """,
    )


_OIDC_COMPLETE_BODY = """
<div id="content">
    <h1>ReqTrackManager MCP server</h1>
    <p class="lead">Completing sign-in…</p>
</div>
<script>
(function () {
    function el(tag, attrs, text) {
        var e = document.createElement(tag);
        if (attrs) { for (var k in attrs) { e.setAttribute(k, attrs[k]); } }
        if (text !== undefined) { e.textContent = text; }
        return e;
    }
    var content = document.getElementById('content');
    function showError(message) {
        content.innerHTML = '';
        content.appendChild(el('h1', null, 'ReqTrackManager MCP server'));
        content.appendChild(el('div', {'class': 'error'}, message));
        var p = el('p', {'class': 'hint'});
        p.appendChild(document.createTextNode('Return to '));
        p.appendChild(el('a', {'href': '/login'}, '/login'));
        p.appendChild(document.createTextNode(' to try again.'));
        content.appendChild(p);
    }

    // The token (success case) travels only in the URL *fragment* —
    // matching the backend's own reasoning in routers/auth_oidc.py: never
    // sent to any server, never logged. The denial case travels in the
    // query string instead since it carries no secret, mirroring
    // OidcCompletePage.tsx's identical handling of both cases.
    var fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    var query = new URLSearchParams(window.location.search);
    var expectedNonce = sessionStorage.getItem('reqtrack_mcp_oidc_nonce');
    sessionStorage.removeItem('reqtrack_mcp_oidc_nonce'); // single-use regardless of outcome

    if (query.get('error') === 'not_provisioned') {
        if (!expectedNonce || query.get('client_nonce') !== expectedNonce) {
            showError('Sign-in could not be verified. Please try again.');
        } else {
            showError(query.get('message') || 'Your organisation has not provisioned you access.');
        }
        return;
    }

    var token = fragment.get('token');
    var nonce = fragment.get('client_nonce');
    if (!token || !expectedNonce || nonce !== expectedNonce) {
        // Covers both a missing/expired nonce and an outright mismatch —
        // this is the same login-CSRF check OidcCompletePage.tsx performs
        // client-side (see its docstring for the full threat model): a
        // bare token in the URL proves nothing about who is viewing it,
        // only a nonce this same browser generated before starting the
        // flow does.
        showError('Sign-in could not be verified. Please try again.');
        return;
    }
    // Clear the fragment immediately so the token never lingers in browser
    // history/back-forward cache as a visible URL.
    window.history.replaceState(null, '', window.location.pathname + window.location.search);

    var mcpUrl = window.location.origin + '/mcp';
    content.innerHTML = '';
    content.appendChild(el('h1', null, 'Signed in'));
    content.appendChild(el('p', {'class': 'lead'},
        "This token is a normal ReqTrackManager access token — copy it into your MCP " +
        "client's config now; this page won't show it again."));
    content.appendChild(el('label', null, 'Access token'));
    content.appendChild(el('div', {'class': 'token-box'}, token));
    content.appendChild(el('label', null, 'MCP endpoint'));
    content.appendChild(el('div', {'class': 'token-box'}, mcpUrl));
    content.appendChild(el('label', null, 'Claude Code'));
    content.appendChild(el('pre', null,
        'claude mcp add --transport http reqtrackmanager ' + mcpUrl +
        ' --header "Authorization: Bearer ' + token + '"'));
    content.appendChild(el('label', null, 'VS Code (.vscode/mcp.json)'));
    content.appendChild(el('pre', null, JSON.stringify({
        servers: { reqtrackmanager: { type: 'http', url: mcpUrl, headers: { Authorization: 'Bearer ' + token } } },
    }, null, 2)));
})();
</script>
"""


def _oidc_complete_page_html() -> str:
    """Landing page for the SSO flow started from this server's own
    `/login` page (the `client=mcp` case in `routers/auth_oidc.py`).
    Entirely client-rendered: the token only ever exists in the URL
    *fragment* the browser navigated here with, which this server's own
    handler below never even sees (fragments aren't sent to any server) —
    the inline script reads it directly out of `location.hash`, checks the
    anti-replay nonce the SSO button stashed in `sessionStorage` before
    starting the flow, and renders the result without any further round
    trip to this server. See `_OIDC_COMPLETE_BODY`'s comments for the full
    nonce-check rationale (identical to the frontend's own
    `OidcCompletePage.tsx`).
    """
    return _page("ReqTrackManager MCP — Completing sign-in", _OIDC_COMPLETE_BODY)


async def _get_org_login_info(slug: str) -> dict | None:
    """Looks up an organisation's public, unauthenticated login-page info
    by slug via the backend's `GET /api/v1/orgs/by-slug/{slug}/login-info`
    — the same endpoint the frontend's own org-branded login page uses.
    No token is needed or sent; this data (name, slug, whether SSO is
    enabled/required) is deliberately public.

    Returns:
        The `OrgLoginInfoOut` dict, or `None` if no org has this slug.
    """
    # URL-encoded so a crafted `?org=` value (e.g. containing `/`, `..`, or
    # `?`) can never reshape which path or query string this request
    # actually sends — a hardening-review finding: an unencoded slug could
    # otherwise make httpx's own dot-segment normalization escape the
    # intended `/orgs/by-slug/` prefix, or split the URL at an embedded `?`
    # and land the hardcoded `/login-info` suffix in the query string
    # instead of the path, reaching a different backend endpoint than
    # intended (confirmed low-impact today: this call is always anonymous
    # and every unauthenticated GET on the backend is already meant to be
    # public — but encoding correctly here means that stops being an
    # invariant this code silently depends on).
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        response = await client.get(f"{REQTRACK_API_URL}/api/v1/orgs/by-slug/{quote(slug, safe='')}/login-info")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _mcp_url_for(request: Request) -> str:
    """Builds this server's own MCP endpoint URL from the incoming request's
    own scheme/host, so the displayed URL is correct whether reached via
    localhost:8100 directly or through a reverse proxy on a public
    hostname — the exact address the user's browser just used to load this
    page is by definition a reachable one.
    """
    return f"{str(request.base_url).rstrip('/')}/mcp"


_NO_STORE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate"}


async def _resolve_sso(org_slug: str | None) -> tuple[dict | None, str | None]:
    """Shared by `login_page` and `login_submit`: resolves an `?org=<slug>`
    value to `(sso_info, error)` — `sso_info` is `None` and `error` is set
    if the slug doesn't exist or the org doesn't have SSO enabled;
    otherwise `sso_info` is the login-info dict and `error` is `None`.
    """
    if not org_slug:
        return None, None
    try:
        info = await _get_org_login_info(org_slug)
    except httpx.HTTPError:
        return None, "Could not check this organisation's sign-in settings. Please try again shortly."
    if info is None:
        return None, f"No organisation found for '{html.escape(org_slug)}'."
    if not info.get("sso_enabled"):
        return None, f"{html.escape(info['name'])} does not have SSO enabled."
    return info, None


@mcp.custom_route("/login", methods=["GET"])
async def login_page(request: Request) -> HTMLResponse:
    """Serves the credentials form, optionally with a "Sign in with SSO"
    button when `?org=<slug>` names an org with SSO enabled (mirrors the
    frontend's own `/login/{slug}` org-branded page). See `_login_form_html`
    and the module docstring's pass-through-auth design note — this page
    exists only to save a user from hand-crafting a `curl` call to the
    backend's own `/api/v1/auth/login` (or driving its OIDC redirect
    manually); it introduces no new authentication mechanism of its own."""
    sso, error = await _resolve_sso(request.query_params.get("org"))
    return HTMLResponse(_login_form_html(error, sso), headers=_NO_STORE_HEADERS)


@mcp.custom_route("/login/oidc/complete", methods=["GET"])
async def login_oidc_complete(request: Request) -> HTMLResponse:
    """Landing page for the SSO login flow — see `_oidc_complete_page_html`."""
    return HTMLResponse(_oidc_complete_page_html(), headers=_NO_STORE_HEADERS)


@mcp.custom_route("/login", methods=["POST"])
async def login_submit(request: Request) -> HTMLResponse:
    """Relays submitted credentials to the backend's own `/api/v1/auth/login`
    and renders the result: a token (`_success_html`), a 2FA challenge
    (`_totp_form_html`), or a generic invalid-credentials error
    (`_login_form_html`).

    Security notes:
    - The submitted password lives only in this function's local scope for
      the duration of this one relay call — it is never logged, written to
      disk, or included in any exception message.
    - The submitted email is never echoed back into any HTML response (the
      re-shown form on failure is a fresh, empty form) — this route
      performs no manual escaping of it for that reason, by construction
      rather than by care.
    - All responses carry `Cache-Control: no-store` since a successful one
      contains a live secret.
    - No CSRF protection: this route has no ambient session/cookie
      authority to forge (identical reasoning to why the native frontend's
      own login form has none) — a forged cross-site POST here can only
      ever act as the attacker's own browser, using the attacker's own
      submitted credentials.
    """
    form = await request.form()
    email = form.get("email", "")
    password = form.get("password", "")
    org_slug = form.get("org") or None
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(f"{REQTRACK_API_URL}/api/v1/auth/login", json={"email": email, "password": password})
    except httpx.HTTPError:
        sso, _ = await _resolve_sso(org_slug)
        return HTMLResponse(
            _login_form_html("Could not reach the ReqTrackManager backend. Please try again shortly.", sso),
            headers=_NO_STORE_HEADERS,
        )

    if response.status_code == 401:
        sso, _ = await _resolve_sso(org_slug)
        return HTMLResponse(_login_form_html("Invalid email or password.", sso), headers=_NO_STORE_HEADERS)
    if response.is_error:
        sso, _ = await _resolve_sso(org_slug)
        return HTMLResponse(
            _login_form_html("Sign-in failed unexpectedly. Please try again.", sso),
            headers=_NO_STORE_HEADERS,
        )

    body = response.json()
    if body.get("requires_2fa"):
        return HTMLResponse(_totp_form_html(body["challenge_token"]), headers=_NO_STORE_HEADERS)
    return HTMLResponse(_success_html(body["access_token"], _mcp_url_for(request)), headers=_NO_STORE_HEADERS)


@mcp.custom_route("/login/2fa", methods=["POST"])
async def login_2fa_submit(request: Request) -> HTMLResponse:
    """Second step of the login flow: exchanges a challenge token + TOTP
    code for a real access token via the backend's `/api/v1/auth/2fa/verify`.
    Same security notes as `login_submit` apply (no logging, no caching,
    nothing user-supplied echoed back unescaped)."""
    form = await request.form()
    challenge_token = form.get("challenge_token", "")
    code = form.get("code", "")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(
                f"{REQTRACK_API_URL}/api/v1/auth/2fa/verify",
                json={"challenge_token": challenge_token, "code": code},
            )
    except httpx.HTTPError:
        return HTMLResponse(
            _totp_form_html(challenge_token, "Could not reach the ReqTrackManager backend. Please try again shortly."),
            headers=_NO_STORE_HEADERS,
        )

    if response.status_code == 401:
        return HTMLResponse(_totp_form_html(challenge_token, "Invalid or expired code."), headers=_NO_STORE_HEADERS)
    if response.is_error:
        return HTMLResponse(
            _totp_form_html(challenge_token, "Verification failed unexpectedly. Please try again."),
            headers=_NO_STORE_HEADERS,
        )

    body = response.json()
    return HTMLResponse(_success_html(body["access_token"], _mcp_url_for(request)), headers=_NO_STORE_HEADERS)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    """Plain liveness check for the container orchestrator (same convention
    as the backend's and frontend's own `/health` endpoints) — deliberately
    doesn't call the backend itself, so this server's own health doesn't
    flap because of unrelated backend downtime."""
    return PlainTextResponse("ok")


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8100)
