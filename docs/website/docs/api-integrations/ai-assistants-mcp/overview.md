---
sidebar_position: 1
---

# Overview

ReqTrackManager ships a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server — `mcp-server/` — that exposes requirements, change requests, notifications, and review schedules as tools an AI assistant can call directly, instead of a person copy-pasting content into a chat window. It runs as its own container, talks to the same REST API everything else uses, and is reachable by both local developer tools (Claude Code, VS Code Copilot Chat) and remote/hosted ones (Microsoft Copilot Studio) — see [Deploying for remote clients](./deploying-for-remote-clients.md).

Read-only by default. An opt-in **write mode** additionally lets an AI assistant *author* requirement content — narrowly scoped, with a structural guarantee that no tool, in either mode, can ever approve or decide anything. See [Write mode](#write-mode) below.

Every tool call authenticates with the caller's own ReqTrackManager token — see [Authenticating](../authenticating.md), which covers this in full; this page and the rest of this section link back to it rather than repeating it.

## What it can do

Fifteen read tools, always available:

| Tool | Purpose |
| --- | --- |
| `list_organizations` | Organisations the caller's account belongs to or administers |
| `list_projects` | Projects the caller has a role on, optionally filtered by organisation or a name/summary search |
| `get_project` | A single project's detail |
| `list_requirements` | Requirements in a project, with the same filters the UI's filter panel offers (status, component, category, keyword, or a name/code search) |
| `get_requirement` | A single requirement's full current detail |
| `get_requirement_history` | A requirement's full version history — every prior state, who changed it, and why |
| `list_change_requests` | Change requests in a project, optionally filtered by status |
| `get_change_request` | A single change request's full current detail |
| `list_change_request_votes` | A change request's advisory stakeholder vote tally and individual votes |
| `list_change_request_tasks` | Follow-up tasks tracked against a change request |
| `list_change_request_comments` | The discussion thread on a change request |
| `list_requirement_comments` | The discussion thread on a requirement |
| `list_notifications` | The caller's own in-app notifications, optionally unread-only |
| `list_my_reviews_due` | Requirements assigned to the caller with a review date that has passed, across every project |
| `list_project_reviews_due` | Every requirement in a project with a review date that has passed, regardless of assigned reviewer |

Plus two write tools, only when write mode is enabled:

| Tool | Purpose |
| --- | --- |
| `create_requirement` | Creates a new requirement (always starts in "draft") |
| `update_requirement` | Edits an unlocked requirement's content — a partial update; cannot touch `status` |

No tool, in either mode, can vote, comment, decide a change request, or record a review outcome — and, in write mode, `update_requirement` cannot approve or complete a requirement either. See [Known limitations](./known-limitations.md) for what's deliberately out of scope and why.

## Write mode

Off by default (`MCP_WRITES_ENABLED` unset, or anything other than `true`/`1`/`yes`/`on`) — a deployment operator must explicitly opt in before this server can change any data at all, and when it's off, `create_requirement`/`update_requirement` don't just refuse to run — they don't exist: an MCP client's tool list never mentions them. The bundled dev/test stack already sets it on; the production stack defaults it off.

**Requirement content only, never workflow state.** `update_requirement` has no `status` parameter at all — there is no way to make it approve, complete, or otherwise transition a requirement through this server, regardless of what the calling account's own role could do directly via the API. Editing an already-approved (locked) requirement is rejected with a clear error pointing at a change request instead — this server has no tool to create or decide one.

**Why approval specifically stays human-only, structurally, not just by convention:** ReqTrackManager's approval workflow (a Project Manager approving a requirement, or deciding a change request) is only meaningful if every approval represents a real person taking accountability for that decision. The backend's own RBAC would *correctly* let a PM-privileged caller approve something through this server if a tool offered it — RBAC isn't wrong here, it's just answering a different question ("is this account allowed to?") than the one that matters for this specific action ("did an accountable human actually decide this, right now, deliberately?"). So this boundary is enforced at this server's own tool surface — by never exposing the capability in the first place — rather than left to the backend's per-account authorization to (correctly, but insufficiently) gate.

**Still exactly the same pass-through authentication and authorization as every read tool** — write mode doesn't add a second permission model, it just adds two more tools that happen to issue `POST`/`PUT` requests instead of `GET`. The caller's own account still needs a requirement-editing project role for either write tool to succeed, exactly as the UI would require.

**What's still not exposed, even with write mode on** — a deliberately narrow first cut, not an oversight: submitting or deciding a change request, voting, commenting, recording a review outcome, marking a requirement completed, archiving/deleting, uploading attachments, and creating traceability links.

## Module-contributed tools

Beyond the tools above, a backend module can declare its own tools that this server registers automatically, without any module-specific code living in the MCP server itself — see [Modules → Building your own module](../../modules/building-your-own-module.md#module-contributed-mcp-tools) for the mechanism.

**Compliance is the first module to use this**, contributing ten read-only tools:

| Tool | Purpose |
| --- | --- |
| `compliance_list_standards` | Lists an organisation's compliance standards |
| `compliance_get_standard_version` | Fetches a single version of a compliance standard |
| `compliance_list_requirements` | Lists the requirements defined in one version of a compliance standard |
| `compliance_get_project_status` | Gets a project's overall compliance status against each of its currently assigned, active standards |
| `compliance_list_non_compliant_requirements` | Lists every applicable, Non-Compliant requirement across a project's active standard assignments |
| `compliance_list_expiring_evidence` | Lists a project's non-archived supporting evidence approaching or past its expiry date |
| `compliance_list_pending_approvals` | Lists every requirement currently awaiting formal approval/sign-off across a project's active standard assignments |
| `compliance_list_reviews_due` | Lists every scheduled compliance review currently due or overdue for a project |
| `compliance_list_requirement_mappings` | Lists the cross-standard/cross-version mapping links for one compliance requirement |
| `compliance_get_standard_version_diff` | Computes the added/removed/modified/replaced/re-mapped requirement diff between two versions of a standard |

No mutating tool is declared anywhere in Compliance's MCP surface — not for the standards lifecycle, evidence, approvals, review scheduling, requirement mappings, or (most notably) the project version-migration action that touches every requirement row on an assignment. That's a deliberate, narrower application of the same "add write tools cautiously" default described in [Write mode](#write-mode) above, not an oversight; `approve`/`reject` specifically are additionally marked so that even a future accidental attempt to declare a tool for either would be mechanically excluded.

**How it works, briefly:** the backend's `GET /api/v1/system/modules/mcp-tools` returns a manifest of every currently-registered module tool, built with the registered tool name always prefixed by its declaring module's key (e.g. `compliance_list_standards`), `mutates` derived from the HTTP method rather than declared by the module, and any tool that would resolve to an approval/decision action excluded from the manifest entirely — the same "approval stays human-only" principle enforced mechanically rather than by trust. This server fetches that manifest lazily and authenticated (never at an unauthenticated boot-time call), caching it in-process for up to 10 minutes by default (`MODULE_TOOLS_REFRESH_SECONDS`). Each declarative tool is a plain proxy call to the module's own REST endpoint — no module code ever runs inside this server's own process. A mutating module tool is only ever registered when write mode is enabled, the same gate this server's own write tools use.

For a deployment with no module registered, this section has no visible effect — the manifest is simply empty.

## Running it

Part of both Compose stacks already — no extra step beyond the normal `docker compose up`:

```bash
cd tests/container && docker compose up -d --build   # dev/test; also available in the root docker-compose.yml
```

It listens on `:8100`, with the MCP endpoint at `http://localhost:8100/mcp` and a plain liveness check at `http://localhost:8100/health`. `REQTRACK_API_URL` (default `http://backend:8000`, the Compose-internal address) points it at the backend.

## Where this fits

- [Authenticating](../authenticating.md) — getting the token every tool call needs.
- [Setting up Claude Code](./setting-up-claude-code.md), [VS Code](./setting-up-vs-code.md), [Microsoft Copilot Studio](./setting-up-microsoft-copilot-studio.md), [generic/other MCP clients](./generic-mcp-clients.md) — connecting a specific client.
- [Deploying for remote clients](./deploying-for-remote-clients.md) — making this reachable from a hosted client like Copilot Studio.
- [Known limitations](./known-limitations.md) — what's deliberately out of scope, and why.
