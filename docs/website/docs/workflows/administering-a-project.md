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

**Project Admin → Structure** shows the project's components and their categories as a collapsible tree, with the prefix and the number of requirements beside each row. Search by name or prefix opens the matches, and the tree remembers which components you left open.

| The Structure page: components with their prefixes and requirement counts, and Requirement aliases beneath |
| --- |
| ![Project admin Structure page showing a collapsible list of components with category counts, prefixes and requirement counts, and an Add component button](../../static/img/screenshots/project-admin-structure.png) |

| Add component: the prefix is suggested from the name and can be edited |
| --- |
| ![Add component side panel with the name Software Design and the suggested prefix SD](../../static/img/screenshots/structure-add-component.png) |

- **Add component** (the primary button) and each component's **Add category** open a small form. The **prefix** is suggested from the name, for example `SW` for "Software" and `SWD` for "Software Design", and is yours to edit: if it is already used by a sibling the suggestion takes the next free number (`SW2`), and a name with no letters or digits suggests nothing. A prefix is unique among the project's components, and a category's prefix is unique within its component.
- A row's actions menu edits it, moves it up or down, and deletes it. A category can also be **moved to another component**: its requirements, their aliases and other placed records move with it and sit in the new component. Codes already issued never change, and new requirements take the new component's prefix.
- Renaming or changing a prefix never changes already-issued requirement IDs, only new ones.
- Deleting a category that holds nothing needs only a confirmation; if requirements or other placed records are in it, the dialog asks which category to move them to. A component is deleted only after its categories are deleted or moved.
- A requirement's form chooses its component and its category as one pair from this tree, and the Requirements list filters by the same tree (see [Components on every record](../core-features/components-on-records.md)).

## Record codes

**Project Admin → Settings → Record codes** sets the letters new records of each type start their code with, for this project only (`ADR-006` instead of `DEC-006`). A type with no value of its own follows the nearest parent project that sets one, then the organisation's setting (see [Administering an organisation → Record code prefixes](./administering-an-organisation.md#record-code-prefixes)), then the built-in prefix; **Use inherited value** clears the project's own. The rules are the organisation's: two to five letters, different for every record type, never a project code or the organisation code. Codes already issued never change. A project made from a template, and a project bundle export and import, carry the project's own prefixes; an import numbers its records afresh with the destination's prefix.

| Project Admin → Settings → Record codes |
| --- |
| ![Record codes section of the project settings with a prefix field for each record type](../../static/img/screenshots/project-record-codes.png) |

## Custom fields

**Project Admin → Custom fields** defines additional attributes on requirements or change requests — short text, long text, checkbox, or a fixed list of options. These appear automatically on the create/edit forms and are versioned along with everything else.

## Link types

**Project Admin → Fields & actions → Link types** lists the organisation's link types (and any a parent project defined) with a **Hide** toggle each, and lets the project add link types of its own. The organisation can switch this off, which shows the list read-only. See [Links and traceability → Link types for one project](../core-features/links-and-traceability.md#link-types-for-one-project).

## Tags

**Project Admin → Tags** sets whether anyone who can tag a record may coin a new tag or only the listed ones, and lets you add, rename, colour, merge, reclassify and delete the project's tags, and shows where each tag is used by kind of record. A child project follows its parent's list until it adds a tag of its own. See [Tags](../core-features/tags.md#keeping-the-list-tidy-project-admin--tags).

## Reports

**Project Admin → Reports** holds the project's report layouts, report packs and where each report appears. Introductions, chapters and appendices are written in a layout; the organisation has one report look, so there is no branding to pick when generating. See [Reports and export](../core-features/reports-and-export.md#introductions-chapters-and-appendices).

## Terminology

**Project Admin → Terminology** renames how a fixed set of nouns (project, stage, component, category, requirement, change request) are labelled in this project's UI, for a team with different internal vocabulary — the override reaches the nav, list-page headings, and every other surface those words appear on, not just the settings page itself.

## Navigation names

Under **Project Admin → Settings**, below Terminology, **Navigation names** renames an entry of the project navigation (for example Decisions to ADRs). The new name is shown in the navigation, as the page title and as the back link from that entry's records; the nouns inside sentences are unchanged, and are set under Terminology. Each row shows the built-in name and a box for the name to use instead. A name inherited from a parent project or from the organisation appears in the box as a grey suggestion with its source, and is replaced by typing your own. **Restore** empties a row, and **Save names** applies the change at once. A name has at most 40 characters of plain text, and only project managers can change it.

## Project groups

**Project Admin → Project groups** lists the project's four fixed role groups — Members, Project Administrators, Project Managers, Stakeholders — each showing its actual members by name/email, with a picker to add and a button to remove. Rather than assigning roles one person at a time, add someone (or a whole organisation-level group) to the group matching the access they need.

## Adding external users

The picker used to add someone (or an organisation-level group) directly to the project normally only searches your organisation's own members. Typing a full email address that isn't already a member can also surface a result — **Add** for an existing account elsewhere in the system, or **Invite** for a brand-new one — if the organisation's admin has enabled it (**Advanced settings → External users on projects**, see [Administering an organisation](./administering-an-organisation.md)). Picking a person, group, or email match stages it in a list rather than granting anything immediately — set (or change) each staged entry's own role, add as many more as you need, then commit them all with one button press. An existing account is added right away once committed; a brand-new one gets an email to finish signing up — either way, the project role you picked is waiting for them as soon as they can sign in.

## Modules

**Project Admin → Modules** has one on/off switch per module (sub-components behind a collapsed summary). A new project starts with the organisation's defaults; later changes to those defaults don't affect it. A hint shows when this project differs from the organisation's default for new projects. A module or sub-component the organisation has turned **Off** is greyed out with an explanation — only an org admin can make it available again.

| Project admin: Modules |
| --- |
| One switch per module; sub-components collapsed behind a summary |
| ![Project admin Modules tab: Compliance, Decision Management and Context & Strategy each with one switch, Context & Strategy's sub-components collapsed](../../static/img/screenshots/project-admin-modules.png) |

See [Administering an organisation → Modules](./administering-an-organisation.md#modules) for the organisation's availability settings, and [Modules → Overview](../modules/overview.md) for the full gating mechanics.

## Settings

**Project Admin → Settings** holds project-wide flags: whether ordinary members (not just stakeholders/administrators/managers) can submit [change requests](./change-requests.md), whether the project is **usable as a project template** for new projects, and the **Export project bundle** action for backing up or migrating a project. See [Core Features → Project templates](../core-features/project-templates.md) and [Core Features → Zip export/import](../core-features/zip-export-import.md).

## Archiving a project

**Project Admin → Archive project** hides it from the default project list (it still appears with the Archived filter applied) without deleting any data.

## Where this fits

See [Custom fields, terminology, and templates](../concepts/custom-fields-terminology-and-templates.md) for why these live at the project level rather than a global setting, [Stages, baselining, and reviews](./stages-baselining-and-reviews.md) for the stage-sequence configuration also reached from Project Admin, and [Administering an organisation](./administering-an-organisation.md) for the organisation-level counterpart.
