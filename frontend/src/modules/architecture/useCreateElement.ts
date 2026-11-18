/**
 * Module: modules/architecture/useCreateElement
 *
 * The create step the Elements list, an element's "Add child" and the Links panel's "Create new" share: create the
 * element through the API (with its ports and, for "Save and activate", already active), apply the quick links and tags its
 * form collected, and keep the form open with the message when the server refuses. One implementation, so the three
 * places cannot differ in what they do after a create.
 */
import { useCallback, useState } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { projectElementApi } from "./api";
import type { ElementCreateExtras } from "./ElementFormModal";
import type { ElementFieldValues } from "./types";

/**
 * @param projectId The project the element is created in.
 * @param onCreated Called with the new element's id once it and its links and tags exist.
 * @returns `error` (the last refusal, or null), `clearError`, and `create`, which the form's `onSave` calls.
 */
export function useCreateElement(projectId: string, onCreated: (id: string) => void) {
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId, "architecture_element");
  const commitTags = useCommitTags(projectId, "architecture_element");
  const [error, setError] = useState<string | null>(null);
  const create = useCallback(async (values: ElementFieldValues, extras: ElementCreateExtras) => {
    setError(null);
    try {
      const created = await projectElementApi(projectId).create({ ...values, activate: extras.activate, ports: extras.ports });
      showToast("Element created.");
      await commitQuickLinks(created.id, extras.quickLinks);
      await commitTags(created.id, extras.tags);
      onCreated(created.id);
    } catch (err) {
      setError(toErrorMessage(err, "Could not create the element."));
    }
  }, [projectId, showToast, commitQuickLinks, commitTags, onCreated]);
  return { error, clearError: useCallback(() => setError(null), []), create };
}
