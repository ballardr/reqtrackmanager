/**
 * Module: modules/architecture/CreateDiagramDialog
 *
 * A self-contained "New diagram" dialog for another record's Links panel (registered as
 * `TierAModuleDefinition.linkedRecordCreators.architecture_diagram`): it loads the project's elements, shows the same
 * `DiagramFormModal` the Diagrams list uses and reports the new id.
 */
import { useEffect, useState } from "react";

import type { LinkedRecordCreatorProps } from "../types";
import { projectElementApi } from "./api";
import { DiagramFormModal } from "./DiagramFormModal";
import { useCreateDiagram } from "./useCreateDiagram";
import type { ArchitectureElement } from "./types";

/**
 * @param projectId The project the diagram is created in.
 * @param onCreated Called with the new diagram's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreateDiagramDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const form = useCreateDiagram(projectId, onCreated);
  const [elements, setElements] = useState<ArchitectureElement[] | null>(null);

  useEffect(() => {
    let live = true;
    projectElementApi(projectId).list({ open_only: true })
      .then((list) => { if (live) setElements(list); })
      .catch(() => { if (live) setElements([]); });
    return () => { live = false; };
  }, [projectId]);

  if (elements === null) return null;
  return <DiagramFormModal elements={elements} projectId={projectId} error={form.error} onCancel={onCancel} onSave={form.create} />;
}
