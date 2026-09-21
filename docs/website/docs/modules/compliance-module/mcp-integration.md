---
sidebar_position: 7
---

# AI assistant (MCP) integration

The Compliance module contributes ten read-only tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md) — the same mechanism an AI assistant like Claude Code or VS Code Copilot Chat uses to read requirements, change requests, and everything else in ReqTrackManager. Compliance was the first module to use it, and the [Decision Management module](../decision-management-module/mcp-integration.md) now does too — both register their tools automatically the moment the module is enabled for an organisation, with no MCP-server-specific code shipped for either.

Every tool is read-only: nothing that approves, decides, or otherwise mutates compliance state is ever exposed here. This is narrower than the MCP server as a whole — its core tools now let an AI assistant approve a requirement or decide a change request once an org admin and a project manager/administrator have each explicitly opted in (see [AI assistants → Write mode](../../api-integrations/ai-assistants-mcp/overview.md#write-mode)) — but no equivalent opt-in exists for Compliance's own approval/sign-off action, so it stays fully excluded regardless of that setting. See [AI assistants → Module-contributed tools](../../api-integrations/ai-assistants-mcp/overview.md#module-contributed-tools) for the mechanism that enforces this, and for the full, current parameter list per tool.

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

Because these are ordinary tool calls against the same authenticated MCP server every other ReqTrackManager tool uses, the usual scoping and authentication rules apply unchanged — see [Authenticating](../../api-integrations/authenticating.md) for how a session works, and [AI assistants → Default organisation/project scope](../../api-integrations/ai-assistants-mcp/overview.md#default-organisationproject-scope) for how a client without an explicit organisation/project in its request gets scoped.

## Where this fits

See [Reporting and export](./reporting-and-export.md) for pulling the same underlying data as a PDF/CSV report instead, and [AI assistants (MCP) → Overview](../../api-integrations/ai-assistants-mcp/overview.md) for the MCP server as a whole, including write mode and how to connect a client to it.
