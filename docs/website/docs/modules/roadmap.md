---
sidebar_position: 5
---

# Roadmap

Compliance is the first module built on ReqTrackManager's [module system](./overview.md), and a number of further modules are being explored to extend the product beyond compliance and core requirements management. Everything below is a proposed direction, not a commitment — none of it is scheduled, none of it has started, and the list itself may change as each one is worked through in more detail. The order below is alphabetical and implies nothing about which, if any, comes first.

| Module | What it would add |
| --- | --- |
| Context & Strategy | An organisation's or project's strategy, pain points, future-state vision, guiding principles, and open questions, tracked as first-class, linkable content rather than left in a slide deck. |
| Decision Management | Formal decision records — type, approval, history, and supersession — so "why did we choose this" has an authoritative, linkable answer instead of living in a meeting note. |
| Deeper compliance integration | Extending the [Compliance module](./compliance-module/overview.md) that's already shipped so its assessments can draw on richer project content as the other modules below arrive — requirement libraries, risk, traceability, governance, decisions, engineering design, and verification actions. |
| Engineering Design | Design artefacts — hierarchical designs, options, revisions and baselines — with ownership, approval, and traceability back to the requirements and decisions that shaped them. |
| Governance & Policies | Organisation-defined lifecycle, approval, review, and baseline policies, plus governance checks and role assignments, so the rules a project must follow can be configured rather than only enforced through fixed core behaviour. |
| On-behalf-of recording | Recording that a decision or approval was actually made by someone other than the account updating the system, with a required reason and optional supporting evidence — for situations like a decision made in a meeting, where a project manager is the one transcribing someone else's call. |
| Reporting & Analysis | Configurable, generated outputs — business requirements documents, engineering specifications, gap analyses, traceability/coverage/compliance reports, decision logs, review packages — built from whichever of these modules a deployment has enabled. |
| Requirement types & libraries | Richer requirement typing (business/stakeholder/project-level) and organisation-level, reusable, versioned requirement sets that a project can adopt and baseline — deepening [Requirements management](../core-features/requirements-management.md) rather than replacing it. |
| Risk Management | Risks with categories, causes/events/consequences, configurable likelihood/severity ratings, ownership, treatment and mitigation, residual risk, and links to requirements, design, decisions, and verification. |
| Stakeholders & Personas | Stakeholders and personas, their roles, interests, needs, and priorities, and their relationships to requirements and pain points, including participation in reviews and approvals. |
| Traceability | Configurable traceability rules and mandatory relationships between artefact types, with validation, matrices, coverage reporting, and documented exceptions, within and across projects. |

Several of these would share common underlying infrastructure — most notably a generic way to relate different kinds of artefacts to each other (a decision to a requirement, a risk to a design, and so on) — designed once rather than rebuilt separately by each module that needs it.

## Where this fits

See [Overview](./overview.md) for how the module system these would build on already works, and [Compliance module](./compliance-module/overview.md) for the one module shipped today.
