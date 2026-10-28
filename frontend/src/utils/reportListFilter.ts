/**
 * Module: utils/reportListFilter
 *
 * The filter a list of report layouts or packs narrows by (search, kind, folder, where it is shared from) and the rule
 * that applies it. Shared by `ReportListControls` and the two lists that use it.
 *
 * Design decisions: a folder filter keeps the folder and everything inside it; a row from the asking scope itself is
 * "own" and every other tier is "shared".
 */

/** The "no filter" value of the folder and kind filters. */
export const FILTER_ALL = "";

export type ReportListSource = "all" | "own" | "shared";

export interface ReportListFilter {
  search: string;
  /** A folder path, or `FILTER_ALL`. */
  folder: string;
  source: ReportListSource;
  /** A kind value, or `FILTER_ALL`. */
  kind: string;
}

export const EMPTY_REPORT_LIST_FILTER: ReportListFilter = { search: "", folder: FILTER_ALL, source: "all", kind: FILTER_ALL };

interface Filterable {
  name: string;
  description: string;
  folder: string;
  origin: string;
}

/**
 * @param rows The rows to narrow.
 * @param filter The current filter.
 * @param kindOf The row's kind value (for the kind filter); omit when there is no kind filter.
 * @returns The rows that match every part of the filter, in their order.
 */
export function applyReportListFilter<R extends Filterable>(
  rows: R[], filter: ReportListFilter, kindOf?: (row: R) => string,
): R[] {
  const needle = filter.search.trim().toLowerCase();
  const folder = filter.folder.toLowerCase();
  return rows.filter((row) => (
    (needle === "" || `${row.name} ${row.description} ${row.folder}`.toLowerCase().includes(needle))
    && (filter.folder === FILTER_ALL || row.folder.toLowerCase() === folder || row.folder.toLowerCase().startsWith(`${folder}/`))
    && (filter.source === "all" || (filter.source === "own") === (row.origin === "project"))
    && (filter.kind === FILTER_ALL || kindOf === undefined || kindOf(row) === filter.kind)
  ));
}
