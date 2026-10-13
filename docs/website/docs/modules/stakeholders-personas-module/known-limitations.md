---
sidebar_position: 29
---

# Known limitations

## Not built yet

- **No organisation-wide reports.** The five [reports](./reports.md) cover one project, or a project and its sub-projects with **Include child projects**. An organisation-wide version would need its own organisation role.
- **Group filtering is on S1 and S4 only.** The Persona validation, Need coverage and Engagement & research yield reports have no Stakeholder group filter.
- **No automatic disposal.** An Engagement's **Retain until** date only flags it as review due. Someone must delete it.
- **No Design or System Element relationships.** See [Relationships → Reserved](./relationships.md#reserved-design-and-system-element).

## By design

- **An Engagement is project-only.** There is no organisation-level Engagement, so a shared organisation Stakeholder's "last engaged" date and the staleness report are judged per project, and a child project does not see its parent's contact history.
- **No MCP tool deletes personal data.** An AI assistant can log and link Engagements but cannot permanently delete a Stakeholder, an Engagement or anything attached to one.
- **A Need is project-only.** There is no organisation-level Need, and no organisation Stakeholder or Persona can hold a Need that spans projects.
- **Hiding is per project, never org-wide.** A project hides an organisation Persona or Stakeholder from itself; there is no way to hide a record from every project short of archiving or retiring it.
- **Groups classify, they don't grant.** A [Stakeholder group](./stakeholder-groups.md) holds no permissions and is not a user or project group. A project's own groups are visible to that project only, not to its child projects; organisation groups reach every project.
- **Relationship status isn't shown.** A relationship lists the target's name but not its status, since each module owns its own statuses. Open the target to see it.
- **Pain Point and Decision links aren't carried in a project export yet.** A project export includes relationships to Requirements, but relationships to Pain Points and Decisions are exported and then skipped on import with a warning for each, because those modules' own records aren't part of the export yet.
- **No field-level restriction.** A Need's text and a Stakeholder's contact details are visible to everyone who can view the module in that project. A Persona never grants permissions.
- **Reverse view is not on other modules' pages.** "Who experiences this Pain Point?" is available through the API and an AI assistant, but the Pain Point and Decision pages don't list their Stakeholders and Personas yet.

## Where this fits

See [Overview](./overview.md) for what the module does support.
