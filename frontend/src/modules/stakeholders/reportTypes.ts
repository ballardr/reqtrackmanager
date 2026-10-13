/**
 * Module: modules/stakeholders/reportTypes
 *
 * The `ReportResult.data` shape this module's custom report view reads, mirroring
 * what `collect_power_interest_grid` (S1) returns in
 * `backend/app/modules/stakeholders/reports.py`. S2, S3 and S5 have no custom
 * view, and S4's view reads only the generic sections.
 */
import type { GridQuadrant } from "./types";

/** One Stakeholder placed on the grid. */
export interface GridItem {
  id: string;
  project_id: string;
  name: string;
  /** The Influence level name, "" when unset. */
  influence: string;
  /** The Interest level name, "" when unset. */
  interest: string;
}

/** S1's `data`. */
export interface PowerInterestGridData {
  /** Whether the run was arranged by a top-level group (the sections then carry a Branch column). */
  group_by: boolean;
  quadrants: Record<GridQuadrant, GridItem[]>;
  unscored: GridItem[];
}
