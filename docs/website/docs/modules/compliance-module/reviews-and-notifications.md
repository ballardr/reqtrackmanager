---
sidebar_position: 4
---

# Scheduled reviews and notifications

Assessing a project once isn't the end of the story — a standard's own requirements, or a project's assignment to one, need periodic revisiting, and people need to actually find out when that's due rather than having to check every day. This page covers both halves of that: scheduled reviews, and the background notifications built on top of them.

## Scheduled reviews

A standard itself, or a project's assignment to one, can have one or more scheduled reviews, each carrying:

- A **frequency label** (e.g. quarterly, annually) describing the intended cadence.
- An optional **automatic recurrence** — if set, completing a review automatically schedules the next one.
- A **next-due date**.
- An **owner** — who's responsible for actually carrying it out.
- Once completed, a retained **outcome**.

Completing a recurring review creates the next cycle as a new row rather than reopening the old one, so review history is never overwritten. For example, a quarterly review of "Customer Security Addendum" completed on the 15th of the month, with its outcome recorded, immediately produces a new row due roughly three months out — the completed review stays exactly as it was recorded, and a later audit can see the full sequence of past outcomes rather than just the most recent one.

## Notification triggers

Daily background sweeps notify the relevant Compliance Officers/Managers about the following conditions. Each notification is sent at most once per underlying event, not repeated on every sweep — an evidence item that's already triggered its "expiring soon" notification won't send it again the next day just because the sweep ran again.

| Trigger | Who's notified | Fires when |
| --- | --- | --- |
| Evidence approaching or past expiry | Compliance Officers/Managers with access to the project | The evidence's own expiry date enters its "expiring soon" window, or passes |
| Required action approaching or past its due date | Compliance Officers/Managers with access to the project | The action's due date enters its "approaching" window, or passes |
| Scheduled review coming due or overdue | The review's owner, plus Compliance Officers/Managers | The review's next-due date enters its "coming due" window, or passes |
| Project's target compliance date approaching or passed | Compliance Officers/Managers with access to the project | The project's own target date (where set) enters its "approaching" window, or passes |
| A requirement assessed Non-Compliant | Compliance Officers/Managers with access to the project | The compliance status changes to Non-Compliant |
| An approval request, or an approval invalidated by a material change | The relevant approver, or Compliance Officers/Managers | A requirement is submitted for approval, or a previously Approved/Pending requirement is flagged Requires Re-assessment (see [Approval/sign-off](./assessing-a-project.md#the-five-things-an-assessment-tracks)) |

## Where this fits

See [Assessing a project](./assessing-a-project.md) for the assessment states these notifications are reacting to, and [Overview → Roles](./overview.md#roles) for who "Compliance Officers/Managers" resolves to on a given project.
