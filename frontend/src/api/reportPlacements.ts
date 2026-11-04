/**
 * Module: api/reportPlacements
 *
 * The client of the report placement endpoints: where each report appears in the Reports picker for an organisation
 * or a project (its folder, and whether a module report is shown), and the resolved view the picker reads.
 *
 * Responsibilities: the wire types, the endpoint calls for both tiers and `PLACEMENT_KEY_REQUIREMENTS` / `packPlacementKey`,
 * the keys of the entries the picker builds itself.
 */
import { api } from "./client";
import type { LayoutScope } from "./reportLayouts";

/** The project's own requirements report (a picker entry with its own request model). */
export const PLACEMENT_KEY_REQUIREMENTS = "report:platform.requirements";

/** The placement key of a pack. */
export function packPlacementKey(packId: string): string {
  return `pack:${packId}`;
}

export type PlacementSource = "project" | "ancestor" | "organization";

/** One report a scope can place (`ReportPlacementOut`). */
export interface ReportPlacement {
  report_key: string;
  title: string;
  description: string;
  kind: "report" | "sheet" | "pack";
  /** Its module, "Custom reports" or "Report packs". */
  group: string;
  default_folder: string;
  /** Where it files now. */
  folder: string;
  folder_from: PlacementSource | null;
  /** This scope's own override (`null` = none, `""` = the top level). */
  own_folder: string | null;
  hidden: boolean;
  hidden_from: PlacementSource | null;
  own_hidden: boolean | null;
  can_hide: boolean;
}

/** What a scope's placements say about one report (only reports with a placement are listed). */
export interface ResolvedPlacement {
  report_key: string;
  folder: string | null;
  hidden: boolean;
}

/** Sets one scope's placement; a field left out is unchanged, one sent as `null` clears this scope's override. */
export interface PlacementChange {
  report_key: string;
  folder?: string | null;
  hidden?: boolean | null;
}

export interface ReportPlacementApi {
  scope: LayoutScope;
  list(): Promise<ReportPlacement[]>;
  set(change: PlacementChange): Promise<ReportPlacement[]>;
  resolved(): Promise<ResolvedPlacement[]>;
}

/** The live implementation for an organisation or a project. */
export function reportPlacementApi(scope: LayoutScope): ReportPlacementApi {
  const base = `/api/v1/${scope.kind === "project" ? "projects" : "orgs"}/${scope.id}/report-placements`;
  return {
    scope,
    list: () => api.get<ReportPlacement[]>(base),
    set: (change) => api.put<ReportPlacement[]>(base, change),
    resolved: () => api.get<ResolvedPlacement[]>(`${base}/resolved`),
  };
}
