/**
 * Module: hooks/useApprovalStatus
 *
 * What a record page shows about approval separation: whether the record's latest approval was a self-approval, and
 * whether the viewer must find another approver (`GET .../approval-separation/status/{type}/{id}`, one read per page).
 *
 * Responsibilities:
 * - Load the status for a project record or an organisation-owned record, and again when `reloadKey` changes (after a
 *   move that may approve the record).
 * - Offer the Promote step's refusal reason (`blockedReason`) when the viewer may not approve their own record.
 *
 * Design decisions: until the status is loaded, or when it cannot be (no scope, a failed request), nothing is marked and
 * nothing is blocked, so a page behaves as before and never waits on this read; the server stays the authority and
 * refuses an approval the page offered.
 */
import { useCallback, useState } from "react";

import { approvalSeparationApi, type ApprovalScope, type ApprovalSeparationApi, type ApprovalStatus } from "../api/approvalSeparation";
import type { LifecyclePromote } from "../components/LifecycleTrack";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "./useLoadOnChange";

/** What a record page reads from the status. */
export interface RecordApprovalStatus {
  /** The loaded status, or `null` while unknown. */
  status: ApprovalStatus | null;
  /** The record's latest approval was given by its creator. */
  selfApproved: boolean;
  /** The reason approval is unavailable to the viewer, or `undefined` when it is not. */
  blockedReason: string | undefined;
  /** The Promote move to an approval step: blocked with the reason when the viewer may not approve their own record. */
  approve(to: string, onPromote: () => void): LifecyclePromote;
}

/**
 * @param scope The record's project or owning organisation; `null` while unknown.
 * @param artefactType The registered record type.
 * @param recordId The record, or `undefined` while it loads.
 * @param reloadKey A value that changes when the record may have been approved (its status), so the status is read again.
 * @param api The calls (the live ones by default); injectable for stories.
 */
export function useApprovalStatus(
  scope: ApprovalScope | null, artefactType: string, recordId: string | undefined, reloadKey: string | undefined = undefined,
  api: ApprovalSeparationApi = approvalSeparationApi,
): RecordApprovalStatus {
  const strings = useStrings();
  const [status, setStatus] = useState<ApprovalStatus | null>(null);
  const scopeKey = scope === null ? "" : "projectId" in scope ? `p:${scope.projectId}` : `o:${scope.organizationId}`;

  const load = useCallback(async () => {
    if (!scope || !recordId) {
      setStatus(null);
      return;
    }
    try {
      setStatus(await api.status(scope, artefactType, recordId));
    } catch {
      setStatus(null);
    }
    // `scope` is an object literal at the call site; its identity is `scopeKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, scopeKey, artefactType, recordId]);
  useLoadOnChange(load, [scopeKey, artefactType, recordId, reloadKey]);

  const blockedReason = status?.needs_other_approver ? strings.approvalSeparation.needsOtherApprover : undefined;
  return {
    status,
    selfApproved: status?.self_approved ?? false,
    blockedReason,
    approve: (to, onPromote) => (blockedReason ? { to, blockedReason } : { to, onPromote }),
  };
}
