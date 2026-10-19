/**
 * Module: modules/stakeholders/ResearchFindingsPanel
 *
 * Research extras: what an engagement taught the team. A finding has a project-scoped
 * code (FND-001), a title and a description, and links to other records through the one
 * shared `ArtefactLinksPanel` (so it can raise or answer Pain Points, Needs and Open
 * Questions, and take any other link a project allows) in its compact form, leaving out the
 * engagement it already sits in; a link to a finding lands on its card (`#finding-<id>`). A
 * finding is created and edited in a `Modal` (principle 3) and deleted behind a
 * tier-1 confirm; it has no comments or files of its own and is deleted with its
 * engagement, because it can quote participants.
 */
import { RecordCode } from "../../components/RecordCode";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Modal } from "../../components/Modal";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectResearchApi } from "./api";
import { TextAreaField, TextField } from "../../components/FormFields";
import type { ResearchFinding } from "./types";
import { FormActions } from "../../components/FormActions";

/** A finding sits in its engagement's page, so its link list leaves the engagement out (the trace still shows it). */
const HIDE_ENGAGEMENT = ["engagement"] as const;

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
        <FormActions
          error={error}
          onCancel={onCancel}
          onSave={() => onSave({ title: title.trim(), description })}
          saveDisabled={title.trim() === ""}
        />
      </div>
    </Modal>
  );
}

export function ResearchFindingsPanel({
  projectId, engagementId, onChanged,
}: {
  projectId: string;
  engagementId: string;
  /** Called after a finding is added, edited or deleted, so a page's Links panel can refresh. */
  onChanged?: () => void;
}) {
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
      onChanged?.();
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not save the finding."));
    }
  }

  async function remove(finding: ResearchFinding) {
    try {
      await projectResearchApi.deleteFinding(projectId, finding.id);
      showToast("Finding deleted.");
      setRefresh((n) => n + 1);
      onChanged?.();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not delete the finding."), "error");
    }
  }

  // A link to a finding lands on its card: scroll to `#finding-<id>` once the findings have loaded.
  const { hash } = useLocation();
  const loaded = findings !== null;
  useEffect(() => {
    if (loaded && hash.startsWith("#finding-")) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [loaded, hash]);

  if (findings === null) return null;

  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <span className="row" style={{ gap: "0.35rem", alignItems: "center" }}>
        <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Findings</span>
        <button type="button" className="btn btn-sm btn-icon" aria-label="Add finding" title="Add finding" aria-haspopup="dialog" onClick={() => setCreating(true)}>
          <Plus aria-hidden="true" />
        </button>
      </span>
      {findings.length === 0 && <span className="text-muted">No findings recorded for this engagement.</span>}
      {findings.map((f) => (
        <div key={f.id} id={`finding-${f.id}`} className="card stack" style={{ gap: "0.35rem" }} aria-label={`Finding ${f.title}`}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <span className="row" style={{ gap: "0.5rem", alignItems: "baseline" }}>
              <span className="text-muted" style={{ fontSize: "0.85rem" }}><RecordCode code={f.unique_code} /></span>
              <strong>{f.title}</strong>
            </span>
            <span className="row" style={{ gap: "0.35rem" }}>
              <button className="btn btn-sm btn-icon" aria-label={`Edit ${f.title}`} title={`Edit ${f.title}`} onClick={() => { setFormError(null); setEditing(f); }}><Pencil /></button>
              <button className="btn btn-sm btn-icon" aria-label={`Delete ${f.title}`} title={`Delete ${f.title}`} onClick={() => setDeleting(f)}><Trash2 /></button>
            </span>
          </div>
          {f.description && <div style={{ whiteSpace: "pre-wrap" }}>{f.description}</div>}
          <ArtefactLinksPanel projectId={projectId} artefactType="research_finding" artefactId={f.id} compact hideLinkedTypes={HIDE_ENGAGEMENT} />
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
