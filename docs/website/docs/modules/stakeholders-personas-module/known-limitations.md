---
sidebar_position: 29
---

# Known limitations

## Not built yet

- **Engagements aren't documented here yet.** The **Engagements** screens exist (the project's Engagements page, a "Log contact" shortcut and an engagement timeline on Stakeholder and Persona pages, and, when the off-by-default **Research extras** are on, session prompts, anonymous participants and findings), and Engagements can also be logged through AI assistants ([MCP](./mcp-integration.md)). A page walking through them is still to come.
- **Nothing compares contact to cadence yet.** A Stakeholder's "last engaged" date is derived from Engagements, but no report or screen flags a Stakeholder who is overdue against their target cadence.
- **No module reports.** The power/interest grid report, Persona validation, Need coverage and engagement staleness reports are planned but not built. A Stakeholder's grid position is shown on its own page only.
- **Persona weights aren't used for scoring yet.** The importance weight and its per-project override are stored and resolved, but scoring Pain Points per Persona is not available yet.
- **No Design or System Element relationships.** See [Relationships → Reserved](./relationships.md#reserved-design-and-system-element).

## By design

- **A Need is project-only.** There is no organisation-level Need, and no organisation Stakeholder or Persona can hold a Need that spans projects.
- **Hiding is per project, never org-wide.** A project hides an organisation Persona or Stakeholder from itself; there is no way to hide a record from every project short of archiving or retiring it.
- **Groups classify, they don't grant.** A [Stakeholder group](./stakeholder-groups.md) holds no permissions and is not a user or project group. A project's own groups are visible to that project only, not to its child projects; organisation groups reach every project.
- **Relationship status isn't shown.** A relationship lists the target's name but not its status, since each module owns its own statuses. Open the target to see it.
- **Pain Point and Decision links aren't carried in a project export yet.** A project export includes relationships to Requirements, but relationships to Pain Points and Decisions are exported and then skipped on import with a warning for each, because those modules' own records aren't part of the export yet.
- **No field-level restriction.** A Need's text and a Stakeholder's contact details are visible to everyone who can view the module in that project. A Persona never grants permissions.
- **Reverse view is not on other modules' pages.** "Who experiences this Pain Point?" is available through the API and an AI assistant, but the Pain Point and Decision pages don't list their Stakeholders and Personas yet.

## Where this fits

See [Overview](./overview.md) for what the module does support.
