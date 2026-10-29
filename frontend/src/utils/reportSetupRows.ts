/**
 * Module: utils/reportSetupRows
 *
 * The one row model of the Report setup list: every report a scope can arrange (module and platform reports, custom
 * layouts and report packs) as a single typed row, merged on the client from the three lists the server already serves
 * (placements, layouts, packs) and the filter that narrows them.
 *
 * Responsibilities:
 * - Join the placement list (which holds the folder a report files under now and whether a module report is hidden)
 *   with the layout and pack lists (which hold what only the owner can change) by the report's placement key.
 * - Add the layouts and packs a project has hidden, which the placement list leaves out, so they can be shown again.
 * - Say, per row, which of the row's actions apply (`rowCan`), so the list and its stories share one rule.
 *
 * Design decisions: a client-side merge, not a combined endpoint: the three lists are small and each is already
 * authorised per row by the server (a 403 on any shows the load failure). A hidden row keeps its folder so it does not
 * jump to the top level. Pure functions over plain data.
 */
import type { LayoutOrigin } from "../api/reportLayouts";
import type { ReportLayoutSummary } from "../api/reportLayouts";
import type { ReportPackSummary } from "../api/reportPacks";
import type { PlacementSource, ReportPlacement } from "../api/reportPlacements";

/** The default folders the server files a layout or pack under when its author chose none. */
export const CUSTOM_REPORTS_FOLDER = "Custom reports";
export const REPORT_PACKS_FOLDER = "Report packs";

/** What a row is: a custom layout, a pack, or a report a module or the platform provides. */
export type SetupRowType = "layout" | "pack" | "module";

/** What the report looks like to a person (the picker's type icon): a document, a table of rows or a pack of files. */
export type SetupRowShape = "report" | "sheet" | "pack";

/** Where a row comes from: an owned or shared layout/pack, or a module or the platform. */
export type SetupRowOrigin = LayoutOrigin | "platform";

/** One report in the setup list. */
export interface ReportSetupRow {
  /** The placement key (`layout:<id>`, `pack:<id>`, `report:<module>.<key>`), unique in a list. */
  key: string;
  type: SetupRowType;
  shape: SetupRowShape;
  title: string;
  description: string;
  /** Where it files now. */
  folder: string;
  /** Where it files with no placement. */
  defaultFolder: string;
  origin: SetupRowOrigin;
  /** The asking scope owns the layout or pack (a module report is never owned). */
  owned: boolean;
  /** Hidden from the Reports list in this scope. */
  hidden: boolean;
  hiddenFrom: PlacementSource | null;
  /** The tier that set the folder when it is not the default. */
  folderFrom: PlacementSource | null;
  /** This scope's own folder override on a shared row (`null` = none). */
  ownFolder: string | null;
  /** This scope's own hide/show override of a module report (`null` = none). */
  ownHidden: boolean | null;
  /** A module report: whether a placement may hide it. A layout or pack hides through its own endpoint. */
  canHidePlacement: boolean;
  version: number | null;
  updatedAt: string | null;
  /** A pack's number of reports. */
  entries: number | null;
  layout?: ReportLayoutSummary;
  pack?: ReportPackSummary;
}

/** The actions a row can offer, derived once. */
export interface RowCapabilities {
  open: boolean;
  editDetails: boolean;
  copy: boolean;
  delete: boolean;
  hide: boolean;
  show: boolean;
  resetFolder: boolean;
  resetVisibility: boolean;
}

const LAYOUT_PREFIX = "layout:";
const PACK_PREFIX = "pack:";

function fromLayout(layout: ReportLayoutSummary, placement: ReportPlacement | undefined): ReportSetupRow {
  const fallback = layout.folder || CUSTOM_REPORTS_FOLDER;
  return {
    key: `${LAYOUT_PREFIX}${layout.id}`, type: "layout", shape: layout.family === "table" ? "sheet" : "report",
    title: layout.name, description: layout.description,
    folder: placement?.folder ?? fallback, defaultFolder: placement?.default_folder ?? fallback,
    origin: layout.origin, owned: layout.editable, hidden: layout.hidden, hiddenFrom: layout.hidden ? "project" : null,
    folderFrom: placement?.folder_from ?? null, ownFolder: placement?.own_folder ?? null, ownHidden: null, canHidePlacement: false,
    version: layout.current_version, updatedAt: layout.updated_at, entries: null, layout,
  };
}

function fromPack(pack: ReportPackSummary, placement: ReportPlacement | undefined): ReportSetupRow {
  const fallback = pack.folder || REPORT_PACKS_FOLDER;
  return {
    key: `${PACK_PREFIX}${pack.id}`, type: "pack", shape: "pack", title: pack.name, description: pack.description,
    folder: placement?.folder ?? fallback, defaultFolder: placement?.default_folder ?? fallback,
    origin: pack.origin, owned: pack.editable, hidden: pack.hidden, hiddenFrom: pack.hidden ? "project" : null,
    folderFrom: placement?.folder_from ?? null, ownFolder: placement?.own_folder ?? null, ownHidden: null, canHidePlacement: false,
    version: pack.current_version, updatedAt: pack.updated_at, entries: pack.entries, pack,
  };
}

function fromPlacement(placement: ReportPlacement): ReportSetupRow {
  return {
    key: placement.report_key, type: "module", shape: placement.kind, title: placement.title, description: placement.description,
    folder: placement.folder, defaultFolder: placement.default_folder, origin: "platform", owned: false,
    hidden: placement.hidden, hiddenFrom: placement.hidden_from, folderFrom: placement.folder_from, ownFolder: placement.own_folder,
    ownHidden: placement.own_hidden, canHidePlacement: placement.can_hide, version: null, updatedAt: null, entries: null,
  };
}

/**
 * Merges the three lists into the setup list's rows.
 *
 * @param placements Every report the scope can place (module, platform, layouts and packs that are not hidden).
 * @param layouts The scope's layouts, hidden ones included for a manager.
 * @param packs The scope's packs, hidden ones included for a manager.
 * @returns One row per report, in no particular order (the list sorts them).
 */
export function buildSetupRows(
  placements: ReportPlacement[], layouts: ReportLayoutSummary[], packs: ReportPackSummary[],
): ReportSetupRow[] {
  const placementByKey = new Map(placements.map((p) => [p.report_key, p]));
  const rows: ReportSetupRow[] = [
    ...layouts.map((layout) => fromLayout(layout, placementByKey.get(`${LAYOUT_PREFIX}${layout.id}`))),
    ...packs.map((pack) => fromPack(pack, placementByKey.get(`${PACK_PREFIX}${pack.id}`))),
  ];
  const known = new Set(rows.map((row) => row.key));
  for (const placement of placements) {
    // A layout or pack the lists did not return (it cannot be opened from here) still lists, as a placement.
    if (!known.has(placement.report_key)) rows.push(fromPlacement(placement));
  }
  return rows;
}

/**
 * @param row The row.
 * @param inProject Whether the list is a project's (hiding a shared layout or pack is a project-only action).
 * @returns Which actions apply to it.
 */
export function rowCan(row: ReportSetupRow, inProject: boolean): RowCapabilities {
  const hasObject = row.layout !== undefined || row.pack !== undefined;
  const sharedObject = hasObject && !row.owned;
  return {
    open: hasObject,
    editDetails: hasObject && row.owned,
    copy: hasObject,
    delete: hasObject && row.owned,
    hide: !row.hidden && ((sharedObject && inProject) || row.canHidePlacement),
    show: row.hidden && ((hasObject && inProject) || (!hasObject && row.canHidePlacement)),
    resetFolder: !row.owned && row.ownFolder !== null,
    resetVisibility: !hasObject && row.ownHidden !== null,
  };
}

/** The type filter's values. */
export type SetupTypeFilter = "" | "report" | "sheet" | "pack";
/** The status filter's values. */
export type SetupStatusFilter = "" | "moved" | "hidden";
/** Where a row is shared from (a project's list). */
export type SetupSourceFilter = "" | "own" | "shared";

export interface ReportSetupFilter {
  search: string;
  type: SetupTypeFilter;
  status: SetupStatusFilter;
  source: SetupSourceFilter;
}

export const EMPTY_SETUP_FILTER: ReportSetupFilter = { search: "", type: "", status: "", source: "" };

/** Whether any part of the filter is set. */
export function isFiltering(filter: ReportSetupFilter): boolean {
  return filter.search.trim() !== "" || filter.type !== "" || filter.status !== "" || filter.source !== "";
}

/**
 * @param rows The rows to narrow.
 * @param filter The current filter.
 * @returns The rows that match every part of it, in their order.
 */
export function applySetupFilter(rows: ReportSetupRow[], filter: ReportSetupFilter): ReportSetupRow[] {
  const needle = filter.search.trim().toLowerCase();
  return rows.filter((row) => (
    (needle === "" || `${row.title} ${row.description} ${row.folder}`.toLowerCase().includes(needle))
    && (filter.type === "" || row.shape === filter.type)
    && (filter.status === "" || (filter.status === "hidden" ? row.hidden : row.folder !== row.defaultFolder))
    && (filter.source === "" || (filter.source === "own") === row.owned)
  ));
}
