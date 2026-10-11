/**
 * Module: testing/linkTraceUniverse
 *
 * The small world the trace stories share: one focus requirement with a
 * two-step upstream chain, a decision and a four-deep verification chain
 * downstream, and related records, so each story names only what it asserts.
 */
import { buildTraceApi, type TraceLink, type TraceRecord } from "./artefactLinksFixtures";

export const FOCUS_ID = "req-2";

export const TRACE_RECORDS: TraceRecord[] = [
  { id: "req-0", label: "REQ-000 Platform baseline", status: "approved" },
  { id: "req-1", label: "REQ-001 Keep reports", status: "approved" },
  { id: FOCUS_ID, label: "REQ-002 Store reports", status: "approved" },
  { id: "dec-1", type: "decision", typeLabel: "Decision", label: "DEC-001 Use Postgres", status: "draft" },
  { id: "pp-1", type: "pain_point", typeLabel: "Pain Point", label: "Reports arrive late", status: "accepted" },
  { id: "test-1", label: "TST-001 Restore from backup" },
  { id: "test-2", label: "TST-002 Restore under load" },
  { id: "test-3", label: "TST-003 Restore across regions" },
  { id: "test-4", label: "TST-004 Restore after failover" },
  { id: "req-3", label: "REQ-003 Export reports" },
  { id: "req-4", label: "REQ-004 Email reports" },
];

export const TRACE_LINKS: TraceLink[] = [
  { source: FOCUS_ID, target: "req-1", forward: "Depends on", reverse: "Is a dependency of", flow: "forward_is_upstream" },
  { source: "req-1", target: "req-0", forward: "Depends on", reverse: "Is a dependency of", flow: "forward_is_upstream" },
  { source: "dec-1", target: FOCUS_ID, forward: "Implements", reverse: "Is implemented by", flow: "forward_is_upstream" },
  { source: "dec-1", target: "pp-1", forward: "Addresses", reverse: "Is addressed by", flow: "forward_is_upstream" },
  { source: FOCUS_ID, target: "test-1", forward: "Verified by", reverse: "Verifies", flow: "forward_is_downstream" },
  { source: "test-1", target: "test-2", forward: "Verified by", reverse: "Verifies", flow: "forward_is_downstream" },
  { source: "test-2", target: "test-3", forward: "Verified by", reverse: "Verifies", flow: "forward_is_downstream" },
  { source: "test-3", target: "test-4", forward: "Verified by", reverse: "Verifies", flow: "forward_is_downstream" },
  { source: FOCUS_ID, target: "req-3", forward: "Related to", reverse: "Related to", flow: "none" },
  { source: "req-3", target: "req-4", forward: "Related to", reverse: "Related to", flow: "none" },
];

/** The shared world as a fake API. */
export function buildUniverseApi() {
  return buildTraceApi(TRACE_RECORDS, TRACE_LINKS);
}

/** Decisions that replaced one another: DEC-000 (superseded) -> DEC-001 (superseded) -> DEC-002 (the record traced),
 * each implementing or addressing things of its own, to exercise "Hide inactive records". */
export const SUPERSESSION_FOCUS_ID = "dec-2";

export const SUPERSESSION_RECORDS: TraceRecord[] = [
  { id: SUPERSESSION_FOCUS_ID, type: "decision", typeLabel: "Decision", label: "DEC-002 Adopt dual-redundant controllers", status: "approved" },
  { id: "dec-1", type: "decision", typeLabel: "Decision", label: "DEC-001 Single controller with hot-swap", status: "superseded" },
  { id: "dec-0", type: "decision", typeLabel: "Decision", label: "DEC-000 Single controller", status: "superseded" },
  { id: "req-av", label: "AV-PERF-001 Acquire GPS lock", status: "approved" },
  { id: "pp-late", type: "pain_point", typeLabel: "Pain Point", label: "Reports arrive late", status: "accepted" },
  { id: "req-old", label: "REQ-000 Platform baseline", status: "approved" },
  { id: "req-archived", label: "REQ-900 Withdrawn idea", status: "archived", isArchived: true },
];

export const SUPERSESSION_LINKS: TraceLink[] = [
  { source: "dec-1", target: SUPERSESSION_FOCUS_ID, forward: "Is superseded by", reverse: "Supersedes", flow: "forward_is_downstream" },
  { source: "dec-0", target: "dec-1", forward: "Is superseded by", reverse: "Supersedes", flow: "forward_is_downstream" },
  { source: "dec-1", target: "req-av", forward: "Implements", reverse: "Is implemented by", flow: "forward_is_upstream" },
  { source: "dec-1", target: "pp-late", forward: "Addresses", reverse: "Is addressed by", flow: "forward_is_upstream" },
  { source: "dec-0", target: "req-old", forward: "Implements", reverse: "Is implemented by", flow: "forward_is_upstream" },
  { source: SUPERSESSION_FOCUS_ID, target: "req-archived", forward: "Related to", reverse: "Related to", flow: "none" },
];

/** The supersession world as a fake API. */
export function buildSupersessionApi() {
  return buildTraceApi(SUPERSESSION_RECORDS, SUPERSESSION_LINKS);
}
