/**
 * Module: modules/context_strategy/StrategyFormModal
 *
 * Create/edit dialog for a Strategy's content fields — mirrors `modules/decisions/
 * DecisionFormModal.tsx`'s "shared by create and edit, distinguished by
 * whether `initial` is passed" convention, and `docs/ux-style-guide.md`'s
 * "create-as-a-layer" principle: creation happens in a `Modal` layered over
 * the list, never a full navigation away from it.
 *
 * `change_note` only renders in edit mode (mirrors Decision's identical
 * create/edit field-set asymmetry) — a new Strategy has no prior version to
 * explain a change from.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { FormActions } from "../../components/FormActions";
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { STRATEGY_PRIORITY_LABEL, STRATEGY_TIME_HORIZON_LABEL } from "./types";
import type { Strategy, StrategyFieldValues, StrategyPriority, StrategyTimeHorizon } from "./types";

const TEXT_FIELDS: { key: keyof StrategyFieldValues; label: string; rows: number }[] = [
  { key: "objective", label: "Objective / strategic theme", rows: 2 },
  { key: "current_state", label: "Current state", rows: 2 },
  { key: "desired_future_state", label: "Desired future state", rows: 2 },
  { key: "rationale", label: "Rationale", rows: 2 },
  { key: "expected_outcomes", label: "Expected outcomes", rows: 2 },
  { key: "constraints", label: "Constraints", rows: 2 },
  { key: "measures_of_success", label: "Measures of success", rows: 2 },
];

export function StrategyFormModal({
  initial,
  scopeLabel,
  projectId,
  error,
  onCancel,
  onSave,
}: {
  initial?: Strategy;
  /** e.g. "organisation" / a project's own name — shown in the modal title
   * so it's clear which scope a new Strategy is being created in, since
   * this same modal serves both the org-scoped and project-scoped pages. */
  scopeLabel: string;
  /** The project a new record is created in; with it a create form offers the quick-link field. Omit for the organisation scope. */
  projectId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StrategyFieldValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [priority, setPriority] = useState<StrategyPriority>(initial?.priority ?? "medium");
  const [timeHorizon, setTimeHorizon] = useState<StrategyTimeHorizon>(initial?.time_horizon ?? "medium_term");
  const [changeNote, setChangeNote] = useState("");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof Strategy] as string | undefined) ?? ""]))
  );

  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);

  function save() {
    onSave({
      title,
      priority,
      time_horizon: timeHorizon,
      change_note: changeNote,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as StrategyFieldValues, quickLinks, tags);
  }

  const valid = title.trim() !== "" && (fields.objective ?? "").trim() !== "";

  return (
    <Modal title={initial ? `Edit ${initial.title}` : `New Strategy (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Title" ariaLabel="Strategy title" value={title} onChange={setTitle} />
          </FormGridFull>
          {TEXT_FIELDS.map((f) => (
            <FormGridFull key={f.key}>
              <TextAreaField helpNotNeeded required={f.key === "objective"}
                label={f.label} rows={f.rows} value={fields[f.key] ?? ""}
                onChange={(value) => setFields((prev) => ({ ...prev, [f.key]: value }))}
              />
            </FormGridFull>
          ))}
          <LabeledSelect helpNotNeeded
            label="Priority"
            value={priority}
            onChange={(v) => setPriority(v as StrategyPriority)}
            options={Object.entries(STRATEGY_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
          />
          <LabeledSelect helpNotNeeded
            label="Time horizon"
            value={timeHorizon}
            onChange={(v) => setTimeHorizon(v as StrategyTimeHorizon)}
            options={Object.entries(STRATEGY_TIME_HORIZON_LABEL).map(([value, label]) => ({ value, label }))}
          />
          {initial && (
            <FormGridFull>
              <TextField helpNotNeeded label="Change note" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} />
            </FormGridFull>
          )}
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="strategy" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="strategy" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
