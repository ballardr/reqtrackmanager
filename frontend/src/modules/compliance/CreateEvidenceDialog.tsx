/**
 * Module: modules/compliance/CreateEvidenceDialog
 *
 * A self-contained "Add evidence" dialog for another record's Links panel (registered as
 * `TierAModuleDefinition.linkedRecordCreators.compliance_evidence`): the same `EvidenceFormModal` the Evidence list
 * uses, including files staged at creation, and reports the new id.
 */
import { useLinkedRecordSave } from "../../hooks/useLinkedRecordSave";
import type { LinkedRecordCreatorProps } from "../types";
import * as complianceApi from "./api";
import { EvidenceFormModal } from "./EvidenceFormModals";

/**
 * @param projectId The project the evidence is recorded in.
 * @param onCreated Called with the new evidence's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateEvidenceDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "compliance_evidence", "Evidence", onCreated);
  return (
    <EvidenceFormModal
      projectId={projectId} error={error} onCancel={onCancel}
      onSave={(values, files, quickLinks, tags) => save(async () => {
        const created = await complianceApi.createEvidence(projectId, values);
        for (const file of files) await complianceApi.uploadEvidenceAttachment(projectId, created.id, file);
        return created;
      }, quickLinks, tags)}
    />
  );
}
