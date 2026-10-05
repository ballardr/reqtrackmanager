/**
 * Module: modules/context_strategy/GuidingPrincipleFormModal
 *
 * Create/edit dialog for a Guiding Principle's content fields (docs/plans/
 * module-01-context-and-strategy-plan.md Phase 7.4) — mirrors
 * `StrategyFormModal.tsx`'s exact "shared by create and edit, distinguished
 * by whether `initial` is passed" convention and `docs/ux-style-guide.md`'s
 * "create-as-a-layer" principle.
 *
 * Fewer fields than `StrategyFormModal.tsx` — no `time_horizon` equivalent,
 * and `owner_id` is deliberately **not** a field here (see `types.ts`'s own
 * docstring on `GuidingPrincipleFieldValues` — `GuidingPrincipleDetailPage.tsx`'s
 * dedicated `AssigneePicker` assigns it directly, mirroring
 * `PainPointFormModal.tsx`'s identical exclusion). `change_note` only
 * renders in edit mode, same asymmetry as `StrategyFormModal.tsx`.
 */
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { LabeledSelect } from "../../components/LabeledSelect";
import { GUIDING_PRINCIPLE_PRIORITY_LABEL } from "./types";
import type { GuidingPrinciple, GuidingPrincipleFieldValues, GuidingPrinciplePriority } from "./types";

const TEXT_FIELDS: { key: keyof GuidingPrincipleFieldValues; label: string; rows: number }[] = [
  { key: "principle_statement", label: "Principle statement", rows: 3 },
  { key: "rationale", label: "Rationale", rows: 2 },
];

export function GuidingPrincipleFormModal({
  initial,
  scopeLabel,
  error,
  onCancel,
  onSave,
}: {
  initial?: GuidingPrinciple;
  /** e.g. "organisation" / "project" — shown in the modal title so it's
   * clear which scope a new Guiding Principle is being created in, since
   * this same modal serves both the org-scoped and project-scoped pages. */
  scopeLabel: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: GuidingPrincipleFieldValues) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [priority, setPriority] = useState<GuidingPrinciplePriority>(initial?.priority ?? "medium");
  const [changeNote, setChangeNote] = useState("");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof GuidingPrinciple] as string | undefined) ?? ""])
    )
  );

  function save() {
    onSave({
      name,
      priority,
      change_note: changeNote,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as GuidingPrincipleFieldValues);
  }

  const valid = name.trim() !== "" && (fields.principle_statement ?? "").trim() !== "";

  return (
    <Modal title={initial ? `Edit ${initial.name}` : `New Guiding Principle (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Guiding Principle name" />
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
        <LabeledSelect
          label="Priority"
          value={priority}
          onChange={(v) => setPriority(v as GuidingPrinciplePriority)}
          options={Object.entries(GUIDING_PRINCIPLE_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
        />
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
