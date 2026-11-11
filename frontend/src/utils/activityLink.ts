/**
 * Module: utils/activityLink
 *
 * Where an activity entry's record opens, for every registered record type: the one place the project History
 * table, the overview's activity widget and a record's Activity aside decide the link and its label.
 *
 * Requirements and change requests carry their code and title in `detail` (`activityEntryLink`); any other
 * type the viewer may see carries a `record_label` from the server and resolves its page through the module
 * registry (`getArtefactPath`), so a module's records link without a per-type case here. A record with no label
 * (hidden from the viewer) or no page of its own gets no link.
 */
import { activityEntryLink, type ChangeEntry } from "../api/types";
import { getArtefactPath } from "../modules/artefactPaths";

/** A link and its visible label. */
export interface ActivityLink {
  to: string;
  label: string;
}

/**
 * @param entry The activity entry.
 * @param projectId The project whose history it is.
 * @returns The record's link and label, or `null` when the entry is not about an openable record.
 */
export function activityRecordLink(entry: ChangeEntry, projectId: string): ActivityLink | null {
  const core = activityEntryLink(entry, projectId);
  if (core) return core;
  if (!entry.record_label) return null;
  const to = getArtefactPath(entry.entity_type, projectId, entry.entity_id);
  return to ? { to, label: entry.record_label } : null;
}
