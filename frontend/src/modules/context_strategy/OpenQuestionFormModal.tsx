/**
 * Module: modules/context_strategy/OpenQuestionFormModal
 *
 * Create/edit dialog for an Open Question's content fields — mirrors
 * `PainPointFormModal.tsx`'s exact "shared by create and edit, distinguished
 * by whether `initial` is passed" convention and its own "no create/edit
 * field-set asymmetry" shape (no `change_note` — Open Question has no
 * version table).
 *
 * **No `title` field, unlike every other artefact's own form modal (Decided
 * by: Agent, following the backend's own field shape directly) —
 * `question` itself doubles as this artefact's display title**, the same
 * precedent `GuidingPrincipleFormModal.tsx`'s `name` field already
 * established (§9.2 names "Question" as the primary field).
 *
 * **`owner`/`due_date` are handled differently from each other, despite
 * both being nullable "assign later" fields (Decided by: Agent).** `owner`
 * is deliberately **not** a field here — §9.4 places "Assign" on the manager
 * tier, not the create/edit content form, the same exclusion
 * `PainPointFieldValues` makes (`OpenQuestionDetailPage.tsx`'s own dedicated
 * `RecordPrincipalField` assigns it directly instead). `due_date` **is** included
 * here — unlike owner assignment, §9.2 lists "Due/Review
 * Date" as a plain content field alongside question/context/evidence, with
 * no separate manager-tier capability naming it, so it follows
 * `FutureStateFormModal`'s `target_date`-shaped plain-nullable-date-field
 * precedent instead.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { FormActions } from "../../components/FormActions";
import { DateField, TextAreaField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
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
  projectId,
  error,
  onCancel,
  onSave,
}: {
  initial?: OpenQuestion;
  /** The project the Open Question is created in; with it a create form offers the quick-link field. */
  projectId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: OpenQuestionFieldValues, quickLinks: CollectedLink[]) => void;
}) {
  const [priority, setPriority] = useState<OpenQuestionPriority>(initial?.priority ?? "medium");
  const [dueDate, setDueDate] = useState(initial?.due_date ?? "");
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
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
    } as OpenQuestionFieldValues, quickLinks);
  }

  const valid = (fields.question ?? "").trim() !== "";

  return (
    <Modal
      title={initial ? "Edit Open Question" : "New Open Question"}
      onClose={onCancel}
      size="lg"
    >
      <div className="stack">
        <FormGrid minColumn="18rem">
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
            onChange={(v) => setPriority(v as OpenQuestionPriority)}
            options={Object.entries(OPEN_QUESTION_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
          />
          <DateField label="Due / review date (optional)" ariaLabel="Due date" value={dueDate} onChange={setDueDate} />
          {!initial && projectId && (
            <FormGridFull>
              <QuickLinkField
                projectId={projectId} artefactType="open_question" value={quickLinks} onChange={setQuickLinks}
              />
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
