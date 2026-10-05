---
sidebar_position: 28
---

# AI assistant (MCP) integration

Stakeholders & Personas contributes 36 tools to ReqTrackManager's [MCP server](../../api-integrations/ai-assistants-mcp/overview.md) — the same mechanism an AI assistant like Claude Code uses to read and update Requirements and the other modules' content. They register automatically when the module is enabled for an organisation. All are project-scoped.

Writes follow the usual MCP write mode: the server must have writes enabled, and the signed-in account's own role decides what it may change. There is no approval step in this module, so no tool needs the AI-approval opt-in that Decision Management's and Context & Strategy's approve tools need.

## What's covered

| Category | Count | Covers |
| --- | --- | --- |
| List / get | 6 | Listing and fetching Personas, Stakeholders and Stakeholder Needs. |
| Create / update | 6 | Creating a record (always as Draft) or changing some of its fields. |
| Activate / retire | 6 | Moving a record between Draft, Active and Retired. |
| Relationship reads | 8 | The relationship kinds, the records a relationship can point at, a Stakeholder's or Persona's relationships, who is related to a given Pain Point, Requirement or Decision, who a Stakeholder represents and who has a Need. |
| Relationship changes | 10 | Adding and removing relationships, "represents" links, "has need" links and "gives rise to" links. |

Every `remove_*` tool deletes only the link, never either record. There is deliberately **no tool to permanently delete a Stakeholder**: irreversible deletion of personal data stays a human action in the app. File and comment endpoints are not exposed.

## What you can ask for

| You ask | Tool it maps to |
| --- | --- |
| "Who are this project's Stakeholders?" / "Which Personas do we have?" | `list_stakeholders` / `list_personas` |
| "What does Dana Whitfield need?" | `list_need_holders`, `list_stakeholder_needs` |
| "Who experiences this Pain Point?" | `list_incoming_relationships` |
| "Create a Persona for the remote pilot." | `create_persona` |
| "Record that this Stakeholder was consulted on that Decision." | `add_stakeholder_relationship` (kind `consulted_on_decision`) |
| "Say this Need gave rise to that Requirement." | `add_need_requirement` |

## Where this fits

See [Relationships](./relationships.md) for what each relationship kind means, and [AI assistants (MCP) → Overview](../../api-integrations/ai-assistants-mcp/overview.md) for connecting a client and for write mode.
