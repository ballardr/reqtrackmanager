---
sidebar_position: 5
---

# Change requests

## Proposing a change

Once a requirement is locked, go to the project's **Change Requests** page (its own **Make a change request** link also appears directly on the requirement's own detail page):

1. Choose **new requirement** or **modify requirement**. For "modify requirement," pick the requirement first, then tick a checkbox for each field you actually want to change — only ticked fields become editable, pre-filled from the current value, and only ticked fields are proposed. Anything left unticked stays untouched when the change request is approved.
2. Give a **reason** for the change — required either way.
3. **Submit** it. This notifies the project's managers and stakeholders.

By default only stakeholders, administrators, and managers can submit change requests; a project setting (**Project Admin → Settings**) can open this up to ordinary members too.

## Deciding a change request

A project manager or administrator opens the change request and **approves** or **rejects** it, with an optional decision note:

- **Approve** applies only the ticked fields to the target requirement (creating it, for a "new requirement" change request) and notifies the requester. A proposed attachment is only actually attached to the requirement once approved.
- **Reject** leaves the requirement untouched.

| Change request detail |
| --- |
| Tasks, advisory stakeholder votes, discussion, and approve/reject |
| ![Change request detail page with tasks, stakeholder votes, and discussion](../../static/img/screenshots/change-request-detail.png) |

Someone who submitted a change request never sees Approve/Reject controls on their own submission, even if they otherwise hold a role that could decide other change requests — separation of duties between proposing and approving a change is enforced by the server, not just hidden in the UI.

## Tasks and stakeholder votes

While a change request is open, anyone with access can:

- Add a **task** — a short description, an optional assignee and due date, and a done/not-done checkbox — for tracking follow-up work the change implies.
- Cast an **advisory stakeholder vote** (approve/reject, with an optional comment). This is a visible signal for whoever decides the change request; it never itself approves or rejects it. **View comments** next to the vote tally shows every comment left with a vote.

## Withdrawing a change request

The creator — or a manager, on their behalf — can withdraw a change request any time before it's decided.

## Where this fits

See [Change requests and baselines](../concepts/change-requests-and-baselines.md) for why the review workflow and separation of duties exist, [Core Features → Change requests](../core-features/change-requests.md) for the full field-by-field mechanics, and [Authoring and reviewing requirements](./authoring-and-reviewing-requirements.md) for what triggers the need for one in the first place.
