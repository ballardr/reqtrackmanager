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
