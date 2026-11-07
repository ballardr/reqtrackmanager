/**
 * Module: components/StageWorkflowEditor
 *
 * The create/edit dialog for a stage workflow: its name and its ordered phases, each with a free-text
 * name and a kind that carries the behaviour (open, review, locked, on hold, closed). Used by
 * `StageWorkflowsPanel` for both the organisation and the project tier, so the two cannot drift. The
 * caller saves; an existing phase keeps its `id` so a stage following it is not detached.
 */
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import type { StagePhaseKind, StageWorkflow, StageWorkflowPhaseWrite } from "../api/types";
import { STAGE_PHASE_KIND_LABEL, STAGE_PHASE_KINDS } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FieldCaption } from "./FieldHelp";
import { FormActions } from "./FormActions";
import { InlineTextInput, TextField } from "./FormFields";
import { InlineSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/** The values the dialog saves. */
export interface StageWorkflowValues {
  name: string;
  phases: StageWorkflowPhaseWrite[];
}

/**
 * @param workflow The workflow being edited, or null to create one (it starts with a single open phase).
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the name and the phases in order (the first is the starting phase).
 */
export function StageWorkflowEditor({
  workflow, error, onCancel, onSave,
}: {
  workflow: StageWorkflow | null;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StageWorkflowValues) => void;
}) {
  const strings = useStrings();
  const [name, setName] = useState(workflow?.name ?? "");
  const [phases, setPhases] = useState<StageWorkflowPhaseWrite[]>(
    workflow ? workflow.phases.map((p) => ({ id: p.id, name: p.name, kind: p.kind })) : [{ name: "", kind: "open" }],
  );
  const setPhase = (index: number, change: Partial<StageWorkflowPhaseWrite>) =>
    setPhases((list) => list.map((p, i) => (i === index ? { ...p, ...change } : p)));
  const movePhase = (index: number, delta: number) =>
    setPhases((list) => {
      const target = index + delta;
      if (target < 0 || target >= list.length) return list;
      const next = [...list];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  const valid = name.trim() !== "" && phases.length > 0 && phases.every((p) => p.name.trim() !== "");
  return (
    <Modal title={workflow ? strings.stageWorkflows.editWorkflow : strings.stageWorkflows.newWorkflow} onClose={onCancel} size="lg">
      <div className="stack">
        <TextField helpNotNeeded required label={strings.stageWorkflows.workflowName} value={name} onChange={setName} />
        <div className="stack" style={{ gap: "var(--space-2)" }}>
          <FieldCaption label={strings.stageWorkflows.phases} help={strings.help.workflowPhases} required />
          {phases.map((phase, index) => (
            <div key={phase.id ?? `new-${index}`} className="row">
              <InlineTextInput
                ariaLabel={`${strings.stageWorkflows.phaseName} ${index + 1}`} value={phase.name}
                onChange={(next) => setPhase(index, { name: next })}
              />
              <InlineSelect
                ariaLabel={`${strings.stageWorkflows.phaseKind} ${index + 1}`} value={phase.kind} placeholder={null}
                onChange={(next) => setPhase(index, { kind: next as StagePhaseKind })}
                options={STAGE_PHASE_KINDS.map((kind) => ({ value: kind, label: STAGE_PHASE_KIND_LABEL[kind] }))}
              />
              <button
                className="btn" disabled={index === 0} onClick={() => movePhase(index, -1)}
                aria-label={strings.stageWorkflows.movePhaseUp(phase.name || String(index + 1))}
              >
                <ArrowUp />
              </button>
              <button
                className="btn" disabled={index === phases.length - 1} onClick={() => movePhase(index, 1)}
                aria-label={strings.stageWorkflows.movePhaseDown(phase.name || String(index + 1))}
              >
                <ArrowDown />
              </button>
              <button
                className="btn btn-danger" disabled={phases.length === 1}
                onClick={() => setPhases((list) => list.filter((_, i) => i !== index))}
                aria-label={strings.stageWorkflows.removePhase(phase.name || String(index + 1))}
              >
                <Trash2 />
              </button>
            </div>
          ))}
          <div>
            <button className="btn" onClick={() => setPhases((list) => [...list, { name: "", kind: "open" }])}>
              <Plus /> {strings.stageWorkflows.addPhase}
            </button>
          </div>
          <FieldCaption label={strings.stageWorkflows.phaseKind} help={strings.help.workflowPhaseKind} muted />
        </div>
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={!valid}
          onSave={() => onSave({ name: name.trim(), phases: phases.map((p) => ({ ...p, name: p.name.trim() })) })}
        />
      </div>
    </Modal>
  );
}
