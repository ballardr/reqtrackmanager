---
sidebar_position: 4
---

# Authoring and reviewing requirements

## Creating a requirement

From a project's **Requirements** page (or **New requirement** on the Overview page):

1. Pick a **component**, then a **category** belonging to that component — the category list narrows to match whichever component you've picked. Together they form the requirement's identifier, e.g. `SW-PERF-014`.
2. Give it a **name**, and optionally reasoning, a free-text description, and any project-specific custom fields your organisation has defined.
3. Pick a **target version** (the form pre-fills the project's first stage) and a **level** — Requirement, Recommended, or Optional.

| Requirements list |
| --- |
| Status, target version, and category filters; click a status badge to filter, click again to clear |
| ![Requirements list showing status badges, filters, and search](../../static/img/screenshots/requirements-list.png) |

While the project's current stage is still in scoping, requirements within a component/category can be reordered with the up/down arrows.

## Reviewing and editing a requirement

Open a requirement from the list to see its full detail: an editable form, its complete version history (who changed what, and when), a discussion thread, traceability links to other requirements, and file attachments.

| Requirement detail |
| --- |
| Editable fields, version history, and a discussion thread for one requirement |
| ![Requirement detail page with fields, change log, and discussion](../../static/img/screenshots/requirement-detail.png) |

Add a comment in the discussion thread for informal back-and-forth — this works even on a locked requirement, since it isn't part of the governed content. Attach a file to a comment with the paperclip icon while writing it, or while editing your own existing one.

A requirement's detail page also carries a **review date** and an assigned reviewer, tracked separately from stage-level review deadlines — see [Stages, baselining, and reviews → Scheduling and recording an individual review](./stages-baselining-and-reviews.md#scheduling-and-recording-an-individual-review).

## Marking a requirement completed

Once a requirement is approved, a project manager can mark it **Completed** from its detail page (and uncomplete it to correct a mistake) — a separate status from approval, for tracking which approved requirements have actually been delivered and verified, not just baselined.

## What happens once a requirement is locked

Once a requirement reaches **Approved** or **Completed** status, its edit form disables itself with a "Locked" badge. This isn't just a UI convention — the server rejects a direct edit attempt too, even bypassing the form entirely. Further changes go through a [change request](./change-requests.md) instead. See [Requirements, versions, and the lifecycle](../concepts/requirements-versions-and-lifecycle.md) for why locking exists.

Archiving and recreating a requirement with the same name doesn't dodge this history either — a new requirement always gets a distinct identifier, so there's no way to "become" an archived one and its version history stands unchanged.

## Where this fits

See [Core Features → Requirements management](../core-features/requirements-management.md) for the mechanics of every field and action on this page, [Reporting and CSV import/export](./reporting-and-csv-import-export.md) for bulk-loading requirements from a spreadsheet, and [Change requests](./change-requests.md) for modifying a locked requirement.
