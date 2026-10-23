/**
 * Module: testing/recordTablesFixtures
 *
 * Story fixtures for the shared list actions: a requirement-shaped table definition and a fake
 * `RecordTablesApi` whose calls are spies, so a story can drive the Export menu and the Import wizard with no network.
 */
import { fn, type Mock } from "storybook/test";

import type {
  GridColumn,
  GridRow,
  RecordColumn,
  RecordGridData,
  RecordColumns,
  RecordImportResult,
  RecordTablesApi,
} from "../api/recordTables";

const column = (partial: Partial<RecordColumn> & Pick<RecordColumn, "key" | "label">): RecordColumn => ({
  kind: "text", importable: true, editable: false, required: false, sensitivity: "none", included: true, choices: null,
  ...partial,
});

/** A requirement-shaped table: required name, component and category, a closed `level`, a date and a person. */
export function buildRecordColumns(overrides: Partial<RecordColumns> = {}): RecordColumns {
  return {
    label: "Requirements",
    columns: [
      column({ key: "code", label: "Code", importable: false }),
      column({ key: "name", label: "Name", required: true, editable: true }),
      column({ key: "component", label: "Component", kind: "enum", required: true, choices: ["AUTH", "BILL"] }),
      column({ key: "category", label: "Category", kind: "enum", required: true, choices: ["LOG"] }),
      column({ key: "level", label: "Level", kind: "enum", editable: true, choices: ["Requirement", "Recommended", "Optional"] }),
      column({ key: "owner", label: "Owner", kind: "principal" }),
      column({ key: "review_date", label: "Review date", kind: "date" }),
      column({ key: "status", label: "Status", kind: "enum", importable: false }),
    ],
    omitted_sensitivity: [],
    omitted_reasons: {},
    importable: true,
    can_import: true,
    not_importable_reason: null,
    filter_params: ["status", "search"],
    max_rows: 5000,
    max_bytes: 5 * 1024 * 1024,
    ...overrides,
  };
}

/** An import result with no rows, for a story to override. */
export function buildImportResult(overrides: Partial<RecordImportResult> = {}): RecordImportResult {
  return {
    applied: false, created: 0, updated: 0, unchanged: 0, failed: 0, rows: [], ignored_columns: {}, omitted_sensitivity: [],
    error_csv: "", ...overrides,
  };
}

/**
 * A spy that resolves each call to the next of `results` (the last one repeats). Storybook resets mocks before every
 * story, which drops `mockResolvedValueOnce` queues, so the position is read from the spy's own call count instead.
 */
export function inSequence<T>(...results: T[]) {
  const spy: Mock<(...args: unknown[]) => Promise<T>> = fn(async () => results[Math.min(spy.mock.calls.length - 1, results.length - 1)]);
  return spy;
}

/** A spy whose every call rejects with `message`. */
export function failing(message: string) {
  return fn(async () => {
    throw new Error(message);
  });
}

/**
 * A fake API: every call is a spy; pass overrides to change what a call resolves to. The default implementations are
 * passed to `fn` (not set with `mockResolvedValue`) so they survive Storybook's reset of mocks between stories.
 */
export function fakeRecordTables(overrides: Partial<RecordTablesApi> = {}, columns: RecordColumns = buildRecordColumns()): RecordTablesApi {
  return {
    columns: fn(async () => columns),
    exportFile: fn(async () => new Blob(["code,name\n"], { type: "text/csv" })),
    importFile: fn(async () => buildImportResult()),
    grid: fn(async () => buildGrid()),
    saveRow: fn(async (_projectId: string, _recordType: string, code: string, cells: Record<string, string>) => {
      const row = buildGrid().rows.find((r) => r.code === code) ?? buildGrid().rows[0];
      return { ...row, cells: { ...row.cells, ...cells } };
    }),
    ...overrides,
  };
}

const gridColumn = (partial: Partial<GridColumn> & Pick<GridColumn, "key" | "label">): GridColumn => ({
  kind: "text", editable: false, required: false, choices: null, ...partial,
});

/** A Pain-Point-shaped grid: a title for context, then a closed priority, three score levels, a flag and a date. */
export function buildGrid(overrides: Partial<RecordGridData> = {}): RecordGridData {
  const rows: GridRow[] = [
    { id: "r1", code: "PNP-001", read_only: null, locks: {}, project_id: "project-1", cells: { title: "Slow reports", priority: "Medium", severity: "", frequency: "", confidence: "", is_intentional: "false", date_identified: "2026-10-01" } },
    { id: "r2", code: "PNP-002", read_only: null, locks: {}, project_id: "project-1", cells: { title: "Lost sessions", priority: "High", severity: "Major", frequency: "Frequent", confidence: "Medium", is_intentional: "true", date_identified: "" } },
    {
      id: "r3", code: "PNP-003", read_only: null, project_id: "project-1", cells: { title: "Per persona", priority: "Low", severity: "", frequency: "", confidence: "", is_intentional: "false", date_identified: "" },
      locks: { severity: "This Pain Point is scored per persona; edit its scores on the Pain Point page.", frequency: "Scored per persona.", confidence: "Scored per persona." },
    },
    { id: "r4", code: "PNP-004", project_id: "project-1", read_only: "This Pain Point has reached a terminal outcome; its content can no longer be edited.", locks: {}, cells: { title: "Closed one", priority: "Low", severity: "Minor", frequency: "Rare", confidence: "Low", is_intentional: "false", date_identified: "" } },
  ];
  return {
    label: "Pain points",
    columns: [
      gridColumn({ key: "title", label: "Title", required: true }),
      gridColumn({ key: "priority", label: "Priority", kind: "enum", editable: true, required: true, choices: ["Low", "Medium", "High"] }),
      gridColumn({ key: "severity", label: "Severity", kind: "enum", editable: true, choices: ["Cosmetic", "Minor", "Moderate", "Major", "Blocker"] }),
      gridColumn({ key: "frequency", label: "Frequency", kind: "enum", editable: true, choices: ["Rare", "Occasional", "Frequent", "Constant"] }),
      gridColumn({ key: "confidence", label: "Confidence", kind: "enum", editable: true, choices: ["Low", "Medium", "High"] }),
      gridColumn({ key: "is_intentional", label: "Intentional", kind: "bool", editable: true }),
      gridColumn({ key: "date_identified", label: "Date identified", kind: "date", editable: true }),
      gridColumn({ key: "status", label: "Status", kind: "enum" }),
    ],
    rows, total: rows.length, truncated: false, max_rows: 500, can_edit: true, omitted_sensitivity: [], ...overrides,
  };
}
