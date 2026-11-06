/**
 * Module: components/CreateRequirementDialog
 *
 * A self-contained "New requirement" dialog for another record's Links panel (a core type's entry in
 * `modules/coreLinkedRecordCreators`): the same `RequirementCreateModal` the Requirements page uses, without the
 * follow-up file step (the panel links the new requirement and closes the dialog).
 */
import { useAuth } from "../context/AuthContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { useProjectPeople } from "../hooks/useProjectPeople";
import type { LinkedRecordCreatorProps } from "../modules/types";
import { RequirementCreateModal } from "./RequirementCreateModal";

/**
 * @param projectId The project the requirement is created in.
 * @param onCreated Called with the new requirement's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateRequirementDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { user } = useAuth();
  const roles = useMyProjectRoles(projectId);
  const { orgUsers } = useProjectPeople(projectId);
  if (orgUsers === null) return null;
  const isOrgAdmin = orgUsers.some((u) => u.user_id === user?.id && u.roles.includes("org_admin"));
  const canManageProject = roles.includes("project_manager") || roles.includes("project_administrator") || isOrgAdmin;
  return (
    <RequirementCreateModal
      projectId={projectId} canManageProject={canManageProject} offerAttach={false}
      onCreated={(requirement) => onCreated(requirement.id)} onClose={onCancel}
    />
  );
}
