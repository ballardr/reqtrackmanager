---
sidebar_position: 13
---

# Known limitations

- **No Decision-Management-specific admin surface for per-Decision-Type approval.** Restricting who may approve a specific Decision Type is possible (see [Role Management → Per-Decision-Type approval scoping](../../core-features/role-management.md#per-decision-type-approval-scoping)), but it's configured entirely through the generic, org-wide Role Management page rather than a dedicated control on this module's own admin screens.
- **Six relationship types are reserved but not built.** Decision → Open Question / Pain Point / Strategy / Guiding Principle / Compliance / Design links are not available today — they're blocked on modules that don't exist yet (or, for Compliance, on integration work between the two modules that hasn't been done yet even though Compliance itself already ships). See [Relationships and templates → Reserved relationship types](./relationships-and-templates.md#reserved-relationship-types-not-yet-available).
- **No "Create Decision from Open Question" workflow.** Blocked on the same Context & Strategy module the Open Question relationship above is blocked on.

## Where this fits

See [Overview](./overview.md) for what the module *does* support.
