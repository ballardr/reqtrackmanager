/**
 * Module: modules/context_strategy/GuidingPrincipleFormModal
 *
 * Create/edit dialog for a Guiding Principle's content fields — mirrors
 * `StrategyFormModal.tsx`'s exact "shared by create and edit, distinguished
 * by whether `initial` is passed" convention and `docs/ux-style-guide.md`'s
 * "create-as-a-layer" principle.
 *
 * Fewer fields than `StrategyFormModal.tsx` — no `time_horizon` equivalent,
 * and `owner` is deliberately **not** a field here (see `types.ts`'s own
 * docstring on `GuidingPrincipleFieldValues` — `GuidingPrincipleDetailPage.tsx`'s
 * dedicated `RecordPrincipalField` assigns it directly, mirroring
 * `PainPointFormModal.tsx`'s identical exclusion). `change_note` only
 * renders in edit mode, same asymmetry as `StrategyFormModal.tsx`.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { FormActions } from "../../components/FormActions";
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
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
  projectId,
  error,
  onCancel,
  onSave,
}: {
  initial?: GuidingPrinciple;
  /** e.g. "organisation" / "project" — shown in the modal title so it's
   * clear which scope a new Guiding Principle is being created in, since
   * this same modal serves both the org-scoped and project-scoped pages. */
  scopeLabel: string;
  /** The project a new record is created in; with it a create form offers the quick-link field. Omit for the organisation scope. */
  projectId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: GuidingPrincipleFieldValues, quickLinks: CollectedLink[]) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [priority, setPriority] = useState<GuidingPrinciplePriority>(initial?.priority ?? "medium");
  const [changeNote, setChangeNote] = useState("");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof GuidingPrinciple] as string | undefined) ?? ""])
    )
  );

  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);

  function save() {
    onSave({
      name,
      priority,
      change_note: changeNote,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as GuidingPrincipleFieldValues, quickLinks);
  }

  const valid = name.trim() !== "" && (fields.principle_statement ?? "").trim() !== "";

  return (
    <Modal title={initial ? `Edit ${initial.name}` : `New Guiding Principle (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField label="Name" ariaLabel="Guiding Principle name" value={name} onChange={setName} />
          </FormGridFull>
          {TEXT_FIELDS.map((f) => (
            <FormGridFull key={f.key}>
              <TextAreaField
                label={f.label} rows={f.rows} value={fields[f.key] ?? ""}
                onChange={(value) => setFields((prev) => ({ ...prev, [f.key]: value }))}
              />
            </FormGridFull>
          ))}
          <LabeledSelect
            label="Priority"
            value={priority}
            onChange={(v) => setPriority(v as GuidingPrinciplePriority)}
            options={Object.entries(GUIDING_PRINCIPLE_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
          />
          {initial && (
            <FormGridFull>
              <TextField label="Change note (optional)" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} />
            </FormGridFull>
          )}
          {!initial && projectId && (
            <FormGridFull>
              <QuickLinkField projectId={projectId} artefactType="guiding_principle" value={quickLinks} onChange={setQuickLinks} />
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
