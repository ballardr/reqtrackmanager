---
sidebar_position: 12
---

# AI assistant (MCP) integration

The Decision Management module contributes seven read-only tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md) — the same mechanism an AI assistant like Claude Code or VS Code Copilot Chat uses to read requirements, change requests, and everything else in ReqTrackManager. This follows the same module-contributed-tools mechanism the [Compliance module](../compliance-module/mcp-integration.md) already uses, registering these tools automatically the moment Decision Management is enabled for an organisation, with no MCP-server-specific code shipped for it.

Every tool is read-only: nothing that creates, proposes, submits, approves, rejects, supersedes, comments on, or attaches a file to a Decision is ever exposed here — deliberately, the same narrow-by-design choice [Compliance's own MCP integration](../compliance-module/mcp-integration.md) already documents for its own approval/sign-off action. This module's mutating actions (particularly approve/reject/supersede) are exactly the kind of accountable-human governance action this whole mechanism keeps off the tool surface, regardless of ReqTrackManager's separate MCP write mode — see [AI assistants → Write mode](../../api-integrations/ai-assistants-mcp/overview.md#write-mode) for what that setting does and does not cover. The approve/reject endpoints are additionally marked so that even a future accidental tool declaration for either would be mechanically excluded from the manifest, rather than relying on nobody ever declaring one.

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

Because these are ordinary tool calls against the same authenticated MCP server every other ReqTrackManager tool uses, the usual scoping and authentication rules apply unchanged — see [Authenticating](../../api-integrations/authenticating.md) for how a session works, and [AI assistants → Default organisation/project scope](../../api-integrations/ai-assistants-mcp/overview.md#default-organisationproject-scope) for how a client without an explicit organisation/project in its request gets scoped.

## Where this fits

See [Relationships and templates](./relationships-and-templates.md) for what a Decision's relationships actually mean, and [AI assistants (MCP) → Overview](../../api-integrations/ai-assistants-mcp/overview.md) for the MCP server as a whole, including write mode and how to connect a client to it.
