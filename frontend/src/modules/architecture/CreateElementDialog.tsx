/**
 * Module: modules/architecture/CreateElementDialog
 *
 * A self-contained "New element" dialog for another record's Links panel (registered as
 * `TierAModuleDefinition.linkedRecordCreators.architecture_element`): it loads the project's element types, symbols,
 * elements and the organisation's members, shows the same `ElementFormModal` the Elements list uses and reports the new id.
 */
import { useEffect, useState } from "react";

import { useProjectPeople } from "../../hooks/useProjectPeople";
import type { LinkedRecordCreatorProps } from "../types";
import { projectElementApi, projectSymbolUrl } from "./api";
import { ElementFormModal } from "./ElementFormModal";
import { useArchitectureReference } from "./useArchitectureReference";
import { useCreateElement } from "./useCreateElement";
import type { ArchitectureElement } from "./types";

/**
 * @param projectId The project the element is created in.
 * @param onCreated Called with the new element's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateElementDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const reference = useArchitectureReference(projectId);
  const { project } = useProjectPeople(projectId);
  const form = useCreateElement(projectId, onCreated);
  const [candidates, setCandidates] = useState<ArchitectureElement[] | null>(null);

  useEffect(() => {
    let live = true;
    projectElementApi(projectId).list({ open_only: true })
      .then((list) => { if (live) setCandidates(list); })
      .catch(() => { if (live) setCandidates([]); });
    return () => { live = false; };
  }, [projectId]);

  if (!reference.loaded || project === null || candidates === null) return null;
  return (
    <ElementFormModal
      elementTypes={reference.elementTypes} connectionTypes={reference.connectionTypes} candidates={candidates}
      symbols={reference.symbols} symbolUrl={(id) => projectSymbolUrl(projectId, id)} orgUsers={reference.orgUsers}
      organizationId={project.organization_id} projectId={projectId} error={form.error} onCancel={onCancel} onSave={form.create}
    />
  );
}
