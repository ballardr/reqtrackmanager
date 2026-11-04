"""
Module: modules.product_feedback.mcp_tools

The Product Feedback module's MCP tool declarations (`docs/modules.md` section 6). Each tool proxies an existing
router endpoint, so the endpoint's own authorisation, guards and audit logging apply unchanged; declaring a tool
grants nothing.

Responsibilities:
- `build_mcp_tools`: read tools (requests, versions, comments, settings) and write tools (create, update,
  lifecycle move, comment) for a project, plus list and create for the organisation's inbox.

Design decisions:
- Write-enabled (**Decided by: User**, as for every module's MCP tools). Writes still need `MCP_WRITES_ENABLED`
  and the caller's own role.
- No tool decides on a person's behalf beyond what the endpoint allows; there is no delete tool and no tool for
  changing the project's submission policy (a project administrator's setting).

Dependencies: `modules.registry` (`McpToolDefinition`).
"""

from __future__ import annotations

from app.modules.product_feedback.service import PRODUCT_FEEDBACK_MODULE_KEY
from app.modules.registry import McpToolDefinition

_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{PRODUCT_FEEDBACK_MODULE_KEY}"
_ORG_PREFIX = f"/api/v1/orgs/{{organization_id}}/modules/{PRODUCT_FEEDBACK_MODULE_KEY}"
_REQUESTS = f"{_PREFIX}/requests"
_REQUEST = f"{_REQUESTS}/{{request_id}}"

_PROJECT_ID = {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project that owns the request."}
_ORG_ID = {"name": "organization_id", "type": "uuid", "required": True, "in": "path", "description": "The organisation whose inbox it is."}
_REQUEST_ID = {"name": "request_id", "type": "uuid", "required": True, "in": "path", "description": "The enhancement request."}


def _body(name: str, type_: str, description: str, *, required: bool = False) -> dict:
    return {"name": name, "type": type_, "required": required, "in": "body", "description": description}


def _query(name: str, type_: str, description: str) -> dict:
    return {"name": name, "type": type_, "required": False, "in": "query", "description": description}


_REQUEST_FIELDS = [
    _body("description", "string", "The proposed solution, in the requester's terms."),
    _body("owner", "object", 'Who looks after it: {"type": "user" | "org_group" | "project_group", "id": uuid}; null clears it.'),
    _body("external_ref_url", "string", "URL of the same item in a delivery tool (e.g. a Jira issue); null clears it."),
    _body("external_ref_key", "string", "Key of that item (e.g. PROJ-123); null clears it."),
]
_LIST_FILTERS = [
    _query("include_archived", "boolean", "Also list archived requests."),
    _query("status", "string", "Only this status: new, under_review, accepted, delivered, declined or duplicate."),
    _query("open_only", "boolean", "Only new, under review or accepted requests."),
    _query("search", "string", "Case-insensitive match on code, title or description."),
]


def build_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """The module's MCP tools, read tools first."""
    return (
        McpToolDefinition(
            name="list_requests", description="Lists a project's enhancement requests with status, owner and external reference.",
            method="GET", path_template=_REQUESTS, params=[_PROJECT_ID, *_LIST_FILTERS],
        ),
        McpToolDefinition(
            name="get_request",
            description="Fetches one enhancement request with its current content and legal next statuses.",
            method="GET", path_template=_REQUEST, params=[_PROJECT_ID, _REQUEST_ID],
        ),
        McpToolDefinition(
            name="list_request_versions", description="Lists a request's full version history, oldest first.",
            method="GET", path_template=f"{_REQUEST}/versions", params=[_PROJECT_ID, _REQUEST_ID],
        ),
        McpToolDefinition(
            name="list_request_comments", description="Lists the comments on a request, oldest first.",
            method="GET", path_template=f"{_REQUEST}/comments", params=[_PROJECT_ID, _REQUEST_ID],
        ),
        McpToolDefinition(
            name="get_feedback_settings",
            description="Reads who may submit requests in the project (any member, or triagers only).",
            method="GET", path_template=f"{_PREFIX}/settings", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="create_request",
            description=(
                "Submits an enhancement request in the New status. Any project member may unless the project "
                "restricted submission to triagers; only the title is required."
            ),
            method="POST", path_template=_REQUESTS,
            params=[_PROJECT_ID, _body("title", "string", "Short name of the request.", required=True), *_REQUEST_FIELDS],
        ),
        McpToolDefinition(
            name="update_request",
            description="Updates a request as a new version; only the fields supplied change. Needs the Feedback Triager role.",
            method="PUT", path_template=_REQUEST,
            params=[_PROJECT_ID, _REQUEST_ID, _body("title", "string", "Short name of the request."), *_REQUEST_FIELDS,
                    _body("change_note", "string", "Reason for the change.")],
        ),
        McpToolDefinition(
            name="transition_request",
            description=(
                "Moves a request along its lifecycle (get_request lists allowed_next_statuses). Declining needs a "
                "comment, stored as the decline reason. Needs the Feedback Triager role."
            ),
            method="POST", path_template=f"{_REQUEST}/transition",
            params=[_PROJECT_ID, _REQUEST_ID, _body("status", "string", "The status to move to.", required=True),
                    _body("comment", "string", "Why; the decline reason when declining.")],
        ),
        McpToolDefinition(
            name="add_request_comment", description="Adds a comment to a request's discussion.", method="POST",
            path_template=f"{_REQUEST}/comments",
            params=[_PROJECT_ID, _REQUEST_ID, _body("body", "string", "The comment text.", required=True)],
        ),
        McpToolDefinition(
            name="list_inbox_requests",
            description="Lists the organisation's inbox requests (answers 404 when the organisation switched the inbox off).",
            method="GET", path_template=f"{_ORG_PREFIX}/requests", params=[_ORG_ID, *_LIST_FILTERS],
        ),
        McpToolDefinition(
            name="create_inbox_request",
            description="Submits an enhancement request to the organisation's inbox. Any organisation member may.",
            method="POST", path_template=f"{_ORG_PREFIX}/requests",
            params=[_ORG_ID, _body("title", "string", "Short name of the request.", required=True), *_REQUEST_FIELDS],
        ),
    )
