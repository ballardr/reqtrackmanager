---
sidebar_position: 11
---

# Administering an organisation

Reach an organisation's admin page via **My organisations** in the nav, or from **Preferences → Your access**'s **Manage organisation** link — see [Organisations and projects](./organisations-and-projects.md#finding-your-organisations) for both routes in context.

| Organisation admin |
| --- |
| Users, groups, and organisation-wide settings |
| ![Organisation admin page showing users and settings](../../static/img/screenshots/org-admin.png) |

## Managing users

The **Users** section lists every member, with access-review filters useful for periodic review: stale logins (180+ days), accounts without 2FA, and accounts with no project access at all. Once an accepted email domain is set (see below), it also lists existing accounts elsewhere in the system matching that domain but not yet members.

## Managing groups

**Groups** let you assign organisation-level roles to a set of users at once rather than one at a time — the same building block [project groups](./administering-a-project.md#project-groups) use one level down.

## Shared resource files

**Shared resources** are files that aren't specific to one requirement or change request — a standards document, a reference spec — available to link into any project in the organisation and to append as an extra section on a generated report. See [Core Features → File attachments and shared resources](../core-features/file-attachments-and-shared-resources.md).

## Branding and report templates

Set the organisation's logo and, under **Templates & reports**, define **report templates** (accent colour, cover page, footer text) and organisation-wide **report defaults** (introduction/chapters/appendices) that a project falls back to wherever it leaves its own report content blank. See [Core Features → Reports and export](../core-features/reports-and-export.md).

## Single sign-on

Configure an identity provider for the organisation under **SSO** — see [API & Integrations → Single sign-on](../api-integrations/index.md) for the full setup.

## Advanced settings

**Advanced settings** controls organisation-wide policy:

- Whether every member is **required to have 2FA enabled** — a member who hasn't enrolled can still sign in but can't use anything else in the organisation until they do.
- Whether **self-signup** is allowed for an accepted email domain, on top of the server-wide sign-up mode a server admin controls (see [Server administration](./server-administration.md)).
- Whether and how **external users** can be added to the organisation's projects — see [Administering a project → Adding external users](./administering-a-project.md#adding-external-users).

## Seeing every project in the organisation

An org admin can see every project belonging to the organisation — including ones without a direct role on them — from the admin page's **Projects** section. This is visibility into which projects exist, not a grant of access to their requirements or change requests; see [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md) for why that distinction is deliberate.

## Organisation overview isn't here

The read-only **Organisation overview** stats page (project/requirement/member counts, storage used) is visible to any member, not just admins, so it's covered under [Organisations and projects → Organisation overview](./organisations-and-projects.md#organisation-overview) instead of here.

## Where this fits

See [Organisations and projects](../concepts/organisations-and-projects.md) for the containment model this page administers, and [Administering a project](./administering-a-project.md) for the project-level counterpart to everything here.
