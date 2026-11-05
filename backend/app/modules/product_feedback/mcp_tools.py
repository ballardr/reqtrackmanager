"""
Module: modules.product_feedback.mcp_tools

The Product Feedback module's MCP tool declarations (`docs/modules.md` section 6). Each tool proxies an existing
router endpoint, so the endpoint's own authorisation, guards and audit logging apply unchanged; declaring a tool
grants nothing.

Responsibilities:
- `build_mcp_tools`: read tools (requests, versions, comments, demand, merges, close-the-loop, settings) and write tools
  (create, update, lifecycle move, comment, merge, unmerge, record requesters as told, scoring scheme) for a project,
  plus list, create, scoring scheme and move-into-a-project for the organisation's inbox.

Design decisions:
- Write-enabled (**Decided by: User**, as for every module's MCP tools). Writes still need `MCP_WRITES_ENABLED`
  and the caller's own role.
- No tool decides on a person's behalf beyond what the endpoint allows; there is no delete tool and no tool for
  changing the project's submission policy (a project administrator's setting).

Dependencies: `modules.registry` (`McpToolDefinition`).
"""

from __future__ import annotations

from app.modules.product_feedback.reports import REPORT_DEFINITIONS
from app.modules.product_feedback.service import PRODUCT_FEEDBACK_MODULE_KEY
from app.modules.registry import McpToolDefinition
from app.services.report_framework import report_mcp_tools

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
    _body(
        "levels", "object",
        'Scoring levels by axis key, e.g. {"impact": <level id>, "effort": null}: the ids come from '
        "get_request_scoring_scheme; an axis set to null is cleared, one not mentioned is kept. Axes: reach, impact, "
        "confidence, ease (higher is easier), effort (a higher level lowers a RICE score) and demand (derived from "
        "the requesters unless a level is chosen), plus any axis (key c_...) the organisation or project defined: the "
        "scheme lists the ones this project can use.",
    ),
]
_CREATE_REFERENCES = _body(
    "references", "array",
    'External references to items in outside tools, each {"system_id": uuid (list_external_systems), "key": '
    '"PROJ-123", "url": "https://...", "role": "origin" | "delivery"}; a key or a url is needed. Later changes use '
    "add_request_reference, update_request_reference and remove_request_reference.",
)
_REFERENCE_ID = {"name": "reference_id", "type": "uuid", "required": True, "in": "path", "description": "The external reference."}
_REFERENCE_FIELDS = [
    _body("key", "string", "The item's key in that system, e.g. PROJ-123."),
    _body("url", "string", "Link to the item (an absolute http or https URL); null clears it on update."),
    _body("role", "string", "origin (the request came from this item) or delivery (it is built there); default delivery."),
]
_SCORING_MODEL = _query(
    "scoring_model", "string",
    "Score under these models, comma-separated, the first being the primary: ice, rice, rice_demand or a model "
    "(key m_...) the organisation or project defined (default: the project's enabled models).",
)
_LIST_FILTERS = [
    _query("include_archived", "boolean", "Also list archived requests."),
    _query("status", "string", "Only this status: new, under_review, accepted, delivered, declined or duplicate."),
    _query("open_only", "boolean", "Only new, under review or accepted requests."),
    _query("search", "string", "Case-insensitive match on code, title or description."),
    _query(
        "scored", "string",
        "unscored: only requests missing a level on the first model's manual axes (the ones still to score); "
        "scored: only the fully scored.",
    ),
    _query("missing_axis", "string", "Only requests with no level on this axis (reach, impact, confidence, ease, effort)."),
]


def build_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """The module's MCP tools, read tools first."""
    return (
        McpToolDefinition(
            name="list_requests", description="Lists a project's enhancement requests with status, owner and external references.",
            method="GET", path_template=_REQUESTS, params=[_PROJECT_ID, *_LIST_FILTERS, _SCORING_MODEL],
        ),
        McpToolDefinition(
            name="get_request",
            description=(
                "Fetches one enhancement request with its current content, legal next statuses, scoring levels and "
                "derived ICE or RICE score."
            ),
            method="GET", path_template=_REQUEST, params=[_PROJECT_ID, _REQUEST_ID, _SCORING_MODEL],
        ),
        McpToolDefinition(
            name="get_request_scoring_scheme",
            description=(
                "Reads the Reach, Impact, Confidence and Effort levels (ids and weights), the ICE and RICE models and "
                "their rating bands that apply to the project. Use it to find the level ids a request takes."
            ),
            method="GET", path_template=f"{_PREFIX}/scoring-scheme", params=[_PROJECT_ID],
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
            name="get_request_close_the_loop",
            description=(
                "What became of a request and who has been told: each requester with whether they were told the "
                "outcome, the Pain Points it addresses, the Requirements that realise it, and suggest_delivered (an "
                "accepted request whose requirements are all complete). Link Pain Points ('Addresses') and "
                "Requirements ('Realised by') with the core link tools."
            ),
            method="GET", path_template=f"{_REQUEST}/close-the-loop", params=[_PROJECT_ID, _REQUEST_ID],
        ),
        McpToolDefinition(
            name="list_open_loops",
            description=(
                "Lists the project's delivered or declined requests that still have requesters who have not been told "
                "the outcome, with those requesters."
            ),
            method="GET", path_template=f"{_PREFIX}/close-the-loop", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="list_external_systems",
            description=(
                "Lists the project's effective external systems (Jira, ServiceNow, ...): the ids a request's "
                "references take as system_id."
            ),
            method="GET", path_template=f"{_PREFIX}/external-systems", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="list_request_channels",
            description=(
                "Lists the project's effective request channels (Support ticket, Call, Email, ...): the ids "
                "set_requester_channel takes as channel_id."
            ),
            method="GET", path_template=f"{_PREFIX}/request-channels", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="list_request_references",
            description="Lists a request's references to items in outside tools, with each one's system and role.",
            method="GET", path_template=f"{_REQUEST}/references", params=[_PROJECT_ID, _REQUEST_ID],
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
            params=[_PROJECT_ID, _body("title", "string", "Short name of the request.", required=True), *_REQUEST_FIELDS,
                    _CREATE_REFERENCES],
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
            name="mark_requesters_informed",
            description=(
                "Records that requesters were told the outcome of a delivered or declined request (informed=false "
                "withdraws the record). Nothing is sent to anyone: tell them first, then record it. Needs the "
                "Feedback Triager role; refused (409) unless the request is delivered or declined and every party is "
                "one of its requesters (get_request_demand lists them)."
            ),
            method="PUT", path_template=f"{_REQUEST}/informed",
            params=[
                _PROJECT_ID, _REQUEST_ID,
                _body("parties", "array", 'Requesters, each {"artefact_type": "stakeholder" | "persona", "id": uuid}.', required=True),
                _body("informed", "boolean", "True (default) to record, false to withdraw."),
                _body("note", "string", "How or by whom they were told."),
            ],
        ),
        McpToolDefinition(
            name="add_request_reference",
            description=(
                "Adds a reference from a request to an item in an outside tool (a Jira epic, a ServiceNow ticket). Not "
                "a new version of the request. Needs the Feedback Triager role."
            ),
            method="POST", path_template=f"{_REQUEST}/references",
            params=[_PROJECT_ID, _REQUEST_ID,
                    _body("system_id", "uuid", "The system (list_external_systems).", required=True), *_REFERENCE_FIELDS],
        ),
        McpToolDefinition(
            name="update_request_reference",
            description="Changes a reference; only the fields supplied change. Needs the Feedback Triager role.",
            method="PATCH", path_template=f"{_REQUEST}/references/{{reference_id}}",
            params=[_PROJECT_ID, _REQUEST_ID, _REFERENCE_ID, _body("system_id", "uuid", "The system (list_external_systems)."),
                    *_REFERENCE_FIELDS],
        ),
        McpToolDefinition(
            name="remove_request_reference", description="Removes a reference. Needs the Feedback Triager role.",
            method="DELETE", path_template=f"{_REQUEST}/references/{{reference_id}}",
            params=[_PROJECT_ID, _REQUEST_ID, _REFERENCE_ID],
        ),
        McpToolDefinition(
            name="set_requester_channel",
            description=(
                "Records how requesters asked (their channel), or clears it with channel_id null. A requester reached "
                "through an Engagement is shown as an Engagement and needs none. Needs the Feedback Triager role; "
                "refused (409) unless every party is a current requester (get_request_demand lists them)."
            ),
            method="PUT", path_template=f"{_REQUEST}/requester-channel",
            params=[
                _PROJECT_ID, _REQUEST_ID,
                _body("parties", "array", 'Requesters, each {"artefact_type": "stakeholder" | "persona", "id": uuid}.', required=True),
                _body("channel_id", "uuid", "The channel (list_request_channels); null clears it."),
            ],
        ),
        McpToolDefinition(
            name="add_request_comment", description="Adds a comment to a request's discussion.", method="POST",
            path_template=f"{_REQUEST}/comments",
            params=[_PROJECT_ID, _REQUEST_ID, _body("body", "string", "The comment text.", required=True)],
        ),
        McpToolDefinition(
            name="list_inbox_requests",
            description="Lists the organisation's inbox requests (answers 404 when the organisation switched the inbox off).",
            method="GET", path_template=f"{_ORG_PREFIX}/requests", params=[_ORG_ID, *_LIST_FILTERS, _SCORING_MODEL],
        ),
        McpToolDefinition(
            name="get_inbox_scoring_scheme",
            description="Reads the request scoring levels and models that apply to the organisation's inbox.",
            method="GET", path_template=f"{_ORG_PREFIX}/scoring-scheme", params=[_ORG_ID],
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
            params=[_ORG_ID, _body("title", "string", "Short name of the request.", required=True), *_REQUEST_FIELDS,
                    _CREATE_REFERENCES],
        ),
        McpToolDefinition(
            name="list_inbox_external_systems",
            description="Lists the organisation's external systems (Jira, ServiceNow, ...) an inbox request's references can use.",
            method="GET", path_template=f"{_ORG_PREFIX}/external-systems", params=[_ORG_ID],
        ),
    ) + report_mcp_tools(REPORT_DEFINITIONS, project_router_prefix=_PREFIX)
