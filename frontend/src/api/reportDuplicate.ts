/**
 * Module: api/reportDuplicate
 *
 * The client of duplicating one report layout or pack, or starting a layout from a built-in starter
 * (`POST .../report-duplicate`, at a project or the organisation). A dry run returns the plan, the call without it
 * creates the copy.
 *
 * Responsibilities: the wire types, the labels a person reads for each source and destination (render enum values
 * through these, never the raw string), and one injectable interface bound to a scope so a story can run the dialog
 * without a server.
 */
import { api } from "./client";
import type { LayoutScope } from "./reportLayouts";

/** What can be duplicated. */
export type DuplicateKind = "layout" | "pack" | "starter";

/** Where the copy goes: the project in the page, or the organisation (a copy up). */
export type DuplicateTarget = "project" | "organization";

/** What a person calls each destination. */
export const DUPLICATE_TARGET_LABEL: Record<DuplicateTarget, string> = {
  project: "This project",
  organization: "The organisation (shared with every project)",
};

/** Where the source comes from, as the plan words it (the built-in starters are not stored anywhere). */
export const DUPLICATE_ORIGIN_LABEL: Record<string, string> = {
  project: "This project",
  ancestor: "A parent project",
  organization: "The organisation",
  starter: "Built-in starter",
};

export interface DuplicateRequest {
  kind: DuplicateKind;
  source_id?: string;
  starter_key?: string;
  target: DuplicateTarget;
  /** The copy's name; the server suggests one when empty. */
  name?: string;
  dry_run: boolean;
}

/** The plan of a duplicate, or its result (`new_id` set once created). */
export interface DuplicateResult {
  dry_run: boolean;
  kind: DuplicateKind;
  source_name: string;
  origin: string;
  name: string;
  suggested_name: string;
  name_taken: boolean;
  shadows: boolean;
  folder: string;
  warnings: string[];
  /** Project pictures that stop a copy up to the organisation. */
  blocked_images: string[];
  new_id: string | null;
  target: DuplicateTarget;
  /** The caller's organisation (where a copy up lands). */
  organization_id: string;
}

/** A built-in starter layout. */
export interface ReportStarter {
  key: string;
  name: string;
  description: string;
  orientation: string;
}

export interface ReportDuplicateApi {
  scope: LayoutScope;
  starters(): Promise<ReportStarter[]>;
  duplicate(request: DuplicateRequest): Promise<DuplicateResult>;
}

/** The live implementation for an organisation or a project. */
export function reportDuplicateApi(scope: LayoutScope): ReportDuplicateApi {
  const base = `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-duplicate`;
  return {
    scope,
    starters: () => api.get<ReportStarter[]>(`${base}/starters`),
    duplicate: (request) => api.post<DuplicateResult>(base, request),
  };
}
