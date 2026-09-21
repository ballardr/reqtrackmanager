/**
 * Module: modules/decisions/DecisionTemplateFormModal
 *
 * Create/edit dialog for an org-scoped `DecisionTemplate` (Phase 0 addendum
 * items 1/2/6/7) — nine fields (name, description, and seven per-content-
 * field prompt texts), too busy for `DefinitionList`'s inline-row-edit
 * shape, so this follows `modules/compliance/StandardFormModal.tsx`'s own
 * precedent: a dedicated `size="lg"` `Modal` form shared by create and edit,
 * distinguished by whether `initial` is passed (mirrors
 * `EvidencePanel.tsx`'s `EvidenceFormModal` for the smaller-scale version of
 * the same create/edit split).
 */
import { useState } from "react";

import { Modal } from "../../components/Modal";
import type { DecisionTemplateFieldValues } from "./types";

const PROMPT_FIELDS: { key: keyof DecisionTemplateFieldValues; label: string }[] = [
  { key: "context_prompt", label: "Context — prompt/guidance" },
  { key: "options_considered_prompt", label: "Options considered — prompt/guidance" },
  { key: "chosen_option_prompt", label: "Chosen option — prompt/guidance" },
  { key: "rationale_prompt", label: "Rationale — prompt/guidance" },
  { key: "consequences_prompt", label: "Consequences — prompt/guidance" },
  { key: "assumptions_prompt", label: "Assumptions — prompt/guidance" },
  { key: "constraints_prompt", label: "Constraints — prompt/guidance" },
];

export function DecisionTemplateFormModal({
  initial,
  error,
  onCancel,
  onSave,
}: {
  initial?: DecisionTemplateFieldValues;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: DecisionTemplateFieldValues) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [prompts, setPrompts] = useState<Record<string, string>>(() =>
    Object.fromEntries(PROMPT_FIELDS.map((f) => [f.key, (initial?.[f.key] as string | null) ?? ""]))
  );

  function save() {
    onSave({
      name,
      description: description || null,
      ...(Object.fromEntries(
        PROMPT_FIELDS.map((f) => [f.key, prompts[f.key] || null])
      ) as Record<string, string | null>),
    } as DecisionTemplateFieldValues);
  }

  return (
    <Modal title={initial ? "Edit decision template" : "New decision template"} onClose={onCancel} size="lg">
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Template name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Template name" />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Description</span>
          <textarea className="input" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        {PROMPT_FIELDS.map((f) => (
          <label key={f.key} className="stack" style={{ gap: "0.25rem" }}>
            <span>{f.label}</span>
            <textarea
              className="input"
              rows={2}
              value={prompts[f.key]}
              onChange={(e) => setPrompts((p) => ({ ...p, [f.key]: e.target.value }))}
            />
          </label>
        ))}
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={!name.trim()} onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
