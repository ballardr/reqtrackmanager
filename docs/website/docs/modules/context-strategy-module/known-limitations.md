---
sidebar_position: 22
---

# Known limitations

- **No Decision-target relationships yet.** `Strategy → Informs → Decision`, `Guiding Principle → Guides → Decision`, `Open Question → Resolved by → Decision`, and `Pain Point → Addresses → Decision` are all reserved but not built — blocked on [Decision Management](../decision-management-module/overview.md)'s own Phase 7 (reserved-relationship wiring), which hasn't been picked up yet even though both modules now ship. See [Relationships and types → Reserved relationship types](./relationships-and-types.md#reserved-relationship-types-not-yet-available).
- **No "resolve an Open Question into a Decision" workflow.** Blocked on the same reserved relationship above — an Open Question can be marked Resolved on its own, but there is no built-in conversion into a new Decision record yet.
- **No configurable type vocabulary for Guiding Principle.** Unlike Pain Point's two-tier org/project type system, a Guiding Principle has no `type` field at all — this was a deliberate scope decision for this module's Phase 4, not an oversight, but it means Guiding Principles can't currently be filtered or grouped by category the way Pain Points can.
- **No dedicated admin surface for per-artefact-type approval scoping.** As with Decision Management's own equivalent limitation, narrowing who may approve/activate/resolve a *specific* Strategy, Future State, Guiding Principle, or Open Question (rather than the flat, artefact-type-wide Approver/Resolver role) is possible only through the generic, org-wide Role Management page, not a dedicated control on this module's own screens.
- **Pain Point scoring is configuration only so far.** Organisations and projects can set up Severity/Frequency/Confidence levels, the default model and rating bands ([Pain Point → Scoring configuration](./pain-point.md#scoring-configuration)), but individual Pain Points can't be scored per persona yet — that needs Personas from the Stakeholders & Personas module first.
- **Pain Point and Open Question have no supersession concept.** Unlike Strategy, Future State, and Guiding Principle, there's no "this record supersedes that one" relationship for either — a Pain Point believed obsolete is instead recorded as a **Duplicate of** another, and there's no equivalent mechanism for Open Question at all.

## Where this fits

See [Overview](./overview.md) for what the module *does* support.
