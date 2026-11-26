/**
 * Module: modules/traceability/ReviewSettingsModal
 *
 * The dialog that edits one record type's review settings, shared by a governance profile and a project. It wraps
 * `ReviewSettingsFields` in a `Modal` whose header carries Save (`FormActions`).
 *
 * Responsibilities:
 * - Validate the numbers before Save is available and show a save failure in the header.
 * - In a project that has its own settings, offer "Use inherited value", which saves `null` so the project follows the
 *   nearest ancestor project again.
 *
 * Design decisions: `onSave` performs the request and throws to report a failure; the dialog closes only after it succeeds.
 */
import { useState } from "react";

import type { OrgUser, Principal } from "../../api/types";
import { toErrorMessage } from "../../context/ToastContext";
import { FormActions } from "../../components/FormActions";
import { Modal } from "../../components/Modal";
import { reviewProblem } from "./policyText";
import { ReviewSettingsFields } from "./ReviewSettingsFields";
import type { ReviewSettingsValues } from "./types";

/**
 * @param typeLabel The record type's singular name.
 * @param initial The settings the dialog opens with.
 * @param ownerDisplay The resolved default owner of `initial`.
 * @param orgUsers The organisation's users for the owner picker.
 * @param organizationId The organisation, for group listing and user search.
 * @param projectId The project when a project group may be the owner.
 * @param allowFollowParent Offers "Use inherited value" (saves `null`).
 * @param onSave Saves the settings, or `null` to follow the nearest ancestor project; rejects on failure.
 * @param onClose Closes the dialog.
 */
export function ReviewSettingsModal({
  typeLabel, initial, ownerDisplay, orgUsers, organizationId, projectId, allowFollowParent, onSave, onClose,
}: {
  typeLabel: string;
  initial: ReviewSettingsValues;
  ownerDisplay?: Principal | null;
  orgUsers: OrgUser[];
  organizationId: string | undefined;
  projectId?: string;
  allowFollowParent?: boolean;
  onSave: (values: ReviewSettingsValues | null) => Promise<void>;
  onClose: () => void;
}) {
  const [values, setValues] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const problem = reviewProblem(values);

  async function save(next: ReviewSettingsValues | null) {
    setSaving(true);
    setError(null);
    try {
      await onSave(next);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, "The review settings could not be saved."));
      setSaving(false);
    }
  }

  return (
    <Modal title={`Edit review settings: ${typeLabel}`} onClose={onClose} dirty={JSON.stringify(values) !== JSON.stringify(initial)}>
      <div className="stack">
        <FormActions
          error={error ?? problem} onCancel={onClose} onSave={() => void save(values)} saveDisabled={saving || problem !== null}
          leading={allowFollowParent
            ? <button type="button" className="btn" disabled={saving} onClick={() => void save(null)}>Use inherited value</button>
            : undefined}
        />
        <ReviewSettingsFields
          values={values} onChange={setValues} orgUsers={orgUsers} organizationId={organizationId} projectId={projectId}
          ownerDisplay={ownerDisplay}
        />
      </div>
    </Modal>
  );
}
