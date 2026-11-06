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

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
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
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId, "pain_point");
  const commitTags = useCommitTags(projectId, "pain_point");
  const [types, setTypes] = useState<EffectivePainPointType[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    projectPainPointApi.listTypes(projectId).then((rows) => { if (live) setTypes(rows); }).catch(() => { if (live) setTypes([]); });
    return () => { live = false; };
  }, [projectId]);

  if (types === null) return null;
  return (
    <PainPointFormModal
      projectId={projectId} types={types} error={error} onCancel={onCancel}
      onSave={async (values: PainPointFieldValues, quickLinks, tags) => {
        setError(null);
        try {
          const created = await projectPainPointApi.create(projectId, values);
          showToast("Pain Point created.");
          await commitQuickLinks(created.id, quickLinks);
          await commitTags(created.id, tags);
          onCreated(created.id);
        } catch (err) {
          setError(toErrorMessage(err, "Could not create Pain Point."));
        }
      }}
    />
  );
}
