"""
Module: modules.compliance.service

Pure/near-pure business logic for the Compliance Module's Phase 7 project
compliance assessment layer (docs/compliance-module-plan.md Phase 7;
docs/Compliance_Module_Requirements.md §9, §20) — kept out of `project_
router.py`/`router.py` so it's independently testable and reusable by later
phases (Phase 9's approval workflow and Phase 10's scheduled reviews both
need "what is this assignment's current overall state" the same way Phase 7
does; Phase 6 had no equivalent need for a dedicated service module, so it
kept its logic inline in `router.py` — this phase's logic is different
enough, and reused widely enough later, to earn its own file).

Responsibilities:
- `resolve_applicability_for_version`: §9's hierarchical applicability
  resolution — computes each requirement's *effective* applicability and
  how it was determined (explicit/inherited/overridden), in one pass over
  a standard version's full requirement tree. Never stored — see
  `models.py`'s own docstring for why `ProjectComplianceRequirement.
  explicit_applicability` only ever holds what a user actually set.
- `materialize_assessment_rows`: creates one `ProjectComplianceRequirement`
  per `ComplianceRequirement`, and one `ComplianceRequiredActionAssessment`
  per `ComplianceRequiredAction`, for a newly-created `ProjectCompliance`.
- `summarize_project_compliance`: §20's overall status calculation — the
  exact, documented rule this phase is required to define. See that
  function's own docstring for the full rule.
- `compute_evidence_validity_state`/`build_evidence_out` (Phase 8, §14):
  the exact, documented "valid/expiring/expired" derivation for a
  `ComplianceEvidence` row — see `compute_evidence_validity_state`'s own
  docstring for the rule and its warning-window constant.
- `advance_approval_state_on_assessment`/`invalidate_approval_if_in_flight`
  (Phase 9, §12/§16/§27): the two state-machine transition rules a
  `ProjectComplianceRequirement`'s `approval_state` goes through outside
  the explicit `submit-for-approval`/`approve`/`reject` actions themselves
  (which are simple enough to stay inline in `project_router.py`, mirroring
  how Phase 7's own `update_requirement_applicability`/`update_requirement_
  assessment` never needed a service-layer wrapper for their own direct
  transitions either) — see each function's own docstring for the exact
  rule and why the two mutation-triggers (a fresh assessment vs. every
  other material change) transition differently.
- `compute_review_schedule_state`/`build_review_out`/`complete_review`
  (Phase 10, §17): the "upcoming/due/overdue" derivation for a `SCHEDULED`
  `ComplianceReview` (computed, never stored — mirrors `compute_evidence_
  validity_state`'s own reasoning), the response-schema builder, and the
  completion action's recurrence logic (creates the next cycle's row when
  `recurrence_days` is set — see that function's own docstring).
- `get_effective_compliance_officers`/`get_effective_compliance_managers`
  (Phase 10, §18): notification-recipient resolution for Compliance's own
  event-driven notifications (`router.py`/`project_router.py`) — deliberately
  *not* an authorization check (RBAC gating stays exactly
  `require_module_role`, unchanged), just "who should be told about this,"
  so a same-org/-project fan-out that misses an edge case (e.g. an org
  group granting `ORG_ADMIN`, which this codebase's groups don't support
  anyway — see each function's own docstring) is a missed notification, not
  a security gap.

External dependencies: `app.modules.compliance.models`/`.enums`, SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.compliance.enums import (
    ComplianceApplicability,
    ComplianceApplicabilitySource,
    ComplianceApprovalState,
    ComplianceEvidenceValidityState,
    ComplianceReviewOutcome,
    ComplianceReviewStatus,
    ComplianceStatus,
)
from app.modules.compliance.models import (
    ComplianceEvidence,
    ComplianceEvidenceActionLink,
    ComplianceEvidenceFile,
    ComplianceEvidenceRequirementLink,
    ComplianceRequiredAction,
    ComplianceRequiredActionAssessment,
    ComplianceRequirement,
    ComplianceReview,
    ComplianceReviewEvidenceLink,
    ComplianceStandard,
    ComplianceStandardVersion,
    ProjectCompliance,
    ProjectComplianceRequirement,
)
from app.modules.compliance.schemas import (
    ComplianceEvidenceOut,
    ComplianceReviewOut,
    ProjectComplianceRequirementOut,
    ProjectComplianceStatusOut,
)

ApplicabilityResolution = dict[uuid.UUID, tuple[ComplianceApplicability, ComplianceApplicabilitySource]]


def resolve_applicability_for_version(
    requirements: list[ComplianceRequirement],
    pcr_by_requirement_id: dict[uuid.UUID, ProjectComplianceRequirement],
) -> ApplicabilityResolution:
    """Resolves effective applicability + its source for every requirement
    in one standard version's tree, in a single pass (§9's "Hierarchical
    Applicability").

    Rule, applied per requirement, root-to-leaf:
    - If this row has its own `explicit_applicability`:
      - If the nearest resolved ancestor is effectively `NOT_APPLICABLE`
        and this row's explicit value is `APPLICABLE`, the effective value
        is `APPLICABLE` with source `OVERRIDDEN` (§9: "Child requirements
        may be individually overridden where the standard/process
        permits this").
      - Otherwise the effective value is this row's own explicit value,
        with source `EXPLICIT` (covers both "no conflicting NA ancestor"
        and "explicitly NOT_APPLICABLE with no ancestor override to
        speak of").
    - If this row has no explicit decision (`None`):
      - If the nearest resolved ancestor is effectively `NOT_APPLICABLE`,
        the effective value is `NOT_APPLICABLE` with source `INHERITED`
        (§9: "Parent marked Not Applicable -> child requirements are
        automatically considered Not Applicable").
      - Otherwise the effective value defaults to `APPLICABLE`, with
        source `EXPLICIT` — the ordinary, undecorated default; see
        `ComplianceApplicabilitySource`'s own docstring for why this
        shares a bucket with an actively-confirmed `APPLICABLE`.
    A requirement with no `ProjectComplianceRequirement` row at all (should
    not happen once materialisation has run, but handled defensively) is
    treated the same as one with `explicit_applicability=None`.

    Args:
        requirements: Every `ComplianceRequirement` in one standard
            version (any order — parent/child order is resolved
            internally via `parent_requirement_id`, not list order).
        pcr_by_requirement_id: This project's `ProjectComplianceRequirement`
            row for each requirement, keyed by `requirement_id`.

    Returns:
        A dict from `requirement_id` to `(effective_applicability, source)`,
        one entry per requirement given.
    """
    by_id = {r.id: r for r in requirements}
    resolved: ApplicabilityResolution = {}

    def _resolve(requirement_id: uuid.UUID) -> tuple[ComplianceApplicability, ComplianceApplicabilitySource]:
        if requirement_id in resolved:
            return resolved[requirement_id]

        requirement = by_id[requirement_id]
        pcr = pcr_by_requirement_id.get(requirement_id)
        explicit = pcr.explicit_applicability if pcr is not None else None

        parent_id = requirement.parent_requirement_id
        parent_effective = (
            _resolve(parent_id)[0] if parent_id is not None and parent_id in by_id
            else ComplianceApplicability.APPLICABLE
        )

        if explicit is not None:
            if (
                parent_effective == ComplianceApplicability.NOT_APPLICABLE
                and explicit == ComplianceApplicability.APPLICABLE
            ):
                result = (ComplianceApplicability.APPLICABLE, ComplianceApplicabilitySource.OVERRIDDEN)
            else:
                result = (explicit, ComplianceApplicabilitySource.EXPLICIT)
        elif parent_effective == ComplianceApplicability.NOT_APPLICABLE:
            result = (ComplianceApplicability.NOT_APPLICABLE, ComplianceApplicabilitySource.INHERITED)
        else:
            result = (ComplianceApplicability.APPLICABLE, ComplianceApplicabilitySource.EXPLICIT)

        resolved[requirement_id] = result
        return result

    for requirement_id in by_id:
        _resolve(requirement_id)
    return resolved


def materialize_assessment_rows(
    db: Session, *, project_compliance_id: uuid.UUID, standard_version_id: uuid.UUID
) -> None:
    """Creates one `ProjectComplianceRequirement` per `ComplianceRequirement`
    in `standard_version_id`, and one `ComplianceRequiredActionAssessment`
    per `ComplianceRequiredAction` under each of those requirements — the
    full, one-time materialisation a new `ProjectCompliance` assignment
    needs (see `models.py`'s own docstring for why this happens once, in
    full, rather than lazily: a published version's requirement/required-
    action set is immutable, so there is nothing to reconcile later).

    Every row starts at its column defaults (`NOT_STARTED`/`None`
    explicit applicability/`NOT_ASSESSED` approval/not completed) — this
    function does not accept or infer any initial values.
    """
    requirements = db.scalars(
        select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == standard_version_id)
    ).all()
    for requirement in requirements:
        pcr = ProjectComplianceRequirement(project_compliance_id=project_compliance_id, requirement_id=requirement.id)
        db.add(pcr)
        db.flush()

        required_actions = db.scalars(
            select(ComplianceRequiredAction).where(ComplianceRequiredAction.requirement_id == requirement.id)
        ).all()
        for action in required_actions:
            db.add(
                ComplianceRequiredActionAssessment(
                    project_compliance_requirement_id=pcr.id, required_action_id=action.id
                )
            )


class ProjectComplianceStatusSummary:
    """Plain data holder for `summarize_project_compliance`'s result —
    field names match `schemas.ProjectComplianceStatusOut` exactly so a
    router can build that response with `**summary.__dict__` plus the
    handful of assignment-identifying fields the summary itself doesn't
    carry (project id, standard id/reference/name, version id/label,
    target date, assigned_at)."""

    def __init__(
        self,
        *,
        total_requirements: int,
        applicable_count: int,
        not_applicable_count: int,
        counts_by_status: dict[str, int],
        compliance_percentage: float,
        has_non_compliant: bool,
        overall_compliance_state: Literal["compliant", "non_compliant", "in_progress", "not_applicable"],
        overall_approval_state: ComplianceApprovalState,
    ) -> None:
        self.total_requirements = total_requirements
        self.applicable_count = applicable_count
        self.not_applicable_count = not_applicable_count
        self.counts_by_status = counts_by_status
        self.compliance_percentage = compliance_percentage
        self.has_non_compliant = has_non_compliant
        self.overall_compliance_state = overall_compliance_state
        self.overall_approval_state = overall_approval_state


_APPROVAL_STATE_PRECEDENCE: tuple[ComplianceApprovalState, ...] = (
    ComplianceApprovalState.REJECTED,
    ComplianceApprovalState.REQUIRES_REASSESSMENT,
    ComplianceApprovalState.PENDING_APPROVAL,
    ComplianceApprovalState.ASSESSED,
    ComplianceApprovalState.NOT_ASSESSED,
    ComplianceApprovalState.APPROVED,
)


def _aggregate_approval_state(states: list[ComplianceApprovalState]) -> ComplianceApprovalState:
    """Reduces every applicable requirement's own `approval_state` to one
    overall value, by precedence — the state needing the most attention
    wins, so the overall value is `APPROVED` only when *every* applicable
    row is `APPROVED` (§20: "A project may have 100% compliant requirements
    but still have an overall status of 'Pending Approval'" — the same
    "worst wins" principle applied generically across every
    `ComplianceApprovalState` member, not just that one example pairing).
    No endpoint sets anything but `NOT_ASSESSED` until Phase 9 ships, so
    this always returns `NOT_ASSESSED` in practice today — see `models.py`'s
    own docstring for why the column/this calculation exist a phase ahead
    of the workflow that transitions it.
    """
    if not states:
        return ComplianceApprovalState.NOT_ASSESSED
    present = set(states)
    for candidate in _APPROVAL_STATE_PRECEDENCE:
        if candidate in present:
            return candidate
    return ComplianceApprovalState.NOT_ASSESSED


def summarize_project_compliance(
    pcrs: list[ProjectComplianceRequirement],
    applicability: ApplicabilityResolution,
) -> ProjectComplianceStatusSummary:
    """§20's "Overall Project Compliance Status" — the exact, documented
    calculation this phase is required to define:

    - `total_requirements`: every `ProjectComplianceRequirement` row for
      this assignment, applicable or not (§20's own "152 total
      requirements" example counts every requirement, not just applicable
      ones).
    - `not_applicable_count`/`applicable_count`: partition by *effective*
      applicability (§9) — `applicable_count = total - not_applicable`.
    - `counts_by_status`: a count per `ComplianceStatus` value, among
      **applicable** rows only (a Not Applicable row's own
      `compliance_status` is not meaningful and must not be counted here
      or anywhere else — §20: "Not Applicable requirements should not
      count against the project's compliance percentage").
    - `compliance_percentage`: `compliant / applicable * 100`, rounded to
      one decimal place. `100.0` when `applicable_count == 0` (vacuously
      fully compliant — nothing applicable can be non-compliant) rather
      than a division-by-zero or a misleading `0.0`.
    - `has_non_compliant`: whether any applicable row is `NON_COMPLIANT`
      — always shown, per §20's "If any requirement is Non-Compliant, the
      overall compliance state should clearly indicate this," regardless
      of how high the percentage is.
    - `overall_compliance_state`: `"not_applicable"` if nothing is
      applicable; else `"non_compliant"` if `has_non_compliant`; else
      `"compliant"` if every applicable row is `COMPLIANT`; else
      `"in_progress"` (some mix of Not Started/In Progress/Blocked/
      Pending Review/Rejected, but no outright Non-Compliant row).
    - `overall_approval_state`: see `_aggregate_approval_state` — kept as
      a **separate** field from `overall_compliance_state`, never folded
      into it, per §20's explicit "Approval/sign-off should be reflected
      separately from the calculated compliance percentage."

    Args:
        pcrs: Every `ProjectComplianceRequirement` row for one
            `ProjectCompliance` assignment.
        applicability: This assignment's resolved applicability map (see
            `resolve_applicability_for_version`), keyed by `requirement_id`
            — must contain an entry for every row in `pcrs`.

    Returns:
        The computed summary.
    """
    counts_by_status: dict[str, int] = {s.value: 0 for s in ComplianceStatus}
    applicable_count = 0
    not_applicable_count = 0
    compliant_count = 0
    has_non_compliant = False
    approval_states: list[ComplianceApprovalState] = []

    for pcr in pcrs:
        effective, _source = applicability[pcr.requirement_id]
        if effective == ComplianceApplicability.NOT_APPLICABLE:
            not_applicable_count += 1
            continue
        applicable_count += 1
        counts_by_status[pcr.compliance_status.value] += 1
        if pcr.compliance_status == ComplianceStatus.COMPLIANT:
            compliant_count += 1
        if pcr.compliance_status == ComplianceStatus.NON_COMPLIANT:
            has_non_compliant = True
        approval_states.append(pcr.approval_state)

    compliance_percentage = 100.0 if applicable_count == 0 else round(compliant_count / applicable_count * 100, 1)

    overall_compliance_state: Literal["compliant", "non_compliant", "in_progress", "not_applicable"]
    if applicable_count == 0:
        overall_compliance_state = "not_applicable"
    elif has_non_compliant:
        overall_compliance_state = "non_compliant"
    elif compliant_count == applicable_count:
        overall_compliance_state = "compliant"
    else:
        overall_compliance_state = "in_progress"

    return ProjectComplianceStatusSummary(
        total_requirements=len(pcrs),
        applicable_count=applicable_count,
        not_applicable_count=not_applicable_count,
        counts_by_status=counts_by_status,
        compliance_percentage=compliance_percentage,
        has_non_compliant=has_non_compliant,
        overall_compliance_state=overall_compliance_state,
        overall_approval_state=_aggregate_approval_state(approval_states),
    )


def build_requirement_out(
    pcr: ProjectComplianceRequirement, applicability: ApplicabilityResolution
) -> ProjectComplianceRequirementOut:
    """Builds the response schema for one `ProjectComplianceRequirement`
    row, filling in its computed `effective_applicability`/
    `applicability_source` from an already-resolved `applicability` map
    (see `resolve_applicability_for_version`) — used by every `project_
    router.py` endpoint that returns one or more of these rows, so the
    "computed, not stored" fields are never built ad hoc per call site."""
    effective, source = applicability[pcr.requirement_id]
    return ProjectComplianceRequirementOut(
        id=pcr.id,
        project_compliance_id=pcr.project_compliance_id,
        requirement_id=pcr.requirement_id,
        explicit_applicability=pcr.explicit_applicability,
        effective_applicability=effective,
        applicability_source=source,
        justification=pcr.justification,
        notes=pcr.notes,
        compliance_status=pcr.compliance_status,
        assessed_at=pcr.assessed_at,
        assessed_by=pcr.assessed_by,
        applicability_set_at=pcr.applicability_set_at,
        applicability_set_by=pcr.applicability_set_by,
        approval_state=pcr.approval_state,
        approval_decided_at=pcr.approval_decided_at,
        approval_decided_by=pcr.approval_decided_by,
        decision_note=pcr.decision_note,
        created_at=pcr.created_at,
        updated_at=pcr.updated_at,
    )


def load_pcrs_and_applicability(
    db: Session, *, project_compliance_id: uuid.UUID, standard_version_id: uuid.UUID
) -> tuple[list[ProjectComplianceRequirement], ApplicabilityResolution]:
    """Loads every `ProjectComplianceRequirement` row for one assignment
    plus every `ComplianceRequirement` in its standard version, and
    resolves applicability across the whole tree in one pass (§9)  — the
    shared loading step every endpoint that needs a resolved applicability
    value goes through, whether it ultimately only needs one row's value
    or all of them: resolution is inherently whole-tree (a row's own
    effective value can depend on its ancestors' explicit decisions), so
    there is no cheaper "just this one row" query to make instead."""
    requirements = list(
        db.scalars(
            select(ComplianceRequirement).where(ComplianceRequirement.standard_version_id == standard_version_id)
        ).all()
    )
    pcrs = list(
        db.scalars(
            select(ProjectComplianceRequirement).where(
                ProjectComplianceRequirement.project_compliance_id == project_compliance_id
            )
        ).all()
    )
    pcr_by_requirement_id = {pcr.requirement_id: pcr for pcr in pcrs}
    applicability = resolve_applicability_for_version(requirements, pcr_by_requirement_id)
    return pcrs, applicability


def build_status_out(db: Session, project_compliance: ProjectCompliance) -> ProjectComplianceStatusOut:
    """Builds the full §20 status summary response for one `ProjectCompliance`
    assignment. Used by both `router.py`'s cross-project listing (§26,
    Compliance Manager) and `project_router.py`'s per-project status
    endpoint (§20, the `compliance_get_project_status` MCP tool) — one
    calculation, two callers, never duplicated."""
    version = db.get(ComplianceStandardVersion, project_compliance.standard_version_id)
    standard = db.get(ComplianceStandard, version.standard_id)
    pcrs, applicability = load_pcrs_and_applicability(
        db, project_compliance_id=project_compliance.id, standard_version_id=version.id
    )
    summary = summarize_project_compliance(pcrs, applicability)
    return ProjectComplianceStatusOut(
        project_compliance_id=project_compliance.id,
        project_id=project_compliance.project_id,
        standard_id=standard.id,
        standard_reference=standard.reference,
        standard_name=standard.name,
        standard_version_id=version.id,
        version_label=version.version_label,
        target_compliance_date=project_compliance.target_compliance_date,
        assigned_at=project_compliance.assigned_at,
        total_requirements=summary.total_requirements,
        applicable_count=summary.applicable_count,
        not_applicable_count=summary.not_applicable_count,
        counts_by_status=summary.counts_by_status,
        compliance_percentage=summary.compliance_percentage,
        has_non_compliant=summary.has_non_compliant,
        overall_compliance_state=summary.overall_compliance_state,
        overall_approval_state=summary.overall_approval_state,
    )


# --- Phase 9: Approval / sign-off workflow -----------------------------------------

#: `approval_state` values a material change (an applicability change, or a
#: change to supporting evidence) downgrades to `REQUIRES_REASSESSMENT` —
#: see `invalidate_approval_if_in_flight`'s own docstring for why this is
#: exactly `{PENDING_APPROVAL, APPROVED}` and no other member.
_IN_FLIGHT_APPROVAL_STATES = (ComplianceApprovalState.PENDING_APPROVAL, ComplianceApprovalState.APPROVED)


def advance_approval_state_on_assessment(pcr: ProjectComplianceRequirement) -> ComplianceApprovalState:
    """Applies §12/§16's assessment-side approval transition: performing a
    fresh compliance-status assessment (`project_router.py::update_
    requirement_assessment`) always moves `approval_state` to `ASSESSED`,
    from *any* prior state.

    This is deliberately unconditional, including from `APPROVED` — unlike
    `invalidate_approval_if_in_flight` below, which flags `REQUIRES_
    REASSESSMENT` for a change *not* accompanied by an actual reassessment.
    Landing an assessment endpoint's own effect on `REQUIRES_REASSESSMENT`
    would be self-contradictory (that state means "a reassessment is still
    needed," but a reassessment was just performed) — `ASSESSED` is always
    the correct result here, satisfying §12's "must not simply remain
    'Approved'" for the assessment-change case specifically, and restarting
    the approval cycle (a new `submit-for-approval` is required before this
    row can be `APPROVED` again).

    Args:
        pcr: The row being reassessed. Mutated in place; caller commits.

    Returns:
        The `approval_state` value immediately before this call, for audit
        logging.
    """
    previous = pcr.approval_state
    pcr.approval_state = ComplianceApprovalState.ASSESSED
    return previous


def invalidate_approval_if_in_flight(pcr: ProjectComplianceRequirement) -> ComplianceApprovalState | None:
    """Applies §12/§16/§27's "material change without an accompanying
    reassessment" approval transition — used by `project_router.py::
    update_requirement_applicability` (when the applicability decision
    actually changes) and by the evidence endpoints (`archive_evidence`/
    `revalidate_evidence`, via `find_pcrs_linked_to_evidence` below) when a
    piece of evidence supporting an in-flight or decided approval is
    archived or revalidated.

    Rule: if `approval_state` is currently `PENDING_APPROVAL` or `APPROVED`,
    it moves to `REQUIRES_REASSESSMENT` — a pending decision is no longer
    trustworthy once its underlying material changes, and an already-
    `APPROVED` row must not simply remain so (§12's explicit rule, §27's
    "material change... should identify whether reassessment/reapproval is
    required"). Every other state (`NOT_ASSESSED`, `ASSESSED`, `REJECTED`,
    already-`REQUIRES_REASSESSMENT`) is left untouched — none of them
    represent a decision or pending decision that could be invalidated.

    Args:
        pcr: The row to check/mutate in place; caller commits.

    Returns:
        The `approval_state` value immediately before this call, if it was
        changed; `None` if no change was made (nothing to log).
    """
    if pcr.approval_state in _IN_FLIGHT_APPROVAL_STATES:
        previous = pcr.approval_state
        pcr.approval_state = ComplianceApprovalState.REQUIRES_REASSESSMENT
        return previous
    return None


def find_pcrs_linked_to_evidence(db: Session, *, evidence_id: uuid.UUID) -> list[ProjectComplianceRequirement]:
    """Every `ProjectComplianceRequirement` that a piece of evidence
    supports — directly (`ComplianceEvidenceRequirementLink`) or via one of
    its required-action assessments (`ComplianceEvidenceActionLink` ->
    `ComplianceRequiredActionAssessment.project_compliance_requirement_id`)
    — de-duplicated by id. Used by `archive_evidence`/`revalidate_evidence`
    to find every approval `invalidate_approval_if_in_flight` should be
    checked against when that evidence materially changes (§13's "a single
    piece of evidence should be capable of supporting multiple compliance
    requirements," extended to required actions of those requirements too)."""
    direct_ids = set(
        db.scalars(
            select(ComplianceEvidenceRequirementLink.project_compliance_requirement_id).where(
                ComplianceEvidenceRequirementLink.evidence_id == evidence_id
            )
        ).all()
    )
    via_action_ids = set(
        db.scalars(
            select(ComplianceRequiredActionAssessment.project_compliance_requirement_id)
            .join(
                ComplianceEvidenceActionLink,
                ComplianceEvidenceActionLink.required_action_assessment_id == ComplianceRequiredActionAssessment.id,
            )
            .where(ComplianceEvidenceActionLink.evidence_id == evidence_id)
        ).all()
    )
    pcr_ids = direct_ids | via_action_ids
    if not pcr_ids:
        return []
    return list(db.scalars(select(ProjectComplianceRequirement).where(ProjectComplianceRequirement.id.in_(pcr_ids))).all())


# --- Phase 8: Evidence ------------------------------------------------------------

#: Days before `ComplianceEvidence.expiry_date` that it is reported
#: `EXPIRING_SOON` rather than `VALID` (§14: "The system should provide
#: appropriate warnings/notifications when evidence is approaching
#: expiry"). A plain constant, not a per-project/per-org configurable
#: setting: §14 names no specific lead time, and Phase 10 (Scheduled
#: Reviews + Notifications) is where this module's actual warning/
#: notification delivery is built — if that phase needs this to be
#: configurable (mirroring `Project.review_reminder_lead_days_default`'s
#: own precedent for an analogous "how many days before X is this
#: worth flagging" setting), it can promote this constant to a column
#: then, once there is a real notification consumer to configure for.
EVIDENCE_EXPIRY_WARNING_DAYS = 30


def compute_evidence_validity_state(
    evidence: ComplianceEvidence, *, today: date | None = None
) -> ComplianceEvidenceValidityState:
    """Derives a `ComplianceEvidence` row's current validity (§14) from its
    `expiry_date` — never stored, so it can never drift out of date the
    way a cached/stored flag could (§14: "Expired evidence must not
    silently continue to be treated as valid").

    Rule:
    - No `expiry_date` at all -> `NO_EXPIRY` (nothing to ever warn about).
    - `expiry_date` already passed -> `EXPIRED`.
    - `expiry_date` within `EVIDENCE_EXPIRY_WARNING_DAYS` of today (inclusive)
      -> `EXPIRING_SOON`.
    - Otherwise -> `VALID`.

    Independent of `evidence.is_archived` — an archived (no-longer-
    applicable) row is still assigned a real validity state; see
    `ComplianceEvidenceValidityState`'s own docstring for why these are
    deliberately different questions. Callers that want to exclude
    archived/no-longer-applicable evidence from an "expiring/expired"
    listing (e.g. `list_expiring_or_expired_evidence` below) filter on
    `is_archived` themselves, not by folding it into this function.

    Args:
        evidence: The row to evaluate.
        today: Overridable for tests; defaults to the real current date.

    Returns:
        The computed `ComplianceEvidenceValidityState`.
    """
    if evidence.expiry_date is None:
        return ComplianceEvidenceValidityState.NO_EXPIRY
    today = today or date.today()
    if evidence.expiry_date < today:
        return ComplianceEvidenceValidityState.EXPIRED
    if evidence.expiry_date <= today + timedelta(days=EVIDENCE_EXPIRY_WARNING_DAYS):
        return ComplianceEvidenceValidityState.EXPIRING_SOON
    return ComplianceEvidenceValidityState.VALID


def build_evidence_out(db: Session, evidence: ComplianceEvidence) -> ComplianceEvidenceOut:
    """Builds the response schema for one `ComplianceEvidence` row,
    filling in its computed `validity_state` (`compute_evidence_validity_
    state`) and its current linked requirement/required-action-assessment
    ids (§13's multi-linkage) — used by every `project_router.py` endpoint
    that returns one or more evidence rows, so these two derived/joined
    fields are never built ad hoc per call site."""
    requirement_ids = list(
        db.scalars(
            select(ComplianceEvidenceRequirementLink.project_compliance_requirement_id).where(
                ComplianceEvidenceRequirementLink.evidence_id == evidence.id
            )
        ).all()
    )
    action_ids = list(
        db.scalars(
            select(ComplianceEvidenceActionLink.required_action_assessment_id).where(
                ComplianceEvidenceActionLink.evidence_id == evidence.id
            )
        ).all()
    )
    return ComplianceEvidenceOut(
        id=evidence.id,
        project_id=evidence.project_id,
        title=evidence.title,
        description=evidence.description,
        issuing_organisation=evidence.issuing_organisation,
        issued_date=evidence.issued_date,
        expiry_date=evidence.expiry_date,
        provided_by=evidence.provided_by,
        provided_at=evidence.provided_at,
        notes=evidence.notes,
        validity_state=compute_evidence_validity_state(evidence),
        is_archived=evidence.is_archived,
        archived_at=evidence.archived_at,
        archived_by=evidence.archived_by,
        created_at=evidence.created_at,
        updated_at=evidence.updated_at,
        linked_requirement_ids=requirement_ids,
        linked_required_action_assessment_ids=action_ids,
    )


def list_expiring_or_expired_evidence(db: Session, *, project_id: uuid.UUID) -> list[ComplianceEvidence]:
    """Every non-archived `ComplianceEvidence` row for `project_id` whose
    computed validity is `EXPIRING_SOON` or `EXPIRED` (§14) — backs both
    `GET .../expiring-evidence` and the `compliance_list_expiring_evidence`
    MCP tool. Archived (no-longer-applicable) evidence is excluded: a row
    the project has already marked as no longer relevant isn't something
    worth surfacing as needing attention (see `ComplianceEvidenceValidityState`'s
    own docstring on why "applicable" and "valid" are different axes)."""
    all_evidence = db.scalars(
        select(ComplianceEvidence).where(
            ComplianceEvidence.project_id == project_id, ComplianceEvidence.is_archived.is_(False)
        )
    ).all()
    return [
        evidence
        for evidence in all_evidence
        if compute_evidence_validity_state(evidence)
        in (ComplianceEvidenceValidityState.EXPIRING_SOON, ComplianceEvidenceValidityState.EXPIRED)
    ]


def resolve_evidence_file_project_id(db: Session, file_id: uuid.UUID) -> uuid.UUID | None:
    """Resolves a `FileAsset` id to the project it belongs to, if it is
    attached to a piece of Compliance evidence (`ComplianceEvidenceFile`)
    — the Compliance module's own `ModuleDefinition.resolve_file_owner_
    project_id` hook (`app.modules.registry`), called generically by
    `routers.files.download_file` alongside every other owner-type check,
    without that core router needing to import anything from this module
    directly (the whole point of the hook: a core file that must stay
    module-agnostic can still authorize a module-owned attachment).

    Returns:
        The owning project's id, or `None` if `file_id` isn't a Compliance
        evidence attachment at all.
    """
    link = db.scalar(select(ComplianceEvidenceFile).where(ComplianceEvidenceFile.file_id == file_id))
    if link is None:
        return None
    evidence = db.get(ComplianceEvidence, link.evidence_id)
    return evidence.project_id if evidence is not None else None


# --- Phase 10: Scheduled reviews ---------------------------------------------------

#: Days before `ComplianceReview.next_due_date` that a still-`SCHEDULED`
#: review is reported `DUE` rather than `UPCOMING` (§17/§28's "identify
#: upcoming and overdue compliance reviews"). A plain constant, like
#: `EVIDENCE_EXPIRY_WARNING_DAYS` above, but a shorter window: a review
#: (an activity someone must actually schedule time to perform) warrants a
#: shorter advance flag than a certificate's own expiry.
COMPLIANCE_REVIEW_DUE_WARNING_DAYS = 14


def compute_review_schedule_state(
    review: ComplianceReview, *, today: date | None = None
) -> Literal["upcoming", "due", "overdue"] | None:
    """Derives a `ComplianceReview`'s current schedule state (§17/§28) from
    `next_due_date` — never stored, mirroring `compute_evidence_validity_
    state`'s own "can't drift" reasoning.

    Rule:
    - Not `SCHEDULED` (i.e. `COMPLETED`) -> `None` (the concept doesn't
      apply to a completed review).
    - `next_due_date` already passed -> `OVERDUE`.
    - `next_due_date` within `COMPLIANCE_REVIEW_DUE_WARNING_DAYS` of today
      (inclusive) -> `DUE`.
    - Otherwise -> `UPCOMING`.

    Args:
        review: The row to evaluate.
        today: Overridable for tests; defaults to the real current date.

    Returns:
        The computed state, or `None` for a non-`SCHEDULED` review.
    """
    if review.status != ComplianceReviewStatus.SCHEDULED:
        return None
    today = today or date.today()
    if review.next_due_date < today:
        return "overdue"
    if review.next_due_date <= today + timedelta(days=COMPLIANCE_REVIEW_DUE_WARNING_DAYS):
        return "due"
    return "upcoming"


def build_review_out(db: Session, review: ComplianceReview) -> ComplianceReviewOut:
    """Builds the response schema for one `ComplianceReview` row, filling in
    its computed `schedule_state` and current linked evidence ids — used by
    every endpoint (`router.py`/`project_router.py`) that returns one or
    more review rows, so these two derived/joined fields are never built ad
    hoc per call site."""
    linked_evidence_ids = list(
        db.scalars(
            select(ComplianceReviewEvidenceLink.evidence_id).where(ComplianceReviewEvidenceLink.review_id == review.id)
        ).all()
    )
    return ComplianceReviewOut(
        id=review.id,
        standard_id=review.standard_id,
        project_compliance_id=review.project_compliance_id,
        frequency_label=review.frequency_label,
        recurrence_days=review.recurrence_days,
        next_due_date=review.next_due_date,
        owner_id=review.owner_id,
        status=review.status,
        schedule_state=compute_review_schedule_state(review),
        notes=review.notes,
        outcome=review.outcome,
        completed_at=review.completed_at,
        completed_by=review.completed_by,
        created_by=review.created_by,
        created_at=review.created_at,
        updated_at=review.updated_at,
        linked_evidence_ids=linked_evidence_ids,
    )


def complete_review(
    db: Session, review: ComplianceReview, *, outcome: ComplianceReviewOutcome, notes: str, actor_id: uuid.UUID
) -> ComplianceReview | None:
    """Completes a `SCHEDULED` `ComplianceReview` (§17's "Review outcome").
    Caller (`router.py`/`project_router.py`) has already checked `review.
    status == SCHEDULED` (409 otherwise) — this function only performs the
    transition.

    Marks `review` itself `COMPLETED` (retained as history — §17 — never
    deleted or reopened) and, when `review.recurrence_days` is set, creates
    and returns a **new** `SCHEDULED` row for the next cycle (`next_due_date
    = today + recurrence_days`, same owner/standard-or-project-compliance/
    frequency_label/recurrence_days) — see `models.py`'s own Phase 10 notes
    for why a new row rather than reopening this one. A one-off review
    (`recurrence_days is None`) simply stays `COMPLETED` with nothing
    scheduled after it.

    Does not commit — caller commits as part of its own single transaction.

    Args:
        db: An active session (the new row, if any, is added but not
            flushed/committed).
        review: The row being completed. Mutated in place.
        outcome: The `ComplianceReviewOutcome` to record.
        notes: Replaces `review.notes` (mirrors `ProjectComplianceAssessmentUpdate.
            notes`'s own "supply the current full value" convention).
        actor_id: The user completing the review.

    Returns:
        The newly-created next-cycle `ComplianceReview`, or `None` if this
        review doesn't recur.
    """
    now = datetime.now(UTC)
    review.status = ComplianceReviewStatus.COMPLETED
    review.outcome = outcome
    review.notes = notes
    review.completed_at = now
    review.completed_by = actor_id

    if review.recurrence_days is None:
        return None

    next_review = ComplianceReview(
        standard_id=review.standard_id,
        project_compliance_id=review.project_compliance_id,
        frequency_label=review.frequency_label,
        recurrence_days=review.recurrence_days,
        next_due_date=date.today() + timedelta(days=review.recurrence_days),
        owner_id=review.owner_id,
        created_by=actor_id,
    )
    db.add(next_review)
    return next_review


def get_effective_compliance_officers(db: Session, project_id: uuid.UUID) -> set[uuid.UUID]:
    """Users who should be notified as a project's compliance officers
    (§18) — this project's effective project managers (who already hold
    every Compliance Officer capability via `require_module_role`'s own
    composition, Phase 2) union anyone holding a direct `compliance_officer`
    `UserModuleRole` grant on this project. Not an authorization check —
    see this module's own docstring for why "misses an edge case" here is
    only a missed notification, not a security gap."""
    from app.models.module_role import UserModuleRole
    from app.services.rbac import get_effective_project_managers

    ids = get_effective_project_managers(db, project_id)
    ids.update(
        db.scalars(
            select(UserModuleRole.user_id).where(
                UserModuleRole.project_id == project_id,
                UserModuleRole.module_key == "compliance",
                UserModuleRole.role_key == "compliance_officer",
            )
        ).all()
    )
    return ids


def get_effective_compliance_managers(db: Session, organization_id: uuid.UUID) -> set[uuid.UUID]:
    """Users who should be notified as an organisation's compliance
    managers (§18) — direct `OrgRole.ORG_ADMIN` grants union anyone holding
    a direct `compliance_manager` `UserModuleRole` grant on this
    organisation. Direct-grant-only for `ORG_ADMIN` (unlike `get_effective_
    compliance_officers`'s reuse of the fuller `get_effective_project_
    managers`) — this codebase's org groups don't grant `OrgRole` members
    the way project groups grant `ProjectRole` members (no `OrgGroupRole`
    table exists), so there is no inheritance path to also cover. Not an
    authorization check — see this module's own docstring."""
    from app.models.enums import OrgRole
    from app.models.module_role import UserModuleRole
    from app.models.organization import UserOrgRole

    ids = set(
        db.scalars(
            select(UserOrgRole.user_id).where(
                UserOrgRole.organization_id == organization_id, UserOrgRole.role == OrgRole.ORG_ADMIN
            )
        ).all()
    )
    ids.update(
        db.scalars(
            select(UserModuleRole.user_id).where(
                UserModuleRole.organization_id == organization_id,
                UserModuleRole.module_key == "compliance",
                UserModuleRole.role_key == "compliance_manager",
                UserModuleRole.project_id.is_(None),
            )
        ).all()
    )
    return ids
