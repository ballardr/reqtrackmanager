/**
 * Module: modules/traceability/ApprovalRolesModal
 *
 * The dialog that sets the roles an approval policy adds as approvers of one record type, for a governance profile or a
 * project.
 *
 * Responsibilities: hold the chosen roles while the dialog is open, report a failed save beside the actions, hand the
 * chosen roles to `onSave` and, for a project, offer to follow the nearest ancestor project again (`onSave(null)`).
 *
 * Design decisions: the tier a value falls back to is stated through the shared `OverridePill` (docs/ux-style-guide.md,
 * "Pattern: scoring and inherited settings"); returning to the inherited value acts at once and ends the dialog.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { Modal } from "../../components/Modal";
import { OverridePill } from "../../components/OverridePill";
import { toErrorMessage } from "../../context/ToastContext";
import { ApproverRolesField } from "./ApproverRolesField";
import { GOVERNANCE_HELP } from "./help";
import type { ApproverRole, ApproverRoleOption } from "./types";

/**
 * @param typeLabel The record type's singular name, for the title.
 * @param options The roles the policy may name.
 * @param initial The roles chosen now.
 * @param onSave Saves the chosen roles, or `null` to follow the nearest ancestor project; rejects to report a failure,
 *   which stays in the dialog.
 * @param onClose Closes the dialog.
 * @param allowFollowParent Offers the way back to the inherited value (a project's policy).
 * @param own Whether the project has a value of its own (shown through the pill); only read with `allowFollowParent`.
 * @param inheritedFrom The ancestor project whose value applies while the project has none of its own.
 */
export function ApprovalRolesModal({
  typeLabel, options, initial, onSave, onClose, allowFollowParent = false, own = true, inheritedFrom = null,
}: {
  typeLabel: string;
  options: ApproverRoleOption[];
  initial: ApproverRole[];
  onSave: (roles: ApproverRole[] | null) => Promise<void>;
  onClose: () => void;
  allowFollowParent?: boolean;
  own?: boolean;
  inheritedFrom?: string | null;
}) {
  const [roles, setRoles] = useState<ApproverRole[]>(initial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(next: ApproverRole[] | null) {
    setSaving(true);
    setError(null);
    try {
      await onSave(next);
    } catch (err) {
      setError(toErrorMessage(err, "The approvers could not be saved."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Approvers: ${typeLabel}`} onClose={onClose}>
      <div className="stack">
        <FormActions error={error} onCancel={onClose} onSave={() => void save(roles)} saveDisabled={saving} />
        {allowFollowParent && (
          <div className="row">
            <OverridePill
              custom={own} disabled={saving} resetLabel="Use inherited value" onReset={() => void save(null)}
              defaultLabel={inheritedFrom ? `Inherited from ${inheritedFrom}` : "Inherited from the nearest ancestor project"}
            />
          </div>
        )}
        <ApproverRolesField
          label="Additional approvers"
          help={allowFollowParent ? GOVERNANCE_HELP.approvalProjectRoles : GOVERNANCE_HELP.approvalRoles}
          options={options} value={roles} onChange={setRoles}
        />
      </div>
    </Modal>
  );
}
