/**
 * Module: components/CreateChangeRequestDialog
 *
 * A self-contained "New change request" dialog for another record's Links panel (a core type's entry in
 * `modules/coreLinkedRecordCreators`): the same `ChangeRequestCreateModal` the Change requests page uses. When the page
 * record is a requirement, it is pre-selected as the requirement to change (it stays editable), because a finding or an
 * enhancement request is often a change to an existing requirement.
 */
import type { LinkedRecordCreatorProps } from "../modules/types";
import { ChangeRequestCreateModal } from "./ChangeRequestCreateModal";

/**
 * @param projectId The project the request is made in.
 * @param pageRecord The record whose Links panel opened the dialog.
 * @param onCreated Called with the new request's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateChangeRequestDialog({ projectId, pageRecord, onCreated, onCancel }: LinkedRecordCreatorProps) {
  return (
    <ChangeRequestCreateModal
      projectId={projectId} defaultRequirementId={pageRecord.type === "requirement" ? pageRecord.id : undefined}
      onCreated={onCreated} onClose={onCancel}
    />
  );
}
