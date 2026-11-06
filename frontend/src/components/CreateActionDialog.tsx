/**
 * Module: components/CreateActionDialog
 *
 * A self-contained "New action" dialog for another record's Links panel (a core type's entry in
 * `modules/coreLinkedRecordCreators`): it loads the project's action types and the organisation's members, shows the
 * same `ActionFormModal` the Actions page uses and reports the new action's id.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ActionTypeDefinition, RequirementAction } from "../api/types";
import { useLinkedRecordSave } from "../hooks/useLinkedRecordSave";
import { useProjectPeople } from "../hooks/useProjectPeople";
import type { LinkedRecordCreatorProps } from "../modules/types";
import { ActionFormModal } from "./ActionFormModal";

/**
 * @param projectId The project the action is created in.
 * @param onCreated Called with the new action's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateActionDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "requirement_action", "Action", onCreated);
  const { project, orgUsers } = useProjectPeople(projectId);
  const [types, setTypes] = useState<ActionTypeDefinition[] | null>(null);

  useEffect(() => {
    let live = true;
    api.get<ActionTypeDefinition[]>(`/api/v1/projects/${projectId}/action-types`)
      .then((rows) => { if (live) setTypes(rows); })
      .catch(() => { if (live) setTypes([]); });
    return () => { live = false; };
  }, [projectId]);

  if (types === null || orgUsers === null) return null;
  return (
    <ActionFormModal
      projectId={projectId} actionTypes={types} orgUsers={orgUsers} organizationId={project?.organization_id}
      error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(
        () => api.post<RequirementAction>(`/api/v1/projects/${projectId}/actions`, values), quickLinks, tags,
      )}
    />
  );
}
