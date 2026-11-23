/**
 * Module: modules/context_strategy/OpenQuestionFormModal
 *
 * Create/edit dialog for an Open Question's content fields. Shared by create and edit (edit when `initial` is passed),
 * as `PainPointFormModal.tsx` is, with the same field set in both modes (no `change_note`: no version table).
 *
 * There is no `title` field: `question` is the display title, as `name` is for `GuidingPrincipleFormModal.tsx`.
 *
 * `owner` is not a field: assignment is a manager-tier action, as in `PainPointFieldValues`, done through
 * `OpenQuestionDetailPage.tsx`'s `RecordPrincipalField`. `due_date` is a field: it is plain content with no
 * manager-tier capability of its own, a nullable date like `FutureStateFormModal`'s `target_date`.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { FormActions } from "../../components/FormActions";
import { DateField, TextAreaField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { OPEN_QUESTION_PRIORITY_LABEL } from "./types";
import type { OpenQuestion, OpenQuestionFieldValues, OpenQuestionPriority } from "./types";
import { CONTEXT_STRATEGY_HELP } from "./help";

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
  onSave: (values: OpenQuestionFieldValues, quickLinks: CollectedLink[], tags: string[]) => void;
}) {
  const [priority, setPriority] = useState<OpenQuestionPriority>(initial?.priority ?? "medium");
  const [dueDate, setDueDate] = useState(initial?.due_date ?? "");
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
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
    } as OpenQuestionFieldValues, quickLinks, tags);
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
              <TextAreaField markdown="math" helpNotNeeded required={f.key === "question"}
                label={f.label} rows={f.rows} value={fields[f.key] ?? ""}
                onChange={(value) => setFields((prev) => ({ ...prev, [f.key]: value }))}
              />
            </FormGridFull>
          ))}
          <LabeledSelect help={CONTEXT_STRATEGY_HELP.priority}
            label="Priority"
            value={priority}
            onChange={(v) => setPriority(v as OpenQuestionPriority)}
            options={Object.entries(OPEN_QUESTION_PRIORITY_LABEL).map(([value, label]) => ({ value, label }))}
          />
          <DateField help={CONTEXT_STRATEGY_HELP.openQuestionDueDate} label="Due / review date" ariaLabel="Due date" value={dueDate} onChange={setDueDate} />
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField
                projectId={projectId} artefactType="open_question" value={quickLinks} onChange={setQuickLinks}
              />
                <TagField projectId={projectId} artefactType="open_question" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={save} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
