/**
 * Module: modules/context_strategy/OpenQuestionFormModal
 *
 * Create/edit dialog for an Open Question's content fields (docs/plans/
 * module-01-context-and-strategy-plan.md Phase 7.5) — mirrors
 * `PainPointFormModal.tsx`'s exact "shared by create and edit, distinguished
 * by whether `initial` is passed" convention and its own "no create/edit
 * field-set asymmetry" shape (no `change_note` — Open Question has no
 * version table, Phase 5's own scope decision).
 *
 * **No `title` field, unlike every other artefact's own form modal (Decided
 * by: Agent, following the backend's own field shape directly) —
 * `question` itself doubles as this artefact's display title**, the same
 * precedent `GuidingPrincipleFormModal.tsx`'s `name` field already
 * established (source overview §9.2 names "Question" as the primary field).
 *
 * **`owner_id`/`due_date` are handled differently from each other, despite
 * both being nullable "assign later" fields (Decided by: Agent).** `owner_id`
 * is deliberately **not** a field here — §9.4 places "Assign" on the manager
 * tier, not the create/edit content form, the same exclusion
 * `PainPointFieldValues` makes (`OpenQuestionDetailPage.tsx`'s own dedicated
 * `AssigneePicker` assigns it directly instead). `due_date` **is** included
 * here — unlike owner assignment, source overview §9.2 lists "Due/Review
 * Date" as a plain content field alongside question/context/evidence, with
 * no separate manager-tier capability naming it, so it follows
 * `FutureStateFormModal`'s `target_date`-shaped plain-nullable-date-field
 * precedent instead.
 */
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { LabeledSelect } from "../../components/LabeledSelect";
import { OPEN_QUESTION_PRIORITY_LABEL } from "./types";
import type { OpenQuestion, OpenQuestionFieldValues, OpenQuestionPriority } from "./types";

const TEXT_FIELDS: { key: keyof OpenQuestionFieldValues; label: string; rows: number }[] = [
  { key: "question", label: "Question", rows: 2 },
  { key: "context", label: "Context", rows: 3 },
  { key: "evidence", label: "Evidence", rows: 2 },
];

export function OpenQuestionFormModal({
  initial,
  error,
  onCancel,
  onSave,
}: {
  initial?: OpenQuestion;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: OpenQuestionFieldValues) => void;
}) {
  const [priority, setPriority] = useState<OpenQuestionPriority>(initial?.priority ?? "medium");
  const [dueDate, setDueDate] = useState(initial?.due_date ?? "");
  const [fields, setFields] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      TEXT_FIELDS.map((f) => [f.key, (initial?.[f.key as keyof OpenQuestion] as string | undefined) ?? ""])
    )
  );

  function save() {
    onSave({
      priority,
      due_date: dueDate || null,
      ...(Object.fromEntries(TEXT_FIELDS.map((f) => [f.key, fields[f.key] ?? ""])) as Record<string, string>),
    } as OpenQuestionFieldValues);
  }

  const valid = (fields.question ?? "").trim() !== "";

  return (
    <Modal
      title={initial ? "Edit Open Question" : "New Open Question"}
      onClose={onCancel}
      size="lg"
    >
      <div className="stack">
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
          onChange={(v) => setPriority(v as OpenQuestionPriority)}
          options={Object.entries(OPEN_QUESTION_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
        />
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Due / review date (optional)</span>
          <input
            className="input" type="date" value={dueDate}
            onChange={(e) => setDueDate(e.target.value)} aria-label="Due date"
          />
        </label>
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={!valid} onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
