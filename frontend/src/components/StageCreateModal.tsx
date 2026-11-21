/**
 * Module: components/StageCreateModal
 *
 * The dialog that adds a stage to a project, opened by Project Administration's "New stage" button so the Stages
 * section shows no empty fields until someone asks (docs/ux-style-guide.md, "Pattern: creation controls on demand").
 *
 * Responsibilities:
 * - Collect the stage's name and the workflow that governs its phases; offer a shortcut to define a new workflow
 *   (`onNewWorkflow`, which opens its own editor over this dialog and selects the result through `workflowId`).
 * - Hand the values to `onCreate`; the dialog closes only when it reports success, and a refusal is already toasted.
 *
 * The workflow choice is controlled by the caller because creating a workflow elsewhere selects it here.
 */
import { Plus } from "lucide-react";
import { useState } from "react";

import type { StageWorkflow } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FormActions } from "./FormActions";
import { TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/**
 * @param workflows The project's workflows; the first is the default.
 * @param workflowId The chosen workflow id (empty for the first one).
 * @param onWorkflowChange Called when another workflow is picked.
 * @param onNewWorkflow Opens the workflow editor.
 * @param onCreate Creates the stage; resolves true when it exists (the dialog then closes).
 * @param onClose Closes the dialog.
 */
export function StageCreateModal({
  workflows, workflowId, onWorkflowChange, onNewWorkflow, onCreate, onClose,
}: {
  workflows: StageWorkflow[];
  workflowId: string;
  onWorkflowChange: (id: string) => void;
  onNewWorkflow: () => void;
  onCreate: (name: string, workflowId: string) => Promise<boolean>;
  onClose: () => void;
}) {
  const strings = useStrings();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = name.trim() !== "";

  async function save() {
    if (!valid || busy) return;
    setBusy(true);
    const created = await onCreate(name, workflowId || workflows[0]?.id || "");
    setBusy(false);
    if (created) onClose();
  }

  return (
    <Modal title={strings.admin.newStage} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <TextField helpNotNeeded required label={strings.admin.name} value={name} onChange={setName} inputProps={{ autoFocus: true }} />
        <LabeledSelect
          help={strings.help.stageWorkflowChoice} label={strings.stageWorkflows.workflow} placeholder={null}
          value={workflowId || workflows[0]?.id || ""} onChange={onWorkflowChange}
          options={workflows.map((w) => ({ value: w.id, label: w.name }))}
        />
        <div>
          <button type="button" className="btn" onClick={onNewWorkflow}><Plus /> {strings.stageWorkflows.newWorkflow}</button>
        </div>
        <FormActions onCancel={onClose} onSave={() => void save()} saveLabel={strings.common.add} saveDisabled={!valid || busy} />
      </form>
    </Modal>
  );
}
