/**
 * Module: api/reportFile
 *
 * The client of exporting report layouts and packs as a `.zip` file and importing such a file
 * (`/report-file/export`, `/report-file/import`), for a project or the organisation.
 *
 * Responsibilities: the wire types, the labels a person reads for each kind and outcome (render enum values through
 * these, never the raw string), and one injectable interface so a story can run the dialogs without a server.
 */
import { api } from "./client";
import type { LayoutScope } from "./reportLayouts";

/** What a file holds. */
export type FileItemKind = "layout" | "pack";

/** What the import does with one item. */
export type FileItemAction = "create" | "rename" | "skip" | "left_out";

export const FILE_KIND_LABEL: Record<FileItemKind, string> = { layout: "Layout", pack: "Pack" };

export const FILE_ACTION_LABEL: Record<FileItemAction, string> = {
  create: "Import",
  rename: "Import under a new name",
  skip: "Skip: name already used",
  left_out: "Cannot be imported",
};

/** How a name the target already uses is settled. */
export type FileConflict = "rename" | "skip";
export const FILE_CONFLICT_LABEL: Record<FileConflict, string> = {
  rename: 'Import under a new name ("Name (copy)")',
  skip: "Skip it",
};

export interface FileExportRequest {
  layout_ids: string[];
  pack_ids: string[];
  include_history: boolean;
  include_pack_layouts: boolean;
}

export interface FileItemResult {
  kind: FileItemKind;
  name: string;
  new_name: string;
  action: FileItemAction;
  versions: number;
  warnings: string[];
  new_id: string | null;
}

/** The preview or the result of an import. */
export interface FileImportResult {
  dry_run: boolean;
  items: FileItemResult[];
  pictures: number;
  warnings: string[];
}

export interface ReportFileApi {
  scope: LayoutScope;
  /** The report file for the chosen layouts and packs, named as the server named it. */
  exportFile(request: FileExportRequest): Promise<Blob>;
  /** Previews (`dryRun`) or applies a report file. */
  importFile(file: File, options: { onConflict: FileConflict; dryRun: boolean }): Promise<FileImportResult>;
}

/** The live implementation for a project or the organisation. */
export function reportFileApi(scope: LayoutScope): ReportFileApi {
  const base = `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-file`;
  return {
    scope,
    exportFile: (request) => api.postForFile(`${base}/export`, request),
    importFile: (file, { onConflict, dryRun }) =>
      api.postFile<FileImportResult>(`${base}/import?dry_run=${dryRun ? "true" : "false"}`, file, { on_conflict: onConflict }),
  };
}
