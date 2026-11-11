/**
 * Module: hooks/useLinkedRecordSave
 *
 * The save step every "Create new" dialog of the Links panel shares (`TierAModuleDefinition.linkedRecordCreators`):
 * create the record through the type's own API, apply the quick links and tags its form collected, report the new id,
 * and keep the form open with the message when the create is refused. One implementation, so a dialog is a form plus
 * a create call and no module repeats the error handling.
 */
import { useCallback, useState } from "react";

import type { CollectedLink } from "../api/artefactLinks";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useCommitQuickLinks } from "./useCommitQuickLinks";
import { useCommitTags } from "./useCommitTags";

/** What a dialog's create call resolves to: the new record's id and, when part of it could not be applied, a warning. */
export interface CreatedRecord {
  id: string;
  /** Shown as an error toast beside the success one (the record exists; for example its groups could not be set). */
  warning?: string | null;
}

/**
 * @param projectId The project the record is created in.
 * @param artefactType The record's registered artefact type (keys its quick links and tags).
 * @param noun The record's name for messages, for example "Decision".
 * @param onCreated Called with the new record's id once it is created and its links and tags are applied.
 * @returns `error`, the message of the last refused create (null otherwise), and `save`, which runs the create.
 */
export function useLinkedRecordSave(
  projectId: string, artefactType: string, noun: string, onCreated: (id: string) => void,
): {
  error: string | null;
  save: (create: () => Promise<CreatedRecord>, quickLinks?: CollectedLink[], tags?: string[]) => Promise<void>;
} {
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId, artefactType);
  const commitTags = useCommitTags(projectId, artefactType);
  const [error, setError] = useState<string | null>(null);
  const save = useCallback(async (create: () => Promise<CreatedRecord>, quickLinks: CollectedLink[] = [], tags: string[] = []) => {
    setError(null);
    try {
      const created = await create();
      showToast(`${noun} created.`);
      if (created.warning) showToast(created.warning, "error");
      await commitQuickLinks(created.id, quickLinks);
      await commitTags(created.id, tags);
      onCreated(created.id);
    } catch (err) {
      setError(toErrorMessage(err, `Could not create ${noun}.`));
    }
  }, [showToast, commitQuickLinks, commitTags, noun, onCreated]);
  return { error, save };
}
