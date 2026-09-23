---
sidebar_position: 7
---

# AI assistant (MCP) integration

The Compliance module contributes 78 tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md) — the same mechanism an AI assistant like Claude Code or VS Code Copilot Chat uses to read requirements, change requests, and everything else in ReqTrackManager. Compliance was the first module to use it, and the [Decision Management module](../decision-management-module/mcp-integration.md) now does too — both register their tools automatically the moment the module is enabled for an organisation, with no MCP-server-specific code shipped for either.

Ten tools are read-only (unchanged since this module first added MCP tools); as of 2026-09-22 the other 68 are write tools, covering essentially every mutating compliance endpoint — standards/versions/requirements/required-actions/action-types/mapping-relationship-types, project assignment and version migration, requirement applicability/assessment, required-action-assessment completion, evidence, reviews, and traceability links. Each write tool is subject to the same two gates every MCP write already has: the deployment's `MCP_WRITES_ENABLED` switch, and the calling account's own real RBAC role (a caller can never do anything through this server they couldn't already do through the UI). See [AI assistants → Write mode](../../api-integrations/ai-assistants-mcp/overview.md#write-mode).

**Approving/rejecting a requirement's compliance sign-off is the one exception**, and only a partial one: `compliance_approve_requirement`/`compliance_reject_requirement` exist as tools, but calling either through MCP additionally requires the target project's and its organisation's `allow_ai_approvals` flag both be explicitly enabled — the same opt-in the MCP server's core `approve_requirement`/`decide_change_request` tools already require, generalized so Compliance's own approval action can reuse it. `compliance_submit_requirement_for_approval` needs no such opt-in — submitting only queues a decision for a human (or, once opted in, an AI) to make; it doesn't decide anything itself. Standard member/group role assignment has no MCP tool at all, since granting an RBAC role is not something this MCP surface exposes for any module. See [AI assistants → Module-contributed tools](../../api-integrations/ai-assistants-mcp/overview.md#module-contributed-tools) for the mechanism that enforces all of this, and for the full, current parameter list per tool.

## What you can ask for

| You ask | Tool it maps to |
| --- | --- |
| "What compliance standards does this organisation have?" | `compliance_list_standards` |
| "What requirements are in v1.1 of the Customer Security Addendum?" | `compliance_list_requirements` |
| "How compliant is this project against its assigned standards?" | `compliance_get_project_status` |
| "Which requirements on this project are Non-Compliant right now?" | `compliance_list_non_compliant_requirements` |
| "Is any of this project's evidence about to expire?" | `compliance_list_expiring_evidence` |
| "What's waiting on approval for this project?" | `compliance_list_pending_approvals` |
| "Are there any compliance reviews overdue on this project?" | `compliance_list_reviews_due` |
| "What does this requirement map to in our other standards?" | `compliance_list_requirement_mappings` |
| "What changes between v1.0 and v1.1 of this standard?" | `compliance_get_standard_version_diff` |

## What you can ask it to do (write mode)

| You ask | Tool it maps to |
| --- | --- |
| "Mark this requirement Compliant, with this justification." | `compliance_update_requirement_assessment` |
| "Assign the ISO 27001 v2 standard to this project." | `compliance_assign_standard_to_project` |
| "Log this piece of evidence and link it to that requirement." | `compliance_create_evidence` |
| "Submit this requirement's assessment for approval." | `compliance_submit_requirement_for_approval` |
| "Approve/reject this requirement's assessment." (needs the org+project AI-approval opt-in above) | `compliance_approve_requirement` / `compliance_reject_requirement` |
| "Schedule a review of this standard for next quarter." | `compliance_create_standard_review` |
| "Migrate this assignment to the new published version." | `compliance_migrate_project_compliance_version` |

Because these are ordinary tool calls against the same authenticated MCP server every other ReqTrackManager tool uses, the usual scoping and authentication rules apply unchanged — see [Authenticating](../../api-integrations/authenticating.md) for how a session works, and [AI assistants → Default organisation/project scope](../../api-integrations/ai-assistants-mcp/overview.md#default-organisationproject-scope) for how a client without an explicit organisation/project in its request gets scoped.

## Where this fits

See [Reporting and export](./reporting-and-export.md) for pulling the same underlying data as a PDF/CSV report instead, and [AI assistants (MCP) → Overview](../../api-integrations/ai-assistants-mcp/overview.md) for the MCP server as a whole, including write mode and how to connect a client to it.
