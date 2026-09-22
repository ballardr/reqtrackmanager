"""
Module: modules.decisions.enums

Decision-Management-owned vocabulary (docs/plans/module-04-decision-
management-plan.md Phase 1). Kept in this package rather than
`app.models.enums`, mirroring `app.modules.compliance.enums`'s own
reasoning — these are domain concepts this module owns, not core
ReqTrackManager concepts.
"""

from __future__ import annotations

import enum


class DecisionStatus(str, enum.Enum):
    """Lifecycle states for a `Decision` (Phase 0 addendum Q1/Q4 — a fixed
    enum of this module's own, not a reuse of `app.models.enums.
    RequirementStatus`, whose four states don't cover approval-with-
    rejection or supersession).

    `REJECTED` and `SUPERSEDED` are both real, queryable terminal-ish
    states rather than events layered on an earlier status — a rejected or
    superseded Decision "remains available for historical purposes" (source
    overview §13/10.6) precisely because it's still filterable/reportable
    by its own status, not just recoverable from the audit log.

    Transition enforcement (Draft -> Proposed -> Under Review -> Approved,
    with Rejected reachable from Proposed/Under Review and Superseded only
    reachable from Approved once a superseding Decision itself reaches
    Approved) is Phase 2's responsibility, not this enum's — this module
    declares the full set of valid values now (Phase 1: data model) so the
    column doesn't need a later migration to widen it.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
