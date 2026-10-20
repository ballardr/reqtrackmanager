/**
 * Module: modules/decisions/DecisionTemplateFormModal
 *
 * Create/edit dialog for an org-scoped `DecisionTemplate` — nine fields (name, description, and seven per-content-
 * field prompt texts), too busy for `DefinitionList`'s inline-row-edit
 * shape, so this follows `modules/compliance/StandardFormModal.tsx`'s own
 * precedent: a dedicated `size="lg"` `Modal` form shared by create and edit,
 * distinguished by whether `initial` is passed (mirrors
 * `EvidencePanel.tsx`'s `EvidenceFormModal` for the smaller-scale version of
 * the same create/edit split).
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
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
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Template name" value={name} onChange={setName} />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Description" value={description} onChange={setDescription} />
          </FormGridFull>
          {PROMPT_FIELDS.map((f) => (
            <FormGridFull key={f.key}>
              <TextAreaField helpNotNeeded
                label={f.label} value={prompts[f.key]}
                onChange={(value) => setPrompts((p) => ({ ...p, [f.key]: value }))}
              />
            </FormGridFull>
          ))}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={!name.trim()} />
      </div>
    </Modal>
  );
}
