# Lifecycle track register (phase 62)

Part of [the platform review plan](platform-review-2026-11-19-plan.md). Every record type with states: its main path, off-path states, the forward move (Promote), the moves that became rows of the actions menu, the locked states and the dialog each move keeps. The rules are in the style guide's "Pattern: lifecycle track and Promote"; the track is `components/LifecycleTrack.tsx`.

**Status: closed 2026-11-24.** Every type below passes `lifecycle` to `RecordHeader`; `scripts/check_lifecycle_track.py` fails `transitions=` and `stateMenu=`.

## Types with a lifecycle

| Type | Main path | Off-path (one end step while current) | Promote (next forward move) | Actions-menu rows | Locked states | Dialog kept behind Promote |
|------|-----------|----------------------------------------|-----------------------------|-------------------|---------------|----------------------------|
| Requirement | Draft, Approved, Completed (Reviewed is shown only while a requirement holds that status; nothing in the product sets it) | Archived | Draft or Reviewed to Approved (project managers; others see a padlock); Approved to Completed | Revert completion | Approved, Completed | Approval comment |
| Change request | Draft, Submitted, In review, Approved | Rejected, Withdrawn | Draft to Submitted; Submitted or In review to Approved (project managers; others see a padlock) | Approve and clear completion (a completed target), Reject, Withdraw | none | Link-merge dialog when links are proposed |
| Strategy, Future state | Draft, Proposed, Under review, Approved, Active | Superseded, Retired | Each step to the next | Send back, Supersede, Retire | Approved, Active, off-path | Comment on Approved and Active |
| Guiding principle | Draft, Proposed, Approved, Active | Superseded, Retired | Each step to the next | Send back, Supersede, Retire | Approved, Active, off-path | Comment on Approved and Active |
| Pain point | Submitted, Triaged, Accepted, Addressed, Closed | Rejected, Duplicate | Each step to the next | Reject, Mark duplicate (at Triaged) | Closed, off-path | Comment on every move after Triaged |
| Open question | Open, Investigating, Ready for Decision, Resolved | Withdrawn | Each step to the next | Withdraw | Resolved, Withdrawn | Optional comment on the last two moves |
| Decision | Draft, Proposed, Under review, Approved | Rejected, Superseded | Each step to the next | Reject | Approved, Superseded | Approval comment |
| Risk | Identified, Assessed, Treatment planned, Treatment in progress, Mitigated, Closed | Accepted, Transferred, Avoided, Realised, Rejected | Each step to the next; an outcome to Closed | Every other allowed move (Return to, Mark as) | Accepted | Comment on every move |
| Product feedback request | New, Under review, Accepted, Delivered | Declined, Duplicate | Each step to the next (triagers; others see a padlock) | Return to review, Back to new, Reopen, Decline, Undo merge | none | Comment |
| Persona, Stakeholder, Stakeholder need | Draft, Active | Retired | Draft to Active | Retire, Reactivate (from Retired) | none | Optional comment |
| Architecture element, connection, diagram, state machine | Draft, Proposed, Active | Retired, Rejected | Draft to Proposed, Proposed to Active (when the server allows it) | Activate directly (Draft), Return to draft, Reject, Retire, Reactivate, Reopen as draft | none | none (a server refusal is a toast) |

## Not a lifecycle

| Where | Reason |
|-------|--------|
| Action outcome (Pending, Completed, Failed) | A free choice among outcomes with no path; stays a select. |
| Compliance evidence validity | A validity indicator, not a state path; its Revalidate is a row of the actions menu. |

## Optional states (phase 65)

A project may turn off these states and an organisation may require them (`ModuleDefinition.lifecycles`, `docs/modules.md` section 4l15). Approval states and the ends of a path are never optional; requirement and change request have no optional state.

| Type | Optional states | Gated |
|------|-----------------|-------|
| Pain point | Triaged | none |
| Open question | Investigating | none |
| Decision | Proposed, Under review | Approved |
| Strategy, Future state | Proposed, Under review | Approved |
| Guiding principle | Proposed | Approved |
| Risk | Treatment planned, Treatment in progress | Accepted |
| Product feedback request | Under review | none |

Types that keep their fixed path: requirement, change request, persona, stakeholder, stakeholder need and the architecture types.
