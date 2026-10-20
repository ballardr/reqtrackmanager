/**
 * Module: modules/context_strategy/FutureStateFormModal
 *
 * Create/edit dialog for a Future State's content fields — mirrors
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

import { FormActions } from "../../components/FormActions";
import { DateField, TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
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
  projectId,
  error,
  onCancel,
  onSave,
}: {
  initial?: FutureState;
  /** e.g. "organisation" / "project" — shown in the modal title so it's
   * clear which scope a new Future State is being created in, since this
   * same modal serves both the org-scoped and project-scoped pages. */
  scopeLabel: string;
  /** The project a new record is created in; with it a create form offers the quick-link field. Omit for the organisation scope. */
  projectId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: FutureStateFieldValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [targetDate, setTargetDate] = useState(initial?.target_date ?? "");
  const [changeNote, setChangeNote] = useState("");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof FutureState] as string | undefined) ?? ""]))
  );

  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);

  function save() {
    onSave({
      title,
      target_date: targetDate.trim() === "" ? null : targetDate,
      change_note: changeNote,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as FutureStateFieldValues, quickLinks, tags);
  }

  const valid = title.trim() !== "" && (fields.desired_state ?? "").trim() !== "";

  return (
    <Modal title={initial ? `Edit ${initial.title}` : `New Future State (${scopeLabel})`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <FormGridFull>
            <TextField helpNotNeeded required label="Title" ariaLabel="Future State title" value={title} onChange={setTitle} />
          </FormGridFull>
          {TEXT_FIELDS.map((f) => (
            <FormGridFull key={f.key}>
              <TextAreaField helpNotNeeded required={f.key === "desired_state"}
                label={f.label} rows={f.rows} value={fields[f.key] ?? ""}
                onChange={(value) => setFields((prev) => ({ ...prev, [f.key]: value }))}
              />
            </FormGridFull>
          ))}
          <DateField helpNotNeeded label="Target date" ariaLabel="Target date" value={targetDate ?? ""} onChange={setTargetDate} />
          {initial && (
            <FormGridFull>
              <TextField helpNotNeeded label="Change note" ariaLabel="Change note" value={changeNote} onChange={setChangeNote} />
            </FormGridFull>
          )}
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="future_state" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="future_state" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
