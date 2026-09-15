---
sidebar_position: 12
---

# Administering a project

**Project Admin** (in a project's nav) is where a project manager or administrator configures everything about the project short of its actual requirement content.

| Project admin |
| --- |
| Settings tab: project template flag, bundle export, and other project-wide settings |
| ![Project admin settings tab](../../static/img/screenshots/project-admin-settings.png) |

## Components and categories

**Project Admin → Categories** shows the two-level tree — each category belongs to exactly one component, and its prefix only needs to be unique within that component. Both can be renamed inline (renaming never changes already-issued requirement IDs, only new ones going forward). Deleting a category requires picking another to reassign its requirements to; deleting a component requires it to have no categories left under it first.

## Custom fields

**Project Admin → Custom fields** defines additional attributes on requirements or change requests — short text, long text, checkbox, or a fixed list of options. These appear automatically on the create/edit forms and are versioned along with everything else.

## Terminology

**Project Admin → Terminology** renames how a fixed set of nouns (project, stage, component, category, requirement, change request) are labelled in this project's UI, for a team with different internal vocabulary — the override reaches the nav, list-page headings, and every other surface those words appear on, not just the settings page itself.

## Project groups

**Project Admin → Project groups** lists the project's four fixed role groups — Members, Project Administrators, Project Managers, Stakeholders — each showing its actual members by name/email, with a picker to add and a button to remove. Rather than assigning roles one person at a time, add someone (or a whole organisation-level group) to the group matching the access they need.

## Adding external users

The picker used to add someone to a project group normally only searches your organisation's own members. Typing a full email address that isn't already a member can also surface a result — **Add** for an existing account elsewhere in the system, or **Invite** for a brand-new one — if the organisation's admin has enabled it (**Advanced settings → External users on projects**, see [Administering an organisation](./administering-an-organisation.md)). An existing account is added right away; a brand-new one gets an email to finish signing up — either way, the project role you picked is waiting for them as soon as they can sign in.

## Settings

**Project Admin → Settings** holds project-wide flags: whether ordinary members (not just stakeholders/administrators/managers) can submit [change requests](./change-requests.md), whether the project is **usable as a project template** for new projects, and the **Export project bundle** action for backing up or migrating a project. See [Core Features → Project templates](../core-features/project-templates.md) and [Core Features → Zip export/import](../core-features/zip-export-import.md).

## Archiving a project

**Project Admin → Archive project** hides it from the default project list (it still appears with the Archived filter applied) without deleting any data.

## Where this fits

See [Custom fields, terminology, and templates](../concepts/custom-fields-terminology-and-templates.md) for why these live at the project level rather than a global setting, [Stages, baselining, and reviews](./stages-baselining-and-reviews.md) for the stage-sequence configuration also reached from Project Admin, and [Administering an organisation](./administering-an-organisation.md) for the organisation-level counterpart.
