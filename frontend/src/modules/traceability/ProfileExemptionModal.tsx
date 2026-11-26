/**
 * Module: modules/traceability/ProfileExemptionModal
 *
 * The dialog that exempts one project from an Enforced profile: the project, whether its nested projects are exempt too and
 * the reason, which is kept for audit and review.
 *
 * Responsibilities: offer only projects that are not already exempt, send `profileApi.addExemption` and hand the updated
 * profile to the caller.
 *
 * Design decisions: an exemption lifts only this profile for the project; the project's own choices and the organisation's
 * other profiles still apply, which the project field's help says.
 */
import { useState } from "react";

import { CheckboxField, TextAreaField } from "../../components/FormFields";
import { FormActions } from "../../components/FormActions";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { useMutation } from "../../hooks/useMutation";
import { profileApi } from "./api";
import { GOVERNANCE_HELP } from "./help";
import type { ProfileDetail } from "./types";
import { projectChoiceLabel, useOrgProjectChoices } from "./useOrgProjectChoices";

/**
 * @param orgId The organisation.
 * @param profileId The Enforced profile the project is exempted from.
 * @param taken Ids of the projects that are already exempt.
 * @param onAdded Called with the updated profile after the exemption is saved.
 * @param onClose Closes the dialog.
 */
export function ProfileExemptionModal({
  orgId, profileId, taken, onAdded, onClose,
}: { orgId: string; profileId: string; taken: ReadonlySet<string>; onAdded: (profile: ProfileDetail) => void; onClose: () => void }) {
  const run = useMutation();
  const { projects, failed } = useOrgProjectChoices(orgId);
  const [projectId, setProjectId] = useState("");
  const [includeChildren, setIncludeChildren] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const options = (projects ?? []).filter((p) => !taken.has(p.id)).map((p) => ({ value: p.id, label: projectChoiceLabel(p) }));

  /** Saves the exemption; the dialog stays open when the request fails. */
  async function save() {
    let updated: ProfileDetail | null = null;
    setBusy(true);
    const ok = await run(
      async () => {
        updated = await profileApi.addExemption(orgId, profileId, { project_id: projectId, include_children: includeChildren, reason: reason.trim() });
      },
      { success: "Exemption added.", failure: "Could not add the exemption." },
    );
    setBusy(false);
    if (ok && updated) onAdded(updated);
  }

  return (
    <Modal title="Add exemption" onClose={onClose}>
      <div className="stack">
        {failed && <span role="alert" style={{ color: "var(--color-danger)" }}>The organisation's projects could not be loaded.</span>}
        <LabeledSelect required label="Project" help={GOVERNANCE_HELP.profileExemptionProject} value={projectId} options={options} onChange={setProjectId} />
        <CheckboxField label="Includes nested projects" help={GOVERNANCE_HELP.profileTargetChildren} checked={includeChildren} onChange={setIncludeChildren} />
        <TextAreaField
          label="Reason" help={GOVERNANCE_HELP.profileExemptionReason} plainText="Audit text shown in the exemption list" value={reason}
          onChange={setReason} inputProps={{ maxLength: 500 }}
        />
        <FormActions onCancel={onClose} onSave={() => void save()} saveLabel="Add exemption" saveDisabled={busy || projectId === ""} cancelDisabled={busy} />
      </div>
    </Modal>
  );
}
