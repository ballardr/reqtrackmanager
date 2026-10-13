/**
 * Module: modules/stakeholders/ResearchFindingsPanel
 *
 * Research extras: what an engagement taught the team. A finding is a titled
 * description that can itself raise or answer Pain Points, Needs and Open
 * Questions, through the same `EngagementOutcomesPanel` an engagement uses. A
 * finding is created and edited in a `Modal` (principle 3) and deleted behind a
 * tier-1 confirm; it has no comments or files of its own and is deleted with its
 * engagement, because it can quote participants.
 */
import { Pencil } from "lucide-react";
import { useEffect, useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Modal } from "../../components/Modal";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectEngagementApi, projectResearchApi } from "./api";
import { EngagementOutcomesPanel } from "./EngagementOutcomesPanel";
import { TextAreaField, TextField } from "./RecordFormFields";
import type { OutcomeTargetType, ResearchFinding } from "./types";

function FindingFormModal({
  initial, error, onCancel, onSave,
}: {
  initial?: ResearchFinding;
  error: string | null;
  onCancel: () => void;
  onSave: (values: { title: string; description: string }) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  return (
    <Modal title={initial ? `Edit ${initial.title}` : "New finding"} onClose={onCancel} size="lg">
      <div className="stack">
        <TextField label="Title" ariaLabel="Finding title" value={title} onChange={setTitle} hint="One line, e.g. “Technicians skip the checklist when offline”." />
        <TextAreaField label="Description" rows={5} value={description} onChange={setDescription} hint="Findings can quote participants and are deleted with the engagement." />
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={title.trim() === ""} onClick={() => onSave({ title: title.trim(), description })}>
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function ResearchFindingsPanel({ projectId, engagementId }: { projectId: string; engagementId: string }) {
  const { showToast } = useToast();
  const [findings, setFindings] = useState<ResearchFinding[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ResearchFinding | null>(null);
  const [deleting, setDeleting] = useState<ResearchFinding | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    projectResearchApi.listFindings(projectId, engagementId).then((rows) => active && setFindings(rows)).catch(() => active && setFindings([]));
    return () => {
      active = false;
    };
  }, [projectId, engagementId, refresh]);

  async function save(values: { title: string; description: string }) {
    setFormError(null);
    try {
      if (editing) await projectResearchApi.updateFinding(projectId, editing.id, values);
      else await projectResearchApi.addFinding(projectId, engagementId, values);
      showToast(editing ? "Finding updated." : "Finding added.");
      setEditing(null);
      setCreating(false);
      setRefresh((n) => n + 1);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not save the finding."));
    }
  }

  async function remove(finding: ResearchFinding) {
    try {
      await projectResearchApi.deleteFinding(projectId, finding.id);
      showToast("Finding deleted.");
      setRefresh((n) => n + 1);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not delete the finding."), "error");
    }
  }

  if (findings === null) return null;

  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Findings</span>
        <button className="btn" onClick={() => setCreating(true)}>Add finding</button>
      </div>
      {findings.length === 0 && <span className="text-muted">No findings recorded for this engagement.</span>}
      {findings.map((f) => (
        <div key={f.id} className="card stack" style={{ gap: "0.35rem" }} aria-label={`Finding ${f.title}`}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <strong>{f.title}</strong>
            <span className="row" style={{ gap: "0.35rem" }}>
              <button className="btn" aria-label={`Edit ${f.title}`} onClick={() => { setFormError(null); setEditing(f); }}><Pencil size={14} /></button>
              <button className="btn" aria-label={`Delete ${f.title}`} onClick={() => setDeleting(f)}>Delete</button>
            </span>
          </div>
          {f.description && <div style={{ whiteSpace: "pre-wrap" }}>{f.description}</div>}
          <EngagementOutcomesPanel
            heading="This finding raised or answered"
            projectId={projectId}
            holderId={f.id}
            api={projectResearchApi.findingOutcomes}
            loadTargets={(targetType: OutcomeTargetType) => projectEngagementApi.listOutcomeTargets(projectId, targetType)}
          />
        </div>
      ))}
      {(creating || editing) && (
        <FindingFormModal
          initial={editing ?? undefined}
          error={formError}
          onCancel={() => { setCreating(false); setEditing(null); setFormError(null); }}
          onSave={save}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete ${deleting.title}?`}
          message="The finding and its links to Pain Points, Needs and Open Questions are deleted. Those records stay."
          confirmLabel="Delete"
          onConfirm={() => {
            const finding = deleting;
            setDeleting(null);
            void remove(finding);
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
