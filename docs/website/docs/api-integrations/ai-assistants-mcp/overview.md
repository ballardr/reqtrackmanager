---
sidebar_position: 1
---

# Overview

ReqTrackManager ships a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server — `mcp-server/` — that exposes requirements, change requests, notifications, and review schedules as tools an AI assistant can call directly, instead of a person copy-pasting content into a chat window. It runs as its own container, talks to the same REST API everything else uses, and is reachable by both local developer tools (Claude Code, VS Code Copilot Chat) and remote/hosted ones (Microsoft Copilot Studio) — see [Deploying for remote clients](./deploying-for-remote-clients.md).

Read-only by default. An opt-in **write mode** (on by default) additionally lets an AI assistant *author* requirement content and, separately, perform an approval-type action once an org admin and a project manager/administrator have each explicitly enabled that for their own organisation/project. See [Write mode](#write-mode) below.

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

Plus five write tools, only when write mode is enabled:

| Tool | Purpose |
| --- | --- |
| `create_requirement` | Creates a new requirement (always starts in "draft") |
| `update_requirement` | Edits an unlocked requirement's content — a partial update; cannot touch `status` |
| `approve_requirement` | Approves a draft or reviewed requirement — only when AI approval is enabled for the project and its organisation |
| `decide_change_request` | Approves or rejects a submitted change request — only when AI approval is enabled for the project and its organisation |
| `complete_requirement` | Marks an approved requirement completed — only when AI approval is enabled for the project and its organisation |

No tool, in any configuration, can vote, comment, or record a review outcome. See [Known limitations](./known-limitations.md) for what's deliberately still out of scope and why.

## Write mode

On by default (`MCP_WRITES_ENABLED` unset, or anything other than `false`/`0`/`no`/`off`) — set it to `false` explicitly to opt a deployment back into read-only-only. Both the bundled dev/test stack and the production stack default it on. When it's off, none of the five write tools above exist at all: an MCP client's tool list never mentions them.

**`create_requirement`/`update_requirement`: requirement content only, never workflow state.** `update_requirement` has no `status` parameter at all — there is no way to make it approve, complete, or otherwise transition a requirement through either tool, regardless of what the calling account's own role could do directly via the API. Editing an already-approved (locked) requirement is rejected with a clear error pointing at a change request instead.

**`approve_requirement`/`decide_change_request`/`complete_requirement`: approval-type actions, gated by an explicit organisation-and-project opt-in.** ReqTrackManager's approval workflow is only meaningful if every approval represents a real person taking accountability for that decision, so this was originally kept entirely off-limits through this server. It's since been deliberately, narrowly reopened, under a two-level opt-in that must **both** be true:

- The organisation's **Allow AI approval via MCP** setting (Org Admin → Security → Advanced settings), an org-admin-only toggle.
- The specific project's own **Allow AI approval via MCP for this project** setting (Project Admin → Overview), a project-manager/administrator-only toggle.

Both are off by default, and enabling either one requires the enabling admin/manager to explicitly acknowledge — via a dialog that blocks confirmation until an acknowledgment checkbox is checked — that an AI-made approval isn't necessarily a deliberate, in-the-moment human decision and may weaken the accountability the approval workflow is meant to represent. If either flag is off, calling one of these three tools fails with a clear error, even if the calling account's own role would normally allow the action directly through the UI — a plain UI/API call is entirely unaffected by these two flags either way.

Every approval/decision/completion performed this way is visibly marked "(via MCP)" wherever that requirement's or change request's activity is displayed, and approving a requirement this way records the change note "Approved via MCP." directly in its Version History.

**Still exactly the same pass-through authentication and authorization as every read tool** — write mode doesn't add a second permission model. The caller's own account still needs a requirement-editing project role for `create_requirement`/`update_requirement`, and the project-manager role for the three approval-type tools, exactly as the UI would require.

**What's still not exposed, in any configuration** — a deliberately narrow set, not an oversight: submitting a change request, voting, commenting, recording a review outcome, archiving/deleting, uploading attachments, and creating traceability links.

## Default organisation/project scope

Two optional HTTP headers on the MCP connection — `X-Default-Organization-Id` / `X-Default-Project-Id` — let a client permanently scoped to one organisation or project omit `organization_id`/`project_id` from every tool call; the configured default is used instead when a call doesn't name one explicitly. Set them the same way you set the `Authorization` header — see [Generic/other MCP clients](./generic-mcp-clients.md).

## Module-contributed tools

Beyond the tools above, a backend module can declare its own tools that this server registers automatically, without any module-specific code living in the MCP server itself — see [Modules → Building your own module](../../modules/building-your-own-module.md#module-contributed-mcp-tools) for the mechanism.

**Compliance and Decision Management are the modules that use this so far.** Compliance's MCP surface was write-enabled 2026-09-22 (see [decisions.md](https://github.com/ballardr/reqtrackmanager/blob/main/docs/decisions.md)'s "Compliance MCP write tools + generalized AI approval gate" entry); Decision Management's approve/reject actions got the identical gated treatment the same day, as an explicit follow-up (see that same doc's "Decision Management MCP approval gate" entry) — its other mutating actions remain undeclared.

Compliance contributes 78 tools: 10 read-only —

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

— plus 68 write tools covering essentially every mutating compliance endpoint (standards/versions/requirements/required-actions/action-types/mapping-relationship-types CRUD, project assignment/migration, assessment, evidence, reviews, traceability links; full list in [Compliance module → AI assistant integration](../../modules/compliance-module/mcp-integration.md)), each gated the same as any other MCP write tool by write mode and the caller's own RBAC role. `compliance_approve_requirement`/`compliance_reject_requirement` are the one exception: they exist as tools but additionally require the target project's and its organisation's `allow_ai_approvals` opt-in (the same one `approve_requirement`/`decide_change_request`/`complete_requirement` above use, generalized for module reuse) — no longer a hard, no-opt-in-possible exclusion. Standard member/group role assignment and the two file-upload endpoints (`import_standard`, evidence file upload) still have no MCP tool — an RBAC role grant and a file upload respectively, neither of which this mechanism supports for any module.

Decision Management contributes nine tools: seven read-only —

| Tool | Purpose |
| --- | --- |
| `decisions_list_decision_types` | Lists the Decision Types configured for a project |
| `decisions_list_decisions` | Lists the Decision records in a project |
| `decisions_get_decision` | Fetches a single Decision record, including its current status and content |
| `decisions_list_decision_relationships` | Lists a Decision's relationship links (supersession, Decision↔Requirement, Decision↔Decision) |
| `decisions_list_decision_comments` | Lists the comments on a Decision |
| `decisions_list_decision_files` | Lists the files directly attached to a Decision |
| `decisions_list_decision_templates` | Lists an organisation's Decision Templates |

— plus two write tools, `decisions_approve_decision`/`decisions_reject_decision` (2026-09-22, the explicit follow-up to Compliance's equivalent change above — "Yes, apply the same treatment"): both exist as tools but additionally require the target project's and its organisation's `allow_ai_approvals` opt-in, the same one `compliance_approve_requirement`/`compliance_reject_requirement` and the three core approval-type tools already use — no longer a hard, no-opt-in-possible exclusion. No tool exists for creating a Decision, proposing/submitting it for review, superseding, commenting, or attaching a file — `propose`/`submit-for-review` need no opt-in (they only queue a decision, they don't decide anything) and the rest simply weren't in this change's scope.

**How it works, briefly:** the backend's `GET /api/v1/system/modules/mcp-tools` returns a manifest of every currently-registered module tool, built with the registered tool name always prefixed by its declaring module's key (e.g. `compliance_list_standards`), `mutates` derived from the HTTP method rather than declared by the module, and any tool that would resolve to a route still marked `openapi_extra=APPROVAL_ACTION_ROUTE_EXTRA` excluded from the manifest entirely regardless of what the module declares (neither Compliance's nor Decision Management's `approve`/`reject` routes carry this marker any longer — both resolve normally, then hit the same runtime `allow_ai_approvals` opt-in described above). This server fetches that manifest lazily and authenticated (never at an unauthenticated boot-time call), caching it in-process for up to 10 minutes by default (`MODULE_TOOLS_REFRESH_SECONDS`). Each declarative tool is a plain proxy call to the module's own REST endpoint — no module code ever runs inside this server's own process. A mutating module tool is only ever registered when write mode is enabled, the same gate this server's own write tools use.

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
