/**
 * Module: modules/stakeholders/PersonaFormModal
 *
 * Create/edit dialog for a Persona's content fields (docs/ux-style-guide.md
 * principle 3: a full entity create/edit is a `Modal`). Shared by create and
 * edit (distinguished by whether `initial` is passed) and by the org and
 * project scopes (`scopeLabel` only changes the title).
 *
 * `owner_id`/`champion_id` are not fields here — `PersonaDetailPage` assigns
 * them through `AssigneePicker`. `weight` is optional: blank means "no
 * weight", which scoring treats as equal weighting. `change_note` only
 * renders when editing. Every field has a visible label (principle 13).
 */
import { useState } from "react";

import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import type { Persona, PersonaFieldValues } from "./types";

const TEXT_FIELDS: { key: keyof PersonaFieldValues; label: string; rows: number }[] = [
  { key: "description", label: "Description", rows: 2 },
  { key: "goals", label: "Goals", rows: 2 },
  { key: "needs", label: "Needs", rows: 2 },
  { key: "behaviours", label: "Behaviours", rows: 2 },
  { key: "context_environment", label: "Context / environment", rows: 2 },
  { key: "skills_proficiency", label: "Skills / proficiency", rows: 2 },
  { key: "frequency_of_use", label: "Frequency of use", rows: 1 },
  { key: "constraints", label: "Constraints", rows: 2 },
];

export function PersonaFormModal({
  initial,
  scopeLabel,
  typeOptions,
  error,
  onCancel,
  onSave,
}: {
  initial?: Persona;
  /** e.g. "organisation" / "project", shown in the title of a new persona. */
  scopeLabel: string;
  /** The enabled types this scope offers; the current type is always kept selectable. */
  typeOptions: { value: string; label: string }[];
  error?: string | null;
  onCancel: () => void;
  onSave: (values: PersonaFieldValues) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [typeId, setTypeId] = useState(initial?.persona_type_id ?? "");
  const [roleTitle, setRoleTitle] = useState(initial?.role_title ?? "");
  const [weight, setWeight] = useState(initial?.weight != null ? String(initial.weight) : "");
  const [changeNote, setChangeNote] = useState("");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof Persona] as string | undefined) ?? ""])),
  );

  const weightNumber = weight.trim() === "" ? null : Number(weight);
  const weightValid = weightNumber === null || (Number.isFinite(weightNumber) && weightNumber > 0);
  const valid = name.trim() !== "" && weightValid;

  const options =
    initial?.persona_type_id && !typeOptions.some((o) => o.value === initial.persona_type_id)
      ? [...typeOptions, { value: initial.persona_type_id, label: `${initial.persona_type_name ?? "Current type"} (disabled)` }]
      : typeOptions;

  function save() {
    onSave({
      name: name.trim(),
      persona_type_id: typeId || null,
      role_title: roleTitle,
      weight: weightNumber,
      change_note: changeNote,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as PersonaFieldValues);
  }

  return (
    <Modal title={initial ? `Edit ${initial.name}` : `New Persona (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Persona name" />
        </label>
        <LabeledSelect label="Type" value={typeId} onChange={setTypeId} options={options} placeholder="No type" />
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Role / job title</span>
          <input className="input" value={roleTitle} onChange={(e) => setRoleTitle(e.target.value)} aria-label="Role or job title" />
        </label>
        {TEXT_FIELDS.map((f) => (
          <label key={f.key} className="stack" style={{ gap: "0.25rem" }}>
            <span>{f.label}</span>
            <textarea
              className="input"
              rows={f.rows}
              value={fields[f.key] ?? ""}
              onChange={(e) => setFields((prev) => ({ ...prev, [f.key]: e.target.value }))}
              aria-label={f.label}
            />
          </label>
        ))}
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Importance weight (optional)</span>
          <input
            className="input"
            type="number"
            min="0"
            step="any"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
            aria-label="Importance weight"
            aria-invalid={!weightValid}
          />
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>
            Used when scoring against personas. Leave blank to weight every persona equally; must be greater than zero.
          </span>
        </label>
        {initial && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Change note (optional)</span>
            <input className="input" value={changeNote} onChange={(e) => setChangeNote(e.target.value)} aria-label="Change note" />
          </label>
        )}
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={!valid} onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
