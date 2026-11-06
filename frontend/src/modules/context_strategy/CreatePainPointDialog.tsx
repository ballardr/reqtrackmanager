/**
 * Module: modules/context_strategy/CreatePainPointDialog
 *
 * A self-contained "New Pain Point" dialog for another record's Links panel (registered as
 * `TierAModuleDefinition.linkedRecordCreators.pain_point`): it loads the project's Pain Point types, shows the same
 * `PainPointFormModal` the Pain Points list uses, creates the record (with its quick links and tags) and reports its
 * id so the panel can link it. Scoring is left to the Pain Point's own page, since the form offers it only to someone
 * who may score and that check belongs to the list page (**Decided by: Agent**).
 */
import { useEffect, useState } from "react";

import { useLinkedRecordSave } from "../../hooks/useLinkedRecordSave";
import type { LinkedRecordCreatorProps } from "../types";
import { projectPainPointApi } from "./api";
import { PainPointFormModal } from "./PainPointFormModal";
import type { EffectivePainPointType, PainPointFieldValues } from "./types";

/**
 * @param projectId The project the Pain Point is created in.
 * @param onCreated Called with the new Pain Point's id.
 * @param onCancel Called when the dialog is dismissed without creating.
 */
export function CreatePainPointDialog({ projectId, onCreated, onCancel }: LinkedRecordCreatorProps) {
  const { error, save } = useLinkedRecordSave(projectId, "pain_point", "Pain Point", onCreated);
  const [types, setTypes] = useState<EffectivePainPointType[] | null>(null);

  useEffect(() => {
    let live = true;
    projectPainPointApi.listTypes(projectId).then((rows) => { if (live) setTypes(rows); }).catch(() => { if (live) setTypes([]); });
    return () => { live = false; };
  }, [projectId]);

  if (types === null) return null;
  return (
    <PainPointFormModal
      projectId={projectId} types={types} error={error} onCancel={onCancel}
      onSave={(values: PainPointFieldValues, quickLinks, tags) => save(() => projectPainPointApi.create(projectId, values), quickLinks, tags)}
    />
  );
}
