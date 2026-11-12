/**
 * Module: modules/architecture/useCreateDiagram
 *
 * The create step the Diagrams list and the Links panel share: create the diagram (already active for "Save and
 * activate", with the scope's elements placed when asked), apply the quick links and tags its form collected, and keep the
 * form open with the message when the server refuses.
 */
import { useCallback, useState } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { projectDiagramApi } from "./api";
import type { DiagramCreateExtras } from "./DiagramFormModal";
import type { DiagramFieldValues } from "./types";

/**
 * @param projectId The project the diagram is created in.
 * @param onCreated Called with the new diagram's id once it and its links and tags exist.
 * @returns `error` (the last refusal, or null), `clearError`, and `create`, which the form's `onSave` calls.
 */
export function useCreateDiagram(projectId: string, onCreated: (id: string) => void) {
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId, "architecture_diagram");
  const commitTags = useCommitTags(projectId, "architecture_diagram");
  const [error, setError] = useState<string | null>(null);
  const create = useCallback(async (values: DiagramFieldValues, extras: DiagramCreateExtras) => {
    setError(null);
    try {
      const created = await projectDiagramApi(projectId).create({ ...values, activate: extras.activate, populate: extras.populate });
      showToast("Diagram created.");
      await commitQuickLinks(created.id, extras.quickLinks);
      await commitTags(created.id, extras.tags);
      onCreated(created.id);
    } catch (err) {
      setError(toErrorMessage(err, "Could not create the diagram."));
    }
  }, [projectId, showToast, commitQuickLinks, commitTags, onCreated]);
  return { error, clearError: useCallback(() => setError(null), []), create };
}
