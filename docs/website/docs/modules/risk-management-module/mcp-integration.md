---
sidebar_position: 37
---

# AI assistant (MCP) integration

Risk Management contributes 19 tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md), the same mechanism an AI assistant like Claude Code uses to read and update Requirements and the other modules' content. They register automatically when the module is enabled for an organisation, and all are project-scoped. Tool names start with `risk_management_`.

Writes follow the usual MCP write mode: the server must have writes enabled, and the signed-in account's own role decides what it may change. **Accepting a Risk is the one approval-type action.** Calling `risk_management_transition_risk` with the target status `accepted` additionally needs the Risk Acceptor role *and* the project's and organisation's `allow_ai_approvals` setting turned on, the same opt-in as other modules' approve tools. Every other move needs no opt-in.

## What's covered

| Category | Tools |
| --- | --- |
| Read | `list_risks`, `get_risk`, `list_risk_versions`, `list_risk_treatments`, `list_risk_reviews`, `get_risk_review`, `list_risk_comments`, `list_risk_types`, `get_risk_scoring_scheme` |
| Write | `create_risk`, `update_risk`, `transition_risk`, `assess_risk_treatment`, `record_risk_review`, `add_risk_comment` |
| Reports (read-only) | `get_risk_register_report`, `get_risk_exposure_report`, `get_treatment_coverage_report`, `get_review_schedule_report`; see [Reports](./reports.md) |

Treatment links are made with the core link tools (a Requirement *Mitigates* the Risk; the Risk is *Treated by* an Action), then judged with `assess_risk_treatment`. There is no delete tool, and file attachments are not exposed. Ratings are never set directly: an assistant reads level ids from `get_risk_scoring_scheme` and sets levels.

## What you can ask for

| You ask | Tool it maps to |
| --- | --- |
| "Which Risks have no effective treatment?" | `list_risks` (filter effectively treated = false) |
| "Which Risk reviews are overdue?" | `list_risks` (filter review overdue = true), or `get_review_schedule_report` |
| "Show the risk exposure before and after treatment." | `get_risk_exposure_report` |
| "Why does RSK-004's treatment need reassessment?" | `list_risk_treatments` |
| "Add a supply-chain Risk about the modem." | `create_risk`, then `update_risk` |
| "Mark the diagnostics treatment on RSK-001 as effective." | `assess_risk_treatment` |
| "Record a confirmed review of RSK-001, next one in a month." | `record_risk_review` |

A Risk's `owner` is `{"type": "user" | "org_group" | "project_group", "id": …}` on create and update, and comes back with the owner's name and kind.

The same facts and gotchas appear to the assistant as the module's usage guide in the [Agent skill](../../api-integrations/ai-assistants-mcp/agent-skill.mdx), including which statuses need which facts and why an acceptance should only be made on the user's explicit instruction.

## Where this fits

See [Treatment and relationships](./treatment-and-relationships.md) for what a verdict means, and [AI assistants (MCP) → Overview](../../api-integrations/ai-assistants-mcp/overview.md) for connecting a client and for write mode.
