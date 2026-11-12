/**
 * Module: modules/architecture/DiagramTogglesPanel
 *
 * The editor's "View switches" card. Each switch is a labelled on/off control that changes only what this page shows
 * (the choice lives in the page address and is never stored); "Edit" and "Remove" change the diagram's stored switches, and
 * "Add switch" opens `ToggleFormModal`. A switch that is off hides its elements and connections, and a hidden element
 * between two others is bridged by a dashed line.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DetailCard } from "../../components/DetailCard";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import type { DiagramToggle } from "./types";

/**
 * @param toggles The diagram's switches with their state in this view.
 * @param editable False hides Add, Edit and Remove (the viewer cannot change the diagram).
 * @param onFlip Called when a switch is flipped on the page, with the state it should now have.
 * @param onAdd Opens the new-switch form.
 * @param onEdit Opens the form for a switch.
 * @param onRemove Removes a switch from the diagram (after confirmation).
 */
export function DiagramTogglesPanel({
  toggles, editable, onFlip, onAdd, onEdit, onRemove,
}: {
  toggles: DiagramToggle[];
  editable: boolean;
  onFlip: (toggle: DiagramToggle, on: boolean) => void;
  onAdd: () => void;
  onEdit: (toggle: DiagramToggle) => void;
  onRemove: (toggle: DiagramToggle) => void;
}) {
  const [removing, setRemoving] = useState<DiagramToggle | null>(null);
  return (
    <DetailCard
      heading="View switches"
      action={editable ? <button type="button" className="btn btn-sm" onClick={onAdd}>Add switch</button> : undefined}
    >
      {toggles.length === 0 ? (
        <p className="text-muted">This diagram has no view switches.</p>
      ) : (
        <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--space-2)" }}>
          {toggles.map((t) => (
            <li key={t.id} className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
                <ToggleSwitch checked={t.on} onChange={(on) => onFlip(t, on)} label={t.name} />
                <span>{t.name}</span>
              </span>
              {editable && (
                <span className="row" style={{ gap: "var(--space-1)" }}>
                  <button type="button" className="btn btn-sm" aria-label={`Edit switch ${t.name}`} onClick={() => onEdit(t)}>Edit</button>
                  <button type="button" className="btn btn-sm" aria-label={`Remove switch ${t.name}`} onClick={() => setRemoving(t)}>Remove</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {removing && (
        <ConfirmDialog
          title="Remove this switch?"
          message={`The switch "${removing.name}" is removed from this diagram. Its elements and connections are not changed.`}
          confirmLabel="Remove"
          onConfirm={() => { onRemove(removing); setRemoving(null); }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </DetailCard>
  );
}
