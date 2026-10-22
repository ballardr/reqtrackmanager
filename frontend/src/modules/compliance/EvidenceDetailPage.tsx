/**
 * Module: modules/compliance/EvidenceDetailPage
 *
 * One piece of supporting evidence (§13-§15) as a routed page
 * (`/projects/:projectId/modules/compliance/evidence/:evidenceId`, `module.ts`; the same path
 * `artefactPaths` gives search and the Links panel). Evidence carries file attachments and a Links
 * panel, so it is a page rather than a `SidePanel` (docs/ux-style-guide.md "Pattern: entity detail
 * panel"): header with Edit, Revalidate and Archive, the evidence's fields, §15's append-only
 * revalidation history, its files, and the shared Links, Activity and tags.
 *
 * Fetches its own data. Edit and Revalidate are `Modal` layers (`EvidenceFormModals.tsx`); every
 * mutating control always renders and the backend's compliance-officer check surfaces as a toast.
 * Evidence has no comment thread, so there is no discussion section.
 */
import { FolderOpen } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { FileAsset, Project } from "../../api/types";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { DetailLayout } from "../../components/DetailLayout";
import { FileAttachmentList } from "../../components/FileAttachmentList";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordField } from "../../components/RecordDetailParts";
import { RecordHeader } from "../../components/RecordHeader";
import { RecordTags } from "../../components/RecordTags";
import { ResourcePickerModal } from "../../components/ResourcePickerModal";
import { Spinner } from "../../components/Spinner";
import { useArchiveAction } from "../../components/useConfirmedAction";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import * as complianceApi from "./api";
import { EvidenceFormModal, RevalidateModal } from "./EvidenceFormModals";
import { projectCompliancePath } from "./paths";
import {
  COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL, COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE,
  type ComplianceEvidence, type ComplianceEvidenceRevalidation,
} from "./types";

/** The evidence detail page; reads `projectId` and `evidenceId` from the route. */
export function EvidenceDetailPage() {
  const { projectId, evidenceId } = useParams<{ projectId: string; evidenceId: string }>();
  const { showToast } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [evidence, setEvidence] = useState<ComplianceEvidence | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [revalidations, setRevalidations] = useState<ComplianceEvidenceRevalidation[]>([]);
  const [editing, setEditing] = useState(false);
  const [revalidating, setRevalidating] = useState(false);
  const [showResourcePicker, setShowResourcePicker] = useState(false);

  useLoadOnChange(async () => {
    if (!projectId || !evidenceId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then(setProject).catch(() => setProject(null));
    try {
      const [item, fls, revals] = await Promise.all([
        complianceApi.getEvidence(projectId, evidenceId),
        complianceApi.listEvidenceFiles(projectId, evidenceId),
        complianceApi.listEvidenceRevalidations(projectId, evidenceId),
      ]);
      setEvidence(item);
      setFiles(fls);
      setRevalidations(revals);
    } catch (err) {
      setLoadError(toErrorMessage(err, "This evidence could not be found, or you don't have access to it."));
    }
  }, [projectId, evidenceId]);

  const archive = useArchiveAction({
    noun: "evidence",
    isArchived: evidence?.is_archived ?? false,
    hidden: !evidence,
    archiveBody: "This evidence will be marked no longer applicable. Any approvals it supports may require re-assessment. Nothing is deleted.",
    onToggle: async () => {
      if (!projectId || !evidence) return;
      try {
        setEvidence(await (evidence.is_archived
          ? complianceApi.unarchiveEvidence(projectId, evidence.id)
          : complianceApi.archiveEvidence(projectId, evidence.id)));
        showToast(evidence.is_archived ? "Evidence unarchived." : "Evidence archived.");
      } catch (err) {
        showToast(toErrorMessage(err, "Could not update evidence."), "error");
      }
    },
  });

  if (!projectId || !evidenceId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (evidence === null || project === null) return <Spinner />;

  return (
    <DetailLayout
      activity={<RecordActivity projectId={projectId} artefactType="compliance_evidence" artefactId={evidence.id} refreshToken={recordActivityKey(evidence)} />}
      aside={<ArtefactLinksPanel projectId={projectId} artefactType="compliance_evidence" artefactId={evidence.id} />}
    >
      <RecordHeader
        recordLabel="Evidence"
        title={evidence.title}
        code={evidence.unique_code}
        tags={<RecordTags projectId={projectId} artefactType="compliance_evidence" artefactId={evidence.id} />}
        back={{ to: projectCompliancePath(projectId, "evidence"), label: "← Evidence" }}
        badges={
          <>
            {evidence.is_archived && <Badge tone="muted">Archived</Badge>}
            <Badge tone={COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE[evidence.validity_state]}>
              {COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[evidence.validity_state]}
            </Badge>
          </>
        }
        subtitle={evidence.expiry_date ? `Expires ${evidence.expiry_date}` : undefined}
        onEdit={evidence.is_archived ? undefined : () => setEditing(true)}
        actions={[archive.item]}
        transitions={<button className="btn" onClick={() => setRevalidating(true)}>Revalidate</button>}
      />
      {archive.dialog}
      <div className="stack">
        <DetailCard>
          <p style={{ margin: 0 }}>{evidence.description || <span className="text-muted">No description.</span>}</p>
          {evidence.issuing_organisation && <RecordField label="Issuing organisation" value={evidence.issuing_organisation} />}
          {evidence.issued_date && <RecordField label="Issued" value={evidence.issued_date} />}
          {evidence.notes && <RecordField label="Notes" value={evidence.notes} />}
        </DetailCard>

        {revalidations.length > 0 && (
          <DetailCard heading="Revalidation history">
            <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.85rem" }}>
              {revalidations.map((r) => (
                <li key={r.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                  {new Date(r.revalidated_at).toLocaleDateString()}: {r.previous_expiry_date ?? "no expiry"} → {r.new_expiry_date ?? "no expiry"}
                  {r.justification && ` — ${r.justification}`}
                </li>
              ))}
            </ul>
          </DetailCard>
        )}

        <DetailCard
          heading="Files"
          action={
            <button className="btn" onClick={() => setShowResourcePicker(true)}>
              <FolderOpen /> Link from shared resources
            </button>
          }
        >
          <FileAttachmentList
            files={files}
            onUpload={async (file) => {
              const asset = await complianceApi.uploadEvidenceAttachment(projectId, evidence.id, file);
              setFiles((prev) => [...prev, asset]);
            }}
            onRemove={async (fileId) => {
              await complianceApi.unlinkEvidenceFile(projectId, evidence.id, fileId);
              setFiles((prev) => prev.filter((f) => f.id !== fileId));
            }}
          />
        </DetailCard>
      </div>

      {showResourcePicker && (
        <ResourcePickerModal
          title="Link from shared resources"
          sources={[
            { id: "org-resources", label: "Organisation shared resources", loadFiles: () => api.get<FileAsset[]>(`/api/v1/orgs/${project.organization_id}/resources`) },
          ]}
          onClose={() => setShowResourcePicker(false)}
          onAttach={async (fileIds) => {
            for (const fileId of fileIds) {
              const asset = await complianceApi.linkEvidenceOrgResource(projectId, evidence.id, fileId);
              setFiles((prev) => (prev.some((f) => f.id === asset.id) ? prev : [...prev, asset]));
            }
            setShowResourcePicker(false);
          }}
        />
      )}

      {editing && (
        <EvidenceFormModal
          initial={evidence}
          onCancel={() => setEditing(false)}
          onSave={async (values) => {
            try {
              setEvidence(await complianceApi.updateEvidence(projectId, evidence.id, values));
              showToast("Evidence updated.");
              setEditing(false);
            } catch (err) {
              showToast(toErrorMessage(err, "Could not update evidence."), "error");
            }
          }}
        />
      )}

      {revalidating && (
        <RevalidateModal
          onCancel={() => setRevalidating(false)}
          onSave={async (values) => {
            try {
              setEvidence(await complianceApi.revalidateEvidence(projectId, evidence.id, values));
              setRevalidations(await complianceApi.listEvidenceRevalidations(projectId, evidence.id));
              showToast("Evidence revalidated.");
              setRevalidating(false);
            } catch (err) {
              showToast(toErrorMessage(err, "Could not revalidate evidence."), "error");
            }
          }}
        />
      )}
    </DetailLayout>
  );
}
