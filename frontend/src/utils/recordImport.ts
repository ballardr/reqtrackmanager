/**
 * Module: utils/recordImport
 *
 * The pure steps of the record import wizard: guessing which of the person's CSV headers is which column, and
 * rebuilding the file in the server's own header names (with any "same value for every row" columns), so the
 * server only ever receives the one canonical format an export writes. Kept free of React so the rules are
 * unit-testable.
 */
import Papa from "papaparse";

import type { RecordColumn } from "../api/recordTables";

/** The reserved first column that names the record an import row updates (blank creates). */
export const CODE_COLUMN_KEY = "code";

/** Where one server column's values come from: a header of the file, or one fixed value for every row. */
export type ColumnSource = { kind: "header"; header: string } | { kind: "fixed"; value: string };

/** A header as compared for matching: lower case with spaces, underscores and hyphens removed. */
function squash(text: string): string {
  return text.trim().toLowerCase().replace(/[\s_-]/g, "");
}

/**
 * Pairs each server column with the file header that names it: the exact key or label first (ignoring case), then
 * the same with spaces, underscores and hyphens removed. A header is used for one column only.
 *
 * @param headers The file's headers.
 * @param keys The server columns, each `{key, label}` (include the `code` column).
 * @returns `{column key: header}` for the columns that found one.
 */
export function guessMapping(headers: string[], keys: { key: string; label: string }[]): Record<string, string> {
  const mapping: Record<string, string> = {};
  const taken = new Set<string>();
  const pick = (matches: (header: string) => boolean): string | undefined =>
    headers.find((header) => !taken.has(header) && matches(header));
  for (const { key, label } of keys) {
    const found =
      pick((h) => h.trim().toLowerCase() === key.toLowerCase() || h.trim().toLowerCase() === label.toLowerCase()) ??
      pick((h) => squash(h) === squash(key) || squash(h) === squash(label));
    if (found !== undefined) {
      mapping[key] = found;
      taken.add(found);
    }
  }
  return mapping;
}

/**
 * Whether a create from this file can succeed: the file names the record (a `code` column) or every column a
 * new record needs has a source.
 *
 * @param columns The importable, policy-included columns, with `code` first.
 * @param sources Where each column's values come from.
 * @returns The labels of the required columns that still lack a source and that block the import; empty when it may go on.
 */
export function missingRequired(columns: RecordColumn[], sources: Record<string, ColumnSource | undefined>): string[] {
  if (sources[CODE_COLUMN_KEY]) return [];
  return columns.filter((c) => c.required && !sources[c.key]).map((c) => c.label);
}

/**
 * Rebuilds the person's file in the server's headers.
 *
 * Only columns with a source are written; a column left out stays out, so the server leaves that field alone on an
 * update. A fixed value is written on every row.
 *
 * @param rows The parsed rows, keyed by the file's headers.
 * @param columns The columns to write, in order.
 * @param sources Where each column's values come from.
 * @returns CSV text with the server's column keys as its header.
 */
export function buildImportCsv(
  rows: Record<string, string>[],
  columns: Pick<RecordColumn, "key">[],
  sources: Record<string, ColumnSource | undefined>,
): string {
  const used = columns.filter((c) => sources[c.key]);
  const data = rows.map((row) =>
    used.map((c) => {
      const source = sources[c.key]!;
      return source.kind === "fixed" ? source.value : row[source.header] ?? "";
    }),
  );
  return Papa.unparse({ fields: used.map((c) => c.key), data });
}

/** The header row of an import template: the importable columns, `code` first (left blank to create). */
export function templateCsv(columns: Pick<RecordColumn, "key">[]): string {
  return Papa.unparse({ fields: columns.map((c) => c.key), data: [] });
}
