"""
Module: modules.traceability.mcp_tools

MCP tool declarations of the Governance half (`docs/modules.md` section 6); each proxies a route of the module's organisation
or project router, so its permission check, sub-component gate and audit event apply. `build_mcp_tools` declares read tools
and write tools for governance health, the project's profile choices and approval, review and baseline policy, and the
organisation's profiles with their policy and health default.

Design decisions:
- Writes need `MCP_WRITES_ENABLED` and the caller's own right (`manage_project_governance` or `manage_org_governance`).
- No tool can approve, reject or finalise a blocked transition or baseline: none of this module's routes does either.
- Deleting a profile and adding or removing an exemption are not tools. Each lifts a control an organisation enforces, so
  they stay a person's act in the application (a stated integrity reason, as an approval is a person's act).

Dependencies: `modules.registry` (`McpToolDefinition`), `modules.traceability._shared`.
"""

from __future__ import annotations

from app.modules.registry import McpToolDefinition
from app.modules.traceability._shared import TRACEABILITY_MODULE_KEY

_ORG = f"/api/v1/orgs/{{organization_id}}/modules/{TRACEABILITY_MODULE_KEY}"
_PROJECT = f"/api/v1/projects/{{project_id}}/modules/{TRACEABILITY_MODULE_KEY}"


def _path(name: str, type_: str, description: str) -> dict:
    return {"name": name, "type": type_, "required": True, "in": "path", "description": description}


def _body(name: str, type_: str, description: str, *, required: bool = False) -> dict:
    return {"name": name, "type": type_, "required": required, "in": "body", "description": description}


def _query(name: str, type_: str, description: str, *, required: bool = False) -> dict:
    return {"name": name, "type": type_, "required": required, "in": "query", "description": description}


_ORG_ID = _path("organization_id", "uuid", "The organisation.")
_PROJECT_ID = _path("project_id", "uuid", "The project.")
_PROFILE_ID = _path("profile_id", "uuid", "The governance profile (`list_governance_profiles`).")
_TYPE = _path("artefact_type", "string", "The registered record type, as the policy read lists it (for example `requirement`).")
_MODE = (
    "`on_demand` (computed for each viewer), `snapshot_interval` (a stored snapshot refreshed every interval) or "
    "`snapshot_on_change` (a stored snapshot recomputed on the next read after a change)."
)
_INTERVAL = "Snapshot interval in hours: 1, 6, 12, 24, 48, 72, 120, 168, 240 or 336."
_POLICY_ROLES = _body(
    "roles", "array",
    'Roles that may also approve the type: `[{"kind": "project" | "module" | "custom", "key": ...}]` (the read lists the '
    "role options). `[]` adds none.",
    required=True,
)
_PROJECT_POLICY_ROLES = _body(
    "roles", "array",
    'Roles the project adds as approvers of the type: `[{"kind": "project" | "module" | "custom", "key": ...}]`; `[]` adds none; '
    "null follows the nearest ancestor project.",
)
_REVIEW_SETTINGS = [
    _body("interval_days", "integer", "Longest gap between reviews, 1 to 3650 days."),
    _body("lead_days", "integer", "Days before the due date the reminder is sent, 0 to 365."),
    _body("default_owner", "object", 'Who is reminded when a record has no reviewer: {"type": "user" | "org_group" | "project_group", "id": uuid}.'),
]
_BASELINE_SETTINGS = [
    _body("applies_to_stage", "boolean", "Run the checks before a stage baseline (default true)."),
    _body("applies_to_manual", "boolean", "Run the checks before a manual baseline (default false). At least one of the two is true."),
    _body("notify_managers", "boolean", "Tell the project's managers when a check refuses a stage's automatic approval (default true)."),
    _body("checks", "array", "Namespaced check keys to run, from the read's `check_options` (for example `traceability:required_fields`)."),
    _body("required_fields", "array", 'Fields the required-fields check demands: `[{"artefact_type": ..., "field_key": ...}]`.'),
]


def build_mcp_tools() -> tuple[McpToolDefinition, ...]:
    """The module's MCP tools: project health and policy first, then the organisation's profiles and policy."""
    return (
        McpToolDefinition(
            name="get_governance_health",
            description=(
                "A project's governance health: the share complete (or the count outstanding) of each record category, reviews due, "
                "and the results of the enabled baseline checks, limited to the record types the caller may read. Live for "
                "the caller in `on_demand`, else the stored snapshot with the time it was read."
            ),
            method="GET", path_template=f"{_PROJECT}/health", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="refresh_governance_health",
            description=(
                "Recomputes the project's stored health snapshot now (a snapshot mode only; the baseline checks run as the "
                "configured runner, else as the caller)."
            ),
            method="POST", path_template=f"{_PROJECT}/health/refresh", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="get_governance_health_settings",
            description=(
                "How the project's health is kept: mode, snapshot interval, baseline check runner, where each comes from, and "
                "the size guidance."
            ),
            method="GET", path_template=f"{_PROJECT}/health/settings", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="set_governance_health_settings",
            description=(
                "Sets the project's own health mode, snapshot interval and baseline check runner (every field is replaced; null"
                " follows the organisation's default)."
            ),
            method="PUT", path_template=f"{_PROJECT}/health/settings",
            params=[
                _PROJECT_ID,
                _body("mode", "string", f"{_MODE} null follows the organisation's default."),
                _body("interval_hours", "integer", f"{_INTERVAL} null follows the organisation's default."),
                _body(
                    "checks_runner_id", "uuid",
                    "A user who holds a role in the project; the baseline checks of a snapshot run as them. "
                    "null: only a person who refreshes runs them.",
                ),
            ],
        ),
        McpToolDefinition(
            name="list_project_governance_profiles",
            description=(
                "The organisation's governance profiles that reach the project and what each does for it (enforced, default, "
                "opted in or out, available)."
            ),
            method="GET", path_template=f"{_PROJECT}/profiles", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="set_project_governance_profile_choice",
            description="Opts the project out of a Default profile or in to an Opt-in profile (an Enforced profile cannot be chosen away).",
            method="PUT", path_template=f"{_PROJECT}/profiles/{{profile_id}}/choice",
            params=[_PROJECT_ID, _PROFILE_ID, _body("opted_in", "boolean", "true opts in, false opts out, null clears the choice.")],
        ),
        McpToolDefinition(
            name="get_project_approval_policies",
            description=(
                "The roles that may also approve each record type in the project, with where each comes from, and the roles a "
                "policy may name."
            ),
            method="GET", path_template=f"{_PROJECT}/approval-policies", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="set_project_approval_policy",
            description=(
                "Sets the roles the project adds as approvers of one record type. This only adds approvers: it never removes a "
                "default approver and never performs an approval."
            ),
            method="PUT", path_template=f"{_PROJECT}/approval-policies/{{artefact_type}}",
            params=[_PROJECT_ID, _TYPE, _PROJECT_POLICY_ROLES],
        ),
        McpToolDefinition(
            name="get_project_review_policies",
            description=(
                "The review interval, reminder lead and default owner of each record type with a review schedule in the "
                "project, with where each comes from."
            ),
            method="GET", path_template=f"{_PROJECT}/review-policies", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="set_project_review_policy",
            description=(
                "Sets the review settings the project gives one record type (`settings` null follows the nearest ancestor "
                "project; an object with nothing set is a choice of none)."
            ),
            method="PUT", path_template=f"{_PROJECT}/review-policies/{{artefact_type}}",
            params=[
                _PROJECT_ID, _TYPE,
                _body("settings", "object", "`{interval_days, lead_days, default_owner}`, each optional; null follows the ancestor."),
            ],
        ),
        McpToolDefinition(
            name="get_project_baseline_policy",
            description=(
                "The checks that run before the project's baselines and the fields it requires, with where each comes from, and"
                " the options on offer."
            ),
            method="GET", path_template=f"{_PROJECT}/baseline-policy", params=[_PROJECT_ID],
        ),
        McpToolDefinition(
            name="set_project_baseline_policy",
            description=(
                "Sets the project's own baseline policy (`settings` null follows the nearest ancestor project; settings with no"
                " check is a choice of none)."
            ),
            method="PUT", path_template=f"{_PROJECT}/baseline-policy",
            params=[
                _PROJECT_ID,
                _body(
                    "settings", "object",
                    "`{applies_to_stage, applies_to_manual, notify_managers, checks[], required_fields[]}`; null follows the ancestor.",
                ),
            ],
        ),
        McpToolDefinition(
            name="preview_baseline_checks",
            description=(
                "Runs the enabled baseline checks against what a baseline taken now would hold and lists every failing record "
                "and check, writing nothing."
            ),
            method="GET", path_template=f"{_PROJECT}/baseline-checks",
            params=[
                _PROJECT_ID,
                _query("kind", "string", "`stage` (needs stage_id) or `manual`.", required=True),
                _query("stage_id", "uuid", "The stage whose baseline is previewed."),
                _query("component_id", "uuid", "A component's own baseline of the stage."),
            ],
        ),
        McpToolDefinition(
            name="get_governance_health_defaults",
            description="The organisation's default way of keeping governance health (mode and snapshot interval).",
            method="GET", path_template=f"{_ORG}/health-defaults", params=[_ORG_ID],
        ),
        McpToolDefinition(
            name="set_governance_health_defaults",
            description="Sets the default health mode and snapshot interval of every project that sets none of its own.",
            method="PUT", path_template=f"{_ORG}/health-defaults",
            params=[_ORG_ID, _body("mode", "string", _MODE, required=True), _body("interval_hours", "integer", _INTERVAL)],
        ),
        McpToolDefinition(
            name="list_governance_profiles",
            description="The organisation's governance profiles with their mode, targets, exemptions and policy-row counts.",
            method="GET", path_template=f"{_ORG}/profiles", params=[_ORG_ID],
        ),
        McpToolDefinition(
            name="get_governance_profile",
            description="One governance profile with the projects it binds, offers or has been opted out of.",
            method="GET", path_template=f"{_ORG}/profiles/{{profile_id}}", params=[_ORG_ID, _PROFILE_ID],
        ),
        McpToolDefinition(
            name="create_governance_profile",
            description="Creates a governance profile. An Enforced profile binds every project it reaches as soon as it has policy rows.",
            method="POST", path_template=f"{_ORG}/profiles",
            params=[
                _ORG_ID,
                _body("name", "string", "Unique within the organisation.", required=True),
                _body("mode", "string", "`enforced`, `default` or `opt_in`.", required=True),
                _body("description", "string", "A short summary."),
                _body("target_kind", "string", "`all_projects` (default) or `selected_projects`."),
                _body("targets", "array", 'For `selected_projects`: `[{"project_id": uuid, "include_children": bool}]`.'),
            ],
        ),
        McpToolDefinition(
            name="update_governance_profile",
            description="Renames a profile or changes its description or mode; a field left out is unchanged.",
            method="PATCH", path_template=f"{_ORG}/profiles/{{profile_id}}",
            params=[
                _ORG_ID, _PROFILE_ID,
                _body("name", "string", "New name."),
                _body("description", "string", "New description."),
                _body("mode", "string", "`enforced`, `default` or `opt_in`."),
            ],
        ),
        McpToolDefinition(
            name="set_governance_profile_targets",
            description="Replaces the projects a profile reaches.",
            method="PUT", path_template=f"{_ORG}/profiles/{{profile_id}}/targets",
            params=[
                _ORG_ID, _PROFILE_ID,
                _body("target_kind", "string", "`all_projects` or `selected_projects`.", required=True),
                _body("targets", "array", 'For `selected_projects`: `[{"project_id": uuid, "include_children": bool}]`.'),
            ],
        ),
        McpToolDefinition(
            name="get_profile_lifecycle_policy",
            description="The lifecycle states a profile requires of each record type and whether it forbids skipping steps.",
            method="GET", path_template=f"{_ORG}/profiles/{{profile_id}}/lifecycle", params=[_ORG_ID, _PROFILE_ID],
        ),
        McpToolDefinition(
            name="set_profile_lifecycle_required",
            description="Sets the optional states a profile requires of one record type (`[]` removes the requirement).",
            method="PUT", path_template=f"{_ORG}/profiles/{{profile_id}}/lifecycle/{{artefact_type}}",
            params=[_ORG_ID, _PROFILE_ID, _TYPE, _body("required", "array", "State keys the type's projects must keep on.", required=True)],
        ),
        McpToolDefinition(
            name="set_profile_lifecycle_skip",
            description="Sets whether a profile forbids skipping steps of a record's lifecycle.",
            method="PUT", path_template=f"{_ORG}/profiles/{{profile_id}}/lifecycle/skip",
            params=[_ORG_ID, _PROFILE_ID, _body("forbidden", "boolean", "true forbids skipping.", required=True)],
        ),
        McpToolDefinition(
            name="get_profile_stage_workflow_policy",
            description=(
                "The organisation stage workflow a profile requires of its projects, how it binds them and the workflows it may "
                "name."
            ),
            method="GET", path_template=f"{_ORG}/profiles/{{profile_id}}/stage-workflow", params=[_ORG_ID, _PROFILE_ID],
        ),
        McpToolDefinition(
            name="set_profile_stage_workflow_policy",
            description=(
                "Makes a profile require an organisation stage workflow: new stages of its projects start in it and a project "
                "cannot hide it. In `restrict` mode a project may use only the workflows its profiles name."
            ),
            method="PUT", path_template=f"{_ORG}/profiles/{{profile_id}}/stage-workflow",
            params=[
                _ORG_ID, _PROFILE_ID,
                _body("workflow_id", "uuid", "An organisation workflow, from the read's `options`.", required=True),
                _body("mode", "string", "`default` (new stages start in it; other workflows stay usable) or `restrict`."),
            ],
        ),
        McpToolDefinition(
            name="get_profile_approval_policy",
            description="The roles a profile adds as approvers of each record type, with the roles a policy may name.",
            method="GET", path_template=f"{_ORG}/profiles/{{profile_id}}/approval", params=[_ORG_ID, _PROFILE_ID],
        ),
        McpToolDefinition(
            name="set_profile_approval_policy",
            description="Sets the roles a profile adds as approvers of one record type. This only adds approvers and never performs an approval.",
            method="PUT", path_template=f"{_ORG}/profiles/{{profile_id}}/approval/{{artefact_type}}",
            params=[_ORG_ID, _PROFILE_ID, _TYPE, _POLICY_ROLES],
        ),
        McpToolDefinition(
            name="get_profile_review_policy",
            description="The review interval, reminder lead and default owner a profile gives each record type with a review schedule.",
            method="GET", path_template=f"{_ORG}/profiles/{{profile_id}}/review", params=[_ORG_ID, _PROFILE_ID],
        ),
        McpToolDefinition(
            name="set_profile_review_policy",
            description="Sets the review settings a profile gives one record type (nothing set removes them).",
            method="PUT", path_template=f"{_ORG}/profiles/{{profile_id}}/review/{{artefact_type}}",
            params=[_ORG_ID, _PROFILE_ID, _TYPE, *_REVIEW_SETTINGS],
        ),
        McpToolDefinition(
            name="get_profile_baseline_policy",
            description="The baseline checks and required fields a profile asks of its projects, with the check options.",
            method="GET", path_template=f"{_ORG}/profiles/{{profile_id}}/baseline", params=[_ORG_ID, _PROFILE_ID],
        ),
        McpToolDefinition(
            name="set_profile_baseline_policy",
            description="Sets the baseline policy a profile gives its projects.",
            method="PUT", path_template=f"{_ORG}/profiles/{{profile_id}}/baseline",
            params=[_ORG_ID, _PROFILE_ID, *_BASELINE_SETTINGS],
        ),
    )
