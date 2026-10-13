/**
 * Module: modules/stakeholders/ResearchPromptsPanel
 *
 * Research extras: an engagement's ordered session prompts (the questions
 * planned for an interview or focus group) with the response notes taken against
 * each. Add a prompt inline, edit its text and notes in a `Modal` (principle 3),
 * reorder with up/down, and delete behind a tier-1 confirm. "Session prompts" is
 * the name used throughout so they are not confused with Open Questions.
 * Response notes can quote participants, so they are removed with the
 * engagement. Every change toasts; the list reloads from the server's order.
 */
import { ArrowDown, ArrowUp, Pencil } from "lucide-react";
import { useEffect, useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Modal } from "../../components/Modal";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectResearchApi } from "./api";
import { TextAreaField } from "./RecordFormFields";
import type { EngagementPrompt } from "./types";

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
        <TextAreaField label="Prompt" rows={2} value={text} onChange={setText} />
        <TextAreaField label="Response notes" rows={5} value={notes} onChange={setNotes} hint="What was said. Notes can name people and are deleted with the engagement." />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={text.trim() === ""} onClick={() => onSave({ prompt: text.trim(), response_notes: notes })}>
            Save
          </button>
        </div>
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

  return (
    <div className="stack" style={{ gap: "0.35rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Session prompts</span>
      {prompts.length === 0 ? (
        <span className="text-muted">No session prompts yet.</span>
      ) : (
        <ol style={{ margin: 0, paddingLeft: "1.25rem" }}>
          {prompts.map((p, index) => (
            <li key={p.id} style={{ marginBottom: "0.35rem" }}>
              <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                <span>{p.prompt}</span>
                <button className="btn" aria-label={`Move ${p.prompt} up`} disabled={index === 0} onClick={() => mutate(() => projectResearchApi.movePrompt(projectId, engagementId, p.id, "up"), "Prompt moved.", "Could not move the prompt.")}>
                  <ArrowUp size={14} />
                </button>
                <button className="btn" aria-label={`Move ${p.prompt} down`} disabled={index === prompts.length - 1} onClick={() => mutate(() => projectResearchApi.movePrompt(projectId, engagementId, p.id, "down"), "Prompt moved.", "Could not move the prompt.")}>
                  <ArrowDown size={14} />
                </button>
                <button className="btn" aria-label={`Edit ${p.prompt}`} onClick={() => setEditing(p)}><Pencil size={14} /></button>
                <button className="btn" aria-label={`Delete ${p.prompt}`} onClick={() => setDeleting(p)}>Delete</button>
              </div>
              {p.response_notes && <div className="text-muted" style={{ whiteSpace: "pre-wrap" }}>{p.response_notes}</div>}
            </li>
          ))}
        </ol>
      )}
      <div className="row" style={{ gap: "0.5rem", alignItems: "flex-end" }}>
        <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
          <span>New session prompt</span>
          <input className="input" value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="New session prompt" />
        </label>
        <button
          className="btn" disabled={draft.trim() === ""}
          onClick={() => {
            const text = draft.trim();
            setDraft("");
            void mutate(() => projectResearchApi.addPrompt(projectId, engagementId, { prompt: text }), "Prompt added.", "Could not add the prompt.");
          }}
        >
          Add prompt
        </button>
      </div>
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
    </div>
  );
}
