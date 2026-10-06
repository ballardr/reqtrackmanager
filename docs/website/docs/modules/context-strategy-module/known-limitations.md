---
sidebar_position: 22
---

# Known limitations

- **No Decision-target relationships yet.** `Strategy → Informs → Decision`, `Guiding Principle → Guides → Decision`, `Open Question → Resolved by → Decision`, and `Pain Point → Addresses → Decision` are all reserved but not built — blocked on [Decision Management](../decision-management-module/overview.md)'s own Phase 7 (reserved-relationship wiring), which hasn't been picked up yet even though both modules now ship. See [Relationships and types → Reserved relationship types](./relationships-and-types.md#reserved-relationship-types-not-yet-available).
- **No "resolve an Open Question into a Decision" workflow.** Blocked on the same reserved relationship above — an Open Question can be marked Resolved on its own, but there is no built-in conversion into a new Decision record yet.
- **No configurable type vocabulary for Guiding Principle.** Unlike Pain Point's two-tier org/project type system, a Guiding Principle has no `type` field at all — this was a deliberate scope decision for this module's Phase 4, not an oversight, but it means Guiding Principles can't currently be filtered or grouped by category the way Pain Points can.
- **No dedicated admin surface for per-artefact-type approval scoping.** As with Decision Management's own equivalent limitation, narrowing who may approve/activate/resolve a *specific* Strategy, Future State, Guiding Principle, or Open Question (rather than the flat, artefact-type-wide Approver/Resolver role) is possible only through the generic, org-wide Role Management page, not a dedicated control on this module's own screens.
- **An intentional limitation can't yet be linked to its product tier.** Pain Points can be flagged intentional and are reported separately ([Pain Point scoring](./pain-point-scoring.md#intentional-limitations), [R9 Upgrade drivers](./report-reference.md#r9-upgrade-drivers)), but the *intentional in* / *removed by* links to a product tier are reserved until the Product Tiers module exists, so R9 groups by Pain Point rather than by tier for now.
- **Some report gap lists are interim.** R2, R3 and R6 list gaps from the links that exist today; they become fuller once required-link rules and Decision links ship. R6's *Linked Decisions* column stays at zero until the Decision relationships above are built.
- **Organisation-wide R1 matrix colours come from one project.** When an organisation report spans projects with different rating-band overrides, the matrix uses the first project's bands.
- **Pain Point and Open Question have no supersession concept.** Unlike Strategy, Future State, and Guiding Principle, there's no "this record supersedes that one" relationship for either — a Pain Point believed obsolete is instead recorded as a **Duplicate of** another, and there's no equivalent mechanism for Open Question at all.

## Where this fits

See [Overview](./overview.md) for what the module *does* support.
