---
sidebar_position: 2
---

# Setting up Claude Code

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

## Self-refreshing token (recommended for anything longer than a quick test)

Claude Code supports a `headersHelper` — a command it runs fresh on every connection and reconnect, and automatically re-runs (retrying the failed call once) if a tool call comes back 401/403. `mcp-server/scripts/get_auth_header.sh` is written exactly for this: it logs in and prints the header JSON `headersHelper` expects.

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

This requires a native, 2FA-disabled account — see the script's own docstring, and [Authenticating](../authenticating.md#the-manual-way--call-the-login-endpoint-directly) for why a 2FA-enabled account can't complete a non-interactive login this way. Check `claude mcp list` afterward; it reports `✔ Connected`, `! Needs authentication`, or `✘ Failed to connect` per server.

## Where this fits

See [Overview](./overview.md) for what's available once connected, and [Authenticating](../authenticating.md) for where the token itself comes from — a [Personal Access Token](../authenticating.md#the-recommended-way--a-personal-access-token) works here too, in place of a session token.
