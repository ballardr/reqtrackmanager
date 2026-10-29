/**
 * Module: utils/extraReportItem
 *
 * Turns a host-provided report entry (the requirement report, a report pack) into a report picker item, with the
 * scope's placements (a folder, or hidden) applied. Shared by every picker that lists such entries (the Reports
 * dialog's `ReportCatalogue` and the record list's `ReportDownloadDialog`), so they file and hide them alike.
 */
import { PLACEMENT_KEY_REQUIREMENTS, type ResolvedPlacement } from "../api/reportPlacements";
import type { ExtraReportEntry } from "../components/ReportCatalogue";
import type { ReportPickerItem } from "../components/ReportPicker";

/** Where a host's extra report files unless a placement moves it. */
const DEFAULT_EXTRA_FOLDER = "Platform";

/**
 * @param entry The extra entry.
 * @param placements The scope's resolved placements by report key (`useReportPlacements`).
 * @returns The item, or `null` when a placement hides the entry.
 */

export function extraItem(entry: ExtraReportEntry, placements: Map<string, ResolvedPlacement>): ReportPickerItem | null {
  const key = entry.placementKey ?? (entry.key === "requirements" ? PLACEMENT_KEY_REQUIREMENTS : `report:platform.${entry.key}`);
  const placed = placements.get(key);
  if (placed?.hidden && key.startsWith("report:")) return null;
  return {
    id: entry.key, title: entry.title, description: entry.description, kind: entry.kind ?? "report", favouriteKey: key,
    folder: placed?.folder ?? entry.folder ?? DEFAULT_EXTRA_FOLDER,
  };
}
