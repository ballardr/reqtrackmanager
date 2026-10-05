/**
 * Module: modules/context_strategy/StrategyFormModal
 *
 * Create/edit dialog for a Strategy's content fields (docs/plans/module-01-
 * context-and-strategy-plan.md Phase 7.1) — mirrors `modules/decisions/
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

import { Modal } from "../../components/Modal";
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
  error,
  onCancel,
  onSave,
}: {
  initial?: Strategy;
  /** e.g. "organisation" / a project's own name — shown in the modal title
   * so it's clear which scope a new Strategy is being created in, since
   * this same modal serves both the org-scoped and project-scoped pages. */
  scopeLabel: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StrategyFieldValues) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [priority, setPriority] = useState<StrategyPriority>(initial?.priority ?? "medium");
  const [timeHorizon, setTimeHorizon] = useState<StrategyTimeHorizon>(initial?.time_horizon ?? "medium_term");
  const [changeNote, setChangeNote] = useState("");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof Strategy] as string | undefined) ?? ""]))
  );

  function save() {
    onSave({
      title,
      priority,
      time_horizon: timeHorizon,
      change_note: changeNote,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as StrategyFieldValues);
  }

  const valid = title.trim() !== "" && (fields.objective ?? "").trim() !== "";

  return (
    <Modal title={initial ? `Edit ${initial.title}` : `New Strategy (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Title</span>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Strategy title" />
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
          onChange={(v) => setPriority(v as StrategyPriority)}
          options={Object.entries(STRATEGY_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
        />
        <LabeledSelect
          label="Time horizon"
          value={timeHorizon}
          onChange={(v) => setTimeHorizon(v as StrategyTimeHorizon)}
          options={Object.entries(STRATEGY_TIME_HORIZON_LABEL).map(([value, label]) => ({ value, label }))}
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
