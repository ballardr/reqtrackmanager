---
sidebar_position: 3
---

# Setting up VS Code (GitHub Copilot Chat)

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
        "Authorization": "Bearer ${input:reqtrack-token}",
        "X-Default-Project-Id": "<uuid, optional>"
      }
    }
  }
}
```

Open the Command Palette → **MCP: Add Server** → **HTTP** as an alternative to hand-writing the file, then paste the URL and let VS Code walk you through the input prompt. Click **Start** at the top of `mcp.json` to connect.

There's no `headersHelper` equivalent in VS Code today, so a token configured this way needs manually re-entering (Command Palette → **MCP: Add Server** again, or clear the stored input) once it expires — a [Personal Access Token](../authenticating.md) is the more convenient choice here than a 12-hour session token, since you'll re-enter it far less often. `X-Default-Project-Id`/`X-Default-Organization-Id` are optional (see [Overview → Default organisation/project scope](./overview.md#default-organisationproject-scope)) — add them as plain static entries in the same `"headers"` object, or drop the line entirely if you don't want a default scope.

## Where this fits

See [Overview](./overview.md) for what's available once connected.
