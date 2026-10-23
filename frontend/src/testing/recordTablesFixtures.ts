/**
 * Module: testing/recordTablesFixtures
 *
 * Story fixtures for the shared list actions: a requirement-shaped table definition and a fake
 * `RecordTablesApi` whose calls are spies, so a story can drive the Export menu and the Import wizard with no network.
 */
import { fn, type Mock } from "storybook/test";

import type {
  RecordColumn,
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
    exportCsv: fn(async () => new Blob(["code,name\n"], { type: "text/csv" })),
    importFile: fn(async () => buildImportResult()),
    ...overrides,
  };
}
