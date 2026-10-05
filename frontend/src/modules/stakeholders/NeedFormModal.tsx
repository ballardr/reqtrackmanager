/**
 * Module: modules/stakeholders/NeedFormModal
 *
 * Create/edit dialog for a Stakeholder Need's content fields (docs/ux-style-
 * guide.md principle 3: a full entity create/edit is a `Modal`). Shared by
 * create and edit (distinguished by whether `initial` is passed). A need is
 * always project-scoped, so unlike the Persona/Stakeholder forms there is no
 * scope or type to choose. `owner_id` is assigned from the detail page through
 * `AssigneePicker`; `change_note` only renders when editing. Every field has a
 * visible label (principle 13).
 */
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { TextAreaField, TextField } from "./RecordFormFields";
import type { Need, NeedFieldValues } from "./types";

export function NeedFormModal({
  initial,
  error,
  onCancel,
  onSave,
}: {
  initial?: Need;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: NeedFieldValues) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [rationale, setRationale] = useState(initial?.rationale ?? "");
  const [changeNote, setChangeNote] = useState("");

  return (
    <Modal title={initial ? `Edit ${initial.name}` : "New Stakeholder Need"} onClose={onCancel} size="lg">
      <div className="stack">
        <TextField label="Name" ariaLabel="Need name" value={name} onChange={setName} hint="A short title, e.g. “Diagnose faults quickly”." />
        <TextAreaField
          label="Need" rows={3} value={description} onChange={setDescription}
          hint="The need in the stakeholder's own words, before it becomes a requirement."
        />
        <TextAreaField label="Rationale" rows={3} value={rationale} onChange={setRationale} hint="Why it matters, and where it came from." />
        {initial && <TextField label="Change note (optional)" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} />}
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={name.trim() === ""}
            onClick={() => onSave({ name: name.trim(), description, rationale, change_note: changeNote })}
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
