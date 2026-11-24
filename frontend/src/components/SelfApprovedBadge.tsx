/**
 * Module: components/SelfApprovedBadge
 *
 * The "Self-approved" marker of a record whose latest approval was given by the person who created it, with who and
 * when in its tooltip. Drawn by `RecordHeader` from its `approval` prop; a list or a report names the same fact from the
 * `self_approved` history event.
 */
import type { ApprovalStatus } from "../api/approvalSeparation";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { Tooltip } from "./Tooltip";

/**
 * @param status The record's approval status; nothing is drawn unless it is a self-approval.
 */
export function SelfApprovedBadge({ status }: { status: ApprovalStatus | null }) {
  const text = useStrings().approvalSeparation;
  if (!status?.self_approved) return null;
  return (
    <Tooltip wrap label={text.selfApprovedHelp(status.approved_by_name, status.approved_at ? new Date(status.approved_at).toLocaleString() : null)}>
      <span><Badge tone="warning">{text.selfApproved}</Badge></span>
    </Tooltip>
  );
}
