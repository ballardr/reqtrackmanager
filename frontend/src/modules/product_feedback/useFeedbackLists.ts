/**
 * Module: modules/product_feedback/useFeedbackLists
 *
 * The choices of the module's two classified lists for a picker: the external systems a reference can name and the
 * channels a requester can have asked through. A project request picks from its project's effective list (the
 * organisation's entries with the project's overrides, minus the ones it hid); an inbox request picks from the
 * organisation's active entries. Entries that are switched off are left out, so only a usable choice is offered.
 */
import { useEffect, useState } from "react";

import { channelTypes, systemTypes } from "./api";

/** One choice in a picker. */
export interface ListChoice {
  value: string;
  label: string;
}

/**
 * @param projectId A project request's project; omit for an inbox request.
 * @param organizationId The organisation (used for an inbox request).
 * @returns The external systems the request's tier offers, in order (empty while loading).
 */
export function useExternalSystemChoices(projectId?: string, organizationId?: string): ListChoice[] {
  const [choices, setChoices] = useState<ListChoice[]>([]);
  useEffect(() => {
    let live = true;
    const load: Promise<ListChoice[]> = projectId
      ? systemTypes.project.list(projectId).then((rows) => rows.filter((e) => e.is_enabled).map((e) => ({ value: e.id, label: e.name })))
      : organizationId
        ? systemTypes.org.list(organizationId).then((rows) => rows.filter((e) => e.is_active).map((e) => ({ value: e.id, label: e.name })))
        : Promise.resolve([]);
    load.then((rows) => { if (live) setChoices(rows); }).catch(() => { if (live) setChoices([]); });
    return () => { live = false; };
  }, [projectId, organizationId]);
  return choices;
}

/**
 * @param projectId The project whose channel list to offer.
 * @returns The channels the project offers, in order (empty while loading).
 */
export function useRequestChannelChoices(projectId: string): ListChoice[] {
  const [choices, setChoices] = useState<ListChoice[]>([]);
  useEffect(() => {
    let live = true;
    channelTypes.project.list(projectId)
      .then((rows) => { if (live) setChoices(rows.filter((e) => e.is_enabled).map((e) => ({ value: e.id, label: e.name }))); })
      .catch(() => { if (live) setChoices([]); });
    return () => { live = false; };
  }, [projectId]);
  return choices;
}
