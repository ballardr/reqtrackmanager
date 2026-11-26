---
sidebar_position: 57
---

# Known limitations

## Not built yet

- **The Traceability half is not available.** Requirement types, traceability rules, traceability exceptions, traceability matrices and cross-project traceability are listed as sub-components, and a person with the right permissions sees them in the module's settings, but switching them on adds no screen or behaviour. See [Roadmap](../roadmap.md). Because traceability checks do not exist yet, no baseline check refuses a baseline for a missing link.
- **A project's lifecycle policy has no Governance screen of its own.** It is set on the existing [Lifecycles](../../core-features/lifecycles.md) page, which names the profile behind each required state.
- **Custom record states.** An organisation cannot define its own states for a record type. Each type keeps its states, locks and checks; a project's stage and component phases are the one exception, because they follow the kind of phase a [workflow](../../core-features/stages-and-baselining.md) defines.
- **No minimum number of approvers.** An approval policy adds roles that may approve; it cannot require two approvals.
- **Review interval is applied to Requirements and Risks.** For the other record types with a review schedule, the interval has no effect; the reminder lead and default owner do.

## By design

- **Policy only adds.** A project cannot relax an organisation's profile, and a profile cannot remove a default approver.
- **An Enforced profile can be lifted only by an exemption,** which an organisation administrator or Organisation Governance Manager adds. A server administrator has no bypass.
- **An import never relaxes an Enforced profile.** A project import carries no exemption and cannot choose away an Enforced profile.
- **A project's choice does not reach its nested projects.** Reach down the hierarchy is the organisation's decision.
- **Health shows counts, never titles.** A person without permission to view a record type sees no figure for it.
- **Baseline checks in a snapshot need a runner.** Without one, only a person pressing Refresh now runs them.
- **No tool deletes a profile, adds an exemption or approves anything.** Each stays a person's act.

## Where this fits

See [Overview](./overview.md) for what the module does support.
