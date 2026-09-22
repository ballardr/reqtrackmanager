---
sidebar_position: 12
---

# AI assistant (MCP) integration

The Decision Management module contributes nine tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md) — the same mechanism an AI assistant like Claude Code or VS Code Copilot Chat uses to read requirements, change requests, and everything else in ReqTrackManager. This follows the same module-contributed-tools mechanism the [Compliance module](../compliance-module/mcp-integration.md) already uses, registering these tools automatically the moment Decision Management is enabled for an organisation, with no MCP-server-specific code shipped for it.

Seven tools are read-only. **Approving/rejecting a Decision is the one exception, and only a partial one**, as of 2026-09-22 (`docs/decisions.md`'s "Decision Management MCP approval gate" entry — the user's explicit follow-up to [Compliance's own equivalent change](../compliance-module/mcp-integration.md), "Yes, apply the same treatment"): `decisions_approve_decision`/`decisions_reject_decision` exist as tools, but calling either through MCP additionally requires the target project's and its organisation's `allow_ai_approvals` flag both be explicitly enabled — the same opt-in the MCP server's core `approve_requirement`/`decide_change_request` tools and Compliance's own `compliance_approve_requirement`/`compliance_reject_requirement` already require. Nothing that creates, proposes, submits for review, supersedes, comments on, or attaches a file to a Decision is exposed here — `propose`/`submit-for-review` need no opt-in (they only queue a decision for a human, or now an opted-in AI assistant, to make; neither decides anything itself), and the rest simply weren't in scope for this change.

## What you can ask for

| You ask | Tool it maps to |
| --- | --- |
| "What Decision Types does this project use?" | `decisions_list_decision_types` |
| "What Decisions are recorded on this project?" | `decisions_list_decisions` |
| "What did we decide about the authentication approach?" (once you have the Decision) | `decisions_get_decision` |
| "What Requirements does this Decision implement or affect?" | `decisions_list_decision_relationships` |
| "What's the discussion history on this Decision?" | `decisions_list_decision_comments` |
| "What files are attached to this Decision?" | `decisions_list_decision_files` |
| "What Decision Templates does this organisation have available?" | `decisions_list_decision_templates` |

## What you can ask it to do (write mode)

| You ask | Tool it maps to |
| --- | --- |
| "Approve/reject this Decision." (needs the org+project AI-approval opt-in above) | `decisions_approve_decision` / `decisions_reject_decision` |

Because these are ordinary tool calls against the same authenticated MCP server every other ReqTrackManager tool uses, the usual scoping and authentication rules apply unchanged — see [Authenticating](../../api-integrations/authenticating.md) for how a session works, and [AI assistants → Default organisation/project scope](../../api-integrations/ai-assistants-mcp/overview.md#default-organisationproject-scope) for how a client without an explicit organisation/project in its request gets scoped.

## Where this fits

See [Relationships and templates](./relationships-and-templates.md) for what a Decision's relationships actually mean, and [AI assistants (MCP) → Overview](../../api-integrations/ai-assistants-mcp/overview.md) for the MCP server as a whole, including write mode and how to connect a client to it.
