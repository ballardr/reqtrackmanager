/**
 * Module: modules/product_feedback/CreateRequestDialog
 *
 * A self-contained "New request" dialog for another record's Links panel (registered as
 * `TierAModuleDefinition.linkedRecordCreators.enhancement_request`): it loads the project's scoring scheme and the
 * organisation's members, shows the same `RequestFormModal` the Enhancement requests list uses and reports the new id.
 * The server's `can_create` flag already hides it from a person the project's submission policy does not allow.
 */
import { useEffect, useState } from "react";

import { projectScoringApi, type ScoringScheme } from "../../api/scoring";
import { useLinkedRecordSave } from "../../hooks/useLinkedRecordSave";
import { useProjectPeople } from "../../hooks/useProjectPeople";
import type { LinkedRecordCreatorProps } from "../types";
import { projectRequestApi } from "./api";
import { RequestFormModal } from "./RequestFormModal";

/**
 * @param projectId The project the request is submitted to.
 * @param onCreated Called with the new request's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateRequestDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "enhancement_request", "Request", onCreated);
  const { project, orgUsers } = useProjectPeople(projectId);
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);

  useEffect(() => {
    let live = true;
    // Scoring is secondary to the form: a failure leaves the score pickers out.
    projectScoringApi.get(projectId, "enhancement_request").then((s) => { if (live) setScheme(s); }).catch(() => { if (live) setScheme(null); });
    return () => { live = false; };
  }, [projectId]);

  if (project === null || orgUsers === null) return null;
  return (
    <RequestFormModal
      scopeLabel="project" scheme={scheme} orgUsers={orgUsers} organizationId={project.organization_id} projectId={projectId}
      error={error} onCancel={onCancel}
      onSave={(values, quickLinks, tags) => save(() => projectRequestApi.create(projectId, values), quickLinks, tags)}
    />
  );
}
