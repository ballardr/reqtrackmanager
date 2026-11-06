/**
 * Module: modules/decisions/CreateDecisionDialog
 *
 * A self-contained "New decision" dialog for another record's Links panel (registered as
 * `TierAModuleDefinition.linkedRecordCreators.decision`): it loads the project's Decision Types, the organisation's
 * templates and members, shows the same `DecisionFormModal` the Decisions list uses and reports the new id.
 */
import { useEffect, useState } from "react";

import { useAuth } from "../../context/AuthContext";
import { useLinkedRecordSave } from "../../hooks/useLinkedRecordSave";
import { useProjectPeople } from "../../hooks/useProjectPeople";
import type { LinkedRecordCreatorProps } from "../types";
import { createDecision, listDecisionTemplates, listDecisionTypes } from "./api";
import { DecisionFormModal } from "./DecisionFormModal";
import type { DecisionTemplate, DecisionTypeDefinition } from "./types";

/**
 * @param projectId The project the Decision is created in.
 * @param onCreated Called with the new Decision's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateDecisionDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { user } = useAuth();
  const { error, save } = useLinkedRecordSave(projectId, "decision", "Decision", onCreated);
  const { project, orgUsers } = useProjectPeople(projectId);
  const [types, setTypes] = useState<DecisionTypeDefinition[] | null>(null);
  const [templates, setTemplates] = useState<DecisionTemplate[]>([]);

  useEffect(() => {
    let live = true;
    listDecisionTypes(projectId).then((rows) => { if (live) setTypes(rows); }).catch(() => { if (live) setTypes([]); });
    return () => { live = false; };
  }, [projectId]);
  useEffect(() => {
    if (!project) return;
    let live = true;
    listDecisionTemplates(project.organization_id).then((rows) => { if (live) setTemplates(rows); }).catch(() => { if (live) setTemplates([]); });
    return () => { live = false; };
  }, [project]);

  if (types === null || project === null || orgUsers === null) return null;
  return (
    <DecisionFormModal
      decisionTypes={types} templates={templates} orgUsers={orgUsers} organizationId={project.organization_id}
      projectId={projectId} currentUserId={user?.id} error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => createDecision(projectId, values), quickLinks, tags)}
    />
  );
}
