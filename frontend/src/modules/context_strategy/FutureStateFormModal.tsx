/**
 * Module: modules/context_strategy/FutureStateFormModal
 *
 * Create/edit dialog for a Future State's content fields (docs/plans/
 * module-01-context-and-strategy-plan.md Phase 7.2) — mirrors
 * `StrategyFormModal.tsx`'s exact "shared by create and edit, distinguished
 * by whether `initial` is passed" / create-as-a-layer shape, adapted to
 * Future State's own field list: no `priority`/`time_horizon` (Future State
 * has neither — see `types.ts`'s own docstring), and one field Strategy
 * doesn't have, `target_date`.
 *
 * **`target_date` handling, Decided by: Agent.** A plain HTML
 * `<input type="date">`: typing a date sends that ISO string, clearing the
 * field back to empty sends `null`. No client-side "explicitly set" flag is
 * needed (see `api.ts`'s own docstring on `buildFutureStateApi`) — the `PUT`
 * endpoint is a full-replace payload where `target_date` is always present
 * (a real date string or `null`), and the backend always treats a `PUT` as
 * an explicit set/clear of every field it carries.
 */
import { useState } from "react";

import { Modal } from "../../components/Modal";
import type { FutureState, FutureStateFieldValues } from "./types";

const TEXT_FIELDS: { key: keyof FutureStateFieldValues; label: string; rows: number }[] = [
  { key: "current_state", label: "Current state", rows: 2 },
  { key: "desired_state", label: "Desired state", rows: 2 },
  { key: "outcomes", label: "Outcomes", rows: 2 },
  { key: "success_measures", label: "Success measures", rows: 2 },
  { key: "constraints", label: "Constraints", rows: 2 },
  { key: "assumptions", label: "Assumptions", rows: 2 },
];

export function FutureStateFormModal({
  initial,
  scopeLabel,
  error,
  onCancel,
  onSave,
}: {
  initial?: FutureState;
  /** e.g. "organisation" / "project" — shown in the modal title so it's
   * clear which scope a new Future State is being created in, since this
   * same modal serves both the org-scoped and project-scoped pages. */
  scopeLabel: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: FutureStateFieldValues) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [targetDate, setTargetDate] = useState(initial?.target_date ?? "");
  const [changeNote, setChangeNote] = useState("");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof FutureState] as string | undefined) ?? ""]))
  );

  function save() {
    onSave({
      title,
      target_date: targetDate.trim() === "" ? null : targetDate,
      change_note: changeNote,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as FutureStateFieldValues);
  }

  const valid = title.trim() !== "" && (fields.desired_state ?? "").trim() !== "";

  return (
    <Modal title={initial ? `Edit ${initial.title}` : `New Future State (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Title</span>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Future State title" />
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
          <span>Target date (optional)</span>
          <input
            type="date"
            className="input"
            value={targetDate ?? ""}
            onChange={(e) => setTargetDate(e.target.value)}
            aria-label="Target date"
          />
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
