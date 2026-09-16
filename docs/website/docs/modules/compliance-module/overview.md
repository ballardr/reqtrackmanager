---
sidebar_position: 1
---

# Overview

The Compliance module lets an organisation define reusable compliance standards (an internal security standard, a regulatory obligation, or a customer-mandated framework), version them, and track each project's own compliance assessment against whichever standards it's assigned — independently of every other project. It ships as one of ReqTrackManager's built-in modules, enabled by default per organisation.

For example, an organisation might author "ISO 27001:2022" and "Customer Security Addendum" as two separate standards; a project serving that customer gets both assigned to it, while a purely internal project only carries the first. Each project's assessment against a standard — what's applicable, its compliance status, its evidence, its sign-off — lives entirely on that project's own assignment and never leaks into any other project's view of the same standard.

| Compliance standards |
| --- |
| An organisation's compliance standards, each tracked separately with its own issuing organisation and status |
| ![Compliance Standards list showing three standards with their issuing organisations and Active status](../../../static/img/screenshots/compliance-standards-list.png) |

## Enabling the module

Compliance defaults to **enabled** for every organisation. A server admin can turn it off deployment-wide (module entitlement), and an org admin can enable or disable it per organisation (module enablement) from the organisation's Modules settings — see [Modules → Overview](../overview.md#gating-entitlement--enablement) for the exact mechanics. Disabling it hides its navigation and endpoints for that organisation; no data is deleted.

## Roles

Compliance defines four of its own roles, module-contributed rather than new core role values (they render through the same role-management UI as every other role):

| Role | Scope | Grants |
| --- | --- | --- |
| **Compliance Manager** | Organisation | Creates and manages compliance standards, versions, requirements, and required actions; assigns standards to projects; views compliance across every project in the organisation. |
| **Compliance Officer** | Project | Modifies a project's compliance assessments, applicability decisions, and evidence, and performs approval/sign-off for the projects they're assigned to. |
| **Standards Manager** | One specific standard | Everything a Compliance Manager can do, but scoped to just this one standard — requirements, versions, publish/retire, and this standard's own "Members" roster. |
| **Standards Contributor** | One specific standard | May edit a draft version's requirements and required actions on this one standard, and propose/discuss changes — may not publish/retire a version or manage the standard's own membership. |

Both Compliance Manager and Compliance Officer compose with the roles that already carry equivalent authority elsewhere in ReqTrackManager: a server admin or an organisation's own org admin can do everything a Compliance Manager can; a project's Project Manager can do everything a Compliance Officer can, on that project. Every other project member (or org member, for standards) has read-only access — granted automatically once the module is enabled, with no role needed just to view.

**Standards Manager/Contributor** (a standard's own dedicated working group, for organisations that maintain standards internally) are narrower still: scoped to one specific standard, not every standard in the organisation. A Compliance Manager already satisfies either check with no per-standard grant needed. A standard's creator is automatically granted Standards Manager on it, and a standard must always have at least one Standards Manager — the last one can't be removed unless another explicit grant, or the organisation's designated fallback compliance-managers group, covers the floor. Manage this roster from a standard's own "Members" section — either role can be granted directly to a person, or to an org group as a whole.

For example, a security team that owns "ISO 27001:2022" end to end would typically hold Standards Manager on that one standard rather than the organisation-wide Compliance Manager role — they can author, publish, and retire its versions and manage its own membership, but can't touch a different team's standard, and don't automatically see every project's assessment the way a Compliance Manager would.

## In this section

- [Data model and standards lifecycle](./data-model-and-lifecycle.md) — how a standard, its versions, and a project's assessment relate to each other, and how a standard moves from draft to published to retired.
- [Assessing a project](./assessing-a-project.md) — assigning a standard, applicability, compliance status, required actions, evidence, approval/sign-off, and the resulting dashboards.
- [Scheduled reviews and notifications](./reviews-and-notifications.md) — recurring reviews and the background sweeps that keep people informed of what needs attention.
- [Cross-standard mapping and version migration](./mapping-and-migration.md) — relating requirements across standards, and moving a project's assignment onto a newer published version.
- [Reporting and export](./reporting-and-export.md) — PDF/CSV reports, and how compliance content travels through ReqTrackManager's export/import bundles.
- [AI assistant (MCP) integration](./mcp-integration.md) — the read-only tools an AI assistant can call against a project or organisation's compliance data.
- [Known limitations](./known-limitations.md) — what this module deliberately doesn't do yet.

## Where this fits

See [Modules → Overview](../overview.md) for how the module system itself works, and [Modules → Building your own module](../building-your-own-module.md) for how a module like this one is put together.
