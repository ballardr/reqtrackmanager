# MCP server: reading (and, optionally, writing) requirements from an AI assistant

ReqTrackManager ships a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server — `mcp-server/` — that exposes requirements, change requests, notifications, and review schedules as tools an AI assistant can call directly, instead of a person copy-pasting content into a chat window. It runs as its own container, talks to the same REST API everything else uses, and is meant to be reachable by both local developer tools (Claude Code, VS Code Copilot Chat) and remote/hosted ones (Microsoft Copilot Studio) — see [Deploying it for remote clients](#deploying-it-for-remote-clients-copilot-studio-etc) below.

Read-only by default. An opt-in **write mode** (`MCP_WRITES_ENABLED=true`) additionally lets an AI assistant *author* requirement content — create new requirements and edit unlocked ones — narrowly scoped and with a structural guarantee that no tool, in either mode, can ever approve or decide anything. See [Write mode](#write-mode) below, and [docs/decisions.md](decisions.md)'s "MCP server write mode" entry for the full design rationale, including why this is this project's deliberately-preferred way to let AI act on the system at all (rather than building a bespoke AI backend/model into the product itself).

## What it can do

Fifteen read tools, always available:

| Tool | Purpose |
| --- | --- |
| `list_organizations` | Organisations the caller's account belongs to or administers |
| `list_projects` | Projects the caller has a role on, optionally filtered by organisation or a name/summary search |
| `get_project` | A single project's detail |
| `list_requirements` | Requirements in a project, with the same filters the UI's filter panel offers (status, component, category, keyword, or a name/code search) |
| `get_requirement` | A single requirement's full current detail |
| `get_requirement_history` | A requirement's full version history — every prior state, who changed it, and why (C-A-09) |
| `list_change_requests` | Change requests in a project, optionally filtered by status |
| `get_change_request` | A single change request's full current detail |
| `list_change_request_votes` | A change request's advisory stakeholder vote tally and individual votes (C-R-03) |
| `list_change_request_tasks` | Follow-up tasks tracked against a change request (C-R-02, C-R-04) |
| `list_change_request_comments` | The discussion thread on a change request |
| `list_requirement_comments` | The discussion thread on a requirement |
| `list_notifications` | The caller's own in-app notifications, optionally unread-only |
| `list_my_reviews_due` | Requirements assigned to the caller with a review date that has passed, across every project |
| `list_project_reviews_due` | Every requirement in a project with a review date that has passed, regardless of assigned reviewer |

Plus two write tools, only when [write mode](#write-mode) is enabled:

| Tool | Purpose |
| --- | --- |
| `create_requirement` | Creates a new requirement (always starts in "draft") |
| `update_requirement` | Edits an unlocked requirement's content — a partial update; cannot touch `status` |

No tool, in either mode, can vote, comment, decide a change request, or record a review outcome — and, in write mode, `update_requirement` cannot approve or complete a requirement either. See [Known limitations](#known-limitations) for what's deliberately out of scope and why.

A backend module can also contribute its own tools here, prefixed with that module's key (e.g. `compliance_list_standards`) — see [Module-contributed tools](#module-contributed-tools) below. None are registered today; this repository has no module with tools yet.

## Write mode

Off by default (`MCP_WRITES_ENABLED` unset or anything other than `true`/`1`/`yes`/`on`) — a deployment operator must explicitly opt in before this server can change any data at all, and when it's off, `create_requirement`/`update_requirement` don't just refuse to run, they don't exist: an MCP client's tool list never mentions them. Set `MCP_WRITES_ENABLED=true` on the `mcp-server` container's environment to turn it on (the bundled dev/test stack, `tests/container/docker-compose.yml`, already does; the production `docker-compose.yml` at the repo root defaults it off).

**Requirement content only, never workflow state.** `update_requirement` has no `status` parameter at all — there is no way to make it approve, complete, or otherwise transition a requirement through this server, regardless of what the calling account's own role could do directly via the API. Attempting to edit an already-approved (locked) requirement is rejected with a clear error telling the caller a change request is needed instead; this server has no tool to create or decide one.

**Why approval specifically stays human-only, structurally, not just by convention:** ReqTrackManager's approval workflow (a Project Manager approving a requirement, or deciding a change request) is only meaningful if every approval represents a real person taking accountability for that decision. The backend's own RBAC would *correctly* let a PM-privileged caller approve something through this server if a tool offered it — RBAC isn't wrong here, it's just answering a different question ("is this account allowed to?") than the one that matters for this specific action ("did an accountable human actually decide this, right now, deliberately?"). So this boundary is enforced at this server's own tool surface — by never exposing the capability in the first place — rather than left to the backend's per-account authorization to (correctly, but insufficiently) gate.

**Still exactly the same pass-through authentication and authorization as every read tool** (see [Authentication model](#authentication-model) below) — write mode doesn't add a second permission model, it just adds two more tools that happen to issue `POST`/`PUT` requests instead of `GET`. The caller's own account still needs a requirement-editing project role (stakeholder, administrator, or manager) for either write tool to succeed, exactly as the UI would require.

**What's still not exposed, even with write mode on** — a deliberately narrow first cut, not an oversight: submitting or deciding a change request, voting, commenting, recording a review outcome, marking a requirement completed, archiving/deleting, uploading attachments, and creating traceability links. All read-only-adjacent for now (each already has a read tool where relevant); a natural, larger follow-up if any of them is wanted later — see [Known limitations](#known-limitations).

## Module-contributed tools

Beyond the hand-written tools above, a backend module (compliance-module-plan.md Phase 4 — Compliance is the first module planned to use this, though none does yet) can declare its own tools that this server registers automatically, without any module-specific code living in this file. See [docs/modules.md](modules.md#6-module-contributed-mcp-tools) for the full design writeup aimed at someone building a module; this section covers only what a deployment operator or an MCP client needs to know.

**How it works, briefly:** the backend's `GET /api/v1/system/modules/mcp-tools` (normal bearer-token authentication, no exemption) returns a manifest of every currently-registered module tool, already mechanically verified on the backend side — the registered tool name is always prefixed with its declaring module's key (e.g. `compliance_list_standards`), `mutates` is derived from HTTP method rather than declared by the module, and any tool that would resolve to an approval/decision-type action is excluded from the manifest entirely, the same "approval stays human-only" principle [Write mode](#write-mode) above already applies to this server's own hand-written tools. This server fetches that manifest **lazily and authenticated** — never at an unauthenticated boot-time call — using whichever connecting session's own already-presented token first triggers a refresh within a cache window (`MODULE_TOOLS_REFRESH_SECONDS`, default 600 seconds / 10 minutes); the result is cached in-process and reused across every session until the next refresh. Each declarative tool is a plain proxy call through the same `_call_backend` helper every hand-written tool above uses — no module's own code ever runs inside this process.

**A mutating module tool is only registered when `MCP_WRITES_ENABLED=true`** — the same gate this server's own `create_requirement`/`update_requirement` already use, applied generically rather than per-tool.

**Nothing to configure for the common case.** With no module registered yet in the backend (the state of this repository today — Compliance itself doesn't land until a later phase), the manifest is simply an empty list and this section has no visible effect. Once a module with tools is registered and enabled for at least one organisation, its tools appear in this server's tool list automatically, within one refresh window (or immediately after this server restarts). `MODULE_TOOLS_REFRESH_SECONDS` is the only new environment variable this mechanism adds, and only needs changing if the default 10-minute cache window is too slow or too chatty for a given deployment.

## Authentication model

**This server holds no credentials of its own and performs no authorization itself.** Every tool call requires the *caller* to present their own ReqTrackManager access token — either the JWT a normal login issues, or a Personal Access Token (see [Getting a token](#getting-a-token)) — as an `Authorization: Bearer <token>` HTTP header on the MCP connection. The server does nothing more than relay that exact header to the backend API on every request it makes on the caller's behalf, entirely format-agnostic about which kind of token it's forwarding; the backend's own existing, already-tested RBAC (plus, for a PAT, its own organisation-scope restriction) does 100% of the access-control work.

This was a deliberate choice over the alternative (the MCP server logging in once as a fixed "integration" service account): a shared service account would mean every user of this MCP server sees whatever that one account can see — the opposite of this project's per-user, per-project access model, and a much larger blast radius if that one credential ever leaked. With pass-through auth, an AI assistant using this server can never see anything the person configuring it couldn't already see themselves through the normal UI or API. There is no second permission model to design, audit, or get wrong.

Concretely, this means:

- **No Authorization header at all** → the tool call fails immediately with a clear message telling you to configure one. It never silently returns an empty result.
- **An expired or otherwise-invalid token** → the backend's own 401 is surfaced as a clear tool error. Native-login access tokens are short-lived (12 hours by default — `ACCESS_TOKEN_EXPIRE_MINUTES`) and there is currently no longer-lived "API token" concept in ReqTrackManager, so a token used here needs periodic refreshing the same way a browser session would. See each client's setup section below for how to make that less painful — Claude Code in particular can refresh it automatically.
- **A valid token for an account with no access to a given org/project/requirement** → the backend's own 403 (or 404, for something that doesn't exist) is surfaced exactly as calling the REST API directly would produce.

### Getting a token

**The recommended way — a Personal Access Token.** In the app itself, go to **Preferences → Personal Access Tokens**, give it a name, pick which organisation(s) it should be able to reach, and create it. Unlike a normal login session (12 hours by default), a PAT lives as long as its scoped organisation(s) allow — up to 90 days by default, or whatever an org admin has configured — so an MCP client configured with one keeps working for weeks without needing reconfiguring. Paste the resulting `rtm_pat_...` token into any of the client configs below exactly where a session token would go; `mcp-server` doesn't need to know or care which kind of token it's forwarding. See [docs/decisions.md](decisions.md)'s "Personal Access Tokens" section for the full design (scoping, revocation, and how its expiry is computed), and your org admin if you need a token to live longer than the current cap allows.

A token is shown exactly once, at creation — copy it immediately. You (or an org/server admin, for incident response) can revoke it at any time from the same Preferences page; revocation takes effect on the token's very next use, not after some delay.

**The quick way — the server's own `/login` page**, if you just need something working right now and don't need it to outlive a 12-hour session. Visit `http://localhost:8100/login` (or wherever `mcp-server` is deployed) in a browser. It's a plain HTML sign-in form served by `mcp-server` itself — no separate service, nothing to install. Enter your ReqTrackManager email and password (and a TOTP code afterward, if your account has 2FA enabled); the page relays those credentials to the backend's own `POST /api/v1/auth/login` (and `/api/v1/auth/2fa/verify` for the 2FA step) on your behalf, one time, and then shows you the resulting access token plus ready-to-paste config snippets for Claude Code and VS Code.

A few things worth knowing about this page:

- It never authenticates as its own account — it's a convenience wrapper around the same login endpoint you'd otherwise call directly, not a new credential store or a new auth mechanism. Everything in [Authentication model](#authentication-model) above still applies.
- Your password is sent once, server-side, straight through to the backend's login endpoint, and is never written to a log, a file, or anywhere else.
- The token is only ever shown in the page's response body — never in a URL — and the response is sent with `Cache-Control: no-store` so it isn't cached anywhere along the way.

**SSO accounts**: if your organisation has SSO enabled, visit `http://localhost:8100/login?org=<your-org-slug>` instead (ask your admin for the slug, same as you would for the app's own org-branded `/login/{slug}` page). This shows a "Sign in with SSO" button that redirects through your identity provider's real login page — if your browser already has an active session there, it comes straight back with a token, no form to fill in at all (the same "already logged in → it just works" experience as tools like VS Code's Azure DevOps MCP server). Under the hood this reuses ReqTrackManager's existing OIDC login flow (`docs/decisions.md`'s "MCP server: expanded tool set..." section has the full design writeup, including why this doesn't require a custom OAuth authorization server) — landing on `/login/oidc/complete` instead of the main app once you're back.

**The manual way — call the login endpoint directly**, useful for scripting or automation:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"your-password"}'
```

This returns `{"access_token": "...", ...}` for an account without 2FA. An account with 2FA enabled instead returns a short-lived challenge token that must be exchanged via `POST /api/v1/auth/2fa/verify` with a current TOTP code — fine for a one-off manual token, but not something a non-interactive script (like the `headersHelper` below) can complete on its own; use a 2FA-disabled account for automated setups.

Consider creating a dedicated account for AI-assistant use rather than reusing a real person's login — its access is scoped by whatever real ReqTrackManager role you give it, same as any other account (a project-`stakeholder`-only account, for instance, can only ever retrieve that project's requirements through this server).

## Running it

Part of both Compose stacks already — no extra step beyond the normal `docker compose up`:

```bash
cd tests/container && docker compose up -d --build   # dev/test; also available in the root docker-compose.yml
```

It listens on `:8100`, with the MCP endpoint at `http://localhost:8100/mcp` and a plain liveness check at `http://localhost:8100/health`. `REQTRACK_API_URL` (default `http://backend:8000`, the Compose-internal address) points it at the backend.

## Setting up Claude Code

**Quick, static token** (simplest; you'll need to re-run this when the token expires):

```bash
claude mcp add --transport http reqtrackmanager http://localhost:8100/mcp \
  --header "Authorization: Bearer <your-access-token>"
```

Or in `.mcp.json` directly, with environment-variable expansion so the token isn't committed to the repo:

```json
{
  "mcpServers": {
    "reqtrackmanager": {
      "type": "http",
      "url": "http://localhost:8100/mcp",
      "headers": {
        "Authorization": "Bearer ${REQTRACK_TOKEN}"
      }
    }
  }
}
```

**Self-refreshing token (recommended for anything longer than a quick test)**: Claude Code supports a `headersHelper` — a command it runs fresh on every connection and reconnect, and automatically re-runs (retrying the failed call once) if a tool call comes back 401/403. `mcp-server/scripts/get_auth_header.sh` is written exactly for this: it logs in and prints the header JSON `headersHelper` expects.

```json
{
  "mcpServers": {
    "reqtrackmanager": {
      "type": "http",
      "url": "http://localhost:8100/mcp",
      "headersHelper": "REQTRACK_URL=http://localhost:8000 REQTRACK_EMAIL=you@example.com REQTRACK_PASSWORD=your-password mcp-server/scripts/get_auth_header.sh"
    }
  }
}
```

(Requires a native, 2FA-disabled account — see the script's own docstring.) Check `claude mcp list` afterward; it reports `✔ Connected`, `! Needs authentication`, or `✘ Failed to connect` per server.

## Setting up VS Code (GitHub Copilot Chat)

VS Code's MCP support uses `.vscode/mcp.json` with an `inputs` array so the token is prompted for once and stored securely, rather than committed to the file:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "reqtrack-token",
      "description": "ReqTrackManager access token (from POST /api/v1/auth/login)",
      "password": true
    }
  ],
  "servers": {
    "reqtrackmanager": {
      "type": "http",
      "url": "http://localhost:8100/mcp",
      "headers": {
        "Authorization": "Bearer ${input:reqtrack-token}"
      }
    }
  }
}
```

Open the Command Palette → **MCP: Add Server** → **HTTP** as an alternative to hand-writing the file, then paste the URL and let VS Code walk you through the input prompt. Click **Start** at the top of `mcp.json` to connect. There's no `headersHelper` equivalent in VS Code today, so a token configured this way needs manually re-entering (Command Palette → **MCP: Add Server** again, or clear the stored input) once it expires.

## Setting up Microsoft Copilot Studio

Copilot Studio's native MCP wizard supports header-based API-key authentication directly, which lines up with this server's pass-through design:

1. In your agent, go to **Tools → Add a tool → New tool → Model Context Protocol**.
2. **Server URL**: the publicly-reachable MCP endpoint — see [Deploying it for remote clients](#deploying-it-for-remote-clients-copilot-studio-etc) below, since `localhost` won't be reachable from Copilot Studio's own infrastructure.
3. **Authentication type**: **API key**.
4. **Type**: **Header**.
5. **Header name**: `Authorization`.
6. **Value**: `Bearer <your-access-token>` — type the literal word `Bearer` followed by the token; Copilot Studio sends whatever you enter here as the header's raw value, it doesn't add the scheme prefix for you.
7. **Create**, then **Add to agent**.

Because Copilot Studio's connection is configured once per connector rather than refreshed per-session the way Claude Code's `headersHelper` can, use a Personal Access Token here rather than a 12-hour session token — see [Getting a token](#getting-a-token) above.

## Generic / other MCP clients

Any MCP client that supports the Streamable HTTP transport (the current, non-deprecated transport — SSE is legacy) can use this server with just two things:

- **URL**: `http://<host>:8100/mcp` (or wherever it's deployed/proxied).
- **Header**: `Authorization: Bearer <a ReqTrackManager access token>`.

No OAuth flow, no client registration, no server-specific SDK — it's a standard MCP server over plain HTTP with one required header. See the [MCP specification](https://modelcontextprotocol.io/specification) for the wire protocol itself.

## Deploying it for remote clients (Copilot Studio, etc.)

A cloud service like Copilot Studio needs a publicly-reachable URL, not `localhost`. The same reverse-proxy pattern documented in [deployment.md](deployment.md#same-origin-subpath-deployment-avoiding-cors) for the REST API applies here — add one more `location` block:

```nginx
location /mcp/ {
    proxy_pass http://mcp-server:8100;
    proxy_set_header Host $host;
    # Streamable HTTP keeps a connection open for server-initiated
    # messages — make sure buffering/timeouts don't cut that off:
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

Then the MCP URL you give any remote client is `https://my.website.com/mcp/mcp` (the proxy's own `/mcp/` prefix, plus the server's own `/mcp` endpoint path underneath it) — or adjust the `location` match/`proxy_pass` target if you'd rather it resolve to a cleaner external path.

**Always put this behind TLS in production**, same as the rest of the stack (see deployment.md's "TLS and reverse proxy") — the bearer token travels in a plain HTTP header, exactly like every other authenticated request this app makes, and is only as safe as the transport it rides over.

## Known limitations

- **Read-only unless write mode is explicitly enabled, and narrow even then.** See [Write mode](#write-mode) above. Voting, commenting, submitting/deciding change requests, recording review outcomes, marking a requirement completed, archiving, and file/link management are all still out of scope regardless of `MCP_WRITES_ENABLED` — letting an AI assistant *author requirement content* is a deliberately smaller, safer surface than letting it act on the rest of the workflow, and approval-type actions specifically are excluded on principle, not just left for later (see Write mode's rationale). A natural, larger follow-up if any of the non-approval items is ever wanted.
- **No zero-click "click a button and you're connected" login.** Some MCP servers (Azure DevOps' among them) drive a full OAuth 2.1 flow so a client like VS Code can pop a browser automatically on first connection with no separate step. This server deliberately doesn't do that: building a spec-compliant OAuth 2.1 authorization server (PKCE, dynamic client registration, redirect_uri validation, authorization-code/token storage) is a substantial undertaking to get right, and `fastmcp`'s own documentation for the feature that would provide it explicitly warns "this is an extremely advanced pattern that most users should avoid." The `/login` page above is the deliberately-simpler alternative: one browser visit, a real login form, no new protocol surface — you still have to paste the resulting token into your client's config once, rather than it happening invisibly, but there's no custom authorization-server code to get wrong. See `docs/decisions.md` for the full writeup of this tradeoff.
- **~~No long-lived API token mechanism~~ — resolved.** Personal Access Tokens (Preferences → Personal Access Tokens) are exactly this: independently revocable, scoped to whichever organisation(s) their creator chooses, and long-lived by default (90 days unless an org sets its own cap) — see [Getting a token](#getting-a-token) above. Session tokens (12-hour lifetime) and Claude Code's self-refreshing `headersHelper` remain available as lighter-weight alternatives when a long-lived credential isn't wanted.
- **SSO accounts can't use the automated login helper.** `get_auth_header.sh` does a single non-interactive native-credential login; SSO accounts should use `/login?org=<slug>`'s "Sign in with SSO" button instead (see [Getting a token](#getting-a-token) above).
- **Third-party data flow.** Once an AI tool (Copilot Studio, or any hosted assistant) is configured against this server, whatever content it retrieves is sent to that tool's own infrastructure as part of normal MCP tool-call responses — the same way it would be if a person pasted that content into the tool's chat window, but worth being deliberate about for any organisation with confidentiality commitments around its data. See [docs/soc2/policies/vendor-and-subprocessor-management-policy.md](soc2/policies/vendor-and-subprocessor-management-policy.md) and [data-classification-and-confidentiality-policy.md](soc2/policies/data-classification-and-confidentiality-policy.md) for how this project's own compliance documentation treats that.
- **Module-contributed tools are declarative, single-REST-call proxies only.** A module tool needing genuinely custom logic (multiple backend calls, non-trivial response shaping) would mean shipping real module code into this server's own process — a different, larger trust question this mechanism deliberately doesn't take on. See [Module-contributed tools](#module-contributed-tools) above and [docs/modules.md](modules.md#6-module-contributed-mcp-tools).
