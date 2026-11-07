/**
 * Module: hooks/useCommitTags
 *
 * Applies the tags and the components a create form collected with `TagField` (which also offers
 * `ComponentField`), once the record exists. The record is already saved by then, so a refused set never undoes
 * it: the user is told what failed and where to add them by hand (the new record's header).
 */
import { useCallback } from "react";

import { recordPlacementsApi, type RecordPlacementsApi } from "../api/placements";
import { recordTagsApi, type RecordTagsApi } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { takePendingPlacements } from "./pendingPlacements";

/**
 * @param projectId The project the record was created in.
 * @param artefactType The record's registered artefact type.
 * @param api Injectable calls (stories pass a fake); defaults to the live API.
 * @param placementsApi Injectable placement calls; defaults to the live API.
 * @returns A function that tags the new record with `names` and places it where `ComponentField` chose, reporting
 *   a failure in a toast; it resolves `true` when there was nothing to apply or everything was saved, and never throws.
 */
export function useCommitTags(
  projectId: string, artefactType: string, api: RecordTagsApi = recordTagsApi,
  placementsApi: RecordPlacementsApi = recordPlacementsApi,
): (artefactId: string, names: string[]) => Promise<boolean> {
  const strings = useStrings();
  const { showToast } = useToast();
  return useCallback(async (artefactId, names) => {
    const sentence = (message: string) => (message.endsWith(".") ? message : `${message}.`);
    let saved = true;
    const places = takePendingPlacements(projectId, artefactType);
    if (names.length > 0) {
      try {
        await api.set(projectId, artefactType, artefactId, names);
      } catch (err) {
        showToast(strings.tags.create.failed(sentence(toErrorMessage(err, strings.common.error))), "error");
        saved = false;
      }
    }
    if (places.length > 0) {
      try {
        await placementsApi.set(projectId, artefactType, artefactId, places);
      } catch (err) {
        showToast(strings.placements.create.failed(sentence(toErrorMessage(err, strings.common.error))), "error");
        saved = false;
      }
    }
    return saved;
  }, [api, placementsApi, projectId, artefactType, showToast, strings]);
}
