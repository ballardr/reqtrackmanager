/**
 * Module: utils/recordTotals
 *
 * Shapes the overview's per-type record counts for the donut chart: the largest types keep a slice of their
 * own and the rest fold into one "Other" slice, so a project with many modules on stays readable while the
 * legend still lists every type with its exact count.
 */
import type { RecordTypeCount } from "../api/types";

/** The most slices that name a record type; any further types share the "Other" slice. */
export const MAX_TYPE_SLICES = 7;

/** The slice colours in order: seven for record types, the last (muted) for "Other". Theme variables, so light and dark both work. */
export const RECORD_SLICE_COLORS = [
  "var(--color-primary)",
  "var(--color-accent)",
  "var(--color-warning)",
  "var(--color-danger)",
  "var(--color-info)",
  "var(--color-entity-requirement)",
  "var(--color-entity-change-request)",
  "var(--color-text-muted)",
];

export interface RecordTotalsChart {
  /** `[label, count]` per slice, in colour order. */
  segments: Array<[string, number]>;
  /** One row per record type, pointing at the slice it is drawn in. */
  legend: Array<{ type: string; label: string; count: number; segment: number }>;
  /** The record type a slice stands for, or `null` for the "Other" slice (several types). */
  segmentTypes: Array<string | null>;
}

/**
 * Builds the chart data for `counts` (largest first, as the API returns them).
 *
 * @param counts The overview's `records_by_type`.
 * @param otherLabel The caption of the folded slice.
 * @param maxTypeSlices How many types get their own slice; a remainder of exactly one type keeps its own slice.
 */
export function buildRecordTotalsChart(
  counts: RecordTypeCount[], otherLabel: string, maxTypeSlices: number = MAX_TYPE_SLICES,
): RecordTotalsChart {
  const folded = counts.length > maxTypeSlices + 1;
  const named = folded ? counts.slice(0, maxTypeSlices) : counts;
  const rest = folded ? counts.slice(maxTypeSlices) : [];
  const segments: Array<[string, number]> = named.map((c) => [c.label, c.count]);
  const segmentTypes: Array<string | null> = named.map((c) => c.type);
  if (rest.length > 0) {
    segments.push([otherLabel, rest.reduce((sum, c) => sum + c.count, 0)]);
    segmentTypes.push(null);
  }
  const legend = counts.map((c, idx) => ({
    type: c.type, label: c.label, count: c.count, segment: idx < named.length ? idx : named.length,
  }));
  return { segments, legend, segmentTypes };
}
