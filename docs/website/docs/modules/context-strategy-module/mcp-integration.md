---
sidebar_position: 21
---

# AI assistant (MCP) integration

Context & Strategy contributes 62 tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md) — the same mechanism an AI assistant like Claude Code or VS Code Copilot Chat uses to read and update Requirements, Decisions, and everything else in ReqTrackManager. These register automatically the moment the module is enabled for an organisation, with no MCP-server-specific code shipped for it — the same module-contributed-tools mechanism [Compliance](../compliance-module/mcp-integration.md) and [Decision Management](../decision-management-module/mcp-integration.md) already use.

All 62 tools are project-scoped — there is no org-scoped equivalent, even for Strategy/Future State/Guiding Principle's organisation-level records, since the approval gate below needs a specific project to check against and this module's MCP surface stays project-only throughout rather than special-casing an org-only variant of it.

## What's covered

| Category | Count | Covers |
| --- | --- | --- |
| List / get | 15 | Listing and fetching each of the five artefact types, plus listing each one's relationship links. |
| Create / update content | 10 | Creating a new record (Draft status) or replacing an existing one's content, for each of the five artefact types. |
| Relationships and supersessions | 8 | Creating a typed or untyped relationship from an artefact to another, and recording a supersession (Strategy, Future State, and Guiding Principle only — Pain Point and Open Question have no supersession concept). |
| Plain lifecycle transitions | 24 | Every non-decisive status change — propose, submit for review, send back, activate, retire, triage, reject, mark duplicate, accept, address, close, investigate, mark ready for decision, withdraw. None of these require the AI-approval opt-in below, since none of them constitute a final approval or resolution. |
| Approve / decide (gated) | 5 | `approve_strategy`, `approve_future_state`, `activate_guiding_principle`, `retire_guiding_principle`, `resolve_open_question` — see below. |

File upload and comment endpoints are not exposed through MCP at all — the same posture Decision Management already takes toward its own comment/file endpoints, and (for file upload specifically) the same `multipart/form-data` constraint that mechanism can't express regardless.

## What you can ask for

| You ask | Tool it maps to |
| --- | --- |
| "What Strategies does this project have?" | `list_strategies` |
| "What's the current state of the Falcon-3 Strategy?" | `get_strategy` |
| "What's this project's Future State vision?" | `list_future_states` / `get_future_state` |
| "What Pain Points have been raised on this project?" | `list_pain_points` |
| "What Guiding Principles apply to this project?" | `list_guiding_principles` |
| "What Open Questions are still unresolved?" | `list_open_questions` |
| "What does this Strategy link to?" | `list_strategy_relationships` (and the equivalent for the other four artefact types) |

## What you can ask it to do (write mode)

| You ask | Tool it maps to |
| --- | --- |
| "Create a Strategy for..." / "Update this Strategy's rationale..." | `create_strategy` / `update_strategy` (and the equivalent create/update pair for the other four artefact types) |
| "Link this Pain Point to the Strategy it's driving." | `create_pain_point_relationship` (kind: `drives_strategy`) |
| "Move this Pain Point to Triaged." / "Accept it." / "Address it." / "Close it." | `triage_pain_point` / `accept_pain_point` / `address_pain_point` / `close_pain_point` |
| "Investigate this Open Question." / "Mark it ready for a decision." | `investigate_open_question` / `mark_open_question_ready_for_decision` |
| "Record that this new Strategy supersedes the old one." | `create_strategy_supersession` |
| "Approve this Strategy." (needs the org+project AI-approval opt-in below) | `approve_strategy` |
| "Resolve this Open Question." (needs the org+project AI-approval opt-in below) | `resolve_open_question` |

## The approval gate

Five tools — `approve_strategy`, `approve_future_state`, `activate_guiding_principle`, `retire_guiding_principle`, and `resolve_open_question` — sit at this module's approve/decide tier, the point in each lifecycle where a human (or an explicitly opted-in AI assistant) makes the call rather than just moving a record along for review. Calling any of them through MCP additionally requires the target project's and its organisation's `allow_ai_approvals` flag to both be explicitly enabled — the same opt-in the MCP server's core `approve_requirement`/`decide_change_request` tools, Compliance's `compliance_approve_requirement`, and Decision Management's `decisions_approve_decision` all already require.

Guiding Principle's own gated pair is `activate_guiding_principle`/`retire_guiding_principle` rather than an `approve_guiding_principle` — approving a Guiding Principle (`Proposed → Approved`) is a plain lifecycle transition here (this lifecycle has no `Under Review` step to approve out of), and it's *activating* an already-approved principle, or retiring one, that carries the same "this is now in force / no longer in force" weight the other four gated tools carry.

Because these are ordinary tool calls against the same authenticated MCP server every other ReqTrackManager tool uses, the usual scoping and authentication rules apply unchanged — see [Authenticating](../../api-integrations/authenticating.md) for how a session works.

## Where this fits

See [Relationships and types](./relationships-and-types.md) for what each relationship kind actually means, and [AI assistants (MCP) → Overview](../../api-integrations/ai-assistants-mcp/overview.md) for the MCP server as a whole, including write mode and how to connect a client to it.
