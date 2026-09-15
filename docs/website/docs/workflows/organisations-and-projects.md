---
sidebar_position: 3
---

# Organisations and projects

## Finding your organisations

Click **My organisations** in the nav's Global section (or reach the same admin page from **Preferences → Your access**, which additionally lists your role at each one) to see every organisation you belong to, with a **Manage organisation** link wherever you hold `org_admin`. If you belong to only one organisation, this skips straight to it rather than showing a one-item list to choose from. See [Administering an organisation](./administering-an-organisation.md) for what happens once you're there.

## Organisation overview

**Organisation overview** in the nav (visible to any member, not just admins) is a read-only stats dashboard for one organisation — project, requirement, and member counts, and total file storage used — the general-purpose equivalent of a project's own Overview page, one level up. Like the organisations list above, it resolves straight to your one organisation if that's all you belong to.

## Browsing and finding projects

Open **Projects** in the nav. The list is filterable by active/archived status, by your role on the project, by the project's current stage status, and — if you belong to more than one organisation — by which organisation it's in, and is searchable by name or summary. Each card shows the project's organisation and how many requirements it currently has.

| Projects list |
| --- |
| Filterable, searchable project list with role and organisation filters |
| ![Projects list with filters and search](../../static/img/screenshots/projects-page.png) |

Disabled organisations' projects are hidden by default; use the **All** filter to include them.

## Creating a project

Click **New project** from the Projects page — either blank, or **from a template** (any project in the organisation marked "usable as a project template," see [Core Features → Project templates](../core-features/project-templates.md)). Only an org admin or a project creator can do this; a plain member sees no create option. A [hierarchical project](../concepts/organisations-and-projects.md) can also be created as a sub-project of one you manage, from that parent project's own admin page.

## Favouriting a project

Click the star icon next to a project to favourite it — favourited projects always sort to the top of your list, regardless of any other filter or search applied. Once you have at least one, a **Favourites** link appears in the nav's Global section as a quick jump list.

## Opening a project

Click into a project to reach its **Overview** — a summary of its stage, requirement counts, and recent activity, and the jumping-off point for every other project page (Requirements, Change Requests, Actions, Files, Reports, Project history, Project admin).

| Project overview |
| --- |
| A project's overview: current stage, requirement counts, and recent activity |
| ![Project overview page](../../static/img/screenshots/project-overview.png) |

## Where this fits

See [Organisations and projects](../concepts/organisations-and-projects.md) for the containment model and project hierarchy this page's filters and cards reflect, and [Roles, groups, and access control](../concepts/roles-groups-and-access-control.md) for why being an org admin alone doesn't grant you access to a project's requirements — you still need a project role, which is where [Administering a project](./administering-a-project.md) picks up.
