/**
 * Module: modules/traceability/exceptionFixtures
 *
 * Story data for the traceability exception screens.
 */
import type { TraceabilityException } from "./types";

export const EXCEPTION_PROJECT_ID = "p-1";

/** An approved, covering exception, with any field overridden. */
export function buildException(overrides: Partial<TraceabilityException> = {}): TraceabilityException {
  return {
    id: "tex-1", project_id: EXCEPTION_PROJECT_ID, unique_code: "TEX-001", title: "Exception to Requirements are verified",
    status: "approved",
    record: { artefact_type: "requirement", artefact_type_label: "Requirement", id: "req-1", code: "SW-PERF-001", label: "Respond within one second", removed: false },
    rule_id: "rule-1", rule_name: "Requirements are verified", reason: "Verification is deferred to the **flight test**.",
    requester: { type: "user", id: "user-1", label: "Alex Morgan", member_count: null, exists: true },
    approver: null, expires_on: "2027-06-30", review_date: "2027-01-15", creator_id: "user-1", decided_by_id: "user-2",
    decided_by_name: "Sam Whitfield", decided_at: "2026-11-02T03:00:00Z", decision_comment: "Accepted for this release.",
    covers: true, no_cover_reason: null, expired: false, rule_changed: false, needs_organisation_approval: false,
    is_archived: false, created_at: "2026-11-01T03:00:00Z", updated_at: "2026-11-02T03:00:00Z",
    ...overrides,
  };
}
