"""
Module: modules.compliance.enums

Compliance-owned vocabulary, kept here rather than in `app.models.enums` because the Compliance module owns these
concepts.

Stored: `ComplianceStandardVersionStatus` (`ComplianceStandardVersion.status`); `ComplianceStatus` and
`ComplianceApplicability` (`ProjectComplianceRequirement.compliance_status` / `.explicit_applicability`);
`ComplianceApprovalState` (`.approval_state`, default `NOT_ASSESSED`; folded into the overall status by
`service.summarize_project_compliance`); `ComplianceReviewStatus` (`ComplianceReview.status`: a review's lifecycle is
event history, not derivable from a date); `ComplianceStandardApplicabilityDefault`
(`ComplianceStandard.applicability_default`).

Computed, never stored, so a queryable derived value cannot drift: `ComplianceApplicabilitySource`
(`service.resolve_applicability`), `ComplianceEvidenceValidityState` (`service.compute_evidence_validity_state`, §14) and
whether a `SCHEDULED` review is upcoming, due or overdue (`service.compute_review_schedule_state`, §17).
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

    This is the vocabulary
    `ProjectComplianceRequirement.status` uses. Deliberately
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

    Belongs to `ProjectComplianceRequirement`,
which also carries the hierarchical-inheritance/explicit-
    override machinery §9 requires. `NOT_APPLICABLE` is deliberately a first-
    class value here, not the absence of a row: per §31, "Not Applicable is
    an explicit applicability decision, not simply an absence of assessment."
    """

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class ComplianceApprovalState(str, enum.Enum):
    """Formal approval/sign-off state of a project's compliance assessment
    against one requirement (§12).

    Belongs to the approval workflow, which also needs the full state-machine transition history (§16)
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
    """How a `ProjectComplianceRequirement`'s effective applicability was determined (§9 "Hierarchical Applicability":
    the UI distinguishes explicit, inherited and overridden values). Computed at read time by
    `service.resolve_applicability`, not stored.

    EXPLICIT covers a user-set value and the undecorated Applicable default (no decision, no Not Applicable ancestor);
    both render without a badge, unlike INHERITED and OVERRIDDEN.
    """

    EXPLICIT = "explicit"
    INHERITED = "inherited"
    OVERRIDDEN = "overridden"


class ComplianceEvidenceValidityState(str, enum.Enum):
    """A `ComplianceEvidence` row's current validity, derived from `expiry_date` at read time (§14) by
    `service.compute_evidence_validity_state` (rule and warning window there) and never stored. It is independent of
    `is_archived`: archived evidence still has a state, though the expiring and expired listings exclude it.

    `NO_EXPIRY` is distinct from `VALID` (§14 treats "no expiry date" and "expiry not yet reached" as different
    facts), so a reminder sweep can tell nothing to ever warn about from currently fine.
    """

    NO_EXPIRY = "no_expiry"
    VALID = "valid"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"


class ComplianceReviewStatus(str, enum.Enum):
    """Lifecycle state of a `ComplianceReview` row (§17).

    A review starts `SCHEDULED`. `COMPLETED` is terminal and retained (§17: completed reviews are compliance history);
    recording an outcome creates a new `SCHEDULED` row for the next cycle when `recurrence_days` is set, rather than
    reopening the completed row. There is no `CANCELLED` or `OVERDUE` member: whether a `SCHEDULED` review is upcoming,
    due or overdue is computed against `next_due_date` (`service.compute_review_schedule_state`).
    """

    SCHEDULED = "scheduled"
    COMPLETED = "completed"


class ComplianceReviewOutcome(str, enum.Enum):
    """Outcome recorded when a `ComplianceReview` is completed (§17); `None` until completion.

    There are three values, not the met/failed pair of `RequirementReviewOutcome`: a compliance review is an audit-style
    event that commonly finds follow-up work without failing, which `ACTION_REQUIRED` captures.
    """

    SATISFACTORY = "satisfactory"
    ACTION_REQUIRED = "action_required"
    UNSATISFACTORY = "unsatisfactory"


class ComplianceStandardApplicabilityDefault(str, enum.Enum):
    """A `ComplianceStandard`'s default project-assignment mode.

    `OPT_IN` (the default) means a project acquires the standard only by explicit assignment (Project Manager
    self-service or a Compliance Manager acting for the project), one project at a time. `APPLIES_TO_ALL_PROJECTS` is the
    centrally mandated case: switching a standard to it creates a `ProjectCompliance` row for every current non-archived,
    non-excluded project of the organisation (`service.reconcile_standard_applicability`), and a project created later
    gets the same at creation (`ModuleDefinition.on_project_created`). Only a Compliance Manager (or organisation or
    server admin) may set it; a Project Manager acts only on their own project's assignment row (§3).
    """

    OPT_IN = "opt_in"
    APPLIES_TO_ALL_PROJECTS = "applies_to_all_projects"
