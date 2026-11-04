"""
Module: modules.product_feedback.mcp_tools

The Product Feedback module's MCP tool declarations (`docs/modules.md` section 6). Each tool proxies an existing
router endpoint, so the endpoint's own authorisation, guards and audit logging apply unchanged; declaring a tool
grants nothing.

Responsibilities:
- `build_mcp_tools`: read tools (requests, versions, comments, demand, merges, settings) and write tools (create,
  update, lifecycle move, comment, merge, unmerge) for a project, plus list, create and move-into-a-project for the organisation's inbox.

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
            name="get_request_demand",
            description=(
                "Who asked for a request: distinct requesters (Stakeholders and Personas, including those reached "
                "through linked Engagements and requests merged into it), the engagements it was raised in, the "
                "requester count and weighted demand. Add requesters with the core link tools (link type 'Requested by')."
            ),
            method="GET", path_template=f"{_REQUEST}/demand", params=[_PROJECT_ID, _REQUEST_ID],
        ),
        McpToolDefinition(
            name="list_request_merges",
            description="Lists the merges a request took part in (as canonical or duplicate), active and ended.",
            method="GET", path_template=f"{_REQUEST}/merges", params=[_PROJECT_ID, _REQUEST_ID],
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
            name="merge_request",
            description=(
                "Marks a request as a duplicate of another request of the same project: its requesters then count "
                "toward the canonical request's demand. Reversible with unmerge_request. Needs the Feedback Triager "
                "role; refused (409) unless the duplicate is new, under review or accepted and neither is archived."
            ),
            method="POST", path_template=f"{_REQUEST}/merge",
            params=[_PROJECT_ID, _REQUEST_ID, _body("canonical_id", "uuid", "The request that stays.", required=True),
                    _body("note", "string", "Why they are the same.")],
        ),
        McpToolDefinition(
            name="unmerge_request",
            description="Reverses a merge: the duplicate returns to the status it had. Needs the Feedback Triager role.",
            method="POST", path_template=f"{_REQUEST}/unmerge", params=[_PROJECT_ID, _REQUEST_ID],
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
            name="move_inbox_request_to_project",
            description=(
                "Triages an inbox request into a project of the organisation: it keeps its id, status, comments and "
                "history, takes the project's next ENH code and its tags and files become the project's. Needs the "
                "Organisation Feedback Triager role; refused (409) if the request has links."
            ),
            method="POST", path_template=f"{_ORG_PREFIX}/requests/{{request_id}}/move-to-project",
            params=[_ORG_ID, _REQUEST_ID, _body("project_id", "uuid", "The project to move it into.", required=True)],
        ),
        McpToolDefinition(
            name="create_inbox_request",
            description="Submits an enhancement request to the organisation's inbox. Any organisation member may.",
            method="POST", path_template=f"{_ORG_PREFIX}/requests",
            params=[_ORG_ID, _body("title", "string", "Short name of the request.", required=True), *_REQUEST_FIELDS],
        ),
    )
