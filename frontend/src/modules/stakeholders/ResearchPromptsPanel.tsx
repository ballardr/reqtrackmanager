/**
 * Module: modules/stakeholders/ResearchPromptsPanel
 *
 * Research extras: an engagement's ordered session prompts (the questions
 * planned for an interview or focus group) with the response notes taken against
 * each. Add a prompt from a (+) popover, edit its text and notes in a `Modal` (principle 3),
 * reorder with up/down, and delete behind a tier-1 confirm. "Session prompts" is
 * the name used throughout so they are not confused with Open Questions.
 * Response notes can quote participants, so they are removed with the
 * engagement. Every change toasts; the list reloads from the server's order.
 */
import { ArrowDown, ArrowUp, Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { AddPopoverButton } from "../../components/AddPopoverButton";
import { AlignedRows } from "../../components/AlignedRows";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Modal } from "../../components/Modal";
import { RecordFieldGroup } from "../../components/RecordDetailParts";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectResearchApi } from "./api";
import { TextAreaField, TextField } from "../../components/FormFields";
import type { EngagementPrompt } from "./types";
import { FormActions } from "../../components/FormActions";

function PromptEditModal({
  prompt, onCancel, onSave,
}: {
  prompt: EngagementPrompt;
  onCancel: () => void;
  onSave: (values: { prompt: string; response_notes: string }) => void;
}) {
  const [text, setText] = useState(prompt.prompt);
  const [notes, setNotes] = useState(prompt.response_notes);
  return (
    <Modal title="Edit session prompt" onClose={onCancel} size="lg">
      <div className="stack">
        <TextAreaField helpNotNeeded label="Prompt" rows={2} value={text} onChange={setText} />
        <TextAreaField helpNotNeeded label="Response notes" rows={5} value={notes} onChange={setNotes} hint="What was said. Notes can name people and are deleted with the engagement." />
        <FormActions
          onCancel={onCancel}
          onSave={() => onSave({ prompt: text.trim(), response_notes: notes })}
          saveDisabled={text.trim() === ""}
        />
      </div>
    </Modal>
  );
}

export function ResearchPromptsPanel({ projectId, engagementId }: { projectId: string; engagementId: string }) {
  const { showToast } = useToast();
  const [prompts, setPrompts] = useState<EngagementPrompt[] | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<EngagementPrompt | null>(null);
  const [deleting, setDeleting] = useState<EngagementPrompt | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    projectResearchApi.listPrompts(projectId, engagementId).then((rows) => active && setPrompts(rows)).catch(() => active && setPrompts([]));
    return () => {
      active = false;
    };
  }, [projectId, engagementId, refresh]);

  async function mutate(action: () => Promise<unknown>, success: string, failure: string) {
    try {
      await action();
      showToast(success);
      setRefresh((n) => n + 1);
    } catch (err) {
      showToast(toErrorMessage(err, failure), "error");
    }
  }

  if (prompts === null) return null;

  const addForm = (close: () => void) => (
    <div className="stack">
      <TextField helpNotNeeded label="New session prompt" value={draft} onChange={setDraft} inputProps={{ autoFocus: true }} />
      <FormActions
        onCancel={close}
        onSave={() => {
          const text = draft.trim();
          setDraft("");
          close();
          void mutate(() => projectResearchApi.addPrompt(projectId, engagementId, { prompt: text }), "Prompt added.", "Could not add the prompt.");
        }}
        saveLabel="Add prompt"
        saveDisabled={draft.trim() === ""}
      />
    </div>
  );

  return (
    <RecordFieldGroup helpNotNeeded label="Session prompts" gap="0.35rem" action={<AddPopoverButton label="Add to Session prompts">{addForm}</AddPopoverButton>}>
      {prompts.length === 0 ? (
        <span className="text-muted">No session prompts yet.</span>
      ) : (
        <AlignedRows
          ordered
          ariaLabel="Session prompts"
          rows={prompts.map((p, index) => ({
            id: p.id,
            lead: <span className="text-muted">{index + 1}.</span>,
            main: p.prompt,
            actions: (
              <>
                <button className="btn btn-sm btn-icon" aria-label={`Move ${p.prompt} up`} title={`Move ${p.prompt} up`} disabled={index === 0} onClick={() => mutate(() => projectResearchApi.movePrompt(projectId, engagementId, p.id, "up"), "Prompt moved.", "Could not move the prompt.")}>
                  <ArrowUp />
                </button>
                <button className="btn btn-sm btn-icon" aria-label={`Move ${p.prompt} down`} title={`Move ${p.prompt} down`} disabled={index === prompts.length - 1} onClick={() => mutate(() => projectResearchApi.movePrompt(projectId, engagementId, p.id, "down"), "Prompt moved.", "Could not move the prompt.")}>
                  <ArrowDown />
                </button>
                <button className="btn btn-sm btn-icon" aria-label={`Edit ${p.prompt}`} title={`Edit ${p.prompt}`} onClick={() => setEditing(p)}><Pencil /></button>
                <button className="btn btn-sm btn-icon" aria-label={`Delete ${p.prompt}`} title={`Delete ${p.prompt}`} onClick={() => setDeleting(p)}><Trash2 /></button>
              </>
            ),
            detail: p.response_notes ? <span style={{ whiteSpace: "pre-wrap" }}>{p.response_notes}</span> : undefined,
          }))}
        />
      )}
      {editing && (
        <PromptEditModal
          prompt={editing}
          onCancel={() => setEditing(null)}
          onSave={(values) => {
            const prompt = editing;
            setEditing(null);
            void mutate(() => projectResearchApi.updatePrompt(projectId, engagementId, prompt.id, values), "Prompt updated.", "Could not update the prompt.");
          }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete this session prompt?"
          message="The prompt and the response notes taken against it are deleted."
          confirmLabel="Delete"
          onConfirm={() => {
            const prompt = deleting;
            setDeleting(null);
            void mutate(() => projectResearchApi.deletePrompt(projectId, engagementId, prompt.id), "Prompt deleted.", "Could not delete the prompt.");
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </RecordFieldGroup>
  );
}
