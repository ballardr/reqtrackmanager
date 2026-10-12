"""
Module: modules.risk_management.mcp_tools

The Risk Management module's MCP tool declarations (docs/plans/module-03-risk-
management-plan.md Phase 4; `docs/modules.md` section 6). Each tool proxies an
existing project-router endpoint, so the endpoint's own authorisation, guards
and audit logging apply unchanged; declaring a tool grants nothing.

Responsibilities:
- `build_mcp_tools`: read tools (risks, versions, treatments, reviews, comments,
  types, the scoring scheme) and write tools (create, update, lifecycle move,
  treatment verdict, review, comment), then the read-only `get_<slug>_report` tools
  the report framework generates from `reports.REPORT_DEFINITIONS`.

Design decisions:
- Write-enabled, per the plan's 2026-09-22 instruction (Decided by: User). Writes
  still need `MCP_WRITES_ENABLED` and the caller's own role.
- Moving a risk to `accepted` goes through the same `transition_risk` tool: the
  endpoint applies the Risk Acceptor role and the org+project AI-approval gate
  itself, so no separate tool or special casing is needed here.
- There is no delete tool; archiving is a UI action. Relationships are made with
  the core link tools, since the generic link endpoints are not under this
  module's prefix.
"""

from __future__ import annotations

from app.modules.registry import McpToolDefinition
from app.modules.risk_management.reports import REPORT_DEFINITIONS
from app.modules.risk_management.service import RISK_MODULE_KEY
from app.services.report_framework import report_mcp_tools

_PREFIX = f"/api/v1/projects/{{project_id}}/modules/{RISK_MODULE_KEY}"
_RISKS = f"{_PREFIX}/risks"
_RISK = f"{_RISKS}/{{risk_id}}"

_PROJECT_ID = {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": "The project that owns the Risk."}
_RISK_ID = {"name": "risk_id", "type": "uuid", "required": True, "in": "path", "description": "The Risk."}


def _body(name: str, type_: str, description: str, *, required: bool = False) -> dict:
    return {"name": name, "type": type_, "required": required, "in": "body", "description": description}


def _query(name: str, type_: str, description: str) -> dict:
    return {"name": name, "type": type_, "required": False, "in": "query", "description": description}


_LEVELS = "Level id from the `risk` scoring scheme (read `get_risk_scoring_scheme`); null clears it."

_RISK_FIELDS = [
    _body("statement", "string", "The risk statement, e.g. 'If X happens then Y'."),
    _body("cause", "string", "What gives rise to the risk."),
    _body("risk_event", "string", "The event that may occur."),
    _body("consequence", "string", "What follows if it occurs."),
    _body("risk_type_id", "uuid", "An effective Risk type id (`list_risk_types`)."),
    _body("treatment_strategy", "string", "mitigate, transfer, avoid or accept."),
    _body("acceptance_criteria", "string", "What would make the residual risk acceptable."),
    _body("inherent_likelihood_level_id", "uuid", f"Inherent Likelihood. {_LEVELS}"),
    _body("inherent_consequence_level_id", "uuid", f"Inherent Consequence. {_LEVELS}"),
    _body("inherent_detectability_level_id", "uuid", f"Inherent Detectability. {_LEVELS}"),
    _body("residual_likelihood_level_id", "uuid", f"Residual Likelihood. {_LEVELS}"),
    _body("residual_consequence_level_id", "uuid", f"Residual Consequence. {_LEVELS}"),
    _body("residual_detectability_level_id", "uuid", f"Residual Detectability. {_LEVELS}"),
    _body(
        "owner", "object",
        'Who owns the risk: {"type": "user" | "org_group" | "project_group", "id": uuid}; null clears it.',
    ),
    _body("review_date", "string", "Date (YYYY-MM-DD) the risk is next due for review; null clears it."),
]


def build_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """The module's MCP tools, read tools first."""
    return (
        McpToolDefinition(
            name="list_risks",
            description=(
                "Lists a project's Risks with status, derived inherent and residual ratings, owner, review date and "
                "whether each is effectively treated."
            ),
            method="GET", path_template=_RISKS,
            params=[
                _PROJECT_ID,
                _query("include_archived", "boolean", "Also list archived risks."),
                _query("effectively_treated", "boolean", "false lists risks with no effective treatment yet; true the opposite."),
                _query("review_overdue", "boolean", "true lists risks whose scheduled review date has passed."),
            ],
        ),
        McpToolDefinition(
            name="get_risk", description="Fetches one Risk with its current content, ratings and legal next statuses.",
            method="GET", path_template=_RISK, params=[_PROJECT_ID, _RISK_ID],
        ),
        McpToolDefinition(
            name="list_risk_versions", description="Lists a Risk's full version history, oldest first.",
            method="GET", path_template=f"{_RISK}/versions", params=[_PROJECT_ID, _RISK_ID],
        ),
        McpToolDefinition(
            name="list_risk_treatments",
            description=(
                "Lists the requirements, designs and actions that mitigate or treat a Risk, each with its verdict "
                "(proposed, effective, ineffective or needs_reassessment) and why a verdict needs reassessment."
            ),
            method="GET", path_template=f"{_RISK}/treatments", params=[_PROJECT_ID, _RISK_ID],
        ),
        McpToolDefinition(
            name="list_risk_reviews",
            description="Lists a Risk's recorded reviews, newest first, each with the ratings it was made against.",
            method="GET", path_template=f"{_RISK}/reviews", params=[_PROJECT_ID, _RISK_ID],
        ),
        McpToolDefinition(
            name="get_risk_review", description="Fetches one recorded review of a Risk.", method="GET",
            path_template=f"{_RISK}/reviews/{{review_id}}",
            params=[_PROJECT_ID, _RISK_ID,
                    {"name": "review_id", "type": "uuid", "required": True, "in": "path", "description": "The review."}],
        ),
        McpToolDefinition(
            name="list_risk_comments", description="Lists the comments on a Risk, oldest first.",
            method="GET", path_template=f"{_RISK}/comments", params=[_PROJECT_ID, _RISK_ID],
        ),
        McpToolDefinition(
            name="list_risk_types", description="Lists the project's effective Risk types (Safety, Technical, ...).",
            method="GET", path_template=f"{_PREFIX}/risk-types", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="get_risk_scoring_scheme",
            description=(
                "Reads the Likelihood, Consequence and Detectability levels (ids and weights), default model, rating "
                "bands and per-cell ratings that apply to the project. Use it to find the level ids a risk takes."
            ),
            method="GET", path_template=f"{_PREFIX}/scoring-scheme", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="create_risk",
            description="Proposes a Risk in the Identified status. Any project member may; only the title is required.",
            method="POST", path_template=_RISKS,
            params=[_PROJECT_ID, _body("title", "string", "Short name of the risk.", required=True), *_RISK_FIELDS],
        ),
        McpToolDefinition(
            name="update_risk",
            description="Updates a Risk as a new version; only the fields supplied change. Needs the Risk Manager role.",
            method="PUT", path_template=_RISK,
            params=[_PROJECT_ID, _RISK_ID, _body("title", "string", "Short name of the risk."), *_RISK_FIELDS,
                    _body("change_note", "string", "Reason for the change.")],
        ),
        McpToolDefinition(
            name="transition_risk",
            description=(
                "Moves a Risk along its lifecycle (get_risk lists allowed_next_statuses). Moving to accepted needs the "
                "Risk Acceptor role and, through MCP, the project's and organisation's AI-approval opt-in."
            ),
            method="POST", path_template=f"{_RISK}/transition",
            params=[_PROJECT_ID, _RISK_ID, _body("status", "string", "The status to move to.", required=True),
                    _body("comment", "string", "Why; recorded as the version's change note.")],
        ),
        McpToolDefinition(
            name="assess_risk_treatment",
            description=(
                "Records whether one treatment link actually reduces the Risk: effective, ineffective, proposed or "
                "needs_reassessment. effective and ineffective need a rationale. The risk's owner or a Risk Manager only."
            ),
            method="PUT", path_template=f"{_RISK}/treatments/{{link_id}}",
            params=[_PROJECT_ID, _RISK_ID,
                    {"name": "link_id", "type": "uuid", "required": True, "in": "path",
                     "description": "The treatment link (link_id from list_risk_treatments)."},
                    _body("status", "string", "The verdict.", required=True),
                    _body("rationale", "string", "Why the treatment is or is not effective.")],
        ),
        McpToolDefinition(
            name="record_risk_review",
            description=(
                "Records a periodic review of a Risk and sets the date of the next one. A review cannot be 'confirmed' "
                "while a treatment needs reassessment. The risk's owner or a Risk Manager only."
            ),
            method="POST", path_template=f"{_RISK}/reviews",
            params=[_PROJECT_ID, _RISK_ID,
                    _body("outcome", "string", "confirmed (the assessment stands) or reassessed.", required=True),
                    _body("notes", "string", "What the review found.", required=True),
                    _body("next_review_date", "string", "Future date (YYYY-MM-DD) of the next review; null for none.",
                          required=True)],
        ),
        McpToolDefinition(
            name="add_risk_comment", description="Adds a comment to a Risk's discussion.", method="POST",
            path_template=f"{_RISK}/comments",
            params=[_PROJECT_ID, _RISK_ID, _body("body", "string", "The comment text.", required=True)],
        ),
    ) + report_mcp_tools(REPORT_DEFINITIONS, project_router_prefix=_PREFIX)
