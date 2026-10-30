/**
 * Module: api/reportCopy
 *
 * The client of copying reports between projects of one organisation: the projects a person can copy into, and the
 * preview and the copy itself (`POST /projects/{target}/report-copy`, the body names the source project and the selection).
 *
 * Responsibilities: the wire types, the labels a person reads for each kind and outcome (render enum values through
 * these, never the raw string), and one injectable interface so a story can run the dialog without a server.
 */
import { api } from "./client";

/** What can be copied. */
export type CopyKind = "layout" | "pack" | "folder" | "placement";

/** What the copy does with one item. */
export type CopyAction = "create" | "rename" | "skip" | "exists" | "left_out";

/** What a person calls each kind of item. */
export const COPY_KIND_LABEL: Record<CopyKind, string> = {
  layout: "Layout",
  pack: "Pack",
  folder: "Folder",
  placement: "Module report setting",
};

/** What a person calls each outcome. */
export const COPY_ACTION_LABEL: Record<CopyAction, string> = {
  create: "Copy",
  rename: "Copy under a new name",
  skip: "Skip: name already used",
  exists: "Already there",
  left_out: "Cannot be copied",
};

/** What a person calls each way of settling a name the target project already uses. */
export type CopyConflict = "rename" | "skip";
export const COPY_CONFLICT_LABEL: Record<CopyConflict, string> = {
  rename: 'Copy under a new name ("Name (copy)")',
  skip: "Skip it",
};

/** What to copy (the ids and keys the source project's setup list shows). */
export interface CopyItems {
  layout_ids: string[];
  pack_ids: string[];
  folders: string[];
  placement_keys: string[];
}

export interface CopyRequest extends CopyItems {
  source_project_id: string;
  on_conflict: CopyConflict;
  favourites: boolean;
  dry_run: boolean;
}

export interface CopyItemResult {
  kind: CopyKind;
  source_id: string;
  name: string;
  origin: string;
  action: CopyAction;
  new_name: string;
  warnings: string[];
  new_id: string | null;
}

export interface CopyResult {
  dry_run: boolean;
  target_project_id: string;
  items: CopyItemResult[];
  warnings: string[];
  favourites_carried: number;
}

/** A project the person may copy reports into. */
export interface CopyTarget {
  id: string;
  name: string;
  parent_project_id: string | null;
}

export interface ReportCopyApi {
  targets(sourceProjectId: string): Promise<CopyTarget[]>;
  copy(targetProjectId: string, request: CopyRequest): Promise<CopyResult>;
}

/** The live implementation. */
export const reportCopyApi: ReportCopyApi = {
  targets: (sourceProjectId) => api.get<CopyTarget[]>(`/api/v1/projects/${sourceProjectId}/report-copy/targets`),
  copy: (targetProjectId, request) => api.post<CopyResult>(`/api/v1/projects/${targetProjectId}/report-copy`, request),
};

export const EMPTY_COPY_ITEMS: CopyItems = { layout_ids: [], pack_ids: [], folders: [], placement_keys: [] };
