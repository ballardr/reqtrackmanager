"""
Module: modules.compliance.enums

Compliance-module-owned vocabulary (docs/Compliance_Module_Requirements.md,
docs/compliance-module-plan.md Phase 5). Kept in this package rather than
`app.models.enums` since these are domain concepts the Compliance module
itself owns, not core ReqTrackManager concepts — consistent with Phase 5's
models living under `app.modules.compliance.models` rather than
`app.models`.

`ComplianceStandardVersionStatus` is consumed starting Phase 5 itself
(`ComplianceStandardVersion.status`). `ComplianceStatus` and
`ComplianceApplicability` are consumed starting Phase 7
(`ProjectComplianceRequirement.compliance_status`/`.explicit_applicability`).
`ComplianceApprovalState` is also a Phase 7 column
(`ProjectComplianceRequirement.approval_state`, defaulting `NOT_ASSESSED`),
added a phase ahead of the workflow that actually transitions it (Phase 9)
because §20's overall-status calculation — which Phase 7 itself must
define — folds approval state in (see `service.py::summarize_project_
compliance`); no endpoint moves a row off `NOT_ASSESSED` until Phase 9
ships. `ComplianceApplicabilitySource` is Phase 7's own addition, computed
(never stored) by `service.py::resolve_applicability`.

`ComplianceEvidenceValidityState` is Phase 8's own addition (§14), also
computed rather than stored — see `service.py::compute_evidence_validity_
state` — for the same "queryable derived state, not a stored one that can
drift" reason `ComplianceApplicabilitySource` already established.

`ComplianceReviewStatus`/`ComplianceReviewOutcome` are Phase 10's own
addition (§17). Unlike `ComplianceApplicabilitySource`/
`ComplianceEvidenceValidityState`, `ComplianceReviewStatus` *is* a stored
column (`ComplianceReview.status`) — a review's own lifecycle (scheduled ->
completed) is a real event history, not something derivable from a date
comparison the way evidence validity is. Whether a still-`SCHEDULED` review
is upcoming/due/overdue *is* computed, never stored, for the same
"can't drift" reason as the other two — see `service.py::compute_review_
schedule_state`.

`ComplianceStandardApplicabilityDefault` is Phase 20's own addition (second
human-review round; docs/compliance-module-plan.md Phase 20) — a stored
column (`ComplianceStandard.applicability_default`) recording whether a
standard's default project-assignment mode is the ordinary, fully-manual
per-project opt-in (every existing standard's unchanged behaviour) or an
org-wide "applies to all projects by default, except..." mandate. See
`models.py`'s own Phase 20 design-decisions section for the reconciliation
mechanism this drives.
"""

from __future__ import annotations

import enum


class ComplianceStandardVersionStatus(str, enum.Enum):
    """Lifecycle state of a `ComplianceStandardVersion` (§4).

    A version starts `DRAFT` (its requirements/required actions may still
    be edited), moves to `PUBLISHED` when a Compliance Manager publishes it
    (§3 — after which its requirements become immutable per §4's "must not
    silently alter historical compliance assessment"), and may later be
    `RETIRED` (no longer assignable to new projects, but never deleted —
    existing `ProjectCompliance` assignments must remain associated with
    their original version regardless of its current status, per §27).
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class ComplianceStatus(str, enum.Enum):
    """A project's assessed compliance state against one requirement (§10).

    Not used by any Phase 5 model — this is the vocabulary
    `ProjectComplianceRequirement.status` (Phase 7) will use. Deliberately
    *not* a field on `ComplianceRequirement` itself: per §31's "A Compliance
    Requirement must not contain the compliance state of a project,"
    compliance status is inherently project-specific.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    BLOCKED = "blocked"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"


class ComplianceApplicability(str, enum.Enum):
    """Whether a compliance requirement applies to a given project (§9).

    Not used by any Phase 5 model — belongs to `ProjectComplianceRequirement`
    (Phase 7), which also carries the hierarchical-inheritance/explicit-
    override machinery §9 requires. `NOT_APPLICABLE` is deliberately a first-
    class value here, not the absence of a row: per §31, "Not Applicable is
    an explicit applicability decision, not simply an absence of assessment."
    """

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class ComplianceApprovalState(str, enum.Enum):
    """Formal approval/sign-off state of a project's compliance assessment
    against one requirement (§12).

    Not used by any Phase 5 model — belongs to the approval workflow (Phase
    9), which also needs the full state-machine transition history (§16)
    this enum's values alone don't capture. `REQUIRES_REASSESSMENT` is the
    state an otherwise-`APPROVED` assessment moves to when material
    underlying information changes (evidence expiry, a standard version
    change) — per §31, "Approved compliance must be re-assessed/re-approved
    when material underlying information changes," never silently left
    `APPROVED`.
    """

    NOT_ASSESSED = "not_assessed"
    ASSESSED = "assessed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUIRES_REASSESSMENT = "requires_reassessment"


class ComplianceApplicabilitySource(str, enum.Enum):
    """How a `ProjectComplianceRequirement`'s *effective* applicability was
    determined (§9's "Hierarchical Applicability" — "The UI must clearly
    distinguish: Explicitly set applicability. Applicability inherited from
    a parent. An overridden inherited value."). Computed at read time by
    `app.modules.compliance.service.resolve_applicability`; not itself a
    stored column — see that function's docstring for the full resolution
    rule.

    EXPLICIT covers both "a user actively set this row's own applicability"
    and "nothing has been decided on this row and no ancestor says
    Not Applicable either" (the ordinary, undecorated Applicable default) —
    both render identically in the UI (no special badge), unlike INHERITED/
    OVERRIDDEN, which the UI must call out per §9.
    """

    EXPLICIT = "explicit"
    INHERITED = "inherited"
    OVERRIDDEN = "overridden"


class ComplianceEvidenceValidityState(str, enum.Enum):
    """A `ComplianceEvidence` row's *current* validity, derived from its
    `expiry_date` at read time (§14 — "The system must be able to
    identify: Valid evidence. Evidence approaching expiry. Expired
    evidence."). Computed by `service.py::compute_evidence_validity_state`,
    never stored — see that function's own docstring for the exact rule
    and the warning-window constant it uses. Independent of `ComplianceEvidence.
    is_archived`: archived evidence is still assigned a validity state (it
    simply isn't surfaced by the "expiring/expired" listings, which exclude
    archived rows) — "no longer applicable" (§13) and "no longer valid"
    (§14) are deliberately different questions.

    `NO_EXPIRY` is a distinct value from `VALID`, not folded into it: §14's
    own field list treats "has no expiry date at all" and "has an expiry
    date that hasn't been reached yet" as different facts about a piece of
    evidence, and a caller (e.g. a future Phase 10 reminder sweep) should
    be able to tell "nothing to ever warn about" apart from "currently
    fine, but will eventually need attention" without inspecting
    `expiry_date` itself.
    """

    NO_EXPIRY = "no_expiry"
    VALID = "valid"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"


class ComplianceReviewStatus(str, enum.Enum):
    """Lifecycle state of a `ComplianceReview` row (§17).

    A review starts `SCHEDULED`. `COMPLETED` is a terminal, retained state
    (§17's "Completed reviews must be retained as part of the compliance
    history") — recording an outcome creates a new `SCHEDULED` row for the
    next cycle when the review recurs (`ComplianceReview.recurrence_days`
    is set) rather than reopening/reusing the completed row, mirroring
    `RequirementReview`'s own "outcome recorded on a fresh row, the
    schedule field it satisfied is untouched" shape one level up. There is
    deliberately no `CANCELLED`/`OVERDUE` member: whether a `SCHEDULED`
    review is upcoming/due/overdue is a computed, point-in-time comparison
    against `next_due_date` (`service.py::compute_review_schedule_state`),
    not a state transition to persist — see this module's own docstring.
    """

    SCHEDULED = "scheduled"
    COMPLETED = "completed"


class ComplianceReviewOutcome(str, enum.Enum):
    """Outcome recorded when a `ComplianceReview` is completed (§17's
    "Review outcome"). `None` (nullable on the model) until completion.

    Three values, not `RequirementReviewOutcome`'s simpler met/failed pair:
    a compliance review is a broader audit-style event (§17's own examples
    include "Annual security compliance review," "Review after a
    significant standard change") that commonly identifies follow-up work
    without being an outright failure — `ACTION_REQUIRED` captures that
    middle outcome so it isn't forced into `SATISFACTORY` or
    `UNSATISFACTORY`.
    """

    SATISFACTORY = "satisfactory"
    ACTION_REQUIRED = "action_required"
    UNSATISFACTORY = "unsatisfactory"


class ComplianceStandardApplicabilityDefault(str, enum.Enum):
    """A `ComplianceStandard`'s default project-assignment mode (Phase 20).

    `OPT_IN` (the default for every standard, including every one that
    existed before this phase) is today's fully-manual behaviour: a
    project acquires this standard only via an explicit assignment
    (Project-Manager self-service or a Compliance Manager acting on a
    project's behalf), one project at a time. `APPLIES_TO_ALL_PROJECTS` is
    the org-wide, centrally-mandated case — switching a standard to this
    mode reconciles a real `ProjectCompliance` row into existence for
    every current non-archived, non-excluded project in the standard's
    organisation (`service.py::reconcile_standard_applicability`), and a
    project created afterward gets the same treatment at creation time
    (`ModuleDefinition.on_project_created`). Only a Compliance Manager (or
    org admin/server admin) may switch a standard into this mode — a
    Project Manager may act on their own project's own assignment row but
    never on this standard-level setting (§3).
    """

    OPT_IN = "opt_in"
    APPLIES_TO_ALL_PROJECTS = "applies_to_all_projects"
