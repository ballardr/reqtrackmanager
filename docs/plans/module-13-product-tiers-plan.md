# Module 13 — Product Tiers — Implementation Plan

See [future-modules-2026-09-index.md](future-modules-2026-09-index.md) for
cross-cutting architecture. Not in the overview. Requested by the user on
2026-10-04 while scoping
[Module 1's Reporting extension](module-01-context-and-strategy-plan.md)
(Phase 9 Q9–Q11).

**Source:** user direction, 2026-10-04. A product may be sold in several
tiers (e.g. Standard and Pro), with some features enabled only in higher
tiers. Some pain points are therefore *intentional*: they push users to
upgrade. **Decided by: User.**

**Status:** Proposed, not started. Hard-depends on Module 0. Soft
dependency: Module 1, whose intentional Pain Point → Tier links stay
reserved until this module lands.

## Status / Resume Here

0 / 4 phases complete. Phase 0 is next.

| # | Phase | Status |
|---|-------|--------|
| 0 | Exploratory: scope & open questions | [ ] Not started |
| 1 | Data model: Tier, ordering, RBAC, nested fallback | [ ] Not started |
| 2 | Relationships (Requirement/Pain Point ↔ Tier) + frontend UI | [ ] Not started |
| 3 | Docs website coverage | [ ] Not started |

## Settled so far

- **"Tiers", not "versions."** "Version" implies a release over time; this
  module models parallel commercial packaging. **Decided by: Agent.**
- **Project-scoped**, with nested fallback. A child project with no tiers
  of its own uses its nearest ancestor's (the `resolve_effective_action_types`
  pattern), and tiers are seeded only on root projects. **Decided by:
  User.**
- **Tier is a relationship target, not a scoring dimension.** This avoids
  persona × tier scoring explosion in Module 1. **Decided by: Agent.**

## Phase 0 — open questions

1. **Ordered or unordered tiers?** Recommend ordered (Standard < Pro <
   Enterprise) with an explicit rank. "The tier that removes this pain
   point" and "upgrade path" only make sense with an order. Add-ons that
   aren't part of a ladder would need a separate concept, so confirm
   whether add-ons exist.
2. **Requirement → Tier applicability.** Is "feature X is Pro-only" a
   relationship (`available_in → Tier`) or a field on Requirement? A
   relationship keeps core Requirement untouched, per the module-boundary
   rule. Recommend a relationship.
3. **Inheritance between tiers.** Does Pro implicitly include everything
   in Standard? Recommend yes, derived from rank, so applicability is only
   recorded at the lowest tier that includes a feature.
4. **Scope creep guard.** Pricing, entitlement enforcement, and licensing
   are out of scope. This module describes tiers for requirements and
   context work; it doesn't run billing.

**Reasoning:** *Why:* product packaging drives which problems are fixed and
which are deliberate. *Risk addressed:* intentional limitations treated as
defects, and tier-specific features undocumented. *Expected outcome:* tiers
can be linked from Pain Points and Requirements, enabling Module 1's R9
"Upgrade drivers" report.
