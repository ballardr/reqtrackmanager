/**
 * Module: components/StageWorkflowEditor
 *
 * The create/edit dialog for a stage workflow: its name and its ordered phases, each with a free-text name and a kind
 * that carries the behaviour (open, review, locked, on hold, closed). The phases are one grid, one line per phase
 * (order, name, kind, a row actions menu), in the aligned-rows pattern of docs/ux-style-guide.md; Save is in the dialog
 * header. `StageWorkflowsPanel` uses it for both tiers. The caller saves; an existing phase keeps its `id` so a stage
 * following it is not detached.
 */
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import type { StagePhaseKind, StageWorkflow, StageWorkflowPhaseWrite } from "../api/types";
import { STAGE_PHASE_KIND_LABEL, STAGE_PHASE_KINDS } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { FieldCaption, FieldHelp } from "./FieldHelp";
import { FormActions } from "./FormActions";
import { InlineTextInput, TextField } from "./FormFields";
import { InlineSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/** Column tracks: order number, name (takes the spare width), kind (as wide as its longest option), row menu. */
const PHASE_TRACKS = "2.5rem minmax(7rem, 1fr) fit-content(10rem) 2.25rem";

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
  const rowItems = (index: number): ActionMenuItem[] => {
    const s = strings.stageWorkflows;
    const items: ActionMenuItem[] = [];
    if (index > 0) items.push({ label: s.moveUp, icon: <ArrowUp />, onSelect: () => movePhase(index, -1) });
    if (index < phases.length - 1) items.push({ label: s.moveDown, icon: <ArrowDown />, onSelect: () => movePhase(index, 1) });
    items.push({
      label: s.remove, icon: <Trash2 />, danger: true, disabled: phases.length === 1, title: phases.length === 1 ? s.lastPhaseTitle : undefined,
      onSelect: () => setPhases((list) => list.filter((_, i) => i !== index)),
    });
    return items;
  };
  return (
    <Modal title={workflow ? strings.stageWorkflows.editWorkflow : strings.stageWorkflows.newWorkflow} onClose={onCancel} size="lg">
      <div className="stack">
        <TextField helpNotNeeded required label={strings.stageWorkflows.workflowName} value={name} onChange={setName} />
        <div className="stack" style={{ gap: "var(--space-2)" }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <FieldCaption label={strings.stageWorkflows.phases} help={strings.help.workflowPhases} required />
            <button className="btn btn-sm" onClick={() => setPhases((list) => [...list, { name: "", kind: "open" }])}>
              <Plus /> {strings.stageWorkflows.addPhase}
            </button>
          </div>
          <div className="definition-grid" role="group" aria-label={strings.stageWorkflows.phases} style={{ gridTemplateColumns: PHASE_TRACKS }}>
            <div className="definition-grid__head">{strings.stageWorkflows.order}</div>
            <div className="definition-grid__head">{strings.stageWorkflows.phase}</div>
            <div className="definition-grid__head">
              <span className="field-caption">
                <span>{strings.stageWorkflows.phaseKind}</span>
                <FieldHelp label={strings.stageWorkflows.phaseKind} help={strings.help.workflowPhaseKind} />
              </span>
            </div>
            <div className="definition-grid__head" />
            {phases.map((phase, index) => (
              <div key={phase.id ?? `new-${index}`} className="definition-grid__row">
                <div className="definition-grid__cell text-muted">{index + 1}</div>
                <div className="definition-grid__cell">
                  <InlineTextInput
                    ariaLabel={`${strings.stageWorkflows.phaseName} ${index + 1}`} value={phase.name}
                    onChange={(next) => setPhase(index, { name: next })}
                  />
                </div>
                <div className="definition-grid__cell">
                  <InlineSelect
                    ariaLabel={`${strings.stageWorkflows.phaseKind} ${index + 1}`} value={phase.kind} placeholder={null} autoWidth
                    onChange={(next) => setPhase(index, { kind: next as StagePhaseKind })}
                    options={STAGE_PHASE_KINDS.map((kind) => ({ value: kind, label: STAGE_PHASE_KIND_LABEL[kind] }))}
                  />
                </div>
                <div className="definition-grid__actions">
                  <ActionMenu
                    size="sm" items={rowItems(index)}
                    triggerLabel={strings.stageWorkflows.phaseActionsAria(phase.name || String(index + 1))}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={!valid}
          onSave={() => onSave({ name: name.trim(), phases: phases.map((p) => ({ ...p, name: p.name.trim() })) })}
        />
      </div>
    </Modal>
  );
}
