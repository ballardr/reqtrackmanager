---
sidebar_position: 13
---

# Known limitations

- **Decision Approver is a single, flat, project-wide role.** There is no way yet to restrict who may approve Decisions of a specific Decision Type (e.g. only an "Architecture Approver" may approve an Architecture decision) — every Decision Approver on a project may approve, reject, or supersede any Decision in it regardless of type. Per-decision-type approver binding is planned once a future Fine-Grained Access Control module exists to express "which role can do what" generically, rather than this module building its own bespoke policy engine.
- **Six relationship types are reserved but not built.** Decision → Open Question / Pain Point / Strategy / Guiding Principle / Compliance / Design links are not available today — they're blocked on modules that don't exist yet (or, for Compliance, on integration work between the two modules that hasn't been done yet even though Compliance itself already ships). See [Relationships and templates → Reserved relationship types](./relationships-and-templates.md#reserved-relationship-types-not-yet-available).
- **No "Create Decision from Open Question" workflow.** Blocked on the same Context & Strategy module the Open Question relationship above is blocked on.

## Where this fits

See [Overview](./overview.md) for what the module *does* support.
