/**
 * Module: api/reportFolders
 *
 * The client of the report folder endpoints: the folders the Reports picker can file a report under for an organisation
 * or a project, and adding, renaming and deleting the ones that scope owns.
 *
 * Responsibilities: the wire types and the endpoint calls for both tiers. A folder path travels in the body or query
 * string, never the URL path, because it contains `/`.
 */
import { api } from "./client";
import type { LayoutScope } from "./reportLayouts";

/** One folder a scope can file under (`ReportFolderOut`); `own` is true when the scope can rename or delete it. */
export interface ReportFolder {
  path: string;
  own: boolean;
}

/** The folders after a rename or delete, and what the change moved. */
export interface ReportFolderChange {
  folders: ReportFolder[];
  /** The renamed folder's new path; `null` for a delete. */
  path: string | null;
  layouts: number;
  packs: number;
  placements: number;
}

export interface ReportFolderApi {
  scope: LayoutScope;
  list(): Promise<ReportFolder[]>;
  add(path: string): Promise<ReportFolder[]>;
  rename(path: string, name: string): Promise<ReportFolderChange>;
  remove(path: string): Promise<ReportFolderChange>;
}

/** The live implementation for an organisation or a project. */
export function reportFolderApi(scope: LayoutScope): ReportFolderApi {
  const base = `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-folders`;
  return {
    scope,
    list: () => api.get<ReportFolder[]>(base),
    add: (path) => api.post<ReportFolder[]>(base, { path }),
    rename: (path, name) => api.patch<ReportFolderChange>(base, { path, name }),
    remove: (path) => api.delete<ReportFolderChange>(`${base}?path=${encodeURIComponent(path)}`),
  };
}
