/**
 * Module: hooks/useCommitQuickLinks
 *
 * Creates the links a create form collected with `QuickLinkField`, once the record exists.
 * The record is already saved by then, so a refused link set never undoes it: the user is told
 * what failed and where to add the links by hand (the new record's Links panel), because making
 * every create endpoint transactional with its links would mean changing all of them.
 */
import { useCallback } from "react";

import { artefactLinksApi, type ArtefactLinksApi, type CollectedLink } from "../api/artefactLinks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";

/**
 * @param projectId The project the record was created in.
 * @param artefactType The record's registered artefact type.
 * @param api Injectable calls (stories pass a fake); defaults to the live API.
 * @returns A function that links the new record to `links` all-or-nothing and reports the outcome in
 *   a toast; it resolves `true` when there was nothing to link or every link was created, and never throws.
 */
export function useCommitQuickLinks(
  projectId: string, artefactType: string, api: ArtefactLinksApi = artefactLinksApi,
): (artefactId: string, links: CollectedLink[]) => Promise<boolean> {
  const strings = useStrings();
  const { showToast } = useToast();
  return useCallback(async (artefactId, links) => {
    if (links.length === 0) return true;
    try {
      await api.createMany(
        projectId, artefactType, artefactId,
        links.map(({ link_type_id, direction, other_type, other_id }) => ({ link_type_id, direction, other_type, other_id })),
      );
      showToast(strings.artefactLinks.quick.added(links.length));
      return true;
    } catch (err) {
      const message = toErrorMessage(err, strings.artefactLinks.addFailed);
      showToast(strings.artefactLinks.quick.failed(message.endsWith(".") ? message : `${message}.`), "error");
      return false;
    }
  }, [api, projectId, artefactType, showToast, strings]);
}
