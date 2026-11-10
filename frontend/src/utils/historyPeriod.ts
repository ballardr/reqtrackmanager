/**
 * Module: utils/historyPeriod
 *
 * The time range of the project History page, from a preset or a custom pair of date-times, as the UTC instants
 * the API takes. A person's range is their own wall-clock time: a `datetime-local` value or the start of their
 * local day, converted to an instant here in the browser, never on the server (docs/decisions.md, "Time and
 * Dates": a past instant is stored and sent in UTC, and only browsers convert to and from local time).
 *
 * Responsibilities:
 * - `periodRange`: the `since` and `until` instants of a preset or custom range.
 * - `localInputToInstant`: one `datetime-local` value as an instant, optionally the last millisecond of its minute.
 *
 * Design decisions:
 * - The upper bound of a custom range is the **end** of the chosen minute: the input has minute precision, so
 *   a bound written as 17:00 would otherwise hide an event at 17:00:30 that the person plainly meant to include.
 * - A preset counts local calendar days: "Last 7 days" starts at 00:00 six days ago, so a daylight-saving change
 *   inside the range moves no event in or out by an hour.
 */

export type PeriodKey = "today" | "week" | "month" | "custom";

export const PERIOD_KEYS: readonly PeriodKey[] = ["today", "week", "month", "custom"];

/** The UTC instants (ISO 8601) of a range; a missing bound is open. */
export interface PeriodRange {
  since?: string;
  until?: string;
}

const MS_PER_MINUTE = 60_000;

/**
 * One `datetime-local` value (`2026-11-05T09:00`) as an instant.
 *
 * @param value The input's value, read as the person's local time.
 * @param endOfMinute Return the last millisecond of that minute instead of its start (an upper bound).
 * @returns The ISO 8601 UTC instant, or `null` for an empty or invalid value.
 */
export function localInputToInstant(value: string, endOfMinute = false): string | null {
  if (!value) return null;
  const start = new Date(value);
  if (Number.isNaN(start.getTime())) return null;
  return new Date(start.getTime() + (endOfMinute ? MS_PER_MINUTE - 1 : 0)).toISOString();
}

/** 00:00 local time `daysBack` calendar days before `now`'s day. */
function startOfLocalDay(now: Date, daysBack: number): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysBack, 0, 0, 0, 0);
}

/**
 * The range of a period.
 *
 * @param period The preset, `custom`, or `""` for any time.
 * @param customSince / customUntil The custom range's `datetime-local` values (used for `custom` only).
 * @param now The current time (a parameter so a test can fix it).
 * @returns The `since` and `until` instants; any time has neither.
 */
export function periodRange(period: PeriodKey | "", customSince: string, customUntil: string, now: Date = new Date()): PeriodRange {
  const range: PeriodRange = {};
  if (period === "today") range.since = startOfLocalDay(now, 0).toISOString();
  else if (period === "week") range.since = startOfLocalDay(now, 6).toISOString();
  else if (period === "month") range.since = startOfLocalDay(now, 29).toISOString();
  else if (period === "custom") {
    const since = localInputToInstant(customSince);
    const until = localInputToInstant(customUntil, true);
    if (since) range.since = since;
    if (until) range.until = until;
  }
  return range;
}
