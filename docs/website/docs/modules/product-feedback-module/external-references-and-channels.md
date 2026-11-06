---
sidebar_position: 45
---

# External references and channels

Delivery stays in your own tracker. A request points to the work with **external references**, and each requester says **how they asked** with a channel. Both are chosen from lists your organisation controls, so "Jira" is spelled one way everywhere.

## External references

A request can carry any number of references, each with:

| Field | Meaning |
| --- | --- |
| **System** | The tool, from the external system list (Jira, ServiceNow, Zendesk, Azure DevOps, GitHub, Other, or your own). |
| **Key** | The item's identifier, such as `FAL-214` or `INC0012345`. |
| **URL** | A link to the item. Only `http` and `https` links are accepted, and they open in a new tab. |
| **Role** | **Came from** (the ticket the request arose from) or **Delivered in** (where it is being built). |

The **External references** card on the request page adds, edits and removes them, and the create form has the same list. A reference is not a version of the request: it is changed on its own and audited, without creating a new version. A reference's system is stored by identity, so renaming a system renames it on every request.

External references are a [sub-component](./overview.md#enabling-the-module). With it off, the card, the form section and the **External Systems** settings are hidden, and stored references are kept for when it is switched back on. With it on but no enabled external system in the project (every one hidden or switched off), there is nothing to add a reference to, so the card and the form section are not shown either; a request that already has references still shows its card.

## Request channels

The channel records the route each requester used, set per requester from the [Demand section](./demand-and-merging.md#channel-per-ask). Out of the box: Engagement, Support ticket, Call, Chat, Conversation, Email, Survey, Internal and Other. The channel mix shows in the [Close the loop](./reports.md#close-the-loop-f3) report and the export.

## Managing the two lists

Both lists work the same way as the other type lists:

- The **organisation** owns the shared list, at **Organisation admin → External Systems** and **Request Channels** (Organisation admin or the Feedback List Admin role).
- A **project** adds entries of its own and can **hide** an organisation entry it does not use (and restore it) at **Project admin → External Systems** and **Request Channels**.
- A project with none of its own entries shows its nearest ancestor project's list, then the organisation's; its first change copies that list into it.
- Deleting an entry that requests use asks you to reassign them first.

Both lists, with the defaults a project hid, travel in the project and organisation bundles.

## Where this fits

See [Enhancement requests](./enhancement-request.md) for the request itself, and [Reports](./reports.md) for the channel mix.
