/**
 * Module: modules/architecture/useCreateConnection
 *
 * The create step the Connections list and an element's "New connection" share: create the connection (already active for
 * "Save and activate"), apply the quick links and tags its form collected, and keep the form open with the message when the
 * server refuses (for example an end the person cannot read).
 */
import { useCallback, useState } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useCommitQuickLinks } from "../../hooks/useCommitQuickLinks";
import { useCommitTags } from "../../hooks/useCommitTags";
import { projectConnectionApi } from "./api";
import type { ConnectionCreateExtras } from "./ConnectionFormModal";
import type { ConnectionFieldValues } from "./types";

/**
 * @param projectId The project the connection is created in.
 * @param onCreated Called with the new connection's id once it and its links and tags exist.
 * @returns `error` (the last refusal, or null), `clearError`, and `create`, which the form's `onSave` calls.
 */
export function useCreateConnection(projectId: string, onCreated: (id: string) => void) {
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId, "architecture_connection");
  const commitTags = useCommitTags(projectId, "architecture_connection");
  const [error, setError] = useState<string | null>(null);
  const create = useCallback(async (values: ConnectionFieldValues, extras: ConnectionCreateExtras) => {
    setError(null);
    try {
      const created = await projectConnectionApi(projectId).create({ ...values, activate: extras.activate });
      showToast("Connection created.");
      await commitQuickLinks(created.id, extras.quickLinks);
      await commitTags(created.id, extras.tags);
      onCreated(created.id);
    } catch (err) {
      setError(toErrorMessage(err, "Could not create the connection."));
    }
  }, [projectId, showToast, commitQuickLinks, commitTags, onCreated]);
  return { error, clearError: useCallback(() => setError(null), []), create };
}
