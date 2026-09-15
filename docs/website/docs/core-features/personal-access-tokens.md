---
sidebar_position: 10
---

# Personal access tokens

## What a PAT is for

A personal access token (PAT) is a long-lived credential for non-interactive tools — a script calling the REST API directly, or an MCP server — that shouldn't need to re-authenticate every 12 hours the way an interactive browser session does. A PAT never grants more access than the account that created it already has.

## Creating a token

From **Preferences → Personal Access Tokens**, click **New personal access token**: give it a name, choose which organisation(s) it can access, optionally narrow it to specific projects within them (leave every project unchecked for a token that follows the account's full organisation-level access), and pick an expiry — the picker warns if a chosen lifetime exceeds what the server allows.

| Creating a token |
| --- |
| Scoping a new token to an organisation, optionally narrowed to specific projects |
| ![New personal access token dialog with organisation and project scoping](../../static/img/screenshots/pat-create-dialog.png) |

The token's value is shown once, at creation — it isn't retrievable again afterward, only revoked and replaced with a new one.

## Using and revoking a token

Pass the token as `Authorization: Bearer <token>` on API requests. From the same Personal Access Tokens page, an existing token can be revoked at any time, immediately invalidating it.

## Where this fits

See [API & Integrations → Authenticating](../api-integrations/index.md) for how a PAT is used to call the REST API or connect an MCP client, and [Workflows → Preferences and help](../workflows/index.md) for the end-to-end task walkthrough.
