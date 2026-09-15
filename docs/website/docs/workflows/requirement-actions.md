---
sidebar_position: 7
---

# Requirement actions

## Creating an action

Go to a project's **Actions** page and click **New action**:

1. Give it a title and pick an **action type** (project-defined — e.g. "Review" or "Test," configured in **Project Admin → Fields & actions**).
2. Optionally set an assignee and due date.

| Action detail |
| --- |
| An action's outcome, assignee, due date, linked requirements, and discussion |
| ![Action detail page showing outcome, assignee, and linked requirements](../../static/img/screenshots/action-detail.png) |

## Linking an action to requirements

From the action's detail page, link it to any requirement it helps satisfy — one test run or audit can be linked from several requirements at once, since a link doesn't duplicate the action. Unlinking removes just that association, not the action itself.

Once a requirement is locked, adding or removing an action link to it goes through a [change request](./change-requests.md) instead of a direct edit, the same lock that governs the requirement's own fields.

## Recording an outcome

Open the action and record its outcome — **Pending**, **Completed**, or **Failed** — which stamps who recorded it and when. An action carries its own discussion thread and file attachments, separate from any requirement it's linked to.

## Finding and archiving actions

The **Actions** list filters by type and outcome. **Include archived** brings back actions that have been archived rather than deleted — like requirements, actions are never hard-deleted, only archived, preserving the record of what was done.

## Where this fits

See [Core Features → Requirement actions](../core-features/requirement-actions.md) for how an action differs from a requirement's own review-date fields, and [Authoring and reviewing requirements](./authoring-and-reviewing-requirements.md) for scheduling a review directly on a requirement instead.
