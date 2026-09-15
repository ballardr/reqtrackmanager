---
sidebar_position: 2
---

# Two-factor auth and personal access tokens, security angle

Both features already have their own how-to pages — [Core Features → Two-factor authentication](../core-features/two-factor-authentication.md) and [Core Features → Personal access tokens](../core-features/personal-access-tokens.md) — so this page doesn't repeat the setup steps. It covers *why* each exists and what it protects against, which is the framing that matters when deciding whether/how to require them for an organisation.

## Why a second factor exists

A password alone is a single point of failure: reused across sites, phished, or leaked in an unrelated breach, and an attacker who has it can sign in as that user with nothing else standing in the way. Time-based one-time-password (TOTP) two-factor authentication adds a second, independent factor — something the account holder has (an authenticator app), not just something they know — so a compromised password alone is no longer sufficient to sign in.

An organisation can go further and **require** 2FA for every member (**Organisation admin → Security → Advanced settings**), enforced server-side rather than merely suggested in the UI: a member of an organisation that requires it can still log in with just their password, but nothing else in that organisation works until they've completed enrolment. For an organisation whose requirements data carries real regulatory or contractual weight, this closes the gap between "2FA is available" and "2FA is actually in use by everyone with access."

## Why personal access tokens, not shared credentials

The alternative to a Personal Access Token (PAT) is sharing a real account's session credentials with a script or third-party tool — which has no expiry control, no way to scope it down to less than the account's full access, and no way to revoke just that one use without also logging the human out of everything else. A PAT addresses all three:

- **Scoped**: narrowed to one or more organisations, optionally further to specific projects — a token given to an automated tool or an AI assistant can be handed less access than the creating account actually has, not the same access under a different name.
- **Expiring**: a mandatory expiry, with a server-enforced maximum lifetime an org admin controls — an abandoned token doesn't stay valid indefinitely.
- **Independently revocable**: revoking one PAT has no effect on the creating account's own session or any other token it holds.

This is what keeps the [REST API](../api-integrations/rest-api-overview.md) and [MCP server](../api-integrations/ai-assistants-mcp/overview.md) integration model from quietly expanding the effective privilege surface of connecting a script or an AI assistant: a PAT can never exceed the creating account's own access regardless of how it's scoped, and a leaked or over-scoped token is bounded by whatever scope was chosen at creation — not by everything the account could otherwise reach.

## Where this fits

- [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md) — how 2FA and PATs sit alongside the broader org/project role model.
- [API & Integrations → Authenticating](../api-integrations/authenticating.md) — using a PAT (or a session token) to call the REST API or connect an MCP client.
- [Encryption and secrets handling](./encryption-and-secrets-handling.md) — how a TOTP secret is protected at rest once enrolment is complete.
