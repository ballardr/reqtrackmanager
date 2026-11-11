/**
 * Module: components/ComponentTrackEditor
 *
 * The dialog for one component's track within one stage when component phases are on: the workflow the
 * component follows, whether the stage applies to it at all, and an owner (a user or a group) who may move
 * the track. The caller saves; only what the dialog changes is sent, and the server refuses a workflow or
 * applicability change once the track has left an open phase or has a baseline, its message shown here.
 */
import { useState } from "react";

import type { OrgUser, PrincipalRef, StageWorkflow, ComponentTrack } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { PrincipalFormField } from "./PrincipalFormField";
import { ToggleField } from "./FormFields";

/** The changes the dialog saves; a key is present only when it differs from the track. */
export interface ComponentTrackChanges {
  workflow_id?: string;
  not_applicable?: boolean;
  owner?: PrincipalRef | null;
}

/**
 * @param track The track being edited.
 * @param componentName The component's name, for the title.
 * @param stageName The stage's name, for the title.
 * @param workflows The workflows the project may use.
 * @param orgUsers The organisation's users, for the owner picker.
 * @param organizationId The organisation, enabling user search and group listing in the picker.
 * @param projectId The project, enabling project groups in the picker.
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the changes (possibly none).
 */
export function ComponentTrackEditor({
  track, componentName, stageName, workflows, orgUsers, organizationId, projectId, error, onCancel, onSave,
}: {
  track: ComponentTrack;
  componentName: string;
  stageName: string;
  workflows: StageWorkflow[];
  orgUsers: OrgUser[];
  organizationId: string;
  projectId: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (changes: ComponentTrackChanges) => void;
}) {
  const strings = useStrings();
  const [workflowId, setWorkflowId] = useState(track.workflow_id);
  const [notApplicable, setNotApplicable] = useState(track.not_applicable);
  const [owner, setOwner] = useState<PrincipalRef | null>(track.owner ? { type: track.owner.type, id: track.owner.id } : null);
  const ownerChanged = (owner?.id ?? null) !== (track.owner?.id ?? null) || (owner?.type ?? null) !== (track.owner?.type ?? null);

  function save() {
    const changes: ComponentTrackChanges = {};
    if (workflowId !== track.workflow_id) changes.workflow_id = workflowId;
    if (notApplicable !== track.not_applicable) changes.not_applicable = notApplicable;
    if (ownerChanged) changes.owner = owner;
    onSave(changes);
  }

  return (
    <Modal title={strings.componentPhases.editTitle(componentName, stageName)} onClose={onCancel}>
      <div className="stack">
        <LabeledSelect
          label={strings.componentPhases.workflow} help={strings.help.componentTrackWorkflow} placeholder={null}
          value={workflowId} onChange={setWorkflowId} options={workflows.map((w) => ({ value: w.id, label: w.name }))}
        />
        <ToggleField
          label={strings.componentPhases.notApplicable} help={strings.help.componentTrackNotApplicable}
          checked={notApplicable} onChange={setNotApplicable}
        />
        <PrincipalFormField
          label={strings.componentPhases.owner} help={strings.help.componentTrackOwner} ariaLabel={strings.componentPhases.ownerAria}
          orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} value={owner} display={track.owner}
          onChange={setOwner} clearLabel={strings.componentPhases.unassign}
        />
        <FormActions error={error} onCancel={onCancel} onSave={save} />
      </div>
    </Modal>
  );
}
