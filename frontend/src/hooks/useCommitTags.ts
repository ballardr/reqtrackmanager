/**
 * Module: hooks/useCommitTags
 *
 * Applies the tags a create form collected with `TagField`, once the record exists. The record
 * is already saved by then, so a refused tag set never undoes it: the user is told what failed and
 * where to add the tags by hand (the new record's header).
 */
import { useCallback } from "react";

import { recordTagsApi, type RecordTagsApi } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";

/**
 * @param projectId The project the record was created in.
 * @param artefactType The record's registered artefact type.
 * @param api Injectable calls (stories pass a fake); defaults to the live API.
 * @returns A function that tags the new record with `names` and reports a failure in a toast; it
 *   resolves `true` when there was nothing to apply or the tags were saved, and never throws.
 */
export function useCommitTags(
  projectId: string, artefactType: string, api: RecordTagsApi = recordTagsApi,
): (artefactId: string, names: string[]) => Promise<boolean> {
  const strings = useStrings();
  const { showToast } = useToast();
  return useCallback(async (artefactId, names) => {
    if (names.length === 0) return true;
    try {
      await api.set(projectId, artefactType, artefactId, names);
      return true;
    } catch (err) {
      const message = toErrorMessage(err, strings.common.error);
      showToast(strings.tags.create.failed(message.endsWith(".") ? message : `${message}.`), "error");
      return false;
    }
  }, [api, projectId, artefactType, showToast, strings]);
}
