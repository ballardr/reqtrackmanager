/**
 * Module: modules/stakeholders/reportFixtures
 *
 * Storybook-only builders for the S1 and S4 report results,
 * shaped like the backend's `ReportOut` for those reports. Kept beside the
 * stories rather than in the global `testing/` helpers so core test helpers
 * never import a module's types (the same convention as Context & Strategy's
 * `reportFixtures`).
 */
import type { ReportCatalogueEntry, ReportResult } from "../../api/reports";
import { buildReportCatalogueEntry, buildReportResult } from "../../testing/reportFixtures";
import type { GridItem, PowerInterestGridData } from "./reportTypes";

const MODULE = "stakeholders";
const UUID_PARAM = { type: "uuid" as const, default: null, choices: null, minimum: null, maximum: null };

/** The S1 catalogue entry (project scope). */
export function gridEntry(overrides: Partial<ReportCatalogueEntry> = {}): ReportCatalogueEntry {
  return buildReportCatalogueEntry({
    module_key: MODULE, module_name: "Stakeholders & Personas", key: "s1", slug: "power-interest-grid",
    title: "Power/interest grid", description: "Stakeholders on Influence × Interest.",
    path: "/api/v1/projects/project-1/modules/stakeholders/reports/power-interest-grid",
    params: [
      { name: "group_id", description: "Only this group.", ...UUID_PARAM },
      { name: "group_by", description: "Arrange by this group.", ...UUID_PARAM },
    ],
    ...overrides,
  });
}

/** The S4 catalogue entry (project scope). */
export function stalenessEntry(overrides: Partial<ReportCatalogueEntry> = {}): ReportCatalogueEntry {
  return buildReportCatalogueEntry({
    module_key: MODULE, module_name: "Stakeholders & Personas", key: "s4", slug: "engagement-staleness",
    title: "Engagement staleness", description: "Stakeholders overdue for engagement.",
    path: "/api/v1/projects/project-1/modules/stakeholders/reports/engagement-staleness",
    params: [
      { name: "group_id", description: "Only this group.", ...UUID_PARAM },
      { name: "group_by", description: "Arrange by this group.", ...UUID_PARAM },
      { name: "persona_months", type: "integer", default: 6, choices: null, minimum: 1, maximum: 60, description: "Persona window." },
    ],
    ...overrides,
  });
}

/** One Stakeholder on the grid. */
export function gridItem(overrides: Partial<GridItem> = {}): GridItem {
  return { id: "sh-1", project_id: "project-1", name: "Sam Sponsor", influence: "High", interest: "High", ...overrides };
}

/** S1's `data`: one Stakeholder in each quadrant but Monitor, and one unscored. */
export function gridData(overrides: Partial<PowerInterestGridData> = {}): PowerInterestGridData {
  return {
    group_by: false,
    quadrants: {
      manage_closely: [gridItem()],
      keep_satisfied: [gridItem({ id: "sh-2", name: "Pat Regulator", interest: "Low" })],
      keep_informed: [gridItem({ id: "sh-3", name: "Uma User", influence: "Low" })],
      monitor: [],
    },
    unscored: [gridItem({ id: "sh-4", name: "Newly Added", influence: "", interest: "" })],
    ...overrides,
  };
}

const GRID_COLUMNS = ["Stakeholder", "Project", "Type", "Influence", "Interest", "Owner", "Groups", "Target cadence"];

/** An S1 result built from `gridData()` (the sections mirror the data). */
export function gridResult(overrides: Partial<ReportResult> = {}): ReportResult {
  const data = (overrides.data as PowerInterestGridData | undefined) ?? gridData();
  const rows = (items: GridItem[]) => items.map((i) => [i.name, "Atlas Platform", "Customer", i.influence, i.interest, "", "", "Monthly"]);
  return buildReportResult({
    key: "s1", title: "Power/interest grid", notes: ["Covers this project only."],
    sections: [
      { key: "manage_closely", title: "Manage closely", columns: GRID_COLUMNS, rows: rows(data.quadrants.manage_closely), note: "", gap: false },
      { key: "keep_satisfied", title: "Keep satisfied", columns: GRID_COLUMNS, rows: rows(data.quadrants.keep_satisfied), note: "", gap: false },
      { key: "keep_informed", title: "Keep informed", columns: GRID_COLUMNS, rows: rows(data.quadrants.keep_informed), note: "", gap: false },
      { key: "monitor", title: "Monitor", columns: GRID_COLUMNS, rows: rows(data.quadrants.monitor), note: "", gap: false },
      { key: "unscored", title: "Not scored", columns: GRID_COLUMNS, rows: rows(data.unscored), note: "Influence or Interest is not set.", gap: true },
    ],
    metrics: [{ label: "Stakeholders", value: 4 }, { label: "Not scored", value: data.unscored.length, gap: true }],
    data,
    ...overrides,
  });
}

/** An S4 result: one overdue Stakeholder, one with no cadence and one Persona not engaged lately. */
export function stalenessResult(overrides: Partial<ReportResult> = {}): ReportResult {
  return buildReportResult({
    key: "s4", title: "Engagement staleness",
    sections: [
      {
        key: "overdue", title: "Overdue for engagement",
        columns: ["Stakeholder", "Project", "Influence", "Interest", "Target cadence", "Last engaged", "Overdue by", "Availability", "Owner"],
        rows: [["Sam Sponsor", "Atlas Platform", "High", "High", "Monthly", "2026-07-01", "75 days", "Only Fridays", "Alex Owner"]],
        note: "", gap: true,
      },
      {
        key: "no_cadence", title: "No target cadence set",
        columns: ["Stakeholder", "Project", "Influence", "Interest", "Suggested cadence", "Last engaged", "Owner"],
        rows: [["Newly Added", "Atlas Platform", "", "", "", "", ""]], note: "", gap: true,
      },
      {
        key: "personas_not_engaged", title: "Personas with no engagement in 6 months",
        columns: ["Persona", "Project", "Weight", "Last engagement", "Owner"],
        rows: [["Field Technician", "Atlas Platform", "3", "", ""]], note: "", gap: true,
      },
    ],
    metrics: [{ label: "Overdue", value: 1, gap: true }, { label: "No target cadence", value: 1, gap: true }],
    data: { overdue: 1, no_cadence: 1, personas_not_engaged: 1 },
    ...overrides,
  });
}
