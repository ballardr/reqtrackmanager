/**
 * Module: components/ServiceUserFormModal
 *
 * Creates or edits a service user in a dialog over the shared `ServiceUserFields`. Saving is the caller's: it sends
 * the draft to the endpoint and reports a failure through `error`. The form has no quick-link, tag or placement
 * fields because a service user is an account, not a record in a project.
 */
import { useState } from "react";

import { BLANK_SERVICE_USER, draftFromServiceUser, type ServiceUser, type ServiceUserDraft } from "../api/serviceUsers";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { ServiceUserFields } from "./ServiceUserFields";

/**
 * @param organizationId The organisation the service user belongs to.
 * @param initial The service user being edited; omit to create one.
 * @param error A save error to show in the header.
 * @param onCancel Closes the dialog.
 * @param onSave Called with the values to save.
 */
export function ServiceUserFormModal({
  organizationId, initial, error, onCancel, onSave,
}: {
  organizationId: string;
  initial?: ServiceUser;
  error?: string | null;
  onCancel: () => void;
  onSave: (draft: ServiceUserDraft) => void;
}) {
  const strings = useStrings();
  const [draft, setDraft] = useState<ServiceUserDraft>(() => (initial ? draftFromServiceUser(initial) : BLANK_SERVICE_USER));
  return (
    <Modal title={initial ? strings.serviceUsers.editTitle : strings.serviceUsers.createTitle} onClose={onCancel} size="lg">
      <div className="stack">
        <ServiceUserFields
          draft={draft} organizationId={organizationId} responsibleDisplay={initial?.responsible}
          onChange={(patch) => setDraft((current) => ({ ...current, ...patch }))}
        />
        <FormActions
          error={error} onCancel={onCancel} onSave={() => onSave(draft)}
          saveLabel={initial ? strings.common.save : strings.common.create} saveDisabled={!draft.name.trim()}
        />
      </div>
    </Modal>
  );
}
