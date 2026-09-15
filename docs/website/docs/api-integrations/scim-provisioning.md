---
sidebar_position: 5
---

# SCIM provisioning

SCIM (System for Cross-domain Identity Management, RFC 7643/7644) lets an identity provider push user and group changes into ReqTrackManager as they happen, rather than waiting for someone to log in. That's the key difference from OIDC-login-time sync (see [Single sign-on](./single-sign-on.md#how-a-user-gains-access-and-a-role)): SCIM can promptly deprovision someone who's stopped logging in, since it doesn't depend on a login happening at all.

## What it does

- **Users**: an IdP's `POST /scim/v2/Users` finds-or-creates a `User` by email and grants baseline membership in the calling organisation if the resolved account holds no role there yet. `DELETE` or a `PATCH` setting `active: false` deactivates the account rather than deleting it, consistent with every other user-removal path in the app.
- **Groups**: `POST`/`PATCH /scim/v2/Groups` manage this app's own organisation groups directly — a SCIM Group's `id` *is* the underlying `OrgGroup.id`, so there's no separate mapping table for an IdP to keep straight. Membership add/remove operations only ever touch direct user membership, never a group-nesting relationship — those are structural and admin-managed, and an IdP's roster can't rearrange them.

## Scope and limits — stated candidly

This is a pragmatic subset of the SCIM spec, not full compliance, documented the same way the rest of this project documents real gaps rather than hiding them:

- **Filtering** is limited to a single `attr eq "value"` expression (`userName eq`/`emails.value eq` for Users, `displayName eq` for Groups) — covers what Okta/Entra ID/Google Workspace actually send, not the full SCIM filter grammar.
- **PATCH** supports `active`/`displayName` replace on Users and `members` add/remove on Groups — again, what those same IdPs' provisioning engines actually send for deprovisioning and group-sync, not arbitrary path expressions.
- **No Bulk operations, no ETags/versioning, no schema extensions.** `/scim/v2/ServiceProviderConfig` and `/scim/v2/ResourceTypes` are supported (several IdP SCIM clients probe them during setup), but `/scim/v2/Schemas` introspection is not.

## Authentication: a per-organisation bearer token

SCIM calls come from the IdP's provisioning engine, not a logged-in browser, so they use a separate mechanism from everything else on this page: a **per-organisation bearer token**, managed from **Organisation admin → SCIM provisioning** (org-admin only). The raw token is shown exactly once, at generation; generating a new one immediately invalidates the previous one — there is only ever a single active token per organisation.

```
Authorization: Bearer <scim-token>
```

against `https://{host}/scim/v2/...`.

## Pointing a real IdP at it

- **Microsoft Entra ID** and **Authentik** both have first-party SCIM provisioning connectors — point them at `https://{host}/scim/v2` with the bearer token above and they handle the rest.
- **Keycloak** doesn't ship SCIM support out of the box (as of Keycloak 26) — it needs the community `keycloak-scim` extension, which isn't exercised by this project's own automated tests. The token generate → authenticated request → revoke cycle is still tested directly against this app's own SCIM endpoint, just not through a real Keycloak-mediated round trip the way the OIDC login flow is.

## Where this fits

- [Single sign-on (OIDC/SSO)](./single-sign-on.md) — the login-time counterpart; a group can be synced by either or both paths.
- [Workflows → Administering an organisation](../workflows/administering-an-organisation.md) — managing groups and the SCIM token in the UI.
