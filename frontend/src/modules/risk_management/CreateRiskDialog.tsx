/**
 * Module: modules/risk_management/CreateRiskDialog
 *
 * A self-contained "New risk" dialog for another record's Links panel (registered as
 * `TierAModuleDefinition.linkedRecordCreators.risk`): it loads the project's enabled Risk Types, scoring scheme and
 * the organisation's members, shows the same `RiskFormModal` the Risks register uses and reports the new id.
 */
import { useEffect, useState } from "react";

import { useAuth } from "../../context/AuthContext";
import { useLinkedRecordSave } from "../../hooks/useLinkedRecordSave";
import { useProjectPeople } from "../../hooks/useProjectPeople";
import type { LinkedRecordCreatorProps } from "../types";
import { riskApi } from "./api";
import { RiskFormModal } from "./RiskFormModal";
import { useRiskScheme } from "./useRiskScheme";

/**
 * @param projectId The project the risk is created in.
 * @param onCreated Called with the new risk's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateRiskDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { user } = useAuth();
  const { error, save } = useLinkedRecordSave(projectId, "risk", "Risk", onCreated);
  const scheme = useRiskScheme(projectId);
  const { project, orgUsers } = useProjectPeople(projectId);
  const [riskTypes, setRiskTypes] = useState<{ id: string; name: string }[] | null>(null);

  useEffect(() => {
    let live = true;
    riskApi.listTypes(projectId)
      .then((types) => { if (live) setRiskTypes(types.filter((t) => t.is_enabled).map((t) => ({ id: t.id, name: t.name }))); })
      .catch(() => { if (live) setRiskTypes([]); });
    return () => { live = false; };
  }, [projectId]);

  if (riskTypes === null || project === null || orgUsers === null) return null;
  return (
    <RiskFormModal
      scheme={scheme} riskTypes={riskTypes} orgUsers={orgUsers} organizationId={project.organization_id}
      projectId={projectId} currentUserId={user?.id} error={error} onCancel={onCancel}
      onSave={(values, _changeNote, quickLinks, tags) => save(() => riskApi.create(projectId, values), quickLinks, tags)}
    />
  );
}
