---
sidebar_position: 5
---

# Generic / other MCP clients

Any MCP client that supports the Streamable HTTP transport (the current, non-deprecated transport — SSE is legacy) can use this server with just two things:

- **URL**: `http://<host>:8100/mcp` (or wherever it's deployed/proxied).
- **Header**: `Authorization: Bearer <a ReqTrackManager access token>`.
- **Optional headers**: `X-Default-Organization-Id`/`X-Default-Project-Id` — see [Overview → Default organisation/project scope](./overview.md#default-organisationproject-scope), useful if this client only ever talks to one project/organisation.

No OAuth flow, no client registration, no server-specific SDK — it's a standard MCP server over plain HTTP with one required header (plus the two optional ones above). See the [MCP specification](https://modelcontextprotocol.io/specification) for the wire protocol itself, and [Authenticating](../authenticating.md) for where the token comes from.

## Where this fits

See [Overview](./overview.md) for what's available once connected, and [Deploying for remote clients](./deploying-for-remote-clients.md) if your client isn't on the same network as the server.
