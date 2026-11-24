---
sidebar_position: 7
---

# Lifecycles

Records such as Pain Points, Decisions, Strategies and Risks move through **states**: a Pain Point is Submitted, Triaged, Accepted, Addressed and Closed. A project can turn off the **optional** states it does not use, and an organisation can **require** states so no project turns them off.

```mermaid
flowchart LR
    S["Submitted"] --> T["Triaged (optional)"] --> A["Accepted"] --> D["Addressed"] --> C["Closed"]
    S -. "Triaged turned off" .-> A
```

## What can be turned off

| Record type | Optional states |
|---|---|
| Pain Point | Triaged |
| Open Question | Investigating |
| Decision | Proposed, Under review |
| Strategy, Future State | Proposed, Under review |
| Guiding Principle | Proposed |
| Risk | Treatment planned, Treatment in progress |
| Enhancement request | Under review |

A start state, an end state, a state outside the main path (Rejected, Withdrawn, Retired) and an **approval** state (Approved) are never optional. With the review steps of a Decision turned off, it goes from Draft to Approved through the same approval dialog, and only a person who holds the approval permission can do it.

## Turning a state off in a project

A project administrator opens **Project administration, Lifecycles**. Each record type lists its optional states with a checkbox; clear one and the record moves past it. The track under the type shows the path that results.

- A record that already sits in a state you turn off can still be opened, edited and moved on. Turning the state back on restores it.
- **Risks:** a step that is passed over still applies its checks. Moving a risk from Assessed to Mitigated with Treatment planned turned off still needs an owner and a treatment strategy.
- A nested project that has no choice of its own uses its parent project's choice, and says so. **Use inherited setting** returns to it.

## Requiring a state in an organisation

An organisation administrator opens **Organisation administration, Lifecycles** and selects **Require** beside a state. No project of the organisation can turn it off, and a project that had turned it off uses it again from then on; its records are not changed. The project's row shows **Required by the organisation** and cannot be edited.

To let one project keep its own choice, select **Exempt a project** under the type, choose the project and, if its nested projects are exempt too, **Include nested projects**. Removing the exemption makes the requirement bind the project again.

## Permissions

| Action | Permission |
|---|---|
| See a project's lifecycles | Any project member |
| Change a project's choice | **Manage project lifecycles** (project administrators and managers, organisation administrators) |
| Require a state, add an exemption | **Manage organisation lifecycles** (organisation administrators) |

Every change is recorded in the project's history (record type and state names only).

## Moving a record

A move the project does not allow is refused with the states that are allowed. The same rule applies to the application, the API and the MCP server.
