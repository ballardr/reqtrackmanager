/**
 * Module: modules/traceability/ProfileFormModal
 *
 * The dialog that creates a governance profile: name, description, how it binds projects (mode) and which projects it
 * reaches. Policy rows (lifecycle, approval, review, baseline) are set afterwards on the profile's page, so a new profile
 * starts empty and changes nothing until it holds policy.
 *
 * Responsibilities: validate the name, send `profileApi.create`, report the outcome in a toast and hand the created
 * profile to the caller, which opens it.
 *
 * Design decisions: the dialog is a `Modal` whose actions sit in its header (`FormActions`). The mode defaults to Default,
 * the gentlest of the three modes: it binds nothing a project cannot opt out of.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextAreaField, TextField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { useMutation } from "../../hooks/useMutation";
import { profileApi } from "./api";
import { GOVERNANCE_HELP } from "./help";
import { ProfileTargetsField } from "./ProfileTargetsField";
import { PROFILE_MODE_OPTIONS } from "./profileOptions";
import type { ProfileDetail, ProfileMode, ProfileTarget, ProfileTargetKind } from "./types";

/**
 * @param orgId The organisation the profile belongs to.
 * @param onCreated Called with the created profile after the toast.
 * @param onClose Closes the dialog.
 */
export function ProfileFormModal({
  orgId, onCreated, onClose,
}: { orgId: string; onCreated: (profile: ProfileDetail) => void; onClose: () => void }) {
  const run = useMutation();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<ProfileMode>("default");
  const [targetKind, setTargetKind] = useState<ProfileTargetKind>("all_projects");
  const [targets, setTargets] = useState<ProfileTarget[]>([]);
  const [busy, setBusy] = useState(false);

  /** Creates the profile; the dialog stays open when the request fails. */
  async function save() {
    let created: ProfileDetail | null = null;
    setBusy(true);
    const ok = await run(
      async () => {
        created = await profileApi.create(orgId, {
          name: name.trim(), description: description.trim(), mode, target_kind: targetKind,
          targets: targetKind === "selected_projects" ? targets : [],
        });
      },
      { success: "Profile created.", failure: "Could not create the profile." },
    );
    setBusy(false);
    if (ok && created) onCreated(created);
  }

  return (
    <Modal title="New profile" onClose={onClose} size="lg">
      <div className="stack">
        <TextField helpNotNeeded required label="Name" value={name} onChange={setName} inputProps={{ maxLength: 200 }} />
        <TextAreaField
          helpNotNeeded plainText="Configuration text shown in lists" label="Description" value={description} onChange={setDescription}
          inputProps={{ maxLength: 500 }}
        />
        <LabeledSelect
          required label="Mode" help={GOVERNANCE_HELP.profileMode} value={mode} placeholder={null} autoWidth
          options={PROFILE_MODE_OPTIONS} onChange={(value) => setMode(value as ProfileMode)}
        />
        <ProfileTargetsField
          orgId={orgId} targetKind={targetKind} targets={targets}
          onChange={(kind, next) => { setTargetKind(kind); setTargets(next); }}
        />
        <FormActions onCancel={onClose} onSave={() => void save()} saveLabel="Create" saveDisabled={busy || name.trim() === ""} cancelDisabled={busy} />
      </div>
    </Modal>
  );
}
