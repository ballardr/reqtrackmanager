/**
 * Module: modules/compliance/EvidencePanel
 *
 * The project's supporting-evidence library (§13-§15) — project-scoped, not
 * nested under one standard assignment, since a single piece of evidence
 * may support requirements across more than one of a project's standard
 * assignments at once (§13's "multiple compliance requirements and/or
 * standards"; `project_router.py`'s own Phase 8 design). A `DirectoryTable`
 * + `FilterPanel` list (style guide "Pattern: directories at scale"), a
 * `Modal` create flow (Principle 3), and a `SidePanel` detail view (edit
 * metadata, revalidate — §15's append-only history — archive/unarchive,
 * and file attachments reusing `FileAttachmentList`/`ResourcePickerModal`
 * exactly as `RequirementDetailPage.tsx`'s own Attachments card does, per
 * §13's "reuse ReqTrackManager's existing attachment/file mechanisms").
 *
 * Linking evidence to a specific requirement/required-action assessment is
 * done from the requirement side (`RequirementAssessmentPanel`'s own
 * "Link existing evidence" control) — this panel is the canonical evidence
 * CRUD surface, not a second place to manage linkage.
 */
import { FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";

import type { FileAsset } from "../../api/types";
import { COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL } from "../../api/types";
import { api } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { Modal } from "../../components/Modal";
import { ResourcePickerModal } from "../../components/ResourcePickerModal";
import { SidePanel } from "../../components/SidePanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceEvidence, ComplianceEvidenceRevalidation } from "./types";

export function EvidencePanel({ projectId, orgId }: { projectId: string; orgId: string }) {
  const { showToast } = useToast();
  const [evidence, setEvidence] = useState<ComplianceEvidence[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<ComplianceEvidence | null>(null);
  const [editing, setEditing] = useState(false);
  const [revalidating, setRevalidating] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<ComplianceEvidence | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [revalidations, setRevalidations] = useState<ComplianceEvidenceRevalidation[]>([]);
  const [showResourcePicker, setShowResourcePicker] = useState(false);

  async function reload() {
    try {
      setEvidence(await complianceApi.listEvidence(projectId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load evidence."));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function openEvidence(item: ComplianceEvidence) {
    setSelected(item);
    try {
      const [fls, revals] = await Promise.all([
        complianceApi.listEvidenceFiles(projectId, item.id),
        complianceApi.listEvidenceRevalidations(projectId, item.id),
      ]);
      setFiles(fls);
      setRevalidations(revals);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load evidence detail."), "error");
    }
  }

  async function handleArchiveToggle() {
    if (!archiveTarget) return;
    try {
      const updated = archiveTarget.is_archived
        ? await complianceApi.unarchiveEvidence(projectId, archiveTarget.id)
        : await complianceApi.archiveEvidence(projectId, archiveTarget.id);
      showToast(archiveTarget.is_archived ? "Evidence unarchived." : "Evidence archived.");
      setArchiveTarget(null);
      setSelected(updated);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update evidence."), "error");
    }
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (evidence === null) return <Spinner />;

  const filtered = evidence
    .filter((e) => includeArchived || !e.is_archived)
    .filter((e) => !search || e.title.toLowerCase().includes(search.toLowerCase()));

  const columns: DirectoryColumn<ComplianceEvidence>[] = [
    { key: "title", label: "Title", render: (e) => e.title },
    { key: "issuing_organisation", label: "Issuing organisation", render: (e) => e.issuing_organisation ?? "—" },
    { key: "expiry_date", label: "Expiry", render: (e) => e.expiry_date ?? "—" },
    { key: "validity", label: "Validity", render: (e) => COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[e.validity_state] },
    { key: "status", label: "Status", render: (e) => (e.is_archived ? "Archived" : "Active") },
  ];

  return (
    <div className="stack">
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        Add evidence
      </button>
      <div className="side-grid">
        <FilterPanel
          sectionKey="compliance.evidence" total={evidence.length} matching={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search evidence…" searchAriaLabel="Search evidence"
        >
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
        <DirectoryTable
          ariaLabel="Compliance evidence"
          columns={columns}
          rows={filtered}
          rowKey={(e) => e.id}
          onRowClick={openEvidence}
          emptyState={<p className="text-muted">No evidence recorded for this project yet.</p>}
        />
      </div>

      {creating && (
        <EvidenceFormModal
          onCancel={() => setCreating(false)}
          onSave={async (values) => {
            try {
              await complianceApi.createEvidence(projectId, values);
              showToast("Evidence created.");
              setCreating(false);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not create evidence."), "error");
            }
          }}
        />
      )}

      {selected && (
        <SidePanel title={selected.title} onClose={() => setSelected(null)}>
          <div className="stack">
            <p>{selected.description || <span className="text-muted">No description.</span>}</p>
            <p className="text-muted" style={{ margin: 0 }}>
              Validity: {COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[selected.validity_state]}
              {selected.expiry_date && ` — expires ${selected.expiry_date}`}
            </p>
            <div className="row">
              <button className="btn" onClick={() => setEditing(true)}>Edit</button>
              <button className="btn" onClick={() => setRevalidating(true)}>Revalidate</button>
              <button className="btn btn-danger" onClick={() => setArchiveTarget(selected)}>
                {selected.is_archived ? "Unarchive" : "Archive"}
              </button>
            </div>

            {revalidations.length > 0 && (
              <>
                <h3 style={{ margin: "0.5rem 0 0" }}>Revalidation history</h3>
                <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.85rem" }}>
                  {revalidations.map((r) => (
                    <li key={r.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                      {new Date(r.revalidated_at).toLocaleDateString()}: {r.previous_expiry_date ?? "no expiry"} → {r.new_expiry_date ?? "no expiry"}
                      {r.justification && ` — ${r.justification}`}
                    </li>
                  ))}
                </ul>
              </>
            )}

            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3 style={{ margin: 0 }}>Files</h3>
              <button className="btn" onClick={() => setShowResourcePicker(true)}>
                <FolderOpen size={14} /> Link from shared resources
              </button>
            </div>
            <FileAttachmentList
              files={files}
              onUpload={async (file) => {
                const asset = await complianceApi.uploadEvidenceAttachment(projectId, selected.id, file);
                setFiles((prev) => [...prev, asset]);
              }}
              onRemove={async (fileId) => {
                await complianceApi.unlinkEvidenceFile(projectId, selected.id, fileId);
                setFiles((prev) => prev.filter((f) => f.id !== fileId));
              }}
            />
          </div>
        </SidePanel>
      )}

      {showResourcePicker && selected && (
        <ResourcePickerModal
          title="Link from shared resources"
          sources={[
            { id: "org-resources", label: "Organisation shared resources", loadFiles: () => api.get<FileAsset[]>(`/api/v1/orgs/${orgId}/resources`) },
          ]}
          onClose={() => setShowResourcePicker(false)}
          onAttach={async (fileIds) => {
            for (const fileId of fileIds) {
              const asset = await complianceApi.linkEvidenceOrgResource(projectId, selected.id, fileId);
              setFiles((prev) => (prev.some((f) => f.id === asset.id) ? prev : [...prev, asset]));
            }
            setShowResourcePicker(false);
          }}
        />
      )}

      {editing && selected && (
        <EvidenceFormModal
          initial={selected}
          onCancel={() => setEditing(false)}
          onSave={async (values) => {
            try {
              const updated = await complianceApi.updateEvidence(projectId, selected.id, values);
              showToast("Evidence updated.");
              setEditing(false);
              setSelected(updated);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not update evidence."), "error");
            }
          }}
        />
      )}

      {revalidating && selected && (
        <RevalidateModal
          onCancel={() => setRevalidating(false)}
          onSave={async (values) => {
            try {
              const updated = await complianceApi.revalidateEvidence(projectId, selected.id, values);
              showToast("Evidence revalidated.");
              setRevalidating(false);
              await openEvidence(updated);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not revalidate evidence."), "error");
            }
          }}
        />
      )}

      {archiveTarget && (
        <ConfirmDialog
          title={archiveTarget.is_archived ? `Unarchive "${archiveTarget.title}"?` : `Archive "${archiveTarget.title}"?`}
          message={
            archiveTarget.is_archived
              ? "This evidence will count as applicable again."
              : "This evidence will be marked no longer applicable. Any approvals it supports may require re-assessment. Nothing is deleted."
          }
          confirmLabel={archiveTarget.is_archived ? "Unarchive" : "Archive"}
          onConfirm={handleArchiveToggle}
          onCancel={() => setArchiveTarget(null)}
        />
      )}
    </div>
  );
}

function EvidenceFormModal({
  initial,
  onCancel,
  onSave,
}: {
  initial?: ComplianceEvidence;
  onCancel: () => void;
  onSave: (values: {
    title: string; description: string; issuing_organisation: string | null; issued_date: string | null;
    expiry_date?: string | null; notes: string;
  }) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [issuingOrganisation, setIssuingOrganisation] = useState(initial?.issuing_organisation ?? "");
  const [issuedDate, setIssuedDate] = useState(initial?.issued_date ?? "");
  const [expiryDate, setExpiryDate] = useState(initial?.expiry_date ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");

  return (
    <Modal title={initial ? "Edit evidence" : "Add evidence"} onClose={onCancel}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Title</span>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Evidence title" />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Description</span>
          <textarea className="input" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Issuing organisation</span>
          <input className="input" value={issuingOrganisation} onChange={(e) => setIssuingOrganisation(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Issued date</span>
          <input className="input" type="date" value={issuedDate} onChange={(e) => setIssuedDate(e.target.value)} />
        </label>
        {!initial && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Expiry date (optional — change later via Revalidate)</span>
            <input className="input" type="date" value={expiryDate} onChange={(e) => setExpiryDate(e.target.value)} />
          </label>
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Notes</span>
          <textarea className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary" disabled={!title.trim()}
            onClick={() =>
              onSave({
                title, description, issuing_organisation: issuingOrganisation || null,
                issued_date: issuedDate || null, expiry_date: initial ? undefined : (expiryDate || null), notes,
              })
            }
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}

function RevalidateModal({
  onCancel,
  onSave,
}: {
  onCancel: () => void;
  onSave: (values: { new_expiry_date: string | null; justification: string }) => void;
}) {
  const [newExpiryDate, setNewExpiryDate] = useState("");
  const [justification, setJustification] = useState("");

  return (
    <Modal title="Revalidate evidence" onClose={onCancel}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>New expiry date (optional)</span>
          <input className="input" type="date" value={newExpiryDate} onChange={(e) => setNewExpiryDate(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Justification</span>
          <textarea className="input" rows={2} value={justification} onChange={(e) => setJustification(e.target.value)} />
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" onClick={() => onSave({ new_expiry_date: newExpiryDate || null, justification })}>
            Revalidate
          </button>
        </div>
      </div>
    </Modal>
  );
}
