---
sidebar_position: 7
---

# Known limitations

- **Read-only unless write mode is explicitly enabled, and narrow even then.** See [Overview → Write mode](./overview.md#write-mode). Voting, commenting, submitting/deciding change requests, recording review outcomes, marking a requirement completed, archiving, and file/link management are all still out of scope regardless of write mode — letting an AI assistant *author requirement content* is a deliberately smaller, safer surface than letting it act on the rest of the workflow, and approval-type actions specifically are excluded on principle, not just left for later.
- **No zero-click "click a button and you're connected" login.** Some MCP servers drive a full OAuth 2.1 authorization flow so a client can pop a browser automatically on first connection with no separate step. This server deliberately doesn't: building a spec-compliant OAuth 2.1 authorization server (PKCE, dynamic client registration, redirect URI validation, authorization-code/token storage) is a substantial undertaking to get right, and the underlying MCP framework's own documentation for the feature that would provide it explicitly warns it's an advanced pattern most users should avoid. `mcp-server`'s own `/login` page (see [Authenticating](../authenticating.md)) is the deliberately simpler alternative — one browser visit, a real login form, no new protocol surface — at the cost of pasting the resulting token into your client's config once rather than it happening invisibly.
- **SSO accounts can't use the automated login helper.** `get_auth_header.sh` does a single non-interactive native-credential login; an SSO account should get a Personal Access Token instead, or use `mcp-server`'s own `/login?org=<slug>` "Sign in with SSO" button for a one-off token.
- **Third-party data flow.** Once an AI tool (Copilot Studio, or any hosted assistant) is configured against this server, whatever content it retrieves is sent to that tool's own infrastructure as part of normal MCP tool-call responses — the same way it would be if a person pasted that content into the tool's chat window, but worth being deliberate about for any organisation with confidentiality commitments around its data.
- **Module-contributed tools are declarative, single-REST-call proxies only.** A module tool needing genuinely custom logic (multiple backend calls, non-trivial response shaping) would mean shipping real module code into this server's own process — a different, larger trust question this mechanism deliberately doesn't take on. See [Overview → Module-contributed tools](./overview.md#module-contributed-tools).

## Where this fits

See [Overview](./overview.md) for what the server *does* support, and [Authenticating](../authenticating.md) for the token model every limitation above is stated in terms of.
