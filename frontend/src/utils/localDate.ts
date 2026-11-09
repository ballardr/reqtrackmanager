/**
 * Module: utils/localDate
 *
 * The viewer's calendar day. A date a person types or sees ("today") is their local day, which differs
 * from the UTC day for part of every day outside UTC; `localToday()` is the one place that is worked out
 * (the API client sends it as `X-Client-Date` so the server's "has this happened yet" rules agree with it).
 */

/** Today as `YYYY-MM-DD` in the viewer's timezone. */
export function localToday(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * A calendar date a person chose, shown as that same day in a long local format ("1 December 2026"). The date has
 * no time or timezone, so it is built from its parts rather than parsed as a UTC instant, which would shift it a day
 * west of Greenwich.
 *
 * @param value `YYYY-MM-DD`.
 * @returns The formatted day, or `value` unchanged when it is not a date.
 */
export function formatPlainDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])).toLocaleDateString(undefined, { dateStyle: "long" });
}

/**
 * The two UTC instants that bound a window of the viewer's own calendar days, for a filter on a time that has
 * already happened (an upload time is stored in UTC). The start is the first moment of `from`'s local day and the end
 * is the first moment of the local day after `to`, so both days are wholly included and the end is exclusive.
 *
 * @param from First local day, `YYYY-MM-DD`, or "" for no start.
 * @param to Last local day, `YYYY-MM-DD`, or "" for no end.
 * @returns ISO 8601 instants ending in `Z`; a side with no day is absent.
 */
export function localDayWindow(from: string, to: string): { from?: string; before?: string } {
  const localMidnight = (day: string, plusDays: number): string | undefined => {
    const [year, month, date] = day.split("-").map(Number);
    if (!year || !month || !date) return undefined;
    return new Date(year, month - 1, date + plusDays).toISOString();
  };
  return { from: from ? localMidnight(from, 0) : undefined, before: to ? localMidnight(to, 1) : undefined };
}
