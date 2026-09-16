---
sidebar_position: 4
---

# Setting up Microsoft Copilot Studio

Copilot Studio's native MCP wizard supports header-based API-key authentication directly, which lines up with this server's pass-through design:

1. In your agent, go to **Tools → Add a tool → New tool → Model Context Protocol**.
2. **Server URL**: the publicly-reachable MCP endpoint — see [Deploying for remote clients](./deploying-for-remote-clients.md), since `localhost` won't be reachable from Copilot Studio's own infrastructure.
3. **Authentication type**: **API key**.
4. **Type**: **Header**.
5. **Header name**: `Authorization`.
6. **Value**: `Bearer <your-access-token>` — type the literal word `Bearer` followed by the token; Copilot Studio sends whatever you enter here as the header's raw value, it doesn't add the scheme prefix for you.
7. **Create**, then **Add to agent**.

Because Copilot Studio's connection is configured once per connector rather than refreshed per-session the way Claude Code's `headersHelper` can, use a [Personal Access Token](../authenticating.md) here rather than a 12-hour session token.

The wizard above only configures one header (the `Authorization` API key), so it has no dedicated slot for the optional `X-Default-Organization-Id`/`X-Default-Project-Id` headers described in [Overview → Default organisation/project scope](./overview.md#default-organisationproject-scope) — if your Copilot Studio setup supports adding further custom headers to an MCP connector beyond this wizard's single API-key field, add them there the same way; otherwise, have the assistant pass `project_id`/`organization_id` explicitly on each tool call instead.

## Where this fits

See [Overview](./overview.md) for what's available once connected, and [Deploying for remote clients](./deploying-for-remote-clients.md) for exposing this server outside `localhost` in the first place.
